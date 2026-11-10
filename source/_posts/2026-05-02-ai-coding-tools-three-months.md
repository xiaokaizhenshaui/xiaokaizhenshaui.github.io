---
title: "三个 AI 编码工具轮着用了 90 天，我把订阅退了两个"
date: 2026-05-02
categories:
  - AI 工具
tags:
  - AI 工具
  - 编码助手
  - 工程效率
lead: "90 天、412 个提交、三份订阅，最后只留了一份：赢的那个不是写得最准的，是唯一一个翻车时我看得见的。"
---

二月一号我把三款工具的订阅一次性开齐了，想法很朴素：同一个需求让它们各写一遍，谁写得好留谁。头两周其实只有 Cursor 在干活，另外两份纯吃灰。到五月二号早上退订了两个，只剩 Claude Code 还按月扣着。四月那篇月度末尾留了句「结论有点意外，留到 5 月那篇写」，就是这篇。留下它跟便宜没关系（三个里它不便宜），是因为另外两个在我最常干的两件事上翻车翻得太具体，具体到我能把报错和 diff 原样贴出来。

这九十天基本泡在线书店那套 API 上：Spring Boot 3.2.5 + JDK 21.0.4，GraphQL 层是 graphql-java，前端类型生成用 TypeScript 5.4.5，本地 Node 20.11.1。仓库不大，`git ls-files | wc -l` 是 218 个文件，但 Java 和 TS 混着，还夹了一堆手写 SQL，正好够折腾。

## 一开始想一个工具全包，两周就放弃了

第一版只开 Cursor，图省事，所有活儿都往里塞。按任务拆开看，其实差别特别大：

- **补全**：写 GraphQL resolver 的样板、DTO 的 getter、JUnit 参数化测试的模板，这种敲几个字符就能猜到下一行的活儿，Copilot 最跟手，Cursor 慢半拍。
- **改重构**：四月那次把 `Book.price` 从 `int` 换成 `Money` 值对象，要动 11 个 Java 文件、2 处 SQL，再重新生成 TS 类型。Cursor 一轮只改了 3 个文件，剩下 8 个我手动补到半夜。
- **读陌生代码**：接手 `promotion` 包，四千行、零注释、没文档，靠 codebase 问答先摸出调用链，比我自己 `grep` 快，但这活儿只有能读全库的工具干得了。
- **写脚本**：一次性的统计、清洗，谁开着就用谁，不值得为它挑工具。

两周后我就改成按任务分工了：补全交给编辑器里的 Copilot，重构和读代码用 Claude Code（它在终端里，能读整个 repo 还能自己跑命令），Cursor 夹在中间，负责「在编辑器里顺手问一句」。所谓「一个工具全包」是我自己一厢情愿，工具之间根本不是替代关系。

## 三款摆一起比

| | Copilot | Cursor | Claude Code |
| --- | --- | --- | --- |
| 补全响应 | 敲 4 个字符就弹，最跟手 | 要等小半秒 | 没有补全，终端里干活 |
| 11 文件那次重构 | 只动当前文件 | 改对 6 个 | 11 个全改完，还自己跑了 `mvn test` |
| 长会话 | 无所谓，本来就短 | 第 30 轮起开始动没让动的文件 | 靠 CLAUDE.md 兜着，撑到 60 轮还行 |
| 陌生代码 | 基本靠猜 | 能索引全库 | 能读、能 grep、能跑命令验证 |
| 90 天提交数 | 22 | 61 | 88 |
| 五月二号之后 | 退订 | 退订 | 留着 |

补全响应那两格是我掐着表抓了十来次的不严谨数字，别当 benchmark 看。真决定去留的是第 2 行和第 3 行。

## CLAUDE.md 我改了四版

一开始啥也没配，生成的代码 import 了 `javax.validation.constraints.NotNull`——Spring Boot 3 早就是 `jakarta.*` 了；分页参数写成 `page/size`，我们全项目统一 `offset/limit`；还有一次给它加状态枚举，它把中文塞了进去（下面细说）。这些都不是能力问题，是它不知道我这个仓库的规矩。

第四版长这样，放在仓库根目录：

```markdown
# 项目约定（改代码前先读）

## 技术栈
- Java 21（JDK 21.0.4），Spring Boot 3.2.5，Maven；用 jakarta.*，别用 javax.*
- GraphQL 用 graphql-java，schema 在 src/main/resources/graphql/*.graphqls
- 改完 schema 要跑 `npm run codegen` 重新生成 web/src/generated/graphql.ts

## 硬规矩
- 枚举常量、GraphQL enum value、DTO 字段名一律英文；给用户看的中文文案放
  messages_zh_CN.properties，不许塞进 enum
- 分页参数统一叫 offset / limit，不用 page / size
- 不许改 pom.xml、application.yml、CI 配置，除非我明确说要改
- 每次改完跑 `mvn -q -DskipTests compile` 和 `mvn -q test`，编译不过别把代码留着

## 提交
- 提交信息末尾加一行 `Assisted-by: <工具名>`，一行就够
```

写完这版，前面那些低级错基本没再出现。至于「不许改 pom.xml」那条有没有管用，往下看。

## 三次翻车，两次是我自己没兜住

**一、生成的代码编译不过。** 让它给 `BookResolver` 加一个按 ISBN 模糊查的方法，它照着 Spring Data 的习惯猜了个仓库方法名：

```text
$ mvn -q -DskipTests compile
[ERROR] COMPILATION ERROR :
[ERROR] .../BookResolver.java:[47,36] cannot find symbol
[ERROR]   symbol:   method findByIsbnContainingIgnoreCase(java.lang.String)
[ERROR]   location: variable bookRepository of type com.youngcerulean.bookstore.repo.BookRepository
[ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin:3.11.0:compile
[ERROR] -> [Help 1]
```

我那个 `BookRepository` 是手写的，方法叫 `findByIsbnContains`，没有派生查询那套命名。当时图快没本地编译就 commit 了，CI 拦下来的。这条我认，是没兜住——现在 CLAUDE.md 里那两行 `mvn` 就是为它加的。

**二、上下文一长就开始胡改文件。** 三月底那次和 Cursor 聊到第三十多轮，我只让它改 `BookStatus` 到 GraphQL 枚举的映射。结果 `git diff` 里多出两处：它把 `application.yml` 里的 `spring.threads.virtual.enabled: true` 删了（那是我四月刚加的，见 04-04 那篇），还把 `pom.xml` 里 maven-surefire-plugin 从 3.2.5 降到 3.0.0，给的理由是「统一插件版本」。我根本没让它碰构建文件，那两行混在十几行正常改动里，盯了十分钟才看见。后来定死一条规矩：每轮结束先 `git diff --stat`，超过 3 个文件就停下来重看。

**三、中文文案进了 enum。** 让它给 `BookStatus` 加「在售 / 下架 / 预售」，它直接写成 `在售, 下架, 预售`。Java 编译居然过了（标识符允许中文），但 graphql-java 建 schema 时挂了，说 enum value 得匹配 `[_A-Za-z][_0-9A-Za-z]*`；更要命的是真让它过，`codegen` 生成的 TS 里会冒出中文的联合类型成员。改回 `ON_SALE / OFF_SHELF / PRE_ORDER`，中文挪到 `messages_zh_CN.properties`。这条当天就写进 CLAUDE.md 了。

> 顺带一提：这三次里只有第一次是「写错代码」，后两次都是「动了不该动的东西」。我后来才想明白，评估这类工具，看它写得对不对只占一半，另一半是看它改了哪些你没让它改的地方。

## 到底有多少提交是它们写的

从二月起我给提交加了一行 trailer，靠它认人：

```bash
# 提交时带一行标记
git commit -m "fix(book): 补上 BookStatus 的 GraphQL 枚举映射" \
  -m "Assisted-by: claude"

# 看最近十条里谁带过标记
git log -10 --pretty=format:'%h %s | %(trailers:key=Assisted-by,valueonly)'
```

一开始图省事写在标题里当 `[ai]` 前缀，被仓库的 commitlint hook 直接拦了（要求 `type(scope): subject`），才换成 trailer。统计脚本扫最近 90 天的 `%B`，按 trailer 分桶：

```python
#!/usr/bin/env python3
"""统计最近 90 天里带辅助标记（Assisted-by）的提交占比。"""
import subprocess
from collections import Counter
from datetime import datetime, timedelta

since = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
raw = subprocess.check_output(
    ["git", "log", f"--since={since}", "--pretty=format:%B%x1e"],
    text=True,
)

total = 0
by_tool = Counter()
for record in raw.split("\x1e"):
    body = record.strip().lower()
    if not body:
        continue
    total += 1
    for tool in ("cursor", "claude", "copilot"):
        if f"assisted-by: {tool}" in body:
            by_tool[tool] += 1
            break
    else:
        by_tool["hand-written"] += 1

print(f"统计区间: {since} 起，共 {total} 个提交")
for tool, n in by_tool.most_common():
    print(f"  {tool:12s} {n:4d}  {n / total * 100:5.1f}%")
```

五月二号跑出来的结果：

```text
统计区间: 2026-02-01 起，共 412 个提交
  hand-written   241  58.5%
  claude          88  21.4%
  cursor          61  14.8%
  copilot         22   5.3%
```

带标记的是 171 个，占 41.5%。但那个 58.5% 我不太信——复制粘贴改个字段名、调个日志级别这种，谁会老实加 trailer，手写那堆里肯定混了漏标的。真实比例只会更高，不会更低。

## 退了两个，留了一个

Copilot 退得最没悬念：它只在补全这一件事上赢，90 天 22 个提交，而补全这活儿编辑器自带和别的工具免费额度都能干，为它单独付一份不值。Cursor 退得有点犹豫，它是三款里交互最顺的，但跟 Claude Code 功能重叠太厉害，长会话那次之后我审 diff 的时间比自己写还长，就把它砍了。

留 Claude Code 不是因为它写得最准。它一样会编出 `findByIsbnContainingIgnoreCase` 这种东西。留它是因为它在终端里能读全库、能自己跑 `mvn test` 验证、11 文件那次重构真给我省了事，而且——出错时 `mvn compile` 的输出就摆在屏幕上，我看得见。Cursor 那种悄悄把 `application.yml` 改了、还附一条像模像样理由的，最吓人。

## 还没解决的

提交标记全靠自觉，漏标的没法补，上面那个 41.5% 只能当个下限看。长会话退化也没根治，我现在靠「聊到 30 轮就开新会话」加 `git diff --stat` 硬扛，纯土办法。

最卡我的是另一件事：CLAUDE.md 里白纸黑字写了「不许改 pom.xml、application.yml」，那次它还是改了。我把这句话挪到文件最前面、加粗、连写三遍，都没挡住。下一步想试试把检查挂成 hook——这轮 diff 里一旦出现 `pom.xml` 或 `application.yml` 就直接拒掉、让我手动确认，而不是等我发现。还没动手，拿不准会不会把正常的依赖升级也一起拦下来。等试完再写。
