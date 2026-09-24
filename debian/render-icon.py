#!/usr/bin/env python3
"""画一张不含官方标志的占位图标：圆角方块加音符。"""

import sys

from PIL import Image, ImageDraw


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else "icon.png"
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = 16
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=48,
        fill=(236, 65, 65, 255),
    )
    # 音符头和符杆，用几何图形，不临摹官方唱片标志。
    head = (96, 132, 156, 176)
    draw.ellipse(head, fill=(255, 255, 255, 255))
    draw.rectangle((140, 64, 156, 150), fill=(255, 255, 255, 255))
    draw.polygon([(156, 64), (196, 84), (196, 100), (156, 80)], fill=(255, 255, 255, 255))
    image.save(dest)


if __name__ == "__main__":
    main()
