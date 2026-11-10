---
title: "在线书店的 GraphQL API，我把 Schema 推翻重写了两次"
date: 2026-04-11
categories:
  - 全栈开发
tags:
  - GraphQL
  - TypeScript
  - Apollo Server
lead: "第一版照着数据库表抄出 11 个 type，书籍详情页要发 5 次请求；按页面用例重写后一次拿全，type 反而少到 7 个。"
---

4 月 9 号晚上 11 点 40，前端同事把 Chrome Network 面板的截图甩进群里，红框圈着 5 个 `/graphql`，配一句「一个书籍详情页你让我发五次？」。我点开日志，确实是 5 个，body 还都不一样：

> `{ "query": "{ bookById(id:\"bk_1042\"){ id title authorId priceCents } }" }`
> `{ "query": "{ authorById(id:\"au_07\"){ id name } }" }`
> `{ "query": "{ stockByBookId(bookId:\"bk_1042\") }" }`
> `{ "query": "{ reviewsByBookId(bookId:\"bk_1042\"){ rating content } }" }`

那一刻我反应过来，慢不在 resolver，在我第一版 Schema 就是照着 MySQL 表一行行抄出来的。机器上 `node -v` 是 `v20.11.1`，`@apollo/server` 锁在 `4.10.0`，周末两天全花在推倒重来上。

## 第一版：11 张表抄成 11 个 type

我写 Java 写久了，骨子里是「一张表一个 POJO / 一个 Mapper」那套。建 GraphQL 的时候没多想，把 `books`、`authors`、`orders`、`reviews` 直接翻成 type，外键原样留成 `authorId`、`publisherId`，状态用 `Int` 表示（1 待付款、20 已付款，跟库里 tinyint 对齐）。

```graphql
# 第一版 src/schema.graphql（已废弃，这里只贴 5 个）
type Book {
  id: ID!
  isbn: String
  title: String!
  authorId: ID!
  publisherId: ID!
  priceCents: Int!
  status: Int!
  createdAt: String!
}

type Author {
  id: ID!
  name: String!
  countryCode: String
}

type Review {
  id: ID!
  bookId: ID!
  userId: ID!
  rating: Int!
  content: String
}

type Order {
  id: ID!
  userId: ID!
  bookId: ID!
  status: Int!
  paidAt: String
}

type Query {
  bookById(id: ID!): Book
  authorById(id: ID!): Author
  stockByBookId(bookId: ID!): Int
  reviewsByBookId(bookId: ID!): [Review!]!
}
```

完整文件里还有 `Publisher`、`Stock`、`User`、`Cart`、`Category`、`Address`，凑齐 11 个 type，外加 `Query` / `Mutation`。当时还挺得意：字段和表一一对应，`createdAt`、`publisherId` 一个没落，谁都能看懂。顺带一提，`status: Int!` 这个决定后来被我骂了两次，客户端拿到 `20` 完全不知道是该显示「已付款」还是「待发货」，只能自己维护一份魔法数字表。

## 五次请求是设计出来的，不是写慢了

问题出在 type 之间没有边。`Book` 只给了 `authorId`，没给 `author` 字段，客户端想展示作者名，只能拿 `authorId` 再发一次请求；库存、评价、推荐同理。我数了下详情页的调用链：

| 第几次 | 拿什么 | 依赖上一次的结果 |
| --- | --- | --- |
| 1 | `Book` 基础信息 + `authorId` | — |
| 2 | 作者名 | 要第 1 次的 `authorId` |
| 3 | 库存数 | 要第 1 次的 `id` |
| 4 | 前 3 条评价 | 要第 1 次的 `id` |
| 5 | 「买了又买」书单 | 要第 1 次的 `id` |

前两次还是串行的，压根没法并发。本地拿 `curl` 掐了下，5 次往返加起来差不多 900ms，前端还得写 200 多行代码把 5 坨数据拼成一个 ViewModel。说白了，我把数据库的「关系」拆掉了，又让客户端在浏览器里替我 join 回去。这点跟当年用 MyBatis 不开 `<association>`、在 Service 里 for 循环查详情是一个毛病，只不过这次循环跑在了公网上。

发现之后我先想着「能不能不动 Schema，客户端凑合一下」，让前端把后三次请求用 `Promise.all` 并发掉。改完一测，从 900ms 降到 610ms，看着有起色，可第 2 次还得等第 1 次的 `authorId`，串行链断不了，前端那 200 多行拼装逻辑一行没少。更别提小程序那边是另一套代码，同样的坑还得再踩一遍。这才死心：数据表长得像什么，跟页面要什么是两码事，契约得按后者来。

## 第二版：按页面用例建类型

重写的时候我把数据库表全关了，只盯着设计稿问：这一个页面到底要显示什么。答案是「一张卡片：封面、书名、价格、作者名、有货没货、几条评价、推荐几本别的书」。那就直接建一个 `BookDetail`，把这些一次性给全，嵌套的 `author` 用 resolver 在服务端 join。

```graphql
# 第二版 src/schema.graphql
type AuthorBrief {
  id: ID!
  name: String!
  otherBookCount: Int!
}

type ReviewItem {
  id: ID!
  rating: Int!
  content: String!
  authorName: String!
}

type BookDetail {
  id: ID!
  title: String!
  priceCents: Int!
  coverUrl: String!
  author: AuthorBrief!
  inStock: Boolean!
  reviewCount: Int!
  topReviews: [ReviewItem!]!
  alsoBought: [BookDetail!]!
}

input AddToCartInput {
  bookId: ID!
  quantity: Int = 1
}

type CartPayload {
  cartId: ID!
  itemCount: Int!
  totalCents: Int!
}

type Query {
  bookDetail(id: ID!): BookDetail
  featuredBooks(limit: Int = 10): [BookDetail!]!
}

type Mutation {
  addToCart(input: AddToCartInput!): CartPayload!
}
```

`status: Int!` 换成了 `inStock: Boolean!`，`createdAt`、`publisherId` 这种页面根本不用的字段直接从对外契约里删掉（库里还留着，内部用，不暴露）。type 从 11 个降到 7 个（含一个 input），请求从 5 次变 1 次，首屏接口耗时从 900ms 左右掉到 260ms。前端那个 ViewModel 文件当场删了。

改完客户端那条查询长这样：`{ bookDetail(id:"bk_1042"){ title priceCents coverUrl author { name otherBookCount } inStock reviewCount topReviews { content rating } } }`，一次拿全，浏览器里再没有 join。删字段这事我当时还犹豫过，怕以后要用又得加回来；后来发现真需要的是内部报表和后台，走的是另一套直连库的 Java 服务，压根不经过 GraphQL，删得挺干净。对外契约少一个字段，就少一处要长期兼容的负担，这笔账是后来才想明白的。

## schema-first 还是 code-first

中间纠结过要不要换 Pothos / Nexus 那套 code-first，让 TS 类型自己生成 Schema。我列了个表比了下：

| | schema-first（手写 SDL） | code-first（Pothos 之类） |
| --- | --- | --- |
| 契约长什么样 | 一个 `schema.graphql`，PR 里能直接 diff | 散在 TS 文件里，得跑一遍才看得见全貌 |
| 前端 codegen | 直接读 `.graphql`，零依赖 | 要先起服务或导出 schema 文件 |
| 类型和 resolver 对齐 | 靠人肉，加字段容易漏 | 编译器帮你盯着 |
| 我这种 Java 脑子 | 看着 SDL 舒服 | 一堆 builder 链式调用，半天进不去状态 |

选来选去还是选了 schema-first，主要因为前端要拿 SDL 做 codegen，而且「改了哪个字段」在 review 时一眼能看出来。代价也认了：有次给 `BookDetail` 加了 `subtitle`，SDL 改了 resolver 忘了，页面一片空白，查了半小时。后来上了 codegen 生成 `Resolvers` 类型，编译器开始替我盯这件事，这个坑才堵上（怎么接进 CI 是另一篇的事）。

另外 code-first 那套我并没完全否掉，内部后台后来试过 Pothos，写起来确实顺，类型不用两处维护，加字段时 builder 会提醒你把 resolver 补上。只是对外这套已经跑了大半年，SDL 还被小程序和 codegen 两边引用，迁移成本比收益高，就先搁着。工具没有对错，看谁在消费这份契约，以及改动的时候谁会被牵连——这句当时要是早点想明白，能少写一版 Schema。

## 错误消息：中文给人看，英文给机器看

还有条规矩是这次一并定下的：抛给用户的 `message` 全写中文，`extensions.code` 保持英文常量。原因很实在——之前照着 Stack Overflow 抄了句 `throw new Error('Book not found')`，前端直接把这行英文渲染进了 toast，被产品截图发群里问「咱们什么时候改英文站了」。

```ts
// src/server.ts
import { ApolloServer } from '@apollo/server';
import { startStandaloneServer } from '@apollo/server/standalone';
import { GraphQLError } from 'graphql';
import { readFileSync } from 'node:fs';
import { loadBookDetail, listFeaturedBooks, loadAuthorBrief } from './db';

const typeDefs = readFileSync('./src/schema.graphql', 'utf8');

const resolvers = {
  Query: {
    bookDetail: async (_parent: unknown, args: { id: string }) => {
      const detail = await loadBookDetail(args.id);
      if (!detail) {
        throw new GraphQLError('没找到这本书，可能已经下架了', {
          extensions: { code: 'BOOK_NOT_FOUND', bookId: args.id },
        });
      }
      return detail;
    },
    featuredBooks: (_p: unknown, args: { limit?: number }) =>
      listFeaturedBooks(args.limit ?? 10),
  },
  BookDetail: {
    author: (book: { authorId: string }) => loadAuthorBrief(book.authorId),
  },
};

async function main() {
  const server = new ApolloServer({ typeDefs, resolvers });
  const { url } = await startStandaloneServer(server, {
    context: async () => ({ locale: 'zh-CN' }),
    listen: { port: 4000 },
  });
  console.log(`服务起来了：${url}`);
}

main().catch((err) => {
  console.error('启动失败', err);
  process.exit(1);
});
```

`code` 给前端弹窗分流和监控报警用，`message` 给人看，`bookId` 这类结构化的塞进 `extensions` 而不是拼进句子。顺带说一句，上面 `loadAuthorBrief` 暂时还是一条 SQL 一本书，列表页会打出 31 条，这个坑当时完全没意识到，先记着。

## 依赖清单

```json
{
  "name": "bookstore-graphql-api",
  "private": true,
  "scripts": {
    "dev": "tsx watch src/server.ts",
    "start": "tsx src/server.ts"
  },
  "dependencies": {
    "@apollo/server": "^4.10.0",
    "graphql": "^16.9.0"
  },
  "devDependencies": {
    "tsx": "^4.16.2",
    "typescript": "^5.5.4",
    "@types/node": "^20.14.10"
  }
}
```

`npm install && npm run dev` 起来之后 `curl -X POST http://localhost:4000/graphql -H 'content-type: application/json' -d '{"query":"{ featuredBooks(limit:2){ title priceCents author { name } } }"}'` 能直接拿到嵌套的作者名。我第一次跑的时候把 `schema.graphql` 放到了项目根目录，`readFileSync('./src/schema.graphql')` 直接 `ENOENT`，改成绝对路径才消停，这种小破事记一下免得下次再踩。

## 还没解决的

`BookDetail.alsoBought` 是递归的，客户端能构造 `alsoBought { alsoBought { alsoBought { ... } } }` 一路套下去，服务端没加查询深度限制，真被人写个 20 层的查询大概率要把库拖死。Apollo Server 4 本身不带 depth limit，得自己挂个 validation rule 或者上 `graphql-depth-limit` 之类的包。我还没动，主要没想清楚限几层合适：限 3 层，推荐位的设计稿刚好要用到第 3 层，卡太死又怕以后改版。先记着，等把 N+1 那摊弄完再说。
