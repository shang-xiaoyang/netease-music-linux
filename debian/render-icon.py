#!/usr/bin/env python3
"""画一张不含官方标志的占位图标：圆角方块加音符。

传入一个文件时只画这一张。传入目录时按面板常用尺寸各画一张。
"""

import os
import sys

from PIL import Image, ImageDraw


def _vector(size):
    """按目标尺寸画圆角红底音符，不从低分辨率源图缩小。"""
    scale = 8
    canvas = max(32, int(size) * scale)
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    radius = int(canvas * 7.2 / 32)
    pen.rounded_rectangle((0, 0, canvas - 1, canvas - 1), radius=radius, fill=(236, 65, 65, 255))
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
    return image.resize((int(size), int(size)), Image.Resampling.LANCZOS)


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
