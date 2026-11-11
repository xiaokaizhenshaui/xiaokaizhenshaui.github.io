---
title: "给在线书店接 RAG，第一版把整本书塞进 prompt"
date: 2026-05-09
categories:
  - 大模型
tags:
  - RAG
  - 大模型
  - 检索
lead: "47 个 chunk 塞进 prompt，烧 3.8 万 token，答的却是第 1 章。"
---

用户问「《书店夜话》第 12 章里，主人公最后把店盘出去了吗」，模型回了他四百字第 1 章的梗概，末了还报了一遍营业时间。这就是五月六号晚上给在线书店加的那个「问这本书」入口，上线四十分钟我就把它关了。翻日志，那次请求的 `usage.prompt_tokens` 是 38412，我们网关后面挂的模型窗口是 32k，超出的部分被从中间截了——第 12 章那段恰好在被砍掉的后半截里。

说白了第一版就是懒：把一章切完的 chunk 一股脑全拼进 prompt，想着「反正都给它，它自己会挑」。结果又贵又慢，还答非所问。底下这套现在是 PostgreSQL 16.2 + pgvector，embedding 本地跑，Python 3.11，模型走 Ollama 的 `qwen2.5:7b`。四月那篇月度里我留了句「RAG 补一篇工程向的，重点讲 chunk 和 rerank」，rerank 这回没顾上，chunk 倒是结结实实踩了一圈。

## 第一版：整章全拼

代码大概是这样（没留下来，凭记忆复原）：`chunks = split(book_text, 800)`，然后 `prompt = "参考：\n" + "\n".join(chunks) + "\n问题：" + question`。怕超窗口，我自己加了一刀 `prompt[:30000]`，想着截掉点尾巴无所谓。

一本《书店夜话》平均切出 47 个 chunk，全拼进去 3.8 万 token，首字延迟 9.2 秒。更要命的是那一刀：按字符从头截，保留的是第 1 章开头，用户问后面章节就全瞎了。当时贴到群里的翻车记录：

```text
> 《书店夜话》第 12 章里，主人公最后把书店盘出去了吗？

助手：这本书主要讲主人公在城南开了一家小书店，经营范围包括精装本、
      二手书和咖啡，每天早上九点开门，晚上九点打烊。店里常来的客人
      有一位退休的中学老师……（后面四百字全是第 1 章的内容）

我：……我问的是第 12 章。
助手：第 1 章还提到，书店门口种了一排梧桐，夏天很凉快。
```

二十题的小评测集下面细说，第一版只对了 6 题，而那 6 题里有一半恰好是问第 1 章的。怪不着模型，是我把答案亲手切没了，还顺手塞了三万字噪声进去。上下文一长，它根本不会「自己挑」，相关性被稀释得干干净净。

> 那次之后我把「给模型的信息越少越好」当成了默认前提。之前总觉得多给点更保险，实测下来完全反过来。

## 改成 top-k 检索

第二版拆成两步。离线把书切成 chunk、算 embedding、塞进 pgvector；在线把问题也过一遍 embedding，按余弦相似度取最像的 4 段，只把这 4 段拼进 prompt。

embedding 换过一次。先用 `text-embedding-3-small`（1536 维），书名、作者这类还行，但「第几版」「印次」「典藏」这种中文短词区分得很糊。换成智源的 `BAAI/bge-small-zh-v1.5`，512 维，本地 CPU 上一条 400 字 chunk 大约 30ms，维度直接小一半，索引也跟着小。它还有个坑：query 侧要加一句指令前缀「为这个句子生成表示以用于检索相关文章：」，文档侧不加。我第一版忘了加，命中率白掉两题，翻文档才补回来。

表结构和检索 SQL（pgvector 0.5 以上支持 HNSW）：

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE book_chunk (
    id          bigserial PRIMARY KEY,
    book_isbn   text        NOT NULL,
    book_title  text        NOT NULL,
    chapter     int         NOT NULL,
    page        int         NOT NULL,
    content     text        NOT NULL,
    embedding   vector(512) NOT NULL
);

CREATE INDEX ON book_chunk USING hnsw (embedding vector_cosine_ops);

-- $1 是 query 的 embedding（拼成 '[0.1,0.2,...]' 传进来），$2 是 ISBN
SELECT book_title, chapter, page, content,
       1 - (embedding <=> $1::vector) AS score
FROM book_chunk
WHERE book_isbn = $2
ORDER BY embedding <=> $1::vector
LIMIT 4;
```

`<=>` 是余弦距离，`1 - 距离` 就是相似度；`vector_cosine_ops` 对应这个操作符，别和 `vector_l2_ops` 混了。把 `chapter` 和 `page` 存进表里，是为了后面拼 prompt 能带上出处。一开始没建索引，四百多条全表扫 30ms 还挺快，导入二十多本书涨到两万条之后变成 210ms，才补的 HNSW。

## 中文怎么切，实测了一圈

中文没有空格，按词切得先分词，我试了 `jieba`，命中率没涨，代码倒复杂了一倍，撤了。干脆按字符切，原文里用 `[P123]` 标页码，切的时候把标记摘掉、同时记住每个字符属于哪一页：

```python
#!/usr/bin/env python3
"""中文按字符切 chunk，带重叠；顺带把页码记到每个 chunk 上。"""
import re

PAGE_RE = re.compile(r"\[P(\d+)\]")

def split_chunks(text: str, size: int = 400, overlap: int = 60):
    # 摘掉 [P123] 标记，同时记下每个字符对应的页码
    parts, pages = [], []
    pos, page = 0, 1
    for m in PAGE_RE.finditer(text):
        seg = text[pos:m.start()]
        parts.append(seg)
        pages.extend([page] * len(seg))
        page = int(m.group(1))
        pos = m.end()
    seg = text[pos:]
    parts.append(seg)
    pages.extend([page] * len(seg))
    body = "".join(parts)

    step = size - overlap
    out = []
    for start in range(0, len(body), step):
        piece = body[start:start + size].strip()
        if not piece:
            continue
        out.append({"page": pages[start], "content": piece})
        if start + size >= len(body):
            break
    return out

if __name__ == "__main__":
    sample = "[P1]第一章 开张" + "书正文内容" * 300 + "[P2]第二章 常客"
    chunks = split_chunks(sample, size=400, overlap=60)
    print(f"共 {len(chunks)} 个 chunk，首个 {len(chunks[0]['content'])} 字符，起始页 P{chunks[0]['page']}")
```

`size` 和 `overlap` 我拿那 20 题跑了一圈（单本平均 chunk 数、命中率）：

| size | overlap | 平均 chunk | 20 题命中 |
| --- | --- | --- | --- |
| 200 | 0 | 91 | 11 |
| 400 | 0 | 47 | 13 |
| 400 | 60 | 55 | 16 |
| 400 | 120 | 66 | 16 |
| 600 | 80 | 36 | 14 |

400 字符差不多 300 个汉字。重叠从 0 加到 60 涨了 3 题，都是答案正好压在两段边界上的。再加到 120 没变化，倒多出一堆重复片段。600 太大，一段里混进不相关内容，反而掉回 14。试过按 `。` 和换行优先断句，命中率纹丝不动，代码复杂一倍，也撤了。定下来的是 `400 / 60`。

## 拼 prompt 时把来源和页码带上

只把 4 段文本丢进去还是不够，模型偶尔会拿第 3 章的细节去答第 12 章的题。改成每段前面挂书名、章节、页码，并在系统指令里要求它标引用、片段里没有就直说：

```python
#!/usr/bin/env python3
"""把检索结果拼成 prompt；每段带出处，要求模型给出引用。"""
from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
MODEL = "qwen2.5:7b"

SYSTEM = (
    "你是在线书店的图书问答助手。只根据下面提供的片段回答，"
    "不要编造书里没有的内容。回答里用 [书名 第X章 P页码] 标出依据；"
    "片段里没有答案就直接说「现有片段里没有提到」。"
)

def build_prompt(question: str, rows: list[dict]) -> str:
    blocks = []
    for i, r in enumerate(rows, 1):
        blocks.append(
            f"[{i}] 来源：《{r['book_title']}》 第{r['chapter']}章 P{r['page']} "
            f"(相似度 {r['score']:.3f})\n{r['content']}"
        )
    context = "\n\n".join(blocks)
    return f"{SYSTEM}\n\n--- 参考片段 ---\n{context}\n\n--- 问题 ---\n{question}"

def ask(question: str, rows: list[dict]) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": build_prompt(question, rows)}],
        temperature=0.1,
    )
    return resp.choices[0].message.content

if __name__ == "__main__":
    print(build_prompt("这本书讲的是谁？", [
        {"book_title": "书店夜话", "chapter": 3, "page": 47,
         "score": 0.812, "content": "老板姓陈，早年在出版社做校对。"},
    ]))
```

带上出处之后，20 题从 16 到 17。涨的这一题跟模型变没变聪明没关系，是我能顺着引用去人工核对了。剩下 3 道错题里有 2 道是「检索捞对了、模型没用对」，一看 `[第3章 P47]` 就知道它拿错段了。单次 `prompt_tokens` 从 38412 降到 2140，首字延迟 9.2 秒到 1.4 秒。

> chunk 有 60 字符重叠，一段可能横跨两页，我按起始字符归页，偶尔把 P47 引成 P46。差一页，暂时忍着，没想好要不要按占比归。

## 20 题小评测集

评测集是从客服日志里挑的 20 个真实问题，人工标好答案出自哪章哪页：8 题问细节（某个人名、某个数字），7 题要跨两章才能答，还有 5 题故意问书里根本没有的东西，测它会不会瞎编。

| 版本 | 命中 | 拒答（5 题） | 单次输入 |
| --- | --- | --- | --- |
| 整章全拼 | 6 / 20 | 0 / 5 | 38412 token |
| top-k=4，400/0 | 13 / 20 | 3 / 5 | 1980 token |
| 400/60 | 16 / 20 | 4 / 5 | 2050 token |
| 带来源页码 | 17 / 20 | 4 / 5 | 2140 token |

把 top-k 从 4 调到 6 试过，命中率 17 掉到 16，多塞进来的两段把模型带偏了，宁可少给。剩下 3 道错题：2 道是真没检索到，其中 1 道 top-k 给到 6 能救，但另外那版整体又亏了；1 道是模型看串了引用。

单轮问答现在能用了，一接追问就垮。用户问完「第 12 章他最后把店盘出去了吗」，接着来一句「那他后来呢」或者「这个版本多少钱」，我拿原话去做检索，向量里全是「后来」「这个」，捞回来一堆不相干的片段。拿 20 个追问单独测了一遍，只对了 5 题。

试过把上一轮的问题拼在前面当 query，能救回 3 题，但用户中途换书时，上一轮的实体会硬跟过来，把新问题带偏。

卡住的地方是两条路：要么单独加一步 query 改写，先让模型把「那他后来呢」补成「《书店夜话》第 12 章主人公最后有没有把书店盘出去」再去检索，多一次调用，延迟加约 400ms；要么维护一张小状态表，把会话里出现过的书名、章节、人名记下来，检索前填进 query，便宜，但得处理用户突然换一本书的情况。两条路各跑一版，就用那 20 个追问。
