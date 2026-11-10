#!/usr/bin/env python3
"""生成站点里所有技术示意图 SVG。

旧博客的配图全部挂在已经跑路的免费图床上（i.loli.net / zhimg / apachecn ...），
与其去捞 2021 年的截图，不如按现在的文章重画成矢量图：不失效、能搜、能改、
风格也跟赛博终端主题统一。

用法：python3 tools/make_diagrams.py
输出：source/images/diagrams/*.svg
"""
from html import escape as E
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "source" / "images" / "diagrams"
OUT.mkdir(parents=True, exist_ok=True)

CYAN = "#45e0f5"
PINK = "#ff77c8"
PURPLE = "#a98bff"
GREEN = "#9ce884"
ORANGE = "#ffb86c"
TEXT = "#eef1ff"
MUTED = "#7b88b0"
BORDER = "#2a3352"


def head(title, sub, w=880, h=420, accent=CYAN):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="{E(title)}">
<defs>
<pattern id="g" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" stroke="#1e2740" stroke-width="1"/></pattern>
<marker id="ar" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto"><path d="M0 0 L8 3 L0 6 z" fill="{PURPLE}"/></marker>
</defs>
<rect width="{w}" height="{h}" fill="#0d1120"/>
<rect width="{w}" height="{h}" fill="url(#g)"/>
<rect x="12" y="12" width="{w-24}" height="{h-24}" rx="10" fill="none" stroke="{BORDER}" stroke-width="1.5"/>
<text x="30" y="42" font-family="ui-monospace,Menlo,monospace" font-size="13" fill="{accent}">FIG // {E(title)}</text>
<text x="30" y="63" font-family="PingFang SC,Microsoft YaHei,sans-serif" font-size="12" fill="{MUTED}">{E(sub)}</text>
<line x1="30" y1="76" x2="{w-30}" y2="76" stroke="{BORDER}" stroke-width="1"/>
'''


def box(x, y, w, h, title, accent=CYAN, sub="", fs=15):
    s = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#121728" '
         f'stroke="{accent}" stroke-width="1.6"/>\n'
         f'<text x="{x+w/2}" y="{y+h/2+(0 if sub else 5)}" text-anchor="middle" '
         f'font-family="PingFang SC,Microsoft YaHei,sans-serif" font-size="{fs}" '
         f'fill="{TEXT}">{E(title)}</text>')
    if sub:
        s += (f'\n<text x="{x+w/2}" y="{y+h/2+20}" text-anchor="middle" '
              f'font-family="ui-monospace,Menlo,monospace" font-size="11" '
              f'fill="{MUTED}">{E(sub)}</text>')
    return s


def arrow(x1, y1, x2, y2, label=""):
    s = (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{PURPLE}" '
         f'stroke-width="2" marker-end="url(#ar)"/>')
    if label:
        s += (f'\n<text x="{(x1+x2)/2}" y="{(y1+y2)/2-8}" text-anchor="middle" '
              f'font-family="ui-monospace,Menlo,monospace" font-size="11" '
              f'fill="{PURPLE}">{E(label)}</text>')
    return s


def note(x, y, txt, color=MUTED, size=12):
    return (f'<text x="{x}" y="{y}" font-family="PingFang SC,Microsoft YaHei,sans-serif" '
            f'font-size="{size}" fill="{color}">{E(txt)}</text>')


def save(name, body):
    p = OUT / name
    p.write_text(body + "</svg>\n", encoding="utf-8")
    print(f"  {name:32s} {p.stat().st_size/1024:5.1f} KB")


def main():
    # 1. Docker
    s = head("Docker 架构", "Client / Daemon / Image / Container / Registry 的关系（重绘于 2026，替换失效的 2021 年截图）", 880, 400)
    s += box(40, 120, 180, 80, "Docker CLI", CYAN, "docker build / run / pull")
    s += box(330, 110, 220, 100, "Docker Daemon", PURPLE, "dockerd")
    s += box(660, 110, 180, 80, "Registry", PINK, "Docker Hub / 私有仓")
    s += box(300, 270, 160, 70, "Image", GREEN, "只读模板")
    s += box(520, 270, 160, 70, "Container", GREEN, "可写层 + 进程")
    s += arrow(220, 160, 330, 160, "REST API")
    s += arrow(550, 150, 660, 150, "pull / push")
    s += arrow(380, 210, 380, 270, "build")
    s += arrow(460, 305, 520, 305, "run")
    s += note(40, 368, "镜像是静态定义，容器是运行实例 —— 类与对象的关系")
    save("docker-architecture.svg", s)

    # 2. Kafka 拓扑
    s = head("Kafka 拓扑", "Producer → Broker(Topic/Partition) → Consumer Group", 880, 420)
    s += box(40, 140, 160, 80, "Producer", CYAN, "业务服务")
    s += box(300, 110, 280, 170, "Broker 集群", PURPLE, "Topic: order-events")
    s += box(320, 150, 110, 50, "P0", GREEN, "leader", 13)
    s += box(450, 150, 110, 50, "P1", GREEN, "leader", 13)
    s += box(320, 215, 110, 50, "P0-R", ORANGE, "replica", 13)
    s += box(450, 215, 110, 50, "P1-R", ORANGE, "replica", 13)
    s += box(680, 140, 160, 80, "Consumer", PINK, "Group: stock-svc")
    s += box(300, 320, 280, 50, "ZooKeeper / KRaft", MUTED, "元数据与控制器", 13)
    s += arrow(200, 180, 300, 180, "send")
    s += arrow(580, 180, 680, 180, "poll")
    s += arrow(440, 280, 440, 320, "metadata")
    s += note(40, 392, "分区数决定单 Topic 的并行上限；同组内一个分区只会被一个消费者占用")
    save("kafka-architecture.svg", s)

    # 3. Kafka 日志
    s = head("Partition 日志结构", "offset 单调递增、追加写、不可变", 880, 330)
    for i, off in enumerate(["0", "1", "2", "3", "4", "5", "…"]):
        s += box(50 + i * 112, 140, 96, 80, off, GREEN if i < 6 else MUTED, "record", 16)
    s += arrow(50, 250, 830, 250, "顺序追加 append-only")
    s += note(50, 290, "消费者持有的只是 offset 指针，重放 = 把指针往回拨；消息还在不在取决于 retention")
    save("kafka-log-anatomy.svg", s)

    # 4. 消费组
    s = head("Consumer Group 分区分配", "同一 group.id 内分区互斥；不同组互不影响", 880, 380)
    for i, p in enumerate(["P0", "P1", "P2", "P3"]):
        s += box(60 + i * 120, 130, 90, 60, p, GREEN, "", 16)
    for j, c in enumerate(["C1", "C2"]):
        s += box(250 + j * 260, 255, 150, 65, c, PINK, "group: stock-svc", 14)
    for x1, x2 in [(105, 325), (225, 325), (345, 585), (465, 585)]:
        s += arrow(x1, 190, x2, 255)
    s += note(60, 352, "消费者数量 > 分区数时，多出来的消费者会空转 —— 加机器不总是能提速")
    save("kafka-consumer.svg", s)

    # 5. 大数据生态
    s = head("大数据技术栈分层", "2021 年那篇笔记里贴的四张知乎图已失效，这里按层次重画", 880, 400)
    layers = [
        ("采集 / 同步", "Flume · Kafka · Sqoop · CDC", CYAN),
        ("存储", "HDFS · HBase · Hive · 对象存储", PURPLE),
        ("计算", "MapReduce · Spark · Flink", GREEN),
        ("服务 / 查询", "Presto · ClickHouse · Elasticsearch", PINK),
    ]
    for i, (t, d, c) in enumerate(layers):
        s += box(120, 110 + i * 66, 640, 54, t + "   |   " + d, c, "", 14)
    s += note(120, 378, "先想清楚数据量、延迟要求和一致性，再选组件；别反过来")
    save("hadoop-ecosystem.svg", s)

    # 6. Spring Cloud Stream
    s = head("Spring Cloud Stream Binder 模型", "业务代码只面向绑定接口，中间件差异交给 Binder", 880, 340)
    s += box(50, 140, 200, 80, "Application", CYAN, "@StreamListener / Function")
    s += box(340, 120, 220, 120, "Binder", PURPLE, "Kafka / RabbitMQ")
    s += box(660, 140, 170, 80, "Message Broker", PINK, "Topic / Exchange")
    s += arrow(250, 180, 340, 180, "Message<?>")
    s += arrow(560, 180, 660, 180, "bind")
    s += note(50, 300, "换 MQ 时改依赖和配置，不动业务代码 —— 前提是你没在业务里直接引 broker 客户端 API")
    save("spring-stream-binders.svg", s)

    # 7. ES 倒排索引
    s = head("Elasticsearch 倒排索引", "写入时分词建索引，查询时合并 posting list", 880, 380)
    s += box(50, 130, 220, 80, "文档 doc1", CYAN, '"Kafka 入门笔记"')
    s += box(50, 235, 220, 80, "文档 doc2", CYAN, '"Kafka 消费者组"')
    s += box(360, 120, 200, 200, "倒排索引", PURPLE, "term → docId list")
    s += box(660, 140, 170, 65, "kafka", GREEN, "[1, 2]", 14)
    s += box(660, 220, 170, 65, "消费者", GREEN, "[2]", 14)
    s += arrow(270, 170, 360, 170, "analyze")
    s += arrow(270, 275, 360, 275, "analyze")
    s += arrow(560, 200, 660, 175)
    s += arrow(560, 220, 660, 250)
    s += note(50, 350, "mapping 一旦建错（比如 text 该用 keyword），只能 reindex，别指望改个参数就好")
    save("es-inverted-index.svg", s)

    # 8. Windows 起 Kafka
    s = head("Windows 本地起 Kafka 的顺序", "原 6 张安装截图已失效，改成流程图；命令仍按原步骤", 880, 360)
    steps = [
        ("1", "zookeeper-server-start", CYAN),
        ("2", "kafka-server-start", PURPLE),
        ("3", "kafka-topics --create", GREEN),
        ("4", "producer / consumer", PINK),
    ]
    for i, (n, t, c) in enumerate(steps):
        x = 40 + i * 210
        s += box(x, 140, 185, 90, n + "  " + t.split("-")[0], c, t, 13)
        if i < 3:
            s += arrow(x + 185, 185, x + 210, 185)
    s += note(40, 290, "每一步都要单独开一个 cmd 窗口，关掉窗口就等于把服务杀了")
    s += note(40, 320, "2026 补记：现在直接用 KRaft 模式或 Docker Compose，不用再单独起 ZooKeeper")
    save("kafka-windows.svg", s)

    # 9. JDK 时间轴
    s = head("JDK 8 → 17 关键特性", "LTS 用绿色标出；升级时最容易被卡住的是移除项和模块系统", 880, 330)
    vers = [
        ("8", "Lambda / Stream", GREEN), ("9", "模块系统", MUTED),
        ("11", "HTTP Client / var", GREEN), ("14", "switch 表达式", MUTED),
        ("16", "record", MUTED), ("17", "sealed / 移除 Nashorn", GREEN),
    ]
    for i, (v, d, c) in enumerate(vers):
        s += box(40 + i * 140, 130, 120, 90, "JDK " + v, c, d, 13)
    s += f'<line x1="40" y1="250" x2="840" y2="250" stroke="{BORDER}" stroke-width="2"/>'
    s += note(40, 295, "从 8 直接跳 17：先处理 javax.* → jakarta.*、非法反射访问、以及 --add-opens")
    save("jdk-timeline.svg", s)

    # 10. 线程池
    s = head("ThreadPoolExecutor 任务调度", "核心线程 → 队列 → 最大线程 → 拒绝策略", 880, 350)
    s += box(30, 130, 150, 70, "提交任务", CYAN, "execute()")
    s += box(230, 130, 170, 70, "corePoolSize", GREEN, "未满则建线程")
    s += box(450, 130, 170, 70, "BlockingQueue", PURPLE, "核心满了先入队")
    s += box(670, 130, 170, 70, "maxPoolSize", ORANGE, "队列也满了才扩容")
    for x1, x2 in [(180, 230), (400, 450), (620, 670)]:
        s += arrow(x1, 165, x2, 165)
    s += box(670, 240, 170, 60, "RejectedExecutionHandler", PINK, "抛异常 / 丢弃 / 调用方跑", 12)
    s += arrow(755, 200, 755, 240)
    s += note(30, 290, "用无界队列时 maxPoolSize 基本不会生效 —— 这是最常见的「线程池参数配了没用」")
    save("threadpool-flow.svg", s)

    # 11. 动态规划
    s = head("动态规划：状态与转移", "把原问题拆成可复用的子问题，用表把中间结果存下来", 880, 340)
    for r in range(3):
        for c in range(5):
            x, y = 80 + c * 130, 120 + r * 60
            col = GREEN if (r, c) in [(0, 0), (2, 4)] else (CYAN if r == 2 else MUTED)
            s += (f'<rect x="{x}" y="{y}" width="106" height="46" rx="6" fill="#121728" '
                  f'stroke="{col}" stroke-width="1.4"/>\n'
                  f'<text x="{x+53}" y="{y+29}" text-anchor="middle" '
                  f'font-family="ui-monospace,Menlo,monospace" font-size="13" '
                  f'fill="{TEXT}">dp[{r}][{c}]</text>')
    s += arrow(660, 240, 720, 240)
    s += note(80, 315, "先定义状态含义，再写转移方程，最后才想怎么压缩空间；顺序反了基本会卡住")
    save("dp-state-grid.svg", s)


if __name__ == "__main__":
    main()
