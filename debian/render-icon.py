#!/usr/bin/env python3
"""画一张不含官方标志的占位图标：圆角方块加音符。

传入一个文件时只画这一张。传入目录时按面板常用尺寸各画一张。
"""

import sys

from PIL import Image, ImageDraw


def draw(size):
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(1, size // 16)
    radius = max(2, size * 3 // 16)
    draw.rounded_rectangle(
        (margin, margin, size - margin - 1, size - margin - 1),
        radius=radius,
        fill=(236, 65, 65, 255),
    )
    # 音符头、符杆和符尾都按尺寸缩放，不临摹官方唱片标志。
    head = (
        int(size * 0.34),
        int(size * 0.50),
        int(size * 0.62),
        int(size * 0.70),
    )
    draw.ellipse(head, fill=(255, 255, 255, 255))
    stem = max(1, size // 18)
    draw.rectangle(
        (int(size * 0.62) - stem, int(size * 0.24), int(size * 0.62), int(size * 0.58)),
        fill=(255, 255, 255, 255),
    )
    draw.polygon(
        [
            (int(size * 0.62), int(size * 0.24)),
            (int(size * 0.78), int(size * 0.32)),
            (int(size * 0.78), int(size * 0.40)),
            (int(size * 0.62), int(size * 0.32)),
        ],
        fill=(255, 255, 255, 255),
    )
    return image


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
