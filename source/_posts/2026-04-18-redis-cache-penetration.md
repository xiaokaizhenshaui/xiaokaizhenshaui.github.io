---
title: "缓存穿透那次，Redis 被打到 100% CPU"
date: 2026-04-18
categories:
  - 中间件
tags:
  - Redis
  - 缓存
  - 排障
lead: "刷了 40 分钟，Redis 单核 100%，最险的是我先拿互斥锁把穿透改成了击穿。"
---

## 23:41，先响的是网关不是 Redis

4 月 17 号 23:41，钉钉机器人弹的是「gateway 502 比例 3.7%」，我下意识去翻 Nginx，结果 upstream 全绿。切到 Grafana 才看见 cache-redis-01 的 CPU 一条直线贴着 100%，`used_memory` 倒是平稳在 2.1G，说明不是大 key 撑爆，是命令被打满了。值班群里有人贴了一句：

```bash
redis-cli -h 10.0.3.21 INFO stats | grep -E 'instantaneous_ops_per_sec|total_commands_processed'
instantaneous_ops_per_sec:86432
total_commands_processed:148920311
```

8.6 万 OPS，平时这个点也就 9000 上下。`SLOWLOG GET 5` 倒是干净，全是 GET，没有一条慢命令。穿透最坑就坑在这儿：每条命令都快到监控不报警，但条条落空，请求全部穿到 MySQL。

我去查那段时间的访问日志，一个 `/api/book/detail?bookId=` 的接口占了一半流量，bookId 是 `-1`、`999999999`、`book_xxx` 这种乱七八糟的值，User-Agent 清一色 `python-requests/2.31.0`。我们图书库里最大的 id 才 218 万。抽了 200 个 id 拼进 `SELECT COUNT(*) FROM book WHERE id IN (...)` 跑了一下，一条都没命中。凌晨 0:22 我先在网关按 IP 段限流把那个来源掐了，CPU 从 100% 掉到 34%，但心里清楚这是止血不是治病——脚本换个出口就再来一遍。

我们 Redis 是 6.2.13，单主单从，没上集群，所以那个「单核 100%」是真·单核：处理命令就一个线程，打满了就是打满了，加从库一点用没有。

## 第一版：我把穿透写成了击穿

第二天上午动手改 `BookServiceImpl#getById`。当时想法特别朴素：既然缓存没有就查库，那我加个锁，只放一个线程去查库、查完回填，其他人等着读缓存不就完了。第一版大概长这样，真代码已经被我删了，凭印象复原：

```java
RLock lock = redisson.getLock("lock:book:" + bookId);
lock.lock();
try {
    // double check + 回源 + 回填
} finally {
    lock.unlock();
}
```

压测一跑我就知道坏了。JMeter 200 并发打同一个「不存在的」 id，QPS 反而比不加锁还低，MySQL 那边 `Threads_running` 照样往上走。原因其实很直白：穿透是「大量不同的、不存在的 key」，每个 key 都是第一次来，每个 key 都抢到自己的锁、都放行去查库。锁是按 key 加的，对不同 key 毫无约束力，我等于给 8 万个不存在的 id 各发了一把锁，锁了个寂寞，还白搭 8 万次 SETNX 的开销。

更要命的是同一版里我还踩了第二个坑。为了省事，释放锁没走 Redisson 的 `unlock()`，自己拿 `StringRedisTemplate` 写了个 `DEL lockKey`。结果一个回源线程 GC 停了 3 秒多、锁超时自动过期，B 线程拿到锁，A 醒过来在 finally 里一个 DEL 把 B 的锁删了，C 又拿到锁……同一个 id 瞬间两个线程在回源。这个 bug 本地压测复现了三次我才反应过来是删错锁，跟可重入一点关系没有（Redisson 的锁本来就可重入，我一开始还往那个方向查了半天，纯属跑偏）。

所以第一版的结论是：互斥锁只治「击穿」，也就是一个热点 key 失效、一群人抢着回源那种。碰上「穿透」这一堆根本不存在的 key，它一点办法没有。顺序得反过来，先判断「这个 key 有没有可能存在」，把绝大多数挡掉，锁只留给那些「布隆说可能存在」的漏网之鱼。

## 布隆：Redisson 还是 Guava

选 Redisson 的 `RBloomFilter` 而不是 Guava 的 `BloomFilter`，理由很实际：我们 4 个 pod，Guava 是 JVM 堆里的，每个实例各存一份、各自预热，重启一次全丢，而且 218 万条 id 要灌 4 遍，滚动发布的时候新旧布隆还不一致。Redisson 把位数组放 Redis 里（key 是 `bloom:book:ids`），一份数据所有实例共享，重启不丢，新增书目 `add` 一下就行。

误判率定了 0.01。这里得说清楚：布隆「说不存在」是 100% 准的，「说存在」有 1% 概率是误判——那 1% 会漏到后面查库，但已经把 8.6 万 OPS 砍到 860 了，完全能接受。`tryInit(expectedInsertions, falseProbability)` 会自己算位数组长度和 hash 次数，我按 2000 万预估（现在 218 万，留了三倍多富余），算出来大概占 23.9MB，比想象中小。Guava 那边对应的是 `BloomFilter.create(Funnels.stringFunnel(UTF_8), 20_000_000, 0.01)`，参数含义一样，只是落在堆里。

```java
import org.redisson.api.RBloomFilter;
import org.redisson.api.RedissonClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import java.util.List;

// 依赖：org.redisson:redisson:3.23.5，JDK 17 / Spring Boot 3.1.6
// Guava 对应 com.google.guava:guava:32.1.3-jre（本地布隆，多实例不共享，本次未选）
@Configuration
public class BookCacheConfig {

    private static final Logger log = LoggerFactory.getLogger(BookCacheConfig.class);

    @Bean
    public RBloomFilter<String> bookBloom(RedissonClient redisson,
                                          BookMapper bookMapper) {
        RBloomFilter<String> bloom = redisson.getBloomFilter("bloom:book:ids");
        // 预计 2000 万个 id，误判率 1%；已初始化时 tryInit 返回 false，不会重复灌
        boolean created = bloom.tryInit(20_000_000L, 0.01);
        if (created) {
            List<Long> ids = bookMapper.scanAllIds();
            ids.forEach(id -> bloom.add("book:" + id));
            log.info("布隆预热完成 ids={}，误判率={}，bit 数={}",
                     ids.size(), bloom.getFalseProbability(), bloom.getSize());
        }
        return bloom;
    }
}
```

有个细节我一开始搞混过：Redisson 的布隆是自己用位数组 + 多次 hash 实现的，不是 RedisBloom 模块，我还特意去 `MODULE LIST` 里找 RedisBloom，结果压根没装。另外 `getSize()` 返回的是 bit 数不是字节，得除以 8，日志里那 23.9MB 是我自己换算的。

## 空值缓存 + 短 TTL，还有那段删锁的 Lua

挡完布隆还有两件事。第一，那 1% 误判、以及「刚上架就被删掉」的 id，查库确实没有，得把「没有」这个事实也缓存起来，否则下次同样的 id 又穿一次。我拿固定占位串 `NULL` 写进缓存，TTL 给 60 秒。不敢给长，万一这期间真有这本书上架，用户得等一分钟才看得见。给太短也不行，10 秒的话脚本换着 id 刷还是能打出量。60 秒是跟商品侧「上架到可查」的 SLA 折中出来的。

第二，锁的释放改成 Lua 校验 token，别再删到别人的锁。每个抢锁的线程塞一个 UUID 当 value，释放时先 GET 比对，一致才 DEL，整个动作在一个脚本里原子完成。

```java
import com.alibaba.fastjson2.JSON;
import jakarta.annotation.Resource;
import org.redisson.api.RBloomFilter;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Service;
import java.util.Collections;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;

// 依赖：com.alibaba.fastjson2:fastjson2:2.0.40
@Service
public class BookService {

    @Resource private StringRedisTemplate stringRedis;
    @Resource private RBloomFilter<String> bookBloom;
    @Resource private BookMapper bookMapper;
    // 配置类里用 DefaultRedisScript<Long> 加载 classpath:lua/unlock.lua
    @Resource private RedisScript<Long> unlockScript;

    public Book getById(Long bookId) {
        String key = "book:" + bookId;
        // 1) 布隆说不存在 → 直接返回，绝不回源
        if (!bookBloom.contains(key)) {
            return null;
        }
        // 2) 查缓存：命中真值 / 命中空值占位
        String cached = stringRedis.opsForValue().get(key);
        if (cached != null) {
            return "NULL".equals(cached) ? null : JSON.parseObject(cached, Book.class);
        }
        // 3) 只有「可能存在且缓存未命中」才抢锁回源
        String lockKey = "lock:" + key;
        String token = UUID.randomUUID().toString();
        Boolean locked = stringRedis.opsForValue()
                .setIfAbsent(lockKey, token, 5, TimeUnit.SECONDS);
        if (!Boolean.TRUE.equals(locked)) {
            try {
                Thread.sleep(50);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return null;
            }
            return getById(bookId);   // 简化写法，生产里我加了最多 3 次重试
        }
        try {
            Book book = bookMapper.selectById(bookId);
            if (book == null) {
                stringRedis.opsForValue().set(key, "NULL", 60, TimeUnit.SECONDS);
            } else {
                stringRedis.opsForValue().set(key, JSON.toJSONString(book),
                        3600 + ThreadLocalRandom.current().nextInt(300),
                        TimeUnit.SECONDS);
            }
            return book;
        } finally {
            // Lua 原子校验 token，别删掉其它线程的锁
            stringRedis.execute(unlockScript,
                    Collections.singletonList(lockKey), token);
        }
    }
}
```

```lua
-- unlock.lua：KEYS[1]=锁 key，ARGV[1]=本线程持有的 token
-- 只有 value 对得上才删，防止超时后 A 把 B 的锁删掉
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
```

`setIfAbsent(key, value, timeout, unit)` 是 `SET key value NX EX` 的封装，加锁和设过期一步到位。千万别写成先 SETNX 再 EXPIRE，中间宕机就是个永不释放的死锁——这个坑我 2023 年踩过一次，记忆犹新。

## 雪崩顺手一起治了：TTL 抖一下

改完穿透顺手看了一眼过期时间，好家伙，商品详情统一写死 `3600` 秒，整点批量预热的那批 key 会在同一秒集体失效。那天没出事纯属流量不够集中。我把所有写缓存的地方改成 `3600 + random(0, 300)`，也就是 1 小时到 1 小时 5 分之间散开。就这一行，不动数据结构、不动调用方。

别用 `Math.random()`，多线程争 seed 在 JDK 17 里虽然好了很多，我还是统一换成了 `ThreadLocalRandom`，顺手的事。

## 修复前后

压测用 JMeter 200 并发、5 分钟，脚本按线上那批日志回放（85% 是不存在的 id，15% 是真实 id），Redis 6.2.13、MySQL 8.0.32，book 表 218 万行：

| 指标 | 修复前 | 第一版（只加锁） | 最终版 |
| --- | --- | --- | --- |
| Redis OPS | 86432 | 91107 | 9400 |
| Redis CPU | 100% | 100% | 11% |
| 回源 QPS（MySQL 查询） | 8600 | 8100 | 0.4 |
| P99 延迟 | 1240ms | 1310ms | 38ms |
| MySQL Threads_running 峰值 | 187 | 179 | 6 |

第一版那列是我特意留着警醒自己的：锁加错了不但没降，OPS 还涨了近 5 千，全是多出来的 SETNX/DEL。最终版的 0.4 不是零，是那 1% 布隆误判加上真实新书首次访问的量，符合预期。4 月 18 号 14:00 灰度到 1 个 pod，观察两小时没异常，16:30 全量。当晚 23:40 同一个脚本又来了一波（换了 IP 段），Redis CPU 最高 9%，网关 502 是 0，我在群里回了个「稳了」就下班了。

观察命令基本就盯这几条：

```bash
redis-cli -h 10.0.3.21 -a "$REDIS_PWD" INFO stats | grep -E 'instantaneous_ops_per_sec|total_commands_processed'
redis-cli -h 10.0.3.21 -a "$REDIS_PWD" --bigkeys              # 确认布隆没长成异常大 key
redis-cli -h 10.0.3.21 -a "$REDIS_PWD" SLOWLOG GET 10
redis-cli -h 10.0.3.21 -a "$REDIS_PWD" BF.INFO bloom:book:ids  # 会报 unknown command，见下文
redis-cli -h 10.0.3.21 -a "$REDIS_PWD" MEMORY USAGE bloom:book:ids
```

倒数第二条我留着没删：第一次排查时我确实敲了 `BF.INFO`、也确实吃了 `unknown command 'BF.INFO'`，提醒自己 Redisson 的布隆不是 RedisBloom 模块。`MEMORY USAGE` 返回字节数，当时是 25088000 左右，跟算出来的 23.9MB 对得上。

布隆只支持 `add`，不支持删，偏偏我们图书有下架逻辑。`bloom:book:ids` 里的位一旦置上就下不来，下架的书走「布隆说存在 → 缓存空值 → 查库没有」这条路能挡住，但位数组会一直脏着，误判率随着时间慢慢往上爬。现在靠每季度全量重建一个 `bloom:book:ids:v2` 再切别名糊着，切换那几秒新书可能有短暂漏判。要么换布谷鸟过滤器（RedisBloom 里有 `CF.DEL`），要么干脆把「下架」也当成事件写进空值缓存。

下架率我打算先跑一个月看看数据。真要换布谷鸟，那每季度重建的这套脚本谁来拆，我还没想明白。
