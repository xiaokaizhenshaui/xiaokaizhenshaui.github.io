---
title: "用 record + sealed 重构订单状态，少了一半样板代码"
date: 2026-08-08
categories:
  - Java 开发
tags:
  - Java
  - JDK
  - 重构
lead: "7 个状态类瘦掉一半，少掉的 164 行没一行是业务逻辑。"
---

8 月 3 号上午产品说要加个「部分退款」状态。听起来是个小需求：订单状态加个枚举值，几个地方补一下分支。我当时也是这么想的，结果当天下午灰度就出了事——有个用户申请了部分退款，退款金额算成了 0，页面还显示「处理中」。查下来是 `OrderFeeCalculator` 里一段 `if-else` 漏了新状态，走了兜底返回 0。

项目跑在 JDK 21.0.4 / Spring Boot 3.2.5 上，订单状态原来是一个 enum，7 个地方按状态做分支。我第一版的做法是 `grep -rn 'OrderStatus'` 把 switch 全找出来补 case，补了 6 处，自以为齐了。漏的正是那个写成 `if-else` 的计算器——它里面只判断 `status == ...`，压根没出现 `OrderStatus` 这个词，`grep` 按类名搜自然捞不到。编译器一句都没提醒，因为每个 switch 都有 `default`。

第二版干脆换掉这套结构：sealed interface + record + JDK 21 的 switch 模式匹配。改完这 7 个状态类从 312 行压到 148 行，少掉的 164 行全是 getter、`equals`/`hashCode`、还有那个骗过编译器的 `default`。

## 原来的写法哪里不对

把出问题的那段简化一下，保留原样，两个坑都在：

```java
// ---- OrderStatus.java ----
public enum OrderStatus {
    CREATED, PAID, SHIPPED, DONE, CANCELLED
    // 8 月 3 号加了 PARTIAL_REFUNDED，下面这个 switch 编译照样过
}

// ---- OldFeeCalculator.java ----
public final class OldFeeCalculator {

    // 坑一：default 兜底，新增状态悄悄走到这里，一分钱不退，还不报错
    // 坑二：金额用 double，0.1 + 0.2 那套老问题，退款金额能对不上账
    public static double refundOf(OrderStatus status, double paid) {
        return switch (status) {
            case CREATED, CANCELLED -> 0;
            case PAID, SHIPPED      -> paid;
            case DONE               -> paid * 0.8;
            default                 -> 0;
        };
    }
}
```

JDK 21 的 switch 表达式本来是有穷举检查的：对 enum 覆盖全部常量时不写 `default` 也能编译，以后加一个常量，所有相关 switch 会一起报错。坏就坏在 `default`——它把编译器的嘴堵上了。`case` 没覆盖的新状态被当成「其他」，静悄悄走兜底。7 个分支点里 6 个是这种写法，加 `PARTIAL_REFUNDED` 时全部无感。

`double` 那条是顺手翻出来的旧账：金额字段一路用 `double`，对账时偶尔差一分钱，一直没查。这次一并换成 `BigDecimal`。

## sealed + record，让编译器替我数

改完的核心代码，完整一份，JDK 21 下 `javac` 能过（Jackson 注解先留着，第五节要用）：

```java
package com.example.order.domain;

import com.fasterxml.jackson.annotation.JsonTypeInfo;
import java.math.BigDecimal;
import java.time.Instant;

// permits 列全了，编译器知道订单状态一共就这六种
@JsonTypeInfo(use = JsonTypeInfo.Id.NAME, property = "type")
public sealed interface OrderState
        permits Created, Paid, Shipped, Done, Cancelled, PartiallyRefunded {
    String orderId();
}

record Created(String orderId, Instant createdAt) implements OrderState {}

record Paid(String orderId, Instant paidAt, BigDecimal amount) implements OrderState {}

record Shipped(String orderId, String trackingNo) implements OrderState {}

record Done(String orderId, Instant finishedAt) implements OrderState {}

record Cancelled(String orderId, String reason) implements OrderState {}

// 这次新加的：退款金额和已退次数都得带着，不再靠外部 Map 传
record PartiallyRefunded(String orderId, BigDecimal refundedAmount, int refundCount)
        implements OrderState {}

final class StatusText {

    // 没有 default。以后往 permits 里加一个类型，这个方法立刻编译不过
    static String describe(OrderState state) {
        return switch (state) {
            case Created c           -> "待支付，创建于 " + c.createdAt();
            case Paid p              -> "已支付 " + p.amount() + " 元";
            case Shipped s           -> "已发货，运单 " + s.trackingNo();
            case Done d              -> "已完成";
            case Cancelled c         -> "已取消：" + c.reason();
            case PartiallyRefunded r -> "已部分退款 " + r.refundedAmount()
                                        + " 元，共退 " + r.refundCount() + " 次";
        };
    }
}
```

验证方式很直接：把 `PartiallyRefunded` 加进 `permits` 之后，我故意先不改 `StatusText`，跑 `mvn -q compile`，7 个分支点全吐了同一句：

> the switch expression does not cover all possible input values

这就是我要的东西。以前靠 `grep` 和记性，现在漏一处就编译不过，CI 直接拦住。补完 7 处，`git diff --stat` 显示动了 9 个文件。`Done d` 那个模式变量没用到，编译器会嘀咕一句但不影响，真要显示完成时间时再补这处。

## 少掉的 164 行

| | 改前 | 改后 |
| --- | --- | --- |
| 状态定义 | enum 1 个 + 6 个状态 DTO，共 187 行 | sealed 接口 + 6 个 record，共 46 行 |
| 分支代码 | 7 处 switch / if-else，共 103 行 | 7 处 switch 表达式，共 81 行 |
| 其他（配置、注解） | 22 行 | 21 行 |
| 合计 | 312 行 | 148 行 |

大头是那 6 个状态 DTO。以前每个状态有自己的字段，却都挤在同一个 `OrderStateDto` 里：private final 字段、getter、`equals`、`hashCode`、`toString`、全参构造、builder，Lombok 没敢上，组里有人吃过 `@Data` 加继承的亏，全是手写的，一个 30 行。换成 record 之后一行完事，构造、`equals`、`hashCode`、`toString`、访问器全由编译器生成，`orderId()` 顺带把接口里那个抽象方法也实现了。

record 的组件是 final，状态对象天然不可变。原来那个 DTO 有个 `setRefundAmount()` 被两个地方偷偷调用，改的是状态对象本身的值，上次查退款金额算错时绕了半天才找到——现在想这么干也干不了。

分支代码只少了 22 行，比我想的少。因为 switch 表达式本来就没比老的 switch 短多少，真正省的是「不用再写 7 个兜底分支」，以及那 7 处不用再各自 `throw new IllegalStateException("未知状态")`。

## Jackson 的两个坑

Boot 3.2.5 带的是 `com.fasterxml.jackson.core:jackson-databind:2.15.4`。record 的原生反序列化从 Jackson 2.12 就有了，不用加额外模块，普通 record 丢给 `ObjectMapper.readValue` 就能用。坑在多态：这些状态要通过 MQ 的 JSON 消息传，得带类型信息。

第一个坑是 `Instant`。record 组件里有 `createdAt`、`paidAt`，没注册 `JavaTimeModule` 就直接：

> InvalidDefinitionException: Java 8 date/time type java.time.Instant not supported by default

第二个坑更隐蔽。`@JsonTypeInfo` 我用 `Id.NAME` 打在接口上（就是上面那份代码里的注解），具体类型名没写 `@JsonSubTypes`，改成在配置类里集中 `registerSubtypes`：

```java
package com.example.order.config;

import com.example.order.domain.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.jsontype.NamedType;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class JacksonConfig {

    // 类型名集中注册，接口上只留一个 @JsonTypeInfo
    // 新增状态时必须在这里也加一行，编译器不会提醒（这个坑下面说）
    @Bean
    ObjectMapper objectMapper() {
        return JsonMapper.builder()
                .addModule(new JavaTimeModule())   // 不注册的话 Instant 直接反序列化失败
                .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
                .build()
                .registerSubtypes(
                        new NamedType(Created.class, "CREATED"),
                        new NamedType(Paid.class, "PAID"),
                        new NamedType(Shipped.class, "SHIPPED"),
                        new NamedType(Done.class, "DONE"),
                        new NamedType(Cancelled.class, "CANCELLED"),
                        new NamedType(PartiallyRefunded.class, "PARTIALLY_REFUNDED"));
    }
}
```

`JavaTimeModule` 在 `com.fasterxml.jackson.datatype:jackson-datatype-jsr310`，`spring-boot-starter-json` 已经带进来了，不用单独写坐标。

上线前我故意漏掉 `PartiallyRefunded` 那行，发了一条 `{"type":"PARTIALLY_REFUNDED", ...}`，消费者直接：

> InvalidTypeIdException: Could not resolve type id 'PARTIALLY_REFUNDED' as a subtype of OrderState: known type ids = [CREATED, PAID, SHIPPED, DONE, CANCELLED]

也就是说，sealed 把 switch 那 7 处管住了，这份 `registerSubtypes` 列表还是手写的，编译器一点忙都帮不上。现在靠一条集成测试兜着：遍历 `OrderState.class.getPermittedSubclasses()`，逐个断言都在已注册的类型名里。`getPermittedSubclasses()` 是 JDK 17 就有的 API，写起来十来行，比人肉记靠谱。

## 金额和还没解决的

金额全换成 `BigDecimal` 了，构造用 `new BigDecimal("19.90")` 或者 `BigDecimal.valueOf(1990, 2)`，别用 `new BigDecimal(19.90)`——那个 double 构造器把二进制误差原样带进来，`19.90` 会变成 `19.899999...`。对账脚本里那几笔差一分钱的，换完就没了。这个改动跟 sealed 没关系，纯粹是趁着重构一起收拾，单独提一句免得下次又有人写回去。

`registerSubtypes` 那份列表还是手写的，测试能兜住「漏注册」，兜不住「名字写错」——类型名是字符串，拼错一个字母编译照样过，只有消息到了才炸。想过去掉 `@JsonTypeInfo`、改成按字段自己判类型，可那样又回到写 switch 的老路上。另外 MQ 里还飘着老版本消费者，它们只认那 5 个 `type`，新增的 `PARTIAL_REFUNDED` 会被当成未知类型丢进死信，得等合作方发版，估计下周。

多态序列化这块到底有没有更省事的做法，不用再维护一份手写名单？如果你也用 sealed + record 做过状态机，欢迎到 GitHub 开 issue 说两句。
