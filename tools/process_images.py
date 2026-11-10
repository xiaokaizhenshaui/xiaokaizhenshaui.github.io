#!/usr/bin/env python3
"""处理站点视觉资产。

生成图右下角固定带模型水印，直接裁掉底部一条再等比缩放，比取背景块
覆盖更干净（不会留下色块或糊边），构图损失可以忽略。

用法:
    python3 tools/process_images.py [raw_dir]
默认 raw_dir = source/images/raw，输出写回 source/images。
"""
from pathlib import Path
from PIL import Image
import sys

ROOT = Path(__file__).resolve().parent.parent
RAW = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "source" / "images" / "raw"
OUT = ROOT / "source" / "images"

# (原图前缀, 输出文件, 目标尺寸, 格式, 质量, 是否中心方裁)
SPECS = [
    ("Anime_style_square_avatar", "avatar.webp", (512, 512), "WEBP", 88, True),
    ("Full_body_anime_illustration", "mascot.webp", (512, 710), "WEBP", 86, False),
    ("Wide_cinematic", "og-cover.jpg", (1200, 738), "JPEG", 85, False),
    ("Anime_background_illustration", "hero-city.webp", (1440, 886), "WEBP", 80, False),
]

CUT_BOTTOM = 0.912  # 水印区域约在 y > 0.92


def find_source(prefix):
    hits = sorted(RAW.glob(prefix + "*.png")) + sorted(RAW.glob(prefix + "*.jpg"))
    if not hits:
        raise SystemExit("找不到原图: " + prefix + "*  (" + str(RAW) + ")")
    return hits[-1]


def process(prefix, name, size, fmt, quality, square):
    src = find_source(prefix)
    im = Image.open(src).convert("RGB")

    w, h = im.size
    im = im.crop((0, 0, w, int(h * CUT_BOTTOM)))

    if square:
        side = min(im.size)
        left = (im.width - side) // 2
        top = (im.height - side) // 2
        im = im.crop((left, top, left + side, top + side))

    im = im.resize(size, Image.LANCZOS)
    dest = OUT / name
    if fmt == "WEBP":
        im.save(dest, "WEBP", quality=quality, method=6)
    else:
        im.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)

    print(f"{name:16s} {size[0]}x{size[1]:<5d} {dest.stat().st_size / 1024:7.1f} KB   <- {src.name}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for spec in SPECS:
        process(*spec)
        total += (OUT / spec[1]).stat().st_size
    print(f"合计 {total / 1024:.1f} KB")


if __name__ == "__main__":
    main()
