---
title: "终端里的 AI CLI：上下文写清楚比换模型管用"
date: 2026-10-10
categories:
  - AI 工具
tags:
  - AI 工具
  - CLI
  - 工程规范
lead: "把 58 行 AGENTS.md 塞进仓库之后，同一个需求我从平均纠偏 5 轮降到 1 轮，一次累计 token 从 23k 掉到 9k；中间它还顺手删过一个 resolver，我用 git restore 捞回来了。"
---

2026-10-08 21:40，我让终端里的 AI CLI 给 book-shop-api 加一个 GraphQL query `booksByAuthor`。五轮下来全是纠偏：第一轮它给返回值糊了个 `any`，第二轮把 resolver 写进了 `src/schema/`，第三轮嫌类型报错直接跑了 `npm install`，把 `pnpm-lock.yaml` 改出一堆 diff，第四轮我让它「别动 lock 文件」，它老老实实不动了，却又把 SDL 改在了一个不存在的目录里。第五轮我换了另一个模型，同样的需求原样贴过去，第四轮那个错又原样犯了一遍。

那天晚上我才承认这跟模型没关系。我给它的全部背景就一句「这是个 TypeScript + GraphQL 的在线书店后端，用 pnpm」，它连 `pnpm codegen` 长什么样、resolver 该放哪儿都不知道，犯的每一个错都能从这句背景里推出来。顺带一提，book-shop-api 的工具链我锁得很死：Node 20.11.1、pnpm 9.12.0、TypeScript 5.6.3，订单服务是另一个 Java 21 / Gradle 8.10 的仓库——这些我全都没告诉它。

## 三款终端工具，我现在怎么分工

九月到现在陆陆续续装了四个，最后留下三个常开的：

| 工具 | 读的上下文 | 我让它干 | 明令不让它干 |
| --- | --- | --- | --- |
| Claude Code | `CLAUDE.md` | 跨文件重构、补测试 | 碰 `deploy/`、`.env*` |
| Codex CLI | `AGENTS.md` | 读代码、出单文件补丁 | 自己 `git commit` |
| Aider | `CONVENTIONS.md` | 小范围改动、自动 commit | 超过三个文件的重构 |
| Gemini CLI | `GEMINI.md` | 全仓搜符号、查调用链 | 改代码（只让它读） |

换模型那晚我把四个轮了一遍，结论挺没劲的：同一个烂上下文，谁上都烂。真正起变化的是我第二天把 `AGENTS.md` 重写之后——同一个 Codex CLI，一版过。

（Aider 那个「自动 commit」我真关不掉又舍不得关，它 commit 得比我还勤，后来干脆只在自己的 feature 分支上放它出来。）

## 第一版上下文文件，写了跟没写一样

第一版 `AGENTS.md` 就三行：项目是什么、`用 pnpm`、`别乱删文件`，加起来不到 90 tokens。「用 pnpm」拦不住 `npm install`，因为我没说 lock 文件叫什么、也没说不许装依赖；「别乱删文件」更是一句废话，它根本不知道哪些文件算不该删的。后来我数了下，为「加一个 query」这种需求，平均要来回 5 轮才收敛，每轮都把这三行重新喂一遍，一次需求累计烧掉 23k tokens 上下——钱倒是小事，主要是我得逐轮盯着它别把 lock 改了。

改到第四版才定下来。中间有一版我图省事，把整个 README 和 `src/` 目录树粘了进去，300 多行，单轮输入直接飙到 18k，它开始对着文档复述，改代码反而更慢。上下文不是越长越好，这点我是在账单上看明白的。

## 重写 AGENTS.md

第四版长这样，现在就躺在仓库根目录，四个工具各读各的那份，内容一样：

```markdown
# AGENTS.md（book-shop-api）

## 工具链，别自己猜版本
- Node 20.11.1 / pnpm 9.12.0 / TypeScript 5.6.3
- 装依赖只能用 `pnpm install --frozen-lockfile`
- 本地起服务 `pnpm dev`（4000 端口，GraphQL 在 /graphql）
- 类型检查 `pnpm typecheck`，单测 `pnpm test`
- 订单服务是另一个仓库（Java 21 / Gradle 8.10），不在本目录，别去找也别改

## 目录约定
- SDL 放 `src/schema/*.graphql`，resolver 放 `src/resolvers/*.ts`，一文件一个 query/mutation
- 加字段的顺序：先改 SDL → 再写 resolver → 最后 `pnpm codegen` 生成类型
- `src/generated/` 是生成的，别手写
- 测试放 `tests/`，命名 `*.test.ts`

## 明令禁止
- 不许执行 `npm install` / `yarn`，不许删除或重写 `pnpm-lock.yaml`
- 不许碰 `.env*`、`deploy/`、`k8s/`
- 不许 `git commit` / `git push` / `git reset --hard` / `rm -rf`
- 不许在 resolver 返回值里写 `any`；类型拿不准就回来问我

## 文案与命名
- 面向用户的报错文案、日志里的说明、SDL 的 description 一律简体中文
- 标识符一律英文：query 名小驼峰，类型名大驼峰，文件名同名小驼峰，commit message 英文
- 错误码用英文常量（如 `BOOK_NOT_FOUND`），给用户看的中文文案另写一行
```

写全之后的变化很直接：构建命令 pin 死版本，它不再自作主张装依赖；「先 SDL 再 resolver 再 codegen」写进去，加字段第一轮就对了；最后那条中英文规范是 10-09 补的——它之前把一个 query 命名成 `查询作者书籍`，还给我生成了中文的 GraphQL 描述，评审时我盯着那行看了半天才反应过来哪不对。

现在这份 58 行，约 1380 tokens，每轮都带。一次需求平均 1.2 轮、累计 9k 左右，比第一版那 23k 省了六成。下面是加 `booksByAuthor` 那次我贴进复盘文档的终端记录：

```text
[context] AGENTS.md loaded — 58 lines, ~1380 tokens
[plan] 1) src/schema/book.graphql 加 booksByAuthor  2) 新建 src/resolvers/booksByAuthor.ts  3) pnpm codegen  4) pnpm typecheck
[exec] pnpm codegen -> done  |  pnpm typecheck -> 0 errors
[usage] input 2140 / output 402 / total 2542 tokens  |  rounds 1
```

## 它还是把 OrderResolver.ts 删了

上下文写全也没能拦住全部。10-09 下午我让它「清掉没被引用到的 resolver」，它把 `src/resolvers/OrderResolver.ts` 一起删了——那个文件是被 SDL 里一个 `extend type` 间接引的，静态扫引用没扫出来。先发现的是 `pnpm typecheck` 报了一串 `Cannot find module`：

```bash
$ pnpm typecheck
src/schema/order.graphql:3:1 - error TS2307: 找不到模块 '../resolvers/OrderResolver'
$ git status --short
 D src/resolvers/OrderResolver.ts
 M src/schema/order.graphql

$ git restore src/resolvers/OrderResolver.ts
$ git status --short
 M src/schema/order.graphql
```

文件没提交过，`git restore` 一行就回来了。这里得谢一句自己：上下文里那条「不许 git commit」起了作用，Aider 当时要在的话大概率顺手 commit 了，那就得 `git reflog` 翻 HEAD、再 `git restore --source=HEAD~1 -- <file>`，麻烦一档。恢复完我把「删文件前先 `pnpm typecheck` 一遍」也补进了禁止清单。

顺带一提，`git restore` 是 2.23 之后才有的老命令了，我到现在还习惯性想敲 `git checkout --`，肌肉记忆改不动，干脆在上下文里把两条都写上了。

## 重复活写成脚本，别每次重新对话

加 query 这种事一个月要干七八回，我以前每回都开个新对话，把「先 SDL 再 resolver 再 codegen 再 typecheck」重新描述一遍，token 花得冤枉还不稳。后来直接写成 `scripts/new-query.sh`，人和 CLI 都能跑：

```bash
#!/usr/bin/env bash
# 生成一个 GraphQL query 骨架：./scripts/new-query.sh booksByAuthor
set -euo pipefail

name="${1:-}"
if [[ ! "$name" =~ ^[a-z][a-zA-Z0-9]*$ ]]; then
  echo "query 名用小驼峰英文，例如 booksByAuthor" >&2
  exit 1
fi

sdl="src/schema/${name}.graphql"
resolver="src/resolvers/${name}.ts"
if [[ -e "$sdl" || -e "$resolver" ]]; then
  echo "文件已存在，不覆盖：$sdl / $resolver" >&2
  exit 1
fi

cat > "$sdl" <<EOF
extend type Query {
  ${name}(authorId: ID!): [Book!]!
}
EOF
cat > "$resolver" <<EOF
import type { QueryResolvers } from '../generated/types';

export const ${name}: QueryResolvers['${name}'] = async (_parent, args, ctx) => {
  return ctx.bookRepo.findByAuthor(args.authorId);
};
EOF

pnpm codegen
pnpm typecheck
echo "骨架好了：$sdl / $resolver，接着填实现和 tests/"
```

那个 `^[a-z][a-zA-Z0-9]*$` 就是替上下文里的小驼峰规范兜底；`[[ -e ... ]]` 不覆盖，是被 10-09 那次删文件吓出来的。脚本进仓库之后，加 query 这事儿基本不再开新对话了，单轮 token 从 2k 多降到忽略不计。CLI 想用也直接 `./scripts/new-query.sh xxx`，不用我复述流程。

## 还没解决的

`AGENTS.md`、`CLAUDE.md`、`CONVENTIONS.md`、`GEMINI.md` 四份内容现在靠我手动同步，10-09 改过一次构建命令，漏同步了 `GEMINI.md`，隔天它又拿 `npm install` 给我上了一课。想写个脚本从一份 `AGENTS.md` 生成其余三份（软链也行，就是 Windows 上不省心），拖了两天没动手。还有那条「删文件」的禁令其实没真拦住：它走的是补丁里的 Delete File，不是 `rm`，我的禁止清单只列了命令，没列补丁动作——怎么把这条写进上下文才不变成一句空话，还没想好。
