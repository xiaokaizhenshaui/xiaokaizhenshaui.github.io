---
title: "Docker 学习笔记"
date: 2021-01-11
updated: 2026-11-10
categories:
  - 中间件
tags:
  - "Docker"
  - "容器"
lead: "2021 年从 yum 装 Docker 开始记的笔记，命令留着没动，配图重画了。"
---
> 这篇写于 2021 年。原站配图用的免费图床后来全挂了，这次改版把失效截图换成了本地 SVG 示意图，正文和命令保持原样，现在该怎么做放在文末「2026 补记」里。

## Docker简易学习

## Docker初始学习

![Docker 组件关系（2026 重绘）](/images/diagrams/docker-architecture.svg)

#### Docker的应用场景

- web应用的自动化打包和发布
- 自动化测试集成和发布
- 部署服务型环境后台应用

#### Docker的优点

> docker是一个用于开发，交付和运行应用程序的开放平台。
>
> 可以构建出虚拟环境，大大减少编写代码和在生产环境中运行代码之间的延迟。

1. 快速交付应用
2. 响应式部署和扩展
3. 统一硬件上运行更多的工作负载

## Docker架构

#### 基本概念

> - 镜像：相当于一个root文件系统
> - 容器：镜像（Image）和容器（Container）的关系，就像是面向对象程序设计中的类和实例一样，镜像是静态的定义，容器是镜像运行时的实体。容器可以被创建、启动、停止、删除、暂停等。
> - 仓库：代码控制中心，用来保存镜像

## Docker安装🔧

#### CentOS Docker（CentOS7以上64位版本）

- 官方脚本

```bash
curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun
```

  国内统一源daocloud

```bash
curl -sSL https://get.daocloud.io/docker | sh
```

- 手动安装

  - 先卸载旧版本

```bash
$ sudo yum remove docker \
                  docker-client \
                  docker-client-latest \
                  docker-common \
                  docker-latest \
                  docker-latest-logrotate \
                  docker-logrotate \
                  docker-engine
```

  - 安装Docker仓库

    - 设置仓库

```bash
$ sudo yum install -y yum-utils \
  device-mapper-persistent-data \
  lvm2
```

    - 设置源地址

```bash
$ sudo yum-config-manager \
    --add-repo \
    http://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo
```

  - 安装Docker Engine-Community

```bash
$ sudo yum install docker-ce docker-ce-cli containerd.io
```

- 启动Docker

```bash
$ sudo systemctl start docker
```

- 测试运行

```bash
$ sudo docker run hello-world
```

#### Windows Docker（Not Suggest）

- Docker依赖于已经存在并运行的Linux内核环境
- Docker Desktop是win10和MacOS上官方安装方式

- 开启Hyper-V

  > Hyper-V 是微软开发的虚拟机，类似于 VMWare 或 VirtualBox，仅适用于 Windows 10。这是 Docker Desktop for Windows 所使用的虚拟机。
  >
  > 但是，这个虚拟机一旦启用，QEMU、VirtualBox 或 VMWare Workstation 15 及以下版本将无法使用！如果你必须在电脑上使用其他虚拟机（例如开发 Android 应用必须使用的模拟器），请不要使用 Hyper-V！

  在“应用于功能”中选择hyper-V

  或者在超管的CMD中执行

```cmd
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
```

  安装[Docker Desktop](https://hub.docker.com/?overlay=onboarding)
- 检测是否成功

```cmd
docker run hello-world
```

#### MacOS🍎

- 使用HomeBrew安装

```bash
$ brew install --cask --appdir=/Applications docker
```

- 手动下载

  [Edge版本](https://download.docker.com/mac/edge/Docker.dmg)和[Stable版本](https://download.docker.com/mac/stable/Docker.dmg)的Docker for Mac
- 启动终端后，通过命令检查Docker版本
- 镜像加速

#### Docker镜像加速🚀

- 网易：**<https://hub-mirror.c.163.com/>**
- 阿里云：**https://<你的ID>.mirror.aliyuncs.com**
- 七牛云加速器：**[https://reg-mirror.qiniu.com](https://reg-mirror.qiniu.com/)**
- 查看加速器是否生效

```cmd
docker info
```

#### Docker版本

```bash
docker version
```

## Docker的使用

#### Docker Hello World

```bash
docker run ubuntu:15.10 /bin/echo "Hello world"
```

> 参数解析:
>
> > - **docker:** Docker 的二进制执行文件。
> > - **run:** 与前面的 docker 组合来运行一个容器。
> > - **ubuntu:15.10** 指定要运行的镜像，Docker 首先从本地主机上查找镜像是否存在，如果不存在，Docker 就会从镜像仓库 Docker Hub 下载公共镜像。
> > - **/bin/echo “Hello world”:** 在启动的容器里执行的命令
>
> 解释为：Docker 以ubuntu15.10镜像创建一个新的容器，然后再容器里执行bin/echo “Hello world”，然后输出结果。

- 交互式运行

```bash
docker run -i -t ubuntu:15.10 /bin/bash
```

  > 参数解析：
  >
  > > - **-t:** 在新容器内指定一个伪终端或终端。
  > > - **-i:** 允许你对容器内的标准输入 (STDIN) 进行交互。
  >
  > 随后会进入容器内部，实现操作容器
  >
  > 可使用exit或者ctrl+D来退出
- 启动容器

```bash
docker run -d ubuntu:15.10 /bin/sh -c "while true; do echo hello world; sleep 1; done"
```

  启动一个容器，会返回一个容器ID

  用 **docker ps **来查看运行容器
- 停止容器

  使用**docker stop** id来停止容器

#### Docker的使用

- 获取容器

  > 如果我们本地没有 ubuntu 镜像，我们可以使用 docker pull 命令来载入 ubuntu 镜像
  >
  > 

```bash
docker pull ubuntu
```

- 启动容器

  使用ubuntu镜像启动一个容器，参数为一命令行模式进入该容器

```bash
docker run -it ubuntu /bin/bash
```

  > 参数说明：
  >
  > > - **-i**: 交互式操作。
  > > - **-t**: 终端。
  > > - **ubuntu**: ubuntu 镜像。
  > > - **/bin/bash**：放在镜像名后的是命令，这里我们希望有个交互式 Shell，因此用的是 /bin/bash。

  使用**docker start id**来启动一个已经停止的容器。
- 后台进入和后台退出

  指定容器运行模式 **-d** 且默认不会进入后台

```bash
docker run -itd --name ubuntu-test ubuntu /bin/bash
```

  进入 后台容器 中，退出容器不会导致容器停止

```bash
docker exec -it id /bin/bash
```

- 删除容器

```bash
docker rm -f id
```

  处理所有处于终止的容器

```bash
docker container prune
```

#### Docker镜像的使用

- 管理和使用本地Docker主机镜像

  - 展示镜像

```bash
docker images
```

  - 获取一个新的镜像

```bash
docker pull ubuntu:15.10
```

  - 拖取镜像

```bash
docker pull httpd
```

    拖取完就可以使用

```bash
docker run httpd
```

  - 删除镜像

    使用 **docker rmi** 命令进行删除

```bash
docker rmi hello-world
```

- 创建镜像

  - 构建镜像

    使用 **docker build** 来创建一个新的镜像

    1. 创建一个Dockerfile文件
    2. 使用 ** docker build -t images-name .

       > - **-t** ：指定要创建的目标镜像名
       > - **.** ：Dockerfile 文件所在目录，可以指定Dockerfile 的绝对路径

#### Docker Dockerfile

> Dockerfile 是一个用来构建镜像的文本文件，文本内容包含了一条条构建镜像所需的指令和说明。

#### Docker Compose

> Compose 是用于定义和运行多容器 Docker 应用程序的工具。通过 Compose，您可以使用 YML 文件来配置应用程序需要的所有服务。然后，使用一个命令，就可以从 YML 文件配置中创建并启动所有服务。
>
> > Compose 使用的三个步骤：
> >
> > - 使用 Dockerfile 定义应用程序的环境。
> > - 使用 docker-compose.yml 定义构成应用程序的服务，这样它们可以在隔离环境中一起运行。
> > - 最后，执行 docker-compose up 命令来启动并运行整个应用程序。

#### 守护式容器🛡

- 启动：

```bash
docker run -d container_id
```

## 暂时结尾😊

[docker 指令快速查询](https://www.cnblogs.com/H4ck3R-XiX/p/12227485.html) 👈

[docker中文网](https://www.docker.org.cn/)👈

[docker的简易框架，链接在此👇](https://blog.csdn.net/blissnmx/article/details/102922847)

（后续待更新）

## 2026 补记：现在怎么装

上面那些 `yum-config-manager` 步骤我 2023 年之后就没再用过。本地起中间件一律走 Compose，一条命令完事，也不污染宿主机：

```yaml
# compose.yaml
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: devonly
    ports: ["5432:5432"]
```

```bash
docker compose up -d
docker compose logs -f redis
```

两个当年没写清楚、后来被坑过的点：

- `ports` 和 `expose` 不是一回事：前者是宿主机端口映射，后者只在容器网络内可见。
- 容器里默认 UTC，日志对不上业务时间时别急着改代码，先挂 `/etc/localtime` 或者设 `TZ`。
