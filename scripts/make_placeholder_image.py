#!/usr/bin/env python3
"""
Generate a simple local placeholder image for article layout slots.

Examples:
    python scripts/make_placeholder_image.py --output output/demo/cover-wide.jpg --label "COVER 2.35:1" --size cover
    python scripts/make_placeholder_image.py --output output/demo/cover-square.jpg --label "COVER 1:1" --size square
    python scripts/make_placeholder_image.py --output output/demo/img-01.jpg --label "IMG 01" --size article
"""

import argparse
import json
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


def _draw_centered_text(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], text: str, font: ImageFont.ImageFont, fill: str) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x1, y1, x2, y2 = box
    draw.text((x1 + (x2 - x1 - tw) / 2, y1 + (y2 - y1 - th) / 2), text, fill=fill, font=font)


def _limited_labels(spec: dict, fallback: list[str]) -> list[str]:
    raw = spec.get("labels") if isinstance(spec, dict) else None
    labels = [str(item).strip() for item in raw if str(item).strip()] if isinstance(raw, list) else []
    return (labels or fallback)[:4]


def build_structured_visual(width: int, height: int, spec: dict) -> Image.Image:
    """Build a picture-first structured visual, not a text-card placeholder.

    The output uses diagrammatic shapes, arrows, panels, timelines and sparse CJK
    labels. It is deterministic so CI can verify the visual contract without an
    external image model.
    """
    spec = dict(spec or {})
    role = str(spec.get("visual_role") or "system_map")
    labels = _limited_labels(spec, ["上下文", "工具", "重试"])
    title = str(spec.get("scene") or spec.get("title") or "Token 成本结构")[:26]

    img = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(250 + (241 - 250) * t)
        g = int(252 + (246 - 252) * t)
        b = int(255 + (250 - 255) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    margin = max(34, width // 24)
    ink = "#111827"
    muted = "#64748b"
    line = "#cbd5e1"
    surface = "#ffffff"
    accent = "#76a987"
    blue = "#93c5fd"
    soft_green = "#dff3e5"
    soft_blue = "#e0f2fe"
    soft_gray = "#eef2f7"
    label_font = _load_font(max(20, width // 44))
    small_font = _load_font(max(16, width // 62))
    title_font = _load_font(max(28, width // 34))

    # Header as a small caption, not a giant title card.
    draw.rounded_rectangle((margin, margin * 0.72, width - margin, margin * 1.65), radius=18, fill=surface, outline="#e2e8f0", width=2)
    draw.text((margin * 1.35, margin * 0.93), title, fill=ink, font=title_font)
    draw.rounded_rectangle((width - margin * 4.0, margin * 0.96, width - margin * 1.25, margin * 1.42), radius=14, fill=soft_green, outline="#b8dec1")
    _draw_centered_text(draw, (width - margin * 4.0, margin * 0.96, width - margin * 1.25, margin * 1.42), "烧 Token", small_font, "#27533a")

    canvas = (margin, margin * 2.05, width - margin, height - margin)
    draw.rounded_rectangle(canvas, radius=30, fill=surface, outline="#dbe4ee", width=2)
    x1, y1, x2, y2 = canvas

    def arrow(start: tuple[float, float], end: tuple[float, float], color: str = "#94a3b8") -> None:
        draw.line([start, end], fill=color, width=max(4, width // 260))
        ex, ey = end
        sx, sy = start
        if ex >= sx:
            pts = [(ex, ey), (ex - 16, ey - 10), (ex - 16, ey + 10)]
        else:
            pts = [(ex, ey), (ex + 16, ey - 10), (ex + 16, ey + 10)]
        draw.polygon(pts, fill=color)

    if role in {"flow_diagram", "system_map", "cover_scene"}:
        count = max(3, len(labels))
        step_w = (x2 - x1 - margin * 1.4) / count
        cy = y1 + (y2 - y1) * 0.42
        nodes = []
        for i in range(count):
            cx = x1 + margin * 0.7 + step_w * i + step_w / 2
            box = (cx - step_w * 0.35, cy - height * 0.11, cx + step_w * 0.35, cy + height * 0.11)
            fill = [soft_blue, soft_green, soft_gray, "#fef3c7"][i % 4]
            draw.rounded_rectangle(box, radius=24, fill=fill, outline=line, width=2)
            draw.ellipse((box[0] + 18, box[1] + 16, box[0] + 58, box[1] + 56), fill=surface, outline="#d1d5db")
            draw.arc((box[0] + 27, box[1] + 27, box[0] + 78, box[1] + 78), 205, 30, fill=accent, width=4)
            _draw_centered_text(draw, (box[0] + 10, box[1] + 60, box[2] - 10, box[3] - 16), labels[i % len(labels)], label_font, ink)
            nodes.append((box[2], cy, box[0], cy))
        for i in range(len(nodes) - 1):
            arrow((nodes[i][0] + 10, nodes[i][1]), (nodes[i + 1][2] - 10, nodes[i + 1][3]), blue)
        draw.rounded_rectangle((x1 + margin * 0.75, y2 - height * 0.16, x2 - margin * 0.75, y2 - height * 0.07), radius=18, fill="#f8fafc", outline="#e2e8f0")
        _draw_centered_text(draw, (x1 + margin * 0.75, y2 - height * 0.16, x2 - margin * 0.75, y2 - height * 0.07), "上下文 × 工具 × 重试 → 系统账", label_font, muted)
    elif role == "comparison":
        mid = (x1 + x2) / 2
        for i, (left, right) in enumerate([(x1 + margin * 0.6, mid - margin * 0.25), (mid + margin * 0.25, x2 - margin * 0.6)]):
            fill = soft_blue if i == 0 else soft_green
            draw.rounded_rectangle((left, y1 + margin * 0.75, right, y2 - margin * 0.85), radius=28, fill=fill, outline=line, width=2)
            for j in range(4):
                yy = y1 + margin * 1.3 + j * ((y2 - y1 - margin * 2.6) / 4)
                draw.rounded_rectangle((left + 38, yy, right - 38, yy + 18), radius=9, fill=surface, outline="#dbe4ee")
            _draw_centered_text(draw, (left + 18, y2 - margin * 1.55, right - 18, y2 - margin * 0.95), labels[i % len(labels)], label_font, ink)
        arrow((mid - margin * 0.12, (y1 + y2) / 2), (mid + margin * 0.12, (y1 + y2) / 2), blue)
    elif role == "checklist":
        rows = max(3, len(labels))
        row_h = (y2 - y1 - margin * 1.6) / rows
        for i in range(rows):
            yy = y1 + margin * 0.8 + i * row_h
            draw.rounded_rectangle((x1 + margin * 0.8, yy, x2 - margin * 0.8, yy + row_h * 0.62), radius=18, fill=[soft_blue, soft_green, soft_gray][i % 3], outline=line)
            draw.ellipse((x1 + margin * 1.05, yy + 18, x1 + margin * 1.05 + 34, yy + 52), fill=surface, outline=accent, width=3)
            draw.line([(x1 + margin * 1.05 + 8, yy + 36), (x1 + margin * 1.05 + 17, yy + 44), (x1 + margin * 1.05 + 29, yy + 27)], fill=accent, width=4)
            draw.text((x1 + margin * 1.65, yy + 18), labels[i % len(labels)], fill=ink, font=label_font)
    else:  # cost_structure
        cx, cy = (x1 + x2) / 2, y1 + (y2 - y1) * 0.48
        radii = [height * 0.23, height * 0.17, height * 0.11]
        for i, radius in enumerate(radii):
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=[blue, accent, "#f59e0b"][i], width=max(8, width // 110))
        for i, label in enumerate(labels[:4]):
            angle_y = cy - height * 0.24 + i * height * 0.15
            draw.rounded_rectangle((x2 - margin * 4.4, angle_y, x2 - margin * 1.05, angle_y + 48), radius=16, fill=[soft_blue, soft_green, soft_gray, "#fef3c7"][i], outline=line)
            _draw_centered_text(draw, (x2 - margin * 4.4, angle_y, x2 - margin * 1.05, angle_y + 48), label, small_font, ink)
            arrow((cx + radii[1], cy), (x2 - margin * 4.4, angle_y + 24), "#94a3b8")

    return img.filter(ImageFilter.SMOOTH)


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
    parser.add_argument(
        "--visual-spec",
        default=None,
        help="Optional JSON file with picture-first visual spec",
    )
    args = parser.parse_args()

    width, height = SIZE_PRESETS[args.size]
    if args.visual_spec:
        spec = json.loads(Path(args.visual_spec).read_text(encoding="utf-8"))
        spec.setdefault("title", args.label)
        img = build_structured_visual(width, height, spec)
    else:
        img = build_placeholder(width, height, args.label, args.subtitle)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, quality=92)
    print(output)


if __name__ == "__main__":
    main()
