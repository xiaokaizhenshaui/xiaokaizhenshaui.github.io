---
title: "GraphQL 接口 2 秒 → 180ms，就加了层 DataLoader"
date: 2026-06-06
categories:
  - 全栈开发
tags:
  - GraphQL
  - DataLoader
  - 性能
lead: "30 本书的列表页打出 31 条 SQL，p95 卡在 2100ms；把 loader 改成每请求一份之后，同一脚本压测 p95 掉到 180ms，SQL 只剩 2 条。"
---

6 月 3 号下午两点多，运营丢过来一句「首页怎么转圈转两秒」。我把 `DEBUG=knex:query` 打开，本地跑了一遍 `featuredBooks(limit:30)`，终端刷得根本停不下来：

```bash
$ DEBUG=knex:query npm run dev 2>&1 | tee /tmp/query-before.log
  knex:query select * from "books" where "status" = 20 order by "sales" desc limit 30 +2ms
  knex:query select * from "authors" where "id" = 'au_07' +1ms
  knex:query select * from "authors" where "id" = 'au_07' +1ms
  knex:query select * from "authors" where "id" = 'au_07' +1ms
  ...
$ grep -c 'select \* from "authors"' /tmp/query-before.log
30
$ grep -c 'select \* from "books"' /tmp/query-before.log
1
```

31 条，一条查书，30 条查作者，而且 `au_07` 重复了 8 次——同一位作者被查了 8 遍。环境是 `node v20.11.1`、`knex 3.1.0`、`@apollo/server 4.10.0`，PostgreSQL 15 在本地 Docker 里。看到这串日志我基本不用看代码就知道是 N+1，4 月重写 Schema 时我为了赶进度，`BookDetail.author` 那个 resolver 是直接 `db('authors').where('id', book.authorId).first()`，一本书一次。

## 31 条 SQL 是怎么来的

GraphQL 的执行是逐字段走的：`featuredBooks` 返回 30 个 `BookDetail`，引擎对每一个对象调用一次 `author` resolver，30 次调用彼此不知道对方存在，于是 30 条一模一样形态的 `SELECT` 就出去了。我写 Java 那会儿用 JPA 不开 `@EntityGraph` 也是这个德行，只是 Hibernate 的日志更啰嗦，一眼能看见；换成自己手写的 knex，反而没警觉。

更亏的是网络往返。本地每条 SQL 大概 55~65ms（Docker 桥接 + 连接池没预热），30 条串行就是 1800ms 往上，加上 GraphQL 解析和组装，p95 摸到 2100ms 一点不冤。

在动 DataLoader 之前我先试了两个笨办法。一个是在 `featuredBooks` 的 SQL 里直接 `left join authors`，把作者一次性带出来——列表页确实快了，可 `bookDetail` 单查那条路径还是老样子，而且 `ReviewItem`、`alsoBought` 各自也要 join，SQL 越写越胖，加一个字段就得改一遍 select，两天就放弃了。另一个是给 `authorById` 套了个模块级的 `Map` 当缓存，命中率看着不错，但缓存永不失效，作者改名之后得重启进程才生效，被测试同学当场抓包。两个都不算正经解法，只是把 N+1 从数据库挪到了别处。

## 批处理函数写对了，地方放错了

DataLoader 的思路不复杂：把同一个 tick 里攒下来的 key 收成一批，用一条 `whereIn` 查回来，再按原顺序发回去。我先写了 `loaders.ts`：

```ts
// src/loaders.ts
import DataLoader from 'dataloader';
import { knex } from './db';
import type { Author } from './types';

export interface Loaders {
  authorById: DataLoader<string, Author>;
  reviewCountByBookId: DataLoader<string, number>;
}

export function createLoaders(): Loaders {
  const authorById = new DataLoader<string, Author>(async (ids) => {
    // ids 是 readonly string[]，一次拿全
    const rows = await knex<Author>('authors')
      .whereIn('id', ids as readonly string[])
      .select('*');
    const byId = new Map<string, Author>();
    for (const row of rows) byId.set(row.id, row);
    // 必须按 ids 的原顺序返回，错位一个字段就全串了
    return ids.map((id) => byId.get(id) ?? new Error(`作者 ${id} 不存在`));
  });

  const reviewCountByBookId = new DataLoader<string, number>(async (ids) => {
    const rows = await knex('reviews')
      .whereIn('book_id', ids as readonly string[])
      .groupBy('book_id')
      .select('book_id')
      .count({ cnt: '*' });
    const byId = new Map<string, number>();
    for (const r of rows) byId.set(r.book_id, Number(r.cnt));
    return ids.map((id) => byId.get(id) ?? 0);
  });

  return { authorById, reviewCountByBookId };
}
```

`ids.map(...)` 这句是重点：顺序错了 DataLoader 不会报错，只会把作者张冠李戴，我第一版偷懒直接 `return rows`，压测数据看着「变快了」，但页面上《三体》作者变成了隔壁那位，差点没发现。返回 `Error` 实例也行，DataLoader 会把它当成这个 key 的独立错误，不会把整批炸掉。

## 全局实例差点把用户数据串了

真正翻车的是下一版。我图省事，把 `const loaders = createLoaders()` 提到了模块顶层，想着「反正就查作者和评价数，复用一份还省点对象分配」。结果联调时拿两个账号并发请求，A 的购物车里冒出了 B 刚加的书。

原因有两层。一是 DataLoader 的缓存挂在实例上，模块级实例活满整个进程，A 请求里 `load('au_07')` 的结果会被 B 请求直接命中；二是批处理会把同一 tick 内**所有**请求的 key 合并成一条 `whereIn`，不同用户的数据在同一个批次里走。作者表还好，换成「我的订单」「我的地址」这种按用户隔离的 loader，就是实打实的越权。顺带一提，这跟早年我在 Spring 里把一个带 `ThreadLocal` 的 Bean 写成 singleton 是同一类事故，隔了几年换门语言又踩一遍，挺不好意思的。

改成每请求一份，loader 的生命周期跟请求对齐，缓存自动随请求结束回收：

```ts
// src/server.ts
import { ApolloServer } from '@apollo/server';
import { startStandaloneServer } from '@apollo/server/standalone';
import { readFileSync } from 'node:fs';
import { createLoaders, type Loaders } from './loaders';
import { listFeaturedBooks } from './db';

interface Context {
  loaders: Loaders;
  userId: string | null;
}

const typeDefs = readFileSync('./src/schema.graphql', 'utf8');

const resolvers = {
  Query: {
    featuredBooks: (_p: unknown, args: { limit?: number }, ctx: Context) =>
      listFeaturedBooks(args.limit ?? 10),
  },
  BookDetail: {
    author: (book: { authorId: string }, _a: unknown, ctx: Context) =>
      ctx.loaders.authorById.load(book.authorId),
    reviewCount: (book: { id: string }, _a: unknown, ctx: Context) =>
      ctx.loaders.reviewCountByBookId.load(book.id),
  },
};

async function main() {
  const server = new ApolloServer<Context>({ typeDefs, resolvers });
  const { url } = await startStandaloneServer(server, {
    // 每个请求新建，别提到模块顶层
    context: async ({ req }): Promise<Context> => ({
      loaders: createLoaders(),
      userId: (req.headers['x-user-id'] as string) ?? null,
    }),
    listen: { port: 4000 },
  });
  console.log(`服务起来了：${url}`);
}

main().catch((err) => {
  console.error('启动失败', err);
  process.exit(1);
});
```

改完顺手补了个回归测试：两个不同 `x-user-id` 并发各打 50 次，断言响应里不出现对方的 bookId。这测试现在还在 CI 里跑着，比任何注释都管用。

顺带记一下排查过程，免得下次又从头来：我先怀疑是 Redis 缓存串了，把缓存全关掉问题还在；又去翻 knex 的连接池配置，也没毛病；把 `createLoaders()` 那行从模块顶上挪下来，两个账号的数据立刻干净了。整个过程两个多小时，根因就一行代码的位置。这事之后我们定了条规矩：凡是带缓存、带请求态的对象，一律在 context 里 new，谁提到模块顶层直接打回。

## 缓存键：别拿对象当 key

DataLoader 默认拿 key 本身做缓存键，`string`、`number` 没问题，传对象就坑了。我有次写了 `load({ id: 'au_07', fields: ['name'] })`，两个字面量看着一样但引用不同，缓存永远不命中，`whereIn` 照样一条一条打。要么显式给 `cacheKeyFn: (key) => key.id`，要么干脆只用标量当 key、字段裁剪放到 batch 函数里统一处理——我选了后者，简单。另外还有 `clear(key)`、`prime(key, value)`、`clearAll()`：一次请求里先写后读的场景（比如加购之后立刻查购物车），得手动 `clear` 掉旧值，不然读到的还是写之前的缓存。这个我一开始也没注意，直到后台改价之后同一个 mutation 里读两次价格，第二次还是旧的。

还有个容易忽略的点：DataLoader 的缓存是「同一 key 返回同一个 Promise」，所以批量里重复的 `au_07` 不会真的查两次，这也是为什么 30 条 SQL 能压到 1 条而不是 8 条。但别指望它跨请求帮你省事，它的生命周期就该只有一个请求，想跨请求省得去上 Redis，那是另一个量级的问题，我这小破书店暂时用不上。

## 压测数字

同一个 k6 脚本，`20` 个 VU 跑 30 秒，只改服务端这一层：

```bash
$ k6 run --vus 20 --duration 30s bench/featured.js

# 改前：BookDetail.author 直接查库
http_req_duration......: avg=1864ms  p(95)=2100ms  p(99)=2430ms
http_reqs..............: 1412   (47.05/s)

# 改后：per-request DataLoader
http_req_duration......: avg=152ms   p(95)=180ms   p(99)=210ms
http_reqs..............: 17643  (588.1/s)

$ grep -c 'select \* from "authors"' /tmp/query-after.log
1
```

| | 改前 | 改后 |
| --- | --- | --- |
| p95 | 2100ms | 180ms |
| p99 | 2430ms | 210ms |
| 吞吐 | 47 req/s | 588 req/s |
| SQL 条数 | 31 | 2 |

30 个 `author` 字段全被压进一条 `whereIn (...)`，重复的 `au_07` 也被缓存吃掉了，所以第二次 grep 出来是 `1`。588 req/s 这个数别太当真，本地 Docker、数据就 2000 来本、没开 TLS，数字好看主要是把 30 次往返省了；放到线上有网络抖动和连接池争用，我估摸着能落到 400 出头，这周还没排到压生产环境。

## 还没解决的

`alsoBought` 那块递归查询还是没加深度限制（4 月那篇就欠着），现在批量 loader 一上，深层查询更容易把 `whereIn` 撑成大 IN 列表，两件事叠一块有点慌。另外 `reviewCount` 在一次请求内会命中缓存，管理员后台刚审完一条评价、同一个请求里再读一次，拿到的还是旧数字；要不要在写操作之后 `clearAll()` 我还没定，清太狠又怕把刚省下来的批处理收益还回去。先停在这，等想明白「一次请求内的读一致性」到底要不要保证再说。
