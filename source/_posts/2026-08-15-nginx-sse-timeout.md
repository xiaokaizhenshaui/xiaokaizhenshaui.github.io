---
title: "SSE 连 60 秒就断，锅在 Nginx 不在前端"
date: 2026-08-15
categories:
  - 中间件
tags:
  - Nginx
  - SSE
  - 长连接
lead: "EventSource 每 60 秒重连一次，前端背了两天锅，最后发现是 Nginx 的 proxy_read_timeout 默认 60s 加 proxy_buffering 在作妖，改两行再补个 15s 心跳就好了。"
---

8 月 12 号下午 14:26，运营在群里甩了张截图：进度条走到一半自己跳回 0，控制台里 `EventSource` 的 error 一秒一条，整整齐齐每 60 秒一次。我第一反应是前端又没处理重连，把同事的代码拉下来翻了半小时，`onerror` 里老老实实啥也没干，就一句 `console.warn`，浏览器自动重连本来就是标准行为。怪的是后端日志里 `SseEmitter` 的 `onCompletion` 也跟着每 60 秒触发一次——不是浏览器单方面断，是整条连接被中间谁掐了。前面挡着的是 Nginx `1.24.0`，Ubuntu 22.04 上 apt 装的，配置基本没动过。

> 控制台刷的是：`EventSource's response has a state that is 200 (OK) with Content-Type text/event-stream, but the connection was closed`。readyState 变 0，隔两秒又自动连上。（顺带一提，Chrome 这个自动重连间隔写死在 2~3 秒，你改不动，别折腾。）

## 先绕的两圈弯路

第一版我怀疑是 Spring 那边的超时。`new SseEmitter()` 我确实没传超时参数，可 `spring.mvc.async.request-timeout` 和 Tomcat 的 `async-timeout` 到底哪个 30s 哪个 60s 我当场记不清了，于是先给 `application.yaml` 塞了一堆 `spring.mvc.async.request-timeout: -1`，重启，还是 60 秒断。白忙一场。

第二版更蠢：我翻出之前给 WebSocket 写的那段 location，想着长连接嘛差不多，直接 copy 过来，把 `map $http_upgrade $connection_upgrade`、`proxy_set_header Upgrade $http_upgrade`、`proxy_set_header Connection $connection_upgrade` 一套全贴上了。结果一点用没有。WebSocket 要的是 `101 Switching Protocols`，靠 `Upgrade` 握手换协议；SSE 压根不换协议，它就是一个普通的 `text/event-stream` 响应，靠 chunked 一直往外出 `data:`，没有 `Upgrade`、没有 101、也没有 `Sec-WebSocket-Key`。给一条本来就通的 HTTP 连接套个不存在的握手，Nginx 该 60 秒掐还是掐。

真正让我定位到问题的，是绕过 Nginx 直连后端：

```bash
# 直连 8080，看它到底能活多久
$ curl -N -H 'Accept: text/event-stream' http://127.0.0.1:8080/api/sse/stream
: ping 1786531560012

: ping 1786531575018

data: 第 1 条进度

: ping 1786531590023

data: 第 2 条进度
^C   # 我盯了 4 分多钟一直没断，最后手动掐的
```

`-N` 是 `--no-buffer`，不加的话 curl 会把响应攒着，看不到实时心跳。直连活了 4 分钟没断，走 `dev.local`（80 端口）每 60 秒准断一次，误差不超 1 秒——锅在中间那层，板上钉钉。

翻 `error.log` 才看到一串 `upstream timed out (110: Connection timed out) while reading upstream`，时间点跟每次断连严丝合缝，`while reading upstream` 几个字直接把 `proxy_read_timeout` 点出来了。早该先翻日志的，绕那两圈纯属手比脑快。另外走 80 端口时我拿 `curl -N` 特意数过，`data:` 行是攒了三四条一起蹦出来的，直连 8080 时却是一条一条实时出——这就是 `proxy_buffering on` 把 chunk 攒批的典型样子。两条证据搁一块，配置项基本就锁死了。

## 两个默认值的合谋

Nginx 反向代理有两个默认值跟 SSE 天生犯冲：

| 配置项 | 默认 | 对 SSE 的后果 |
| --- | --- | --- |
| `proxy_read_timeout` | `60s` | 两次上游响应之间超过 60s 没动静，直接断连接 |
| `proxy_buffering` | `on` | 把上游 chunked 数据攒进缓冲区，攒够了才发给浏览器，前端啥也收不到 |

我后端业务消息是「有更新才推」，安静的时候一分多钟不发东西，`proxy_read_timeout` 正好到点；`proxy_buffering on` 又让偶尔真有的 `data:` 行在缓冲区里排队，浏览器端看着就像彻底没数据。两个凑一起，60 秒断一次，准得能拿去当秒表。

## 改完的 location

```nginx
upstream app_upstream {
    server 127.0.0.1:8080;
    keepalive 32;                 # 普通短请求复用连接，SSE 那条本身会一直占着
}

server {
    listen 80;
    server_name dev.local;

    location /api/sse/ {
        proxy_pass http://app_upstream;
        proxy_http_version 1.1;
        proxy_set_header Connection "";       # 配合 upstream keepalive，别把 close 带给上游
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        proxy_buffering off;                 # 关键：每块 chunked 立刻吐给浏览器
        proxy_cache off;
        proxy_read_timeout 600s;             # 默认 60s → 10 分钟，留足余量
        proxy_send_timeout 600s;
    }

    location /api/ {
        proxy_pass http://app_upstream;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
    }
}
```

`keepalive 32` 那行是给 `/api/` 下那些普通接口用的，`proxy_http_version 1.1` 加 `proxy_set_header Connection ""` 是它生效的前提（否则默认 HTTP/1.0 加 `Connection: close`，连接池白搭）。SSE 这条连接一旦建起来就一直占着一个上游连接，跟连接池没关系，别搞混。还有个顺带一提：如果站点开了 gzip，`text/event-stream` 也可能被压缩缓冲住，稳妥起见加一句 `proxy_set_header Accept-Encoding "";` 把压缩请求头抹掉，我这次没踩到，但记一下免得下次又查半天。

更省事的兜底是让后端自己回一个 `X-Accel-Buffering: no` 响应头，Nginx 见到它就不缓冲该响应。注意它是**响应**头，不是 `proxy_set_header` 那种请求头——我一开始真写成 `proxy_set_header X-Accel-Buffering no` 了，那是发给上游的一个请求头，毛用没有，这坑我踩了小半天。共享 ingress、改不了 Nginx 配置的时候，这个响应头是救命的。

## 后端和心跳

```java
// Spring Boot 2.7.18，spring-webmvc 5.3.31；scheduler / executor 为注入的线程池
@GetMapping(value = "/api/sse/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
public SseEmitter stream(HttpServletResponse response) {
    // 改不了网关时，靠这个响应头让 Nginx 别缓冲
    response.setHeader("X-Accel-Buffering", "no");

    SseEmitter emitter = new SseEmitter();   // 不传超时，别让容器 30s 就把我掐了
    ScheduledFuture<?> beat = scheduler.scheduleAtFixedRate(() -> {
        try {
            // 冒号开头是 SSE 注释行，浏览器不触发 message，纯粹用来续命
            emitter.send(SseEmitter.event().comment("ping " + System.currentTimeMillis()));
        } catch (IOException | IllegalStateException e) {
            // 连接已经断了，取消动作放在下面的回调里
        }
    }, 0, 15, TimeUnit.SECONDS);

    emitter.onCompletion(() -> beat.cancel(true));
    emitter.onError(e -> beat.cancel(true));
    emitter.onTimeout(() -> beat.cancel(true));

    executor.submit(() -> {
        try {
            for (int i = 1; i <= 10; i++) {
                emitter.send(SseEmitter.event().name("tick").data("第 " + i + " 条进度"));
                Thread.sleep(5000);
            }
            emitter.complete();
        } catch (Exception e) {
            emitter.completeWithError(e);
        }
    });
    return emitter;
}
```

心跳设 15s，比 `proxy_read_timeout 600s` 小得多，等于每 15 秒就给 Nginx 报一次「我还活着」，那个 600s 其实根本触发不到，纯粹留个余量防抖。改之前 60 秒必断、一天 `onCompletion` 上千次；改之后我挂着跑了一整晚，重连 0 次。注释行用 `comment()` 而不是 `data()`，是因为注释不会进 `EventSource.onmessage`，免得前端把心跳当真数据刷到进度条上——第一版我拿 `data()` 发心跳，前端进度条莫名多出十几条 `ping`，被测试追着问了半天。

## 前端就几行

```javascript
const es = new EventSource('/api/sse/stream');

es.addEventListener('tick', (e) => {
  document.querySelector('#feed').textContent += e.data + '\n';
});
es.addEventListener('open', () => console.log('连上了'));
es.addEventListener('error', () => {
  // 浏览器会自动重连，这里只记日志，千万别手动 close()
  console.warn('连接断开，等浏览器自己重连，readyState=' + es.readyState);
});
```

真没啥可改的，前端从头到尾都是对的，这也是我最开始冤枉同事的原因。

（顺带一提，`EventSource` 只能发 GET、也没法带自定义 header，token 塞不进 Header 只能走 cookie 或 query 参数。我们这版图省事用了 cookie，跨域那次又单独配了一轮 `withCredentials` 和 `Access-Control-Allow-Credentials`，跟超时没关系，是另一摊事了，先按下不表。）

## 还没解决的

`proxy_set_header X-Accel-Buffering no` 那半天算白交学费了。另外现在心跳是固定 15s 全连接广播，真到几千条 SSE 连着的时候，这个 `ScheduledExecutorService` 的线程池得单独调，我还没压过；还有走公司那层 SLB 时它自己也有个 60s 空闲超时，`proxy_read_timeout` 改了它不改照样断——这个得找运维，下次再写。
