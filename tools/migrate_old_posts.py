#!/usr/bin/env python3
"""把旧站编译产物里的 9 篇文章还原成 Hexo Markdown 源码。

旧仓库只有 hexo generate 之后的 public/，没有 source/。这个脚本：
  1. 从 <article id="article-container"> 抽正文
  2. highlight.js 代码块还原成围栏代码块（丢掉行号 gutter）
  3. 失效图床图片删掉，按位置替换成本地 SVG 示意图
  4. 加 front-matter，并给当年没写完的几篇补「2026 补记」+ 可运行代码

用法：python3 tools/migrate_old_posts.py /path/to/old/public
"""
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify as md

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "source" / "_posts"
OUT.mkdir(parents=True, exist_ok=True)

DIAGRAM_NOTE = {
    "docker-architecture.svg": "Docker 组件关系（2026 重绘）",
    "kafka-architecture.svg": "Kafka 拓扑：Producer / Broker / Consumer Group",
    "kafka-log-anatomy.svg": "Partition 日志与 offset",
    "kafka-consumer.svg": "消费组内分区分配",
    "hadoop-ecosystem.svg": "大数据技术栈分层",
    "spring-stream-binders.svg": "Spring Cloud Stream Binder 模型",
    "es-inverted-index.svg": "倒排索引结构",
    "kafka-windows.svg": "Windows 本地启动 Kafka 的顺序",
    "jdk-timeline.svg": "JDK 8 → 17 关键特性",
    "threadpool-flow.svg": "ThreadPoolExecutor 任务调度",
    "dp-state-grid.svg": "动态规划状态表",
}

POSTS = [
    {
        "src": "2021/01/11/Docker入门学习/index.html",
        "file": "Docker入门学习.md",
        "title": "Docker 学习笔记",
        "date": "2021-01-11",
        "cat": "中间件",
        "tags": ["Docker", "容器"],
        "diagrams": ["docker-architecture.svg"],
        "lead": "2021 年从 yum 装 Docker 开始记的笔记，命令留着没动，配图重画了。",
        "note": """## 2026 补记：现在怎么装

上面那些 `yum-config-manager` 步骤我 2023 年之后就没再用过。本地起中间件一律走 Compose，一条命令完事，也不污染宿主机：

```yaml
# compose.yaml
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: devonly
    ports: ["5432:5432"]
```

```bash
docker compose up -d
docker compose logs -f redis
```

两个当年没写清楚、后来被坑过的点：

- `ports` 和 `expose` 不是一回事：前者是宿主机端口映射，后者只在容器网络内可见。
- 容器里默认 UTC，日志对不上业务时间时别急着改代码，先挂 `/etc/localtime` 或者设 `TZ`。
""",
    },
    {
        "src": "2021/01/13/Kafka入门学习(一)/index.html",
        "file": "Kafka入门学习(一).md",
        "title": "Kafka 学习笔记（一）",
        "date": "2021-01-13",
        "cat": "中间件",
        "tags": ["Kafka", "消息队列"],
        "diagrams": ["kafka-architecture.svg", "kafka-log-anatomy.svg", "kafka-consumer.svg"],
        "lead": "Kafka 的拓扑、日志结构和消费组，原文配图来自已关闭的 kafka.apachecn.org。",
        "note": """## 2026 补记

原文的图全来自 `kafka.apachecn.org`，那个站已经关了，上面换成了我自己画的矢量图。三年里最大的变化是 ZooKeeper 下线：Kafka 3.3 起 KRaft 可用，4.0 直接移除 ZK 模式，本地单节点不用再开两个进程。

消费者那边我后来统一换了 cooperative sticky 分配器，并改成手动提交：

```java
// 原生 consumer 配置；Spring Kafka 里对应 ConcurrentKafkaListenerContainerFactory
Map<String, Object> props = new HashMap<>();
props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");
props.put(ConsumerConfig.GROUP_ID_CONFIG, "stock-svc");
props.put(ConsumerConfig.PARTITION_ASSIGNMENT_STRATEGY_CONFIG,
        List.of(CooperativeStickyAssignor.class.getName()));
props.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, false);
props.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG, 200);
props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
```

`MAX_POLL_RECORDS` 别一上来就调大。我有一次调到 2000，单批次处理超过 `max.poll.interval.ms`，触发 rebalance，整组反复重平衡，吞吐反而掉了一半。
""",
    },
    {
        "src": "2021/01/28/大数据入门学习/index.html",
        "file": "大数据入门学习.md",
        "title": "大数据入门学习（一）",
        "date": "2021-01-28",
        "cat": "中间件",
        "tags": ["Hadoop", "大数据"],
        "diagrams": ["hadoop-ecosystem.svg"],
        "lead": "当年把 Hadoop 全家桶列了个遍，四张知乎图现在全挂了。",
        "note": """## 2026 补记

四张知乎图都挂了，合并成一张分层图。当年这篇把组件列了个遍，现在回头看有点本末倒置：绝大多数业务的数据量，单机 PostgreSQL 加个分区表就够；真到需要列式扫描再上 ClickHouse，没必要一上来就搭 HDFS。

后来我给自己定的判断顺序是：数据量 → 查询延迟要求 → 一致性要求 → 才轮到选组件。反过来做，通常就是给自己找了个运维负担。
""",
    },
    {
        "src": "2021/03/13/Dynamic Programming/index.html",
        "file": "Dynamic Programming.md",
        "title": "四大算法 -- 动态规划",
        "date": "2021-03-13",
        "cat": "随笔",
        "tags": ["算法", "动态规划"],
        "diagrams": ["dp-state-grid.svg"],
        "lead": "当年只列了思路没给完整实现，这次补一段能 javac 直接跑的。",
        "note": """## 2026 补记：补一段能跑的

原文写得太空，只有思路没有完整实现。补一个 0/1 背包，`javac Knapsack.java && java Knapsack` 就能跑：

```java
import java.util.Arrays;

public class Knapsack {
    // dp[w]：容量 w 时能拿到的最大价值
    public static int solve(int[] weight, int[] value, int capacity) {
        int[] dp = new int[capacity + 1];
        for (int i = 0; i < weight.length; i++) {
            // 必须倒序遍历；正序会把同一件物品重复放进去，变成完全背包
            for (int w = capacity; w >= weight[i]; w--) {
                dp[w] = Math.max(dp[w], dp[w - weight[i]] + value[i]);
                System.out.println("i=" + i + " " + Arrays.toString(dp));
            }
        }
        return dp[capacity];
    }

    public static void main(String[] args) {
        int[] w = {2, 3, 4, 5};
        int[] v = {3, 4, 5, 6};
        System.out.println("answer=" + solve(w, v, 8)); // 10
    }
}
```

那行 `println` 是我调试状态表的习惯，正式提交时会删掉，留在这里是因为「倒序遍历」光看公式很难体会，把表打出来一眼就明白。
""",
    },
    {
        "src": "2021/03/23/线程池与多线程取舍/index.html",
        "file": "线程池与多线程取舍.md",
        "title": "多线程，线程池",
        "date": "2021-03-23",
        "cat": "Java 开发",
        "tags": ["Java", "并发", "线程池"],
        "diagrams": ["threadpool-flow.svg"],
        "lead": "线程池参数怎么配、什么时候不该用池，2026 年补了虚拟线程的部分。",
        "note": """## 2026 补记：虚拟线程来了，池没消失

JDK 21 之后，IO 密集的那部分我改成虚拟线程了；CPU 密集和需要控制并发上限的场景仍然用平台线程池，两者不是替代关系：

```java
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.stream.IntStream;

public class VirtualThreadDemo {
    public static void main(String[] args) {
        HttpClient client = HttpClient.newHttpClient();
        HttpRequest request = HttpRequest.newBuilder(URI.create("https://example.com")).build();
        Semaphore limit = new Semaphore(64);   // 下游扛不住时用它限流，别靠固定大小的池

        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            IntStream.range(0, 100).forEach(i -> executor.submit(() -> {
                limit.acquireUninterruptibly();
                try {
                    return client.send(request, HttpResponse.BodyHandlers.ofString()).body().length();
                } catch (Exception e) {
                    return -1;
                } finally {
                    limit.release();
                }
            }));
        }
    }
}
```

一个值得记下来的坑：虚拟线程在 `synchronized` 块里遇到阻塞 IO 会 pin 住载体线程，JDK 21 不会自动卸载。当年为了线程安全加的一堆 `synchronized`，升级时得挨个看一遍，必要时换成 `ReentrantLock`。
""",
    },
    {
        "src": "2021/03/24/SpringStream入门教程学习(更新中）/index.html",
        "file": "SpringStream入门教程学习(更新中）.md",
        "title": "SpringStream 入门教程学习",
        "date": "2021-03-24",
        "cat": "中间件",
        "tags": ["Spring Boot", "Kafka", "消息队列"],
        "diagrams": ["spring-stream-binders.svg"],
        "lead": "2021 年只贴了一张图就搁那了，这次把没写完的部分补齐。",
        "note": """## 2026 补记：当年没写完的部分

这篇 2021 年只贴了一张图就停更了，那张图的路径还是 `D:\\HexoLearning\\...`，浏览器当然打不开。这次把内容补上。

Spring Cloud Stream 3.x 之后注解模型（`@StreamListener`）废弃了，推荐函数式模型。一个收订单消息、落库再发通知的例子：

```java
@Configuration
public class OrderFunctions {
    private static final Logger log = LoggerFactory.getLogger(OrderFunctions.class);
    private final OrderRepository repo;

    public OrderFunctions(OrderRepository repo) {
        this.repo = repo;
    }

    @Bean
    public Function<Flux<OrderEvent>, Flux<Notification>> processOrder() {
        return flux -> flux
            .doOnNext(e -> log.info("收到订单 {}", e.orderId()))
            .map(repo::save)
            .map(Notification::from);
    }
}
```

```yaml
spring:
  cloud:
    stream:
      bindings:
        processOrder-in-0:
          destination: order-events
          group: stock-svc
        processOrder-out-0:
          destination: order-notifications
      kafka:
        binder:
          brokers: localhost:9092
```

绑定名 `processOrder-in-0` 不能随便编，它是「函数名 + `-in-` + 参数序号」。写错了启动时**不会报错**，只是安静地收不到消息 —— 我当年就卡在这儿，盯了半天以为 broker 没通。

现在新项目我反而不太用这层抽象了：直接引 `spring-kafka`，代码量差不多，但排查问题时少一层 Binder 的黑盒。抽象层值不值，取决于你是不是真的会换 MQ；如果三年都没换过，它只是多了一个要读文档的地方。
""",
    },
    {
        "src": "2022/01/17/ElasticSearch学习手册/index.html",
        "file": "ElasticSearch学习手册.md",
        "title": "ElasticSearch 学习手册",
        "date": "2022-01-17",
        "cat": "中间件",
        "tags": ["ElasticSearch", "搜索"],
        "diagrams": ["es-inverted-index.svg"],
        "lead": "原文只有半页、配图也挂了，这次补 mapping 和深分页的实际写法。",
        "note": """## 2026 补记

原文只写了半页就断了，配图也挂了。补两段真正建索引时会用到的东西。

```json
PUT /books
{
  "mappings": {
    "properties": {
      "title":     { "type": "text", "fields": { "raw": { "type": "keyword" } } },
      "author":    { "type": "keyword" },
      "price":     { "type": "scaled_float", "scaling_factor": 100 },
      "published": { "type": "date", "format": "yyyy-MM-dd" }
    }
  }
}
```

`title.raw` 是给排序和聚合留的。text 类型默认没有 doc_values，直接拿它做 `terms` 聚合会报 `Fielddata is disabled on text fields by default` —— 这个报错我至少见过三次，每次都是新建索引时忘了加子字段。

深分页别用 `from + size` 翻到几千页，`search_after` 配 PIT 才稳：

```json
GET /books/_search
{
  "size": 20,
  "sort": [{ "published": "desc" }, { "_id": "asc" }],
  "search_after": ["2026-01-01", "book-1024"]
}
```

sort 里补 `_id` 不是洁癖：只按 `published` 排，遇到相同日期时翻页会漏数据或者重复。
""",
    },
    {
        "src": "2022/01/17/JDK8-JDK17个版本重要特性/index.html",
        "file": "JDK8-JDK17个版本重要特性.md",
        "title": "JDK8 - JDK17 各版本重要特性",
        "date": "2022-01-17",
        "cat": "Java 开发",
        "tags": ["Java", "JVM", "JDK"],
        "diagrams": ["jdk-timeline.svg"],
        "lead": "当年基本是 release note 摘抄，这次补几个真正在项目里用上的语法。",
        "note": """## 2026 补记

当年那篇是把每个版本的 release note 抄了一遍，没写代码。挑三个真正在项目里用上的：

```java
// record：DTO 不用再写 getter / equals / hashCode
public record BookDto(String isbn, String title, BigDecimal price) {}

// sealed：限制实现，配合 switch 模式匹配可以穷举，不用写 default
public sealed interface PayResult permits PaySuccess, PayFailed {}
public record PaySuccess(String tradeNo) implements PayResult {}
public record PayFailed(String code, String message) implements PayResult {}

public static String render(PayResult r) {
    return switch (r) {
        case PaySuccess s -> "支付成功：" + s.tradeNo();
        case PayFailed f  -> "支付失败：" + f.message();
    };
}
```

升级时真正花时间的不是语法，是 `javax.*` → `jakarta.*`，以及那些靠 `--add-opens` 撬开 JDK 内部 API 的老依赖。我的顺序一直是：先把依赖升到支持 17 的版本、跑通全量测试，再动语言特性。反过来做，出问题时分不清是依赖炸了还是新语法写错了。
""",
    },
    {
        "src": "2022/03/10/Kafka入门学习(一)/Kafkawindow环境适配/index.html",
        "file": "Kafkawindow环境适配.md",
        "title": "Kafka Windows 环境适配",
        "date": "2022-03-10",
        "cat": "中间件",
        "tags": ["Kafka", "Docker", "Windows"],
        "diagrams": ["kafka-windows.svg"],
        "lead": "六个 cmd 截图全没了，换成流程图；命令保留，另附现在用 KRaft 的起法。",
        "note": """## 2026 补记

六张 cmd 截图全失效了，合并成一张流程图。现在别在 Windows 上直接解压 Kafka 跑了，路径里的空格和 `.bat` 的换行符差异够折腾半天。KRaft 单节点用 Compose 起：

```yaml
services:
  kafka:
    image: apache/kafka:3.8.0
    ports: ["9092:9092"]
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
```

```bash
docker compose up -d
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh \\
  --bootstrap-server localhost:9092 --create --topic order-events --partitions 3
```

当年最容易撞上的两个报错：`NoSuchFileException` 多半是路径分隔符被当成转义，以及「输入行太长」是 CLASSPATH 拼接爆了。两个都不用改 Kafka，换环境就好。
""",
    },
]


def guess_lang(text):
    """旧站把 shell 命令也标成 plaintext，按内容补一个语言标签。"""
    t = text.lstrip()
    if re.match(r"^(\$|sudo|curl|docker|java|javac|brew|yum|apt|systemctl|cd |ls |cat |grep |git |npx|npm|mvn|gradle|kubectl|bin/|\./|Enable-|export |echo )", t):
        return "bash"
    if t.startswith("{") or t.startswith("["):
        return "json"
    if t.startswith("<"):
        return "xml"
    return ""


def extract_code(fig):
    """从 Butterfly 的 highlight.js 结构里还原纯代码文本。"""
    classes = fig.get("class", [])
    lang = next((c for c in classes if c != "highlight"), "")
    if lang in ("plaintext", "plain", "text", ""):
        lang = ""
    code_pre = fig.select_one(".code pre") or fig.find("pre")
    if not code_pre:
        return "", lang
    lines = code_pre.select(".line")
    if lines:
        text = "\n".join(ln.get_text() for ln in lines)
    else:
        for br in code_pre.find_all("br"):
            br.replace_with("\n")
        text = code_pre.get_text()
    text = text.rstrip()
    if not lang:
        lang = guess_lang(text)
    return text, lang


def convert(html_path, meta):
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    art = soup.find("article", id="article-container")
    if not art:
        raise RuntimeError(f"找不到正文容器: {html_path}")

    # 清掉主题塞进正文的组件
    for sel in ["script", "style", ".post-copyright", ".post-reward",
                ".relatedPosts", ".tag_share", ".post-share", ".ad-wrap"]:
        for el in art.select(sel):
            el.decompose()

    codes = []
    for fig in art.find_all("figure", class_=lambda c: c and "highlight" in c):
        text, lang = extract_code(fig)
        placeholder = f"CODEBLOCKPLACEHOLDER{len(codes)}END"
        codes.append((placeholder, text, lang))
        fig.replace_with(BeautifulSoup(f"<p>{placeholder}</p>", "html.parser").p)

    # 图片：按出现顺序映射到本地 SVG，多余的删掉（原文那些本来就是截图示意）
    imgs = [i for i in art.find_all("img")
            if not any(x in (i.get("src") or "") for x in ["friend_404", "inews.gtimg", "avatar"])]
    for idx, img in enumerate(imgs):
        if idx < len(meta["diagrams"]):
            name = meta["diagrams"][idx]
            new = BeautifulSoup(
                f'<p><img src="/images/diagrams/{name}" alt="{DIAGRAM_NOTE.get(name, name)}"></p>',
                "html.parser",
            ).p
            img.replace_with(new)
        else:
            img.decompose()

    body = md(str(art), heading_style="ATX", bullets="-")
    for placeholder, text, lang in codes:
        fence = f"\n\n```{lang}\n{text}\n```\n\n"
        body = body.replace(placeholder, fence)

    # 通用清理
    body = re.sub(r"\n[ \t]+\n", "\n\n", body)          # 纯空白行
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r"^# ", "## ", body, flags=re.M)      # 正文 h1 降级，页面标题才是唯一 h1
    body = re.sub(r"\[\s*\]\(#?[^)]*\)", "", body)      # 空的锚点链接
    # 中文 Kafka 镜像站已关站，正文里的文档链接换到官方
    body = re.sub(r"https?://kafka\.apachecn\.org/[^\s)]*",
                  "https://kafka.apache.org/documentation/", body)
    body = body.replace("\\_", "_").replace("\\*", "*")
    body = body.strip()

    # 原本没有图的文章，在开头插一张示意图
    if not imgs:
        name = meta["diagrams"][0]
        fig_md = f"![{DIAGRAM_NOTE.get(name, name)}](/images/diagrams/{name})\n\n"
        body = fig_md + body

    notice = (
        "> 这篇写于 " + meta["date"][:4] + " 年。原站配图用的免费图床后来全挂了，"
        "这次改版把失效截图换成了本地 SVG 示意图，正文和命令保持原样，"
        "现在该怎么做放在文末「2026 补记」里。\n\n"
    )
    body = notice + body + "\n\n" + meta["note"].strip() + "\n"

    fm = [
        "---",
        "title: " + json.dumps(meta["title"], ensure_ascii=False),
        "date: " + meta["date"],
        "updated: 2026-11-10",
        "categories:",
        "  - " + meta["cat"],
        "tags:",
    ]
    fm += ["  - " + json.dumps(t, ensure_ascii=False) for t in meta["tags"]]
    fm += ["lead: " + json.dumps(meta["lead"], ensure_ascii=False), "---", ""]
    return "\n".join(fm) + body


def main():
    old = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "xiaokaizhenshaui.github.io"
    for meta in POSTS:
        src = old / meta["src"]
        if not src.exists():
            print(f"  SKIP (missing) {src}")
            continue
        text = convert(src, meta)
        (OUT / meta["file"]).write_text(text, encoding="utf-8")
        print(f"  {meta['file']:40s} {len(text):6d} chars")


if __name__ == "__main__":
    main()
