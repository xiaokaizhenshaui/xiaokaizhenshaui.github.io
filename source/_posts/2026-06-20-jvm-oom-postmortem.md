---
title: "凌晨两点的 OOM：从告警到 MAT 的完整路径"
date: 2026-06-20
categories:
  - Java 开发
tags:
  - JVM
  - OOM
  - 排障
lead: "一个 static HashMap 把 4G 堆吃到 3.8G，我按住值班同事没让重启，就为留份 dump。"
---

6 月 20 号凌晨 02:14，企业微信机器人把我和值班同事一起叫醒了：

> 【P2】prod-ord-03 堆内存使用率 96.2%，连续 5 分钟 > 90%；Old Gen 3.8G / 4.0G，Full GC 后未下降

容器是 4C8G，`-Xmx4g -Xms4g`，G1，JDK 21.0.4，跑的是订单服务。日志里还没出现 `OutOfMemoryError`，但按这个趋势再撑半小时就会。

值班同事第一反应是重启 pod，我在群里按住了。重启两分钟就能把告警消掉，可现场也就没了——堆里那 3.8G 到底是什么，重启之后谁也说不清，下次照样炸。何况 `-XX:+HeapDumpOnOutOfMemoryError` 当时没开，这笔欠账后面才补上，真等进程自己 OOM 退出，连 dump 都不会有。

## 先把现场留下来

运维把这台从负载均衡摘了权重，容器没动，我 `kubectl exec` 进去导 dump。用 `jcmd` 而不是先上 `jmap`，主要是不想再触发一次 Full GC，本来老年代就满了：

```bash
# 容器里 java 就是 1 号进程，别在宿主机上 jps 找
PID=1

# 先确认堆参数和当前占用，留个底
jcmd $PID VM.flags | tr ' ' '\n' | grep -E 'MaxHeapSize|UseG1GC'
jcmd $PID GC.heap_info

# jcmd 导 dump，比 jmap -dump:live 少一次 Full GC
jcmd $PID GC.heap_dump /dump/heap-0620-0214.hprof

# 兜底：jcmd 失败再上 jmap，live 只导活对象，文件小一些
# jmap -dump:live,format=b,file=/dump/heap-0620-0214-live.hprof $PID

# 线程栈和 GC 状态一起带走
jcmd $PID Thread.print > /dump/threads-0620-0214.txt
jstat -gcutil $PID 1000 10 > /dump/gcutil-0620-0214.txt
```

`/dump` 挂的是 emptyDir，不能落容器可写层：4G 堆压出来 3.7G 文件，写容器层既慢又容易把 overlay 撑满，pod 一重建就全没了。导了四分多钟，文件 3.7G，服务这段时间还在接流量，好在没崩。

## GC 日志先排除一条路

有人说是不是 G1 参数没调好。看日志就知道不是。我们开的是统一日志（`-Xlog:gc*:file=/var/log/order-gc.log:time,uptime,level,tags:filecount=5,filesize=50m`，JDK 9 以后没有 `-XX:+PrintGCDetails` 了），出事前后是这段：

```bash
[2026-06-20T02:11:44.102+0800][4120.455s][info][gc,start] GC(1847) Pause Full (G1 Compaction Pause)
[2026-06-20T02:11:46.780+0800][4123.133s][info][gc,phases] GC(1847)   Mark Live Objects 2311.402ms
[2026-06-20T02:11:46.881+0800][4123.234s][info][gc,heap]  GC(1847) Eden: 0.0B(200.0M)->0.0B(200.0M) Survivors: 0.0B->0.0B Heap: 3980.0M(4096.0M)->3942.0M(4096.0M)
[2026-06-20T02:11:46.881+0800][4123.234s][info][gc]       GC(1847) Pause Full (G1 Compaction Pause) 3980M->3942M(4096M) 2677.912ms
[2026-06-20T02:12:03.440+0800][4139.793s][info][gc,start] GC(1848) Pause Full (G1 Compaction Pause)
```

关键在 `3980M->3942M`：一次 2.7 秒的 Full GC 只回收了 38M，老年代基本没动，16 秒后又来一次。`Mark Live Objects` 就占了 2.3 秒，说明对象几乎全活着。这不是 GC 节奏、region 大小或者 `-XX:InitiatingHeapOccupancyPercent` 的问题，加堆也只是把爆掉的时间往后推。得去看谁拽着它们。

## MAT 里那棵 dominator tree

3.7G 的 hprof 用 MAT 1.15.0 打开。本地 16G 内存，得先把 `MemoryAnalyzer.ini` 里的 `-Xmx` 调到 12g，不然 MAT 自己先 OOM。跑完 Leak Suspects，dominator tree 第一行毫无悬念：

| 对象 | Retained Heap | 占比 |
| --- | --- | --- |
| `class com.example.order.fee.OrderFeeCache` | 3.62 GB | 92.1% |
| `java.util.HashMap` @ 0x6a1c... | 3.62 GB | 92.1% |
| `java.util.HashMap$Node[]` | 3.61 GB | 91.8% |

`OrderFeeCache` 里就一个东西：

> `private static final Map<String, FeeRule> CACHE = new HashMap<>();`
> 按 `tenantId + ":" + skuId` 做 key，运营改一次价就 `CACHE.put(...)` 一次，没有上限，也没有过期。

顺着 dominator tree 展开，280 多万个 `HashMap$Node`。为了确认不是别处也有大 Map，跑了两条 OQL：

```sql
-- 先把 retained heap 超过 100 MB 的 HashMap 全捞出来，看是不是只有这一个
SELECT * FROM INSTANCEOF java.util.HashMap h
WHERE h.@retainedHeapSize > 104857600

-- 查这个类的实例数：结果是 0，说明东西挂在类上（static），不是挂在某个对象上
SELECT * FROM INSTANCEOF com.example.order.fee.OrderFeeCache
```

第二条返回 0 个，我卡了一下才反应过来：`CACHE` 是 static，实例列表里当然找不到，得去 class 对象的静态属性里看。MAT 不会主动提醒这一点，dominator tree 里显示成 `class ...OrderFeeCache` 而不是某个 `@0x...` 实例，就是线索。

## 为什么没设上限

翻 git log，这个类是 2021 年加的，当时的注释写着「费率规则很少变，查库太频繁，放内存里」。那时候系统只有 3 个租户、几百个 sku，`HashMap` 撑死几千条，确实不用设上限。问题出在后来两次改动：一是接了多租户，key 里带了 `tenantId`；二是改价接口为了留痕，把版本号拼进了 key，变成 `fee:t102:sku8891:v17` 这种。我抽了 dump 里的 key 样本看，同一个 sku 攒了两百多个不同版本，全活着，永远不覆盖，也永远不删。

光说「忘了设上限」太简单了，key 的语义悄悄变了，从「当前生效的规则」变成「每一次改价的快照」，可类名和注释都没跟着改。review 的时候谁也想不到一个叫 `CACHE` 的 static Map 会变成只增不减的账本。

## 换成 Caffeine，然后验证

没自己写 LRU，直接上 Caffeine（Boot 3.2.5 管的是 `com.github.ben-manes.caffeine:caffeine:3.1.8`，不用额外写版本）：

```java
package com.example.order.fee;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.Duration;
import java.util.function.Function;

@Component
public class OrderFeeCache {

    // 上限按峰值活跃 sku 估的：8 千上下，给到 1 万留点余量
    private final Cache<String, FeeRule> cache = Caffeine.newBuilder()
            .maximumSize(10_000)
            .expireAfterWrite(Duration.ofMinutes(10))
            .recordStats()
            .build();

    // key 里的版本号去掉了，改价直接让老条目过期，不再 append 新 key
    public FeeRule get(String tenantId, String skuId, Function<String, FeeRule> loader) {
        return cache.get(tenantId + ":" + skuId, loader);
    }

    public long size() {
        return cache.estimatedSize();
    }

    public long evictions() {
        return cache.stats().evictionCount();
    }

    // 项目里本来就有这个 DTO，为了让示例能单独编译，补一个最简定义
    public record FeeRule(String skuId, BigDecimal price) {}
}
```

验证分三步。先在本地把改价接口按 50 QPS 连打两小时，`size()` 稳定在 7600~8100 之间，`evictions()` 一直在涨，说明确实在淘汰而不是又堆起来了。再灰度一个副本 24 小时，Old Gen 从 3.8G 回落到 600M 上下，Full GC 从出事那晚的每小时 20 多次降到 0。`size()` 和 `evictions()` 也注册到了 `MeterRegistry`，Grafana 上加了一条 `size() > 9000` 就告警的规则——上限这种东西，光配了不看，过两年一样会出事。

顺手把欠账补了：启动参数加上 `-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/dump`，以后真 OOM 不用再靠人手快。

`cache.get(key, loader)` 能保证单个 key 只回源一次，但不同 key 一起失效时还是会把 DB 顶一下，`refreshAfterWrite` 暂时没上。合作方那台联调机还跑着老客户端，改价接口一天发三千多次，key 归一化之后重复率高了不少，`expireAfterWrite` 十分钟是不是给长了，命中率还得再跑一周看。先摘流量再 dump 这套，我总觉得还能再利索点。dump 我还留着，3.7G，没舍得删。
