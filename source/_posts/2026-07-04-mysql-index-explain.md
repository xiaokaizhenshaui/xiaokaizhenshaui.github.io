---
title: "explain 看了八条慢 SQL，七条是索引没生效"
date: 2026-07-04
categories:
  - 中间件
tags:
  - MySQL
  - 索引
  - 性能
lead: "把 long_query_time 从 10 秒调到 0.3 秒，一下午捞出 8 条慢 SQL，7 条都栽在索引没用对上；最慢那条 4.2 秒改到 18 毫秒，剩下第 8 条我到现在还没动。"
---

## 7 月 3 号下午，我把 long_query_time 调到了 0.3

周三下午本来只是想验证一下新上的报表接口，顺手 `SHOW VARIABLES LIKE 'long_query_time'` 看了一眼，返回 `10.000000`，也就是说线上跑了大半年，只有超过 10 秒的 SQL 才记进慢日志——难怪 `/var/lib/mysql/slow.log` 一直是空的。我当时就有点上头，直接改成 0.3 秒，让它在业务低峰跑了一下午：

```sql
SET GLOBAL slow_query_log = 'ON';
SET GLOBAL long_query_time = 0.3;
SET GLOBAL log_output = 'FILE';
SET GLOBAL slow_query_log_file = '/var/lib/mysql/slow.log';
-- log_queries_not_using_indexes 千万别顺手开，一开全是没走索引的小表扫描，日志直接刷爆
SET GLOBAL log_queries_not_using_indexes = 'OFF';
SHOW VARIABLES LIKE 'slow_query%';
```

`long_query_time` 是 GLOBAL 变量，改完只对新建连接生效，连接池里的老连接还是 10 秒。我第一遍统计完发现条数少得离谱，愣了五分钟才想起来得把应用那边的老连接换掉（我们 HikariCP `maximumPoolSize=20`，最后直接重启了一个 pod 才算数）。这种「改了配置以为没生效」的坑，真是每次都踩。

环境：MySQL 8.0.32，InnoDB，单实例 8C16G，`book` 表 218 万行、`order_item` 表 3400 万行，`innodb_buffer_pool_size=8G`。

一下午捞出来 8 条（用 `pt-query-digest` 按总耗时排序），7 条 explain 一眼就能看出索引没用对。第 8 条我放到最后说，它跟索引其实没关系。

（顺带一提，标题写「七条索引没生效」有点不老实：第 7 条索引是生效的，只是没做覆盖、回表太多，严格讲该叫「没用对」。但凑个整挺顺口，就先这么着吧。）

## 先把 explain 这几列看明白

我排查时只盯三列，别的先不管：

- `type`：从好到坏 `system > const > eq_ref > ref > range > index > ALL`。看到 `ALL` 就是全表扫，`index` 是扫全索引（也不快），`range` 以上才算能接受。
- `rows`：预估要扫的行数，不是返回行数。跟表总行数一比就知道离谱不离谱。
- `Extra`：`Using index` 是覆盖索引（好），`Using filesort` 是额外排序（坏），`Using temporary` 更坏；`Using where` 单看没含义，得跟 type 一起看。

比如第 3 条改之前，客户端里 `mysql -e "EXPLAIN SELECT ..."` 出来是这样：

```text
+----+-------------+-------+------------+------+---------------------+------+---------+------+---------+----------+-------------+
| id | select_type | table | partitions | type | possible_keys       | key  | key_len | ref  | rows    | filtered | Extra       |
+----+-------------+-------+------------+------+---------------------+------+---------+------+---------+----------+-------------+
|  1 | SIMPLE      | book  | NULL       | ALL  | idx_created_at      | NULL | NULL    | NULL | 2184306 |    33.33 | Using where |
+----+-------------+-------+------------+------+---------------------+------+---------+------+---------+----------+-------------+
```

`possible_keys` 里有 `idx_created_at`，`key` 却是 NULL——优化器「看见了但没用」，这基本就是列上套了函数或者类型对不上。改成范围查询之后：

```text
+----+-------------+-------+------------+-------+---------------------+----------------+---------+------+------+----------+-----------------------+
| id | select_type | table | partitions | type  | possible_keys       | key            | key_len | ref  | rows | filtered | Extra                 |
+----+-------------+-------+------------+-------+---------------------+----------------+---------+------+------+----------+-----------------------+
|  1 | SIMPLE      | book  | NULL       | range | idx_created_at      | idx_created_at | 6       | NULL | 8214 |   100.00 | Using index condition |
+----+-------------+-------+------------+-------+---------------------+----------------+---------+------+------+----------+-----------------------+
```

`ALL` 变 `range`、`rows` 从 218 万降到 8214，这一列的变化比盯耗时直观多了。`key_len=6` 是 DATETIME（5 字节 + 1 个 nullable 位），说明只用了 `created_at` 这一列，跟我预期一致。

## 表结构和索引长这样

先贴 DDL，后面七条都围着这几张表：

```sql
-- MySQL 8.0.32 / utf8mb4
CREATE TABLE `book` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tenant_id`   BIGINT UNSIGNED NOT NULL,
  `status`      TINYINT         NOT NULL DEFAULT 0 COMMENT '0 下架 1 在售 2 预售',
  `title`       VARCHAR(200)    NOT NULL,
  `price`       INT             NOT NULL COMMENT '单位：分',
  `phone`       VARCHAR(20)     DEFAULT NULL COMMENT '联系人手机号',
  `buyer_id`    BIGINT UNSIGNED DEFAULT NULL,
  `created_at`  DATETIME        NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_phone` (`phone`),
  KEY `idx_buyer` (`buyer_id`),
  KEY `idx_created_at` (`created_at`),
  KEY `idx_tenant_status_created` (`tenant_id`, `status`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='书目';

CREATE TABLE `order_item` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tenant_id`  BIGINT UNSIGNED NOT NULL,
  `book_id`    BIGINT UNSIGNED NOT NULL,
  `qty`        INT NOT NULL,
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_tenant_created` (`tenant_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单明细';
```

那个 `phone` 是 varchar，我第一眼看建表语句还没觉得有问题，直到看见业务代码里传的是个 long——下面第 1 条就是它。（顺带吐槽，手机号存 varchar 是对的，但当年建表的人没写一句「必须带引号」，接口层又拿 Map 接参数，传到 SQL 里就裸奔了。）

## 七条，一条条改

改写前后和耗时放一起。耗时取的是 `pt-query-digest` 里的平均值，同一个从库各跑 20 次取中间值：

```sql
-- ① 隐式类型转换：phone 是 varchar，却拿数字比，MySQL 把列转成了 DOUBLE
-- 改前 1.8s / type=ALL
SELECT * FROM book WHERE phone = 13800138000;
-- 改后 3ms / type=ref，key_len=83（20*4 字节 + 2 长度前缀 + 1 nullable）
SELECT * FROM book WHERE phone = '13800138000';

-- ② 最左前缀：联合索引 (tenant_id, status, created_at)，跳过了最左列
-- 改前 2.4s / type=ALL
SELECT id, title FROM book WHERE status = 1 AND created_at > '2026-06-01';
-- 改后 22ms / type=range，把 tenant_id 带上（这个页面本来就只查当前租户）
SELECT id, title FROM book WHERE tenant_id = 10086 AND status = 1
  AND created_at > '2026-06-01';

-- ③ 函数包裹列：对 created_at 套了 DATE()，索引彻底废掉（最慢的一条）
-- 改前 4.2s / type=ALL，possible_keys 有但 key=NULL
SELECT COUNT(*) FROM book WHERE DATE(created_at) = '2026-07-01';
-- 改后 18ms / type=range
SELECT COUNT(*) FROM book
 WHERE created_at >= '2026-07-01 00:00:00'
   AND created_at <  '2026-07-02 00:00:00';

-- ④ OR 让优化器放弃索引：两列各自有索引，但 explain 没走 index merge
-- 改前 1.1s / type=ALL
SELECT * FROM book WHERE tenant_id = 10086 OR buyer_id = 99213;
-- 改后 9ms / 两条 ref 用 UNION ALL 拼
SELECT * FROM book WHERE tenant_id = 10086
UNION ALL
SELECT * FROM book WHERE buyer_id = 99213 AND tenant_id <> 10086;

-- ⑤ like 前置 %：B+ 树最左前缀用不上
-- 改前 0.9s / type=ALL
SELECT id, title FROM book WHERE title LIKE '%Redis%';
-- 改后 4ms / type=range；跟产品确认过，这个框是「按书名开头找」，历史代码写错了语义
SELECT id, title FROM book WHERE title LIKE 'Redis%';

-- ⑥ Using filesort：ORDER BY price，但联合索引里压根没有 price
-- 改前 3.1s / type=ref, Extra=Using filesort
SELECT id, title, price FROM book WHERE tenant_id = 10086 ORDER BY price DESC LIMIT 20;
-- 改后 31ms / Extra 里 filesort 没了
-- ALTER TABLE book ADD KEY idx_tenant_price (tenant_id, price), ALGORITHM=INPLACE, LOCK=NONE;

-- ⑦ 其实该用覆盖索引：过滤走 idx_tenant_status_created，但要回表取 title/price
-- 改前 0.42s / Extra=NULL（有回表）
SELECT id, title, price FROM book WHERE tenant_id = 10086 AND status = 1;
-- 改后 0.06s / Extra=Using index
-- 把索引扩成 (tenant_id, status, title, price)，SELECT 的列全在索引里
```

第 ④ 条多说两句：MySQL 8.0 是有 index merge 的，理论上 `Using union(...)` 能救，但那天 explain 死活不走，优化器估的 cost 比全表还高（两个条件各自命中率都不低）。我不想跟优化器赌，拆 `UNION ALL` 最稳。第二条里那个 `tenant_id <> 10086` 是为了避免两边都命中同一行时重复返回，因为原本 `OR` 是去重的——这个细节第一版漏了，测试拿一条同时满足两个条件的记录一跑，出来两行，被 QA 拎出来了。

第 ⑥ 条加索引之前我犹豫过，`book` 表写多读少，多一个二级索引就多维护一棵 B+ 树。但那个列表页 QPS 有 300 多，filesort 每次得把几万行捞出来排，`Sort_merge_passes` 一直涨，加完之后这个状态变量基本不动了，值。

第 ⑦ 条索引扩成 `(tenant_id, status, title, price)` 后 `key_len` 从 9 变成 815（`title` 是 `varchar(200) utf8mb4`，光最大字节加长度前缀就 802），不过 varchar 按实际长度存，书名平均十几个汉字，索引文件实测只大了 140MB 左右。`SHOW TABLE STATUS` 显示整表 data 2.1G、index 0.6G，多这 140MB 换 7 倍的提速，划算。这就是我说的「索引生效了但没用对」，七条里它是唯一一个 type 本来就不是 ALL 的。

## 汇总

| # | 病灶 | type 改前 → 改后 | 平均耗时改前 → 改后 |
| --- | --- | --- | --- |
| ① | 隐式类型转换 | ALL → ref | 1.8s → 3ms |
| ② | 最左前缀缺失 | ALL → range | 2.4s → 22ms |
| ③ | 函数包裹列 | ALL → range | 4.2s → 18ms |
| ④ | OR 放弃索引 | ALL → ref×2 | 1.1s → 9ms |
| ⑤ | LIKE 前置 % | ALL → range | 0.9s → 4ms |
| ⑥ | Using filesort | ref + filesort → ref | 3.1s → 31ms |
| ⑦ | 未用覆盖索引 | ref → ref / Using index | 0.42s → 0.06s |

改完这七条，7 月 4 号上午观察两小时，慢日志里这几条全消失了，实例 CPU 峰值从 78% 降到 31%，`Handler_read_rnd_next`（回表 / 全表扫的行数计数器）掉了两个数量级。DDL 我在从库先跑 `ALGORITHM=INPLACE, LOCK=NONE`、验证完再切主库，8.0 加二级索引支持 online DDL，218 万行大概 90 秒，业务没感知。

顺手把 `long_query_time=0.3` 写进 `my.cnf`，不然重启又回 10 秒了：

```bash
# /etc/my.cnf 的 [mysqld] 段，永久生效
# slow_query_log = 1
# long_query_time = 0.3
# log_output = FILE
# slow_query_log_file = /var/lib/mysql/slow.log
# 改完 systemctl restart mysqld；或者先用上面的 SET GLOBAL 顶着

mysqldumpslow -s t -t 10 /var/lib/mysql/slow.log           # 按总耗时排前 10
pt-query-digest /var/lib/mysql/slow.log > /tmp/slow-0703.txt
tail -f /var/lib/mysql/slow.log | grep -A2 '# Time:'       # 实时盯新进来的慢 SQL
```

## 还没解决的：第 8 条

第 8 条是后台导出用的分页：

```sql
EXPLAIN SELECT id, book_id, qty FROM order_item
 WHERE tenant_id = 10086 ORDER BY created_at DESC LIMIT 800000, 20;

+----+-------------+------------+-------+---------------------+---------------------+---------+------+--------+----------+-------------+
| id | select_type | table      | type  | possible_keys       | key                 | key_len | ref  | rows   | filtered | Extra       |
+----+-------------+------------+-------+---------------------+---------------------+---------+------+--------+----------+-------------+
|  1 | SIMPLE      | order_item | ref   | idx_tenant_created  | idx_tenant_created  | 8       | const| 1604821|   100.00 | Using where |
+----+-------------+------------+-------+---------------------+---------------------+---------+------+--------+----------+-------------+
```

explain 是 `type=ref`、`key=idx_tenant_created`，索引老老实实走了，一点毛病没有。慢在 `LIMIT 800000, 20`：MySQL 得按索引扫过 80 万行、回表 80 万次，扔掉前 80 万再取 20 行，pt-query-digest 里平均 3.8 秒。这跟「索引没生效」完全是两回事，所以我没把它算进那七条。

正经解法是改成游标分页，把 `LIMIT offset, size` 换成 `WHERE tenant_id = 10086 AND created_at < 上一页最后一条 ORDER BY created_at DESC LIMIT 20`，配合 `(tenant_id, created_at, id)` 联合索引，翻到第八十万行也只是取 20 行的事。麻烦在前端导出组件是通用的，页码写死在 URL 里，改游标要动三四个页面加一个 SDK，这周排期满了。我先给那个接口加了个 `offset > 100000` 直接拒掉的兜底，提示用户改用按时间范围导出——算是拿胶布糊上了。等下个月把导出服务拆出去，再回来收拾它。
