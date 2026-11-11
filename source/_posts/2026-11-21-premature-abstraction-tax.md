---
title: "三个长得一样的 resolver，我忍住没合并"
date: 2026-11-21
categories:
  - 架构思考
tags:
  - 架构思考
  - 抽象
  - 复杂度
lead: "评审说这三段重复了，我点头，然后忍了整整两个礼拜。"
---

翻 PR 的时候看到一条评论：这三个 resolver 长得一模一样，抽一个公共的吧。我点头，回了个"好，回头改"。然后这两个礼拜我一遍遍打开那三个文件，又一遍遍关上，没动。拖着不动的原因挺简单：越看越觉得那句"一模一样"有点骗人。

`catalog` 的 `books`、`ordering` 的 `orders`、`inventory` 的 `stockItems`，三个 GraphQL query 确实是一个模子：解析 `page`/`size`、拼 `offset`/`limit`、调各自的 repo、把数据库异常翻成 `GraphQLError`。骨架看着能叠在一起。可它们往后的改法我大概能猜到——`orders` 迟早要加"只看本人"和按 status 过滤，`stockItems` 要按仓库维度聚合，`books` 得接在售状态和上下架时间。三处现在像，命门不在一处。

再往下看就散了。`books` 得先过滤 `deletedAt` 和上下架时间，`orders` 默认按 `createdAt` 倒序、还卡一个"只看本人"，`stockItems` 要按 `warehouseId` 分组。三份代码真正重叠的，只有开头算 `offset`/`limit` 的几行和末尾那个 `try/catch`，中间那些过滤条件一份比一份多。评审瞄一眼说"一模一样"，瞄的是骨架；我天天改的恰好是中间那些。当时没动，就是拿不准这些条件往后会长到一块去，还是各长各的。

## 那三份重复

`catalog` 的 `books` 那份长什么样，我尽量说细：从 `args` 里取 `page`、`size`，`Math.min` 卡到 50，`ctx.bookRepo.list` 传 `offset`/`limit`，`catch` 里抛一个带 `CATALOG_QUERY_FAILED` 的 `GraphQLError`。`orders` 那份把 repo 换成 `orderRepo`、错误码换成 `ORDER_QUERY_FAILED`，中间多一行 `listMine(ctx.user.id, ...)`；`stockItems` 换成 `stockRepo`、按 `warehouseId` 先分个组。三份九十来行，读一份就懂三份，谁出问题改谁，另外两份一点不沾，这点我后来才体会到有多值钱。

重复这两个字在评审里太好用了。三份里都写了 `Math.min(args.size ?? 20, 50)`，就有人喊重复；可这行背后的决定——单页最多 50 条、默认 20 条——是产品定的，三处一致恰恰是对的，抽不抽都一样。真正让我犹豫的是另一类：三个 `catch` 翻错误码的写法，那才可能各写各的、漏掉一种异常。把"长得像"和"会一起变"混成一件事，是我这回差点踩的坑。下面这块把抽之前和抽之后摆一起，看得更直。

## BaseResolver 和六个开关

忍到第三周，我还是没扛住，抽了。写了个 `makeListResolver`，想着传个 repo 加一组开关就能覆盖三种情况。结果为了把那点差异塞进去，`Options` 里长出了六个布尔：`withDeleted`、`withSnapshot`、`requireAuth`、`withLock`、`flatten`、`traceSql`，每个配一段 `if`。

六个开关是慢慢攒起来的，被三个用例一个个逼出来。`orders` 要校验登录、`books` 不用，这一处逼出了 `requireAuth`；`books` 要连下架书一起看，就有了 `withDeleted`；改价那次 `PriceSnapshot` 的锁价查询，对应 `withSnapshot`；`stockItems` 扣减时的 `FOR UPDATE` 留给 `withLock`，它按 `warehouseId` 分组后还得把内层数组摊平，于是多一个 `flatten`。`traceSql` 最没道理，纯粹是我调试时顺手留的。每接一个用例就往 `Options` 加一个布尔、往函数体塞一段 `if`，加到第六个，这函数已经不认识自己了，`flatten` 那个我隔一周回来看都得猜半天它展平了什么。

```ts
// ===== 抽之前：src/catalog/book.resolver.ts（三份同形，另两份只换 repo 与错误码）=====
import { GraphQLError } from 'graphql';
import type { Context } from '../platform/context';

export const bookQuery = {
  books: async (_: unknown, args: { page?: number; size?: number }, ctx: Context) => {
    const page = args.page ?? 1;
    const size = Math.min(args.size ?? 20, 50);
    try {
      return await ctx.bookRepo.list({ offset: (page - 1) * size, limit: size });
    } catch (e) {
      throw new GraphQLError('书籍列表查询失败', {
        extensions: { code: 'CATALOG_QUERY_FAILED' },
      });
    }
  },
};

// ===== 抽之后：src/platform/base.resolver.ts（沿用上面两个 import）=====
type Options = {
  withDeleted: boolean;
  withSnapshot: boolean;
  requireAuth: boolean;
  withLock: boolean;
  flatten: boolean;
  traceSql: boolean;
};

export function makeListResolver(repoKey: keyof Context, opts: Options) {
  return async (_: unknown, args: { page?: number; size?: number }, ctx: Context) => {
    const size = Math.min(args.size ?? 20, 50);
    const offset = ((args.page ?? 1) - 1) * size;
    if (opts.requireAuth && !ctx.user) {
      throw new GraphQLError('请先登录', { extensions: { code: 'UNAUTHENTICATED' } });
    }
    const repo = ctx[repoKey] as { list(q: Record<string, unknown>): Promise<unknown[]> };
    const query: Record<string, unknown> = { offset, limit: size };
    if (opts.withDeleted) query.includeDeleted = true;
    if (opts.withSnapshot) query.withPriceSnapshot = true;
    if (opts.withLock) query.forUpdate = true;
    if (opts.traceSql) ctx.logger.debug('list query', query);
    try {
      const rows = await repo.list(query);
      return opts.flatten
        ? rows.flatMap((r) => (r as { items?: unknown[] }).items ?? [r])
        : rows;
    } catch (e) {
      throw new GraphQLError('列表查询失败', { extensions: { code: 'LIST_FAILED' } });
    }
  };
}
```

它跑得起来。行数从九十变成一百出头，我愣了一下，本来以为抽完会少。真正麻烦的在后面：有天给 `orders` 加一个 status 过滤，我得先读 resolver 的装配、再读 `makeListResolver` 的分支、钻进 base 单测里那六种开关组合，绕回 repo，四层。`books` 和 `stockItems` 明明没这个需求，却因为 base 改了签名，两个装配点跟着一起动。

## 退回

又过了十来天，我把它删了，退回三份直白代码。只把两件半年没变过、背后又是同一件事的东西摘出去：分页参数怎么算，数据库异常怎么翻成 `GraphQLError`。删的时候比写的时候痛快：`base.resolver.ts` 整个删掉，六个布尔和函数体里六段 `if` 一起没了，`paginate` 和 `toGraphQLError` 留在 `platform`，加起来二十行出头，两件都不碰业务。base 那六处单测也删了，换回三份各管各的测试，mock 从六样退回两样。

```ts
// 退回之后：src/platform/resolver.helpers.ts + src/ordering/order.resolver.ts
import { GraphQLError } from 'graphql';
import type { Context } from '../platform/context';

export function paginate(args: { page?: number; size?: number }) {
  const page = Math.max(args.page ?? 1, 1);
  const size = Math.min(Math.max(args.size ?? 20, 1), 50);
  return { offset: (page - 1) * size, limit: size };
}

export function toGraphQLError(e: unknown, code: string) {
  return new GraphQLError('查询失败，请稍后再试', {
    extensions: { code, cause: String(e) },
  });
}

export const orderQuery = {
  orders: async (
    _: unknown,
    args: { page?: number; size?: number; status?: string },
    ctx: Context,
  ) => {
    const { offset, limit } = paginate(args);
    try {
      return await ctx.orderRepo.listMine(ctx.user.id, { offset, limit, status: args.status });
    } catch (e) {
      throw toGraphQLError(e, 'ORDER_QUERY_FAILED');
    }
  },
};
```

`listMine` 带不带 `status`、要不要锁，全写在这一份里，不用问别人。加那个 status 过滤，我只动了 `order.resolver.ts` 一个文件。

## 一笔能算的账

我把这三次的数记了一下，不凭感觉吵：

| | 抽之前（三份重复） | 抽之后（BaseResolver） | 退回之后 |
| --- | --- | --- | --- |
| 给 orders 加 status 要动的文件 | 1 | 3（base、order 装配、base 单测） | 1 |
| 读代码要穿几层 | 1 | 4 | 2（resolver、helper） |
| 单测里要 mock 的东西 | 2（repo、ctx） | 6（六个开关加 user、logger） | 2 |
| 三处合计行数 | 约 90 | 约 100 | 约 74 |

行数那栏最没用，抽完反而多了十行。抽象省下来的是行数，这笔我认；它另收一份理解税，按"读几层、动几个文件"计，我那次光盯着行数，差点把这份税当成便宜。

读四层那栏值得拆开看。从 resolver 装配传进去的 `Options` 算起，往下是 `makeListResolver` 里按开关分的那几段 `if`，再往下才轮到某个 repo 怎么解释 `query` 里 `includeDeleted` 这类键，真到 SQL 已经是第四层了。改一个 status 过滤，这四层得在脑子里过一遍才敢下手。退回之后只留 resolver 和 `paginate`，`status` 直接写进 `listMine` 的调用里，眼睛不用跳。mock 那六个也麻烦：`requireAuth` 要造 `ctx.user`，`traceSql` 要塞 `logger`，六个布尔组合出好几种测法，单测比实现还难读。

Rule of Three 我没照字面用。书上那句是"第三次出现就重构"，我实际卡的是另一个问题：这三处往后会不会朝同一个方向改。`books`、`orders`、`stockItems` 只是骨架撞了，要加的过滤条件一个比一个不一样，那就还不到时候。不确定的时候，我宁可先让重复留着，它顶多多占几行，不会让人读四层。

## 有一处后来还是合了

有一处我到底还是合了。三个模块各自有一段"把 PostgreSQL 唯一键冲突翻成业务错误"的 `catch`，逐字一样，背后都是同一个错误码 `23505`，半年里谁都没动过。后来并进了 `toGraphQLError` 的一个分支，判断 `e.code === '23505'`。我肯合它，条件凑齐了才动：三处得逐字相同，背后得是同一个外部契约，而且得放上半年没人碰过。骨架像不算数，得是命门也长在一处。

另一处到今天还分着。三个模块各埋了一行 `logger.info` 打查询耗时，`catalog` 带 `isbn`，`ordering` 带 `userId`，`billing` 带 `invoiceNo`，长得几乎一样，我没合。合了就得在一个通用函数里给三种字段开可选参数，省下那三行，换一个谁都得读一眼的函数，不划算。跟那三个 `catch` 的分别就一条：那三处连带的字段、连带的错误码都一模一样，这三处各带各的上下文。

反正那三份重复，现在还并排躺在 `catalog`、`ordering`、`inventory` 三个目录里，谁也没再提抽的事。
