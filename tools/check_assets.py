#!/usr/bin/env python3
"""CI 质量门禁：图片引用、front-matter、代码块语言标注、禁用词，以及「口语化体检」。

本地跑法：  python3 tools/check_assets.py
有任何「硬伤」就退出码 1，CI 会直接拦下这次构建；「软指标」只提示不拦截。
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "source"
POSTS = SOURCE / "_posts"

# 硬禁用词：一旦出现直接拦截
BANNED = [
    "赋能", "抓手", "闭环", "深入探讨", "综上所述", "值得注意的是",
    "在当今", "总而言之", "本文将", "至关重要", "不难看出", "显而易见",
    "让我们一起", "希望通过本文", "为读者提供", "助力", "全面解析",
    "持续精进", "作为 AI", "AI 生成",
]

# 反 AI 味专项整治后仍可能复发的「复读机式」口头禅：出现即拦截
TICS = ["顺带一提", "下次再写", "等…再写", "等试完再写", "等…再说"]

# 模板化收尾小标题：正文不该再出现这类固定收尾
TEMPLATE_HEADINGS = re.compile(r"^##\s+(还没解决的|下次再写|总结与展望|结语|总结)\s*$", re.M)

# 软指标：只提示，不拦截
TS_OPEN = re.compile(r"^\d{1,2}\s*月\s*\d{1,2}\s*号\s*\d{2}:\d{2}")
LEAD_FORMULA = re.compile(r"(→|落到|降到).{0,30}(但|；|，其实|其实)")

errors = []
warnings = []
checked = 0
ts_open_count = 0
lead_formula_count = 0
last_conn_count = 0

for p in sorted(POSTS.glob("*.md")):
    checked += 1
    text = p.read_text(encoding="utf-8")

    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    body_after_fm = text
    if not fm:
        errors.append(f"{p.name}: 缺少 front-matter")
    else:
        for key in ("title", "date", "categories", "tags", "lead"):
            if not re.search(r"^" + key + r":", fm.group(1), re.M):
                errors.append(f"{p.name}: front-matter 缺 {key}")
        body_after_fm = text[fm.end():]

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

    # 口语化专项整治只对 2024 年起的文章生效；2021-2023 的老笔记是历史记录，保留原貌
    year = None
    if fm:
        dm = re.search(r"^date:\s*(\d{4})", fm.group(1), re.M)
        if dm:
            year = int(dm.group(1))
    if year is None or year >= 2024:
        for tic in TICS:
            if tic in text:
                errors.append(f"{p.name}: 出现复读机式口头禅「{tic}」")
        if TEMPLATE_HEADINGS.search(text):
            errors.append(f"{p.name}: 存在模板化收尾小标题（还没解决的 / 下次再写 / 总结…）")

    # ---- 软指标 ----
    plain = re.sub(r"```.*?```", "", body_after_fm, flags=re.S)
    first_para = ""
    for ln in plain.splitlines():
        s = ln.strip()
        if s and not s.startswith(("#", "|", ">", "-", "*", "!")):
            first_para = s
            break
    if TS_OPEN.match(first_para):
        ts_open_count += 1
    m = re.search(r"^lead:\s*(.+)$", fm.group(1), re.M) if fm else None
    if m and LEAD_FORMULA.search(m.group(1)):
        lead_formula_count += 1
    last_conn_count += len(re.findall(r"最后，", text)) + len(re.findall(r"最后我|最后还是|最后就", text))

if errors:
    print(f"校验失败：{len(errors)} 个硬伤（共 {checked} 篇）")
    for e in errors:
        print("  - " + e)
    sys.exit(1)

print(f"校验通过：{checked} 篇文章，图片引用、front-matter、代码块语言和文案均干净")
if ts_open_count:
    warnings.append(f"{ts_open_count}/{checked} 篇仍以「X 月 X 号 HH:MM」开场（建议打散）")
if lead_formula_count:
    warnings.append(f"{lead_formula_count}/{checked} 篇 lead 仍是「数字→数字 + 但/；」反差公式")
if last_conn_count:
    warnings.append(f"全库「最后」作连接词约 {last_conn_count} 处（仍偏多，可继续口语化）")
if warnings:
    print("软指标提示（不拦截）：")
    for w in warnings:
        print("  ~ " + w)
