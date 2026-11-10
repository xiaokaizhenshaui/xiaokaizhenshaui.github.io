---
title: "SpringStream 入门教程学习"
date: 2021-03-24
updated: 2026-11-10
categories:
  - 中间件
tags:
  - "Spring Boot"
  - "Kafka"
  - "消息队列"
lead: "2021 年只贴了一张图就搁那了，这次把没写完的部分补齐。"
---
> 这篇写于 2021 年。原站配图用的免费图床后来全挂了，这次改版把失效截图换成了本地 SVG 示意图，正文和命令保持原样，现在该怎么做放在文末「2026 补记」里。

## SpringStream入门教程学习(更新中)

## springStream应用场景

1. 应用模型

> Spring Cloud Stream由第三方中间件组成。应用间通信通过channel来完成，通道与外界代理的连接则是通过Binder实现。

![Spring Cloud Stream Binder 模型](/images/diagrams/spring-stream-binders.svg)

Binder可以理解为 提供Middleware操作方法的类

## 2026 补记：当年没写完的部分

这篇 2021 年只贴了一张图就停更了，那张图的路径还是 `D:\HexoLearning\...`，浏览器当然打不开。这次把内容补上。

Spring Cloud Stream 3.x 之后注解模型（`@StreamListener`）废弃了，推荐函数式模型。一个收订单消息、落库再发通知的例子：

```java
@Configuration
public class OrderFunctions {
    private static final Logger log = LoggerFactory.getLogger(OrderFunctions.class);
    private final OrderRepository repo;

    public OrderFunctions(OrderRepository repo) {
        this.repo = repo;
    }

    @Bean
    public Function<Flux<OrderEvent>, Flux<Notification>> processOrder() {
        return flux -> flux
            .doOnNext(e -> log.info("收到订单 {}", e.orderId()))
            .map(repo::save)
            .map(Notification::from);
    }
}
```

```yaml
spring:
  cloud:
    stream:
      bindings:
        processOrder-in-0:
          destination: order-events
          group: stock-svc
        processOrder-out-0:
          destination: order-notifications
      kafka:
        binder:
          brokers: localhost:9092
```

绑定名 `processOrder-in-0` 不能随便编，它是「函数名 + `-in-` + 参数序号」。写错了启动时**不会报错**，只是安静地收不到消息 —— 我当年就卡在这儿，盯了半天以为 broker 没通。

现在新项目我反而不太用这层抽象了：直接引 `spring-kafka`，代码量差不多，但排查问题时少一层 Binder 的黑盒。抽象层值不值，取决于你是不是真的会换 MQ；如果三年都没换过，它只是多了一个要读文档的地方。
