---
title: "给 GraphQL 接上 OpenTelemetry，终于看清一次请求慢在哪"
date: 2026-09-05
categories:
  - 全栈开发
tags:
  - 全栈开发
  - 可观测性
  - GraphQL
lead: "1.8 秒的查询，慢日志里为什么一条都抓不到？31 条 SQL 串着跑，插完桩才看见，改完 210ms。"
---

9 月 2 号下午 3 点 40，监控截图丢进群里：`/graphql` 的 P99 从 300ms 跳到 1.8s，前端补了句「列表页转得能去泡杯茶」。我第一反应是慢查询，翻 MySQL slow log，干干净净，没有一条超过 100ms。应用日志里更省事，一次请求就两行：

> `15:41:07.203 INFO  开始处理 featuredBooks`
> `15:41:09.015 INFO  featuredBooks 完成，耗时 1812ms`

中间那一秒八是黑的。机器 `node -v` 是 `v20.11.1`，`@apollo/server` 锁在 `4.10.0`，`graphql` `16.9.0`，跟 4 月重写 Schema 时一模一样，没升过级。

## 两天里我都试了什么

先是加 `console.time`，从 6 处加到 11 处，一次请求打出来 200 多行日志，时间片互相叠着，还得拿计算器减。删了。又试了装某个 APM 的 Node agent，它默认按 HTTP 路由聚合，`/graphql` 全站就一个路由，聚合出来还是一条 1.8s 的粗柱子，等于没看。那个 agent 还把 `graphql` 包的 `execute` 给 patch 了，启动直接报 `TypeError: Cannot read properties of undefined`，卸了才恢复。

第二天才想明白：GraphQL 的耗时藏在 operation 和 field 这两层，盯「一个接口」看不出来。要的是一次请求内部的时间去哪了，得有 trace，得能按 `operationName` 拆开。于是上 OpenTelemetry，JS SDK 锁在 `@opentelemetry/api` `1.9.0` + `sdk-node` `0.52.1` 这套——不是最新的，但生产上不想跟着 2.x 的迁移一起动，先求稳。

还有个更蠢的：我把 `slow log` 的 `long_query_time` 从 1 降到 0.05，抓了一下午，一条都没多出来。事后看 trace 才明白，31 条 SQL 每条 40 多毫秒，谁都够不上慢查询阈值，慢的是「串着跑 31 次」这件事本身。单条都快、加起来慢，是最难从慢日志里看出来的一种，日志里压根不会留下「调用了 31 次」这种信息。

## 插桩：Apollo Server 4 的 plugin 挂在哪

第一版偷懒，直接 `getNodeAutoInstrumentations()` 全开，里头的 `@opentelemetry/instrumentation-graphql` 默认给每个 resolver 建 span。跑了一次 `featuredBooks(limit:30)`，Jaeger 里一条 trace 出来 340 多个 span，导出体积从 14 KB 涨到 486 KB，`docker stats` 看着 collector 容器内存从 300 MB 一路顶到 1.7 GB，然后被 kill。峰值 QPS 才 60，全采一天就是 2 TB 多的 span 数据，这谁扛得住。

改成自己写 Apollo plugin：只建 operation 级别的 span，可疑字段手动加，field-level 全关。

```ts
// src/telemetry.ts
// 启动：npx tsx --import ./src/telemetry.ts src/server.ts
import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { Resource } from '@opentelemetry/resources';
import { ParentBasedSampler, TraceIdRatioBasedSampler } from '@opentelemetry/sdk-trace-base';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { context, trace, SpanStatusCode, type Context, type Tracer } from '@opentelemetry/api';
import type { ApolloServerPlugin } from '@apollo/server';

const SERVICE_VERSION = '1.4.2';

const sdk = new NodeSDK({
  resource: new Resource({
    'service.name': 'bookstore-graphql',
    'service.version': SERVICE_VERSION,
  }),
  traceExporter: new OTLPTraceExporter({
    url: process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT ?? 'http://127.0.0.1:4318/v1/traces',
  }),
  instrumentations: [
    getNodeAutoInstrumentations({
      '@opentelemetry/instrumentation-fs': { enabled: false },
      '@opentelemetry/instrumentation-graphql': { enabled: false },
    }),
  ],
  sampler: new ParentBasedSampler({ root: new TraceIdRatioBasedSampler(0.2) }),
});
sdk.start();

const tracer: Tracer = trace.getTracer('bookstore-graphql', SERVICE_VERSION);

export interface AppContext {
  traceId: string;
  spanContext: Context;
}

export function createTracingPlugin(): ApolloServerPlugin<AppContext> {
  return {
    async requestDidStart(rc) {
      const opName = rc.request.operationName ?? 'anonymous';
      const span = tracer.startSpan(
        `graphql.${opName}`,
        { attributes: { 'graphql.operation.name': opName } },
        context.active(),
      );
      rc.contextValue.traceId = span.spanContext().traceId;
      rc.contextValue.spanContext = trace.setSpan(context.active(), span);
      return {
        async didEncounterErrors(errCtx) {
          span.setStatus({ code: SpanStatusCode.ERROR, message: 'GRAPHQL_ERROR' });
          span.setAttribute('graphql.error.count', errCtx.errors?.length ?? 0);
        },
        async willSendResponse() {
          span.end();
        },
      };
    },
  };
}

// 只给可疑字段手动加 span，别全开
export function withFieldSpan<T>(ctx: Context, name: string, fn: () => Promise<T>): Promise<T> {
  return context.with(ctx, () =>
    tracer.startActiveSpan(name, async (child) => {
      try {
        return await fn();
      } catch (err) {
        child.setStatus({ code: SpanStatusCode.ERROR });
        child.recordException(err as Error);
        throw err;
      } finally {
        child.end();
      }
    }),
  );
}
```

`--import` 是 Node 20.6 以后才有的，作用是把 `sdk.start()` 抢在所有业务模块前面执行，不然 auto instrumentation 来不及 patch `http` / `mysql2`。`server.ts` 那边就三处改动：`new ApolloServer<AppContext>({ typeDefs, resolvers, plugins: [createTracingPlugin()] })`，`context: async () => ({ traceId: '', spanContext: context.active() })`，以及给 `BookDetail.author` 套一层 `withFieldSpan(ctx.spanContext, 'resolver.BookDetail.author', () => loadAuthorBrief(book.authorId))`。

`spanContext` 存进 contextValue 是为了让手动加的子 span 挂在 operation span 下面，而不是和它平级挂在 HTTP span 上。第一版我没存，Jaeger 里 31 条 SQL 全散在顶层，看不出是谁打出来的。

Apollo Server 4 的 plugin 钩子挺多，`parsingDidStart`、`validationDidStart`、`executionDidStart` 都能挂，我第一版每个都建了 span，一条简单查询又是十几个。索性只留 `requestDidStart` 里那一个 operation span，解析和校验的耗时并进去不单列——真要查解析慢，再临时开。手动加 span 的字段现在只有 3 个：`BookDetail.author`、`BookDetail.topReviews`、`Query.featuredBooks`，都是历史上出过问题的，其余字段不占额度，真慢起来再加。全开撑爆 Collector、只挑几个又怕漏，这个粒度没找到舒服的中间值，先按这份短名单用着。

## Collector 和 compose

Collector 用 `otel/opentelemetry-collector-contrib:0.102.1`，OTLP 收、批量发，后端先接 Jaeger `1.57`。`debug` exporter 开着，本地排查全靠它往终端吐：

```yaml
# otel/collector.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 25
  batch:
    timeout: 5s
    send_batch_size: 512

exporters:
  otlp/jaeger:
    endpoint: jaeger:4317
    tls:
      insecure: true
  debug:
    verbosity: normal

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp/jaeger, debug]
```

```yaml
# docker-compose.otel.yaml
services:
  jaeger:
    image: jaegertracing/all-in-one:1.57
    environment:
      COLLECTOR_OTLP_ENABLED: "true"
    ports:
      - "16686:16686"

  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.102.1
    command: ["--config=/etc/otelcol-contrib/config.yaml"]
    volumes:
      - ./otel/collector.yaml:/etc/otelcol-contrib/config.yaml:ro
    ports:
      - "4317:4317"
      - "4318:4318"
    depends_on:
      - jaeger
```

`docker compose -f docker-compose.otel.yaml up -d`，然后带 `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces` 起服务。第一次我把 compose 里的 `4318` 漏写成 `4317`，`debug` 里啥也没有，终端干等了十分钟，`curl -v http://127.0.0.1:4318/v1/traces` 才报 `Connection refused`。这种小破事记一下。

`memory_limiter` 放在 `batch` 前面不是随手写的，Collector 文档要求它当第一个 processor，不然批量攒到一半才想起来限内存，已经晚了。第一次我调成 `batch, memory_limiter`，压测时还是被 kill 了一次，换回来才稳。`COLLECTOR_OTLP_ENABLED=true` 也别漏，Jaeger 1.57 默认不开 OTLP 接收，漏了的话 collector 那侧会一直报 `connection refused`，而 Jaeger UI 里干干净净，特别容易误判成「没流量」。这两个坑各花了我二十分钟。

## 一段 trace 输出

插完桩后重放那条 `featuredBooks(limit:30)`，从 Jaeger 的 `/api/traces` 导出来（删掉 `processes` 和 `warnings`，`duration` 单位是微秒）：

```json
{
  "data": [
    {
      "traceID": "5b8efff798038103d269b633813fc60c",
      "spans": [
        { "spanID": "3f9c1a02b7e4d5a8", "operationName": "HTTP POST /graphql", "duration": 1816300 },
        { "spanID": "7b21e0c4d8a3f619", "operationName": "graphql.featuredBooks", "duration": 1812034, "references": [{ "refType": "CHILD_OF", "spanID": "3f9c1a02b7e4d5a8" }] },
        { "spanID": "c05d3e8f1a2b4967", "operationName": "resolver.BookDetail.author", "duration": 1479000, "references": [{ "refType": "CHILD_OF", "spanID": "7b21e0c4d8a3f619" }] },
        { "spanID": "e18a7b4c2d9f0351", "operationName": "mysql.query", "duration": 44000, "references": [{ "refType": "CHILD_OF", "spanID": "c05d3e8f1a2b4967" }], "tags": [{ "key": "db.statement", "value": "SELECT id, name FROM authors WHERE id = ?" }] },
        { "spanID": "a4d70c19e2b85f36", "operationName": "mysql.query", "duration": 47000, "references": [{ "refType": "CHILD_OF", "spanID": "c05d3e8f1a2b4967" }], "tags": [{ "key": "db.statement", "value": "SELECT id, name FROM authors WHERE id = ?" }] }
      ]
    }
  ],
  "total": 1,
  "errors": null
}
```

`resolver.BookDetail.author` 一个字段吃掉 1.479s，底下是 31 条一模一样的 `SELECT ... FROM authors WHERE id = ?` 串着跑——4 月重写 Schema 时我自己记过「`loadAuthorBrief` 暂时还是一条 SQL 一本书，列表页会打出 31 条」，当时只记了句「N+1 那摊回头收拾」，结果拖到 9 月才真看见它长什么样。换成 DataLoader 批量（`WHERE id IN (...)`，一条 30ms），同样的查询从 1812ms 掉到 210ms，P99 跟着回到 260ms 上下。

采样率我压到 0.2（`ParentBasedSampler` 包 `TraceIdRatioBasedSampler`）：单条 trace 回到 14 KB，按 60 QPS 算一天约 12 GB span 数据，Jaeger 留 3 天还能接受。0.2 是拍的，试过 0.05，慢请求一天只能捞到两三条，不够看；也试过 1.0，就是上面 1.7 GB 那次。

## traceId 进日志，顺带把文案规矩又踩了一遍

plugin 里把 `traceId` 塞进 `contextValue` 之后，日志就能和 trace 对上了：

> `{"level":"info","traceId":"5b8efff798038103d269b633813fc60c","msg":"没找到这本书，可能已经下架了","bookId":"bk_1042"}`

拿这串 32 位 hex 直接粘进 Jaeger 搜索框，那次请求的完整链路就出来了，比以前翻时间戳方便太多。

这里我又把 4 月定下的那条规矩踩了一遍。第一版图省事，span 名写成 `解析书籍详情`、错误码写成 `书籍没找到`，Jaeger 按 `operationName` 聚合时中文名和英文名混成一团，前端拿 `extensions.code` 分流也得分两套判断。后来在 README 里写死：**span 名、attribute key、错误码、日志里的结构化字段全用英文**（点分命名，`graphql.featuredBooks`、`BOOK_NOT_FOUND`、`GRAPHQL_ERROR`），**只有真正弹给用户看的那句话和日志里给人看的描述用中文**。日志的 `msg` 是给人看的所以用中文，`level`、`traceId`、`bookId` 是机器读的用英文标识符。分类器倒是好写：看这个字符串最后会被谁消费，被人消费就中文，被代码消费就英文。

以前客服转一个用户报障过来，只有一句「下午三点多下单失败」，我得拿时间戳去几台机器的日志里翻，运气不好翻半小时。现在让他们把页面角落里那串 traceId 一起复制过来，粘进 Jaeger 就是完整链路。日志本身是 JSON 一行一个事件，`traceId` 挂在顶层字段上，检索时能直接按它聚合，不用再从 `msg` 里正则抠。顺带把 4 月那篇里 `BOOK_NOT_FOUND` 的例子翻出来核了一遍，`message` 还是中文、`code` 还是英文，没走样。

head sampling 的采样决策在 span 创建那一刻就定了，`didEncounterErrors` 里想「报错了就强制采下来」已经来不及，现在偶尔一个 500 因为没被采中，Jaeger 里查不到，只能靠日志里那行 `traceId` 干瞪眼。Collector 的 `tail_sampling` processor 能按 duration 和状态码事后决定留哪些，但前提是同一个 trace 的所有 span 得落到同一个 collector 实例，多副本要再配一层 `load_balancing` exporter。我们现在单副本，先凑合。

`featuredBooks` 换成批量查之后，`alsoBought` 那个递归字段还是没加深度限制。4 月记下的账，到 9 月还没还上，说起来也挺不好意思的。
