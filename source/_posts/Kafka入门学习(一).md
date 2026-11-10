---
title: "Kafka 学习笔记（一）"
date: 2021-01-13
updated: 2026-11-10
categories:
  - 中间件
tags:
  - "Kafka"
  - "消息队列"
lead: "Kafka 的拓扑、日志结构和消费组，原文配图来自已关闭的 kafka.apachecn.org。"
---
> 这篇写于 2021 年。原站配图用的免费图床后来全挂了，这次改版把失效截图换成了本地 SVG 示意图，正文和命令保持原样，现在该怎么做放在文末「2026 补记」里。

## Kafka入门学习

## Kafka初始学习

[官方地址](https://kafka.apache.org/documentation/)

![Kafka 拓扑：Producer / Broker / Consumer Group](/images/diagrams/kafka-architecture.svg)

#### Kafka介绍🎤

**Kafka**是最初由Linkedin公司开发，是一个**分布式**，**分区的**，**多副本的**，**多订阅者**，基于**zk**协调的分布式日志系统，是常用MQ系统的一个，常见于`web/nginx`日志，访问日志，消息服务等等.官网解释为*一个分布式流处理平台*

#### Kafka主要设计目标👍

- 以时间复杂度为O(1)的方式提供消息持久化能力，即使对TB级以上数据也能保证常数时间的访问性能。
- 高吞吐率，单机至少支持 **100k/s**消息传输。
- 支持Kafka Server间的消息分区，及分布式消费，同时保证每个partition内的消息顺序传输。
- 同时支持离线数据处理和实时数据处理，可以在流式记录产生式就进行处理
- 支持在线水平扩展

Kafka的消息传递模式是发布-订阅模式

#### Kafka的优势☝

1. 解耦

   > 在数据处理过程中插入一个隐含的，基于数据的接口层，确保两端遵守同样的接口约束。
   >
   > > 类比污水处理器工序。
2. 冗余

   > 确保处理数据时，发生失败的情况下，数据被持久化。雄安锡队列把数据进行持久化直到它们已经被完全处理。明确该消息已被处理完毕，然后进行删除。
   >
   > > 异常消息持久化。
3. 扩展性和可恢复性

   > 扩展性
   >
   > > 解耦处理过程，增大消息入队和处理频率比较容易。
   >
   > 可恢复性
   >
   > > 一部分组件失效时，不会影响到整个系统。消息队列降低了进程间的耦合度，即使一个消息在处理时挂掉，再次入队时仍可以被处理。
4. 顺序保证和缓冲

   > 保证一个Partition内消息的有序性。
   >
   > 使用一个缓冲层来帮助任务最高效地执行–写入队列的处理尽可能的快速。
5. *削峰填谷*
6. 异步处理

#### 性能比较👊

- RabbitMQ

  本身支持很多协议：AMQP，XMPP，SMTP，STOMP，十分重量级，更适合企业级开发

  支持中心队列排序，负载均衡，数据持久化等
- Redis

  NoSQL,轻量级队列服务，新增HyperLogLog数据结构

  采用的是发布订阅模式，需要开启多个客户端

  [具体操作](https://www.runoob.com/redis/redis-pub-sub.html)
- ZeroMQ

  ZeroMQ号称最快的消息队列系统，尤其针对大吞吐量的需求场景。但是ZeroMQ仅提供非持久性的队列，也就是说如果宕机，数据将会丢失
- ActiveMQ

  ActiveMQ是Apache下的一个子项目。 类似于ZeroMQ，它能够以代理人和点对点的技术实现队列。同时类似于RabbitMQ，它少量代码就可以高效地实现高级应用场景
- Kafka/Jafka

  Kafka是Apache下的一个子项目，是一个高性能跨语言分布式发布/订阅消息队列系统，而Jafka是在Kafka之上孵化而来的，即Kafka的一个升级版。Kafka通过Hadoop的并行加载机制统一了在线和离线的消息处理。Apache Kafka相对于ActiveMQ是一个非常轻量级的消息系统，除了性能非常好之外，还是一个工作良好的分布式系统

#### 术语解释📚

Kafka有四个核心的API

![Partition 日志与 offset](/images/diagrams/kafka-log-anatomy.svg)

- The [Producer API](https://kafka.apache.org/documentation/) 允许一个应用程序发布一串流式的数据到一个或者多个Kafka topic
- The [Consumer API](https://kafka.apache.org/documentation/) 允许一个应用程序订阅一个或多个 topic ，并且对发布给他们的流式数据进行处理。
- The [Streams API](https://kafka.apache.org/documentation/) 允许一个应用程序作为一个*流处理器*，消费一个或者多个topic产生的输入流，然后生产一个输出流到一个或多个topic中去，在输入输出流中进行有效的转换。
- The [Connector API](https://kafka.apache.org/documentation/) 允许构建并运行可重用的生产者或者消费者，将Kafka topics连接到已存在的应用程序或者数据系统。比如，连接到一个关系型数据库，捕捉表（table）的所有变更内容。

在Kafka中，客户端和服务器使用一个简单、高性能、支持多语言的 [TCP 协议](https://kafka.apache.org/protocol.html).

##### Topics

核心概念:提供一串流式记录–topic

> 因为采用的是发布订阅模式，可以拥有一个或者多个消费者来订阅它的数据。
>
> 每一个topic，Kafka集群都会维持一个分区日志。
>
> ![消费组内分区分配](/images/diagrams/kafka-consumer.svg)
>
> 每个分区都是有序且顺序不变的记录集，不断追加到结构化的**commit log**文件。
>
> 每个**queue**都有自己的**offset(偏移量)**来确定每一条记录。

##### Partition

> 日志的分区partition(分布)在Kafka集群的服务器上。每个服务器在处理数据和请求时，共享这些分区，并且会在一配置的服务器上进行备份，确保容错性。
>
> 在处理负载均衡时，采用zk一样的算法，leader处理一切对partition的读写请求，followes则被动同步leader数据。

##### Producer

> 生产者可以将数据发布到所选的topic中，生产者负责将记录分配到topic的哪一个 partition中。

##### Consumer

> 消费者使用一个消费组名称来进行标识，发布到topic中的每条记录被分配给订阅消费组中的一个消费者实例.消费者实例可以分布在多个进程中或者多个机器上
>
> 如果所有的消费者实例在同一消费组中，消息记录会负载平衡到每一个消费者实例.
>
> 如果所有的消费者实例在不同的消费组中，每条消息记录会广播到所有的消费者进程
>
> 可以看到，数个消费者会组成一个消费组，便于扩展和容错。

##### High-Level

> - 生产者发送到特定topic partition 的消息将按照发送的顺序处理。 也就是说，如果记录M1和记录M2由相同的生产者发送，并先发送M1记录，那么M1的偏移比M2小，并在日志中较早出现
> - 一个消费者实例按照日志中的顺序查看记录.
> - 对于具有N个副本的主题，我们最多容忍N-1个服务器故障，从而保证不会丢失任何提交到日志中的记录.

##### Stream批处理

> Kafka 流处理不仅仅用来读写和存储流式数据，它最终的目的是为了能够进行实时的流处理。
>
> 在Kafka中，流处理器不断地从输入的topic获取流数据，处理数据后，再不断生产流数据到输出的topic中去。

## 启动使用

（待更新）

## 2026 补记

原文的图全来自 `kafka.apachecn.org`，那个站已经关了，上面换成了我自己画的矢量图。三年里最大的变化是 ZooKeeper 下线：Kafka 3.3 起 KRaft 可用，4.0 直接移除 ZK 模式，本地单节点不用再开两个进程。

消费者那边我后来统一换了 cooperative sticky 分配器，并改成手动提交：

```java
// 原生 consumer 配置；Spring Kafka 里对应 ConcurrentKafkaListenerContainerFactory
Map<String, Object> props = new HashMap<>();
props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");
props.put(ConsumerConfig.GROUP_ID_CONFIG, "stock-svc");
props.put(ConsumerConfig.PARTITION_ASSIGNMENT_STRATEGY_CONFIG,
        List.of(CooperativeStickyAssignor.class.getName()));
props.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, false);
props.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG, 200);
props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
```

`MAX_POLL_RECORDS` 别一上来就调大。我有一次调到 2000，单批次处理超过 `max.poll.interval.ms`，触发 rebalance，整组反复重平衡，吞吐反而掉了一半。
