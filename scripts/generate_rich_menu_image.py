"""生成 Rich Menu 背景圖片（2500 x 422 px）。

Usage:
    python scripts/generate_rich_menu_image.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

WIDTH = 2500
HEIGHT = 422
HALF = WIDTH // 2

# 色彩
BG_LEFT = "#4b5563"
BG_RIGHT = "#6b7280"
DIVIDER_COLOR = "#9ca3af"
TEXT_COLOR = "#ffffff"
SUBTEXT_COLOR = "#d1d5db"


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """載入支援中文的字型。bold=True 時使用較粗的變體。"""
    # Noto Sans TC VF 支援 axis variation (wght)
    vf_path = "C:/Windows/Fonts/NotoSansTC-VF.ttf"
    if os.path.exists(vf_path):
        font = ImageFont.truetype(vf_path, size)
        # wght: 100(Thin) ~ 900(Black), 700=Bold
        weight = 700 if bold else 500
        font.set_variation_by_axes([weight])
        return font
    fallback = [
        "C:/Windows/Fonts/msjhbd.ttc" if bold else "C:/Windows/Fonts/msjh.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in fallback:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _load_emoji_font(size: int) -> ImageFont.FreeTypeFont | None:
    """載入 emoji 字型。"""
    path = "C:/Windows/Fonts/seguiemj.ttf"
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return None


def main() -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)

    # 左右背景色
    draw.rectangle([(0, 0), (HALF, HEIGHT)], fill=BG_LEFT)
    draw.rectangle([(HALF, 0), (WIDTH, HEIGHT)], fill=BG_RIGHT)

    # 中間分隔線
    draw.line([(HALF, 20), (HALF, HEIGHT - 20)], fill=DIVIDER_COLOR, width=3)

    font_label = _load_font(72, bold=True)
    font_sub = _load_font(36)
    font_emoji = _load_emoji_font(64)

    # 左邊：重新開始
    _draw_button(draw, 0, HALF, "\U0001f504", "重新開始", "清除資料重來",
                 font_emoji, font_label, font_sub)

    # 右邊：使用說明
    _draw_button(draw, HALF, WIDTH, "\U0001f4d6", "使用說明", "查看操作步驟",
                 font_emoji, font_label, font_sub)

    out_path = os.path.join(os.path.dirname(__file__), "rich_menu.png")
    img.save(out_path, "PNG")
    print(f"Done: {out_path}")


def _draw_button(
    draw: ImageDraw.ImageDraw,
    x1: int,
    x2: int,
    emoji: str,
    label: str,
    subtitle: str,
    font_emoji: ImageFont.FreeTypeFont | None,
    font_label: ImageFont.FreeTypeFont,
    font_sub: ImageFont.FreeTypeFont,
) -> None:
    cx = (x1 + x2) // 2

    # emoji + 文字分開繪製
    label_bbox = draw.textbbox((0, 0), label, font=font_label)
    label_w = label_bbox[2] - label_bbox[0]

    if font_emoji:
        emoji_bbox = draw.textbbox((0, 0), emoji, font=font_emoji)
        emoji_w = emoji_bbox[2] - emoji_bbox[0]
        gap = 20
        total_w = emoji_w + gap + label_w
        start_x = cx - total_w // 2
        y = HEIGHT // 2 - 70

        # 畫 emoji（微調 y 對齊）
        draw.text((start_x, y - 4), emoji, font=font_emoji, embedded_color=True)
        # 畫文字
        draw.text((start_x + emoji_w + gap, y), label, fill=TEXT_COLOR, font=font_label)
    else:
        # fallback：沒有 emoji 字型就只畫文字
        draw.text((cx - label_w // 2, HEIGHT // 2 - 70), label, fill=TEXT_COLOR, font=font_label)

    # 副標籤
    sub_bbox = draw.textbbox((0, 0), subtitle, font=font_sub)
    sub_w = sub_bbox[2] - sub_bbox[0]
    draw.text((cx - sub_w // 2, HEIGHT // 2 + 30), subtitle, fill=SUBTEXT_COLOR, font=font_sub)


if __name__ == "__main__":
    main()
