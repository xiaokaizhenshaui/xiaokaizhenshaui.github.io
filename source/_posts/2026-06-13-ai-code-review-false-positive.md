---
title: "让三个 AI 工具 review 同一个 PR，误报比真 bug 多"
date: 2026-06-13
categories:
  - AI 工具
tags:
  - AI 工具
  - Code Review
  - 工程化
lead: "300 行的 PR 收了 47 条建议，最后采纳 6 条，其中三个工具都盯着同一段空值判断不放。"
---

6 月 11 号晚上 22:40 我提了 PR #482，想赶在周五前合掉。第二天早上 9 点打开 GitHub，合并按钮是灰的：

```bash
$ gh pr checks 482
NAME                                STATE  ELAPSED  URL
ai-review / review (pull_request)   fail   2m 14s   https://github.com/.../actions/runs/...

Merging is blocked: 1 check failed
```

那条 check 的日志里没有编译错误，也没有测试失败，只有 21 条 review 建议——其中 16 条是错的。第一版我把 PR 上的 bot 直接设成了 branch protection 的 required check，等于让一个误报率八成的东西卡住了合并，后面还排了三个等发布的 PR。当天上午我就把它从 required 里摘了，这是后话。

PR 本身不大，`git diff --stat main...HEAD` 是 `18 files changed, 312 insertions(+), 87 deletions(-)`，给在线书店的 `bookSearch` resolver 加游标分页，顺带把热门关键词的查询结果塞进 Redis。环境是 Node 20.11.1 + TypeScript 5.4.5 + Apollo Server 4，schema 是 SDL-first 手写的。312 行里差不多一半是测试。

我手上有三个能 review 的东西：Cursor 的 Agent（本地把 diff 喂进去）、PR 上装的一个 review bot、还有我年初拿模型 SDK 写的一个小 CLI，输出 JSON 到 stdout。三个都跑一遍，本来是想看哪个更准，结果先被数量砸了。

## 47 条建议，最后采纳 6 条

三个工具的输出我按文件加行号手工过了一遍，标成「采纳 / 误报 / 存疑」三种，存疑是那种「说得有点道理但这次不想改」的。

| 工具 | 建议 | 采纳 | 误报 | 存疑 |
| --- | --- | --- | --- | --- |
| Cursor Agent | 19 | 2 | 15 | 2 |
| PR review bot | 21 | 3 | 16 | 2 |
| 自写 CLI | 7 | 1 | 5 | 1 |
| 合计 | 47 | 6 | 36 | 5 |

47 条里采纳 6 条，12.8%。唯一让我没直接把三个工具全关掉的是那 6 条里有一条是真 bug：分页游标在 `title` 相同时会重复返回同一本书，`ORDER BY title, id` 里我漏了把 `id` 拼进游标。三个工具里只有 bot 报了，还夹在两条空值判断中间，差点被我一起划掉。

顺带一提，三个工具都报了同一段 `book.isbn` 的空值判断，措辞都差不多，一度让我以为是真的，翻了 schema 才发现是 `String!`。三个一起错，比一个错更容易骗到人。

## 误报全挤在这三处

36 条误报归类之后，分布特别集中：

| 类型 | 条数 | 典型说法 |
| --- | --- | --- |
| 空值判断 | 14 | 「`book.isbn` 可能为 null，建议加 `?.`」 |
| 并发 / 竞态 | 9 | 「缓存写入没加锁，多线程下会覆盖」 |
| 中文文案当 bug | 8 | 「错误信息应为英文 / 硬编码中文应抽 i18n」 |
| 命名与风格偏好 | 5 | 「`getBookById` 建议改名 `fetchBook`」 |

**空值判断**那 14 条里，11 条指向 schema 里带 `!` 的字段。SDL 写的是 `isbn: String!`，resolver 拿到的就保证非空，工具却按「外部输入不可信」的通用模板套。它只看了 diff 里的 TS 文件，看不到 `schema.graphql`——那几行恰好没改，不在 diff 里。这条后来成了写进约束的第一条。

**并发**那 9 条更离谱。我们跑的是 Node.js 单线程事件循环，`await redis.set(...)` 没有第二个线程来抢，工具却按「共享可变状态要加锁」来判。我怀疑是训练语料里 Java 代码太多。（我四月的笔记里那个订单服务确实是 Java 加虚拟线程，但那是另一个仓库，跟这里没关系。）

**中文文案**那 8 条最像不懂业务。错误信息 `库存不足，请稍后再试` 被建议改成英文，理由是「error messages should be ASCII」；`extensions.code` 我们特意用英文 enum、`message` 用中文给前端直接展示，它两边都想改。有一条把注释 `// 游标指向上一页最后一条` 判成「未翻译的用户可见字符串」，我盯着看了半天才确认它连注释和字符串都没分清。

bot 的原话长这样，行号 88 就是那段 `normalizeIsbn`：

```json
{
  "path": "src/resolvers/bookSearch.ts",
  "line": 88,
  "severity": "warning",
  "category": "null-safety",
  "title": "可能的空指针",
  "body": "book.isbn 可能为 null，直接传给 normalizeIsbn() 会抛异常，建议使用 book?.isbn ?? ''。",
  "suggestion": "const isbn = book?.isbn ?? '';"
}
```

照它改反而会出事：`normalizeIsbn` 第一件事就是 `if (!isbn) throw new Error('isbn 不能为空')`，加个 `?? ''` 等于把校验绕过去，把本来会明确报错的输入变成空字符串继续往下走。

## 先把「条数」数对

统计脚本第一版我写得很偷懒：三个工具各吐一个 JSON 数组，直接 `sum(len(items) for f in files)`，算出 61 条，跟手工数的 47 对不上。查了半天是两件事：bot 对同一行会按「空值」和「可读性」各发一条；Cursor 的输出里混了 4 条「LGTM / 整体没问题」这种根本不算建议的总结。第一版把「条目」和「建议」当成一回事了。

第二版改成先滤噪声、再按 `(tool, path, line)` 去重，顺便统计跨工具重合的位置：

```python
#!/usr/bin/env python3
"""把三个 review 工具的输出合成一张统计表。只用标准库。
用法：python count_suggestions.py cursor.json bot.json cli.json
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

# 不算建议的总结性标题
NOISE_TITLES = {"LGTM", "整体没问题", "无阻塞问题", "Summary"}

def load(path: str) -> list[dict]:
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for it in items:
        if it.get("title", "").strip() in NOISE_TITLES:
            continue
        out.append({
            "path": it["path"],
            "line": int(it.get("line") or 0),
            "title": it["title"],
            "tool": Path(path).stem,   # cursor.json -> cursor
        })
    return out

def main(argv: list[str]) -> None:
    raw = []
    for p in argv[1:]:
        raw.extend(load(p))
    print(f"原始条目（含噪声）: {len(raw)}")

    # 同一个工具对同一行只保留一条
    seen: set[tuple[str, str, int]] = set()
    unique = []
    for it in raw:
        key = (it["tool"], it["path"], it["line"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)

    by_tool: dict[str, int] = defaultdict(int)
    for it in unique:
        by_tool[it["tool"]] += 1
    print(f"去重后建议: {len(unique)}")
    for tool, n in sorted(by_tool.items()):
        print(f"  {tool}: {n}")

    spots: dict[tuple[str, int], set[str]] = defaultdict(set)
    for it in unique:
        spots[(it["path"], it["line"])].add(it["tool"])
    overlap = sum(1 for v in spots.values() if len(v) >= 2)
    print(f"两个以上工具都报的位置: {overlap}")

if __name__ == "__main__":
    main(sys.argv)
```

跑出来是 `61 → 47`，分到各工具 `bot: 21 / cli: 7 / cursor: 19`，重合位置 9 个。9 个里就有那个三个工具一起报错的 `book.isbn`。

## 把项目约束塞进 .cursorrules 和 prompt

第一次改 prompt 我只加了一句「请只报告真正的 bug，不要报告风格问题」，拿同一个 diff 重跑：47 → 44，几乎没动。它不知道什么叫「真正的 bug」。（跟在提示词里写「只输出 JSON 不要解释」是一个道理，光靠祈使句拦不住，得给具体事实。）

后来改成把项目事实一条条列出来，写进仓库根目录的 `.cursorrules`，CLI 那边也从同一份文件读，不复制：

> - GraphQL schema 在 `src/schema/*.graphql`，带 `!` 的字段保证非空，不要建议加 `?.` 或空值判断。
> - resolver 跑在 Node.js 单线程事件循环里，不要套用多线程、加锁、竞态的建议。
> - `extensions.code` 用英文 enum，`message` 是中文且直接展示给前端，不要建议改英文或抽 i18n。
> - 注释里的中文不是用户可见字符串。
> - 不要评论命名、格式、import 顺序，这些归 ESLint / Prettier 管。
> - 只报告能在本地复现的问题；拿不准就别报。

前两条各砍掉十来条。第五条最难写，一开始写成「不要报风格问题」，没用，得点名归谁管它才停。`review_prompt.py` 里约束是从这份文件读进来的：

```python
#!/usr/bin/env python3
"""拼 review 的 messages。约束只放在 .cursorrules 里，别散到各个调用点。
用法：python review_prompt.py < diff.patch
"""
import json
import sys
from pathlib import Path

RULES = Path(__file__).with_name(".cursorrules").read_text(encoding="utf-8")

SYSTEM_PROMPT = f"""你在 review 一个 TypeScript + GraphQL 的在线书店 API。
下面的硬约束和它冲突的建议一律不要给：

{RULES}

输出要求：
- 只输出 JSON 数组，每个元素含 path、line、title、body 四个字段。
- 没有问题时输出空数组 []，不要写「整体没问题」之类的总结。
- title 和 body 用中文，代码标识符保持英文。
"""

def build_messages(diff: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "请 review 下面这个 diff：\n\n" + diff},
    ]

if __name__ == "__main__":
    print(json.dumps(build_messages(sys.stdin.read()),
                     ensure_ascii=False, indent=2))
```

`RULES` 是从 `.cursorrules` 读的，不是抄一份——我第一版真的抄了一份，两周后两边不一致，bot 又开始报空值判断。

| 阶段 | 单个 PR 的建议数 | 采纳 | 采纳率 | 空值判断类误报 |
| --- | --- | --- | --- | --- |
| 原始（#482） | 47 | 6 / 47 | 12.8% | 14 |
| 只加「请报真 bug」 | 44 | 6 / 44 | 13.6% | 13 |
| 写进 .cursorrules 后（5 个 PR 合计） | 31（平均 6.2） | 13 / 31 | 41.9% | 3 |

最后一行是之后 5 个 PR 的合计，不是同一个 PR 重跑。噪音从 47 条降到平均每 PR 6.2 条，最明显的变化其实不是条数，是我愿意逐条看完了——47 条那次我基本扫一眼就全划掉。

## CI 只报不拦，剩下的靠人复核

把 bot 从 required check 里摘掉之后重新接了一版。workflow 照跑，但**不**加进 branch protection，`continue-on-error: true`，结果写进 job summary 和一条 PR comment，任何一步都不 `exit 1`。合不合并由人决定，不由 exit code 决定。

```yaml
# .github/workflows/ai-review.yml
name: ai-review
on:
  pull_request:
    types: [opened, synchronize]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    # 这个 job 不要加到 branch protection 的 required checks 里
    continue-on-error: true
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: 生成 diff
        run: git diff origin/${{ github.base_ref }}...HEAD > /tmp/pr.diff

      - name: 跑自写 CLI
        # cli_review.py 里 import 了 review_prompt.build_messages
        env:
          MODEL_API_KEY: ${{ secrets.MODEL_API_KEY }}
        run: python cli_review.py < /tmp/pr.diff > cli.json || true

      - name: 汇总
        # Actions 的 bash 默认带 -e，所以失败要自己吞掉
        # CI 里没有 Cursor 那份（本地跑的），只有 bot.json 和 cli.json
        run: |
          python count_suggestions.py bot.json cli.json | tee /tmp/report.txt || true
          {
            echo '## AI review 建议（仅供参考，不阻塞合并）'
            echo '<!-- ai-review -->'
            echo '```'
            cat /tmp/report.txt
            echo '```'
          } >> "$GITHUB_STEP_SUMMARY"

      - name: 发一条 comment
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh pr comment "${{ github.event.number }}" \
            --body-file /tmp/report.txt || true
```

`<!-- ai-review -->` 是留着以后做去重用的 marker，现在还没用上。

剩下的还是得人看，我现在固定这么过一遍：

1. 先看「两个以上工具都报的位置」（脚本最后一行），命中率最高——但 #482 那个 `book.isbn` 三个都报了却是误报，所以这条只用来排优先级，不用来判对错。
2. 跳过 `*.graphql`、`*.md`、`src/generated/**` 和纯文案改动，那几处的误报率接近 100%。
3. 每条「采纳」必须能在本地跑出一个失败用例。游标重复那条我写了半个测试才确认，其余五条也是这个路子。
4. 「存疑」不当场改，扔进 `review-debt.md`，月底统一看一次。5 条存疑里后来有 1 条变成了真需求。
5. comment 里带 marker 的我不在 PR 里跟它对话，吵不出结果。

第 3 步最费时间，但也只有它能挡住「三个工具一起错」那种情况。顺带一提，`review-debt.md` 这个文件名是随手起的，两个月下来已经攒了 11 条，得空再清。

## 还没解决的

安全类建议我现在完全不敢信，也不敢不信。47 条里没有一条提到 #482 新增的 `keyword` 参数拼进 Redis key 时没做长度限制——这是我们自己 review 时发现的，一个几百 KB 的 query 能把 key 撑得很难看。三个工具都盯着空值判断，没一个看这个。试过在 prompt 里加一句「重点检查注入、越权、鉴权」，结果它开始对每个 `String` 参数报「可能存在 SQL 注入」，可这一层根本不碰 SQL（在 Java 那边的订单服务里）。加了等于没加，还多 20 条噪音。

所以安全这块照旧只报不拦，另外靠 `npm audit` 和人工 checklist，工具的建议只当提示。怎么让它在「一条不报」和「每行都报」之间给个有用的中间态，我还没想好。

还有个小的：那个 marker 本来打算写个脚本，重跑时编辑同一条 comment 而不是新发一条，现在每次 push 都刷一条，#482 上已经攒了 7 条。下次再写。

如果你也拿几个工具对过同一个 PR，尤其是误报类型的分布跟我不一样的，欢迎到 GitHub 开 issue 聊两句。
