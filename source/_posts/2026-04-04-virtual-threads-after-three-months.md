---
title: "JDK 21 虚拟线程上线三个月，我把线程池拆了"
date: 2026-04-04
categories:
  - Java 开发
tags:
  - Java
  - 虚拟线程
  - 性能
lead: "QPS 涨了 2.4 倍，第一版却差点被我回滚，问题出在哪？"
---

1954 QPS，这是把线程池拆掉、换成虚拟线程之后跑出来的数，比原来翻了 2.4 倍。说回三月中旬动手那会儿，起因很 mundane：压测报告上 4C8G 的容器跑到 800 QPS 就上不去了，CPU 才 40%，`top` 里一堆线程全在 `WAITING`。下游是个 HTTP 接口，平均 120ms，典型的 IO 密集。这种场景还用固定大小的池子，属于自己给自己设上限。

但第一版改完，QPS 只从 800 涨到 860，Young GC 反而从每分钟 3 次变成 11 次。当时差点就回滚了。

## 原来的配置长什么样

Spring Boot 3.2.5 + JDK 21.0.4，任务执行器是这么配的：

```java
@Configuration
public class ExecutorConfig {
    @Bean("queryExecutor")
    public ThreadPoolTaskExecutor queryExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(32);
        executor.setMaxPoolSize(64);
        executor.setQueueCapacity(200);
        executor.setThreadNamePrefix("query-");
        executor.setRejectedExecutionHandler(new CallerRunsPolicy());
        executor.initialize();
        return executor;
    }
}
```

这里的 `CallerRunsPolicy` 是当年怕丢任务加的。真到高峰，队列满了就让 Tomcat 的工作线程自己跑下游调用，结果请求线程也被拖住，雪崩得更快。这个后面还会提到。

Spring Boot 3.2 开虚拟线程其实只要一行：

```yaml
# application.yml
spring:
  threads:
    virtual:
      enabled: true
```

开了之后，`@Async`、`SimpleAsyncTaskExecutor`、Tomcat 的请求处理线程都会走虚拟线程。改完我兴冲冲跑了一轮 JMeter，就是上面那个「几乎没涨」的结果。

## 卡在哪：synchronized 把载体钉住了

先贴当时的诊断命令，比讲道理快：

```bash
# 抓 60 秒 JFR，重点看虚拟线程 pinning 事件
jcmd <pid> JFR.start duration=60s filename=/tmp/vt.jfr \
  settings=profile jdk.VirtualThreadPinned#enabled=true

jfr print --events jdk.VirtualThreadPinned /tmp/vt.jfr \
  | head -40

# 或者直接开系统属性，把 pinning 的堆栈打到 stdout
# -Djdk.tracePinnedThreads=full
```

输出里有大量这样的堆栈：

```text
jdk.VirtualThreadPinned {
  startTime = 14:22:31.442
  duration = 118 ms
  eventThread = "vt-QueryOrder-1837" (javaThreadId = 1837)
  stackTrace = [
    java.lang.Object.wait(...)
    com.xxx.order.OrderCache.get(OrderCache.java:88)
    ...
  ]
}
```

`OrderCache.get` 是 2019 年写的，整个方法挂了 `synchronized`，里面有一次 Redis 调用。JDK 21 里虚拟线程进入 `synchronized` 块遇到阻塞 IO **不会卸载载体线程**，这个 monitor 会把 carrier 一直占着。我那个服务有 4 个 CPU，默认 carrier 池就是 4 个，四个都被钉住，后面所有虚拟线程排队等 carrier —— 等于又变回了 4 个线程的池子，还多了一层调度开销。

> 这个问题在 JDK 24（JEP 491）里基本解决了，`synchronized` 不再 pin，可生产环境还停在 21，等不到那天。

改法很土但有效，把 monitor 换成 `ReentrantLock`：

```java
@Component
public class OrderCache {
    private final Lock lock = new ReentrantLock();
    private final StringRedisTemplate redis;

    public OrderCache(StringRedisTemplate redis) {
        this.redis = redis;
    }

    public OrderDto get(String orderId) {
        lock.lock();
        try {
            String cached = redis.opsForValue().get("order:" + orderId);
            if (cached != null) {
                return JsonMapper.read(cached, OrderDto.class);
            }
            OrderDto dto = loadFromDb(orderId);       // 阻塞 IO，现在可以正常卸载
            redis.opsForValue().set("order:" + orderId, JsonMapper.write(dto), Duration.ofMinutes(5));
            return dto;
        } finally {
            lock.unlock();
        }
    }
}
```

全项目 `grep -rn "synchronized" src/main/java` 一共 23 处，其中 7 处里面有阻塞调用，逐个改掉。另外把 HikariCP 从 5.0.1 升到 5.1.0 —— 老版本内部也有 monitor 等待。

## 第二版的数据

同一台 4C8G、同一份 JMeter 脚本（200 并发、持续 10 分钟）：

| 指标 | 固定线程池 | 虚拟线程第一版 | 去掉 pinning 后 |
| --- | --- | --- | --- |
| 平均 QPS | 812 | 861 | 1954 |
| P99 延迟 | 380 ms | 352 ms | 168 ms |
| CPU 峰值 | 42% | 61% | 78% |
| Young GC / min | 3 | 11 | 6 |

CPU 从 42% 吃到 78% 才算正常，之前大半算力根本没用上，全耗在等 IO 上了。GC 次数比第一版降下来，是因为 carrier 不再堆积请求上下文。

## 三个没那么显眼的坑

**别拿虚拟线程当限流用。** 换完之后下游有一次被我打到超时，因为原来 64 个平台线程天然就是并发上限，现在没了。补一个信号量，或者用 `Semaphore` 包一层：

```java
@Component
public class DownstreamGuard {
    private final Semaphore permits = new Semaphore(64);

    public <T> T call(Supplier<T> action) {
        permits.acquireUninterruptibly();
        try {
            return action.get();
        } finally {
            permits.release();
        }
    }
}
```

**`ThreadLocal` 会跟着虚拟线程泛滥。** 以前池化复用线程，一个 `ThreadLocal` 就占一份，倒也不显。现在一个请求一个虚拟线程，里面要塞了大对象，百万级并发下内存会很难看。MDC 那种轻量的没问题，缓存了用户会话对象的那个我改成了显式传参。JDK 21 的 `ScopedValue` 还是预览特性，没上生产。

**监控要换指标。** `ThreadPoolExecutor.getActiveCount()` 那些全没了。现在看的是 `jdk.internal.misc.VirtualThreads` 相关的 JFR 事件，以及业务侧自己的 in-flight 计数。我们的 Grafana 面板为此重做了一版，这个坑纯属没想到。

## 什么时候不该换

CPU 密集的报表计算我原封不动留在平台线程池里。虚拟线程不提供额外的 CPU，它只是让等待 IO 的线程别占着坑。把 JSON 序列化、加密这类活儿搬过去，除了多一层调度没别的收益。

还有事务边界。原来 `@Async` + `ThreadPoolTaskExecutor` 那套，`TransactionSynchronizationManager` 靠 ThreadLocal 传，切到虚拟线程后线程不复用，反而更清晰，但有几个手写的事务传播工具类假设了「线程会复用」，改的时候得单独验。

pinning 检测眼下还只能靠 JFR 事后看，常驻告警没做起来。我在 CI 里加了一条 `-Djdk.tracePinnedThreads=short` 的集成测试检查，`grep` 到 `VirtualThreadPinned` 就 fail，生产上还没接进去；GraalVM Native Image 下虚拟线程的表现又是另一套，得单独看。如果你也在 JDK 21 上做过同样的迁移，尤其是碰到过 `synchronized` 之外的 pinning 来源，欢迎到 GitHub 开 issue 聊两句。

眼下能做的，也就是先把 CI 那条 `-Djdk.tracePinnedThreads=short` 稳稳跑着。
