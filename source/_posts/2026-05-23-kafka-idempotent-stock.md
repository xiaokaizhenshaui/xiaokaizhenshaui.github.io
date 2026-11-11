---
title: "一次重复扣库存，我把 Kafka 的 exactly-once 重新读了一遍"
date: 2026-05-23
categories:
  - 中间件
tags:
  - Kafka
  - 消息队列
  - 幂等
lead: "重放 37 次、超卖 29 件，我还指望 enable.idempotence 能挡住。"
---

## 14:07 那次滚动重启

5 月 22 号下午 14:07，运维做常规滚动重启，`kubectl rollout restart deploy/stock-consumer`。14:09 客服就转过来一个工单：SKU-88213 页面显示库存 120，用户却成功下了 149 件。我登到库存库一看，`stock` 字段是 `-29`。负数，我们压根没加 unsigned 约束，也没写 `CHECK (stock >= 0)`，扣到负数一路畅通。

翻 consumer 日志，那段重复得刺眼（摘了连续几行，订单号脱敏过）：

```text
2026-05-22 14:08:12.441 [stock-consumer-0-C-1] INFO  c.y.stock.StockListener - 收到扣减 topic=stock-deduct partition=3 offset=88412 key=ORD-20260522-7731 sku=88213 qty=1
2026-05-22 14:08:12.509 [stock-consumer-0-C-1] INFO  c.y.stock.StockListener - 扣减成功 sku=88213 剩余=119
2026-05-22 14:08:12.510 [stock-consumer-0-C-1] INFO  c.y.stock.StockListener - 收到扣减 ... offset=88413 ... sku=88213 qty=1
...（中间 34 行同样是 sku=88213）
2026-05-22 14:08:13.102 [stock-consumer-1-C-1] INFO  c.y.stock.StockListener - 扣减成功 sku=88213 剩余=-29  <-- 重启后重放的第一条
```

数了下，同一个订单号 `ORD-20260522-7731` 在重启前后一共被处理了 37 次，库存从 120 一路扣到 -29。上游订单服务因为 RPC 超时也重试过几次，但主因在 consumer：当时图省事用的是默认 `enable.auto.commit=true`，`auto.commit.interval.ms` 默认 5000ms，`max.poll.records=500`。一批 poll 回来 500 条，处理到第 200 多条时 pod 被 `SIGTERM`，没配优雅停机，preStop 也没等 ack，offset 还停在 88400 没到提交周期。新 pod 起来从 88400 重新拉，那 200 多条全部又走了一遍。

`kafka-consumer-groups.sh --describe` 当时显示 LAG 从 0 突然涨到 218，我第一反应是消费能力不够，差点去加分区，其实是 offset 回退了。这个命令后面贴了。

环境：Kafka 3.4.1（3 broker，KRaft 模式），spring-kafka 3.0.9，Spring Boot 3.1.6，MySQL 8.0.32。

## 第一版：把 enable.idempotence 当成了万能药

出事之后我第一反应是「exactly-once 没开全」，翻文档翻了半小时，回去在 producer 那边加了这几行：

```properties
enable.idempotence=true
acks=all
transactional.id=stock-prod-1
```

consumer 上补了 `isolation.level=read_committed`。本地压测：producer 发 1 条，手动 kill consumer 再起，看库存，扣了两次。我又把 `send` 包进 `executeInTransaction`，还是两次。

那天下午我才把这几个参数的边界搞清楚，之前基本是望文生义：

| 配置 | 在哪端 | 到底管什么 | 不管什么 |
| --- | --- | --- | --- |
| `enable.idempotence=true` | producer | 单个 producer 会话内、单个分区，因重试产生的重复写入（PID + 序列号，broker 端去重） | 跨会话（重启后 PID 变）、跨分区原子性、consumer 端业务被重复执行 |
| `transactional.id` + 事务 | producer | 多分区「要么全写要么全不写」，配合 `read_committed` 让 consumer 看不到 abort 的消息 | 已提交的消息被重复投递 |
| `isolation.level=read_committed` | consumer | 只读 LSO 之前、已 commit 的事务消息，滤掉 uncommitted / abort 的 | 一条已提交消息因 offset 没提交而被重新拉一遍 |

关键就在最后一行：消息在 broker 里本来就只有一份，producer 幂等做得再好也没重复写。问题是我 consumer 处理完了却没提交 offset，broker 认为这批还没消费，重连后原样再发一次。这是 at-least-once 的正常行为，算不上 bug。想让「业务副作用只发生一次」，靠 Kafka 配置做不到，得在业务侧自己兜。

我把 `transactional.id` 留着了，因为订单服务那边确实有「扣库存 + 写流水」跨两个 topic 的场景要用事务，但跟这次事故没关系，纯粹顺手补的。

所以第一版等于白干。第二版把重心挪到 consumer：关掉自动提交、改手动 ack，并且「只有数据库确实扣成功了才 ack」。

## 幂等表 + 唯一索引，最后一道防线

光靠手动 ack 还不够。`ack.acknowledge()` 和 DB 提交之间有条缝：DB 扣成功了、ack 还没发出去，进程挂了，重放照样再扣一次。这个窗口没法靠顺序消除，只能让第二次扣减在 DB 层直接失败。我加了一张幂等表，用「订单号 + SKU」做唯一键：

```sql
-- MySQL 8.0.32，utf8mb4
CREATE TABLE `stock_deduct_log` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `dedup_key`   VARCHAR(96)     NOT NULL COMMENT '业务幂等号：订单号:SKU',
  `msg_key`     VARCHAR(96)     DEFAULT NULL COMMENT 'Kafka 消息 key，排查用',
  `topic`       VARCHAR(64)     DEFAULT NULL,
  `partition`   INT             DEFAULT NULL,
  `offset`      BIGINT          DEFAULT NULL,
  `sku_id`      BIGINT UNSIGNED NOT NULL,
  `qty`         INT             NOT NULL,
  `created_at`  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_dedup_key` (`dedup_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='扣库存幂等流水';
```

`dedup_key` 用的是 `ORD-20260522-7731:88213`，不是消息 offset。这点我想过：offset 在重放时是一样的，理论上也能当幂等号，但一旦分区重分配、或者以后做消息回放 / 补数，offset 会变、甚至不同 topic 撞车，不稳；业务单号才是跟「这次扣减」一一对应的那个东西。

处理流程变成：开事务 → `INSERT` 幂等流水 → `UPDATE stock SET stock = stock - ? WHERE sku_id = ? AND stock >= ?` → 提交 → 再 `ack.acknowledge()`。唯一索引冲突说明这条已经处理过，直接吞掉、照常 ack。`UPDATE` 里那个 `AND stock >= qty` 是顺手补的，配合 `affected rows == 0` 抛库存不足，彻底堵死负库存。

## 配置与手动 ack

consumer 侧配置（Spring Boot `application.yml`）：

```yaml
spring:
  kafka:
    bootstrap-servers: kafka-0:9092,kafka-1:9092,kafka-2:9092
    consumer:
      group-id: stock-consumer
      enable-auto-commit: false          # 关键：关掉自动提交，改由监听器手动 ack
      auto-offset-reset: earliest
      max-poll-records: 100             # 从 500 降下来，缩小重放窗口
      isolation-level: read_committed   # 配合 producer 事务，滤掉 abort 的消息
      key-deserializer: org.apache.kafka.common.serialization.StringDeserializer
      value-deserializer: org.apache.kafka.common.serialization.StringDeserializer
      properties:
        session.timeout.ms: 10000
        max.poll.interval.ms: 300000
    listener:
      ack-mode: manual_immediate        # acknowledge() 立刻提交，不攒批
      concurrency: 3
```

监听器（依赖 `org.springframework.kafka:spring-kafka:3.0.9`）：

```java
import com.alibaba.fastjson2.JSON;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.support.Acknowledgment;
import org.springframework.kafka.support.KafkaHeaders;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

@Component
public class StockListener {

    @KafkaListener(topics = "stock-deduct", groupId = "stock-consumer")
    @Transactional(rollbackFor = Exception.class)
    public void onMessage(ConsumerRecord<String, String> record,
                          Acknowledgment ack,
                          @Header(KafkaHeaders.RECEIVED_PARTITION) int partition) {
        DeductCmd cmd = JSON.parseObject(record.value(), DeductCmd.class);
        String dedupKey = cmd.getOrderNo() + ":" + cmd.getSkuId();
        try {
            // 1) 先插幂等流水，唯一索引挡住重复
            deductLogMapper.insert(new DeductLog(dedupKey, record.key(),
                    "stock-deduct", partition, record.offset(),
                    cmd.getSkuId(), cmd.getQty()));
            // 2) 再扣库存，带 stock >= qty 防超卖；影响行数为 0 直接抛
            int rows = stockMapper.decrease(cmd.getSkuId(), cmd.getQty());
            if (rows == 0) {
                throw new StockNotEnoughException("库存不足 sku=" + cmd.getSkuId());
            }
        } catch (DuplicateKeyException e) {
            // 已经扣过，幂等命中：不回滚、不当错误，正常确认
            log.info("重复消息，跳过 dedupKey={} offset={}", dedupKey, record.offset());
        }
        // 3) 只有事务提交成功后才 ack
        //    @Transactional 的 commit 发生在方法返回之后，方法体里直接 ack
        //    会变成「先 ack 后提交」，提交失败就丢消息了
        TransactionSynchronizationManager.registerSynchronization(
                new TransactionSynchronization() {
                    @Override
                    public void afterCommit() {
                        ack.acknowledge();
                    }
                });
    }
}
```

那个 `afterCommit` 我得交代一下，不然容易埋雷：第一版我就是在方法体最后一行直接 `ack.acknowledge()`，review 时被组里同学拦下来了，DB 还没 commit 呢就告诉 broker「我消费完了」，万一中途回滚，消息真就丢了。改成挂到事务同步回调里才算对，这是第二遍才改对的。

## 死信队列

还有一类消息不能无限重放：JSON 脏数据、`sku_id` 查不到这种，重试一百次也是失败，还会把同一分区后面 99 条全堵住。我给监听容器挂了个 `DefaultErrorHandler`，配 `DeadLetterPublishingRecoverer` 把耗尽重试的消息发到 `stock-deduct.DLT`，回退策略是 `new FixedBackOff(1000L, 3L)`——间隔 1 秒、最多重试 3 次；目的地用 `record.topic() + ".DLT"` 拼，分区号照抄 `record.partition()`，这样人工排查时还能对上原分区。

`FixedBackOff` 那两个参数我第一次还写反了，把 1000 当次数、3 当毫秒，一跑起来重试几乎连着打，日志瞬间刷屏才反应过来——构造是 `(interval, maxAttempts)`，别按字面猜。DLT 里我带上了原始 topic / partition / offset 和异常栈，另外有个单独消费 DLT 的小脚本，人工看完再决定是修数据重投还是作废。spring-kafka 从 2.8 起 `SeekToCurrentErrorHandler` 就废弃了，我一开始还照着老博客找这个类，白翻了十分钟。

## 改完的数字

5 月 23 号 11:00 灰度，Chaos 那边帮我在压测环境做了 20 次随机 `kill -9`（每次都挑在处理中途杀）：

| | 修复前 | 修复后 |
| --- | --- | --- |
| 重启后重复处理条数 | 218（一批 offset 回退） | 0（幂等命中，日志打 skip） |
| 单次 kill 造成的库存偏差 | 最多 -29 | 0 |
| 负库存出现次数 | 1 | 0 |
| 消费吞吐（条/秒） | 约 3100 | 约 2750（多了 1 次 INSERT） |
| DLT 日均条数 | 无 | 2～3（全是上游脏 JSON） |

吞吐掉了 11%，换来的是重启再也不会多扣，这笔账很好算。另外顺手把 `preStop` 加了 15 秒等待、`terminationGracePeriodSeconds` 调到 30，让在途消息有机会 ack 完再退，重放窗口又小了一截。

排查时常用的两条：

```bash
bin/kafka-consumer-groups.sh --bootstrap-server kafka-0:9092 --group stock-consumer --describe
bin/kafka-console-consumer.sh --bootstrap-server kafka-0:9092 --topic stock-deduct.DLT --from-beginning --property print.key=true
```

第一条看 CURRENT-OFFSET 和 LAG，第二条翻死信。事故那天我要是先跑了 `--describe`，大概能早点反应过来是 offset 回退，而不是傻乎乎去查消费能力。

幂等表现在只留 30 天，定时任务按 `created_at` 删。麻烦在于：万一上游拿一个 31 天前的订单号重投（对账补数、历史订单退款重算都可能），唯一索引已经空出来了，照样能再扣一次。要么把 dedup_key 的保留期跟业务单据生命周期对齐，订单表留 3 年，幂等表也留 3 年，单表得按天分区；要么给扣减加一道「原单据状态」校验。我倾向前者，可 3 年流水按现在每天 80 万条算大概是 8 亿行，分区和归档方案还没定。

光这 8 亿行怎么分区归档，就够喝一壶的。
