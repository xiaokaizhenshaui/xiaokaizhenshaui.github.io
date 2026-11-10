---
title: "ElasticSearch 学习手册"
date: 2022-01-17
updated: 2026-11-10
categories:
  - 中间件
tags:
  - "ElasticSearch"
  - "搜索"
lead: "原文只有半页、配图也挂了，这次补 mapping 和深分页的实际写法。"
---
> 这篇写于 2022 年。原站配图用的免费图床后来全挂了，这次改版把失效截图换成了本地 SVG 示意图，正文和命令保持原样，现在该怎么做放在文末「2026 补记」里。

## ElasticSearch学习手册

## ElasticSearch初始入门

[ElasticSearch官方](https://www.elastic.co/cn/)

![倒排索引结构](/images/diagrams/es-inverted-index.svg)

### ES简介📚

Elasticsearch 是一个分布式可扩展的实时搜索和分析引擎,一个建立在全文搜索引擎 *Apache Lucene*基础上的搜索引擎.

> - ElasticSearch对搜索引擎的操作都封装成restful的api，通过http请求就能对其进行操作。
> - 分布式实时文件存储，实时分析。
> - 可扩展到上百台服务器，处理PB级别的结构化或者非结构化数据。

### ES文件存储形式💽

Elasticsearch是面向文档型数据库，一条数据在这里就是一个文档，用*JSON*作为文档序列化的格式

[漫画介绍👈](https://developer.51cto.com/art/201904/594615.htm)

> | 关系数据库 | DB库 | 表 | 行 | 列 |
> | --- | --- | --- | --- | --- |
> | ES | 索引(Index) | 类型(Type) | 文档(Docments) | 字段(Fields) |
>
> - **keyword**与**text**的区别
>
>   > - keyword类型不会分词，根据字符串内容建立反向索引
>   > - Text 类型在存入时，会先分词，然后根据分词后的内容建立反向索引

ES核心概念

> - NRT
>
>   接近实时的搜索平台。
> - cluster**集群**
>
>   由一个或者多个节点组织在一起，共同持有整个数据，一起提供索引和搜索。名字默认是“elasticsearch”
> - node**节点**
> - index**索引**
> - type**类型**
> - document**文档**
> - shards&replicas**分片和复制**

## 2026 补记

原文只写了半页就断了，配图也挂了。补两段真正建索引时会用到的东西。

```json
PUT /books
{
  "mappings": {
    "properties": {
      "title":     { "type": "text", "fields": { "raw": { "type": "keyword" } } },
      "author":    { "type": "keyword" },
      "price":     { "type": "scaled_float", "scaling_factor": 100 },
      "published": { "type": "date", "format": "yyyy-MM-dd" }
    }
  }
}
```

`title.raw` 是给排序和聚合留的。text 类型默认没有 doc_values，直接拿它做 `terms` 聚合会报 `Fielddata is disabled on text fields by default` —— 这个报错我至少见过三次，每次都是新建索引时忘了加子字段。

深分页别用 `from + size` 翻到几千页，`search_after` 配 PIT 才稳：

```json
GET /books/_search
{
  "size": 20,
  "sort": [{ "published": "desc" }, { "_id": "asc" }],
  "search_after": ["2026-01-01", "book-1024"]
}
```

sort 里补 `_id` 不是洁癖：只按 `published` 排，遇到相同日期时翻页会漏数据或者重复。
