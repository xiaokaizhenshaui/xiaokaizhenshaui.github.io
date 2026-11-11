---
title: "GraalVM Native Image 打包 Spring Boot：启动 0.08 秒，但内存没省"
date: 2026-11-07
categories:
  - Java 开发
tags:
  - Java
  - GraalVM
  - Spring Boot
lead: "冷启动压到 0.078 秒我信了，压满 10 分钟内存还是 310MB，白高兴。"
---

## 扩容那 40 秒

现在回看，那天下午光盯着 `kubectl get pods -w` 就盯了小半天。2026-11-05 下午 15 点出头，大促预热，HPA 把订单服务从 4 个 pod 拉到 12 个。新 pod 从 Pending 到 Ready 普遍 38~42 秒，其中真正属于我们代码的只有一小段：JVM 起来、Spring 上下文刷新，日志里那行 `Started OrderApiApplication in 2.6 seconds`，再叠加 readiness 探针的 `initialDelaySeconds: 10` 和两次成功间隔，第一波流量打进来时前面几个请求基本是凉的。

> `order-api-7d9f4c8b5-x2mkq   0/1   Running   0   19s` → `order-api-7d9f4c8b5-x2mkq   1/1   Running   0   41s`

扩容慢这事儿吵了不止一次，加副本数、调探针都试过，能抠的空间不多。有人提「要不试试 Native Image」，我当时心里是翻白眼的——这玩意儿我 2021 年在个人项目里玩过一次，反射配置写到我怀疑人生。但冷启动这块数字确实诱人，加上 Spring Boot 3 的 AOT 把大部分 hint 自动生成了，就答应下来拿预发跑一轮。

环境先摆清楚：Spring Boot 3.2.5、JDK 21（Temurin）、GraalVM 21（其实就是 GraalVM for JDK 21，`native-image --version` 出来 `23.1.2`，组里都简称 GraalVM 21）、`native-maven-plugin` 我写死 0.10.3 没交给父 pom 管，CI runner 是 2C4G 的共享机器。（这个 2C4G 是后面所有倒霉事的源头，先记一笔。）

## 第一版 profile，和跑了 6 分钟被 kill 的那次

第一版 profile 基本照抄 start.spring.io 生成的模板：`spring-boot-maven-plugin` 挂一个 `process-aot` execution，`native-maven-plugin` 把 `compile-no-fork` 绑到 `package`，没加任何 `buildArgs`。命令用的是官方文档那句：

```bash
$ ./mvnw -Pnative native:compile -DskipTests
[INFO] --- spring-boot-maven-plugin:3.2.5:process-aot (process-aot) @ order-api ---
[INFO] --- native-maven-plugin:0.10.3:compile-no-fork (build-native) @ order-api ---
[INFO] Executing: /opt/graalvm/bin/native-image @target/native-image-args.txt
[ERROR] Error: Image build request failed with exit status 137
[INFO] BUILD FAILURE
[INFO] Total time:  06:03 min
```

六分零三秒，等来的不是 BUILD SUCCESS，是 `exit status 137`。137 = 128 + 9，SIGKILL，`dmesg` 里那行说得很直白：

> `Killed process 2143 (native-image), total-vm:7184324kB, anon-rss:3891044kB, ...`

一句话，`native-image` 自己就是个吃内存的 Java 进程，做可达性分析时把 4G 的 runner 撑爆了，OOM killer 直接收走。我之前完全没往这儿想——下意识觉得「构建产物是省内存的，构建过程应该也省」，这逻辑现在看挺蠢的。（那天 CI 队列里还排着另外三个 job，我这一跑把它们也拖慢了，隔壁组在群里问了一句「谁在跑 native」，我没敢认。）

## 把内存喂饱之后

先把 runner 临时提到 4C8G，再给 `native-image` 单独划堆。`-J` 前缀是传给构建器 JVM 自己的参数，`-J-Xmx6g` 才是对的地方；`--no-fallback` 是顺手加的，免得它悄悄退化成 fallback image 还让我以为成功了。

其实 `-J-Xmx6g` 这个值是试出来的。一开始按老习惯给了 `-J-Xmx4g`，跑在 8G 的 runner 上还是在第 5 分钟被 kill 了一回，加到 6g 才稳稳走完；8G 里留 6G 给构建器、剩 2G 给系统和旁边那些 job，是拍脑袋定的，没细算，能用就行。`-J` 这个前缀我头一回还写漏了，直接写成 `-Xmx6g`，native-image 当场不认，又回文档翻了一趟才明白它是把参数转交给构建器 JVM 的。profile 改完：

```xml
<profiles>
  <profile>
    <id>native</id>
    <build>
      <plugins>
        <plugin>
          <groupId>org.springframework.boot</groupId>
          <artifactId>spring-boot-maven-plugin</artifactId>
          <executions>
            <execution>
              <id>process-aot</id>
              <goals>
                <goal>process-aot</goal>
              </goals>
            </execution>
          </executions>
        </plugin>
        <plugin>
          <groupId>org.graalvm.buildtools</groupId>
          <artifactId>native-maven-plugin</artifactId>
          <version>0.10.3</version>
          <configuration>
            <buildArgs>
              <buildArg>-J-Xmx6g</buildArg>
              <buildArg>--no-fallback</buildArg>
            </buildArgs>
          </configuration>
          <executions>
            <execution>
              <id>build-native</id>
              <goals>
                <goal>compile-no-fork</goal>
              </goals>
              <phase>package</phase>
            </execution>
          </executions>
        </plugin>
      </plugins>
    </build>
  </profile>
</profiles>
```

再跑，`./mvnw -Pnative native:compile -DskipTests` 这次走完了：

> `[INFO] BUILD SUCCESS` / `[INFO] Total time:  06:12 min` / `Finished generating 'order-api' in 5m48s.`

构建时间几乎没变，还是六分多钟，只是这次真的出了 `target/order-api` 那个 88 MB 的二进制。因为 `compile-no-fork` 绑在 `package` 阶段，`mvn -Pnative package` 也能出，我两种都试过，产物一样。（AOT 生成的那堆东西在 `target/spring-aot/main/sources`，我点进去看过一眼，全是机器味儿很重的 Java，看两行就关了。）

## 二进制起来第一分钟就 500 了

`./target/order-api --server.port=8080` 起得确实快，0.0x 秒，`/actuator/health` 立刻 UP。我还没来得及高兴，随手 curl 了一下 `/order/SKU-88213`，500：

> `com.fasterxml.jackson.databind.exc.InvalidDefinitionException: No serializer found for class com.acme.order.dto.CouponDTO and no properties discovered to create BeanSerializer (to avoid exception, disable SerializationFeature.FAIL_ON_EMPTY_BEANS)`

类明明在，方法被 AOT 剪了。Native Image 是封闭世界假设，运行时才靠反射摸到的构造、字段、getter，构建期不登记就一律不进镜像。Spring Boot 的 AOT 能覆盖自己那套（`@Controller`、`@Bean`、配置绑定这些），但我们的 DTO 和自包的那层代理它管不着。

第一版我图省事，只在配置类上拍了个 `@RegisterReflectionForBinding({OrderDTO.class, CouponDTO.class})`，DTO 那关过了；结果下一秒又挂在我们自己用 `Proxy.newProxyInstance` 包的一个 `@Transactional` 兜底接口上——JDK 动态代理的接口列表也得登记。补完的 `RuntimeHintsRegistrar` 长这样：

```java
package com.acme.order.config;

import com.acme.order.dto.CouponDTO;
import com.acme.order.dto.OrderDTO;
import com.acme.order.spi.OrderQuery;
import org.springframework.aop.SpringProxy;
import org.springframework.aop.framework.Advised;
import org.springframework.core.DecoratingProxy;
import org.springframework.aot.hint.MemberCategory;
import org.springframework.aot.hint.RuntimeHints;
import org.springframework.aot.hint.RuntimeHintsRegistrar;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.ImportRuntimeHints;
import org.springframework.context.annotation.RegisterReflectionForBinding;

public class OrderRuntimeHints implements RuntimeHintsRegistrar {

    @Override
    public void registerHints(RuntimeHints hints, ClassLoader classLoader) {
        // Jackson 序列化要用构造、字段和 getter/setter，AOT 默认全剪掉
        hints.reflection().registerType(OrderDTO.class, MemberCategory.values());
        hints.reflection().registerType(CouponDTO.class, MemberCategory.values());

        // 自己包的那层 @Transactional 兜底接口走的是 JDK 动态代理
        hints.proxies().registerJdkProxy(
                OrderQuery.class, SpringProxy.class, Advised.class, DecoratingProxy.class);
    }
}

@Configuration
@ImportRuntimeHints(OrderRuntimeHints.class)
@RegisterReflectionForBinding({OrderDTO.class, CouponDTO.class})
class AotHintConfig {
}
```

（两个顶层类放一个文件里，一个 public 一个包内可见，能编译，别学我这么懒。）注解和 registrar 其实有重叠，`@RegisterReflectionForBinding` 覆盖的 DTO 我后来没从 registrar 里删，留着当双保险，反正多注册一点不会让镜像大多少。为了避免下次再靠「跑一遍接口才发现问题」，我又补了个单测用 `RuntimeHintsPredicates.reflection().onType(OrderDTO.class)` 断言 hint 在，这个比人肉 curl 靠谱。

## 三组数字，以及那张被打脸的截图

重复冷启动十次取中位数，压测用 `wrk -t4 -c100 -d600s --latency http://127.0.0.1:8080/order/SKU-88213` 跑 10 分钟。JVM 那组把 `-Xms`、`-Xmx` 都钉在 256m，免得 GC 自己扩堆把 RSS 搅乱；native 那边没有 Xmx 可设，堆策略构建期就定死了，我没动。RSS 取 cgroup 的 `memory.current`，每 30 秒采一次，取后 5 分钟的稳定值，不是峰值——峰值两组都冲到过 400 MB 以上，拿峰值比没意义。数字如下：

| 对比项 | JVM 模式（Temurin 21，`-Xmx256m`） | Native Image |
| --- | --- | --- |
| 产物体积 | 42 MB（fat jar） | 88 MB（单个二进制，还不含 glibc） |
| 启动到 `/actuator/health` 就绪 | 2.6 s | 0.078 s |
| 常驻 RSS（200 QPS 压 10 分钟后） | 330 MB | 310 MB |

启动计时那条命令和对应的 RSS：

```bash
$ /usr/bin/time -v ./target/order-api --server.port=8080
2026-11-06T14:02:31.118+08:00  INFO  c.a.o.OrderApiApplication : Started OrderApiApplication in 0.078 seconds (process running for 0.092)
        Maximum resident set size (kbytes): 98432
```

空载刚起来那会儿 native 只有 96 MB、JVM 214 MB，看着像省了一半，我一激动截了图发群里，配了句「这波稳了」。十分钟后那张图就被打脸了：压测到 200 QPS，Jackson 序列化、DTO 分配、Hikari 连接池这些活一样没少，native 没有 JIT、GC 的弹性也不一样，堆外加堆一路涨到 310 MB，跟 JVM 的 330 MB 基本贴在一起，差的那 20 MB 还在波动范围内。说白了冷启动那 2.5 秒是真省下来了，内存没省——空载那个漂亮数字只存在于没有流量的时候。

体积上更不占理：42 MB 的 fat jar 变成 88 MB 的二进制，镜像层还得多塞一份 glibc。

（本来还想补一列「预热后稳态延迟」：JVM 跑满 10 分钟 JIT 编译完，P99 反而比 native 低了一截，这结果贴出来怕被说偏心，就压着没放表里。）

## 代价：CI 时长和调试体验

原来 `mvn package` 一分四十秒，native 这一趟六分十二秒，翻了快四倍。每个 PR 都跑不现实，我们改成只在大促分支和 nightly 上跑，`native` profile 从默认流水线里摘了出来。这还是单机串行，真要并行几个 namespace，构建机的内存得再翻。

更难受的是调试。native 里没有 `-XX:+HeapDumpOnOutOfMemoryError`，`jstack`、`jmap`、`jcmd` 全用不上；出了异常，堆栈是符号化过后薄薄几行，行号经常对不上源码；反射漏注册这种事没有任何静态检查能保底，只能靠接口跑一遍撞出来——我这次是 curl 撞出来的，下单链路里还有两个不常走到的分支，到现在我也没十足把握它俩的 hint 齐了。AOT 生成的 sources 能读，但那不是给人读的。（native 的日志文件默认也不带 JVM 那套 GC log，排查内存全靠 `/usr/bin/time -v` 和 cgroup 的 `memory.current`，糙得很。）

冷启动这笔账算清楚了：0.078 秒对 2.6 秒，扩容那 40 秒能砍掉一小截，值不值见仁见智；内存那笔账是平的，甚至体积还亏了。但有个问题我一直没答案：310 MB 里到底哪部分是堆外、哪部分是 native image 自己的元数据？`-XX:+PrintGCDetails` 没了，cgroup 只能给个总数，我找不到等价的观测手段把这块拆开。还有第三方 SDK 里那些藏在 `Class.forName` 后面的类，AOT 静态扫不到，我现在只能靠 nightly 跑一遍全量接口碰运气。这活儿全靠撞，撞不出来就当没事，糊弄得很。
