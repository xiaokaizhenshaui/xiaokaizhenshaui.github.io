---
title: "GraphQL codegen 到 tRPC：前后端类型到底怎么共享"
date: 2026-08-01
categories:
  - 全栈开发
tags:
  - TypeScript
  - GraphQL
  - 工程化
lead: "前后端各手写一份 Book，改字段漏一处，线上炸了 3 回；把生成步骤塞进 CI 之后，三套方案（codegen / OpenAPI / tRPC）在我们仓库里各管一段，谁也不替代谁。"
---

7 月 28 号傍晚 `npm run typecheck` 挂了，红字挺长：

> `src/resolvers/book.ts:18:5 - error TS2345: Argument of type '{ id: string; priceYuan: number; }' is not assignable to parameter of type 'Book'.`
> `  Property 'priceCents' is missing in type '{ id: string; priceYuan: number; }' but required in type 'Book'.`

后端 4 月就把价格统一成 `priceCents` 了，前端那份手写的 `Book` 还留着 `priceYuan`。这类事我们已经出过 3 回，每回都是「两边各改各的，编译期谁也管不着谁，等页面白屏了才发现」。当天把生成链条接进 CI，顺手把三套方案的边界理了一遍。仓库是 pnpm workspace，`typescript 5.5.4`，`node v20.11.1`。

## 三套方案，我们居然同时在用

一开始我想「选一个最好的全仓库铺开」，铺了两天发现不对：对外的书店 API、公司里那套 Java 订单服务、内部管理后台，约束完全不一样。

| 方案 | 契约从哪来 | 我们用在 | 难受的地方 |
| --- | --- | --- | --- |
| GraphQL codegen | 手写的 `schema.graphql` | 对外 API：Web、小程序、以后可能接的第三方 | 要额外维护 `.graphql` 操作文档，改字段必须跑一遍生成 |
| OpenAPI 生成 | Java 侧 springdoc 导出的 `openapi.json` | 只读地调订单服务 | Java 注解一改，json 一大片 diff，生成物跟着抖 |
| tRPC | `typeof appRouter` 直接推 | 内部后台，前后端同仓库全 TS | 出了 TS 生态就没戏，第三方别想接 |

一句话分法：有非 TS 客户端、要对外开放，走 GraphQL 或 OpenAPI；全 TS、同一个 monorepo、不对外，tRPC 最省事。硬让 tRPC 去服务小程序，等于把「类型共享」变成「必须全用 TS」，这买卖不划算。顺带一提，Java 那边同事听说我们靠 `typeof` 就能把类型传过去，愣了半天，问「那接口文档呢」——确实没有，后台就我们三个人用。

其实 7 月初我一度想把对外的 GraphQL 也换成 tRPC，省掉 SDL 和 codegen 两层。拉了下小程序那边的同事一聊就放弃了：他们用原生 TS 不假，但发版节奏跟我们不同步，接口一变就得跟着升 SDK，而 SDL 好歹能当一份静态契约摆在那儿慢慢对。OpenAPI 那条更没得选，订单服务是 Java 的，归另一个组，我们只有读 `openapi.json` 的份。所以「选一个最好的」这个前提本身就是错的，边界不一样，工具就不该一样。

## codegen.yml 怎么摆

对外那条走 `@graphql-codegen/cli`。schema 直接指本地 SDL 文件，不用先把服务起起来，CI 里省一个步骤：

```yaml
# codegen.yml（仓库根目录）
schema: ./apps/api/src/schema.graphql
documents: ./apps/web/src/operations/**/*.graphql
generates:
  packages/shared/src/generated/graphql.ts:
    plugins:
      - typescript
      - typescript-resolvers
    config:
      enumsAsTypes: true
      scalars:
        DateTime: string
  packages/shared/src/generated/operations.ts:
    plugins:
      - typescript-operations
```

`enumsAsTypes: true` 是我特意加的，默认会生成 TS `enum`，一旦哪天给枚举加个值，diff 里全是生成文件的变动；换成 `'PAID' | 'SHIPPED' | 'CANCELLED'` 这种联合类型，review 时一眼看得懂。`DateTime` 后端存的是 ISO 字符串，映射成 `string`，不然生成出个 `any` 等于白干。第一版我把 `documents` 写成了 `apps/web/**/*.tsx`，让插件去 TSX 里扒 `gql` 模板，结果把几个测试文件里的示例片段也扒进去了，`Duplicate operation name` 报错，收窄到 `operations/**/*.graphql` 才消停。

## 生成物提交不提交

组里争过一轮。我这边是**提交进 git** 的，理由三条：CI 跑 `tsc -b --noEmit` 不用先起 API 服务；PR 里生成物一 diff，就能直接看到「后端加了个字段，前端 23 处要跟着改」；新人 clone 下来 `pnpm install && pnpm typecheck` 立刻能过。代价是改一次 schema 就多一坨几百行的 diff，看着烦。

防「忘了生成」靠的是 `codegen:check`：CI 里先跑一遍生成，再用 `git diff --exit-code` 卡住生成物有变化的情况。隔壁组选的是不提交、CI 生成完缓存产物，结果有回 schema 服务没起来，任务直接吃了上一轮的缓存，类型对不上还全绿，查了大半天。这么一比我宁愿多几百行 diff。

中途还踩过一次 `codegen.yml` 里 `schema` 指了 `http://localhost:4000/graphql` 的坑：本地忘了起服务，生成直接报 `ECONNREFUSED`，CI 上更麻烦，得先把 API 拉起来才能生成前端类型，链路凭空多一环。改成指本地 SDL 文件之后，`codegen:check` 在 CI 里就是纯文件操作，不依赖任何端口，跑得也快，从 40 多秒降到 6 秒。

## 生成出来的类型怎么用

后端 resolver 不再自己声明返回类型，直接拿生成的 `QueryResolvers` / `BookDetailResolvers` 套上去，字段漏了、拼错了，编译期就红：

```ts
// apps/api/src/resolvers/book.ts
import type {
  QueryResolvers,
  BookDetailResolvers,
} from '@bookstore/shared/generated/graphql';
import { listFeaturedBooks } from '../db';

export const Query: QueryResolvers = {
  featuredBooks: async (_parent, args) => {
    return listFeaturedBooks(args.limit ?? 10);
  },
};

export const BookDetail: BookDetailResolvers = {
  // 这里少返回 priceCents 直接编译不过，不用等运行时白屏
  coverUrl: (book) => `https://cdn.bookstore.cn/cover/${book.isbn}.jpg`,
};
```

前端那份是 `typescript-operations` 生成的 `FeaturedQuery`、`FeaturedQueryVariables`，`useQuery` 挂上去之后 `data.featuredBooks[0].author.name` 一路有提示。7 月 28 号那个 `priceYuan` 的错误，现在会在 `pnpm codegen` 之后立刻变成编译错误，而不是等 QA 点开页面。

## tRPC 那半边

内部后台不用 GraphQL，`initTRPC` + zod，router 的 `typeof` 就是客户端的类型来源，中间不落任何生成文件：

```ts
// apps/api/src/trpc/router.ts
import { initTRPC } from '@trpc/server';
import { z } from 'zod';
import { db } from '../db';

const t = initTRPC.create();

export const appRouter = t.router({
  bookById: t.procedure
    .input(z.object({ id: z.string() }))
    .query(({ input }) => db.books.findById(input.id)),

  setPrice: t.procedure
    .input(z.object({ id: z.string(), priceCents: z.number().int().positive() }))
    .mutation(({ input }) => db.books.updatePrice(input.id, input.priceCents)),
});

export type AppRouter = typeof appRouter;

// apps/admin/src/trpc.ts
import { createTRPCProxyClient, httpBatchLink } from '@trpc/client';
import type { AppRouter } from '@bookstore/api/trpc/router';

export const client = createTRPCProxyClient<AppRouter>({
  links: [httpBatchLink({ url: 'http://localhost:4000/trpc' })],
});

// client.setPrice.mutate({ id: 'bk_1042', priceCents: 9900 })
// 少个字段、把 priceCents 写成字符串，编辑器当场标红
```

有个小细节：router 文件我只 `export type AppRouter`，客户端 import 的是纯类型，打包时会被擦掉，不会把 `db`、`zod` 这些服务端依赖拖进浏览器 bundle。第一版我图方便直接 `import { appRouter }`，构建产物里凭空多了 200 多 KB，还差点把数据库连接配置打了进去，翻 webpack 分析图才发现，吓得赶紧改回来。另外 zod 的 `.input()` 同时管了运行时校验和静态类型，后端不用再写一遍 DTO，这点比 GraphQL 那边「SDL 一份、resolver 类型一份」省事；代价是校验规则全压在 TS 里，非 TS 的调用方既看不懂也没法复用，所以只对内用。

## 目录和 scripts

`package.json` 里我把几个动作捆一起：

```json
{
  "name": "bookstore",
  "private": true,
  "workspaces": ["apps/*", "packages/*"],
  "scripts": {
    "codegen": "graphql-codegen --config codegen.yml",
    "codegen:check": "graphql-codegen --config codegen.yml && git diff --exit-code packages/shared/src/generated",
    "typecheck": "tsc -b --noEmit",
    "typecheck:all": "pnpm codegen:check && pnpm typecheck"
  },
  "devDependencies": {
    "@graphql-codegen/cli": "^5.0.2",
    "@graphql-codegen/typescript": "^4.0.9",
    "@graphql-codegen/typescript-resolvers": "^4.0.9",
    "@graphql-codegen/typescript-operations": "^4.2.0",
    "typescript": "^5.5.4"
  }
}
```

仓库大概长这样（用列表凑合看下）：

- `apps/web/` — Next.js，面向读者，写 `.graphql` 操作文档
- `apps/api/` — Apollo Server 4，SDL 和 resolver
- `apps/admin/` — 内部后台，tRPC
- `packages/shared/src/generated/` — codegen 产物，**提交进 git**
- `packages/shared/src/errorCodes.ts` — 前后端共用的英文错误码
- `packages/shared/src/i18n/zh-CN.ts` — 中文文案，前端查这份

`generated/` 归 `packages/shared` 管，Web 和 admin 都从它 import；`@bookstore/api/trpc/router` 只有 admin 引，没跨到对外那半边去。

目录里那两个 `errorCodes.ts`、`zh-CN.ts` 顺带说下它们为什么单独放。GraphQL 的 enum 值只能 ASCII，`OrderStatus { PAID SHIPPED CANCELLED }`，写「已支付」进去启动就报错，我上周刚踩过，回头单独记。中文一律不进 schema、不进生成类型，单独放 `zh-CN.ts`，前端按 `code` 查表。理由很实际：文案一周能改两回，还可能要上英文站，混进类型里等于把产品改动和编译绑死。`description` 里写中文注释没问题，那是文档不是数据，codegen 不会把它变成字段。说到底生成物只负责「字段叫什么、是什么类型」，「这句话怎么说」不该由 schema 决定。

## 还没解决的

tRPC 推出来的 `Book` 和 codegen 生成的 `BookDetail` 现在是两份，前者多了 `costCents`、`internalNote` 这种后台专用字段。我写了个 `assertAssignable` 的类型小工具想手动对齐，但没人跑就等于没有，迟早还会飘。另外 springdoc 导出的 `openapi.json` 到今天还是我手工下载、手工提交进仓库的，Java 那边改了注解经常忘了同步，生成出来的 `OrderDTO` 落后半个版本——把它接进 CI 这事我记在小本上，下次再写。
