---
title: "本地中间件全家桶：一个 compose.yaml 搞定"
date: 2026-09-19
categories:
  - 中间件
tags:
  - Docker
  - Compose
  - 开发环境
lead: "MySQL 8、Redis 7、单节点 Kafka KRaft、ES 8 塞进一个 compose.yaml，从手动装半天缩到 docker compose up -d --wait 的 90 秒，代价是被 ES 一口吃掉 4G 内存坑过。"
---

9 月 17 号晚上 21:40，新 checkout 的项目在我这台 16G 的 M2 上死活起不来，日志第一行就是 `Communications link failure`，`Caused by: java.net.ConnectException: Connection refused`，连的是 `localhost:3307` 的 MySQL。可 `docker compose ps` 里 MySQL 明明是 `Up 2 seconds` 啊。盯着看才反应过来：`Up` 只代表进程起来了，MySQL 8 第一次初始化数据目录要跑几十秒，这会儿端口根本没在监听，应用抢跑，直接被拒。

（顺带一提，我 2021 年还写过一篇《手动在 CentOS 7 上装 Docker 再一个个拉 MySQL/Redis》，光配 my.cnf 字符编码和开机自启就写了小两千字。现在回头看纯属自己折腾自己，那篇底下有读者留言问「为啥不直接用 compose」，当时嘴硬没回，这回算是还债了。）

## 第一版：只有 depends_on，没有健康

最早那版我写的是短语法 `depends_on: [mysql, redis, kafka, elasticsearch]`。它只保证「容器启动顺序」，不保证「服务能用」。MySQL 初始化、ES 起 JVM 做 recovery、Kafka 选 controller，这些都要时间，应用偏偏在 `Up` 的瞬间就开连。改前起十次有七次 `Connection refused`，剩下三次连上了 ES 也在报 `master_not_discovered_exception`。后来每个中间件自己定义 `healthcheck`，应用侧全换成 `condition: service_healthy`，Compose 等健康检查过了才拉应用，起十次十次干净。这个 `depends_on` 的正确写法在下面完整文件里的 `app` 服务中。

## 端口和 volume 先理顺

我本机 brew 装了个 MySQL 占着 3306，另一个老项目的容器占着 9200，Redis 和 Kafka 也各有遗留。四个中间件的宿主端口全错开，容器内部端口保持不变，免得改应用配置：

| 服务 | 镜像 | 宿主端口 | 容器端口 | 内存上限 |
| --- | --- | --- | --- | --- |
| mysql | mysql:8.0 | 3307 | 3306 | — |
| redis | redis:7.2 | 6380 | 6379 | — |
| kafka | apache/kafka:3.7.0 | 9094 | 29092 | — |
| elasticsearch | elasticsearch:8.13.4 | 9201 | 9200 | 2g |

volume 用命名卷，别用 `./data` 那种相对绑定——组里三人各自路径不一样，换台机器就丢数据。重置脚本里 `down -v` 会把 compose 里声明的命名卷一起删，干净。

定位端口冲突也花了点时间。第一版我直接写死 `3306:3306`，`docker compose up` 当场报 `Error starting userland proxy: listen tcp4 0.0.0.0:3306: bind: address already in use`。`lsof -i :3306` 一看是 brew 那个 MySQL 在跑，`lsof -i :9200` 又撞上隔壁项目的 ES。索性把四个宿主端口整体后移，全塞进 `.env`，谁本机占了哪个改一行就行，compose 文件一个字不用动。还有个小坑：compose 的 `ports` 里 `${MYSQL_PORT}:3306` 必须拿引号包起来，我第一版漏了引号，YAML 把 `3306:3306` 那种写法折腾出一回 `services.mysql.ports must be a list` 的报错。

## 完整 compose.yaml

```yaml
name: local-mw

services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: ${MYSQL_DATABASE}
      TZ: Asia/Shanghai
    ports:
      - "${MYSQL_PORT}:3306"
    volumes:
      - mysql-data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-p${MYSQL_ROOT_PASSWORD}"]
      interval: 5s
      timeout: 3s
      retries: 20
      start_period: 30s

  redis:
    image: redis:7.2
    command: ["redis-server", "--appendonly", "yes"]
    ports:
      - "${REDIS_PORT}:6379"
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 20

  kafka:
    image: apache/kafka:3.7.0
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: INTERNAL://:9092,HOST://:29092,CONTROLLER://:9093
      KAFKA_ADVERTISED_LISTENERS: INTERNAL://kafka:9092,HOST://localhost:${KAFKA_PORT}
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: INTERNAL:PLAINTEXT,HOST:PLAINTEXT,CONTROLLER:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: INTERNAL
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0
    ports:
      - "${KAFKA_PORT}:29092"
    healthcheck:
      test: ["CMD-SHELL", "/opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092 >/dev/null 2>&1"]
      interval: 10s
      timeout: 5s
      retries: 20
      start_period: 20s

  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.13.4
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
      - TZ=Asia/Shanghai
    ports:
      - "${ES_PORT}:9200"
    volumes:
      - es-data:/usr/share/elasticsearch/data
    ulimits:
      memlock:
        soft: -1
        hard: -1
    mem_limit: 2g
    healthcheck:
      test: ["CMD-SHELL", "curl -fs http://localhost:9200/_cluster/health >/dev/null || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 40s

  app:
    build: .
    env_file: .env
    ports:
      - "8080:8080"
    depends_on:
      mysql:          { condition: service_healthy }
      redis:          { condition: service_healthy }
      kafka:          { condition: service_healthy }
      elasticsearch:  { condition: service_healthy }

volumes:
  mysql-data:
  redis-data:
  es-data:
```

几个点记一下。Kafka 走 KRaft 单节点，不挂 ZooKeeper，`KAFKA_PROCESS_ROLES: broker,controller` 把两个角色塞进一个进程，`KAFKA_CONTROLLER_QUORUM_VOTERS` 里那个 `1@kafka:9093` 用的是服务名做内部 DNS。副本数相关的三个参数全压成 1，不然单节点一直报 under-replicated。`start_period` 是给首次启动的宽限期，MySQL 和 ES 这种冷启动慢的必须加，不然健康检查一开始就狂记失败。

Kafka 的 listener 我折腾过两回：第一版只配了一个 `PLAINTEXT://localhost:9094`，宿主机 IDE 里跑没问题，可一但把应用塞进 compose，它拿 `kafka:9092` 连上去，broker 回报的却是 `localhost:9094`，应用容器里的 `localhost` 是它自己，直接连不上。后来改成双 listener：`INTERNAL://kafka:9092` 给 compose 内部用，`HOST://localhost:${KAFKA_PORT}`（宿主 9094 映射到容器 29092）给宿主机用，再用 `KAFKA_INTER_BROKER_LISTENER_NAME: INTERNAL` 指定内部通信走哪个。这个 advertised listener 的坑，几乎每个第一次把 Kafka 塞进 compose 的人都要踩。

## ES 吃内存那回

第一版没写 `mem_limit`，也没设 `ES_JAVA_OPTS`，`docker stats` 一看 ES 容器吃到 4.2G，宿主机 16G 被它一个占掉四分之一，IDEA 直接被系统 OOM killer 带走，一下午的断点全没了（真的会骂人）。后来把堆固定成 `-Xms512m -Xmx512m`，再给容器 `mem_limit: 2g` 双保险——JVM 堆只是其中一块，Lucene 的 off-heap、segment cache 还要吃，光锁堆不够。改前 4.2G、改后稳定在 1.6G 上下。`xpack.security.enabled=false` 是本地图省事不配密码，别往任何能连外网的环境抄。

healthcheck 用 `_cluster/health` 而不是 `_cat/health`，前者返回 JSON 好判，`-fs` 让 curl 非 2xx 直接失败。`status` 是 yellow 也算过（单节点没副本，本来就 yellow），只要接口通就放行。

`retries` 和 `start_period` 我调过好几轮。一开始 `retries: 5`、`interval: 5s`，MySQL 冷启动 40 多秒，第五次失败 Compose 直接判 unhealthy 把后面全卡住；改成 `retries: 20` 加 `start_period: 30s` 才稳。`start_period` 的意思是这段时间里健康检查失败不计入重试，专门给首次初始化留的，冷启动慢的 MySQL 和 ES 不加基本必挂。顺带说个数字：加它之前 `docker compose up -d` 十次里有四次卡在 mysql 的 healthcheck，加完连着起二十次没再红过。

（顺带一提，`.env` 我加进 `.gitignore` 了，`dev_only_123456` 这种明文只在本地躺着；compose 里 `${MYSQL_PORT}` 是 Compose 自己做变量插值，别跟容器内的环境变量搞混。改完端口我习惯先跑一遍 `docker compose config` 看渲染结果，确认 `9094:29092` 没替换错再 `up`，比起来之后再查省事。）

## .env 和一键重置

```bash
# .env —— 宿主端口全部错开本机已装的服务
MYSQL_PORT=3307
MYSQL_ROOT_PASSWORD=dev_only_123456
MYSQL_DATABASE=devdb
REDIS_PORT=6380
KAFKA_PORT=9094
ES_PORT=9201
```

```bash
#!/usr/bin/env bash
# reset.sh —— 数据不要了就跑它，容器和卷一起清
set -euo pipefail
cd "$(dirname "$0")"

docker compose down -v
docker compose up -d --wait
docker compose ps
```

`--wait` 是 Compose V2 才有的（我这边 `Docker Compose version v2.27.0`），它会一直等到所有带 healthcheck 的服务 healthy 才返回，比我自己写 `sleep 30` 靠谱得多。改前我那个脚本是 `up -d` 后面硬塞 `sleep 30`，MySQL 冷启动偶尔超过 30 秒，照样翻车；换成 `--wait` 之后一次没失手。整套从 `down -v` 到 `ps` 出来，计时 90 秒左右，之前手动一个个装是半天。

> 顺带一提，`down -v` 删的是**命名卷**，我那三个 volume 都在 compose 文件里声明着，删得掉；要是你图省事用了 bind mount 到 `./data`，这条命令可不会帮你删，得自己 `rm -rf`。别问我怎么知道的。

## 还没解决的

`app` 这个服务是我偶尔图省事才塞进 compose 的，平时还是宿主机 IDE 直连，两套 bootstrap 地址（`kafka:9092` 和 `localhost:9094`）得靠人记着别写错，挺烦。还有 `mem_limit` 在非 swarm 下生效，组里有人用 rootless Docker 时行为还不太一样，没验过。下次想把这几个做成 `profiles`，默认只起 MySQL + Redis，ES 和 Kafka 按需拉起来，省得每次开机白等那 40 秒。
