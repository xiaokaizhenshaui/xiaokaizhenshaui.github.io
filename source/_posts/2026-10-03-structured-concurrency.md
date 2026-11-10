---
title: "异步编排写到第三版，我换成了 StructuredTaskScope"
date: 2026-10-03
categories:
  - Java 开发
tags:
  - Java
  - 并发
  - JDK
lead: "订单详情页并行查三个下游，CompletableFuture.allOf 在 800ms 超时后返回了，另外两个线程却又闷头跑了 1.2 秒；换成 JDK 21 的 StructuredTaskScope 之后它们才真的被取消。"
---

## 22:14 那条 P99 告警

2026-10-02 晚上 22:14，我正准备合电脑，企业微信机器人弹了一条：订单详情接口 P99 从 340ms 涨到 1.8s，错误率没动，就是慢。这接口我太熟了，拿一个 sku 去并行查库存、物流、优惠券三个下游，拼成 `OrderDetail` 返回，三者互不依赖，本来就该并发。

上 Kibana 捞了一眼，慢的那批请求有个共同点：优惠券服务那天在灰度，偶发 1.5s 才回。我给整个编排设了 800ms 超时，按理说到点就该返回兜底内容，可响应时间还是被拖到 1.5s 往上。第一反应是超时没生效，翻完代码发现它生效了，只是生效得不太对劲。

顺带一提，我们组预发机器的 Dockerfile 里写死了 `eclipse-temurin:17-jdk`，这次为了试 StructuredTaskScope 我专门拉了个 21 的镜像，后面这一通折腾有小一半是这个镜像闹的。（改基础镜像这种事，运维同学第二天才在群里回我一个「？」。）

## 第一版：CompletableFuture.allOf，写得挺顺

最初的版本大概长这样，三个 `supplyAsync` 丢进自己那个 `detailPool`，`orTimeout` 兜 800ms，然后 `allOf` 一收：

```java
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;

public class OrderDetailService {
    private final Executor detailPool;
    private final StockClient stockClient;
    private final LogisticsClient logisticsClient;
    private final CouponClient couponClient;

    public OrderDetailService(Executor detailPool, StockClient stockClient,
                              LogisticsClient logisticsClient, CouponClient couponClient) {
        this.detailPool = detailPool;
        this.stockClient = stockClient;
        this.logisticsClient = logisticsClient;
        this.couponClient = couponClient;
    }

    public OrderDetail load(String sku) {
        CompletableFuture<Stock> stock = CompletableFuture
                .supplyAsync(() -> stockClient.query(sku), detailPool)
                .orTimeout(800, TimeUnit.MILLISECONDS);
        CompletableFuture<Logistics> logistics = CompletableFuture
                .supplyAsync(() -> logisticsClient.query(sku), detailPool)
                .orTimeout(800, TimeUnit.MILLISECONDS);
        CompletableFuture<Coupon> coupon = CompletableFuture
                .supplyAsync(() -> couponClient.query(sku), detailPool)
                .orTimeout(800, TimeUnit.MILLISECONDS);

        CompletableFuture.allOf(stock, logistics, coupon).join();

        return new OrderDetail(stock.join(), logistics.join(), coupon.join());
    }
}
```

跑了一年多没出过事，我一直觉得这写法没毛病。（`allOf` 之后那三个 `join()` 不会再阻塞，因为已经都完成了，这点我当时还专门跟同事争过一轮，结果是我对了，赢得也没什么可高兴的。）

问题出在 `orTimeout` 的语义：800ms 到点，它只把**那一个** CompletableFuture 置成失败，`allOf` 因此抛 `CompletionException`，接口走兜底。可另外两个 `supplyAsync` 早提交进 `detailPool` 了，任务一旦开跑，就跟这个 future 的完成状态脱了钩。没人取消它们，线程照样把 HTTP 发出去、把响应反序列化完，只是结果再没人读。平时三个下游都快，看不出来；一旦有一个慢，另外两个「陪跑」的耗时全压在线程池占用上，我们那个池子一共 32 个线程，压测时被占满过好几回。

把那次慢请求的 traceId 捞出来 grep 一下，实锤了：

```bash
$ grep 'traceId=8f3c21' /var/log/order-detail/app.log | grep -E '超时|cost=|兜底'
22:14:06.901  WARN  [detailPool-7 ]  下游超时 800ms，sku=SKU-88213，downstream=coupon
22:14:06.903  INFO  [detailPool-7 ]  返回兜底，traceId=8f3c21
22:14:07.988  INFO  [detailPool-3 ]  库存查询完成 cost=1092ms
22:14:08.104  INFO  [detailPool-11]  物流查询完成 cost=1203ms
```

接口 06.903 就返回了，物流那条线程 08.104 才打完 cost。超时之后另外两个下游又白白跑了 1.2 秒——取消没传播出去，这才是第一版真正的 bug。（这段日志我贴到组里，有人回「那就 cancel 一下呗」，于是有了下面那段不堪回首的第二版。）

## 第二版：手写 exceptionally + cancel，越写越别扭

知道病因，我很自然地想「在异常分支里把另外两个 cancel 掉不就行了」。于是把三个 future 塞进 `List`，`whenComplete` 里记状态，`allOf` 失败时遍历 list 调 `cancel(true)`，再用 `exceptionally` 补兜底值，结果收集靠 `AtomicReference`。

写了七十来行，能跑，但我越看越烦：

- `cancel(true)` 只是发中断，下游用的是 JDK 自带的 `HttpClient` 同步 `send`，它对中断并不干脆，连接该等还是等；
- 结果和异常分散在 `whenComplete`、`exceptionally`、`handle` 三处，谁先谁后全靠人肉保证，加一个下游就得再改一遍遍历逻辑；
- 最要命的是没有「作用域」这个概念：这三个 future 的生命周期散在方法里，方法都返回了它们还在跑，我得自己向评审证明「不会漏」。

改到第三遍我把它整个删了。为了一个超时的取消传播手写一套状态机，实在不值当。那天接近 23:40，我想起 JDK 21 里那个还是预览状态的 StructuredTaskScope，JEP 453，主打的一句话正好是「子任务的生命周期不能越过产生它的代码块」。

（再顺带一提，`orTimeout` 是 JDK 9 才有的。更早的版本我们用一个 `ScheduledExecutorService` 定时 `completeExceptionally`，连超时线程自己都得管，那套更糙，这里就不翻旧账了。）

## 第三版：StructuredTaskScope.ShutdownOnFailure

JDK 21 里它搬到了 `java.util.concurrent`（19/20 那会儿还在 `jdk.incubator.concurrent`，import 别写错），仍是 preview API。重写之后：

```java
import java.time.Instant;
import java.util.concurrent.StructuredTaskScope;
import java.util.function.Supplier;

public class OrderDetailService {
    private final StockClient stockClient;
    private final LogisticsClient logisticsClient;
    private final CouponClient couponClient;

    public OrderDetailService(StockClient stockClient, LogisticsClient logisticsClient,
                              CouponClient couponClient) {
        this.stockClient = stockClient;
        this.logisticsClient = logisticsClient;
        this.couponClient = couponClient;
    }

    public OrderDetail load(String sku) throws InterruptedException {
        try (var scope = new StructuredTaskScope.ShutdownOnFailure()) {
            Supplier<Stock> stock = scope.fork(() -> stockClient.query(sku));
            Supplier<Logistics> logistics = scope.fork(() -> logisticsClient.query(sku));
            Supplier<Coupon> coupon = scope.fork(() -> couponClient.query(sku));

            // 等全部完成，或第一个失败触发 shutdown，或到 deadline
            scope.joinUntil(Instant.now().plusMillis(800));
            scope.throwIfFailed(e -> new OrderDetailException("下游查询失败", e));

            return new OrderDetail(stock.get(), logistics.get(), coupon.get());
        }
    }
}
```

`OrderDetailException` 是项目里自己那个 `RuntimeException`，就不贴了。几个点是我逐个试出来的：`fork` 返回 `Subtask<T>`，它实现了 `Supplier<T>`，所以拿 `Supplier` 接就行，`get()` 在子任务没成功完成时抛 `IllegalStateException`。`ShutdownOnFailure` 的语义是任何一个子任务抛异常就立刻 `shutdown()` 整个作用域——shutdown 会打断还没完成的兄弟任务，等它们都结束，`join()` / `joinUntil()` 才返回；`try-with-resources` 的 `close()` 再兜一层底，代码块一退出，绝不会有子任务还活着。第一版缺的就是这个。

`throwIfFailed` 我用了带 mapper 的重载，把下游异常包成自己的运行时异常，省得方法签名上挂一串 `throws`。超时换成 `joinUntil(Instant)`，到点返回而不是抛异常，剩下的任务在 `close()` 里被取消。

跟虚拟线程是天生一对：21 这个版本里 `StructuredTaskScope` 无参构造默认就给每个子任务开虚拟线程（想用平台线程，传一个 `ThreadFactory` 进构造函数即可，比如 `Thread.ofVirtual().name("detail-", 1).factory()`）。三个阻塞式 HTTP 挂在虚拟线程上，不占平台线程，我那个 32 线程的 `detailPool` 也就顺手删了——删的时候还有点心虚，毕竟它陪了我们一年多。

预发压了一轮，同样把优惠券拖到 1.5s，日志换成 `到达 deadline，取消兄弟任务`、`subtask=logistics state=CANCELLED`、`subtask=stock state=CANCELLED`，803ms 收工，P99 回到 360ms 上下。线程池占用没了。

## --enable-preview 这个坑，踩了整整一晚上

代码写爽了，编译先给我一巴掌：

> `mvn -q compile` 直接甩回来：`error: StructuredTaskScope is a preview API and is disabled by default. (use --enable-preview to enable preview APIs)`

加上之后能编译，跑测试又挂：

> `java.lang.UnsupportedClassVersionError: Preview features are not enabled for com/acme/order/OrderDetailServiceTest (class file version 65.65535). Try running with '--enable-preview'`

`65.65535` 这个魔数我记了很久——major 65 是 JDK 21，minor 65535 是 preview class 的标记，JVM 不带 `--enable-preview` 直接拒载。坑在于这个 flag 编译和运行时**各要一份**，而且必须配 `--release 21`，`-source/-target` 那套不认。CI、单测、IDE、生产镜像四处都得齐，漏一个就是上面两种错之一。pom 改完长这样：

```xml
<properties>
  <maven.compiler.release>21</maven.compiler.release>
</properties>

<build>
  <plugins>
    <plugin>
      <groupId>org.apache.maven.plugins</groupId>
      <artifactId>maven-compiler-plugin</artifactId>
      <version>3.11.0</version>
      <configuration>
        <release>21</release>
        <compilerArgs>
          <arg>--enable-preview</arg>
        </compilerArgs>
      </configuration>
    </plugin>
    <plugin>
      <groupId>org.apache.maven.plugins</groupId>
      <artifactId>maven-surefire-plugin</artifactId>
      <version>3.2.2</version>
      <configuration>
        <argLine>--enable-preview</argLine>
      </configuration>
    </plugin>
  </plugins>
</build>
```

Dockerfile 的 `ENTRYPOINT` 也补成了 `java --enable-preview -jar app.jar`。（顺带吐槽，IDEA 里光把 Project SDK 切成 21 不够，还得在 Compiler 设置里勾上 preview，不然编辑器一片红，我一度以为自己 import 错了包，来回删了三遍。）

## 上线前没敢按的那个按钮

真到评审，卡住的反而不是代码。

| 项 | 现状 | 麻烦 |
| --- | --- | --- |
| JDK | 生产 17，预发单独 21 | 基础镜像、启动脚本、监控探针都得跟一套 |
| preview flag | 编译 / 测试 / 运行三处 | 漏配就是 `65.65535` |
| API 稳定性 | JEP 453 一次预览 | 之后几个 JDK 这套 API 又动过刀 |
| 回滚 | 保留第一版分支 | 开关得做，不能一刀切 |

预览两个字不是白加的。StructuredTaskScope 在 21 之后又经历了几轮预览修订，`ShutdownOnFailure` 的用法、`join` 的行为都调过；真上了生产，等于把将来升级 JDK 的账先欠着。再加上下游那几个客户端还是同步阻塞的，虚拟线程被取消时连接释放得干不干净，我手里只有预发那点数据，不够硬。

评审的结论是：先在预发挂着，生产继续跑第一版。不过当天我还是上了个小改动——把第一版 `detailPool` 的队列从无界换成 `ArrayBlockingQueue(256)`，并加了拒绝兜底，免得再被「陪跑」任务把池子占满。这点改动小，倒是最先落地的。

## 还没解决的

`joinUntil` 到点返回后 `throwIfFailed` 是不会抛的——超时不算子任务失败，三个 `Subtask` 里可能还有 `state() != SUCCESS` 的，这时候直接 `get()` 会吃 `IllegalStateException`。我现在是在 `throwIfFailed` 前面手动把 `state()` 判一遍，丑是丑了点，但能跑。更想不通的是：`joinUntil` 的 800ms 和下游 `HttpClient` 自己那个 1200ms 读超时怎么对齐？上层 deadline 比下游短，取消是取消了，可底层那条连接到底什么时候真正还给连接池，我还没抓到干净的证据。等哪天把虚拟线程的 dump 看明白，下次再写。
