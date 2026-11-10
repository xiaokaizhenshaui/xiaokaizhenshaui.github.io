---
title: "让大模型稳定吐 JSON，我删掉了半页提示词"
date: 2026-07-11
categories:
  - 大模型
tags:
  - 大模型
  - 结构化输出
  - API
lead: "删掉半页「只输出 JSON 不要解释」和三层正则兜底、改开严格模式之后，解析失败率从 11.4% 降到 0.3%，剩下的 0.3% 重试三次也救不回来。"
---

7 月 8 号下午 15:42，日志里连着三条一样的报错：

```bash
$ grep 'search.parse' /var/log/book-api/app.log | tail -3
2026-07-08T15:42:09+08:00 ERROR search.parse JSONDecodeError: Expecting ',' delimiter: line 4 column 19 (char 71)  raw=```json\n{\n  "author": "余华",\n  "in_stock": true，...
2026-07-08T15:42:10+08:00 ERROR search.parse JSONDecodeError: Expecting property name enclosed in double quotes: line 6 column 3 (char 108)
2026-07-08T15:42:11+08:00 ERROR search.parse JSONDecodeError: Expecting ',' delimiter: line 4 column 19 (char 71)
```

出错的是「自然语言搜书」这个入口：用户敲「找一下余华写的、有货的、五十块以下的书」，我让模型把它解析成结构化检索条件，再交给后端的 GraphQL `bookSearch`。环境是 Python 3.12.4、pydantic 2.7.4，走的是兼容 OpenAI 格式的网关。这一天之前，我已经给这段解析加了半页提示词和三层正则兜底，越补越像在给模型的自由发挥打补丁。当天下午我把提示词删到只剩一句，改开严格模式——这是后话，先说第一版有多烂。

## 第一版：半页提示词加三层正则

第一版的 system prompt 我写了大概半页，核心是这么几句：「只输出 JSON，不要任何解释」「不要用 markdown 代码块」「所有标点用英文半角」「不要尾逗号」「数字不要写成中文」，后面还挂了两个 few-shot 例子。调用侧配了三层兜底：

```python
import json
import re


def loose_load(raw: str) -> dict:
    s = raw.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()  # 去围栏
    s = s.replace("，", ",").replace("“", '"').replace("”", '"')     # 全角标点
    s = re.sub(r",\s*([}\]])", r"\1", s)                           # 去尾逗号
    return json.loads(s)
```

这三层各管一类，看着挺周全，实际每周都能冒出新花样。7 天里 3821 次调用，436 次走到 `loose_load` 还是炸了，11.4%。按失败原因拆：

| 原因 | 次数 | 占比 |
| --- | --- | --- |
| 外层 ```json 围栏没去掉干净 | 183 | 42.0% |
| 中文引号 / 全角逗号 | 100 | 22.9% |
| 尾逗号 | 83 | 19.0% |
| JSON 前面多一句「好的，解析结果如下：」 | 48 | 11.0% |
| 其他（数字写成中文、缺字段…） | 22 | 5.1% |

围栏那条最气：正则用了 `re.M`，模型有时在 ```json 前面还带一句解释，锚点就匹配不上。全角逗号那条 `json.loads` 报的是 `Expecting ',' delimiter`，第一眼我以为是自己的正则写错了，查了二十分钟才看见那个 `，`。

顺带一提，这半页提示词里最短的一句「只输出 JSON」，恰恰是一点用都没有的那句。模型不是不听话，是它在「输出一段像 JSON 的文本」和「输出一个 JSON 值」之间根本没有强制边界。

## 坏输出长这样

贴一段 7 月 8 号那次 `response.choices[0].message.content` 的原文：

````
```json
{
  "author": "余华",
  "in_stock": true，
  "max_price": "五十",
  "tags": ["小说", "当代",],
}
```
````

四个坑凑齐了：外层 ```json 围栏、`true` 后面的全角逗号、`"tags"` 里的尾逗号、`"五十"` 把数字写成了中文。还有一次更绝，模型在 JSON 前面加了句「好的，这是解析结果：」，正则的 `^```(?:json)?` 直接失效。

这四类用正则都能补，但每补一类就多一个分支。两周里我给 `loose_load` 加了 4 个 `if`，还是漏——漏的那次是模型把 key 拼成了 `"有货: true"` 这种，连字段都对不上。到这一步我认了：靠字符串清洗去追模型的自由发挥，追不上。

## 改成严格模式，顺便把提示词删了

改成让接口自己约束输出形状：`response_format` 用 `json_schema`，`strict: true`。schema 单独放一份文件，请求里读进来：

```json
{
  "type": "object",
  "properties": {
    "author": { "type": ["string", "null"], "description": "作者名，没有提到时填 null" },
    "in_stock": { "type": ["boolean", "null"], "description": "是否只要有货的书" },
    "max_price": { "type": ["number", "null"], "description": "价格上限，单位元" },
    "tags": { "type": "array", "items": { "type": "string" }, "description": "题材标签" },
    "error_code": {
      "type": ["string", "null"],
      "enum": ["STOCK_NOT_ENOUGH", "BOOK_NOT_FOUND", "INVALID_CURSOR", null],
      "description": "无法解析时填英文错误码，正常解析填 null"
    }
  },
  "required": ["author", "in_stock", "max_price", "tags", "error_code"],
  "additionalProperties": false
}
```

严格模式对 schema 有硬要求，我第一版就踩了：每个字段都得进 `required`，对象要写 `additionalProperties: false`，可选字段不能省略、得用 `["string", "null"]` 这种联合类型表示「没提到」。还有 `pattern`、`minLength` 这类关键字当时不被支持，我原本想让模型别把关键词写得太长，只能挪到校验层去做。enum 里那个 `null` 也得显式列进去，否则「正常解析」这个状态表达不了。

中文键名这事顺带说一句。第一版 schema 我图省事用了「作者」「库存」这种中文 key，结果 Pydantic 的 alias、前端的字段名、日志里的 key 三处对不上，改了两轮还是别扭，最后全换成英文标识符，中文只留在 `description` 和 `message` 的值里。错误码 enum 坚持用英文（`STOCK_NOT_ENOUGH` 这些），中文文案是给前端展示的，混在 enum 里以后做匹配会很难受。

system prompt 从半页删成一句：「把用户的搜书需求解析成检索条件，没提到的字段填 null。」调用侧：

```python
#!/usr/bin/env python3
"""自然语言搜书：解析 -> 重试 -> 降级。
依赖：pip install openai pydantic
用法：python search_parse.py "找一下余华写的、有货的、五十块以下的书"
"""
import json
import os
import random
import sys
import time
from pathlib import Path

from openai import OpenAI
from pydantic import ValidationError

from schemas import SearchFilter, parse_filters   # 见下一节

# 模型名和网关地址都走环境变量，不在这里写死版本
client = OpenAI(
    api_key=os.environ["MODEL_API_KEY"],
    base_url=os.environ.get("MODEL_BASE_URL"),
)
MODEL = os.environ["SEARCH_MODEL"]

SCHEMA = json.loads(
    Path(__file__).with_name("search_filter.schema.json").read_text(encoding="utf-8")
)

def call_model(query: str) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "把用户的搜书需求解析成检索条件，没提到的字段填 null。"},
            {"role": "user", "content": query},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "search_filter",
                "strict": True,
                "schema": SCHEMA,
            },
        },
    )
    return resp.choices[0].message.content or ""

def parse_with_retry(query: str) -> SearchFilter:
    last_err = None
    for attempt in range(3):
        try:
            return parse_filters(call_model(query))
        except (json.JSONDecodeError, ValidationError, TimeoutError) as e:
            last_err = e
            if attempt < 2:
                # 0.4s / 0.8s，加一点抖动避开同一时刻的重试
                time.sleep(0.4 * (2 ** attempt) + random.random() * 0.1)
    # 三次都失败：不抛 500，降级成不带筛选条件的默认检索
    print(f"[warn] 解析失败，走降级: query={query!r} err={last_err!r}", file=sys.stderr)
    return SearchFilter()

if __name__ == "__main__":
    print(json.dumps(parse_with_retry(sys.argv[1]).model_dump(),
                     ensure_ascii=False))
```

`OpenAI(...)` 这里是通用写法，我们接的是兼容这套格式的网关，`base_url` 从配置注入；具体的模型名和 SDK 版本跟着 requirements 走，不写死在代码里。

## 还是加了一层 Pydantic

严格模式能保证「是合法 JSON 且形状对」，但保证不了「值合理」。`max_price` 照样可能给 -50，`tags` 可能塞 30 个元素，enum 拼错了也只是个字符串。网关偶尔还会返回被截断的内容（后面 0.3% 里几乎全是这个）。所以 `parse_filters` 里再做一次校验：

```python
#!/usr/bin/env python3
"""schemas.py：结构化输出的二次校验。"""
from typing import Literal

from pydantic import BaseModel, Field

ErrorCode = Literal["STOCK_NOT_ENOUGH", "BOOK_NOT_FOUND", "INVALID_CURSOR"]

class SearchFilter(BaseModel):
    author: str | None = None
    in_stock: bool | None = None
    max_price: float | None = Field(default=None, ge=0, le=10000)
    tags: list[str] = Field(default_factory=list, max_length=8)
    error_code: ErrorCode | None = None

    model_config = {"extra": "forbid"}

def parse_filters(raw: str) -> SearchFilter:
    # 严格模式下不该有围栏，这里仍留一道，兼容网关偶尔返回的旧格式
    cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()
    return SearchFilter.model_validate_json(cleaned)
```

`extra="forbid"` 对应 schema 里的 `additionalProperties: false`，多一个字段就判失败。`removeprefix` 那行我犹豫过要不要留，最后留了——9 天里真有 2 次是兼容层把旧格式透传回来的，删掉就得走一次重试。

`ValidationError` 被 `parse_with_retry` 接住，和 `JSONDecodeError` 走同一条重试路径。校验放在这一层而不是塞进 prompt，是因为「价格不能是负数」这种规则写进提示词，模型也只是「尽量遵守」，写进 `Field(ge=0)` 才是每次都判。

## 重试、退避，以及三次之后的降级

重试逻辑就在上面那个 `parse_with_retry` 里：三次，间隔 0.4s 和 0.8s 加抖动，指数退避。这里有个前提变了——严格模式下模型输出本身几乎不会坏，剩下的失败基本不是「模型又乱写了」，而是网关超时、流式返回被截断、或者兼容层偶发抽风。同源请求连着重试，有时三次拿到的都是同一截坏内容，所以第三次之后必须有个落脚点。

降级我选的是返回 `SearchFilter()`，也就是不带任何筛选条件的默认列表页。对用户来说是从「精确搜书」退化成「随便逛逛」，页面不会 500，也不会弹一句「解析失败请重试」。原始 query 和 `last_err` 打进 stderr 和一条告警，第二天能捞出来看。这个取舍我纠结过：要不让用户重试一次？后来发现失败集中在网关抖动那一两分钟，让用户点第二次只会再撞上，不如先给结果。

改完之后 9 天 5107 次调用，走到 `parse_filters` 抛异常的 15 次，0.29%（对外说 0.3%）。其中 12 次重试一次就过，3 次三次都失败走了降级，这 3 次捞出来看全是网关返回的 content 被截断，`finish_reason` 是 `length`。解析失败率从 11.4% 到 0.29%，差的不是那半页提示词，是「约束从一句话变成接口参数」。

## 还没解决的

严格模式不支持 `pattern`、`minLength` 那类关键字，所以「关键词长度别超过 40」现在只在 Pydantic 里判，模型那边并不知道有这条，偶尔会吐一个超长的 `author`，校验拦下来之后走一次重试——等于把本可以在生成时避免的事推给了重试。等网关那边支持更多 schema 关键字了再挪回去。

还有归一化。用户写「余华 著的」「余华写的书」，模型会把 `author` 填成「余华 著的」，`SearchFilter` 校验全过，但 GraphQL 那边按精确匹配搜不到东西。这类「合法但没用」的输出现在完全没拦，日志里也看不出来，只在搜书无结果率上隐约高了一点。想加一层 trim / 别名表，还没动手。

那 3 次 `finish_reason=length` 也有点悬：真要是用户敲了一整段话，`max_tokens` 不够就会稳定复现，降级会变成常态。按输入长度动态给 `max_tokens` 这事我试了一版，怕把成本顶上去又撤了。下次再写。

如果你也在用严格模式，尤其是碰到过 schema 关键字被拒、或者网关透传旧格式的情况，欢迎到 GitHub 开 issue 聊两句。
