---
title: "让 AI 补单测，覆盖率涨了 12 个点，两个测试是假的"
date: 2026-07-18
categories:
  - AI 工具
tags:
  - AI 工具
  - 单元测试
  - 覆盖率
lead: "行覆盖率 41.3% → 53.1%，看着挺美；点开 JaCoCo 才发现两个测试一个 assert 恒真、一个把被测逻辑全 mock 掉了。"
---

7 月 16 号下午四点多，`mvn -q test jacoco:report` 跑完，我点开 `target/site/jacoco/index.html`，订单服务 `order-service` 那一行从红变黄：行覆盖率 `41.3% → 53.1%`，分支覆盖率 `27.8% → 33.4%`。前一天我把 `OrderService` 和它依赖的三个类整个丢给编码工具，让它「照着现有测试风格补单测」，一口气补了 48 个，全绿，测试总数从 62 涨到 110。我截了图发到组里，还顺手写了句「终于过 50 了」。

7 月 17 号早上对着报告一个个类点过去，发现有两个测试压根没测到任何东西。删掉之后覆盖率只从 53.1% 掉到 52.9%——0.2 个点，说明它们本来也没碰到任何新分支，纯粹把测试数量虚报了 2 个。截图那会儿还挺得意的，现在有点想删聊天记录。

## 起因：为什么想到补单测

订单服务是这套在线书店 API 里最老的一块，Spring Boot 3.2.5 + JDK 21.0.4，JUnit 5.10.2 + Mockito 5.11.0。62 个测试大多是 2019 到 2022 年堆的，覆盖的全是「正常下单成功」这条主路径：金额算对、库存够、优惠券能叠。`placeOrder` 里真正容易出事的边界——空订单项、金额为 0、数量溢出、库存扣减失败回滚、重复提交——一条没有。

（顺带一提，分支覆盖率 27.8% 比行覆盖率 41.3% 低这么多，就是因为这些 `if` 的另一半从来没人跑过。这个数字当时没细想，现在看是明摆着的信号。）

我给工具的指令特别省事：「参考 `src/test/java` 现有写法，给 `OrderService` 补单测，覆盖边界条件，跑通 `mvn test` 就行」。没给任何业务规则，也没说哪些写法不许用。它照做了，跑通了，`BUILD SUCCESS`，48 个测试全绿。问题就出在「跑通」这两个字上——全绿和测到了是两回事。

## 两个假测试

把两段挪进同一个类里方便看，import 是完整的：

```java
package com.youngcerulean.bookstore.order;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class OrderServiceFakeTest {

    // 假测试一：恒真断言
    @Test
    void testCalculateTotal_shouldNotThrow() {
        OrderService service = new OrderService(
                new PriceCalculator(), new FakeInventoryClient(true),
                new InMemoryOrderRepository());
        OrderDto dto = service.calculateTotal(
                new OrderRequest("SKU-1024", 2, new BigDecimal("88.00")));

        assertNotNull(dto);                            // 方法第一行就 new，永远不为 null
        assertEquals(dto.getTotal(), dto.getTotal());  // 自己跟自己比
    }

    // 假测试二：mock 铺满，什么都没验
    @Test
    void testPlaceOrder_success() {
        PriceCalculator priceCalculator = mock(PriceCalculator.class);
        InventoryClient inventoryClient = mock(InventoryClient.class);
        OrderRepository orderRepository = mock(OrderRepository.class);
        when(priceCalculator.quote(any())).thenReturn(new BigDecimal("88.00"));
        when(inventoryClient.deduct(anyString(), anyInt())).thenReturn(true);
        when(orderRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));
        OrderService service = new OrderService(
                priceCalculator, inventoryClient, orderRepository);

        OrderResult result = service.placeOrder(
                new OrderRequest("SKU-1024", 2, new BigDecimal("88.00")));

        assertNotNull(result);                  // 同样是恒真
        verify(orderRepository).save(any());    // 只证明「save 被调过」
    }
}
```

`assertEquals(dto.getTotal(), dto.getTotal())` 我看了两遍才确认没看错。就算 `calculateTotal` 把金额算成 `null`，只要 `dto` 不为 null，这条照样绿。第二个更要命：三个依赖全 mock 掉，`quote` 返回写死的 88.00，`deduct` 恒返回 true。断言的是「结果对象不为空」和「save 调过一次」，而真正该验的——`total` 是不是 `88.00 × 2 - 优惠`、库存不足时会不会抛异常、订单状态有没有从 `PENDING` 变成 `PAID`——一个字没提。我把 `placeOrder` 里的金额计算整段注释掉试了一下，这个测试依然绿。

## JaCoCo 报告是怎么看的

本地和 CI 用的是同一套命令：`mvn -q clean test jacoco:report`，看 `target/site/jacoco/index.html`，机器读的是 `target/site/jacoco/jacoco.xml`。

我以前只看首页那个总百分比，这次是点进 `com.youngcerulean.bookstore.order` → `OrderService` → 源码视图，一行行对着看。源码视图里绿色是覆盖、红色是没覆盖、黄色菱形是分支只走了一半；`jacoco.xml` 里 `<counter type="BRANCH" missed="..." covered="..."/>` 是给脚本读的那份。48 个新测试点进去，一大半堆在 getter 和 `toString` 上，把行覆盖率数字撑起来了，`placeOrder` 里那几个黄色菱形一个没变。

把几个阶段的数放一起，才明白那 12 个点是怎么来的：

| 阶段 | 测试数 | 行覆盖率 | 分支覆盖率 |
| --- | --- | --- | --- |
| 补之前 | 62 | 41.3% | 27.8% |
| 工具第一版补完 | 110 | 53.1% | 33.4% |
| 删掉两个假测试 | 108 | 52.9% | 33.4% |
| 按上下文重做后 | 116 | 57.6% | 40.1% |

行覆盖涨得多、分支几乎不动，典型的「只跑到主路径」。光看第二行会以为大功告成。

## 把「不许干什么」写进项目上下文

第二版我没让它直接写测试，先在项目根目录的 `AGENTS.md`（几个编码工具都会读这个文件）里补了一段订单服务的约束，大意是：

> `OrderService` 的测试必须覆盖：空订单项、金额 `<= 0`、数量 `> 99`、库存扣减返回 false、同一 `requestId` 重复提交、优惠券与满减叠加。禁止 `assertTrue(true)`、`assertEquals(x, x)` 一类的恒真断言；禁止用 `assertNotNull(result)` 作为唯一断言；`@Mock` 不得多于 2 个，`PriceCalculator` 用真实实现；金额断言必须写死期望值，不许拿被测对象的返回值自己比自己；库存失败分支必须 `assertThrows`。

前面几条是边界清单，后面几条全是被那两个假测试逼出来的。写完再让它重做，48 个里留下 22 个能看的，另外补了 30 个带具体期望值的用例，有效边界用例从 6 个涨到 27 个。覆盖率 52.9% → 57.6%，分支 33.4% → 40.1%——这次分支涨得比行多，说明真碰到 `if` 的另一半了。

（顺带一提，「`@Mock` 不得多于 2 个」不是什么普适规则，纯粹是给这个服务定的。换成别的服务我可能就得放宽，写进全局上下文之前犹豫了一下，最后还是加了注释限定范围。）

## 改完的真测试

留一个最有代表性的，参数化加异常分支：

```java
package com.youngcerulean.bookstore.order;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;

class OrderServiceBoundaryTest {

    private final InMemoryOrderRepository orderRepository = new InMemoryOrderRepository();
    private final OrderService orderService = new OrderService(
            new PriceCalculator(), new FakeInventoryClient(true), orderRepository);

    @ParameterizedTest(name = "数量={0} 单价={1} 期望总额={2}")
    @CsvSource({
            "1, 88.00,  88.00",
            "2, 88.00, 176.00",
            "3, 35.50, 106.50"
    })
    @DisplayName("总额必须是单价乘数量，写死期望值")
    void totalShouldBeUnitPriceTimesQuantity(int qty, String unit, String expected) {
        OrderRequest req = new OrderRequest("SKU-1024", qty, new BigDecimal(unit));
        assertEquals(new BigDecimal(expected),
                orderService.calculateTotal(req).getTotal());
    }

    @Test
    @DisplayName("库存扣减失败必须抛异常，且订单不落库")
    void shouldRejectWhenInventoryFails() {
        OrderService failing = new OrderService(
                new PriceCalculator(), new FakeInventoryClient(false), orderRepository);

        assertThrows(InsufficientStockException.class,
                () -> failing.placeOrder(
                        new OrderRequest("SKU-1024", 1, new BigDecimal("88.00"))));
        assertEquals(0, orderRepository.count());
    }
}
```

期望值是写死的 `176.00`，不是从 `result` 里再取一遍；库存失败那条同时验了异常和「没落库」这个副作用。依赖用手写 fake，连 Mockito 都不用了——规则里限了 mock 数量，索性省到底。这几个 fake 放在 `src/test/java/.../support/` 下，一共不到 80 行。

## CI 上把阈值卡死

光靠人眼盯报告不现实。我在 `pom.xml` 里让 `verify` 阶段直接 `check`，顺手把 pitest 也配上，依赖坐标一并贴全：

```xml
<dependencies>
  <dependency>
    <groupId>org.junit.jupiter</groupId>
    <artifactId>junit-jupiter</artifactId>
    <version>5.10.2</version>
    <scope>test</scope>
  </dependency>
  <dependency>
    <groupId>org.mockito</groupId>
    <artifactId>mockito-core</artifactId>
    <version>5.11.0</version>
    <scope>test</scope>
  </dependency>
</dependencies>

<build>
  <plugins>
    <plugin>
      <groupId>org.jacoco</groupId>
      <artifactId>jacoco-maven-plugin</artifactId>
      <version>0.8.12</version>
      <executions>
        <execution>
          <id>prepare-agent</id>
          <goals><goal>prepare-agent</goal></goals>
        </execution>
        <execution>
          <id>report</id>
          <phase>test</phase>
          <goals><goal>report</goal></goals>
        </execution>
        <execution>
          <id>check-coverage</id>
          <phase>verify</phase>
          <goals><goal>check</goal></goals>
          <configuration>
            <rules>
              <rule>
                <element>BUNDLE</element>
                <limits>
                  <limit>
                    <counter>LINE</counter>
                    <value>COVEREDRATIO</value>
                    <minimum>0.55</minimum>
                  </limit>
                  <limit>
                    <counter>BRANCH</counter>
                    <value>COVEREDRATIO</value>
                    <minimum>0.38</minimum>
                  </limit>
                </limits>
              </rule>
            </rules>
          </configuration>
        </execution>
      </executions>
    </plugin>
    <plugin>
      <groupId>org.pitest</groupId>
      <artifactId>pitest-maven</artifactId>
      <version>1.15.0</version>
      <configuration>
        <targetClasses>
          <param>com.youngcerulean.bookstore.order.*</param>
        </targetClasses>
        <targetTests>
          <param>com.youngcerulean.bookstore.order.*</param>
        </targetTests>
        <mutationThreshold>60</mutationThreshold>
      </configuration>
      <dependencies>
        <dependency>
          <groupId>org.pitest</groupId>
          <artifactId>pitest-junit5-plugin</artifactId>
          <version>1.2.1</version>
        </dependency>
      </dependencies>
    </plugin>
  </plugins>
</build>
```

阈值定的行 55%、分支 38%，刚好卡在重做后的 57.6% / 40.1% 下面一点，留点余量。GitHub Actions 里就一句 `mvn -B -ntp verify`，失败了连报告一起传上来：

```yaml
name: verify
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '21'
          cache: maven
      - name: 覆盖率与阈值检查
        run: mvn -B -ntp verify
      - name: 变异测试抽查
        run: mvn -B -ntp org.pitest:pitest-maven:mutationCoverage
      - name: 上传报告
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: |
            target/site/jacoco/
            target/pit-reports/
```

PIT 那把是抽查，不是全量常驻：对 `order` 包跑一次 6 分 40 秒，第一版 214 个 mutant 只 kill 掉 73 个（34.1%），重做之后 61.3%，刚过我配的 60。这个数字比覆盖率诚实多了——把 `total` 里的 `multiply` 改成 `add`，第一版那 110 个测试一个都不会红。

## 还没解决的

`check` 卡的是 `BUNDLE` 全局，新增一个类写 0 覆盖测试也能混过去，只要别把整体拉下来。想按 PR 改动的文件卡 diff 覆盖率，JaCoCo 原生不给这个，得在 CI 里自己比 `jacoco.xml` 和 `git diff` 的文件列表，还没动手。另外 GraphQL 那层 resolver 的测试还是一片红，让工具补到一半我喊停了——DataLoader 那套依赖太绕，第一版又是满屏 `@Mock`，等把上下文补完再说。
