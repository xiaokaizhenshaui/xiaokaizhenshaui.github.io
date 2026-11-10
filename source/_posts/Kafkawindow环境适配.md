---
title: "Kafka Windows 环境适配"
date: 2022-03-10
updated: 2026-11-10
categories:
  - 中间件
tags:
  - "Kafka"
  - "Docker"
  - "Windows"
lead: "六个 cmd 截图全没了，换成流程图；命令保留，另附现在用 KRaft 的起法。"
---
> 这篇写于 2022 年。原站配图用的免费图床后来全挂了，这次改版把失效截图换成了本地 SVG 示意图，正文和命令保持原样，现在该怎么做放在文末「2026 补记」里。

## Kafka入门学习

## Kafka预备材料

kafka需要在zookeeper基础上运行，则需要准备zookeeper-3.4.6，kafka_2.13.3-3.1.0.tgz

## zookeeper启动

zookeeper版本暂时没有定位

1. 解压打开文件conf目录，将zoo_sample.cfg重命名成zoo.cfg
2. 从文本编辑器里打开zoo.cfg，把dataDir的值改成“E:\develop\zookeeper-3.4.6\zookeeper-3.4.6\data”
3. 添加环境变量

   1. ZOOKEEPER_HOME: E:\develop\zookeeper-3.4.6\zookeeper-3.4.6
   2. Path: 在现有的值后面添加 “%ZOOKEEPER_HOME%\bin”
4. 运行Zookeeper

```cmd
zkserver
```

   效果：

   ![Windows 本地启动 Kafka 的顺序](/images/diagrams/kafka-windows.svg)

## 安装运行Kafka

3.1 下载安装文件： <http://kafka.apache.org/downloads.html>

3.2 解压文件（本文解压到 G:\kafka_2.11-0.10.0.1）

3.3 打开G:\kafka_2.11-0.10.0.1\config

3.4 从文本编辑器里打开 server.properties

3.5 把 log.dirs的值改成 “G:\kafka_2.11-0.10.0.1\kafka-logs”

3.6 打开cmd

3.7 进入kafka文件目录: cd /d G:\kafka_2.11-0.10.0.1\

3.8 输入并执行以打开kafka:

```cmd
.\bin\windows\kafka-server-start.bat .\config\server.properties
```

## 操作启动

1. 创建topics
2. topics=xiaokai

```cmd
kafka-topics.bat --create --zookeeper localhost:2181 --replication-factor 1 --partitions 1 --topic xiaokai
```

   可能会报错，Exception in thread “main“ joptsimple.UnrecognizedOptionException: zookeeper is not a recognizedException in thread “main“ joptsimple.UnrecognizedOptionException: zookeeper is not a recognized

   是因为2.2版本以后不再需要Zookeeper链接字符串，仅需要–bootstrap-server localhost:9092来替代- -zookeeper localhost:2181

```cmd
kafka-topics.bat --create --bootstrap-server localhost:9092 --replication-factor 1 --partitions 1 --topic txiaokai
```

   检查创建的topics

```cmd
kafka-topics.bat --list --bootstrap-server localhost:9092
```

   即为创建成功
3. 打开一个producer

```cmd
kafka-console-producer.bat --broker-list localhost:9092 --topic xiaokai
```

4. 打开一个consumer

   同时启动，不需要关闭生产者

```cmd
kafka-console-consumer.bat --bootstrap-server localhost:9092 --topic xiaokai
```

## 2026 补记

六张 cmd 截图全失效了，合并成一张流程图。现在别在 Windows 上直接解压 Kafka 跑了，路径里的空格和 `.bat` 的换行符差异够折腾半天。KRaft 单节点用 Compose 起：

```yaml
services:
  kafka:
    image: apache/kafka:3.8.0
    ports: ["9092:9092"]
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
```

```bash
docker compose up -d
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 --create --topic order-events --partitions 3
```

当年最容易撞上的两个报错：`NoSuchFileException` 多半是路径分隔符被当成转义，以及「输入行太长」是 CLASSPATH 拼接爆了。两个都不用改 Kafka，换环境就好。
