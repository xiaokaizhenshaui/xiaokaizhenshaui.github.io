---
title: "ES 翻到第 800 页报错，search_after + PIT 怎么落地"
date: 2026-10-17
categories:
  - 中间件
tags:
  - ElasticSearch
  - 分页
  - 搜索
lead: "后台导出按 from+size 翻到第 800 页被 max_result_window=10000 拍回来，换成 PIT + search_after 后 42 万条订单 3 分钟导完，中间还踩了排序不唯一的坑。"
---

10 月 15 号上午 10:12，运营跑那个「导出全部订单」的任务，日志里啪地一行红：

> `{"error":{"root_cause":[{"type":"query_phase_execution_exception","reason":"Result window is too large, from + size must be less than or equal to: [10000] but was [16000]. See the scroll api for a more efficient way to request large data sets. This limit can be set by changing the [index.max_result_window] index level setting."}],"type":"search_phase_execution_exception"},"status":400}`

一页 20 条，第 800 页就是 `from=15980`，`15980+20=16000`，正好顶到 `index.max_result_window` 默认那 10000。ES 集群 `8.13.4`，索引 `orders` 三个主分片，导出服务用的是 `co.elastic.clients:elasticsearch-java:8.13.4`。第一版思路特别朴素：既然报错说能改 `max_result_window`，那就 `PUT /orders/_settings {"index.max_result_window": 200000}` 呗。改完是不报错了，可导到后面越来越慢，第 700 页单页就要 1.8s，全量跑完要二十几分钟，运营等不及直接把任务杀了。

## from+size 为啥越翻越慢

这不是参数小气，是机制本身扛不住深分页。ES 是分片的，`from=15980, size=20` 这个请求发到协调节点后，**每个分片**都得在本地维护一个能装 `from+size` 条（也就是 16000 条）的优先队列，把命中的文档排好序、丢掉前 15980 条、留下最后 20 条回传。3 个分片就是 3×16000 = 48000 条文档在内存里排一遍，协调节点再把 3 份结果归并。翻到 `from=999980` 那种量级，每个分片要抱住一百万条，堆和 CPU 一起炸。所以 `from+size` 天生适合「前几页」，越往后成本线性涨，跟 10000 这个阈值无关——把阈值调到 20 万只是把撞墙的点往后挪，没解决慢。

（顺带一提，报错里那句 `See the scroll api` 是老版本留下的建议，现在官方更推 PIT + search_after；scroll 每次要维护上下文、还不适合实时翻页，别照着那句去用 scroll 了。）

我后来 `GET /orders/_settings?include_defaults=true&filter_path=**.max_result_window` 拉过一次，确认就是 `10000`，没人动过这个索引。想靠调大阈值蒙混过关的念头就此断了——真把 `index.max_result_window` 改成 200000，等于允许每个分片抱住二十万条文档排序，三个分片六十万条堆在协调节点，OOM 只是时间问题，比报错更难查。

## 第一版：排序不唯一，翻页丢数据

我先把导出改成 `search_after`，想着比 from+size 高级点。排序只写了 `created_at asc`，跑了几十条发现有订单重复出现、又有几条压根没导出来。原因是 `search_after` 靠「上一页最后一条的排序值」当游标定位下一页，排序键不唯一时，同一毫秒里十几条 `created_at` 完全一样，游标落回去就分不清谁是谁，跳页、重复全来了。

补唯一键时我又绕了一下：第一反应加 `_id` 当第二排序，结果 8.x 的 `_id` 默认没开 fielddata，拿它排序直接被拒（这个字段本来就不推荐拿来排序）。后来换成 `_shard_doc`——它是 PIT 自带的、每个分片内单调递增的隐藏排序键，天然唯一，专门给 search_after 当 tiebreaker 用，配上 PIT 正好。排序最终写成 `created_at asc, _shard_doc asc`。

## PIT 是干啥的，keep_alive 又管什么

普通 `search_after` 直接查活索引，翻页期间要是有新订单写进来、或者 segment 做了 merge，前面的排序视图就变了，可能漏也可能重。PIT（point in time）先把这一刻的 Lucene segment 视图「冻」住，后面所有翻页都基于这同一份快照，跟期间的写入隔离。`keep_alive` 是这份快照的存活时间，比如 `5m`，而且**每次带着 PIT 查都会顺延**，不是开一次就固定 5 分钟到期。代价是这些 segment 被占着不释放，堆和文件句柄都吃，所以导完必须显式关掉。

还有个容易忽略的点：`_shard_doc` 只有开着 PIT 时才能用，普通查询里写它 ES 会报不认识这个排序字段。我第一版试 DSL 的时候没带 `pit`，光把 sort 改成 `_shard_doc asc`，直接 400，还以为是拼写错了，回头才想起来它跟 PIT 是绑定的。另外 PIT 是某一刻的逻辑视图，配 `preference`、`routing` 那套在这儿不起作用，别混着写。

三段 DSL 我按 Kibana 控制台的写法贴，第一行是请求行，下面是 JSON。

开 PIT，请求体是空的，返回的 `id` 后面每次都要带上：

```json
POST /orders/_pit?keep_alive=5m

// 响应
{
  "id": "46ToAwMDaWR5X3Rlc3RQSVQAAAAAAAAA..."
}
```

带 PIT 翻页。用了 PIT 就不在路径里写索引（`GET /_search`），`sort` 里那个 `_shard_doc` 别漏，`search_after` 把上一页最后一条的 `sort` 值原样塞回来：

```json
GET /_search
{
  "size": 20,
  "pit": {
    "id": "46ToAwMDaWR5X3Rlc3RQSVQAAAAAAAAA...",
    "keep_alive": "5m"
  },
  "query": { "match_all": {} },
  "sort": [
    { "created_at": "asc" },
    { "_shard_doc": "asc" }
  ],
  "search_after": [ 1728950400000, 12345 ],
  "track_total_hits": false
}
```

用完释放，不然后台一直替你养着这些 segment：

```json
DELETE /_pit
{
  "id": "46ToAwMDaWR5X3Rlc3RQSVQAAAAAAAAA..."
}
```

> 第一页不要带 `search_after`（我第一版图省事塞了个 `[]`，ES 直接回 400，说 `search_after` 的值个数和 sort 对不上），从第二页起才把上一页 `hits.hits` 最后一条的 `sort` 数组填进去。

`track_total_hits: false` 是顺手关掉总数统计，导出场景根本不关心「一共多少条」，深分页下能省掉一圈计数开销。

## Java 客户端怎么串起来

```java
// co.elastic.clients:elasticsearch-java 8.13.4
ElasticsearchClient client = ...;   // 已配好 RestClientTransport

OpenPointInTimeResponse pit = client.openPointInTime(b -> b
        .index("orders")
        .keepAlive(t -> t.time("5m")));
String pitId = pit.id();
List<FieldValue> cursor = null;     // 上一页最后一条的 sort 值
List<Order> exported = new ArrayList<>();

try {
    while (true) {
        SearchRequest.Builder req = new SearchRequest.Builder()
                .pit(p -> p.id(pitId).keepAlive(t -> t.time("5m")))
                .size(500)
                .query(q -> q.matchAll(m -> m))
                .sort(s -> s.field(f -> f.field("created_at").order(SortOrder.Asc)))
                .sort(s -> s.field(f -> f.field("order_id").order(SortOrder.Asc)));
        if (cursor != null) {
            req.searchAfter(cursor);   // 第一页不带
        }
        SearchResponse<Order> resp = client.search(req.build(), Order.class);

        List<Hit<Order>> hits = resp.hits().hits();
        if (hits.isEmpty()) {
            break;
        }
        for (Hit<Order> h : hits) {
            exported.add(h.source());
        }
        cursor = hits.get(hits.size() - 1).sort();
        log.info("已导出 {} 条，游标 {}", exported.size(), cursor);
    }
} catch (Exception e) {
    throw new RuntimeException("导出中断，PIT " + pitId + " 记得释放", e);
} finally {
    // 别赌 keep_alive 自己过期，导完立刻关
    client.closePointInTime(c -> c.id(pitId));
}
```

`size` 我从 20 提到 500，少了几十倍的请求往返；`cursor` 直接取 `hits` 最后一条的 `sort()`，类型就是 `List<FieldValue>`，不用自己拼。Java 这边的第二排序我用了文档里本来就有、且唯一的 `order_id`（keyword），没用 DSL 里的 `_shard_doc`——后者是 PIT 才有的特殊键，客户端里得单独构造，我懒得折腾，反正 search_after 只要求排序组合整体唯一，`created_at + order_id` 一样够用。异常消息写成中文是因为这条会直接透到运营后台的报错弹窗里，给个能看懂的提示比一串 stacktrace 强。`finally` 里关 PIT 是硬性习惯——我有一版把 `closePointInTime` 写在正常流程末尾，中途抛异常就跳过了，隔天发现 ES 上挂着七八个没释放的 PIT，`_cat/segments` 里一堆老 segment 下不掉。

## 改前改后

| | 改前 from+size | 改后 PIT + search_after |
| --- | --- | --- |
| 第 800 页 | 直接 400，`[16000]` 超窗 | 正常返回 |
| 单页耗时（深页） | 1.8s 且随页数涨 | 稳定 30~40ms |
| 42 万条全量 | 跑不完，被杀 | 3 分 12 秒 |
| 翻页期间新写入 | 视图会变，可能漏 | PIT 快照隔离，稳 |

## 还没解决的

`search_after` 只能往后一页页走，运营偶尔要「直接跳到第 900 页」这种需求它给不了，得配合别的方式（比如按时间切片分批），这块还没做。还有 `keep_alive=5m` 是按我本地全量 3 分钟估的，真碰到数据量翻十倍、导出中途卡一下，PIT 可能过期报 `search_context_missing_exception`，到时候要么把 keep_alive 调大、要么做续期重试。下次想试试拿 `slice` 做并行导出，看能不能把 3 分钟再压一压。
