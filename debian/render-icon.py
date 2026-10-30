#!/usr/bin/env python3
"""画一张不含官方标志的占位图标：圆角方块加音符。

传入一个文件时只画这一张。传入目录时按面板常用尺寸各画一张。
"""

import os
import sys

from PIL import Image, ImageDraw


def _lanczos():
    # Pillow 9.1 才有 Image.Resampling。麒麟自带的 7.0 只有 Image.LANCZOS。
    resampling = getattr(Image, "Resampling", None)
    if resampling is not None:
        return resampling.LANCZOS
    return Image.LANCZOS


def _rounded_rectangle(pen, box, radius, fill):
    # Pillow 8.2 才有 rounded_rectangle。旧版用矩形加四个扇形拼出圆角。
    if hasattr(pen, "rounded_rectangle"):
        pen.rounded_rectangle(box, radius=radius, fill=fill)
        return
    x0, y0, x1, y1 = [int(value) for value in box]
    corner = int(radius)
    if corner <= 0:
        pen.rectangle((x0, y0, x1, y1), fill=fill)
        return
    pen.rectangle((x0 + corner, y0, x1 - corner, y1), fill=fill)
    pen.rectangle((x0, y0 + corner, x1, y1 - corner), fill=fill)
    pen.pieslice((x0, y0, x0 + 2 * corner, y0 + 2 * corner), 180, 270, fill=fill)
    pen.pieslice((x1 - 2 * corner, y0, x1, y0 + 2 * corner), 270, 360, fill=fill)
    pen.pieslice((x0, y1 - 2 * corner, x0 + 2 * corner, y1), 90, 180, fill=fill)
    pen.pieslice((x1 - 2 * corner, y1 - 2 * corner, x1, y1), 0, 90, fill=fill)


def _vector(size):
    """按目标尺寸画圆角红底音符，不从低分辨率源图缩小。"""
    scale = 8
    canvas = max(32, int(size) * scale)
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    radius = int(canvas * 7.2 / 32)
    _rounded_rectangle(pen, (0, 0, canvas - 1, canvas - 1), radius, (236, 65, 65, 255))
    unit = canvas / 32.0
    head = (
        int((16.0 - 4.15) * unit),
        int((17.6 - 4.15 * 0.78) * unit),
        int((16.0 + 4.15) * unit),
        int((17.6 + 4.15 * 0.78) * unit),
    )
    pen.ellipse(head, fill=(255, 255, 255, 255))
    stem = max(2, int(1.85 * unit))
    pen.rectangle(
        (
            int(19.55 * unit) - stem // 2,
            int(6.55 * unit),
            int(19.55 * unit) + stem // 2,
            int(16.2 * unit),
        ),
        fill=(255, 255, 255, 255),
    )
    pen.polygon(
        [
            (int(19.55 * unit), int(7.15 * unit)),
            (int(25.35 * unit), int(9.55 * unit)),
            (int(25.35 * unit), int(11.35 * unit)),
            (int(19.55 * unit), int(8.95 * unit)),
        ],
        fill=(255, 255, 255, 255),
    )
    return image.resize((int(size), int(size)), _lanczos())


def draw(size):
    # 源图只有 256px、三色硬边，再缩小会发虚。各尺寸都按矢量重画。
    return _vector(size)


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else "icon.png"
    if dest.endswith("/") or (not dest.endswith(".png")):
        import os
        os.makedirs(dest, exist_ok=True)
        for size in (16, 22, 24, 32, 48, 64, 128, 256, 512):
            draw(size).save(f"{dest.rstrip('/')}/{size}.png")
        return
    draw(256).save(dest)


if __name__ == "__main__":
    main()
