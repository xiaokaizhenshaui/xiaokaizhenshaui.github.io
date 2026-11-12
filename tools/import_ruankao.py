#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
软考高级（Obsidian）笔记 -> Hexo 独立专栏「软考笔记」一次性导入脚本。

源：/Users/mr.caius/Documents/software/obsidianmemory/mymemory/软考高级
目标：hexo-source/source/软考/

处理项：
1. front-matter 规范化：取 H1 作为 title、created 作为 date，补 layout:page、字面量 permalink（软考/<相对路径>/，保留目录结构）；丢弃 Obsidian 的 tags/aliases。
2. 双链 [[目标]] / [[目标|别名]] -> 相对可点击链接（基于 :path/ 结构计算相对路径）；找不到目标时退化为纯文本。
3. callout > [!type] -> 普通引用块（保留中文标签）。
4. 代码围栏（``` / ~~~）内的内容原样保留，避免破坏 mermaid 的 [[体育场节点]] 与代码样例。
5. README.md 变为专栏落地页 source/软考/index.md（permalink: 软考/）。
6. SVG 按原目录结构复制；.canvas / .py 存入 _tools/（Hexo 不发布但留档）。

运行：python3 tools/import_ruankao.py
"""

import os
import re
import shutil

SRC = "/Users/mr.caius/Documents/software/obsidianmemory/mymemory/软考高级"
DST = "/Users/mr.caius/Documents/work/home/hexo-source/source/软考"

CALLOUT_LABELS = {
    "abstract": "摘要", "tip": "提示", "note": "笔记", "warning": "注意",
    "danger": "警告", "info": "信息", "example": "示例", "quote": "引用",
    "question": "问题", "success": "完成", "bug": "缺陷", "failure": "失败",
    "important": "重点", "tldr": "小结", "todo": "待办", "hint": "提示",
}

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
WIKILINK_RE = re.compile(r"\[\[([^\]]+?)\]\]")
CALLOUT_RE = re.compile(r"^(\s*>)\s*\[!([A-Za-z-]+)\]")
IMG_RE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)\s*\)")

# 记录未解析的双链，便于人工核对
UNRESOLVED = set()


def parse_fm(text):
    m = FM_RE.match(text)
    if not m:
        return {}, text
    block = m.group(1)
    body = text[m.end():]
    fm = {}
    cm = re.search(r"created:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", block)
    if cm:
        fm["created"] = cm.group(1)
    am = re.search(r"aliases:\s*\[(.*?)\]", block)
    if am:
        fm["aliases"] = [a.strip().strip("\"'") for a in am.group(1).split(",") if a.strip()]
    return fm, body


def collect_metas():
    metas = {}
    md_files = []
    for root, _dirs, files in os.walk(SRC):
        for f in files:
            if not f.endswith(".md"):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, SRC)
            base = f[:-3]
            md_files.append((full, rel, base))
            page_dir = rel[:-3]
            fm, _ = parse_fm(open(full, encoding="utf-8").read())
            metas[base] = page_dir
            for al in fm.get("aliases", []):
                metas.setdefault(al, page_dir)
    return metas, md_files


def resolve_link(target, current_dir, metas):
    if "|" in target:
        t, disp = target.split("|", 1)
        t, disp = t.strip(), disp.strip()
    else:
        t, disp = target.strip(), target.strip()
    t_norm = t.split("#")[0].strip()
    if t_norm in metas:
        target_dir = metas[t_norm]
        rel = os.path.relpath(target_dir, current_dir)
        href = rel.replace(os.sep, "/")
        if not href.endswith("/"):
            href += "/"
        return f"[{disp}]({href})"
    UNRESOLVED.add(t_norm)
    return disp


def rewrite_img(m, current_dir):
    alt, path = m.group(1), m.group(2)
    if path.startswith("./") or path.startswith("../"):
        # 相对图片路径易被 Hexo 的 url_for 错误处理（会变成 /../ 导致 404），
        # 这里改写成站点绝对路径 /软考/<解析后路径>/。
        resolved = os.path.normpath(os.path.join(current_dir, path))
        path = "/" + os.path.join("软考", resolved).replace(os.sep, "/")
    return f"![{alt}]({path})"


def transform_body(body, current_dir, metas):
    lines = body.split("\n")
    out = []
    in_fence = False
    for line in lines:
        stripped = line.lstrip()
        if re.match(r"^```|^~~~", stripped):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        cm = CALLOUT_RE.match(line)
        if cm:
            label = cm.group(2).lower()
            lab = CALLOUT_LABELS.get(label, label)
            out.append(f"{cm.group(1)} **{lab}**：")
            continue
        if "[[" in line:
            line = WIKILINK_RE.sub(lambda m: resolve_link(m.group(1), current_dir, metas), line)
            line = re.sub(r"\[\[\]\]", "", line)  # 清掉空占位双链 [[]]
        if "![" in line:
            line = IMG_RE.sub(lambda m: rewrite_img(m, current_dir), line)
        out.append(line)
    return "\n".join(out)


def main():
    if os.path.exists(DST):
        print("目标已存在，清空：", DST)
        shutil.rmtree(DST)
    os.makedirs(DST, exist_ok=True)

    metas, md_files = collect_metas()

    for full, rel, base in md_files:
        text = open(full, encoding="utf-8").read()
        fm, body = parse_fm(text)
        hm = H1_RE.search(body)
        title = hm.group(1) if hm else base
        if hm:
            body = body[:hm.start()] + body[hm.end():]
        body = body.lstrip("\n")

        current_dir = os.path.dirname(rel)
        new_body = transform_body(body, current_dir, metas)
        date = fm.get("created", "2026-10-24")

        if base.lower() == "readme":
            out_rel = "index.md"
            permalink = "软考/"
        else:
            out_rel = rel
            page_dir = rel[:-3]
            permalink = "软考/" + page_dir + "/"

        out_path = os.path.join(DST, out_rel)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        new_fm = (
            "---\n"
            f"title: {title}\n"
            f"date: {date}\n"
            "layout: page\n"
            f"permalink: {permalink}\n"
            "---\n"
        )
        open(out_path, "w", encoding="utf-8").write(new_fm + new_body)

    # 复制 SVG（保留原结构）；.canvas / .py 存入 _tools（Hexo 不发布但留档）
    for root, _dirs, files in os.walk(SRC):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, SRC)
            if f.endswith(".svg"):
                dst = os.path.join(DST, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(full, dst)
            elif f.endswith(".canvas") or f.endswith(".py"):
                dst = os.path.join(DST, "_tools", os.path.basename(full))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(full, dst)

    print(f"导入完成：{len(md_files)} 篇 md 写入 {DST}")
    print(f"未解析双链（退化为纯文本，可人工核对）：{len(UNRESOLVED)}")
    for u in sorted(UNRESOLVED):
        print("  -", u)


if __name__ == "__main__":
    main()
