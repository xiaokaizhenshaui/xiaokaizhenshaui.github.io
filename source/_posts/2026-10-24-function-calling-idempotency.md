---
title: "给大模型接工具调用，第一个坑还是幂等"
date: 2026-10-24
categories:
  - 大模型
tags:
  - 大模型
  - Agent
  - 幂等
lead: "模型一超时就把下单工具重发一遍，同一个用户连着落了两单。"
---

「有，帮您下了。」客服群里贴来的截图上，agent 回得挺干脆，可订单列表里躺着 `SO-20261023-00917` 和 `SO-20261023-00918` 两单——用户 `U-44021` 问的是一本库存只剩 2 册的书，两单 SKU 一样、收货地址一样、间隔 2 秒。2026-10-23 21:07 的事。我第一反应是有人手抖点了两次提交，翻工具调用日志才看到，两次都是模型自己发起的 `create_order`，中间夹着一条 `query_stock` 超时。

网关给模型侧设的是 8s 超时，那晚 `query_stock` 撞上库存服务 GC，8.4s 才回。超时之后模型按重试逻辑把上一轮没拿到结果的 tool_call 重发了一遍，可 `create_order` 其实已经执行成功了，只是响应没赶在超时前回去。它不知道，又发了一次。这跟 10-10 那篇写的上下文是两码事：上下文写得再清楚，也管不住模型超时重发。

## 客服 agent 接了哪几个工具

书店客服 agent 这版一共四个工具，出事的是后两个：

| 工具 | 作用 | 我 internal 标的分级 |
| --- | --- | --- |
| `query_book` | 按书名/ISBN 查书目 | read |
| `query_stock` | 查某 SKU 实时库存 | read |
| `create_order` | 按 SKU 和地址下单 | write |
| `query_order` | 查订单状态 | read |

给模型的定义走的是标准 function calling 格式，两个出事的工具长这样（省略了另外两个）：

```json
{
  "type": "function",
  "function": {
    "name": "create_order",
    "description": "按 SKU 创建订单。checkoutId 由结算页生成并随会话传入，模型不得自行生成或修改。",
    "parameters": {
      "type": "object",
      "properties": {
        "checkoutId": { "type": "string", "description": "结算单号，例如 CO-20261023-4412" },
        "sku": { "type": "string" },
        "quantity": { "type": "integer", "minimum": 1 },
        "addressId": { "type": "string" },
        "confirmed": { "type": "boolean", "description": "用户是否已点确认，默认 false" }
      },
      "required": ["checkoutId", "sku", "quantity", "addressId"],
      "additionalProperties": false
    }
  }
}
```

注意 `checkoutId` 那行说明，是第二版才补的，下面讲为什么。分级（`read` / `write`）我没塞进 JSON Schema——function calling 的 `parameters` 不放这种自定义字段，编进去等于给模型看一个它不认的东西——分级放在我自己那张工具注册表里，执行层按它决定要不要拦截。

## 第一版：单号让模型生成，重试直接穿了

第一版我做得很省事：`create_order` 的参数里有个 `orderNo`，让模型自己用「SO-日期-流水」拼一个，我拿这个 `orderNo` 当幂等键，Redis 里 `SETNX` 一下，重复就挡掉。逻辑看着没毛病，10-23 当晚就穿了：模型第一次拼了 `...917`，超时重试时重新拼了一个 `...918`，两个键根本不一样，SETNX 两次都返回成功，两单都落库。

那版还有个更隐蔽的问题：幂等键是 `orderNo`，可同一个 `orderNo` 换工具就失效——后来加 `query_order` 时我才发现键里没带工具名，万一以后两个工具共用一个单号会串。复盘时把这两条合起来，才定了现在的规则：**幂等键 = 工具名 + 业务单号，且业务单号必须由模型之外的上游生成、在进 agent 之前就定死，模型只负责原样透传**。结算页点「结算」时就生成 `checkoutId`，整轮会话带着它，模型重试几次都是同一个值。

（这个坑说穿了不值钱，但我第一版真就是那么写的，还跟同事争过「让模型生成单号更灵活」。争输了。）

## 幂等键 = 工具名 + 业务单号

执行层用 ioredis 5.4.1，写工具一律先抢锁再干活，抢不到就挡回去：

```ts
import Redis from "ioredis";

const redis = new Redis({ host: "127.0.0.1", port: 6379 });
const IDEMPOTENCY_TTL = 900; // 秒

type Level = "read" | "write";
interface ToolDef {
  name: string;
  level: Level;
  run: (args: Record<string, unknown>) => Promise<unknown>;
}

// error code 给程序看，message 给用户看
function refuse(code: string, message: string) {
  return { error: { code, message } };
}

export async function execute(
  tool: ToolDef,
  args: Record<string, unknown>,
  bizNo: string
): Promise<unknown> {
  if (tool.level === "write" && args.confirmed !== true) {
    return refuse("NEED_CONFIRM", "下单需要您再点一次确认，确认前不会真的提交");
  }

  const key = `idem:${tool.name}:${bizNo}`;
  // 只有写工具进幂等；只读工具每次都要拿最新值
  if (tool.level === "write") {
    // SET key value EX 900 NX：抢到返回 "OK"，抢不到返回 null
    const ok = await redis.set(key, "IN_FLIGHT", "EX", IDEMPOTENCY_TTL, "NX");
    if (ok !== "OK") {
      return refuse("DUPLICATE_CALL", "这笔已经提交过了，别重复下单");
    }
  }

  try {
    const result = await tool.run(args);
    return { data: result };
  } catch (e) {
    // 执行失败要把键放掉，否则用户改完参数也重试不了
    if (tool.level === "write") await redis.del(key);
    return refuse("TOOL_FAILED", "服务暂时没响应，请稍后再试");
  }
}
```

挨个说几个点：`redis.set(..., "EX", 900, "NX")` 是 ioredis 的写法，抢到返回字符串 `"OK"`，键已存在返回 `null`，靠这个挡第二次。`catch` 里 `del` 是回放时补的——第一版没删，一次下游失败把键占住 900 秒，用户改了收货地址再提交也被当成重复挡掉，客诉又多一条。`NEED_CONFIRM` 那层是写工具分级：模型第一轮拿到这个 error code，弹确认卡片给用户，用户点了才带 `confirmed: true` 重入，写操作不经过人工确认不落库。只读工具完全不进幂等，`query_stock` 每次都真查，免得库存变了还拿旧的。

error code 全用英文常量（`DUPLICATE_CALL` / `NEED_CONFIRM` / `TOOL_FAILED`），`message` 是给用户和客服看的中文，两边分开，日志里按 code 聚合，改文案不用动监控规则。

## 那晚它到底调了几次

把 10-23 全天的工具调用日志捞出来按 `checkoutId` 过一遍：

```bash
$ grep 'CO-20261023-4412' /var/log/book-agent/tool-call.log
2026-10-23T21:07:38.512Z INFO  callId=c-881 tool=query_stock  key=-                              status=TIMEOUT   cost=8402ms
2026-10-23T21:07:41.220Z INFO  callId=c-882 tool=create_order key=idem:create_order:CO-20261023-4412 status=EXECUTING
2026-10-23T21:07:41.884Z INFO  callId=c-882 tool=create_order status=OK orderNo=SO-20261023-00917
2026-10-23T21:07:43.901Z WARN  callId=c-884 tool=create_order key=idem:create_order:CO-20261023-4412 status=DUPLICATE_BLOCKED
```

`c-882` 41.884 就成功了，只是响应没赶在 8s 超时窗口里回去；`c-884` 是 2 秒后模型重发的那条，第二版里它会在 `redis.set` 那儿拿到 `null`，被 `DUPLICATE_BLOCKED` 挡住，不会再有 `...918`。回放 10-23 全天 1240 次调用，31 次是超时重发，其中 17 次落在 `create_order` 上；拿这 17 条灌进压测重放 200 次，改动前落 200 单，改动后只落 1 单。

## 留痕，和 900 秒那两个坑

每次调用（含被挡掉的）都落一张审计表，`checkoutId` + `tool_name` 上有唯一索引，应用层 SETNX 之外再兜一层库：

```sql
CREATE TABLE tool_call_audit (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  call_id         VARCHAR(32)  NOT NULL,
  tool_name       VARCHAR(32)  NOT NULL,
  biz_no          VARCHAR(64)  NOT NULL,
  status          VARCHAR(24)  NOT NULL,   -- EXECUTING / OK / DUPLICATE_BLOCKED / TOOL_FAILED
  latency_ms      INT          NOT NULL DEFAULT 0,
  created_at      DATETIME(3)  NOT NULL,
  UNIQUE KEY uq_biz_tool (biz_no, tool_name),
  KEY idx_created (created_at)
);
```

压测回放还揪出两个我没想到的问题。一个是 `IDEMPOTENCY_TTL = 900` 太短：有个用户 21:07 问完、21:29 才回来点确认，键早过期了，重入又放了一单，跟前面那次重复几乎一样。改成 86400 秒（24 小时）之后没再复现，长尾订单靠上面那张表的唯一索引兜底，不单靠 Redis。另一个更蠢：第一版我图省事给所有工具都套了 SETNX，`query_stock` 也被挡，库存从 3 变 2 了它还拿 900 秒前的旧值回「有货」——只读工具不进幂等这条，是被这个 bug 逼出来的。

`redis-cli` 里直接验 SETNX 很直观，第二次返回 `(integer) 0`：

> `redis-cli SET "idem:create_order:CO-20261023-4412" "IN_FLIGHT" NX EX 900` → `(integer) 1`；再执行一次 → `(integer) 0`。

写工具现在要人工确认，可客服那边的产品嫌多一次点击，想对「老用户 + 单价低」的单子自动放行，我没松口——一松口等于把幂等从「确认前不落库」退回到「靠 SETNX 兜」，而 SETNX 那层已经证明过挡不住模型换单号。另一个没想清楚的：模型超时重发的判定现在在网关，8s 一刀切，库存服务那次 GC 是 8.4s，要是哪天 GC 到 15s，重试会更密，幂等键的 24h 够不够、要不要按订单状态而不是按时长判重，还没定。10-23 那批慢调用按耗时分完桶，8s 这一刀该切在哪，我心里还是没谱。
