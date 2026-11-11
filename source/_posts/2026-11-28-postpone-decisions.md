---
title: "把决定往后推，是我今年最划算的一次偷懒"
date: 2026-11-28
categories:
  - 架构思考
tags:
  - 架构思考
  - 演进式设计
  - 技术选型
lead: "年初那张草图上画了四个方框，现在回头看，幸亏一个都没照着做。"
---

年初那张草图上，订单库我写的是 MongoDB，旁边画了四个方框，标着 order、catalog、stock、bill，中间拿箭头连了一圈，意思是一上来就拆微服务。那会儿手上就几十行建表 SQL、一张 ER 草稿，连"订单下了之后能不能改价"都还没定。我差点就照着它开工，连 `docker-compose` 里 mongo 的镜像版本都填好了。

拦住我的说不上什么深思熟虑。那份草图自己就站不住：四个方框画完，我没法回答"扣库存和落订单要不要在一个事务里"这个问题。答不上来，就没法定库、更没法定边界。于是我把那张图塞进抽屉，先按 PostgreSQL 单体写着，心里给那几个没想好的决定各记了一笔账。

## 哪些决定贵

后来我慢慢分清楚了，决定的价钱不看它听起来多大，看改起来要动什么。贵的是动了就要碰已落库的数据、或者碰别人已经在解析的契约那几样。往细了数，schema 字段名、订单 ID 格式、GraphQL 对外暴露的字段，还有 Kafka 事件 `OrderPlaced` 的 payload，都算；这几样一旦有第三方或者别的模块对上了，改一次得连数据迁移带通知一起做。便宜的在另一头：Spring Boot 的小版本、Redis 缓存的 TTL、日志格式、内部包怎么摆，改起来顶多重跑一次 CI，被同事吐槽两句就过去了。

按这个分法，年初那张草图上最贵的其实是"订单号对外长什么样"和"事件里带不带金额"，可我当时盯着的是"用不用 MongoDB""拆不拆微服务"这两个看着气派、其实还算能掉头的选型。

这套分法我是被一次改名教出来的，之前没这么清楚。去年把日志里的 `traceId` 从 16 位改成 22 位，动的是 `logback-spring.xml` 里一个 pattern，加两个测试，半天完事，谁也没惊动。同一阵子想改 GraphQL 里 `Order.placedAt` 这个名字，前端和那个对账的 Python 脚本都在解析它，光对齐排期就耗了几天。两件事在我这儿从此分得很清：能一个 PR 悄悄改完的，先定；要拉别人一起改的，往后放，等字段语义长结实了再说。

## 库存扣减把草图推翻了

真正把 MongoDB 那条路堵死的，是三月写库存扣减。下单得在 `orders`、`order_items` 里落记录，同时把 `inventory_movement` 扣掉，还得防超卖，几件事得包在一个 `@Transactional` 里，`SELECT ... FOR UPDATE` 锁住库存行。MongoDB 的多文档事务要开 session 跨集合写，写法绕，我翻了文档就不太想碰；更麻烦的是每月对账，`orders`、`invoices`、`inventory_movement` 三张表 join 出来才对得平，文档模型里得塞一堆冗余字段，将来一处改了三处都得跟着改。

说完全没试过也不老实。MongoDB 那条路我照着草图搭过两天的原型，`orders` 一个集合、`items` 直接嵌成数组，写下单那几行确实比建三张表快。卡在扣库存：嵌入式文档改库存得先读整个订单，并发一上来我就得自己加版本号防覆盖，写到一半发现是在拿业务代码补数据库本该给的事务。原型删了，`docker-compose` 里那行 mongo 镜像也一起删了。放弃得不算心疼，前后也就两天。

回到 PostgreSQL 单体之后，这四张表一个事务里写完，`@Transactional` 一把兜住，对账一条 SQL 带两个 join 就出来了。四个方框缩成一个 `bookstore` 服务，Kafka 只留了 `OrderPlaced`、`BookPriceChanged` 两个事件。那张草图我留着，没删，偶尔翻出来提醒自己当时手里其实什么信息都没有。

## 包住没想好的地方

没定死的地方，我尽量用一层薄东西包着，不让它渗到调用方去。订单号生成我抽了个 `OrderIdGenerator` 接口，对外只露 `String next()`，实现先是 `SequenceOrderIdGenerator` 走数据库自增；将来真要换 ULID 或者带业务前缀的格式，动的是实现类，调 `next()` 的那几个地方不用改。schema 那边我给自己立了条规矩：只加列，不删列，新列一律 `nullable`，先不给默认值，免得回填把历史行锁住。

```sql
-- 2026-03，订单表第一次加列：全 nullable，不回填，对外视图先不暴露
ALTER TABLE orders
    ADD COLUMN price_snapshot numeric(12, 2),
    ADD COLUMN settled_at      timestamptz,
    ADD COLUMN channel         text;

CREATE OR REPLACE VIEW api_order AS
SELECT id, user_id, status, total_amount, created_at
FROM orders;
```

`api_order` 这个视图是故意留的挡板：GraphQL 那层只查它，新加的 `price_snapshot` 先关在后面，语义定死之后再决定放不放进对外字段。对外字段名我宁可啰嗦写成 `placedAt`，也别图省事写 `pat`——省下的那几个字母，将来改名时要还一整礼拜，这笔我吃过。

只加不删的账也得认。`channel` 那列从三月建好到九月才真用上，中间半年整列全是 `null`；`settled_at` 到今天还空着大半，对账只跑了一个账期。留着这些空列看着别扭，可它们没挡过任何一次发布，也没让谁写一行兼容代码。真要较真，删一列要动迁移脚本、动视图、动所有 `SELECT *`，比留着贵得多。

每个悬着的决定我都挂了个截止日期，写在 `flags.yaml` 里，到期要么定、要么把这个 flag 删掉，不许无限期挂着：

```yaml
# src/main/resources/flags.yaml
flags:
  settlement_mode:
    value: "legacy_monolith"
    due: 2027-03-31
    owner: youngCerulean
    note: "billing 对账跑满两个账期之后，再定要不要拆 settlement 服务"
  id_format:
    value: "bigint_sequence"
    due: 2026-09-30
    owner: youngCerulean
    note: "对外订单号格式，一旦有第三方对接就锁死，别再动"
```

## 被拖咬了一口

这套做法有代价，我被咬过一次。`price_snapshot` 那列我建表时图快写成了 `price_snap`，心里想着过两天定死再统一改名。结果 `ordering` 的 `PriceSnapshot`、`billing` 的 `ReconcileJob`、还有给运营导数据的一个 `bash` 脚本，三处都按 `price_snap` 写了，连各自单测的 fixture 里也是这个拼写。等真要统一成 `price_snapshot`，`ALTER TABLE ... RENAME COLUMN` 本身一条 SQL 的事，可三个调用方加三份 fixture，改了整整一个礼拜。拖没问题，拖到别人都把临时字段名当契约了，就晚了。

那一礼拜花在哪儿了，我记得挺细。`ALTER TABLE orders RENAME COLUMN price_snap TO price_snapshot` 一条就完；难的是三处调用方里还有个给运营的 `bash` 脚本，拼的是 `SELECT price_snap FROM orders`，藏在 `scripts/export_orders.sh` 里，没测试覆盖，是运营发现导出空了才嚷出来的。三份单测 fixture 里的字段名也得挨个改。SQL 本身一分钟，找齐这些地方用了一礼拜。

现在我的规矩是，临时的东西也得留个记号：`price_snap` 那种列，建完当天就在 `flags.yaml` 里补一条 `due`，写清楚哪天之前必须定名。延后不等于不做决定，它得给每个悬着的决定配一个"什么时候必须定"的日期，到时候不定也得删。

刚把 `settlement_mode` 的 `due` 从 2026-12 挪到 2027-03——对账才刚跑完第一个账期，信息还不够。存了。
