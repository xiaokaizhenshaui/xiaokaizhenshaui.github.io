---
title: "换框架只用了一周，换边界拖了三个月"
date: 2026-11-14
categories:
  - 架构思考
tags:
  - 架构思考
  - 模块边界
  - 依赖方向
lead: "common 包我前后删了三次，每次都觉得这回总该能干净了吧。"
---

我把 `common` 包整个删掉的那天，里面还躺着 `StringUtil`、`DateUtil`、一个没人记得谁加进来的 `PageWrapper`，外加一个 `OrderStatusEnum`。顶离谱的就是它——订单状态枚举，塞在一个号称"通用"的包里，理由是 catalog 展示书籍时要判断"这本书还能不能下单"。我当时没拦，想着一个枚举而已，import 一下能出什么事。半年后报应来了，一次本地启动直接起不来。

在线书店刚搭的时候，目录是按技术分层铺平的：`controller`、`service`、`repository`、`dto`、`common`，五个包平铺在 `com.youngcerulean.bookstore` 底下。写起来是真快。要加一个"按 ISBN 查可售库存"的接口，`InventoryController` 直接注入 `CatalogService` 就能读定价；`BillingService` 想算运费，顺手把 `OrderRepository` 拉进来查收货地址。谁都能 import 谁，编译期一点脾气都没有。我那会儿还挺得意，觉得找文件方便，改东西不用跨目录跳。

`common` 就是这么长成垃圾桶的。凡是"不知道该放哪"的，第一反应都往里扔：先是工具类，后来是枚举，再后来连 `RedisKeyBuilder` 和半个 GraphQL `DataFetcher` 基类都进去了。到它被二十多个类 import 的时候，谁都不敢删里面任何一行，不知道动了会炸到哪。我删过两回，每回都留几个"暂时还有人用"的类，删完过两周又长回来。

## 一次启动失败，把这事逼到台面上

真让我下决心重排目录的，是那次起不来的本地环境。控制台甩出来的是 `BeanCurrentlyInCreationException: Error creating bean with name 'orderService': Requested bean is currently in creation`。顺着堆栈捋，链条挺清楚：`OrderService` 为了下单时预占发票号，注入了 billing 那边的 `InvoiceNoGenerator`；而 `ReconcileJob` 这个对账定时任务为了读订单明细，反手把 `OrderRepository` 注了进来。两个模块互相拽着对方的 bean，Spring 构造注入时绕成了环。我盯着那行堆栈看了好一会儿，越看越觉得冤——代码没写错什么，是当初那个谁都能 import 谁的平铺结构，把互相拽变成了顺手的事。

其实那次我第一反应是想绕过去。给 `ReconcileJob` 的 `OrderRepository` 加了 `@Lazy`，延迟注入，启动果然就过了，CI 也绿了，我还挺得意，觉得省了大事。过两天回头看那段代码才回过味来：`@Lazy` 只是把成环从启动期挪到了运行期，`OrderService` 和 `ReconcileJob` 照样你中有我，谁也没少依赖谁。那个注解留了不到一礼拜就删了，连着重排目录一起。

修那次只要十几行，把发票号生成挪到下单之后异步发事件就完了。可我心里清楚，只要包还是平的，下个月还会有另一对模块绕成另一个环。换框架治不了这个。那年我们把 Spring Boot 从 2.7 升到 3.2.5、JDK 上到 21，graphql-java 跟着升，前后也就一周，resolver 一行没动。框架说到底是别人替你维护的，升个版本就完事。边界不一样，它自己不会变好，你每天在上面走，踩错了就天天还。

## 我把目录重排成四块，顺手画了条单向线

重排按业务能力切，不按技术层。catalog 管书和价格。ordering 是订单从创建到履约那一整套生命周期。库存和预占归 inventory，billing 那边最杂，发票、支付、还有每月那摊对账都堆在一块。每块内部再分 `api` / `domain` / `infra`：`api` 放对外接口和 GraphQL resolver，`domain` 放不碰任何框架的逻辑，`infra` 放 PostgreSQL、Redis、Kafka 这些具体适配器。另有 `platform` 放 ID 生成和事件总线，谁都能用，它谁都不依赖。

```bash
$ tree -d src/main/java/com/youngcerulean/bookstore
src/main/java/com/youngcerulean/bookstore
├── catalog
│   ├── api
│   ├── domain
│   └── infra
├── ordering
│   ├── api
│   ├── domain
│   └── infra
├── inventory
│   ├── api
│   ├── domain
│   └── infra
├── billing
│   ├── api
│   ├── domain
│   └── infra
└── platform
    ├── event
    └── id
```

方向我写在 README 里，拢共三条。依赖一律朝 catalog 那边走：ordering、inventory、billing 都能依赖 catalog，billing 还能再依赖 ordering，反着来一律不行。同级模块之间不许直接 import 对方的 `domain` 或 `infra`，要说话就走 `api` 下的接口，或者往 `platform.event` 丢事件。还有 `infra` 里的类，不许被别的块的 `infra` 直接引用——这条是后来补的，有次 `BillingRepository` 直接查了 `ordering` 的 `orders` 表，绕开所有接口，被我在评审里逮了回来。

跨模块那部分我留得最松。`ordering` 下单成功后往 `platform.event` 丢一个 `OrderPlaced`，payload 里只放 `orderId`、`userId`、下单时间和一个 `items` 摘要，价格不往里塞，让 billing 自己拿 `orderId` 回查 `PriceSnapshot`。当时有人提议把金额直接塞进事件省一次查询，我没同意：金额这东西一旦进了事件契约，改字段就得跟所有消费方打招呼，宁可多一次查。

## 规矩得有人盯着，不然三个月就烂回去

只写文档靠不住。第一版我就把这三条贴在 README，两周后 `inventory.infra` 里冒出个 import `billing.domain` 的类，写的人还挺无辜，说"就想复用一下计费规则"。于是加了 ArchUnit 测试，把方向钉进 CI：

```java
package com.youngcerulean.bookstore.architecture;

import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ClassFileImporter;
import com.tngtech.archunit.lang.ArchRule;
import org.junit.jupiter.api.Test;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.classes;
import static com.tngtech.archunit.library.dependencies.SlicesRuleDefinition.slices;

class ModuleBoundaryTest {

    private static final JavaClasses imported =
            new ClassFileImporter().importPackages("com.youngcerulean.bookstore");

    @Test
    void modulesShouldBeFreeOfCycles() {
        ArchRule rule = slices()
                .matching("com.youngcerulean.bookstore.(*).(*)..")
                .should().beFreeOfCycles();
        rule.check(imported);
    }

    @Test
    void catalogShouldNotDependOnOrdering() {
        ArchRule rule = classes()
                .that().resideInAPackage("..catalog..")
                .should().onlyDependOnClassesThat()
                .resideOutsideOfPackage("..ordering..");
        rule.check(imported);
    }
}
```

`modulesShouldBeFreeOfCycles` 抓的就是那次起不来那类成环，`catalogShouldNotDependOnOrdering` 把"catalog 不许反过来依赖上层"写成了断言。现在谁加一行反向 import，构建就红，红在测试名上，不用我再去评审里一行行翻。这条测试自打加上，没关过。

## 判断边界好不好，我只看一个数

后来我不拿"高内聚低耦合"糊弄自己了，换了个笨办法：接一个需求，数要动几个模块。上半年做"书籍改价时，已下单未支付的订单按原价结算"，听着只关定价，落地动了三处。`catalog` 那边发了个 `BookPriceChanged` 事件，`ordering` 收到后在 `PriceSnapshot` 里把价锁住，最麻烦的是 `billing`，对账那段得改成读快照，不再读实时价。三个模块听着不少，可每个只动 `domain` 一层，`infra` 没碰，`api` 没动，我心里就踏实，改动被边界收住了。反过来，要是同一个需求得钻进四个模块的 `infra` 改 SQL，那八成是切错了，跟用不用 Spring Boot 没关系。

对照着看更清楚。上礼拜给 `catalog` 加"按 ISBN 批量查"，能不能展示、上下架时间怎么过滤，全在 catalog 自己的 `domain` 和 `infra` 里，一个模块、四五个文件，别的一行没动。我记这个数，图的是改之前能估出活儿要铺多大：动一个模块，心里有底；动到三个、还都钻进 `infra` 改 SQL，就得先停下来想想是不是哪条线画歪了。这法子笨，可比重读一遍"高内聚"管用。

有一处我到现在也没想明白：`billing` 每月跟 `ordering` 对的预收账，那笔"钱收了、订单还没履约"的余额，挂谁头上都别扭。算 billing 的负债吧，履约状态在 ordering；算 ordering 的字段吧，它又得进发票。`ReconcileJob` 里留了条 TODO，写着"预收归属待定"，先按 billing 口径跑着。哪天真想通了，大概又得动一次目录。
