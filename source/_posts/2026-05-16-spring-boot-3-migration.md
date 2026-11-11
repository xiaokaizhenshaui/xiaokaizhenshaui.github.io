---
title: "Spring Boot 2.7 → 3.2，47 个测试挂了三天"
date: 2026-05-16
categories:
  - Java 开发
tags:
  - Spring Boot
  - Java
  - 升级
lead: "47 个测试红了三天，工夫大半耗在一个靠反射撬 JDK 内部字段的老依赖上。"
---

47 个测试，报的是同一句 `java.lang.NoClassDefFoundError: javax/servlet/Filter`，一个不落。那是 5 月 12 号周二下午 16:40，CI 上 `mvn test` 跑完，一片红。机器是 4C8G 的容器，JDK 21.0.4，原来跑 Spring Boot 2.7.18。我上午刚把 `pom.xml` 里的 parent 改成 3.2.5，心里想的是「不就换个版本号」，结果连编译都没过去。三天后这 47 个才全绿，回头看，真正跟 `javax` 相关的活只有半天。

## 第一版是倒着做的

我上手先动语法。全项目 `grep -rl 'javax\.' src/main/java` 数出 23 个文件，一条命令全替了：`grep -rl 'javax\.' src/main/java | xargs sed -i '' 's/javax\./jakarta./g'`。macOS 的 BSD `sed` 那个 `-i ''` 我每次都要忘一次，这次也没例外，先报了 `sed: -i may not be used with stdin`，补上空参数才跑通。换完 `mvn -q compile`，200 多行红字里全是同一句：

> [ERROR] package jakarta.servlet does not exist
> [ERROR] package jakarta.persistence does not exist
> [ERROR] package jakarta.validation does not exist

道理其实很简单：pom 还挂着 2.7 的依赖树，`jakarta.servlet-api` 压根没被拉进来，我把门牌全换成新名字，房子还是旧的。等于没升级，只把代码改成了编译不过的样子。`git checkout .` 回退，重来。

还有个题外话：那次 `sed` 误伤了 `application.properties` 里写死的 `javax.net.ssl.trustStore`，`javax.net.ssl.*` 是 JDK 自己的系统属性名，不属于 Jakarta EE，压根不该动，后来全局搜了一遍才捞出来。

## 先把依赖升上去

正确的顺序是反过来的：先让 pom 能编译、能启动，再改包名。我照着 `mvn dependency:tree` 扫了一遍 `javax` 时代的库，把明显活不到 Boot 3 的先换掉，然后才动版本。改完的 `pom.xml` 关键部分是这样：

```xml
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.5</version>
    <relativePath/>
</parent>

<properties>
    <!-- 编译目标留 17，容器里跑的是 JDK 21.0.4，两头都能落 -->
    <java.version>17</java.version>
</properties>

<dependencies>
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-security</artifactId>
    </dependency>
    <!-- 原来是 xstream 1.4.10，JDK 17 起强封装，反射 TreeMap 直接启动不了 -->
    <dependency>
        <groupId>com.thoughtworks.xstream</groupId>
        <artifactId>xstream</artifactId>
        <version>1.4.20</version>
    </dependency>
</dependencies>
```

`java.version` 我没跟着升到 21，留 17 是为了产出的 jar 还能丢回只装了 17 的那几台老机器上跑，不想为了一次升级把部署基线一起抬了。这个决定后面救了我一次，第六节会说。

先把 parent 换成 3.2.5，确认 `mvn -q compile` 只报包名错误、不报缺类，说明依赖树已经是对的，下一步才轮到语法。这一步我卡了大概一小时，主要耗在判断哪些老库该留、哪些该换，`javax.annotation-api` 那个依赖留着没动，让 recipe 后面自己处理。

## jakarta 替换，半天

没再手写 `sed`，改用 OpenRewrite 的官方 Boot 3.2 recipe，一条命令：

```bash
mvn -U org.openrewrite.maven:rewrite-maven-plugin:run \
  -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-spring:RELEASE \
  -Drewrite.activeRecipes=org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_2
```

输出里有这么几行，我贴在群里当进度汇报：

> [INFO] --- rewrite-maven-plugin:run (default-cli) @ order-service ---
> [INFO] Using active recipe(s) [org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_2]
> [INFO] Parsing Java source files...
> [WARNING] Changes have been made to 63 files
> [INFO]   org.openrewrite.java.ChangePackage: javax.validation -> jakarta.validation
> [INFO]   org.openrewrite.java.ChangePackage: javax.persistence -> jakarta.persistence
> [INFO] Please review and commit the results.

审 diff 花了两个多小时，比替换本身久。recipe 把 `javax.validation`、`javax.persistence`、`javax.servlet` 三套都处理了，还顺手把 `spring.factories` 里几个已失效的自动配置项挪进了 `AutoConfiguration.imports`。有 3 处它没敢动：`javax.annotation.Resource` 来自 `jakarta.annotation-api`，但项目里那个类还打着 `@PostConstruct`，我手动核了一遍确认没漏。真正踩到的是前面说的 `javax.net.ssl.*` 系统属性，recipe 不碰字符串常量，得自己看。

这里还有个小坑：`rewrite-spring:RELEASE` 会跟着 Maven Central 飘。周三我在本地跑和周四 CI 上跑，拉到的版本不一样，改出来的 `AutoConfiguration.imports` 差了两行。后面打算锁死版本，还没排上。

## Spring Security 6 的 lambda

`WebSecurityConfigurerAdapter` 在 Spring Security 6 里整个删掉了。第一版我照着 2.7 的写法改成继承它、用 `.and()` 串起来的链式调用，`mvn compile` 直接报：

> cannot find symbol: method antMatchers(java.lang.String...)

`antMatchers`、`authorizeRequests` 在 6.0 就移除了，换成 `requestMatchers`、`authorizeHttpRequests`，而且官方推荐 lambda DSL，不再靠 `.and()` 串。改成 Bean 形式：

```java
package com.example.order.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
public class SecurityConfig {

    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/actuator/health", "/login", "/css/**").permitAll()
                .requestMatchers("/admin/**").hasRole("ADMIN")
                .anyRequest().authenticated()
            )
            .formLogin(form -> form.loginPage("/login").permitAll())
            .csrf(csrf -> csrf.ignoringRequestMatchers("/api/pay/callback"));
        return http.build();
    }
}
```

`/api/pay/callback` 是支付回调，第三方不带 CSRF token，`ignoringRequestMatchers` 得留着。我第一版图省事写了 `csrf(AbstractHttpConfigurer::disable)`，把整个站点的 CSRF 关了，被组里同事 review 时打回来，改成了只放行这一个路径。这种地方编译能过、测试也绿，全靠人看。

## Hibernate 6 改了 SQL 别名，11 个快照全红

包名改完，`mvn test` 终于能跑起来了，红的东西也换了一批。我们用 `StatementInspector` 抓 Hibernate 实际发出的 SQL 做快照断言，Boot 3.2.5 带的 Hibernate 6.4 把表别名生成规则改了：2.7 那套是 `order0_`，6 里变成 `o1_0`。断言输出长这样：

> expected: "select ... from orders order0_ where order0_.status=? order by order0_.created_at desc"
>  but was: "select ... from orders o1_0 where o1_0.status=? order by o1_0.created_at desc"

47 个红里有 11 个是这个。改法我纠结过：是更新快照，还是别断言整条 SQL。选了后者，快照里那些别名、列顺序本来就是 Hibernate 内部实现，升一次级就要刷一次，纯属给自己找活。写了个 `normalizeAlias()`，先把 `o\d+_\d+` 一类别名统一替换成 `t_` 再比，只保留 `where` 条件和 `order by` 的断言；另外 4 个纯 SQL 文本快照直接删了，改成断言返回的记录数和字段值。

`GenerationType.AUTO` 在 Hibernate 6 里也从全局的 `hibernate_sequence` 变成每个实体一个 `xxx_seq`。有 3 个用 `@Sql` 手写 `insert` 的集成测试因此挂了，报的是 `sequence "hibernate_sequence" not found`，跟 SQL 快照那批完全不是一回事，一开始我还以为是同一个原因，白查了半小时。

## 剩下的两天半，全给了 XStream

`OrderMessageParser` 是 2018 年写的一个报文解析工具类，用 XStream 1.4.10 把合作方发来的 XML 转成对象。JDK 16 起 JEP 403 把强封装默认打开，17 里连 `--illegal-access=permit` 都没了，XStream 老版本靠反射去读 `java.util.TreeMap` 的私有字段，直接被挡住：

```bash
Caused by: java.lang.reflect.InaccessibleObjectException:
  Unable to make field private final java.util.Comparator java.util.TreeMap.comparator
  accessible: module java.base does not "opens java.util" to unnamed module @2f0e140b
    at java.base/java.lang.reflect.AccessibleObject.checkCanSetAccessible(AccessibleObject.java:354)
    at java.base/java.lang.reflect.Field.checkCanSetAccessible(Field.java:178)
    at java.base/java.lang.reflect.Field.setAccessible(Field.java:172)
    at com.thoughtworks.xstream.converters.collections.TreeMapConverter.<clinit>(TreeMapConverter.java:43)
    ... 28 more
```

第一版我想糊过去，照着搜来的答案在启动脚本里加 `--add-opens java.base/java.util=ALL-UNNAMED`，本地确实能起了。结果 CI 的镜像是从另一套 Dockerfile 打的，`JAVA_TOOL_OPTIONS` 没带这一串，部署到预发直接起不来，就是上面那段堆栈。补上环境变量之后又冒出 `com.thoughtworks.xstream.security.ForbiddenClassException`，1.4.10 的反序列化白名单也没配。加了 `--add-opens` 只是把报错往后推了一层，根本没解决。

没再跟它较劲：XStream 升到 1.4.20，这个版本起不靠反射撬 JDK 内部字段了，那段报文解析改成 Jackson 的 `XmlMapper`，白名单问题一并没了。这里就体现出前面留 `java.version=17` 的好处——要是当时顺手把编译目标也抬到 21，合作方那台还停在 17 的联调机就得跟着动，又多一轮扯皮。

回头算账：jakarta 包名、Security 配置、Hibernate 快照，加起来不到一天；`--add-opens` 和 XStream 这一摊，两天半。

现在还有几处不干净：测试环境的启动脚本里那条 `--add-opens` 没删，留着是怕还有别的老库没扫到，但每次看都膈应；`rewrite-spring:RELEASE` 打算换成固定版本，还没排上；另外 2 个 Testcontainers 集成测试因为镜像里的 PostgreSQL 12 跟 Hibernate 6 的方言对不上，暂时挂了 `@Disabled`，镜像提到 16 就能放出来。

升级顺序这事我现在会先写进清单：依赖 → 编译 → 启动 → 语法替换 → 测试。`javax` 那一步最显眼，反而最不费时间。你要是也在 2.7 → 3.2 的路上被哪个反射依赖卡过，来 GitHub 开个 issue 报个库名，我攒一份清单。
