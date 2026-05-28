#!/usr/bin/env python3
"""
Generate a simple local placeholder image for article layout slots.

Examples:
    python scripts/make_placeholder_image.py --output output/demo/cover-wide.jpg --label "COVER 2.35:1" --size cover
    python scripts/make_placeholder_image.py --output output/demo/cover-square.jpg --label "COVER 1:1" --size square
    python scripts/make_placeholder_image.py --output output/demo/img-01.jpg --label "IMG 01" --size article
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


SIZE_PRESETS = {
    "cover": (900, 383),
    "article": (1280, 720),
    "square": (1024, 1024),
}


def _load_font(size: int):
    candidates = [
        # macOS CJK fonts first. The previous Latin-only list rendered Chinese as
        # tofu/garbled boxes in WeChat cover/article images.
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        # Linux common CJK fonts.
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        # Windows CJK fonts.
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        # Latin fallbacks only after CJK fonts.
        "arial.ttf",
        "segoeui.ttf",
        "calibri.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
    ]
    for candidate in candidates:
        try:
            path = Path(candidate)
            if path.is_absolute() and not path.exists():
                continue
            font = ImageFont.truetype(candidate, size=size)
            setattr(font, "_selected_font_path", candidate)
            return font
        except OSError:
            continue
    font = ImageFont.load_default()
    setattr(font, "_selected_font_path", "PIL_DEFAULT_FONT")
    return font


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int):
    for size in range(84, 17, -4):
        font = _load_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
    return _load_font(18)


def build_placeholder(width: int, height: int, label: str, subtitle: str) -> Image.Image:
    img = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(img)

    # Clean Token Burner visual direction: white/cool-gray canvas with restrained
    # low-saturation accents. Avoid dark neon/cyberpunk blue placeholders.
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(248 + (241 - 248) * t)
        g = int(250 + (245 - 250) * t)
        b = int(252 + (249 - 252) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    margin = max(28, width // 26)
    card = (margin, margin, width - margin, height - margin)
    draw.rounded_rectangle(card, radius=max(18, width // 46), fill="#ffffff", outline="#d9e2ec", width=max(2, width // 420))

    accent = "#8abf8f"
    muted_blue = "#dbeafe"
    draw.rounded_rectangle(
        (margin * 1.45, margin * 1.55, width - margin * 1.45, height - margin * 1.55),
        radius=max(16, width // 58),
        fill="#f9fbfd",
        outline="#e5edf5",
        width=max(1, width // 520),
    )
    draw.rectangle((margin * 1.45, height - margin * 1.8, width - margin * 1.45, height - margin * 1.8 + max(7, height // 64)), fill=accent)
    draw.rounded_rectangle((margin * 1.45, margin * 1.2, margin * 1.45 + width * 0.16, margin * 1.2 + max(8, height // 38)), radius=8, fill=muted_blue)

    label_font = _fit_text(draw, label, int(width * 0.62))
    subtitle_font = _load_font(max(18, width // 42))

    label_bbox = draw.textbbox((0, 0), label, font=label_font)
    label_w = label_bbox[2] - label_bbox[0]
    label_h = label_bbox[3] - label_bbox[1]
    label_x = (width - label_w) / 2
    label_y = height * 0.42 - label_h / 2
    draw.text((label_x, label_y), label, fill="#111827", font=label_font)

    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    subtitle_w = subtitle_bbox[2] - subtitle_bbox[0]
    subtitle_x = (width - subtitle_w) / 2
    subtitle_y = label_y + label_h + max(14, height // 36)
    draw.text((subtitle_x, subtitle_y), subtitle, fill="#4b5563", font=subtitle_font)

    return img.filter(ImageFilter.SMOOTH)


def main():
    parser = argparse.ArgumentParser(description="Create a placeholder image for article layout slots")
    parser.add_argument("--output", required=True, help="Output image path")
    parser.add_argument("--label", required=True, help="Main label, e.g. COVER or IMG 01")
    parser.add_argument(
        "--size",
        choices=sorted(SIZE_PRESETS.keys()),
        default="article",
        help="Image preset size",
    )
    parser.add_argument(
        "--subtitle",
        default="replace with final image",
        help="Small helper text rendered below the label",
    )
    args = parser.parse_args()

    width, height = SIZE_PRESETS[args.size]
    img = build_placeholder(width, height, args.label, args.subtitle)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, quality=92)
    print(output)


if __name__ == "__main__":
    main()
