---
title: "中文书名检索换成 embedding 后，我把评测集重写了一遍"
date: 2026-08-22
categories:
  - 大模型
tags:
  - 大模型
  - embedding
  - 检索
lead: "recall@5 从 0.617 涨到 0.862，但真正费劲的不是换模型，是发现旧评测集把一半正确召回标成了不相关。"
---

8 月 19 号凌晨一点，`python3 tools/eval_vector.py --runs eval/hybrid_run.jsonl --k 5` 第一次跑出 `recall@5=0.862`，比 7 月那版关键词检索的 0.617 高了一大截。按理该高兴，可我盯着 bad case 看了十分钟，越看越不对：`三休` 召回了《三体》、`分布式架构` 召回了《微服务设计》，按旧评测集算，这两条都记成「检索错误」。翻到标注文件才反应过来——不是检索错了，是评测集照着「字面能不能命中」标的。第二天我把 47 条 query 全推翻重标，扩到 68 条。这篇写的是这一轮，以及 pgvector 那边的账。

## 关键词检索卡在哪

书店检索层原来是 Elasticsearch 8.13.4 + IK 分词，BM25 打分。三类 query 它天生接不住：

- **同义词**：搜「分布式」找《微服务设计》，词面不重合，BM25 直接 0 分。
- **错别字**：`三休`、`哈利玻特`，分词完啥也匹配不上。
- **简称和中英混排**：`HP`、`重构 第二版`、`1984`，要么撞上英语缩写，要么数字被当成编号。

线上日志里这种不少，`2026-08-03 11:22:41 WARN query="三休" hits=0 cost=18ms` 只是其中一条。7 月那版评测集 47 条 query、213 个标注对，`recall@5=0.617`。当时我一口咬定瓶颈在词库，往 IK 里塞了 600 多个自定义词，只涨到 0.631，1.4 个点。顺带一提，那 600 个词还得长期有人维护，想想就不划算，后来全删了。

## 三个模型，我实测下来的取舍

榜单分数我一个不贴，那些数字跟我这批平均 9 个字的短书名 query 不是一回事，看了也没用。只说自己这套上的相对值：

| 模型 | 维度 | 单条编码耗时（4C8G / CPU） | 68 条 query 上 recall@5 |
| --- | --- | --- | --- |
| m3e-base | 768 | 11 ms | 0.741 |
| BAAI/bge-large-zh-v1.5 | 1024 | 29 ms | 0.784 |
| BAAI/bge-m3 | 1024 | 38 ms | 0.812 |

环境是 Python 3.11.9 + sentence-transformers 3.3.1，没上 GPU。第一版我直接用了 bge-m3，理由很简单：比 bge-large-zh-v1.5 多 2.8 个点。压了一下才傻眼，查询侧单条 38 ms，加上 ES 那一路和 RRF 合并，P99 从 42 ms 涨到 96 ms。书名是离线灌库、编码慢点无所谓，查询是在线的，慢的 3 倍全压在用户请求上。退回 bge-large-zh-v1.5，P99 回到 61 ms，recall 掉 2.8 个点，认了。768 维确实省地方，但掉 4.3 个点，不值。

存储账也顺手算了下：2 万本书切出 31248 个 chunk，1024 维 float4 原始向量 `31248 × 1024 × 4 ≈ 122 MB`，HNSW 索引（`m=16, ef_construction=64`）另外 178 MB。换 768 维能省 30 MB 左右，对这台机器来说根本不算瓶颈，没必要为它牺牲召回。

## chunk 切法：切碎了反而掉点

第一版按 128 token 切、overlap 16，想着粒度细一点召回更准，结果 `recall@5=0.742`，比不切还差。点开 bad case 一看，书名和简介被切到两个 chunk 里，单看一半向量谁都不像。改成 256 token、overlap 32，书名短于 30 字的整条不切、纯书名另存一列做加权，才到 0.784。512 token 也试了，0.761，长简介里塞了目录和推荐语，噪声把书名那点信息冲淡了。

| 切法 | chunk 数 | recall@5 |
| --- | --- | --- |
| 128 / overlap 16 | 58 902 | 0.742 |
| 256 / overlap 32（最后用的） | 31 248 | 0.784 |
| 512 / overlap 64 | 16 704 | 0.761 |
| 不切，一本书一条 | 20 000 | 0.703 |

「短书名不切」这条纯属试出来的，不是什么理论。中文书名平均就 9 个字，硬按 token 切等于把「三体」和「刘慈欣」拆开，怎么想都不对。灌库脚本离线批跑，31248 条编码加写库一共 21 分钟。

## 存进 pgvector

服务端 PostgreSQL 16.3 + pgvector 0.8.0。DDL 和检索语句放一起，`%s` 是脚本里绑定的查询向量占位符：

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE book_chunks (
    id          bigserial    PRIMARY KEY,
    book_id     bigint       NOT NULL,
    book_title  text         NOT NULL,
    chunk_no    integer      NOT NULL,
    content     text         NOT NULL,
    embedding   vector(1024) NOT NULL
);

-- 灌完 31248 条再建索引，用了 4 分 12 秒
CREATE INDEX book_chunks_embedding_hnsw
    ON book_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 下面这条由 vector_search.py 提交，%s 依次为查询向量、查询向量、LIMIT
SET hnsw.ef_search = 100;
SELECT book_id, book_title, chunk_no,
       1 - (embedding <=> %s::vector) AS score
FROM book_chunks
ORDER BY embedding <=> %s::vector
LIMIT %s;
```

`<=>` 是 cosine 距离，越小越像，所以拿 `1 - 距离` 当分数。`ef_search` 从 40 试到 200，100 之后 recall 基本不动、延迟一直涨，就停在这——这个数是拍脑袋定的，没做过并发压测，后面说。查询侧和灌库侧用的是同一个模型，编码时都开了 `normalize_embeddings=True`，否则 cosine 距离和归一化前的向量混在一起会比较乱。

## 把评测集重写了一遍

旧版那 47 条是照着关键词检索标的，「相关」约等于「字面能命中」。换成向量之后，同义词、错别字、简称这三类召回全被记成错误。重写后 68 条，分四类，每条人工标 3 到 5 本相关书，两个人各标一遍，9 条有分歧的拉出来逐条定，最后 287 个 `(query, 相关书)` 对。规则写进 `eval/README.md`：

> 「相关」= 一个真实用户输这个 query 时想找的就是这本书，不看字面有没有命中、不看是不是同一系列。系列书只标用户最可能要的那一册，不把整套全标上。错别字 query 按用户本意标。

同一套检索，只换标注口径，数字长这样：

| 检索方式 | 旧评测集 47 条 | 新评测集 68 条 |
| --- | --- | --- |
| BM25（IK） | 0.617 | 0.604 |
| 向量 bge-large-zh-v1.5 | 0.683 | 0.784 |
| 关键词 + 向量 RRF 混合 | 0.712 | 0.862 |

混合那行凭空多出 15 个点，全是标注给的，模型一个字没改。这事让我有点后背发凉：7 月月报里我还拿 0.617 当基线写得挺笃定，现在看那个数本身就不干净。

重写时特意留下来的几条 bad case，原样记在 `eval/disagreements.md` 里：

| query | 用户想要的 | 混排后排第一的 | 麻烦在哪 |
| --- | --- | --- | --- |
| 三休 | 三体 | 三休的日子 | 错别字，还刚好有本字面一样的书 |
| HP | 哈利·波特与魔法石 | HTTP 权威指南 | 简称撞了英文缩写 |
| 1984 | 一九八四 | 1984 年大事记 | 数字被当成年份 |
| 重构 第二版 | 重构（第2版） | 重构（第1版） | 版本号没进向量 |
| 微服务 | 微服务设计 | 分布式系统概念与设计 | 其实算对，两个标注人争了半天 |

最后一条按 README 里「最可能要的那一册」才勉强算对。分歧没偷偷改，全留着了。

## 检索脚本和评测脚本

依赖就三个，命令行都能直接跑：`psycopg[binary]==3.2.3`、`pgvector==0.3.6`、`sentence-transformers==3.3.1`。

```python
#!/usr/bin/env python3
"""tools/vector_search.py：把 query 编码后走 pgvector 的 HNSW 检索。"""
import argparse
import os

import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-large-zh-v1.5"
SQL = """
SELECT book_id, book_title, chunk_no,
       1 - (embedding <=> %s::vector) AS score
FROM book_chunks
ORDER BY embedding <=> %s::vector
LIMIT %s
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--q", required=True, help="用户输入的检索词")
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    model = SentenceTransformer(MODEL_NAME)
    vec = model.encode(args.q, normalize_embeddings=True)

    dsn = os.environ.get("BOOK_DB_DSN", "postgresql://localhost/bookstore")
    with psycopg.connect(dsn) as conn:
        register_vector(conn)
        conn.execute("SET hnsw.ef_search = 100")
        rows = conn.execute(SQL, (vec, vec, args.k)).fetchall()

    print(f"查询：{args.q}　命中 {len(rows)} 条")
    for book_id, title, chunk_no, score in rows:
        print(f"{score:.4f}  {book_id}  {title}  第 {chunk_no} 段")


if __name__ == "__main__":
    main()
```

评测脚本按类别分开算，不然错别字那类被总数一平均就看不见了：

```python
#!/usr/bin/env python3
"""tools/eval_vector.py：按 query 类别分别统计 recall@k。"""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def load_jsonl(path):
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qrels", default="eval/qrels_v2.jsonl")
    ap.add_argument("--runs", default="eval/hybrid_run.jsonl")
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    qrels = {r["query"]: (r["kind"], set(r["relevant"]))
             for r in load_jsonl(Path(args.qrels))}
    runs = {r["query"]: r["hits"] for r in load_jsonl(Path(args.runs))}

    by_kind = defaultdict(list)
    for q, (kind, relevant) in qrels.items():
        hits = set(runs.get(q, [])[:args.k])
        by_kind[kind].append(len(hits & relevant) / len(relevant))

    all_scores = [s for group in by_kind.values() for s in group]
    for kind in sorted(by_kind):
        g = by_kind[kind]
        print(f"{kind:<10} 条数={len(g):<3} recall@{args.k}={sum(g) / len(g):.3f}")
    print(f"{'合计':<10} 条数={len(all_scores):<3} "
          f"recall@{args.k}={sum(all_scores) / len(all_scores):.3f}")


if __name__ == "__main__":
    main()
```

```bash
pip install "psycopg[binary]==3.2.3" pgvector==0.3.6 sentence-transformers==3.3.1

export BOOK_DB_DSN="postgresql://book:****@127.0.0.1/bookstore"
python3 tools/vector_search.py --q "分布式架构" --k 5
# 查询：分布式架构　命中 5 条
# 0.8312  10241  微服务设计  第 0 段
# 0.8077  10402  分布式系统概念与设计  第 1 段

python3 tools/eval_vector.py --runs eval/hybrid_run.jsonl --k 5
# 字面        条数=20  recall@5=0.941
# 同义词      条数=18  recall@5=0.876
# 错别字      条数=12  recall@5=0.708
# 简称/混排   条数=18  recall@5=0.822
# 合计        条数=68  recall@5=0.862
```

## 还没解决的

错别字那类 0.708，比同义词的 0.876 低一大截，加一层拼音或编辑距离的召回兜底应该能补，可它和向量分数怎么融合没定：RRF 只吃排名不吃分数，简单加权我又怕把别的类别压坏。`ef_search=100` 也还是拍脑袋的，并发上来之后会不会塌没验过。增量灌库更糙，新书上架到向量可见最长滞后 6 小时，运营那边已经问过两次了。

最卡住的其实是个标注问题：`重构 第二版` 那条，用户输第二版，召回第一版到底算不算错？两个标注人给了不同答案，最后按「用户最可能要的那一册」勉强判对。这个「最可能」怎么定义，我到现在没写出一条能落地的规则，下次再写。
