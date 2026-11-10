#!/usr/bin/env python3
"""CI 质量门禁：图片引用、front-matter、代码块语言标注、AI 套话。

本地跑法：  python3 tools/check_assets.py
有任何问题就退出码 1，CI 会直接拦下这次构建。
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "source"
POSTS = SOURCE / "_posts"

BANNED = [
    "赋能", "抓手", "闭环", "深入探讨", "综上所述", "值得注意的是",
    "在当今", "总而言之", "本文将", "至关重要", "不难看出", "显而易见",
    "让我们一起", "希望通过本文", "为读者提供", "助力", "全面解析",
    "持续精进", "作为 AI", "AI 生成",
]

errors = []
checked = 0

for p in sorted(POSTS.glob("*.md")):
    checked += 1
    text = p.read_text(encoding="utf-8")

    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not fm:
        errors.append(f"{p.name}: 缺少 front-matter")
    else:
        for key in ("title", "date", "categories", "tags", "lead"):
            if not re.search(r"^" + key + r":", fm.group(1), re.M):
                errors.append(f"{p.name}: front-matter 缺 {key}")

    for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://")):
            errors.append(f"{p.name}: 外链图片 {target}")
            continue
        if not (SOURCE / target.lstrip("/")).resolve().exists():
            errors.append(f"{p.name}: 图片文件不存在 {target}")

    # 恰好三个反引号才算围栏；四个反引号的展示块整段跳过
    inside = False
    outer = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.startswith("````"):
            outer = not outer
            continue
        if outer or not line.startswith("```"):
            continue
        if not inside:
            if line.strip() == "```":
                errors.append(f"{p.name}:{i}: 代码块未标语言")
            inside = True
        else:
            inside = False

    for word in BANNED:
        if word in text:
            errors.append(f"{p.name}: 出现禁用词「{word}」")

if errors:
    print(f"校验失败：{len(errors)} 个问题（共 {checked} 篇）")
    for e in errors:
        print("  - " + e)
    sys.exit(1)
print(f"校验通过：{checked} 篇文章，图片引用、front-matter、代码块语言和文案均干净")
