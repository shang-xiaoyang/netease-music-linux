#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""网易云音乐 Linux 原生播放器。

浅色主界面按官方客户端的结构排：左侧导航、推荐卡片、歌单封面、底部播放条。
关闭窗口后留在右下角托盘，右键可以打开或退出。
"""

import hashlib
import io
import json
import os
import re
import sys
import subprocess
import threading
import time
import urllib.request

import cairo

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gst", "1.0")

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gst, Gtk, Pango

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except (ValueError, ImportError):
    AppIndicator = None

import netease_api as api

Gst.init(None)

APP_ID = "io.netease-music-linux"
DATA_DIR = os.path.join(GLib.get_user_data_dir(), "netease-cloud-music")
COOKIE_PATH = os.path.join(DATA_DIR, "cookie")
QUALITY_PATH = os.path.join(DATA_DIR, "quality")
VOLUME_PATH = os.path.join(DATA_DIR, "volume")
WINDOW_PATH = os.path.join(DATA_DIR, "window.json")
LYRIC_PATH = os.path.join(DATA_DIR, "desk-lyric.json")
LYRIC_POS_PATH = os.path.join(DATA_DIR, "desk-lyric-pos.json")
LYRIC_STATE_PATH = os.path.join(DATA_DIR, "desk-lyric-state.json")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
RECENT_PATH = os.path.join(DATA_DIR, "recent-playlists.json")
MODE_PATH = os.path.join(DATA_DIR, "play-mode")
COVER_DIR = os.path.join(DATA_DIR, "covers")
RED = "#EC4141"
def _icon_path():
    """任务栏和托盘都只用随程序打包的图标，不读用户主题或旧缓存。"""
    root = os.path.dirname(os.path.abspath(__file__))
    for name in ("icon.png", "netease-music-linux.png"):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    return ""


ICON = _icon_path()

CSS = f"""
window {{
    background: #F5F5F7;
    color: #222;
    font-family: "Noto Sans CJK SC";
}}
.side {{
    background: #F4F4F6;
    border-right: 1px solid #E6E6EA;
}}
.brand {{
    font-size: 14px;
    font-weight: 700;
    color: #222;
}}
.side-row {{
    border-radius: 6px;
    margin: 0 8px;
    min-height: 30px;
    padding: 0 8px;
    color: #333;
    background: transparent;
}}
.side-row image {{
    color: #8A8A90;
}}
.side-row label {{
    color: #333;
    font-size: 13px;
}}
.side-row:hover {{
    background: #D6E8FA;
}}
.side-row:hover image,
.side-row:hover label {{
    color: #1F4E79;
}}
.side-row.current,
.side-row.current image,
.side-row.current label {{
    background: {RED};
    color: white;
}}
.section {{
    color: #9A9AA0;
    font-size: 11px;
    padding: 12px 16px 2px 16px;
}}
.page {{
    background: #F5F5F7;
}}
.card {{
    background: #FFFFFF;
    border-radius: 10px;
    border: 1px solid #EEEEF0;
}}
.card-title {{
    color: white;
    font-weight: 700;
    font-size: 16px;
}}
.card-sub {{
    color: alpha(white, 0.88);
    font-size: 11px;
}}
button.feature-card {{
    padding: 0;
    border: none;
    background: transparent;
    box-shadow: none;
}}
button.feature-card:hover {{
    background: transparent;
}}
.cover-name {{
    color: #222;
    font-size: 12px;
}}
.cover-meta {{
    color: #8E8E93;
    font-size: 11px;
}}
.heading {{
    color: #222;
    font-size: 18px;
    font-weight: 700;
}}
.song-list, .song-list treeview {{
    background: #FFFFFF;
    color: #222;
    font-size: 9px;
}}
.song-list treeview:selected {{
    background: #FDECEC;
    color: #222;
}}
.song-list treeview header button {{
    background: #FFFFFF;
    color: #8E8E93;
    font-size: 9px;
    border: none;
    border-bottom: 1px solid #F0F0F2;
    padding: 4px 6px;
}}
.queue-list, .queue-list treeview {{
    background: #FFFFFF;
    color: #222;
    font-size: 12px;
}}
.queue-list treeview:selected {{
    background: #FDECEC;
    color: #222;
}}
.queue-list treeview header button {{
    background: #FFFFFF;
    color: #A0A0A6;
    font-size: 11px;
    font-weight: 400;
    border: none;
    border-bottom: 1px solid #F0F0F2;
    padding: 2px 4px;
    min-height: 22px;
}}
.col-index {{
    color: #B0B0B6;
    font-size: 12px;
}}
.col-title {{
    color: #222;
    font-size: 13px;
}}
.col-vip {{
    color: {RED};
    font-size: 10px;
    font-weight: 700;
}}
.col-sub {{
    color: #8E8E93;
    font-size: 12px;
}}
.col-meta {{
    color: #8E8E93;
    font-size: 12px;
}}
.player-bar {{
    background: @theme_bg_color;
    color: @theme_fg_color;
    border-top: 1px solid @borders;
    padding: 0;
}}
.progress-row {{
    min-height: 3px;
    padding: 0;
    margin: 0;
}}
.progress-row scale {{
    min-width: 1px;
    min-height: 12px;
    margin: -5px 0 0;
    padding: 0;
}}
.progress-row scale trough {{
    min-height: 3px;
    border-radius: 0;
    background: #F0D5D8;
}}
.progress-row scale highlight {{
    border-radius: 0;
    background: {RED};
}}
.progress-row scale slider {{
    min-width: 12px;
    min-height: 12px;
    margin: -5px 0;
    border-radius: 8px;
    background: #FFFFFF;
    border: 2px solid {RED};
}}
.player-controls {{
    padding: 2px 12px 4px;
}}
.desk-lyric-plate {{
    background: rgba(232, 232, 234, 0.78);
    border-radius: 8px;
}}
.desk-lyric-close {{
    color: #F3A3A3;
    background: rgba(255, 255, 255, 0.55);
    border-radius: 11px;
    font-size: 15px;
    font-weight: 700;
    min-width: 21px;
    min-height: 21px;
    padding: 0;
}}
.time-pill {{
    background: #FFFFFF;
    color: #333333;
    border-radius: 12px;
    padding: 3px 10px;
    font-size: 12px;
}}
.collect-popover {{
    background: #FFFFFF;
    border-radius: 12px;
}}
.collect-title {{
    font-size: 13px;
    font-weight: 700;
    color: #2C2C34;
}}
.collect-tab {{
    color: #8E8E93;
    font-size: 12px;
}}
.collect-tab.active {{
    color: #2C2C34;
    font-weight: 600;
}}
.collect-name {{
    color: #2C2C34;
    font-size: 13px;
}}
.collect-count {{
    color: #8E8E93;
    font-size: 11px;
}}
.collect-plus {{
    background: #F2F2F4;
    color: #8E8E93;
    border-radius: 6px;
    font-size: 18px;
    font-weight: 500;
}}
.comment-page {{
    background: #FFFFFF;
}}
.comment-card {{
    background: #FFFFFF;
    border-bottom: 1px solid #F0F0F2;
    padding: 12px 16px;
}}
.comment-name {{
    color: #507DAF;
    font-size: 13px;
    font-weight: 600;
}}
.comment-body {{
    color: #333333;
    font-size: 14px;
}}
.song-title {{
    color: #222;
    font-size: 13px;
    font-weight: 600;
}}
.dim {{
    color: #8E8E93;
    font-size: 12px;
}}
button.play-main {{
    border-radius: 17px;
    min-width: 34px;
    min-height: 34px;
    padding: 0;
    background: {RED};
    color: #FFFFFF;
    border: none;
    box-shadow: none;
}}
button.play-main:hover {{
    background: #D93636;
    color: #FFFFFF;
}}
button.transport {{
    border-radius: 12px;
    min-width: 24px;
    min-height: 24px;
    padding: 0;
    background: transparent;
    color: @theme_fg_color;
    border: none;
    box-shadow: none;
}}
button.transport:hover,
button.transport:hover image {{
    background: alpha({RED}, 0.16);
    color: {RED};
}}
button.icon-btn {{
    border-radius: 6px;
    min-width: 24px;
    min-height: 24px;
    padding: 2px;
    background: transparent;
    color: @theme_fg_color;
    border: none;
    box-shadow: none;
}}
button.icon-btn:hover {{
    background: alpha(@theme_fg_color, 0.08);
    color: {RED};
}}
button.icon-btn.liked {{
    color: {RED};
}}
button.flat {{
    border: none;
    background: transparent;
    color: @theme_fg_color;
    box-shadow: none;
}}
button.quality-btn {{
    background: #F2F2F4;
    color: #333333;
    border: none;
    border-radius: 10px;
    padding: 0 8px;
    min-height: 22px;
    min-width: 52px;
    font-size: 11px;
    box-shadow: none;
}}
button.quality-btn:hover {{
    background: alpha({RED}, 0.12);
    color: {RED};
}}
button.quality-btn label {{
    color: inherit;
    font-size: 11px;
}}
button.cover-btn {{
    padding: 0;
    border: none;
    background: transparent;
    border-radius: 22px;
}}
.queue-overlay {{
    background: #FFFFFF;
    border: 1px solid #E2E2E6;
    border-radius: 10px;
}}
.queue-head {{
    font-size: 13px;
    font-weight: 600;
    color: #222;
}}
.lyric-page {{
    background: #F7F7F8;
}}
.lyric-page textview, .lyric-page text {{
    background: transparent;
    color: alpha(@theme_fg_color, 0.32);
    font-size: 16px;
}}
.lyric-song {{
    color: #222;
    font-size: 22px;
    font-weight: 700;
}}
.lyric-artist {{
    color: alpha(@theme_fg_color, 0.55);
    font-size: 13px;
}}
.detail-card {{
    background: #FFFFFF;
    border: 1px solid #ECECEE;
    border-radius: 12px;
    padding: 16px;
}}
.detail-name {{
    font-size: 22px;
    font-weight: 700;
    color: #222;
}}
.detail-meta {{
    color: alpha(@theme_fg_color, 0.62);
    font-size: 13px;
}}
.section-label {{
    font-size: 15px;
    font-weight: 700;
    color: #222;
}}
.album-chip {{
    background: #FFFFFF;
    border: 1px solid #ECECEE;
    border-radius: 10px;
    padding: 8px;
}}
.album-chip:hover {{
    border-color: alpha({RED}, 0.45);
}}
.bar-title {{
    color: @theme_fg_color;
    font-size: 13px;
    font-weight: 600;
}}
.bar-artist {{
    color: alpha(@theme_fg_color, 0.55);
    font-size: 12px;
}}
button.bar-link {{
    border: none;
    background: transparent;
    color: alpha(@theme_fg_color, 0.55);
    font-size: 12px;
    padding: 0;
    margin: 0;
    box-shadow: none;
}}
button.bar-link:hover {{
    color: {RED};
}}
button.back-btn {{
    min-width: 28px;
    min-height: 28px;
    padding: 2px;
    border: none;
    border-radius: 14px;
    background: alpha(@theme_fg_color, 0.06);
    color: @theme_fg_color;
    box-shadow: none;
}}
button.back-btn:hover {{
    background: alpha({RED}, 0.14);
    color: {RED};
}}
.lyric-page button.back-btn {{
    background: alpha(@theme_fg_color, 0.06);
    color: @theme_fg_color;
}}
.lyric-page button.back-btn:hover {{
    background: alpha({RED}, 0.14);
    color: {RED};
}}
button.text-btn {{
    border: none;
    background: transparent;
    color: alpha(@theme_fg_color, 0.62);
    padding: 2px 8px;
    box-shadow: none;
}}
button.text-btn:hover {{
    color: {RED};
}}
button.text-btn.on {{
    color: {RED};
    font-weight: 700;
}}
entry {{
    border-radius: 16px;
    min-height: 32px;
}}
scale trough {{
    min-height: 3px;
    background: #E6E6E8;
}}
scale highlight {{
    background: {RED};
}}
menu, .menu {{
    background: #FFFFFF;
    color: #222222;
}}
menu menuitem, .menu menuitem, menuitem, menuitem label {{
    color: #222222;
    background: #FFFFFF;
    font-size: 13px;
}}
menu menuitem:hover, .menu menuitem:hover, menuitem:hover, menuitem:hover label {{
    background: #F3F3F5;
    color: #222222;
}}
menu menuitem:checked, menuitem:checked label {{
    color: {RED};
    background: #FFFFFF;
}}
"""

CARD_COLORS = ("#3B6CFF", "#7A4DFF", "#2F8CFF", "#E23B3B", "#F08A2A")


def _tint_pixbuf(pixbuf, red, green, blue):
    """把单色图标染成指定颜色，保留原来的透明度。"""
    tinted = pixbuf.copy()
    pixels = bytearray(tinted.get_pixels())
    channels = tinted.get_n_channels()
    rowstride = tinted.get_rowstride()
    width, height = tinted.get_width(), tinted.get_height()
    for y in range(height):
        row = y * rowstride
        for x in range(width):
            offset = row + x * channels
            alpha = pixels[offset + 3]
            if not alpha:
                continue
            pixels[offset] = int(red * 255)
            pixels[offset + 1] = int(green * 255)
            pixels[offset + 2] = int(blue * 255)
    return GdkPixbuf.Pixbuf.new_from_data(
        bytes(pixels),
        tinted.get_colorspace(),
        tinted.get_has_alpha(),
        tinted.get_bits_per_sample(),
        width,
        height,
        rowstride,
    )


def _pixbuf_from_surface(surface):
    data = io.BytesIO()
    surface.write_to_png(data)
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(data.getvalue())
    loader.close()
    return loader.get_pixbuf()


def _fixed_icon(draw, size=16):
    """固定逻辑像素。主题图标是 16px，自定义图再按倍率出就会比旁边大一倍。"""
    canvas = max(1, int(size))
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas, canvas)
    ctx = cairo.Context(surface)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_source_rgba(0.16, 0.16, 0.18, 1)
    draw(ctx, size)
    return _pixbuf_from_surface(surface)


def _screen_scale():
    """2 倍屏上 16 逻辑像素要画 32 物理像素。先缩到 16 再显示，主题图标不会糊，自绘图会糊。"""
    try:
        return max(1, int(round(Gdk.Screen.get_default().get_monitor_scale_factor(0))))
    except Exception:
        return 2


def _symbolic_pixbuf(draw, size=16):
    """按逻辑像素出图。GTK 的 set_pixel_size 压不住位图，按屏幕倍率画会被放大。"""
    scale = 1
    logical = max(1, int(size))
    canvas = logical * scale
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas, canvas)
    ctx = cairo.Context(surface)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_source_rgba(0.16, 0.16, 0.18, 1)
    ctx.scale(scale, scale)
    draw(ctx, logical)
    return _pixbuf_from_surface(surface)


def comment_icon(size=16):
    """气泡收在画布内。尾巴不能画到 16 之外，否则按钮里会被裁掉。"""
    def draw(ctx, size):
        ctx.set_line_width(1.15)
        ctx.set_source_rgba(0.16, 0.16, 0.18, 0.85)
        x, y, width, height, radius = 2.4, 2.6, 11.2, 7.2, 2.2
        ctx.new_sub_path()
        ctx.arc(x + width - radius, y + radius, radius, -1.5708, 0)
        ctx.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
        ctx.line_to(7.2, y + height)
        ctx.line_to(4.6, 14.2)
        ctx.line_to(5.6, y + height)
        ctx.arc(x + radius, y + height - radius, radius, 1.5708, 3.1416)
        ctx.arc(x + radius, y + radius, radius, 3.1416, 4.7124)
        ctx.close_path()
        ctx.stroke()

    return _symbolic_pixbuf(draw, size)


def heart_icon(size=16, filled=False):
    """爱心按评论、收藏同一光学尺寸画。SVG 几乎铺满 16 格，贴上去会显大。"""
    def draw(ctx, size):
        ctx.set_line_width(1.15)
        ctx.set_source_rgba(0.925, 0.255, 0.255, 1) if filled else ctx.set_source_rgba(0.16, 0.16, 0.18, 0.85)
        ctx.move_to(8.0, 12.7)
        ctx.curve_to(7.6, 12.35, 3.0, 9.15, 3.0, 6.35)
        ctx.curve_to(3.0, 4.55, 4.25, 3.45, 5.75, 3.45)
        ctx.curve_to(6.7, 3.45, 7.45, 4.0, 8.0, 4.9)
        ctx.curve_to(8.55, 4.0, 9.3, 3.45, 10.25, 3.45)
        ctx.curve_to(11.75, 3.45, 13.0, 4.55, 13.0, 6.35)
        ctx.curve_to(13.0, 9.15, 8.4, 12.35, 8.0, 12.7)
        ctx.close_path()
        if filled:
            ctx.fill()
        else:
            ctx.stroke()

    return _symbolic_pixbuf(draw, size)


def add_icon(size=16):
    """收藏：方框加号，外框和评论气泡同一留白。"""
    def draw(ctx, size):
        ctx.set_line_width(1.15)
        ctx.set_source_rgba(0.16, 0.16, 0.18, 0.85)
        radius = 1.5
        x, y, width = 3.1, 3.1, 9.8
        ctx.new_sub_path()
        ctx.arc(x + width - radius, y + radius, radius, -1.5708, 0)
        ctx.arc(x + width - radius, y + width - radius, radius, 0, 1.5708)
        ctx.arc(x + radius, y + width - radius, radius, 1.5708, 3.1416)
        ctx.arc(x + radius, y + radius, radius, 3.1416, 4.7124)
        ctx.close_path()
        ctx.stroke()
        ctx.move_to(8, 5.5)
        ctx.line_to(8, 10.5)
        ctx.move_to(5.5, 8)
        ctx.line_to(10.5, 8)
        ctx.stroke()

    return _symbolic_pixbuf(draw, size)


def more_icon(size=16):
    def draw(ctx, size):
        ctx.set_source_rgba(0.16, 0.16, 0.18, 0.85)
        for x in (3.3, 8.0, 12.7):
            ctx.arc(x, 8, 1.05, 0, 6.2832)
            ctx.fill()

    return _symbolic_pixbuf(draw, size)


def play_glyph(size=20, playing=False):
    """播放条上的三角和暂停条。按 16 像素图形等比放到目标尺寸，深色，白底上也能看见。"""
    def draw(ctx, size):
        ctx.set_source_rgba(0.12, 0.12, 0.14, 1)
        ctx.scale(size / 16.0, size / 16.0)
        if playing:
            ctx.rectangle(4.3, 3.2, 2.3, 9.6)
            ctx.rectangle(9.4, 3.2, 2.3, 9.6)
            ctx.fill()
            return
        ctx.move_to(5.2, 2.8)
        ctx.line_to(12.6, 8.0)
        ctx.line_to(5.2, 13.2)
        ctx.close_path()
        ctx.fill()

    return _symbolic_pixbuf(draw, size)


def note_icon(size=16):
    """侧栏榜单用的八分音符，形状跟应用图标一致，线宽跟其他侧栏图标一致。"""
    def draw(ctx, size):
        ctx.set_line_width(max(1.15, size / 14))
        scale = size / 16
        ctx.translate(0.35 * scale, 0.15 * scale)
        ctx.scale(scale, scale)
        ctx.arc(5.15, 11.55, 2.05, 0, 6.2832)
        ctx.move_to(7.2, 11.55)
        ctx.line_to(7.2, 3.15)
        ctx.line_to(12.55, 4.85)
        ctx.stroke()

    return _symbolic_pixbuf(draw, size)


def app_mark(size=28):
    """标题栏用矢量圆角红底音符。源图缩到 22px 会发虚，这里按目标尺寸重画。"""
    canvas = max(64, int(size) * 4)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas, canvas)
    ctx = cairo.Context(surface)
    ctx.scale(canvas / 32.0, canvas / 32.0)
    ctx.set_source_rgba(0.925, 0.255, 0.255, 1)
    radius = 7.2
    ctx.arc(radius, radius, radius, 3.1416, 4.7124)
    ctx.arc(32 - radius, radius, radius, 4.7124, 6.2832)
    ctx.arc(32 - radius, 32 - radius, radius, 0, 1.5708)
    ctx.arc(radius, 32 - radius, radius, 1.5708, 3.1416)
    ctx.close_path()
    ctx.fill()
    ctx.set_source_rgba(1, 1, 1, 1)
    ctx.save()
    ctx.translate(16.0, 17.6)
    ctx.scale(1, 0.78)
    ctx.arc(0, 0, 4.15, 0, 6.2832)
    ctx.restore()
    ctx.fill()
    ctx.set_line_width(1.85)
    ctx.set_line_cap(cairo.LINE_CAP_BUTT)
    ctx.move_to(19.55, 16.2)
    ctx.line_to(19.55, 6.55)
    ctx.stroke()
    ctx.move_to(19.55, 7.15)
    ctx.line_to(25.35, 9.55)
    ctx.line_to(25.35, 11.35)
    ctx.line_to(19.55, 8.95)
    ctx.close_path()
    ctx.fill()
    large = _pixbuf_from_surface(surface)
    return large.scale_simple(int(size), int(size), GdkPixbuf.InterpType.BILINEAR)


def fm_icon():
    """私人 FM 用字样，不用带斜杠的禁止图标。"""
    size = 16
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    ctx.select_font_face("Noto Sans CJK SC", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(7.2)
    ctx.set_source_rgba(0.42, 0.42, 0.45, 1)
    for text, y in (("F", 7.1), ("M", 14.2)):
        extents = ctx.text_extents(text)
        ctx.move_to((size - extents.width) / 2 - extents.x_bearing, y)
        ctx.show_text(text)
    data = io.BytesIO()
    surface.write_to_png(data)
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(data.getvalue())
    loader.close()
    return loader.get_pixbuf()


def fmt_time(ms):
    ms = max(0, int(ms or 0))
    seconds = ms // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def fmt_comment_time(ms):
    """评论时间按网易云的相对说法显示。"""
    stamp = int(ms or 0) / 1000
    if stamp <= 0:
        return ""
    delta = max(0, int(time.time() - stamp))
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{delta // 60}分钟前"
    if delta < 86400:
        return f"{delta // 3600}小时前"
    if delta < 86400 * 7:
        return f"{delta // 86400}天前"
    return time.strftime("%Y年%m月%d日", time.localtime(stamp))


def _https_media_url(url):
    """封面和音频只从网易云音乐的地址下载，拒绝本地路径和其他站点。"""
    parsed = urllib.parse.urlparse(str(url or ""))
    host = parsed.hostname or ""
    allowed = host == "music.163.com" or host.endswith(".music.163.com") or host.endswith(".126.net")
    if parsed.scheme not in ("http", "https") or not allowed:
        raise OSError("封面地址不在网易云音乐")
    return urllib.parse.urlunparse(parsed._replace(scheme="https"))


def cover_cache_path(url, size):
    """封面缓存在当前用户的隐藏目录里，文件名不随进程变化。"""
    os.makedirs(COVER_DIR, exist_ok=True)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return os.path.join(COVER_DIR, f"{digest}-{int(size)}.jpg")


def load_pixbuf(url, size, rounded=8, refresh=False):
    path = cover_cache_path(url, size)
    stale = refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) > 6 * 3600
    if stale or not os.path.exists(path) or os.path.getsize(path) < 32:
        safe = _https_media_url(url)
        parsed = urllib.parse.urlparse(safe)
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        query["param"] = f"{size * 2}y{size * 2}"
        req = urllib.request.Request(
            urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query))),
            headers={"User-Agent": api.UA, "Referer": "https://music.163.com/"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        if not data:
            raise OSError("封面为空")
        tmp = path + ".part"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, False)


class Player:
    def __init__(self, on_end, on_state=None):
        self.playbin = Gst.ElementFactory.make("playbin", "netease")
        self.on_end = on_end
        self.on_state = on_state
        self.cached_pos = 0
        self.cached_dur = 0
        self._querying = False
        self._clock_thread = None
        self._want = "stopped"
        self._started_at = 0.0
        self._anchor_pos = 0
        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

    def _emit_state(self):
        if self.on_state:
            GLib.idle_add(self.on_state, self._want)

    def _on_message(self, _bus, message):
        if message.type == Gst.MessageType.EOS:
            self._want = "stopped"
            self._emit_state()
            GLib.idle_add(self.on_end)
        elif message.type == Gst.MessageType.ERROR:
            self._want = "stopped"
            self._emit_state()
            err, _dbg = message.parse_error()
            GLib.idle_add(self.on_end, str(err))
        elif message.type == Gst.MessageType.ASYNC_DONE and self._want == "playing":
            self._started_at = time.time()
            self._emit_state()
        elif message.type == Gst.MessageType.STATE_CHANGED and message.src == self.playbin:
            _old, new, _pending = message.parse_state_changed()
            if new == Gst.State.PLAYING:
                self._want = "playing"
                self._started_at = time.time()
                self._emit_state()
            elif new == Gst.State.PAUSED and self._want == "playing":
                # 缓冲会经过暂停。只有用户暂停才改按钮，不把开播中的按钮打回播放。
                self._emit_state()

    def play(self, url):
        parsed = urllib.parse.urlparse(str(url or ""))
        host = parsed.hostname or ""
        remote = parsed.scheme == "https" and (
            host == "music.163.com" or host.endswith(".music.163.com") or host.endswith(".126.net")
        )
        local = parsed.scheme == "file" and os.path.isfile(urllib.request.url2pathname(parsed.path))
        if not remote and not local:
            raise OSError("播放地址不被允许")
        self.playbin.set_state(Gst.State.NULL)
        self.cached_pos = 0
        self.cached_dur = 0
        self._anchor_pos = 0
        self._started_at = time.time()
        self._want = "playing"
        self._emit_state()
        self.playbin.set_property("uri", url)
        self.playbin.set_property("volume", 1.0)
        self.playbin.set_state(Gst.State.PLAYING)

    def stop(self):
        self._want = "stopped"
        self.playbin.set_state(Gst.State.NULL)
        self._emit_state()

    def pause(self):
        self._want = "paused"
        self._anchor_pos = self.cached_pos
        self._started_at = 0
        self.playbin.set_state(Gst.State.PAUSED)
        self._emit_state()

    def resume(self):
        self._want = "playing"
        self._anchor_pos = self.cached_pos
        self._started_at = time.time()
        self.playbin.set_state(Gst.State.PLAYING)
        self._emit_state()

    def playing(self):
        return self._want == "playing"

    def paused(self):
        if self._want == "paused":
            return True
        _ok, state, _pending = self.playbin.get_state(0)
        return state == Gst.State.PAUSED

    def position_ms(self):
        # 界面线程只读缓存。管道查询会卡住界面，放到后台线程里做。
        if self._want == "playing" and self._started_at:
            guessed = self._anchor_pos + int((time.time() - self._started_at) * 1000)
            if guessed > self.cached_pos:
                self.cached_pos = guessed
        return self.cached_pos

    def duration_ms(self):
        return self.cached_dur

    def refresh_clock(self):
        # 一条后台线程轮询时钟。每拍新建线程会把空闲时的 CPU 抬起来。
        if self._clock_thread and self._clock_thread.is_alive():
            return
        self._querying = True

        def work():
            while self._want in ("playing", "paused"):
                pos = dur = 0
                try:
                    ok, value = self.playbin.query_position(Gst.Format.TIME)
                    if ok and value > 0:
                        pos = int(value / 1_000_000)
                    ok, value = self.playbin.query_duration(Gst.Format.TIME)
                    if ok:
                        dur = int(value / 1_000_000)
                except Exception:
                    pass
                GLib.idle_add(self._store_clock, pos, dur)
                time.sleep(0.4 if self._want == "playing" else 1.2)
            self._querying = False

        self._clock_thread = threading.Thread(target=work, daemon=True)
        self._clock_thread.start()

    def _seek_landed(self, pos):
        """暂停时查询仍会报跳转前的位置。没落到目标附近之前，不拿它覆盖点击位置。"""
        target = getattr(self, "_seek_target", None)
        if target is None:
            return True
        if time.time() - getattr(self, "_seek_stamp", 0) > 4:
            self._seek_target = None
            return True
        return abs(pos - target) < 1500

    def _store_clock(self, pos, dur):
        # 跳转清空管道时，位置会先报旧值或 0。没落到目标附近就继续显示点击的位置。
        if pos and self._seek_landed(pos):
            self.cached_pos = pos
            self._anchor_pos = pos
            self._started_at = time.time()
        if dur:
            self.cached_dur = dur
        return False

    def seek_ms(self, ms):
        target = int(max(0, ms))
        self.cached_pos = target
        self._seek_target = target
        self._seek_stamp = time.time()
        # 查询和跳转都不能在界面线程里等管道。暂停时尤其容易卡住，所以丢到后台。
        threading.Thread(target=self._seek_worker, args=(target,), daemon=True).start()

    def _seek_worker(self, target):
        try:
            _ok, state, _pending = self.playbin.get_state(500 * Gst.MSECOND)
            if state == Gst.State.NULL:
                return
            if state not in (Gst.State.PAUSED, Gst.State.PLAYING):
                self.playbin.set_state(Gst.State.PAUSED)
                self.playbin.get_state(500 * Gst.MSECOND)
            # 暂停时 KEY_UNIT 经常被合成器丢掉，滑块就会弹回原位。精确跳转能停在点击处。
            flags = Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE
            ok = self.playbin.seek_simple(Gst.Format.TIME, flags, int(target) * Gst.MSECOND)
            if not ok:
                self.playbin.seek_simple(
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    int(target) * Gst.MSECOND,
                )
        except Exception:
            return

    def set_volume(self, value):
        # 播放器增益保持 1。滑条改的是系统音量，不在软件里再乘一次。
        self.playbin.set_property("volume", 1.0)


class AppWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="网易云音乐")
        # 和启动器的 StartupWMClass 一致，任务栏才能配上同一张图标。
        self.set_wmclass(APP_ID, APP_ID)
        self.set_default_size(1080, 680)
        # 列表再长也只在窗口内部滚动。不锁住的话，专辑页会把窗口顶出屏幕。
        self.set_size_request(860, 560)
        self._restore_window()
        self._clamp_window()
        if ICON:
            try:
                self.set_icon_from_file(ICON)
            except GLib.Error:
                pass

        self.cookie = api.load_cookie(COOKIE_PATH)
        self.profile = None
        self.mine = []
        self.player = Player(self._on_track_end, self._on_player_state)
        # playing 是正在播放的列表，和左侧正在浏览的列表分开。
        # 只有双击另一份列表里的歌，才会换掉它。
        self.playing = []
        self.playing_title = "当前播放"
        self.playing_index = -1
        self.queue_overlay = None
        self.play_mode = self._load_mode()
        self.lyrics = []
        self.current_song = None
        self._resume_at = 0
        self._resume_used = False
        self.quality = self._load_quality()
        self._applied_quality = self.quality
        self._quality_options = [key for key, _name, _hint in api.QUALITIES]
        self.seeking = False
        self.lyric_open = False
        self.nav_buttons = []

        self._apply_css()
        self._build()
        self._build_tray()
        self.liked_ids = set()
        self.playlist_tracks = {}
        self.comment_offset = 0
        self.comment_song = None
        self.downloads = []
        self.download_worker = None
        self.local_index = {}
        self._cover_jobs = set()
        self._hotkeys = GlobalHotkeys(self._on_hotkey)
        if self._hotkeys.error:
            self._status("全局快捷键未生效：" + self._hotkeys.error)
        elif len(self._hotkeys.ready) == 3:
            self._status("快捷键已生效：Ctrl+Alt+P 播放或暂停，Ctrl+Alt+Home 上一首，Ctrl+Alt+End 下一首")
        self.connect("delete-event", self._on_close)
        self.connect("key-press-event", self._on_key)
        self.connect("button-press-event", self._on_window_press)
        self.connect("configure-event", self._remember_window)
        GLib.timeout_add(400, self._tick)
        self.show_all()
        self._clamp_window()
        if self._desk_lyric_wanted():
            self._launch_desk_lyric()
        self.stack.set_visible_child_name("home")
        self._status("正在加载推荐…")
        self._restore_state()
        self._bg(self._load_home)
        GLib.timeout_add_seconds(15, self._autosave)

    def _apply_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _load_quality(self):
        if os.path.exists(QUALITY_PATH):
            value = open(QUALITY_PATH, encoding="utf-8").read().strip()
            if value in api.QUALITY_LABEL:
                return value
        return "jymaster" if False else "jyeffect"

    def _save_quality(self, key):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(QUALITY_PATH, "w", encoding="utf-8") as handle:
            handle.write(key)

    def _build(self):
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("网易云音乐")
        self.set_titlebar(header)
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mark = Gtk.Image()
        mark.set_from_pixbuf(app_mark(32))
        mark.set_pixel_size(22)
        name = Gtk.Label(label="网易云音乐（非官方）", xalign=0)
        name.get_style_context().add_class("brand")
        brand.pack_start(mark, False, False, 0)
        brand.pack_start(name, False, False, 0)
        header.pack_start(brand)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("搜索歌曲、歌手")
        self.search.set_width_chars(28)
        self.search.connect("activate", self._on_search)
        header.set_custom_title(self.search)
        self.account_btn = Gtk.MenuButton(label="登录")
        self.account_btn.get_style_context().add_class("flat")
        self.account_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._rebuild_account_menu()
        header.pack_end(self.account_btn)

        self.side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.side.get_style_context().add_class("side")
        self.side.set_size_request(196, -1)
        self.nav_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.nav_box.set_margin_top(8)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.nav_box)
        self.side.pack_start(scroll, True, True, 0)

        self.home_page = Gtk.ScrolledWindow()
        self.home_page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.home_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.home_box.set_margin_start(22)
        self.home_box.set_margin_end(22)
        self.home_box.set_margin_top(16)
        self.home_box.set_margin_bottom(16)
        self.home_page.add(self.home_box)

        self.heading = Gtk.Label(label="", xalign=0)
        self.heading.get_style_context().add_class("heading")
        self.heading.set_margin_start(4)
        self.heading.set_margin_top(8)
        list_back = self._icon_button("go-previous-symbolic", self._back_from_list, "back-btn")
        list_back.set_tooltip_text("返回")
        list_back.set_margin_start(8)
        list_back.set_margin_top(8)
        list_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        list_bar.pack_start(list_back, False, False, 0)
        list_bar.pack_start(self.heading, True, True, 0)
        self.list_back = list_back
        # 0 序号  1 标题  2 歌手  3 专辑  4 时长  5 数据  6 封面  7 VIP
        self.store = Gtk.ListStore(str, str, str, str, str, object, GdkPixbuf.Pixbuf, str)
        self.view = Gtk.TreeView(model=self.store, headers_visible=True)
        self.view.set_fixed_height_mode(False)
        self.view.set_activate_on_single_click(False)
        self.view.set_enable_search(False)
        self.view.connect("row-activated", self._on_activate)
        self.view.connect("button-press-event", self._on_list_press)
        self.view.connect("motion-notify-event", self._on_list_motion)
        self.view.connect("leave-notify-event", self._on_list_leave)
        self.view.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        song_scroll = Gtk.ScrolledWindow()
        song_scroll.get_style_context().add_class("song-list")
        song_scroll.get_vadjustment().connect("value-changed", lambda *_: self._schedule_covers())

        index_cell = Gtk.CellRendererText(xalign=1)
        index_cell.set_padding(8, 8)
        index_col = Gtk.TreeViewColumn("#", index_cell, text=0)
        index_col.set_min_width(46)
        index_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        index_col.set_fixed_width(52)
        index_col.set_cell_data_func(index_cell, self._paint_index)
        self.view.append_column(index_col)

        cover_cell = Gtk.CellRendererPixbuf()
        cover_cell.set_padding(4, 6)
        title_cell = Gtk.CellRendererText(ellipsize=3)
        title_cell.set_padding(6, 0)
        vip_cell = Gtk.CellRendererText()
        vip_cell.set_padding(4, 0)
        artist_cell = Gtk.CellRendererText(ellipsize=3)
        artist_cell.set_padding(8, 0)
        title_col = Gtk.TreeViewColumn("标题")
        title_col.pack_start(cover_cell, False)
        title_col.pack_start(title_cell, True)
        title_col.pack_start(vip_cell, False)
        title_col.pack_start(artist_cell, False)
        title_col.add_attribute(cover_cell, "pixbuf", 6)
        title_col.add_attribute(title_cell, "text", 1)
        title_col.add_attribute(vip_cell, "text", 7)
        title_col.add_attribute(artist_cell, "text", 2)
        # 标题不再吃掉剩余宽度。收掉大约一成，专辑和时长才能靠左，滚动条也不压字。
        title_col.set_expand(False)
        title_col.set_min_width(220)
        title_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        title_col.set_fixed_width(360)
        title_col.set_resizable(True)
        self.view.append_column(title_col)
        title_col.set_cell_data_func(title_cell, self._paint_title)
        title_col.set_cell_data_func(vip_cell, self._paint_vip)
        title_col.set_cell_data_func(artist_cell, self._paint_artist)

        album_cell = Gtk.CellRendererText(ellipsize=3, xalign=0)
        album_col = Gtk.TreeViewColumn("专辑", album_cell, text=3)
        album_col.set_min_width(120)
        album_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        album_col.set_fixed_width(168)
        album_col.set_resizable(True)
        album_col.set_cell_data_func(album_cell, self._paint_meta)
        self.view.append_column(album_col)
        duration_cell = Gtk.CellRendererText(xalign=0)
        duration_cell.set_padding(6, 0)
        duration_col = Gtk.TreeViewColumn("时长", duration_cell, text=4)
        duration_col.set_min_width(72)
        duration_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        duration_col.set_fixed_width(86)
        duration_col.set_alignment(0)
        duration_col.set_cell_data_func(duration_cell, self._paint_meta)
        self.view.append_column(duration_col)
        song_scroll.add(self.view)
        self.title_col = title_col
        self.album_col = album_col
        song_scroll.connect("size-allocate", self._fit_song_columns)
        self.song_scroll = song_scroll
        self.list_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.list_page.pack_start(list_bar, False, False, 0)
        self.list_page.pack_start(song_scroll, True, True, 0)

        self.lyric_buf = Gtk.TextBuffer()
        self.lyric_view = Gtk.TextView(buffer=self.lyric_buf, editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD)
        self.lyric_view.set_justification(Gtk.Justification.CENTER)
        self.lyric_view.set_left_margin(120)
        self.lyric_view.set_right_margin(120)
        self.lyric_view.set_pixels_above_lines(10)
        self.lyric_view.set_pixels_below_lines(10)
        self.lyric_view.connect("button-press-event", self._lyric_click)
        self.lyric_title = Gtk.Label(xalign=0.5)
        self.lyric_title.set_margin_top(18)
        self.lyric_title.get_style_context().add_class("lyric-song")
        self.lyric_artist = Gtk.Label()
        self.lyric_artist.set_margin_bottom(8)
        self.lyric_artist.get_style_context().add_class("lyric-artist")
        back = self._icon_button("go-previous-symbolic", lambda: self._show_lyric(False), "back-btn")
        back.set_tooltip_text("返回")
        lyric_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        lyric_bar.set_margin_top(8)
        lyric_bar.set_margin_start(10)
        lyric_bar.pack_start(back, False, False, 0)
        lyric_scroll = Gtk.ScrolledWindow()
        lyric_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        lyric_scroll.add(self.lyric_view)
        self.lyric_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.lyric_page.get_style_context().add_class("lyric-page")
        self.lyric_page.pack_start(lyric_bar, False, False, 0)
        self.lyric_page.pack_start(self.lyric_title, False, False, 0)
        self.lyric_page.pack_start(self.lyric_artist, False, False, 0)
        self.lyric_page.pack_start(lyric_scroll, True, True, 0)

        self.stack = Gtk.Stack()
        self.stack.get_style_context().add_class("page")
        self.stack.add_named(self.home_page, "home")
        self.stack.add_named(self.list_page, "list")
        self._build_album_page()
        self._build_artist_page()
        self.stack.add_named(self.album_page, "album")
        self.stack.add_named(self.artist_page, "artist")
        self.stack.add_named(self.lyric_page, "lyric")
        self._build_comment_page()
        self._build_download_page()
        self.stack.add_named(self.comment_page, "comments")
        self.stack.add_named(self.download_page, "downloads")
        self._build_queue_overlay()

        overlay = Gtk.Overlay()
        overlay.add(self.stack)
        # 打开时铺满内容区，挡住下面的列表。点在面板外就收起，点在面板上仍可选歌。
        self.queue_catcher = Gtk.EventBox()
        self.queue_catcher.set_visible_window(False)
        self.queue_catcher.add(self.queue_overlay)
        self.queue_catcher.connect("button-press-event", self._on_overlay_press)
        overlay.add_overlay(self.queue_catcher)
        self.queue_catcher.hide()

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.pack_start(self.side, False, False, 0)
        body.pack_start(overlay, True, True, 0)

        self.cover = Gtk.Image.new_from_icon_name("media-optical-symbolic", Gtk.IconSize.DIALOG)
        self.cover.set_size_request(46, 46)
        self.cover_btn = Gtk.Button()
        self.cover_btn.get_style_context().add_class("cover-btn")
        self.cover_btn.set_tooltip_text("查看歌词")
        self.cover_btn.add(self.cover)
        self.cover_btn.connect("clicked", lambda *_: self._show_lyric(True))
        self.title_btn = Gtk.Label(label="未在播放", xalign=0)
        self.title_btn.set_ellipsize(3)
        self.title_btn.get_style_context().add_class("bar-title")
        title_click = Gtk.EventBox()
        title_click.add(self.title_btn)
        title_click.connect("button-press-event", lambda *_: self._show_lyric(True))
        self.artist_btn = Gtk.Button(label="未知歌手")
        self.artist_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.artist_btn.get_style_context().add_class("bar-link")
        self.artist_btn.set_tooltip_text("打开歌手")
        self.artist_btn.connect("clicked", lambda *_: self._open_current_artist())
        artist_label = self.artist_btn.get_child()
        if isinstance(artist_label, Gtk.Label):
            artist_label.set_ellipsize(3)
            artist_label.set_max_width_chars(12)
            artist_label.set_xalign(0)
        names = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        names.pack_start(title_click, False, False, 0)
        names.pack_start(self.artist_btn, False, False, 0)
        self.like_btn = self._icon_button(heart_icon(16), self._toggle_like, "icon-btn")
        self.like_btn.set_tooltip_text("喜欢")
        self.comment_btn = self._icon_button(comment_icon(16), lambda: self._open_comments(), "icon-btn")
        self.comment_btn.set_tooltip_text("评论")
        self.collect_btn = self._icon_button(add_icon(16), self._toggle_collect, "icon-btn")
        self.collect_btn.set_tooltip_text("收藏到歌单")
        song_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        song_actions.pack_start(self.like_btn, False, False, 0)
        song_actions.pack_start(self.comment_btn, False, False, 0)
        song_actions.pack_start(self.collect_btn, False, False, 0)
        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        meta.set_size_request(220, -1)
        meta.pack_start(names, False, False, 0)
        meta.pack_start(song_actions, False, False, 0)

        self.play_btn = Gtk.Button()
        self.play_btn.get_style_context().add_class("play-main")
        self.play_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._play_hovered = False
        self._set_play_icon(False)
        self.play_btn.connect("clicked", lambda *_: self._toggle())
        self.play_btn.connect("enter-notify-event", lambda *_: self._play_hover(True))
        self.play_btn.connect("leave-notify-event", lambda *_: self._play_hover(False))
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1000, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.set_size_request(80, 14)
        self.scale.set_valign(Gtk.Align.CENTER)
        self.scale.set_can_focus(False)
        self.scale.set_tooltip_text("点击或拖动进度条跳转")
        self.scale.connect("change-value", self._seek_change)
        self.scale.connect("button-press-event", self._seek_press)
        self.scale.connect("button-release-event", self._seek_release)
        self.scale.connect("motion-notify-event", self._seek_motion)
        self.time_label = Gtk.Label(label="00:00 / 00:00")
        self.time_label.get_style_context().add_class("time-pill")
        self.time_label.set_no_show_all(True)
        self.time_label.hide()
        self.mode_btn = self._icon_button("media-playlist-repeat-symbolic", self._cycle_mode, "icon-btn")
        self._apply_mode_button()
        self.queue_btn = self._icon_button("view-list-symbolic", self._show_queue, "icon-btn")
        self.queue_btn.set_tooltip_text("播放列表")
        self.quality_btn = Gtk.MenuButton(label=self._quality_short())
        self.quality_btn.get_style_context().add_class("quality-btn")
        self.quality_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.quality_btn.set_valign(Gtk.Align.CENTER)
        self.quality_btn.set_size_request(64, 24)
        self.quality_btn.set_tooltip_text("播放音质")
        self.desk_lyric_btn = Gtk.Button(label="词")
        self.desk_lyric_btn.get_style_context().add_class("icon-btn")
        self.desk_lyric_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.desk_lyric_btn.set_valign(Gtk.Align.CENTER)
        self.desk_lyric_btn.set_tooltip_text("桌面歌词")
        self.desk_lyric_btn.connect("clicked", lambda *_: self._toggle_desk_lyric())

        self.prev_btn = self._icon_button("media-skip-backward-symbolic", self._prev, "transport")
        self.next_btn = self._icon_button("media-skip-forward-symbolic", self._next, "transport")
        self.prev_btn.set_tooltip_text("上一首")
        self.next_btn.set_tooltip_text("下一首")

        self.volume_btn = self._icon_button("audio-volume-high-symbolic", self._toggle_volume, "icon-btn")
        self.volume_btn.set_tooltip_text("系统音量")
        self.more_btn = self._icon_button(more_icon(16), self._popup_more, "icon-btn")
        self.more_btn.set_tooltip_text("更多")
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 1, 0.01)
        self.volume.set_inverted(True)
        self.volume.set_draw_value(False)
        self.volume.set_size_request(28, 110)
        self._volume_ready = False
        self.volume.set_value(self._system_volume())
        self._volume_ready = True
        self.volume.connect("value-changed", self._on_volume)
        self.player.set_volume(1.0)
        self._sync_volume_icon(self.volume.get_value())
        volume_pop = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        volume_pop.set_margin_top(8)
        volume_pop.set_margin_bottom(8)
        volume_pop.set_margin_start(6)
        volume_pop.set_margin_end(6)
        volume_pop.pack_start(self.volume, True, True, 0)
        volume_pop.show_all()
        self.volume_popup = Gtk.Popover()
        self.volume_popup.add(volume_pop)
        self.volume_popup.set_relative_to(self.volume_btn)
        self.volume_popup.set_position(Gtk.PositionType.TOP)

        progress = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        progress.get_style_context().add_class("progress-row")
        progress.pack_start(self.scale, True, True, 0)
        self.time_label.set_no_show_all(True)
        progress.pack_start(self.time_label, False, False, 0)
        self._progress_overlay = progress

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        controls.get_style_context().add_class("player-controls")
        controls.pack_start(self.cover_btn, False, False, 0)
        controls.pack_start(meta, False, False, 0)
        center = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        center.set_halign(Gtk.Align.CENTER)
        center.set_hexpand(True)
        center.pack_start(self.mode_btn, False, False, 0)
        center.pack_start(self.prev_btn, False, False, 0)
        center.pack_start(self.play_btn, False, False, 0)
        center.pack_start(self.next_btn, False, False, 0)
        center.pack_start(self.queue_btn, False, False, 0)
        controls.pack_start(center, True, True, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        right.pack_start(self.quality_btn, False, False, 0)
        right.pack_start(self.desk_lyric_btn, False, False, 0)
        right.pack_start(self.volume_btn, False, False, 0)
        right.pack_start(self.more_btn, False, False, 0)
        controls.pack_end(right, False, False, 0)

        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        bar.get_style_context().add_class("player-bar")
        bar.pack_start(progress, False, False, 0)
        bar.pack_start(controls, False, False, 0)

        self.status = Gtk.Label(label="", xalign=0)
        self.status.set_margin_start(16)
        self.status.get_style_context().add_class("dim")
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(body, True, True, 0)
        root.pack_start(bar, False, False, 0)
        root.pack_start(self.status, False, False, 2)
        self.add(root)
        self._rebuild_quality_menu()
        self._fill_nav()
        self._install_accelerators()

    def _install_accelerators(self):
        actions = (
            ("playpause", ["space"], self._toggle),
            ("focus-search", ["<Primary>f"], lambda: self.search.grab_focus()),
            ("seek-back", ["Left"], lambda: self._nudge(-5000)),
            ("seek-forward", ["Right"], lambda: self._nudge(5000)),
            ("close-overlay", ["Escape"], self._escape),
        )
        for name, accels, handler in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, fn=handler: fn())
            self.add_action(action)
            self.get_application().set_accels_for_action("win." + name, accels)

    def _nudge(self, delta):
        total = self.player.duration_ms() or (self.current_song or {}).get("duration") or 0
        if not total:
            return
        target = min(total - 500, max(0, self.player.position_ms() + delta))
        self.player.seek_ms(target)

    def _escape(self):
        if self.queue_overlay is not None and self.queue_overlay.get_reveal_child():
            self._hide_queue()
            return
        if self.lyric_open or self.stack.get_visible_child_name() in ("comments", "downloads"):
            self._show_page("list" if len(self.store) else "home")
            self.lyric_open = False

    def _on_key(self, _win, event):
        if isinstance(self.get_focus(), (Gtk.Entry, Gtk.SearchEntry)):
            return False
        return False

    def _on_window_press(self, _win, event):
        # 播放列表浮在内容区上。点侧栏、播放条或标题栏时，内容区收不到这次点击。
        if self.queue_overlay is None or not self.queue_overlay.get_reveal_child():
            return False
        panel = self.queue_overlay.get_child()
        if panel is None or not panel.get_window():
            return False
        x, y = event.x_root, event.y_root
        origin = panel.get_window().get_root_coords(0, 0)
        if origin is None:
            return False
        px, py = origin
        width, height = panel.get_allocated_width(), panel.get_allocated_height()
        if px <= x <= px + width and py <= y <= py + height:
            return False
        self._hide_queue()
        return False

    def _pulse_stream(self):
        """只找本播放器的 PulseAudio 播放流，不改整机输出。"""
        cached = getattr(self, "_pulse_cache", None)
        if cached and time.time() - cached[0] < 3:
            return cached[1]
        try:
            out = subprocess.check_output(
                ["pactl", "list", "sink-inputs"],
                stderr=subprocess.DEVNULL,
                timeout=2,
                text=True,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        current = None
        matched = None
        for line in out.splitlines():
            head = line.strip()
            if head.startswith("Sink Input #"):
                current = head.split("#", 1)[1].strip()
            elif current and "application.process.id" in head and f"= \"{os.getpid()}\"" in head:
                matched = current
        self._pulse_cache = (time.time(), matched)
        return matched

    def _system_volume(self):
        """读本播放流的音量。还没出声时用上次记住的值。"""
        stream = self._pulse_stream()
        if stream:
            try:
                out = subprocess.check_output(
                    ["pactl", "list", "sink-inputs"],
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                    text=True,
                )
                block = []
                capture = False
                for line in out.splitlines():
                    if line.strip().startswith("Sink Input #"):
                        capture = line.strip().endswith("#" + stream)
                    if capture:
                        block.append(line)
                match = re.search(r"(\d+)%", "\n".join(block))
                if match:
                    return max(0.0, min(1.0, int(match.group(1)) / 100))
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        try:
            return max(0.0, min(1.0, float(open(VOLUME_PATH, encoding="utf-8").read().strip())))
        except (OSError, ValueError):
            return 0.8

    def _on_volume(self, scale):
        # value-changed 只传滑条。多写一个参数时，拖动会直接报错，系统音量不会变。
        if not getattr(self, "_volume_ready", False):
            return
        value = scale.get_value()
        self.player.set_volume(1.0)
        self._sync_volume_icon(value)
        percent = f"{int(round(max(0.0, min(1.0, value)) * 100))}%"
        stream = self._pulse_stream()
        if stream:
            try:
                subprocess.check_call(
                    ["pactl", "set-sink-input-volume", stream, percent],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except (OSError, subprocess.SubprocessError):
                self._status("播放音量没有改成功")
        self._remember_volume(value)

    def _remember_volume(self, value):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(VOLUME_PATH, "w", encoding="utf-8") as handle:
                handle.write(f"{value:.3f}")
        except OSError:
            pass

    def _restore_window(self):
        try:
            data = json.loads(open(WINDOW_PATH, encoding="utf-8").read())
            width = int(data.get("w") or 1080)
            height = int(data.get("h") or 680)
            # 截图和调试窗口写过偏矮的尺寸，那种不拿来当默认高度。
            if height < 560:
                height = 680
            width, height = self._fit_window(width, height)
            self.set_default_size(width, height)
            if data.get("x") is not None:
                self.move(int(data["x"]), int(data["y"]))
        except (OSError, ValueError, TypeError):
            pass

    def _fit_window(self, width, height):
        """窗口不能高过当前屏幕。已经撑出去的尺寸收回到工作区里。"""
        width = max(860, int(width))
        height = max(560, int(height))
        screen = self.get_screen()
        monitor = screen.get_monitor_at_window(self.get_window()) if self.get_window() else 0
        geom = screen.get_monitor_geometry(monitor)
        limit_w = max(860, geom.width - 48)
        limit_h = max(560, geom.height - 80)
        return min(width, limit_w), min(height, limit_h)

    def _clamp_window(self):
        width, height = self.get_size()
        fitted = self._fit_window(width, height)
        if fitted != (width, height):
            self.resize(*fitted)
        return False

    def _remember_window(self, *_args):
        width, height = self.get_size()
        x, y = self.get_position()
        if width < 200 or height < 200:
            return False
        width, height = self._fit_window(width, height)
        now = time.time()
        if now - getattr(self, "_window_saved_at", 0) < 1.5:
            return False
        self._window_saved_at = now
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(WINDOW_PATH, "w", encoding="utf-8") as handle:
                json.dump({"w": width, "h": height, "x": x, "y": y}, handle)
        except OSError:
            pass
        return False

    def _rebuild_account_menu(self):
        menu = Gtk.Menu()
        if self.cookie:
            name = (self.profile or {}).get("nickname") or "已登录"
            vip = (self.profile or {}).get("vip") or ""
            self.account_btn.set_label(name + (f" · {vip}" if vip else ""))
            logout = Gtk.MenuItem(label="退出登录")
            logout.connect("activate", lambda *_: self._logout())
            menu.append(logout)
        else:
            self.account_btn.set_label("登录")
            login = Gtk.MenuItem(label="扫码登录")
            login.connect("activate", lambda *_: self._on_login())
            menu.append(login)
        menu.show_all()
        self.account_btn.set_popup(menu)

    def _song_menu(self, song, index):
        menu = Gtk.Menu()
        liked = self._song_liked(song)
        items = (
            ("下一首播放", lambda: self._play_next(song)),
            ("取消喜欢" if liked else "加入喜欢", lambda: self._toggle_like(song)),
            ("下载", lambda: self._enqueue_download(song)),
            ("查看评论", lambda: self._open_comments(song)),
        )
        for label, handler in items:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _item, fn=handler: fn())
            menu.append(item)
        collect = Gtk.MenuItem(label="收藏到歌单")
        collect.set_submenu(self._playlist_submenu(song))
        menu.append(collect)
        browsing = getattr(self, "_browsing_playlist", None)
        if browsing and self._can_remove_from_open(browsing):
            name = self.heading.get_text() or "当前歌单"
            remove_collect = Gtk.MenuItem(label=f"从「{name}」移除")
            remove_collect.connect(
                "activate",
                lambda *_: self._remove_from(song, browsing, name),
            )
            menu.append(remove_collect)
        if 0 <= index < len(self.playing) and self.playing[index] is song:
            remove = Gtk.MenuItem(label="从播放列表移除")
            remove.connect("activate", lambda *_: self._remove_playing_at(index))
            menu.append(remove)
        menu.show_all()
        return menu

    def _remove_playing_at(self, index):
        if index < 0 or index >= len(self.playing):
            return
        current = self.playing_index == index
        del self.playing[index]
        if index < self.playing_index:
            self.playing_index -= 1
        self._refresh_queue_popup()
        if current:
            if not self.playing:
                self.player.stop()
                self.current_song = None
                return
            self._play_from_playing(min(index, len(self.playing) - 1))

    def _created_playlists(self):
        uid = (self.profile or {}).get("userId")
        return [
            item for item in self.mine
            if item.get("special") != 5 and "喜欢的音乐" not in (item.get("name") or "")
            and (not uid or str(item.get("creator")) == str(uid))
        ]

    def _playlist_submenu(self, song):
        menu = Gtk.Menu()
        created = self._created_playlists()
        if not self.cookie:
            empty = Gtk.MenuItem(label="请先登录")
            empty.set_sensitive(False)
            menu.append(empty)
            return menu
        if not created:
            empty = Gtk.MenuItem(label="还没有自建歌单")
            empty.set_sensitive(False)
            menu.append(empty)
            return menu
        for playlist in created:
            item = Gtk.MenuItem(label=playlist.get("name") or "歌单")
            item.connect(
                "activate",
                lambda _item, pid=playlist.get("id"), name=playlist.get("name"): self._collect_to(song, pid, name),
            )
            menu.append(item)
        return menu

    def _can_remove_from_open(self, playlist_id):
        """只有当前打开的自建歌单才提供移除，不展开二级菜单。"""
        if not self.cookie or not playlist_id:
            return False
        return any(str(item.get("id")) == str(playlist_id) for item in self._created_playlists())

    def _collect_to(self, song, playlist_id, name):
        if not song or not song.get("id") or not playlist_id:
            return
        self._status(f"正在加入「{name}」…")
        self._bg(lambda: self._collect_track(song, playlist_id, name))

    def _collect_track(self, song, playlist_id, name):
        try:
            api.add_playlist_track(playlist_id, song["id"], self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        self._remember_playlist_track(playlist_id, song["id"], True)
        GLib.idle_add(self._status, f"已加入「{name}」：{song.get('name') or ''}")
        if self._viewing_playlist(playlist_id):
            GLib.idle_add(self._insert_song_row, song)

    def _remove_from(self, song, playlist_id, name):
        if not song or not song.get("id") or not playlist_id:
            return
        self._status(f"正在从「{name}」移除…")
        self._bg(lambda: self._remove_track(song, playlist_id, name))

    def _remove_track(self, song, playlist_id, name):
        try:
            api.remove_playlist_track(playlist_id, song["id"], self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        self._remember_playlist_track(playlist_id, song["id"], False)
        GLib.idle_add(self._status, f"已从「{name}」移除：{song.get('name') or ''}")
        if getattr(self, "_browsing_playlist", None) == playlist_id:
            GLib.idle_add(self._drop_song_row, song.get("id"))

    def _remember_playlist_songs(self, playlist_id, songs):
        known = getattr(self, "playlist_tracks", None)
        if known is None:
            known = {}
            self.playlist_tracks = known
        known[playlist_id] = {song.get("id") for song in songs if isinstance(song, dict) and song.get("id")}

    def _remember_playlist_track(self, playlist_id, song_id, present):
        known = getattr(self, "playlist_tracks", None)
        if known is None:
            known = {}
            self.playlist_tracks = known
        ids = set(known.get(playlist_id) or ())
        if present:
            ids.add(song_id)
        else:
            ids.discard(song_id)
        known[playlist_id] = ids

    def _viewing_liked(self):
        return self.stack.get_visible_child_name() == "list" and bool(getattr(self, "_browsing_liked", False))

    def _viewing_playlist(self, playlist_id):
        if self.stack.get_visible_child_name() != "list":
            return False
        current = getattr(self, "_browsing_playlist", None)
        return current is not None and str(current) == str(playlist_id)

    def _insert_song_row(self, song):
        """收藏成功后插到当前列表最前。已在列表里就不重复加。"""
        if not isinstance(song, dict) or not song.get("id"):
            return False
        song_id = str(song.get("id"))
        for row in self.store:
            item = row[5]
            if isinstance(item, dict) and str(item.get("id")) == song_id and item.get("artist") is not None:
                return False
        self.store.insert(0, [
            "01",
            song.get("name") or "",
            song.get("artist") or "",
            song.get("album") or "",
            fmt_time(song.get("duration")),
            song,
            self._cover_placeholder(),
            self._vip_mark(song),
        ])
        self._renumber_rows()
        self._schedule_covers()
        return False

    def _drop_song_row(self, song_id):
        for row in list(self.store):
            song = row[5]
            if isinstance(song, dict) and str(song.get("id")) == str(song_id):
                self.store.remove(row.iter)
        self._renumber_rows()
        return False

    def _renumber_rows(self):
        for index, row in enumerate(self.store, start=1):
            row[0] = f"{index:02d}"

    def _play_next(self, song):
        if not self.playing:
            self.playing = [song]
            self.playing_index = 0
            self._play_song(song)
            return
        insert_at = min(len(self.playing), self.playing_index + 1)
        self.playing.insert(insert_at, song)
        self._refresh_queue_popup()
        self._status(f"下一首播放 {song.get('name') or ''}")

    def _toggle_like(self, song=None):
        song = song or self.current_song
        if not song or not song.get("id"):
            return
        if not self.cookie:
            self._status("请先登录再收藏")
            return
        liked = self._song_liked(song)
        self._bg(lambda: self._like(song, not liked))

    def _like(self, song, like):
        try:
            api.like_song(song["id"], like, self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        if like:
            self.liked_ids.add(song["id"])
        else:
            self.liked_ids.discard(song["id"])
        GLib.idle_add(self._status, ("已加入我喜欢" if like else "已移出我喜欢") + f"：{song.get('name') or ''}")
        GLib.idle_add(self._refresh_like_button)
        if self._viewing_liked():
            GLib.idle_add(self._insert_song_row if like else self._drop_song_row, song if like else song.get("id"))

    def _song_liked(self, song):
        if not isinstance(song, dict) or not song.get("id"):
            return False
        return str(song.get("id")) in {str(item) for item in self.liked_ids}

    def _refresh_like_button(self):
        song = self.current_song or {}
        liked = self._song_liked(song)
        ctx = self.like_btn.get_style_context()
        if liked:
            ctx.add_class("liked")
        else:
            ctx.remove_class("liked")
        image = self.like_btn.get_image()
        if image is not None:
            pixbuf = heart_icon(16, filled=liked)
            if liked:
                pixbuf = _tint_pixbuf(pixbuf, 0.925, 0.255, 0.255)
            image.set_pixel_size(pixbuf.get_width())
            image.set_from_pixbuf(pixbuf)
            for state in (Gtk.StateFlags.NORMAL, Gtk.StateFlags.PRELIGHT, Gtk.StateFlags.ACTIVE):
                image.override_color(state, None)
        self.like_btn.set_tooltip_text("取消喜欢" if liked else "喜欢")
        return False

    def _toggle_collect(self):
        song = self.current_song
        if not song or not song.get("id"):
            self._status("还没有正在播放的歌曲")
            return
        if not self.cookie:
            self._status("请先登录再收藏")
            return
        popover = getattr(self, "_collect_popover", None)
        if popover is not None and popover.get_visible():
            popover.popdown()
            return
        self._show_collect(song)

    def _show_collect(self, song):
        popover = Gtk.Popover()
        popover.get_style_context().add_class("collect-popover")
        popover.set_relative_to(self.collect_btn)
        popover.set_position(Gtk.PositionType.TOP)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_size_request(360, 420)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        title = Gtk.Label(label="收藏到歌单", xalign=0.5)
        title.get_style_context().add_class("collect-title")
        box.pack_start(title, False, False, 0)
        tabs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        default_tab = Gtk.Label(label="默认排序")
        default_tab.get_style_context().add_class("collect-tab")
        default_tab.get_style_context().add_class("active")
        often_tab = Gtk.Label(label="常用优先")
        often_tab.get_style_context().add_class("collect-tab")
        tabs.pack_start(default_tab, False, False, 0)
        tabs.pack_start(often_tab, False, False, 0)
        box.pack_start(tabs, False, False, 4)
        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        create = self._collect_row("创建新歌单", "", lambda: self._create_and_collect(song, popover), plus=True)
        rows.pack_start(create, False, False, 0)
        liked = next((item for item in self.mine if item.get("special") == 5 or "喜欢的音乐" in (item.get("name") or "")), None)
        if liked:
            rows.pack_start(self._collect_row(liked.get("name") or "我喜欢的音乐", f"{liked.get('count') or 0}首", lambda item=liked: self._collect_choice(song, item, popover), cover=liked.get("cover")), False, False, 0)
        for item in self._created_playlists():
            rows.pack_start(self._collect_row(item.get("name") or "歌单", f"{item.get('count') or 0}首", lambda item=item: self._collect_choice(song, item, popover), cover=item.get("cover")), False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(rows)
        box.pack_start(scroll, True, True, 0)
        popover.add(box)
        box.show_all()
        self._collect_popover = popover
        popover.popup()

    def _collect_row(self, name, count, handler, plus=False, cover=""):
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(6)
        row.set_margin_bottom(6)
        if plus:
            mark = Gtk.Label(label="+")
            mark.set_size_request(40, 40)
            mark.get_style_context().add_class("collect-plus")
        else:
            mark = Gtk.Image.new_from_icon_name("folder-music-symbolic", Gtk.IconSize.DIALOG)
            mark.set_pixel_size(40)
            if cover:
                self._bg(lambda url=cover, widget=mark: self._set_remote_image(url, widget, 40))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title = Gtk.Label(label=name, xalign=0)
        title.set_ellipsize(3)
        title.get_style_context().add_class("collect-name")
        text.pack_start(title, False, False, 0)
        if count:
            meta = Gtk.Label(label=count, xalign=0)
            meta.get_style_context().add_class("collect-count")
            text.pack_start(meta, False, False, 0)
        row.pack_start(mark, False, False, 0)
        row.pack_start(text, True, True, 0)
        button.add(row)
        button.connect("clicked", lambda *_: handler())
        return button

    def _collect_choice(self, song, playlist, popover):
        popover.popdown()
        self._collect_to(song, playlist.get("id"), playlist.get("name") or "歌单")

    def _create_and_collect(self, song, popover):
        popover.popdown()
        dialog = Gtk.Dialog(title="创建新歌单", parent=self, flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        dialog.add_button("创建", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry()
        entry.set_placeholder_text("歌单名称")
        entry.set_margin_start(16)
        entry.set_margin_end(16)
        entry.set_margin_top(12)
        entry.set_margin_bottom(12)
        entry.set_activates_default(True)
        dialog.get_content_area().pack_start(entry, True, True, 0)
        dialog.show_all()
        if dialog.run() != Gtk.ResponseType.OK:
            dialog.destroy()
            return
        name = entry.get_text().strip()
        dialog.destroy()
        if not name:
            self._status("歌单名称不能为空")
            return
        self._status(f"正在创建「{name}」…")
        self._bg(lambda: self._create_playlist(song, name))

    def _create_playlist(self, song, name):
        try:
            playlist_id = api.create_playlist(name, self.cookie)
            if song and song.get("id"):
                api.add_playlist_track(playlist_id, song["id"], self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        GLib.idle_add(self._status, f"已创建并加入「{name}」")
        self._load_account()

    def _menu_item(self, label, icon_name, handler, sensitive=True):
        item = Gtk.ImageMenuItem.new_with_label(label)
        item.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU))
        item.set_always_show_image(True)
        item.set_sensitive(sensitive)
        item.connect("activate", lambda *_: handler())
        return item

    def _popup_more(self):
        song = self.current_song or {}
        ready = bool(song.get("id"))
        menu = Gtk.Menu()
        items = (
            ("下载", "folder-download-symbolic", lambda: self._enqueue_download(song), ready),
            ("分享", "emblem-shared-symbolic", lambda: self._share_song(song), ready),
            ("一起听", "system-users-symbolic", lambda: self._status("一起听还没接入"), True),
            ("播放倍速", "media-seek-forward-symbolic", self._cycle_rate, ready),
        )
        for label, icon_name, handler, sensitive in items:
            menu.append(self._menu_item(label, icon_name, handler, sensitive))
        menu.append(Gtk.SeparatorMenuItem())
        artist = song.get("artist") or "歌手"
        album = song.get("album") or "专辑"
        links = (
            (f"歌手: {artist}", "avatar-default-symbolic", self._open_current_artist, ready),
            (f"专辑: {album}", "media-optical-symbolic", lambda: self._open_album(song.get("albumId"), album), ready),
            ("音效", "audio-volume-high-symbolic", lambda: self._status("音效还没接入"), True),
        )
        for label, icon_name, handler, sensitive in links:
            menu.append(self._menu_item(label, icon_name, handler, sensitive))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(self._menu_item("减少推荐", "list-remove-symbolic", lambda: self._status("已记下，当前推荐仍按热门歌单显示")))
        menu.show_all()
        menu.popup_at_widget(self.more_btn, Gdk.Gravity.NORTH_EAST, Gdk.Gravity.SOUTH_EAST, None)

    def _share_song(self, song):
        if not song or not song.get("id"):
            self._status("还没有正在播放的歌曲")
            return
        url = f"https://music.163.com/song?id={int(song['id'])}"
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(url, -1)
        self._status(f"已复制分享链接：{song.get('name') or ''}")

    def _cycle_rate(self):
        rates = (1.0, 1.25, 1.5, 0.75)
        current = getattr(self, "_play_rate", 1.0)
        rate = rates[(rates.index(current) + 1) % len(rates)] if current in rates else 1.0
        self._play_rate = rate
        try:
            self.player.playbin.seek(
                rate,
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                Gst.SeekType.SET,
                int(self.player.position_ms() * Gst.MSECOND),
                Gst.SeekType.NONE,
                0,
            )
        except Exception:
            self._status("倍速没有切换成功")
            return
        self._status(f"播放倍速 {rate:g}x")

    def _toggle_volume(self):
        if self.volume_popup.get_visible():
            self.volume_popup.popdown()
        else:
            self.volume_popup.popup()

    def _sync_volume_icon(self, value):
        icon = "audio-volume-muted-symbolic" if value < 0.01 else (
            "audio-volume-low-symbolic" if value < 0.34 else
            "audio-volume-medium-symbolic" if value < 0.67 else
            "audio-volume-high-symbolic"
        )
        image = self.volume_btn.get_image()
        if image is not None:
            image.set_from_icon_name(icon, Gtk.IconSize.BUTTON)

    def _icon_button(self, name, handler, style="flat"):
        if isinstance(name, str):
            button = Gtk.Button.new_from_icon_name(name, Gtk.IconSize.BUTTON)
        else:
            button = Gtk.Button()
            image = Gtk.Image.new_from_pixbuf(name)
            image.set_pixel_size(name.get_width())
            button.set_image(image)
            button.set_always_show_image(True)
        button.get_style_context().add_class(style)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.connect("clicked", lambda *_: handler())
        return button

    def _quality_short(self, level=None):
        level = level or getattr(self, "_applied_quality", None) or self.quality
        return self._quality_name(level).split()[0] or "音质"

    def _rebuild_quality_menu(self, levels=None, selected=None):
        """菜单只列这首歌能播的档，勾选的是正在播放的档，不是偏好档。"""
        if levels is None:
            levels = getattr(self, "_quality_options", None) or [key for key, _name, _hint in api.QUALITIES]
        allowed = [key for key, _name, _hint in api.QUALITIES if key in levels]
        if not allowed:
            allowed = [key for key, _name, _hint in api.QUALITIES]
        selected = selected or getattr(self, "_applied_quality", None) or self.quality
        if selected not in allowed:
            selected = allowed[0]
        menu = Gtk.Menu()
        menu.get_style_context().add_class("menu")
        group = None
        for key, name, hint in api.QUALITIES:
            if key not in allowed:
                continue
            item = Gtk.RadioMenuItem(label=f"{name}   {hint}", group=group)
            group = item
            item.set_active(key == selected)
            item.get_child().override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.13, 0.13, 0.15, 1))
            item.get_child().override_color(Gtk.StateFlags.PRELIGHT, Gdk.RGBA(0.13, 0.13, 0.15, 1))
            menu.append(item)
            item.connect("activate", self._on_quality, key)
        menu.show_all()
        self._quality_options = allowed
        self.quality_btn.set_popup(menu)
        self.quality_btn.set_label(self._quality_short(selected))

    def _apply_quality_state(self, song, info, levels=None):
        """切歌或切音质后，按钮和菜单都改成实际在播的档。"""
        if self.current_song and song and self.current_song.get("id") != song.get("id"):
            return False
        level = (info or {}).get("level") or self.quality
        if level == "local":
            self._applied_quality = "local"
            self.quality_btn.set_label("本地")
            return False
        self._applied_quality = level
        if levels:
            self._quality_options = [key for key in levels if key in api.QUALITY_LABEL]
        self._rebuild_quality_menu(self._quality_options, selected=level)
        return False

    def _refresh_quality_options(self, song, known=None):
        try:
            levels = api.song_qualities(song["id"], cookie=self.cookie, known=known)
        except api.ApiError:
            return
        if self.current_song and self.current_song.get("id") != song.get("id"):
            return
        if not levels:
            return
        GLib.idle_add(self._rebuild_quality_menu, levels, getattr(self, "_applied_quality", None))

    def _on_quality(self, item, key):
        if item is not None and not item.get_active():
            return
        if key == getattr(self, "_applied_quality", None):
            return
        self.quality = key
        self._save_quality(key)
        song = self.current_song
        if not song or not song.get("id"):
            self._applied_quality = key
            self.quality_btn.set_label(self._quality_short(key))
            self._status(f"音质已设为{api.QUALITY_LABEL.get(key, key)}")
            return
        playing = self.player.playing() or self.player.paused()
        resume_at = self.player.position_ms() if playing else 0
        self._status(f"正在确认{api.QUALITY_LABEL.get(key, key)}…")
        self._bg(lambda: self._switch_quality(song, resume_at, playing))

    def _switch_quality(self, song, resume_at, playing):
        try:
            info = api.song_url(song["id"], level=self.quality, cookie=self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        if self.current_song and self.current_song.get("id") != song.get("id"):
            return
        if not info:
            GLib.idle_add(self._status, f"「{song.get('name') or ''}」没有可播放地址")
            return
        got = info.get("level") or self.quality
        current = getattr(self, "_applied_quality", None)
        if got == current and playing:
            GLib.idle_add(self._quality_kept, song, info)
            self._bg(lambda: self._refresh_quality_options(song, {got: info}))
            return
        self.player.play(info["url"])
        if resume_at > 800:
            self.player.seek_ms(resume_at)
            GLib.timeout_add(180, self._seek_after_switch, song, resume_at, 0)
        GLib.idle_add(self._quality_started, song, info)
        self._bg(lambda: self._refresh_quality_options(song, {got: info}))

    def _quality_kept(self, song, info):
        if self.current_song and self.current_song.get("id") != song.get("id"):
            return False
        self._apply_quality_state(song, info)
        label = api.QUALITY_LABEL.get(info.get("level") or "", "")
        self._status(f"这首歌当前就是{label}，没有重新播放")
        return False

    def _seek_after_switch(self, song, resume_at, tries):
        if not self.current_song or self.current_song.get("id") != song.get("id"):
            return False
        if self.player.cached_dur > 0 or tries >= 8:
            self.player.seek_ms(resume_at)
            return False
        GLib.timeout_add(200, self._seek_after_switch, song, resume_at, tries + 1)
        return False

    def _quality_started(self, song, info):
        if self.current_song and self.current_song.get("id") != song.get("id"):
            return False
        level = info.get("level") or ""
        self._apply_quality_state(song, info)
        label = api.QUALITY_LABEL.get(level, level)
        note = "，已换成这首歌能播的最高档" if level and level != self.quality else ""
        kbps = int((info.get("br") or 0) / 1000)
        self._status(f"正在播放 · {label} · {kbps}kbps {(info.get('type') or '').upper()}{note}")
        self._sync_play_icon()
        return False

    def _fill_nav(self):
        for child in self.nav_box.get_children():
            self.nav_box.remove(child)
        self.nav_buttons = []
        self._nav("推荐", lambda: self._show_home(), current=True, icon="user-home-symbolic")
        for cid, name in api.CHARTS[:4]:
            self._nav(
                name,
                lambda c=cid, n=name: self._open_playlist(c, n),
                icon=note_icon(),
                cover_id=cid,
            )
        self._nav("热门歌单", self._open_discover, icon="folder-music-symbolic")
        if self.profile:
            self._section(self.profile.get("vip") or "我的")
            liked = next((item for item in self.mine if item.get("special") == 5 or "喜欢的音乐" in (item.get("name") or "")), None)
            self._nav("我喜欢的音乐", self._open_liked, icon="emblem-favorite-symbolic")
            self._nav("每日推荐", self._open_daily, icon="x-office-calendar-symbolic")
            self._nav("私人FM", self._open_fm, icon=fm_icon())
            self._nav("听歌排行", self._open_record, icon="utilities-system-monitor-symbolic")
            self._nav("下载管理", self._open_downloads, icon="folder-download-symbolic")
            self._nav("刷新收藏", self._refresh_library, icon="view-refresh-symbolic")
            created = []
            collected = []
            uid = self.profile.get("userId")
            for item in self.mine:
                if item is liked:
                    continue
                (created if item.get("creator") == uid else collected).append(item)
            if created:
                self._section("创建的歌单")
                for item in self._sort_by_recent(created)[:20]:
                    self._nav(
                        item["name"],
                        lambda i=item: self._open_playlist(i["id"], i["name"], mine=True),
                        cover=item.get("cover") or "",
                    )
            if collected:
                self._section("收藏的歌单")
                for item in self._sort_by_recent(collected)[:30]:
                    self._nav(
                        item["name"],
                        lambda i=item: self._open_playlist(i["id"], i["name"]),
                        cover=item.get("cover") or "",
                    )
        self.nav_box.show_all()

    def _load_recent(self):
        if getattr(self, "_recent_playlists", None) is not None:
            return self._recent_playlists
        try:
            self._recent_playlists = json.loads(open(RECENT_PATH, encoding="utf-8").read())
        except (OSError, ValueError):
            self._recent_playlists = {}
        return self._recent_playlists

    def _sort_by_recent(self, items):
        """最近播放过内容的歌单排前面，其余仍按收藏时间。"""
        recent = self._load_recent()

        def key(item):
            stamp = recent.get(str(item.get("id"))) or 0
            added = item.get("added") or 0
            return (1 if stamp else 0, stamp, added)

        return sorted(items, key=key, reverse=True)

    def _touch_playlist(self, ident):
        if not ident:
            return
        recent = self._load_recent()
        recent[str(ident)] = int(time.time())
        self._recent_playlists = recent
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(RECENT_PATH, "w", encoding="utf-8") as handle:
                json.dump(recent, handle)
        except OSError:
            pass
        self._fill_nav()

    def _section(self, text):
        label = Gtk.Label(label=text, xalign=0)
        label.get_style_context().add_class("section")
        self.nav_box.pack_start(label, False, False, 0)

    def _nav(self, text, handler, current=False, icon="folder-music-symbolic", cover="", cover_id=None):
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_halign(Gtk.Align.FILL)
        button.set_always_show_image(True)
        button.get_style_context().add_class("side-row")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if isinstance(icon, str):
            image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
        else:
            image = Gtk.Image.new_from_pixbuf(icon)
        image.set_pixel_size(14)
        label = Gtk.Label(label=text, xalign=0)
        label.set_ellipsize(3)
        row.pack_start(image, False, False, 0)
        row.pack_start(label, True, True, 0)
        button.add(row)
        if current:
            button.get_style_context().add_class("current")
        button.connect("clicked", lambda *_: self._select_nav(button, handler))
        self.nav_buttons.append(button)
        self.nav_box.pack_start(button, False, False, 0)
        if cover or cover_id:
            self._bg(lambda: self._load_nav_cover(image, cover, cover_id))

    def _load_nav_cover(self, image, cover, cover_id):
        """侧栏先显示默认图标。封面到了再换，不挡住歌单列表。"""
        url = cover
        if not url and cover_id:
            url = self._chart_cover(cover_id)
        if not url:
            return
        try:
            pix = load_pixbuf(url, 28)
            pix = pix.scale_simple(14, 14, GdkPixbuf.InterpType.BILINEAR)
        except Exception:
            return
        GLib.idle_add(self._apply_nav_cover, image, pix)

    def _apply_nav_cover(self, image, pix):
        if image.get_parent() is None:
            return False
        image.set_from_pixbuf(pix)
        image.set_pixel_size(14)
        return False

    def _chart_cover(self, playlist_id):
        cached = getattr(self, "_chart_covers", None)
        if cached is None:
            cached = {}
            self._chart_covers = cached
        if playlist_id in cached:
            return cached[playlist_id]
        try:
            payload = api.request("/api/v6/playlist/detail", {"id": int(playlist_id), "n": 0}, cookie=self.cookie)
        except api.ApiError:
            return ""
        cover = ((payload.get("playlist") or {}).get("coverImgUrl") or "")
        cached[playlist_id] = cover
        return cover

    def _select_nav(self, button, handler):
        for item in self.nav_buttons:
            item.get_style_context().remove_class("current")
        button.get_style_context().add_class("current")
        self._hide_queue()
        handler()

    def _open_fm(self):
        if not self.cookie:
            self._status("私人 FM 需要先登录")
            return
        self._hide_queue()
        self._browsing_playlist = None
        self._browsing_liked = False
        self.heading.set_text("私人FM")
        self._show_page("list")
        self.lyric_open = False
        self._status("正在获取私人 FM…")
        self._bg(self._load_fm)

    def _load_fm(self):
        songs = api.personal_fm(self.cookie)
        GLib.idle_add(self._set_songs, songs, f"私人 FM {len(songs)} 首，播完自动换一批")
        if songs:
            GLib.idle_add(self._play_fm_batch, songs)

    def _play_fm_batch(self, songs):
        self.playing = songs
        self.playing_title = "私人FM"
        self.playing_index = 0
        self.play_mode = "order"
        self._apply_mode_button()
        self._play_song(songs[0])
        return False

    def _open_record(self):
        if not self.cookie or not (self.profile or {}).get("userId"):
            self._status("听歌排行需要先登录")
            return
        self._hide_queue()
        self._browsing_playlist = None
        self._browsing_liked = False
        self.heading.set_text("听歌排行 · 最近一周")
        self._show_page("list")
        self._status("正在读取听歌排行…")
        self._bg(self._load_record)

    def _load_record(self):
        songs = api.play_record(self.profile["userId"], self.cookie, weekly=True)
        GLib.idle_add(self._set_songs, songs, f"最近一周播放 {len(songs)} 首")

    def _open_downloads(self):
        self._hide_queue()
        self._show_page("downloads")
        self._refresh_download_view()

    def _show_page(self, name):
        child = self.stack.get_child_by_name(name)
        if child is not None:
            child.show()
        self.stack.set_visible_child_name(name)
        self.stack.show_all()
        if self.queue_overlay is not None and self.queue_overlay.get_reveal_child():
            self.queue_catcher.show()
            self.queue_overlay.show_all()

    def _show_home(self):
        self.lyric_open = False
        # 播放列表遮罩在启动时可能还铺在首页上，第一次点击会被它吃掉。
        self._hide_queue()
        self._show_page("home")

    def _open_playlist(self, ident, name, mine=False):
        self._hide_queue()
        self._browsing_playlist = ident
        self._browsing_liked = False
        self.heading.set_text(name)
        self._show_page("list")
        self.lyric_open = False
        self._status(f"正在打开{name}…")
        self._bg(lambda: self._show_playlist(ident, name, mine))

    def _open_discover(self):
        self._hide_queue()
        self._browsing_playlist = None
        self._browsing_liked = False
        self.heading.set_text("热门歌单")
        self._show_page("list")
        self._status("正在加载热门歌单…")
        self._bg(self._show_discover)

    def _open_liked(self):
        self._hide_queue()
        self._browsing_playlist = None
        self._browsing_liked = True
        liked = next((item for item in self.mine if item.get("special") == 5 or "喜欢的音乐" in (item.get("name") or "")), None)
        if liked:
            self._browsing_playlist = liked.get("id")
        self.heading.set_text("我喜欢的音乐")
        self._show_page("list")
        self._status("正在同步我喜欢的音乐…")
        self._bg(self._show_liked)

    def _open_daily(self):
        self._hide_queue()
        self._browsing_playlist = None
        self._browsing_liked = False
        self.heading.set_text("每日推荐")
        self._show_page("list")
        self._bg(self._show_daily)

    def _refresh_library(self):
        self._status("正在从云端刷新收藏…")
        self._bg(self._load_account)

    def _on_search(self, entry):
        keyword = entry.get_text().strip()
        if not keyword:
            return
        self._hide_queue()
        self._browsing_playlist = None
        self._browsing_liked = False
        self.heading.set_text(f"搜索「{keyword}」")
        self._show_page("list")
        self._status("正在搜索…")
        self._bg(lambda: self._show_search(keyword))

    def _show_search(self, keyword):
        songs = api.search_songs(keyword, cookie=self.cookie)
        GLib.idle_add(self._set_songs, songs, f"找到 {len(songs)} 首")

    def _show_playlist(self, ident, name, mine=False):
        token = getattr(self, "_playlist_token", 0) + 1
        self._playlist_token = token
        if mine or "喜欢的音乐" in (name or ""):
            data = api.playlist_tracks(ident, cookie=self.cookie, by_added=True)
            if token != self._playlist_token:
                return
            self._remember_playlist_songs(ident, data.get("songs") or [])
            self._browsing_liked = True
            GLib.idle_add(self.heading.set_text, data["name"] or name)
            GLib.idle_add(
                self._set_songs,
                data["songs"],
                f"{len(data['songs'])} 首 · 按收藏时间从新到旧",
            )
            return
        data = api.playlist_page(ident, cookie=self.cookie, limit=80)
        if token != self._playlist_token or not data["songs"]:
            if token == self._playlist_token:
                GLib.idle_add(self._status, f"{name} 没有可显示的歌曲")
            return
        liked = data.get("special") == 5 or "喜欢的音乐" in (data.get("name") or name)
        self._browsing_liked = bool(liked)
        total = data.get("total") or len(data["songs"])
        status = f"{len(data['songs'])}/{total} 首" if total > len(data["songs"]) else f"{total} 首"
        GLib.idle_add(self.heading.set_text, data["name"] or name)
        GLib.idle_add(self._set_songs, data["songs"], status)
        if total <= len(data["songs"]):
            return
        songs = list(data["songs"])
        offset = len(songs)
        while offset < total and token == self._playlist_token:
            page = api.playlist_page(ident, cookie=self.cookie, limit=100, offset=offset)
            if token != self._playlist_token or not page["songs"]:
                return
            songs.extend(page["songs"])
            offset += len(page["songs"])
            GLib.idle_add(self._append_songs, list(songs), f"{len(songs)}/{total} 首", token)

    def _show_discover(self):
        GLib.idle_add(self._set_playlists, api.top_playlist(limit=40, cookie=self.cookie))

    def _load_mode(self):
        if os.path.exists(MODE_PATH):
            value = open(MODE_PATH, encoding="utf-8").read().strip()
            if value in ("loop", "order", "single", "shuffle"):
                return value
        return "loop"

    def _save_mode(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(MODE_PATH, "w", encoding="utf-8") as handle:
            handle.write(self.play_mode)

    def _cycle_mode(self):
        order = ("loop", "order", "single", "shuffle")
        self.play_mode = order[(order.index(self.play_mode) + 1) % len(order)]
        self._save_mode()
        self._apply_mode_button()
        self._status(self.mode_btn.get_tooltip_text())

    def _apply_mode_button(self):
        icon, tip = {
            "loop": ("media-playlist-repeat-symbolic", "列表循环：播完最后一首回到第一首"),
            "order": ("media-playlist-consecutive-symbolic", "列表播放：按列表顺序播放，播完停止"),
            "single": ("media-playlist-repeat-song-symbolic", "单曲循环：重复当前歌曲"),
            "shuffle": ("media-playlist-shuffle-symbolic", "随机播放：在当前列表里随机下一首"),
        }[self.play_mode]
        image = self.mode_btn.get_image()
        if image is not None:
            image.set_from_icon_name(icon, Gtk.IconSize.BUTTON)
        self.mode_btn.set_tooltip_text(tip)
        self._refresh_queue_popup()

    def _hide_queue(self):
        if self.queue_overlay is None:
            return
        self.queue_overlay.set_reveal_child(False)
        if getattr(self, "queue_catcher", None) is not None:
            self.queue_catcher.hide()

    def _queue_panel_contains(self, event):
        panel = self.queue_overlay.get_child()
        if panel is None or not panel.get_mapped():
            return False
        origin = panel.translate_coordinates(self.queue_catcher, 0, 0)
        if origin is None:
            return False
        x, y = origin
        width, height = panel.get_allocated_width(), panel.get_allocated_height()
        return x <= event.x <= x + width and y <= event.y <= y + height

    def _on_overlay_press(self, _catcher, event):
        if self.queue_overlay is None or not self.queue_overlay.get_reveal_child():
            return False
        if self._queue_panel_contains(event):
            return False
        self._hide_queue()
        return True

    def _show_queue(self):
        songs = [song for song in self.playing if isinstance(song, dict) and song.get("name")]
        if not songs:
            self._status("还没有正在播放的列表")
            return
        if self.queue_overlay.get_reveal_child():
            self._hide_queue()
            return
        self._refresh_queue_popup()
        self.queue_catcher.show()
        self.queue_overlay.show_all()
        self.queue_overlay.set_reveal_child(True)

    def _detail_back(self):
        return self._icon_button("go-previous-symbolic", self._go_back, "back-btn")

    def _build_album_page(self):
        back = self._detail_back()
        back.set_tooltip_text("返回")
        self.album_cover = Gtk.Image.new_from_icon_name("media-optical-symbolic", Gtk.IconSize.DIALOG)
        self.album_cover.set_size_request(168, 168)
        self.album_name = Gtk.Label(xalign=0)
        self.album_name.set_line_wrap(True)
        self.album_name.get_style_context().add_class("detail-name")
        self.album_artist = Gtk.Button(label="")
        self.album_artist.set_relief(Gtk.ReliefStyle.NONE)
        self.album_artist.set_halign(Gtk.Align.START)
        self.album_artist.get_style_context().add_class("bar-link")
        self.album_artist.connect("clicked", lambda *_: self._open_album_artist())
        self.album_meta = Gtk.Label(xalign=0)
        self.album_meta.set_line_wrap(True)
        self.album_meta.get_style_context().add_class("detail-meta")
        self.album_desc = Gtk.Label(xalign=0)
        self.album_desc.set_line_wrap(True)
        self.album_desc.set_line_wrap_mode(2)
        self.album_desc.set_max_width_chars(48)
        self.album_desc.set_selectable(True)
        self.album_desc.get_style_context().add_class("detail-meta")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        text.set_valign(Gtk.Align.CENTER)
        text.pack_start(self.album_name, False, False, 0)
        text.pack_start(self.album_artist, False, False, 0)
        text.pack_start(self.album_meta, False, False, 0)
        text.pack_start(self.album_desc, False, False, 6)
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        card.get_style_context().add_class("detail-card")
        card.pack_start(self.album_cover, False, False, 0)
        card.pack_start(text, True, True, 0)
        self.album_store = Gtk.ListStore(str, str, str, str, str, object, GdkPixbuf.Pixbuf, str)
        self.album_view = Gtk.TreeView(model=self.album_store, headers_visible=True)
        self.album_view.connect("row-activated", self._on_album_activate)
        self.album_view.connect("button-press-event", self._on_detail_press)
        index_cell = Gtk.CellRendererText(xalign=1)
        index_col = Gtk.TreeViewColumn("#", index_cell, text=0)
        index_col.set_fixed_width(52)
        index_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        title_cell = Gtk.CellRendererText(ellipsize=3)
        title_col = Gtk.TreeViewColumn("歌曲", title_cell, text=1)
        title_col.set_expand(True)
        artist_cell = Gtk.CellRendererText(ellipsize=3)
        artist_col = Gtk.TreeViewColumn("歌手", artist_cell, text=2)
        artist_col.set_fixed_width(180)
        artist_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        duration_cell = Gtk.CellRendererText()
        duration_col = Gtk.TreeViewColumn("时长", duration_cell, text=4)
        duration_col.set_fixed_width(72)
        duration_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        self.album_view.append_column(index_col)
        self.album_view.append_column(title_col)
        self.album_view.append_column(artist_col)
        self.album_view.append_column(duration_col)
        songs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        songs.set_margin_top(16)
        song_label = Gtk.Label(label="歌曲", xalign=0)
        song_label.get_style_context().add_class("section-label")
        song_scroll = Gtk.ScrolledWindow()
        song_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        song_scroll.set_vexpand(True)
        song_scroll.add(self.album_view)
        songs.pack_start(song_label, False, False, 0)
        songs.pack_start(song_scroll, True, True, 0)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.set_margin_start(18)
        body.set_margin_end(18)
        body.set_margin_bottom(12)
        body.pack_start(card, False, False, 0)
        body.pack_start(songs, True, True, 0)
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bar.set_margin_top(6)
        bar.pack_start(back, False, False, 8)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.pack_start(bar, False, False, 0)
        page.pack_start(body, True, True, 0)
        self.album_page = page

    def _build_artist_page(self):
        back = self._detail_back()
        back.set_tooltip_text("返回")
        self.artist_avatar = Gtk.Image.new_from_icon_name("avatar-default-symbolic", Gtk.IconSize.DIALOG)
        self.artist_avatar.set_size_request(132, 132)
        self.artist_name = Gtk.Label(xalign=0)
        self.artist_name.set_line_wrap(True)
        self.artist_name.get_style_context().add_class("detail-name")
        self.artist_alias = Gtk.Label(xalign=0)
        self.artist_alias.set_line_wrap(True)
        self.artist_alias.get_style_context().add_class("detail-meta")
        self.artist_counts = Gtk.Label(xalign=0)
        self.artist_counts.get_style_context().add_class("detail-meta")
        self.artist_brief = Gtk.Label(xalign=0)
        self.artist_brief.set_line_wrap(True)
        self.artist_brief.set_line_wrap_mode(2)
        self.artist_brief.set_max_width_chars(48)
        self.artist_brief.set_selectable(True)
        self.artist_brief.get_style_context().add_class("detail-meta")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        text.set_valign(Gtk.Align.CENTER)
        text.pack_start(self.artist_name, False, False, 0)
        text.pack_start(self.artist_alias, False, False, 0)
        text.pack_start(self.artist_counts, False, False, 0)
        text.pack_start(self.artist_brief, False, False, 6)
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        card.get_style_context().add_class("detail-card")
        card.pack_start(self.artist_avatar, False, False, 0)
        card.pack_start(text, True, True, 0)
        self.artist_album_box = Gtk.FlowBox()
        self.artist_album_box.set_max_children_per_line(6)
        self.artist_album_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.artist_album_box.set_homogeneous(True)
        self.artist_album_box.set_column_spacing(12)
        self.artist_album_box.set_row_spacing(12)
        self.artist_store = Gtk.ListStore(str, str, str, str, str, object, GdkPixbuf.Pixbuf, str)
        self.artist_view = Gtk.TreeView(model=self.artist_store, headers_visible=True)
        self.artist_view.connect("row-activated", self._on_artist_activate)
        self.artist_view.connect("button-press-event", self._on_detail_press)
        index_cell = Gtk.CellRendererText(xalign=1)
        index_col = Gtk.TreeViewColumn("#", index_cell, text=0)
        index_col.set_fixed_width(52)
        index_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        title_cell = Gtk.CellRendererText(ellipsize=3)
        title_col = Gtk.TreeViewColumn("热门歌曲", title_cell, text=1)
        title_col.set_expand(True)
        album_cell = Gtk.CellRendererText(ellipsize=3)
        album_col = Gtk.TreeViewColumn("专辑", album_cell, text=3)
        album_col.set_fixed_width(180)
        album_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        duration_cell = Gtk.CellRendererText()
        duration_col = Gtk.TreeViewColumn("时长", duration_cell, text=4)
        duration_col.set_fixed_width(72)
        duration_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        self.artist_view.append_column(index_col)
        self.artist_view.append_column(title_col)
        self.artist_view.append_column(album_col)
        self.artist_view.append_column(duration_col)
        album_label = Gtk.Label(label="专辑", xalign=0)
        album_label.get_style_context().add_class("section-label")
        album_label.set_margin_top(18)
        song_label = Gtk.Label(label="热门歌曲", xalign=0)
        song_label.get_style_context().add_class("section-label")
        song_label.set_margin_top(16)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_margin_bottom(16)
        content.pack_start(card, False, False, 0)
        content.pack_start(album_label, False, False, 0)
        content.pack_start(self.artist_album_box, False, False, 0)
        content.pack_start(song_label, False, False, 0)
        content.pack_start(self.artist_view, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(content)
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bar.set_margin_top(6)
        bar.pack_start(back, False, False, 8)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.pack_start(bar, False, False, 0)
        page.pack_start(scroll, True, True, 0)
        self.artist_page = page

    def _open_album_artist(self):
        artist = getattr(self, "_album_artist", None) or {}
        if artist.get("id"):
            self._open_artist(artist["id"], artist.get("name"))

    def _show_album_page(self, data, songs):
        data = data or {}
        artist = data.get("artist") or {}
        self._album_artist = artist
        self.album_name.set_text(data.get("name") or "专辑")
        self.album_artist.set_label(artist.get("name") or "")
        self.album_artist.set_sensitive(bool(artist.get("id")))
        pieces = []
        if data.get("company"):
            pieces.append(data["company"])
        if data.get("publish"):
            pieces.append(str(data["publish"]))
        pieces.append(f"{len(songs)} 首")
        self.album_meta.set_text(" · ".join(pieces))
        desc = (data.get("description") or "").strip()
        self.album_desc.set_text(desc[:180] + ("…" if len(desc) > 180 else ""))
        self.album_desc.set_visible(bool(desc))
        self.album_store.clear()
        for index, song in enumerate(songs, start=1):
            self.album_store.append([
                f"{index:02d}",
                song.get("name") or "",
                song.get("artist") or "",
                song.get("album") or data.get("name") or "",
                fmt_time(song.get("duration")),
                song,
                self._cover_placeholder(),
                self._vip_mark(song),
            ])
        cover = data.get("cover")
        if cover:
            self._bg(lambda url=cover: self._set_remote_image(url, self.album_cover, 168))
        self._enter_page("album")
        self._status(f"{data.get('name') or '专辑'} · {len(songs)} 首")
        return False

    def _on_album_activate(self, _view, path, _column):
        songs = [row[5] for row in self.album_store if isinstance(row[5], dict)]
        index = path.get_indices()[0]
        if not songs or index >= len(songs):
            return
        self.playing = songs
        self.playing_title = self.album_name.get_text() or "专辑"
        self.playing_source = None
        self._play_from_playing(index)

    def _build_comment_page(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        back = self._icon_button("go-previous-symbolic", lambda: self._show_page("list" if len(self.store) else "home"), "back-btn")
        back.set_tooltip_text("返回")
        self.comment_title = Gtk.Label(xalign=0)
        self.comment_title.get_style_context().add_class("heading")
        self.comment_count = Gtk.Label(xalign=0)
        self.comment_count.get_style_context().add_class("dim")
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        titles.pack_start(self.comment_title, False, False, 0)
        titles.pack_start(self.comment_count, False, False, 0)
        self.comment_hot = Gtk.Button(label="精彩评论")
        self.comment_hot.get_style_context().add_class("text-btn")
        self.comment_hot.get_style_context().add_class("on")
        self.comment_hot.set_relief(Gtk.ReliefStyle.NONE)
        self.comment_hot.connect("clicked", lambda *_: self._load_comment_tab("hot"))
        self.comment_latest = Gtk.Button(label="最新评论")
        self.comment_latest.get_style_context().add_class("text-btn")
        self.comment_latest.set_relief(Gtk.ReliefStyle.NONE)
        self.comment_latest.connect("clicked", lambda *_: self._load_comment_tab("latest"))
        more = Gtk.Button(label="更多")
        more.get_style_context().add_class("text-btn")
        more.set_relief(Gtk.ReliefStyle.NONE)
        more.connect("clicked", lambda *_: self._comment_more())
        bar.pack_start(back, False, False, 8)
        bar.pack_start(titles, True, True, 0)
        bar.pack_end(more, False, False, 8)
        bar.pack_end(self.comment_latest, False, False, 0)
        bar.pack_end(self.comment_hot, False, False, 0)
        self.comment_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.comment_box.set_margin_top(4)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.comment_box)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.get_style_context().add_class("comment-page")
        page.pack_start(bar, False, False, 6)
        page.pack_start(scroll, True, True, 0)
        self.comment_page = page
        self.comment_tab = "hot"

    def _open_comments(self, song=None):
        song = song or self.current_song
        if not song or not song.get("id"):
            self._status("先选一首歌再看评论")
            return
        self.comment_song = song
        self.comment_offset = 0
        self.comment_title.set_text(song.get("name") or "评论")
        self.comment_count.set_text("评论加载中")
        self._show_page("comments")
        self._status("正在加载评论…")
        self._bg(lambda: self._fetch_comments(song, 0))

    def _load_comment_tab(self, tab):
        self.comment_tab = tab
        for name, button in (("hot", self.comment_hot), ("latest", self.comment_latest)):
            ctx = button.get_style_context()
            if name == tab:
                ctx.add_class("on")
            else:
                ctx.remove_class("on")
        self._render_comments()

    def _comment_more(self):
        song = self.comment_song
        if not song:
            return
        self.comment_offset += 20
        self._bg(lambda: self._fetch_comments(song, self.comment_offset))

    def _fetch_comments(self, song, offset):
        try:
            data = api.comments(song["id"], offset=offset, cookie=self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        self.comment_data = data
        GLib.idle_add(self._render_comments)
        GLib.idle_add(self._status, f"评论 {data['total']} 条")

    def _render_comments(self):
        data = getattr(self, "comment_data", None) or {}
        rows = data.get(self.comment_tab) or []
        for child in self.comment_box.get_children():
            self.comment_box.remove(child)
        total = data.get("total") or 0
        tab = "精彩评论" if self.comment_tab == "hot" else "最新评论"
        self.comment_count.set_text(f"{tab} · {total} 条" if total else tab)
        if not rows:
            empty = Gtk.Label(label="还没有评论")
            empty.set_margin_top(48)
            empty.get_style_context().add_class("dim")
            self.comment_box.pack_start(empty, False, False, 0)
        for item in rows:
            self.comment_box.pack_start(self._comment_card(item), False, False, 0)
        self.comment_box.show_all()
        return False

    def _comment_card(self, item):
        avatar = Gtk.Image.new_from_icon_name("avatar-default-symbolic", Gtk.IconSize.DND)
        avatar.set_size_request(36, 36)
        avatar.set_valign(Gtk.Align.START)
        if item.get("avatar"):
            self._bg(lambda url=item["avatar"], widget=avatar: self._set_remote_image(url, widget, 36, rounded=True))
        name = Gtk.Label(label=item.get("nickname") or "用户", xalign=0)
        name.get_style_context().add_class("comment-name")
        name.set_ellipsize(3)
        when = Gtk.Label(label=fmt_comment_time(item.get("time")), xalign=0)
        when.get_style_context().add_class("dim")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.pack_start(name, False, False, 0)
        head.pack_start(when, False, False, 0)
        body = Gtk.Label(label=item.get("content") or "", xalign=0)
        body.set_line_wrap(True)
        body.set_line_wrap_mode(2)
        body.set_max_width_chars(48)
        body.set_selectable(True)
        body.get_style_context().add_class("comment-body")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text.pack_start(head, False, False, 0)
        text.pack_start(body, False, False, 0)
        liked = Gtk.Label(label=f"♡ {item.get('liked') or 0}")
        liked.get_style_context().add_class("dim")
        liked.set_valign(Gtk.Align.START)
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        card.get_style_context().add_class("comment-card")
        card.pack_start(avatar, False, False, 0)
        card.pack_start(text, True, True, 0)
        card.pack_end(liked, False, False, 0)
        return card

    def _build_download_page(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        back = self._icon_button("go-previous-symbolic", lambda: self._show_page("list" if len(self.store) else "home"), "back-btn")
        back.set_tooltip_text("返回")
        title = Gtk.Label(label="下载管理", xalign=0)
        title.get_style_context().add_class("heading")
        bar.pack_start(back, False, False, 8)
        bar.pack_start(title, False, False, 0)
        self.download_store = Gtk.ListStore(str, str, str, str)
        view = Gtk.TreeView(model=self.download_store, headers_visible=True)
        for idx, name, width in ((0, "歌曲", 200), (1, "状态", 90), (2, "音质", 140), (3, "文件", 240)):
            column = Gtk.TreeViewColumn(name, Gtk.CellRendererText(ellipsize=3), text=idx)
            column.set_min_width(width)
            view.append_column(column)
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.pack_start(bar, False, False, 6)
        page.pack_start(scroll, True, True, 0)
        self.download_page = page

    def _enqueue_download(self, song):
        if not song or not song.get("id"):
            self._status("没有可下载的歌曲")
            return
        self.downloads.append({
            "song": song,
            "status": "等待",
            "path": "",
            "quality": self.quality,
            "level": "",
        })
        self._refresh_download_view()
        self._status(f"已加入下载：{song.get('name') or ''} · {self._quality_name(self.quality)}")
        if self.download_worker is None or not self.download_worker.is_alive():
            self.download_worker = threading.Thread(target=self._download_loop, daemon=True)
            self.download_worker.start()

    def _refresh_download_view(self):
        if not hasattr(self, "download_store"):
            return False
        self.download_store.clear()
        for item in self.downloads:
            song = item["song"]
            level = item.get("level") or item.get("quality") or ""
            self.download_store.append([
                song.get("name") or "",
                item.get("status") or "",
                self._quality_name(level),
                os.path.basename(item.get("path") or ""),
            ])
        return False

    def _download_loop(self):
        for item in self.downloads:
            if item.get("status") not in ("等待",):
                continue
            item["status"] = "下载中"
            GLib.idle_add(self._refresh_download_view)
            try:
                path, level = self._download_one(item["song"], item.get("quality") or self.quality)
            except Exception as exc:
                item["status"] = f"失败：{exc}"
                GLib.idle_add(self._notify, "下载失败", item["song"].get("name") or "")
                GLib.idle_add(self._refresh_download_view)
                continue
            item["status"] = "完成"
            item["path"] = path
            item["level"] = level
            self._index_local(path, item["song"])
            GLib.idle_add(self._notify, "下载完成", os.path.basename(path))
            GLib.idle_add(self._refresh_download_view)

    def _quality_name(self, level):
        for key, name, _hint in api.QUALITIES:
            if key == level:
                return name
        if level == "local":
            return "本地文件"
        return api.QUALITY_LABEL.get(level, level or "")

    def _download_one(self, song, level):
        # 下载档位是加入队列时播放条上的音质。接口按账号权限降级，实际档位记在返回值里。
        info = api.song_url(song["id"], level=level, cookie=self.cookie)
        if not info or not info.get("url"):
            raise api.ApiError("没有可下载地址")
        got = info.get("level") or level
        folder = os.path.join(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC) or os.path.expanduser("~/Music"), "网易云音乐")
        os.makedirs(folder, exist_ok=True)
        ext = "".join(ch for ch in str(info.get("type") or "mp3") if ch.isalnum()) or "mp3"
        raw_name = f"{song.get('artist') or '未知'} - {song.get('name') or song['id']}"
        raw_name = raw_name.replace("/", " ").replace("\\", " ").replace("\x00", "").strip(" .")
        name = (raw_name or str(song["id"])) + "." + ext
        dest = os.path.join(folder, name)
        if os.path.commonpath((folder, os.path.abspath(dest))) != os.path.abspath(folder):
            raise OSError("下载文件名无效")
        req = urllib.request.Request(_https_media_url(info["url"]), headers={"User-Agent": api.UA, "Referer": "https://music.163.com/"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest + ".part", "wb") as handle:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                handle.write(chunk)
        os.replace(dest + ".part", dest)
        self._write_audio_tags(dest, song)
        return dest, got

    def _write_audio_tags(self, path, song):
        # 只写 ID3 标题和歌手。没有额外依赖，失败也不影响文件本身。
        if not path.lower().endswith(".mp3"):
            return
        title = (song.get("name") or "").encode("utf-8")
        artist = (song.get("artist") or "").encode("utf-8")
        frames = b"TIT2" + self._id3_text(title) + b"TPE1" + self._id3_text(artist)
        tag = b"ID3" + bytes([3, 0, 0]) + self._synchsafe(len(frames)) + frames
        with open(path, "rb") as handle:
            body = handle.read()
        if body.startswith(b"ID3"):
            return
        with open(path, "wb") as handle:
            handle.write(tag + body)

    @staticmethod
    def _id3_text(text):
        data = b"\x03" + text
        size = len(data).to_bytes(4, "big")
        return size + b"\x00\x00" + data

    @staticmethod
    def _synchsafe(value):
        return bytes((
            (value >> 21) & 0x7F,
            (value >> 14) & 0x7F,
            (value >> 7) & 0x7F,
            value & 0x7F,
        ))

    def _index_local(self, path, song):
        self.local_index[str(song.get("id"))] = path
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            index_path = os.path.join(DATA_DIR, "local-index.json")
            current = {}
            if os.path.exists(index_path):
                current = json.loads(open(index_path, encoding="utf-8").read())
            current[str(song.get("id"))] = path
            with open(index_path, "w", encoding="utf-8") as handle:
                json.dump(current, handle, ensure_ascii=False)
        except (OSError, ValueError):
            pass

    def _local_file(self, song):
        if not self.local_index:
            path = os.path.join(DATA_DIR, "local-index.json")
            try:
                self.local_index = json.loads(open(path, encoding="utf-8").read())
            except (OSError, ValueError):
                self.local_index = {}
        found = self.local_index.get(str(song.get("id")))
        if not found or not os.path.isfile(found):
            return ""
        music = os.path.realpath(
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC) or os.path.expanduser("~/Music")
        )
        target = os.path.realpath(found)
        if os.path.commonpath((music, target)) != music:
            return ""
        return target

    def _build_queue_overlay(self):
        # 嵌在主窗口右下角，不另开窗口。Wayland 会忽略独立窗口的 move，还会画出标题栏。
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        panel.get_style_context().add_class("queue-overlay")
        panel.set_size_request(320, 360)
        panel.set_margin_end(12)
        panel.set_margin_bottom(12)
        panel.set_halign(Gtk.Align.END)
        panel.set_valign(Gtk.Align.END)
        self.queue_heading = Gtk.Label(xalign=0)
        self.queue_heading.set_margin_start(12)
        self.queue_heading.set_margin_top(8)
        self.queue_heading.set_margin_bottom(2)
        self.queue_heading.set_margin_end(12)
        self.queue_heading.set_ellipsize(3)
        self.queue_heading.get_style_context().add_class("queue-head")
        panel.pack_start(self.queue_heading, False, False, 0)
        # 0 序号  1 歌名  2 歌手  3 id
        self.queue_store = Gtk.ListStore(str, str, str, str)
        view = Gtk.TreeView(model=self.queue_store, headers_visible=True)
        view.set_enable_search(False)
        view.connect("row-activated", self._on_queue_activate)
        view.connect("button-press-event", self._on_queue_press)
        index_cell = Gtk.CellRendererText(xalign=1)
        index_cell.set_padding(4, 2)
        index_cell.set_property("scale", 0.86)
        index_col = Gtk.TreeViewColumn("#", index_cell, text=0)
        index_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        index_col.set_fixed_width(36)
        index_col.set_cell_data_func(index_cell, self._paint_index)
        view.append_column(index_col)
        title = Gtk.CellRendererText(ellipsize=3)
        title.set_padding(4, 2)
        title.set_property("scale", 0.90)
        artist = Gtk.CellRendererText(ellipsize=3)
        artist.set_padding(6, 2)
        artist.set_property("scale", 0.84)
        column = Gtk.TreeViewColumn("标题")
        column.pack_start(title, True)
        column.pack_start(artist, False)
        column.add_attribute(title, "text", 1)
        column.add_attribute(artist, "text", 2)
        column.set_expand(True)
        column.set_cell_data_func(title, self._paint_queue_title)
        column.set_cell_data_func(artist, self._paint_queue_artist)
        view.append_column(column)
        scroll = Gtk.ScrolledWindow()
        scroll.set_margin_start(4)
        scroll.set_margin_end(4)
        scroll.set_margin_bottom(6)
        scroll.get_style_context().add_class("queue-list")
        scroll.add(view)
        panel.pack_start(scroll, True, True, 0)
        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        revealer.set_transition_duration(180)
        revealer.add(panel)
        revealer.set_halign(Gtk.Align.END)
        revealer.set_valign(Gtk.Align.END)
        revealer.set_reveal_child(False)
        self.queue_overlay = revealer
        self.queue_view = view

    def _refresh_queue_popup(self):
        if self.queue_overlay is None:
            return
        names = {"loop": "列表循环", "order": "列表播放", "single": "单曲循环", "shuffle": "随机播放"}
        self.queue_heading.set_text(f"{self.playing_title or '当前播放'} · {names.get(self.play_mode, '')}")
        self.queue_store.clear()
        index = 0
        for song in self.playing:
            if not isinstance(song, dict) or not song.get("name"):
                continue
            index += 1
            self.queue_store.append([
                f"{index:02d}",
                song.get("name") or "",
                song.get("artist") or "",
                str(song.get("id") or ""),
            ])
        if 0 <= self.playing_index < len(self.queue_store):
            self.queue_view.set_cursor(Gtk.TreePath(self.playing_index))
            self.queue_view.scroll_to_cell(Gtk.TreePath(self.playing_index), None, True, 0.4, 0)

    def _on_queue_activate(self, _view, path, _column):
        self._play_from_playing(path.get_indices()[0])

    def _on_queue_press(self, view, event):
        if event.button != 3:
            return False
        path = view.get_path_at_pos(int(event.x), int(event.y))
        if not path:
            return False
        index = path[0].get_indices()[0]
        if index < 0 or index >= len(self.playing):
            return False
        song = self.playing[index]
        if not isinstance(song, dict) or not song.get("id"):
            return False
        view.get_selection().select_path(path[0])
        self._song_menu(song, index).popup_at_pointer(event)
        return True

    def _save_state(self):
        songs = [song for song in self.playing if song.get("id") and "artist" in song]
        if not songs:
            return
        position = self.player.cached_pos if self.current_song else 0
        if position <= 0:
            position = int(getattr(self, "_resume_at", 0) or 0)
        duration = self.player.duration_ms() or (self.current_song or {}).get("duration") or 0
        payload = {
            "title": self.playing_title,
            "source": getattr(self, "playing_source", None),
            "index": self.playing_index,
            "position": position,
            "duration": duration,
            "quality": self.quality,
            "mode": self.play_mode,
            "songs": songs,
        }
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, STATE_PATH)

    def _autosave(self):
        self._save_state()
        return True

    def _restore_state(self):
        if not os.path.exists(STATE_PATH):
            return
        try:
            payload = json.loads(open(STATE_PATH, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            return
        songs = [song for song in payload.get("songs") or [] if song.get("id")]
        if not songs:
            return
        self.playing = songs
        self.playing_title = payload.get("title") or "当前播放"
        self.playing_index = payload.get("index") if isinstance(payload.get("index"), int) else 0
        self.playing_index = min(max(self.playing_index, 0), len(songs) - 1)
        self.current_song = songs[self.playing_index]
        self.playing_source = payload.get("source")
        self.title_btn.set_text(self.current_song.get("name") or "未在播放")
        self._set_bar_artist(self.current_song)
        self._resume_at = int(payload.get("position") or 0)
        self._resume_duration = int(payload.get("duration") or self.current_song.get("duration") or 0)
        self._show_paused_progress()
        self._status(f"已恢复 {self.current_song.get('name') or ''} · {self.playing_title} · 已暂停")
        if self.current_song.get("cover"):
            self._bg(lambda: self._set_remote_image(self.current_song["cover"], self.cover, 46))
        self._set_play_icon(False)
        self._refresh_like_button()

    def _show_paused_progress(self):
        """还没开播时，用上次记下的进度画进度条和时间。"""
        song = self.current_song or {}
        elapsed = int(getattr(self, "_resume_at", 0) or 0)
        total = int(getattr(self, "_resume_duration", 0) or song.get("duration") or 0)
        if total <= 0:
            return False
        self.scale.set_value(min(1000, elapsed * 1000 / total))
        self._place_time_pill(elapsed, total)
        return False

    def _place_time_pill(self, elapsed, total):
        """时间胶囊跟着进度滑块走，贴在进度条中间偏上。"""
        text = f"{fmt_time(elapsed)} / {fmt_time(total)}"
        if text == getattr(self, "_time_text", None) and not self.seeking:
            return False
        self._time_text = text
        self.time_label.set_text(text)
        width = self.scale.get_allocated_width()
        if width <= 24 or not total:
            self.time_label.set_halign(Gtk.Align.CENTER)
            return False
        fraction = max(0.0, min(1.0, float(elapsed) / float(total)))
        pill = self.time_label.get_allocated_width() or 92
        x = int(fraction * (width - 16)) - pill // 2
        x = max(0, min(width - pill, x))
        self.time_label.set_halign(Gtk.Align.START)
        self.time_label.set_margin_start(x)
        return False

    def _resume_playback(self, song, position):
        try:
            info = api.song_url(song["id"], level=self.quality, cookie=self.cookie)
            text = api.lyric(song["id"], cookie=self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        if not info:
            GLib.idle_add(self._status, f"没能恢复「{song.get('name') or ''}」的播放地址")
            return
        self.player.play(info["url"])
        if position > 1500:
            GLib.timeout_add(400, self._seek_after_switch, song, position, 0)
        GLib.idle_add(self._started, song, api.parse_lrc(text), info)

    def _show_liked(self):
        songs = api.liked_songs(self.cookie)
        GLib.idle_add(self.heading.set_text, "我喜欢的音乐")
        GLib.idle_add(self._set_songs, songs, f"云端返回 {len(songs)} 首。若和手机不一致，点左侧「刷新收藏」。")

    def _show_daily(self):
        songs = api.recommend_songs(self.cookie)
        GLib.idle_add(self.heading.set_text, "每日推荐")
        GLib.idle_add(self._set_songs, songs, f"每日推荐 {len(songs)} 首")

    def _vip_mark(self, song):
        """fee 为 1 是 VIP 专享。0 免费，8 是可以试听的非会员曲。"""
        if not isinstance(song, dict):
            return ""
        return "VIP" if int(song.get("fee") or 0) == 1 else ""

    def _row_active(self, model, tree_iter):
        item = model.get_value(tree_iter, 5) if model.get_n_columns() > 5 else None
        current = self.current_song or {}
        if isinstance(item, dict) and current.get("id") and item.get("id") == current.get("id"):
            return True
        if model is getattr(self, "queue_store", None) and self.playing_index >= 0:
            path = model.get_path(tree_iter)
            return path is not None and path.get_indices()[0] == self.playing_index
        return False

    def _paint_index(self, _column, cell, model, tree_iter, _data):
        active = self._row_active(model, tree_iter)
        cell.set_property("foreground", RED if active else "#B0B0B6")
        cell.set_property("weight", 700 if active else 400)
        if model is not getattr(self, "queue_store", None):
            cell.set_property("font-desc", Pango.FontDescription.from_string("Noto Sans CJK SC 9"))

    def _paint_title(self, _column, cell, model, tree_iter, _data):
        active = self._row_active(model, tree_iter)
        cell.set_property("foreground", RED if active else "#222222")
        cell.set_property("weight", 700 if active else 600)
        cell.set_property("font-desc", Pango.FontDescription.from_string("Noto Sans CJK SC 9"))

    def _paint_vip(self, _column, cell, model, tree_iter, _data):
        cell.set_property("foreground", RED)
        cell.set_property("weight", 700)
        cell.set_property("scale", 0.82)
        cell.set_property("font-desc", Pango.FontDescription.from_string("Noto Sans CJK SC 9"))

    def _paint_queue_title(self, _column, cell, model, tree_iter, _data):
        active = self._row_active(model, tree_iter)
        cell.set_property("foreground", RED if active else "#222222")
        cell.set_property("weight", 600 if active else 500)
        cell.set_property("scale", 0.90)

    def _paint_queue_artist(self, _column, cell, model, tree_iter, _data):
        active = self._row_active(model, tree_iter)
        cell.set_property("foreground", RED if active else "#8E8E93")
        cell.set_property("weight", 500 if active else 400)
        cell.set_property("scale", 0.84)

    def _fit_song_columns(self, scroll, allocation):
        """标题列约占内容区一半再少一成，时长左对齐并给滚动条留空。"""
        if not hasattr(self, "title_col"):
            return False
        width = allocation.width
        if width < 240 or width == getattr(self, "_song_width", 0):
            return False
        self._song_width = width
        # 按用户调好的比例：标题约占一半，专辑约占三成，时长靠右并给滚动条留空。
        title = max(220, int(width * 0.50))
        album = max(140, int(width * 0.30))
        duration = max(86, width - 52 - title - album)
        self.title_col.set_fixed_width(title)
        self.album_col.set_fixed_width(album)
        self.view.get_columns()[-1].set_fixed_width(duration)
        return False

    def _paint_artist(self, _column, cell, model, tree_iter, _data):
        active = self._row_active(model, tree_iter)
        cell.set_property("foreground", RED if active else "#8E8E93")
        cell.set_property("weight", 600 if active else 400)
        if model is not getattr(self, "queue_store", None):
            cell.set_property("font-desc", Pango.FontDescription.from_string("Noto Sans CJK SC 9"))

    def _paint_meta(self, _column, cell, model, tree_iter, _data):
        active = self._row_active(model, tree_iter)
        cell.set_property("foreground", RED if active else "#8E8E93")
        cell.set_property("font-desc", Pango.FontDescription.from_string("Noto Sans CJK SC 9"))

    def _set_playlists(self, playlists):
        self.store.clear()
        for index, item in enumerate(playlists, start=1):
            self.store.append([
                f"{index:02d}",
                item["name"],
                f"{item['count']} 首",
                "歌单",
                "",
                item,
                self._cover_placeholder(),
                "",
            ])
        self._status(f"{len(playlists)} 个歌单，双击打开")
        return False

    def _set_songs(self, songs, status, remember=True):
        self.store.clear()
        placeholder = self._cover_placeholder()
        for index, song in enumerate(songs, start=1):
            self.store.append([
                f"{index:02d}",
                song.get("name") or "",
                song.get("artist") or "",
                song.get("album") or "",
                fmt_time(song.get("duration")),
                song,
                placeholder,
                self._vip_mark(song),
            ])
        self._status(status)
        self._cover_jobs = set()
        self._list_token = getattr(self, "_list_token", 0) + 1
        self._paint_cached_covers()
        self._schedule_covers()
        return False

    def _append_songs(self, songs, status, token):
        """后一页回来时接上，不把已经画出来的第一页清掉。"""
        if token != getattr(self, "_playlist_token", None):
            return False
        placeholder = self._cover_placeholder()
        existing = len(self.store)
        if existing > len(songs):
            return False
        for index, song in enumerate(songs[existing:], start=existing + 1):
            self.store.append([
                f"{index:02d}",
                song.get("name") or "",
                song.get("artist") or "",
                song.get("album") or "",
                fmt_time(song.get("duration")),
                song,
                placeholder,
                self._vip_mark(song),
            ])
        self._status(status)
        self._paint_cached_covers()
        self._schedule_covers()
        return False

    def _paint_cached_covers(self):
        """缓存里已有的封面先画上，不用等接口回来。"""
        for row in self.store:
            song = row[5]
            if not isinstance(song, dict) or not song.get("cover"):
                continue
            path = cover_cache_path(song["cover"], 36)
            if not os.path.exists(path) or os.path.getsize(path) < 32:
                continue
            try:
                row[6] = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 36, 36, False)
            except GLib.Error:
                continue
        return False

    def _schedule_covers(self):
        if getattr(self, "_cover_timer", None):
            GLib.source_remove(self._cover_timer)
        self._cover_timer = GLib.timeout_add(80, self._fill_visible_covers)
        return False

    def _cover_placeholder(self):
        if getattr(self, "_placeholder", None) is None:
            self._placeholder = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 36, 36)
            self._placeholder.fill(0xF0F0F2FF)
        return self._placeholder

    def _visible_rows(self):
        if not self.view.get_realized() or len(self.store) == 0:
            return range(0, min(40, len(self.store)))
        visible = self.view.get_visible_range()
        if not visible:
            return range(0, min(40, len(self.store)))
        start = max(0, visible[0].get_indices()[0] - 2)
        end = min(len(self.store), visible[1].get_indices()[0] + 6)
        return range(start, end)

    def _fill_visible_covers(self):
        self._cover_timer = None
        if self.stack.get_visible_child_name() != "list":
            return False
        songs = []
        for index in self._visible_rows():
            song = self.store[index][5]
            if not isinstance(song, dict) or not song.get("id") or song.get("artist") is None:
                continue
            if song.get("id") in self._cover_jobs:
                continue
            songs.append(song)
        if songs:
            for song in songs:
                self._cover_jobs.add(song.get("id"))
            token = getattr(self, "_list_token", 0)
            self._bg(lambda rows=songs, stamp=token: self._fill_covers(rows, stamp))
        return False

    def _fill_covers(self, songs, token=None):
        if token is not None and token != getattr(self, "_list_token", token):
            return
        pending = [song for song in songs if song.get("id")]
        if pending:
            try:
                # 只补没有封面的歌。已有地址不能拿旧接口重刷，旧接口现在不返回图片。
                api.attach_covers(pending, self.cookie)
            except api.ApiError:
                pass
        if token is not None and token != getattr(self, "_list_token", token):
            return
        for song in songs:
            url = song.get("cover")
            if not url:
                continue
            try:
                pix = load_pixbuf(url, 36, refresh=True)
            except Exception:
                continue
            if token is not None and token != getattr(self, "_list_token", token):
                return
            GLib.idle_add(self._set_row_cover, song.get("id"), pix, token)

    def _set_row_cover(self, song_id, pix, token=None):
        if token is not None and token != getattr(self, "_list_token", token):
            return False
        for row in self.store:
            item = row[5]
            if isinstance(item, dict) and str(item.get("id")) == str(song_id) and item.get("artist") is not None:
                row[6] = pix
        return False

    def _render_home(self, cards, playlists):
        for child in self.home_box.get_children():
            self.home_box.remove(child)
        title = Gtk.Label(label="推荐", xalign=0)
        title.get_style_context().add_class("heading")
        self.home_box.pack_start(title, False, False, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        for index, (cid, name) in enumerate(cards):
            row.pack_start(self._feature_card(name, CARD_COLORS[index % len(CARD_COLORS)], cid), True, True, 0)
        self.home_box.pack_start(row, False, False, 4)
        head = Gtk.Label(label="推荐歌单", xalign=0)
        head.get_style_context().add_class("heading")
        head.set_margin_top(12)
        self.home_box.pack_start(head, False, False, 0)
        grid = Gtk.FlowBox()
        grid.set_max_children_per_line(6)
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_homogeneous(True)
        grid.set_column_spacing(12)
        grid.set_row_spacing(12)
        for item in playlists[:12]:
            grid.add(self._cover_tile(item))
        self.home_box.pack_start(grid, False, False, 0)
        self.home_box.show_all()
        self._hide_queue()
        return False

    def _feature_card(self, name, color, playlist_id):
        """推荐榜单卡片。封面图里已有榜名，不再叠字。用按钮接收点击。"""
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_hexpand(False)
        button.set_halign(Gtk.Align.START)
        button.set_size_request(148, 78)
        button.set_tooltip_text(name)
        image = Gtk.Image()
        image.set_halign(Gtk.Align.CENTER)
        image.set_valign(Gtk.Align.CENTER)
        button.add(image)
        button.get_style_context().add_class("feature-card")
        button.connect("clicked", lambda *_: self._open_playlist(playlist_id, name))
        self._bg(lambda: self._load_feature_cover(image, playlist_id, color))
        return button

    def _load_feature_cover(self, image, playlist_id, color):
        cover = self._chart_cover(playlist_id)
        pix = self._feature_placeholder(color, 148, 78)
        if cover:
            try:
                loaded = load_pixbuf(cover, 148)
                loaded = loaded.scale_simple(148, 78, GdkPixbuf.InterpType.BILINEAR)
                pix = self._rounded_pixbuf(loaded, 8)
            except Exception:
                pass
        GLib.idle_add(self._apply_feature_cover, image, pix)

    def _apply_feature_cover(self, image, pix):
        if image.get_parent() is None:
            return False
        image.set_from_pixbuf(pix)
        return False

    def _feature_placeholder(self, color, width=176, height=88):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        ctx = cairo.Context(surface)
        red, green, blue = self._hex_rgb(color)
        ctx.set_source_rgb(red, green, blue)
        self._round_rect(ctx, 0, 0, width, height, 8)
        ctx.fill()
        return _pixbuf_from_surface(surface)

    def _rounded_pixbuf(self, pixbuf, radius):
        width, height = pixbuf.get_width(), pixbuf.get_height()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        ctx = cairo.Context(surface)
        self._round_rect(ctx, 0, 0, width, height, radius)
        ctx.clip()
        ctx.set_source_surface(self._surface_from_pixbuf(pixbuf), 0, 0)
        ctx.paint()
        return _pixbuf_from_surface(surface)

    def _surface_from_pixbuf(self, pixbuf):
        _ok, data = pixbuf.save_to_bufferv("png", [], [])
        return cairo.ImageSurface.create_from_png(io.BytesIO(data))

    def _hex_rgb(self, color):
        text = color.lstrip("#")
        return tuple(int(text[index:index + 2], 16) / 255 for index in (0, 2, 4))

    def _round_rect(self, ctx, x, y, width, height, radius):
        ctx.new_sub_path()
        ctx.arc(x + width - radius, y + radius, radius, -1.5708, 0)
        ctx.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
        ctx.arc(x + radius, y + height - radius, radius, 1.5708, 3.1416)
        ctx.arc(x + radius, y + radius, radius, 3.1416, 4.7124)
        ctx.close_path()

    def _cover_tile(self, item):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        image = Gtk.Image.new_from_icon_name("folder-music-symbolic", Gtk.IconSize.DIALOG)
        image.set_size_request(120, 120)
        name = Gtk.Label(label=item.get("name") or "", xalign=0)
        name.set_ellipsize(3)
        name.set_max_width_chars(14)
        name.get_style_context().add_class("cover-name")
        meta = Gtk.Label(label=f"{item.get('count') or 0} 首", xalign=0)
        meta.get_style_context().add_class("cover-meta")
        box.pack_start(image, False, False, 0)
        box.pack_start(name, False, False, 0)
        box.pack_start(meta, False, False, 0)
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.add(box)
        button.connect("clicked", lambda *_: self._open_playlist(item["id"], item["name"]))
        if item.get("cover"):
            self._bg(lambda url=item["cover"], widget=image: self._set_remote_image(url, widget, 120))
        return button

    def _set_remote_image(self, url, widget, size, rounded=False):
        try:
            pix = load_pixbuf(url, size, rounded=18 if rounded else 0)
        except Exception:
            return
        GLib.idle_add(widget.set_from_pixbuf, pix)

    def _cell_hit(self, view, x, y):
        hit = view.get_path_at_pos(int(x), int(y))
        if not hit:
            return None
        path, column, cell_x, _cell_y = hit
        if path.get_indices()[0] >= len(self.store):
            return None
        item = self.store[path][5]
        if not isinstance(item, dict) or item.get("artist") is None:
            return None
        if column is getattr(self, "album_col", None) and item.get("albumId"):
            return "album", item
        if column is getattr(self, "title_col", None) and item.get("artists"):
            artist_cell = column.get_cells()[-1]
            aligned = column.cell_get_position(artist_cell)
            if not aligned:
                return None
            offset, width = aligned
            pad = artist_cell.get_padding()[0]
            layout = view.create_pango_layout(item.get("artist") or "")
            font = artist_cell.get_property("font-desc")
            if font is not None:
                layout.set_font_description(font)
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            layout.set_width(max(1, (width - pad * 2) * Pango.SCALE))
            text_width = layout.get_pixel_size()[0]
            xalign = artist_cell.get_property("xalign")
            inner = max(0, width - pad * 2)
            start = offset + pad + int((inner - text_width) * xalign)
            if start <= cell_x <= start + text_width + 4:
                return "artist", item
        return None

    def _on_list_motion(self, view, event):
        hit = self._cell_hit(view, event.x, event.y)
        window = view.get_window()
        if window is None:
            return False
        if hit:
            window.set_cursor(Gdk.Cursor.new_from_name(window.get_display(), "pointer"))
            kind, item = hit
            if kind == "artist":
                view.set_tooltip_text(f"打开歌手：{item.get('artist') or ''}")
            else:
                view.set_tooltip_text(f"打开专辑：{item.get('album') or ''}")
        else:
            window.set_cursor(None)
            view.set_tooltip_text(None)
        return False

    def _on_list_leave(self, view, _event):
        window = view.get_window()
        if window is not None:
            window.set_cursor(None)
        view.set_tooltip_text(None)
        return False

    def _set_bar_artist(self, song):
        song = song or {}
        self.artist_btn.set_label(song.get("artist") or "未知歌手")
        child = self.artist_btn.get_child()
        if isinstance(child, Gtk.Label):
            child.set_ellipsize(3)
            child.set_max_width_chars(12)
            child.set_xalign(0)
        artists = [item for item in song.get("artists") or [] if item.get("id")]
        self.artist_btn.set_sensitive(bool(artists))

    def _open_current_artist(self):
        song = self.current_song or {}
        artists = [item for item in song.get("artists") or [] if item.get("id")]
        if not artists and song.get("artistId"):
            artists = [{"id": song.get("artistId"), "name": song.get("artist") or "歌手"}]
        if not artists:
            self._status("这首歌没有歌手主页")
            return
        if len(artists) == 1:
            self._open_artist(artists[0]["id"], artists[0].get("name"))
            return
        menu = Gtk.Menu()
        for artist in artists:
            item = Gtk.MenuItem(label=artist.get("name") or "歌手")
            item.connect(
                "activate",
                lambda _item, chosen=artist: self._open_artist(chosen.get("id"), chosen.get("name")),
            )
            menu.append(item)
        menu.show_all()
        menu.popup_at_widget(self.artist_btn, Gdk.Gravity.NORTH, Gdk.Gravity.SOUTH, None)

    def _enter_page(self, name):
        current = self.stack.get_visible_child_name()
        if current != name:
            self._page_stack = getattr(self, "_page_stack", [])
            self._page_stack.append(current)
        self._show_page(name)

    def _go_back(self):
        stack = getattr(self, "_page_stack", [])
        while stack and stack[-1] == self.stack.get_visible_child_name():
            stack.pop()
        self._show_page(stack.pop() if stack else "home")

    def _back_from_list(self):
        self._go_back()

    def _open_artist(self, artist_id, name):
        if not artist_id:
            self._status("这个名字没有歌手主页")
            return
        self._hide_queue()
        self._enter_page("artist")
        self.artist_name.set_text(name or "歌手")
        self.artist_alias.set_text("")
        self.artist_counts.set_text("正在读取歌手主页…")
        self.artist_brief.set_text("")
        self._status(f"正在打开{name or '歌手'}…")
        self._bg(lambda: self._load_artist(artist_id, name))

    def _load_artist(self, artist_id, name):
        try:
            data = api.artist_home(artist_id, self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        GLib.idle_add(self._show_artist_page, data)

    def _show_artist_page(self, data):
        data = data or {}
        self.artist_name.set_text(data.get("name") or "歌手")
        self.artist_alias.set_text(data.get("alias") or "")
        self.artist_alias.set_visible(bool(data.get("alias")))
        self.artist_counts.set_text(f"歌曲 {data.get('musicCount') or 0} · 专辑 {data.get('albumCount') or 0}")
        brief = (data.get("brief") or "").strip()
        self.artist_brief.set_text(brief[:220] + ("…" if len(brief) > 220 else ""))
        self.artist_brief.set_visible(bool(brief))
        for child in self.artist_album_box.get_children():
            self.artist_album_box.remove(child)
        for album in data.get("albums") or []:
            self.artist_album_box.add(self._album_chip(album))
        self.artist_album_box.show_all()
        self.artist_store.clear()
        songs = data.get("songs") or []
        for index, song in enumerate(songs, start=1):
            self.artist_store.append([
                f"{index:02d}",
                song.get("name") or "",
                song.get("artist") or "",
                song.get("album") or "",
                fmt_time(song.get("duration")),
                song,
                self._cover_placeholder(),
                self._vip_mark(song),
            ])
        avatar = data.get("avatar")
        if avatar:
            self._bg(lambda url=avatar: self._set_remote_image(url, self.artist_avatar, 132, rounded=True))
        self._status(f"{data.get('name') or '歌手'} · {len(songs)} 首热门")
        return False

    def _album_chip(self, album):
        image = Gtk.Image.new_from_icon_name("media-optical-symbolic", Gtk.IconSize.DIALOG)
        image.set_size_request(96, 96)
        name = Gtk.Label(label=album.get("name") or "专辑", xalign=0)
        name.set_ellipsize(3)
        name.set_max_width_chars(12)
        when = Gtk.Label(label=album.get("publish") or "", xalign=0)
        when.get_style_context().add_class("cover-meta")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class("album-chip")
        box.pack_start(image, False, False, 0)
        box.pack_start(name, False, False, 0)
        box.pack_start(when, False, False, 0)
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.add(box)
        button.connect("clicked", lambda *_: self._open_album(album.get("id"), album.get("name")))
        if album.get("cover"):
            self._bg(lambda url=album["cover"], widget=image: self._set_remote_image(url, widget, 96))
        return button

    def _on_artist_activate(self, _view, path, _column):
        songs = [row[5] for row in self.artist_store if isinstance(row[5], dict)]
        index = path.get_indices()[0]
        if not songs or index >= len(songs):
            return
        self.playing = songs
        self.playing_title = self.artist_name.get_text() or "歌手"
        self.playing_source = None
        self._play_from_playing(index)

    def _open_album(self, album_id, name):
        if not album_id:
            return
        self._hide_queue()
        self._show_album_page({"name": name or "专辑"}, [])
        self._status(f"正在打开专辑{name or ''}…")
        self._bg(lambda: self._load_album(album_id, name))

    def _load_album(self, album_id, name):
        try:
            data = api.album_detail(album_id, self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        GLib.idle_add(self._show_album_page, data, data.get("songs") or [])

    def _on_list_press(self, view, event):
        if event.button == 1:
            hit = self._cell_hit(view, event.x, event.y)
            if hit:
                kind, item = hit
                if kind == "artist":
                    self._open_artist(item.get("artistId"), item.get("artist"))
                else:
                    self._open_album(item.get("albumId"), item.get("album"))
                return True
        if event.button != 3:
            return False
        path = view.get_path_at_pos(int(event.x), int(event.y))
        if not path:
            return False
        item = self.store[path[0]][5]
        if not isinstance(item, dict) or item.get("artist") is None or not item.get("id"):
            return False
        view.get_selection().select_path(path[0])
        self._song_menu(item, path[0].get_indices()[0]).popup_at_pointer(event)
        return True

    def _on_detail_press(self, view, event):
        """歌手页、专辑页和主列表共用右键菜单。这些页的行不在播放队列里。"""
        if event.button != 3:
            return False
        path = view.get_path_at_pos(int(event.x), int(event.y))
        if not path:
            return False
        model = view.get_model()
        item = model[path[0]][5]
        if not isinstance(item, dict) or not item.get("id"):
            return False
        view.get_selection().select_path(path[0])
        self._song_menu(item, -1).popup_at_pointer(event)
        return True

    def _on_activate(self, _view, path, _column):
        item = self.store[path][5]
        if not item:
            return
        if item.get("artist") is not None and item.get("id"):
            self._play_index(path.get_indices()[0])
        elif item.get("id"):
            self._open_playlist(item["id"], item.get("name") or "歌单")

    def _play_from_playing(self, index):
        if index < 0 or index >= len(self.playing) or "artist" not in self.playing[index]:
            return
        self.playing_index = index
        self._play_song(self.playing[index])
        self._refresh_queue_popup()

    def _play_index(self, index):
        if index < 0 or index >= len(self.store):
            return
        song = self.store[index][5]
        if not isinstance(song, dict) or song.get("artist") is None or not song.get("id"):
            return
        self.playing = [
            row[5] for row in self.store
            if isinstance(row[5], dict) and row[5].get("artist") is not None and row[5].get("id")
        ]
        self.playing_title = self.heading.get_text() or "当前播放"
        self.playing_source = getattr(self, "_browsing_playlist", None)
        if self.playing_source:
            self._touch_playlist(self.playing_source)
        self.playing_index = next(
            (i for i, item in enumerate(self.playing) if item.get("id") == song.get("id")),
            0,
        )
        self._play_song(song)
        self._refresh_queue_popup()

    def _play_song(self, song):
        self.current_song = song
        self._resume_at = 0
        self._resume_used = True
        self.title_btn.set_text(song["name"])
        self._set_bar_artist(song)
        self.lyric_title.set_text(song["name"])
        self.lyric_artist.set_text(song["artist"] or "")
        self.lyric_buf.set_text("歌词加载中…")
        self._status(f"正在获取{api.QUALITY_LABEL.get(self.quality, '')}…")
        # 上一首的可播档不能带到这首。探测回来前先按偏好显示，不勾上一首的结果。
        self._rebuild_quality_menu([key for key, _name, _hint in api.QUALITIES], selected=self.quality)
        self._bg(lambda: self._start_song(song))
        if song.get("cover"):
            self._bg(lambda: self._set_remote_image(song["cover"], self.cover, 46))
        self.view.queue_draw()
        if self.queue_view is not None:
            self.queue_view.queue_draw()
        self._refresh_like_button()

    def _start_song(self, song):
        try:
            info = api.song_url(song["id"], level=self.quality, cookie=self.cookie)
            original, translated = api.lyric_pair(song["id"], cookie=self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        lines = api.merge_lrc(original, translated)
        local = self._local_file(song)
        if local:
            info = {
                "url": urllib.parse.urljoin("file:", urllib.request.pathname2url(local)),
                "level": "local",
                "br": 0,
                "type": os.path.splitext(local)[1].lstrip("."),
            }
        if not info:
            GLib.idle_add(self._no_url, song, lines)
            return
        self.player.play(info["url"])
        GLib.timeout_add(400, self._apply_saved_volume)
        GLib.idle_add(self._started, song, lines, info)
        GLib.idle_add(self._note_actual_quality, song, info)
        if not local:
            self._bg(lambda: self._refresh_quality_options(song, {info.get("level"): info}))

    def _note_actual_quality(self, song, info):
        self._apply_quality_state(song, info)
        return False

    def _apply_saved_volume(self):
        """开播后播放流才出现。把滑条上的音量套到这一条流，不改其他程序。"""
        stream = self._pulse_stream()
        if not stream:
            return False
        percent = f"{int(round(self.volume.get_value() * 100))}%"
        try:
            subprocess.check_call(
                ["pactl", "set-sink-input-volume", stream, percent],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return False

    def _started(self, song, lines, info):
        if self.current_song and self.current_song.get("id") != song.get("id"):
            return False
        self.lyrics = lines
        self._lyric_index = -1
        self._fill_lyrics(lines)
        level = info.get("level") or ""
        label = api.QUALITY_LABEL.get(level, level)
        note = "，已按账号权限降级" if level and level != self.quality else ""
        kbps = int((info.get("br") or 0) / 1000)
        self._status(f"正在播放 · {label} · {kbps}kbps {(info.get('type') or '').upper()}{note}")
        self._sync_play_icon()
        self._refresh_like_button()
        return False

    def _no_url(self, song, lines):
        self._fill_lyrics(lines)
        self._status(f"「{song['name']}」没有可播放地址。" + ("" if self.cookie else "请先登录。"))
        return False

    def _desk_lyric_wanted(self):
        try:
            payload = json.loads(open(LYRIC_STATE_PATH, encoding="utf-8").read())
            return bool(payload.get("open"))
        except (OSError, json.JSONDecodeError, TypeError):
            return False

    def _remember_desk_lyric(self, open_):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = LYRIC_STATE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"open": bool(open_)}, handle)
            os.replace(tmp, LYRIC_STATE_PATH)
        except OSError:
            pass

    def _toggle_desk_lyric(self):
        """歌词是单独的 XWayland 窗口。主窗口留在 Wayland，才能跟上系统缩放。"""
        if self._desk_lyric_alive():
            self._close_desk_lyric()
            self._remember_desk_lyric(False)
            self._status("桌面歌词已关闭")
            return
        self._launch_desk_lyric()
        self._remember_desk_lyric(True)

    def _desk_lyric_alive(self):
        proc = getattr(self, "_desk_lyric_proc", None)
        return proc is not None and proc.poll() is None

    def _launch_desk_lyric(self):
        if self._desk_lyric_alive():
            return
        self._desk_lyric_proc = _launch_desk_lyric()

    def _close_desk_lyric(self):
        proc = getattr(self, "_desk_lyric_proc", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._desk_lyric_proc = None

    def _lyric_span(self, elapsed):
        """当前句、已唱比例。时间戳按字头写，不再提前，避免歌词快半拍。"""
        lines = self.lyrics or []
        heard = max(0, int(elapsed))
        index = -1
        for i, (ms, text) in enumerate(lines):
            if text and ms <= heard:
                index = i
            elif ms > heard:
                break
        if index < 0:
            title = (self.current_song or {}).get("name") or ""
            return title, 0, 1
        start, text = lines[index]
        end = lines[index + 1][0] if index + 1 < len(lines) else start + 4000
        return text, start, end

    def _publish_desk_lyric(self, elapsed=0):
        """只在换句时写文件。颜色进度由歌词窗口按时间自己往前走，不再每拍读盘。"""
        line, start, end = self._lyric_span(elapsed)
        playing = bool(self.player.playing())
        payload = {
            "line": line,
            "start": int(start),
            "end": int(end),
            "position": int(elapsed),
            "at": time.time(),
            "playing": playing,
        }
        previous = getattr(self, "_desk_lyric_payload", None)
        if (
            previous
            and previous.get("line") == line
            and previous.get("playing") == playing
            and abs(previous.get("position", 0) - int(elapsed)) < 800
        ):
            return
        self._desk_lyric_payload = payload
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = LYRIC_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp, LYRIC_PATH)
        except OSError:
            pass

    def _on_player_state(self, _want):
        self._sync_play_icon()
        return False

    def _sync_play_icon(self):
        playing = bool(self.current_song) and self.player.playing()
        if getattr(self, "_play_shown", None) == playing and not getattr(self, "_play_hovered", False):
            return
        self._play_shown = playing
        self._set_play_icon(playing)

    def _toggle(self):
        if self.player.playing():
            self.player.pause()
        elif self.player.paused() and self.current_song:
            self.player.resume()
        elif self.current_song and self._resume_at and not getattr(self, "_resume_used", False):
            # 启动时只恢复进度，不自动开播。第一次点播放才从上次的位置继续。
            self._resume_used = True
            self._bg(lambda: self._resume_playback(self.current_song, self._resume_at))
        elif self.current_song:
            self._play_from_playing(self.playing_index)

    def _prev(self):
        nxt = self._neighbor(-1)
        if nxt is not None:
            self._play_from_playing(nxt)

    def _next(self):
        nxt = self._neighbor(1)
        if nxt is not None:
            self._play_from_playing(nxt)

    def _neighbor(self, step, wrap=True):
        if not self.playing:
            return None
        if self.play_mode == "shuffle":
            if len(self.playing) == 1:
                return 0
            import random
            choices = [i for i in range(len(self.playing)) if i != self.playing_index]
            return random.choice(choices)
        if self.play_mode == "single" and step > 0 and not wrap:
            return self.playing_index
        nxt = self.playing_index + step
        if 0 <= nxt < len(self.playing):
            return nxt
        if self.play_mode == "order":
            return None
        return nxt % len(self.playing)

    def _play_hover(self, hovered):
        self._play_hovered = hovered
        self._sync_play_icon()
        return False

    def _set_play_icon(self, playing):
        # 主题暂停符是白色，红底没画上时会和底栏混在一起。改用深色自绘，白底上也看得见。
        image = Gtk.Image.new_from_pixbuf(play_glyph(20, playing=playing))
        image.set_pixel_size(20)
        self.play_btn.set_image(image)
        self.play_btn.set_always_show_image(True)

    def _on_hotkey(self, action):
        if action == "playpause":
            self._toggle()
        elif action == "next-track":
            self._next()
        elif action == "prev-track":
            self._prev()
        return False

    def _on_track_end(self, error=None):
        if error:
            self._status(f"播放中断：{error}")
            self._set_play_icon(False)
            return False
        if self.playing_title == "私人FM" and self.playing_index >= len(self.playing) - 1:
            self._bg(self._load_fm)
            return False
        nxt = self._neighbor(1, wrap=False)
        if nxt is None:
            self._set_play_icon(False)
            self._status("列表已播放完")
        else:
            self._play_from_playing(nxt)
        return False

    def _tick(self):
        song = self.current_song
        playing = bool(song) and self.player.playing()
        paused = bool(song) and self.player.paused() and not playing
        if song and (playing or paused) and not self.seeking:
            self.player.refresh_clock()
        self._sync_play_icon()
        if song and (playing or paused):
            elapsed = self.player.position_ms()
            total = self.player.duration_ms() or song.get("duration") or getattr(self, "_resume_duration", 0) or 1
            hold = getattr(self, "_seek_hold", 0)
            if hold and abs(elapsed - hold) > 800 and self.seeking:
                elapsed = hold
            if not self.seeking and total and elapsed >= 0:
                self.scale.set_value(min(1000, elapsed * 1000 / total))
            shown = elapsed
            if self.seeking:
                shown = getattr(self, "_seek_hold", 0) or total * self.scale.get_value() / 1000
                self.scale.set_value(min(1000, shown * 1000 / total))
            self._place_time_pill(shown, total)
            self._highlight_lyric(shown if self.seeking else elapsed)
            self._publish_desk_lyric(shown if self.seeking else elapsed)
        elif song and getattr(self, "_resume_at", 0) and not playing:
            self._show_paused_progress()
        return True

    def _seek_fraction(self, scale, x):
        trough = scale.get_range_rect()
        span = max(1, trough.width)
        return max(0.0, min(1.0, (x - trough.x) / span))

    def _seek_apply(self, fraction):
        total = self.player.duration_ms() or self.player.cached_dur or (self.current_song or {}).get("duration") or 0
        if not total:
            return False
        target = total * max(0.0, min(1.0, fraction))
        self.seeking = True
        self._seek_hold = target
        # 还没开播时，时钟每拍都会用上次的进度把滑块拉回去。点击后改记这个位置。
        if self.player._want == "stopped":
            self._resume_at = int(target)
        self.scale.set_value(fraction * self.scale.get_adjustment().get_upper())
        self.player.cached_pos = target
        self.player.seek_ms(target)
        self._place_time_pill(target, total)
        self._seek_tries = 0
        GLib.timeout_add(300, self._seek_done, target)
        return True

    def _seek_press(self, scale, event):
        """点在轨道任意位置就跳过去。只拖滑块时，细轨道几乎点不中。"""
        if event.button != 1:
            return False
        if not (self.player.duration_ms() or self.player.cached_dur or (self.current_song or {}).get("duration")):
            return False
        # 滑块自己的拖动会在松手时发一次 change-value，值还是旧位置，进度就会弹回去。
        # 点击和拖动都在这里接住，不再交给滑块。
        self._seek_dragging = True
        self._seek_apply(self._seek_fraction(scale, event.x))
        return True

    def _seek_motion(self, scale, event):
        if not getattr(self, "_seek_dragging", False):
            return False
        if not (event.state & Gdk.ModifierType.BUTTON1_MASK):
            return False
        self._seek_apply(self._seek_fraction(scale, event.x))
        return True

    def _seek_change(self, scale, scroll, value):
        # 键盘和滚轮仍走这里。鼠标已经被按下事件接住，这里的值是松手时的旧位置。
        if getattr(self, "_seek_dragging", False):
            return True
        upper = scale.get_adjustment().get_upper() or 1000
        self._seek_apply(max(0.0, min(1.0, value / upper)))
        return True

    def _seek_release(self, scale, event):
        if not getattr(self, "_seek_dragging", False):
            return False
        self._seek_dragging = False
        self._seek_apply(self._seek_fraction(scale, event.x))
        return True

    def _seek_done(self, target):
        if abs(getattr(self, "_seek_hold", 0) - target) > 400:
            return False
        self._seek_tries = getattr(self, "_seek_tries", 0) + 1
        pos = self.player.position_ms()
        close = abs(pos - target) < 1500
        if close or self._seek_tries >= 6:
            self.seeking = False
            if close:
                self._seek_hold = 0
                self.player._seek_target = None
            return False
        self.player.seek_ms(target)
        return True

    def _highlight_lyric(self, elapsed):
        if not self.lyrics or not self.lyric_open:
            return
        heard = max(0, int(elapsed))
        current = 0
        for index, (ms, _line) in enumerate(self.lyrics):
            if ms <= heard:
                current = index
            else:
                break
        if current == getattr(self, "_lyric_index", None):
            return
        self._lyric_index = current
        self._mark_lyric(current)
        start = self.lyric_buf.get_iter_at_line(current + getattr(self, "_lyric_pad", 0))
        self.lyric_view.scroll_to_iter(start, 0.15, True, 0.0, 0.46)

    def _fill_lyrics(self, lines):
        self.lyrics = lines
        self._lyric_index = -1
        text = "\n" * 4 + ("\n".join(line for _, line in lines) or "这首歌没有歌词") + "\n" * 6
        self.lyric_buf.set_text(text)
        self._lyric_pad = 4

    def _lyric_tags(self):
        if hasattr(self, "_lyric_now"):
            return
        self._lyric_now = self.lyric_buf.create_tag("now", foreground=RED, weight=700, scale=1.28)
        self._lyric_near = self.lyric_buf.create_tag("near", foreground="#333333", scale=1.05)
        self._lyric_far = self.lyric_buf.create_tag("far", foreground="#A0A0A6")

    def _mark_lyric(self, current):
        self._lyric_tags()
        pad = getattr(self, "_lyric_pad", 0)
        self.lyric_buf.remove_all_tags(self.lyric_buf.get_start_iter(), self.lyric_buf.get_end_iter())
        last = self.lyric_buf.get_line_count()
        for offset, tag in ((0, self._lyric_now), (-1, self._lyric_near), (1, self._lyric_near)):
            line = current + pad + offset
            if line < 0 or line >= last:
                continue
            start = self.lyric_buf.get_iter_at_line(line)
            end = self.lyric_buf.get_iter_at_line(line + 1) if line + 1 < last else self.lyric_buf.get_end_iter()
            self.lyric_buf.apply_tag(tag, start, end)

    def _lyric_click(self, _view, event):
        if event.button != 1 or not self.lyrics:
            return False
        x, y = self.lyric_view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(event.x), int(event.y))
        found, it = self.lyric_view.get_iter_at_location(x, y)
        if not found:
            return False
        line = it.get_line() - getattr(self, "_lyric_pad", 0)
        if 0 <= line < len(self.lyrics):
            self.player.seek_ms(self.lyrics[line][0])
        return False

    def _show_lyric(self, show):
        self.lyric_open = show
        if show:
            self._show_page("lyric")
        else:
            self._show_page("list" if len(self.store) else "home")

    def present(self):
        self._show_lyric(False)
        self.show()
        super().present()

    def _build_tray(self):
        menu = Gtk.Menu()
        show = Gtk.MenuItem(label="显示主界面")
        show.connect("activate", lambda *_: self.present())
        quit_item = Gtk.MenuItem(label="退出")
        quit_item.connect("activate", lambda *_: self.get_application().quit_player())
        menu.append(show)
        menu.append(quit_item)
        menu.show_all()
        self.tray_menu = menu
        self.indicator = None
        self.status_icon = None
        # 麒麟面板左键走 AppIndicator 的 activate target，自己注册的托盘项面板不会调用。
        if AppIndicator is not None:
            try:
                self.indicator = AppIndicator.Indicator.new(
                    APP_ID, "audio-x-generic", AppIndicator.IndicatorCategory.APPLICATION_STATUS,
                )
                # 必须传文件绝对路径。主题名会先命中 ~/.local 里的旧图标。
                if ICON:
                    self.indicator.set_icon_full(os.path.abspath(ICON), "网易云音乐")
                self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
                self.indicator.set_menu(menu)
                self.indicator.set_activate_target(show)
                self.indicator.set_title("网易云音乐")
                return
            except Exception:
                self.indicator = None
        if ICON:
            self.status_icon = Gtk.StatusIcon.new_from_file(ICON)
        else:
            self.status_icon = Gtk.StatusIcon.new_from_icon_name("audio-x-generic")
        self.status_icon.set_tooltip_text("网易云音乐")
        self.status_icon.set_visible(True)
        self.status_icon.connect("activate", lambda *_: self.present())
        self.status_icon.connect("popup-menu", self._status_popup)

    def _status_popup(self, icon, button, activate_time):
        self.tray_menu.popup(None, None, icon.position_menu, icon, button, activate_time)

    def _on_close(self, *_):
        self._save_state()
        self.hide()
        song = self.current_song
        text = f"正在播放 {song['name']}" if song and self.player.playing() else "已在后台运行"
        self._notify("网易云音乐", text + "。左键托盘打开窗口，右键可退出。")
        return True

    def _notify(self, summary, body):
        try:
            note = Gio.Notification.new(summary)
            note.set_body(body)
            self.get_application().send_notification("netease-music", note)
        except Exception:
            pass

    def _on_login(self, *_):
        self._status("正在生成登录二维码…")
        self._bg(self._start_qr)

    def _logout(self):
        self.cookie = ""
        self.profile = None
        self.mine = []
        try:
            os.remove(COOKIE_PATH)
        except OSError:
            pass
        self._rebuild_account_menu()
        self._fill_nav()
        self._status("已退出登录")

    def _start_qr(self):
        try:
            key, cookie = api.login_qr_create()
        except Exception as exc:
            GLib.idle_add(self._status, f"生成二维码失败：{exc}")
            return
        path = os.path.join(DATA_DIR, "login-qr.png")
        os.makedirs(DATA_DIR, exist_ok=True)
        token = "".join(ch for ch in str(key) if ch.isalnum() or ch in "-_")
        if token != str(key):
            raise OSError("登录二维码无效")
        subprocess.check_call(["qrencode", "-o", path, "-s", "8", "-m", "2", "https://music.163.com/login?codekey=" + token])
        GLib.idle_add(self._show_qr, key, cookie, path)

    def _show_qr(self, key, cookie, path):
        dialog = Gtk.Dialog(title="登录网易云音乐", transient_for=self, modal=True)
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        box = dialog.get_content_area()
        box.set_margin_start(18)
        box.set_margin_end(18)
        box.set_spacing(8)
        hint = Gtk.Label(label="用网易云音乐 App 扫码，并在手机上确认。")
        box.pack_start(Gtk.Label(label="扫码登录"), False, False, 6)
        box.pack_start(Gtk.Image.new_from_file(path), False, False, 0)
        box.pack_start(hint, False, False, 4)
        dialog.show_all()
        state = {"done": False, "cookie": cookie}

        def poll():
            if state["done"]:
                return False
            self._bg(lambda: self._poll_qr(key, state, dialog, hint))
            return True

        GLib.timeout_add(1500, poll)
        dialog.run()
        state["done"] = True
        dialog.destroy()
        return False

    def _poll_qr(self, key, state, dialog, hint):
        if state["done"]:
            return
        try:
            result = api.login_qr_check(key, state["cookie"])
        except Exception as exc:
            GLib.idle_add(hint.set_text, f"检查登录失败：{exc}")
            return
        code = result["code"]
        if code == 802:
            GLib.idle_add(hint.set_text, "已扫码，请在手机上确认。")
        elif code == 803 and result["cookie"]:
            state["done"] = True
            api.save_cookie(COOKIE_PATH, result["cookie"])
            self.cookie = result["cookie"]
            GLib.idle_add(self._finish_login, dialog, hint)
        elif code == 803:
            GLib.idle_add(hint.set_text, "手机已确认，但没有收到登录凭证，请重试。")
        elif code == 800:
            GLib.idle_add(hint.set_text, "二维码已过期，请关闭后重新登录。")

    def _finish_login(self, dialog, hint):
        hint.set_text("登录成功，正在读取账号和歌单…")
        self.account_btn.set_label("正在读取账号…")
        dialog.response(Gtk.ResponseType.OK)
        self._bg(self._load_account)
        return False

    def _load_account(self):
        try:
            profile, playlists = api.likelist_playlist(self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self.account_btn.set_label, "已登录")
            GLib.idle_add(self._status, f"已登录，但没有读到账号：{exc}")
            return
        self.profile = profile
        self.mine = playlists
        try:
            self.liked_ids = set(api.liked_ids(self.cookie))
        except api.ApiError:
            pass
        GLib.idle_add(self._account_ready, profile, playlists)
        GLib.idle_add(self._refresh_like_button)

    def _account_ready(self, profile, playlists):
        vip = profile.get("vip") or ""
        self._rebuild_account_menu()
        self._fill_nav()
        liked = next((item for item in playlists if "喜欢的音乐" in (item.get("name") or "")), None)
        extra = f" · 我喜欢 {liked['count']} 首" if liked else ""
        self._status(f"已登录 {profile['nickname']}" + (f" · {vip}" if vip else "") + extra)
        return False

    def _load_home(self):
        if self.cookie:
            self._load_account()
        try:
            playlists = api.top_playlist(limit=12, cookie=self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        GLib.idle_add(self._render_home, api.CHARTS[:5], playlists)
        GLib.idle_add(self._status, "推荐已更新")

    def _status(self, text):
        self.status.set_text(text)
        return False

    def _bg(self, func):
        def run():
            try:
                func()
            except api.ApiError as exc:
                GLib.idle_add(self._status, str(exc))
            except Exception as exc:
                GLib.idle_add(self._status, f"出错了：{exc}")
        threading.Thread(target=run, daemon=True).start()


class GlobalHotkeys:
    """全局快捷键。

    这台机器是 Wayland，按键只进麒麟合成器。KGlobalAccel 能登记，但回调留在合成器里。
    能回到播放器的是 com.kylin.Wlcom.GlobalShortcuts.Session.Activated。
    启动时如果系统占着这三个组合，就把系统那一项挪走，再登记播放器自己的。
    """

    SERVICE = "org.kde.kglobalaccel"
    MANAGER_PATH = "/com/kylin/Wlcom/GlobalShortcuts"
    MANAGER_IFACE = "com.kylin.Wlcom.GlobalShortcuts.Manager"
    SESSION_IFACE = "com.kylin.Wlcom.GlobalShortcuts.Session"
    SYSTEM_SESSION = "/com/kylin/Wlcom/GlobalShortcuts/Session/kylin_wlcom"
    BINDINGS = (
        ("prev-track", "ctrl+alt+home", "Ctrl+Alt+Home"),
        ("next-track", "ctrl+alt+end", "Ctrl+Alt+End"),
        ("playpause", "ctrl+alt+p", "Ctrl+Alt+P"),
    )

    def __init__(self, handler):
        self.handler = handler
        self.ready = []
        self.error = ""
        self._session = None
        self._bus = None
        try:
            import dbus
            from dbus.mainloop.glib import DBusGMainLoop
        except ImportError:
            self.error = "缺少 python3-dbus，快捷键无法注册"
            return
        DBusGMainLoop(set_as_default=True)
        try:
            self._bus = dbus.SessionBus()
            self._release_old_sessions()
            self._override_system_chords()
            self._bind()
        except Exception as exc:
            self.error = f"快捷键注册失败：{exc}"

    def _manager(self):
        import dbus
        return dbus.Interface(
            self._bus.get_object(self.SERVICE, self.MANAGER_PATH),
            self.MANAGER_IFACE,
        )

    def _release_old_sessions(self):
        import dbus
        for name, path in self._manager().ListSessions().items():
            if not str(name).startswith("netease-"):
                continue
            dbus.Interface(
                self._bus.get_object(self.SERVICE, path),
                self.SESSION_IFACE,
            ).ResetShortcuts()

    def _override_system_chords(self):
        import dbus
        wanted = {key for _action, key, _label in self.BINDINGS}
        try:
            system = dbus.Interface(
                self._bus.get_object(self.SERVICE, self.SYSTEM_SESSION),
                self.SESSION_IFACE,
            )
            listed = system.ListShortcuts()
        except Exception:
            return
        moves = dbus.Dictionary({}, signature="sv")
        for name, item in listed.items():
            current = str(item.get("current_key") or "").lower().replace(" ", "")
            if current not in wanted:
                continue
            parked = f"alt+shift+f{10 + (len(moves) % 3)}"
            moves[str(name)] = dbus.Dictionary({
                "current_key": parked,
                "desc": str(item.get("desc") or name),
            }, signature="sv")
        if moves:
            system.ConfigureShortcuts(moves)

    def _bind(self):
        import dbus
        _ok, path = self._manager().CreateSession("netease-music")
        self._session = dbus.Interface(
            self._bus.get_object(self.SERVICE, path),
            self.SESSION_IFACE,
        )
        payload = dbus.Dictionary({}, signature="sv")
        for action, key, _label in self.BINDINGS:
            payload[action] = dbus.Dictionary({
                "current_key": key,
                "desc": "User Define Function",
            }, signature="sv")
        self._session.BindShortcuts(payload)
        stored = {
            str(name): str(item.get("current_key") or "").lower().replace(" ", "")
            for name, item in self._session.ListShortcuts().items()
        }
        missing = []
        for action, key, label in self.BINDINGS:
            if stored.get(action) == key:
                self.ready.append(label)
            else:
                missing.append(label)
        if missing:
            self.error = "、".join(missing) + " 仍被系统占用"
        self._bus.add_signal_receiver(
            self._on_activated,
            signal_name="Activated",
            dbus_interface=self.SESSION_IFACE,
            path=path,
        )

    def _on_activated(self, action, _timestamp, _options):
        GLib.idle_add(self.handler, str(action))


class MusicApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        if ICON:
            try:
                Gtk.Window.set_default_icon_from_file(ICON)
            except GLib.Error:
                pass
        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", lambda *_: self.quit_player())
        self.add_action(action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

    def do_activate(self):
        if self.win is None:
            self.win = AppWindow(self)
        self.win.present()

    def quit_player(self):
        if self.win:
            self.win._save_state()
            self.win._close_desk_lyric()
            self.win.player.stop()
        self.quit()


def _ui_scale():
    """UKUI 的界面缩放。Wayland 会自己乘上，XWayland 不会，歌词窗口要补上。"""
    try:
        value = float(Gio.Settings.new("org.ukui.SettingsDaemon.plugins.xsettings").get_double("scaling-factor"))
    except (GLib.Error, TypeError, ValueError):
        value = 1.0
    return value if value >= 1 else 1.0


def _launch_desk_lyric():
    """桌面歌词单独走 XWayland。主进程留在 Wayland，窗口才能跟上系统缩放。"""
    env = os.environ.copy()
    env["GDK_BACKEND"] = "x11"
    env.pop("WAYLAND_DISPLAY", None)
    # 不设置 GDK_SCALE。整数倍缩放会把歌词窗口放大，并把它推进任务栏。
    return subprocess.Popen([sys.executable, os.path.abspath(__file__), "--desk-lyric"], env=env)


def _run_desk_lyric():
    """无边框歌词层。悬停才显示半透明底和关闭按钮，松手后记住位置。"""
    scale = _ui_scale()
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_title("桌面歌词")
    titlebar = Gtk.Box()
    titlebar.show()
    window.set_titlebar(titlebar)
    window.set_decorated(False)
    window.set_skip_taskbar_hint(True)
    window.set_skip_pager_hint(True)
    window.set_keep_above(True)
    window.set_accept_focus(True)
    window.set_type_hint(Gdk.WindowTypeHint.UTILITY)
    window.set_app_paintable(True)
    width, height = 760, 64
    window.set_size_request(width, height)
    window.set_default_size(width, height)
    window.set_resizable(False)
    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    if visual is not None:
        window.set_visual(visual)
    overlay = Gtk.Overlay()
    plate = Gtk.Box()
    plate.get_style_context().add_class("desk-lyric-plate")
    plate.set_no_show_all(True)
    plate.hide()
    label = Gtk.Label()
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_margin_start(28)
    label.set_margin_end(28)
    label.set_margin_top(0)
    label.set_margin_bottom(0)
    label.set_size_request(width - 56, height)
    label.set_sensitive(False)
    window._line = ""
    window._cut = -1
    window._widths = {}
    window._clock = {"line": "暂无歌词", "start": 0, "end": 1, "position": 0, "at": time.time(), "playing": False}
    close = Gtk.Button(label="×")
    close.set_relief(Gtk.ReliefStyle.NONE)
    close.get_style_context().add_class("desk-lyric-close")
    close.set_halign(Gtk.Align.END)
    close.set_valign(Gtk.Align.START)
    close.set_margin_top(6)
    close.set_margin_end(6)
    close.set_no_show_all(True)
    close.hide()
    overlay.add(plate)
    overlay.add_overlay(label)
    overlay.add_overlay(close)

    def paint_line(text, fraction):
        """已唱部分淡蓝，后面白色。唱到这个字的开头就变色，不等这个字唱完。"""
        text = text or "暂无歌词"
        fraction = max(0.0, min(0.999, fraction))
        widths = window._widths.get(text) if text == window._line else None
        if not widths or len(widths) != len(text) + 1:
            layout = label.create_pango_layout(text)
            layout.set_font_description(Pango.FontDescription("Sans Bold 18"))
            widths = [0]
            for index in range(1, len(text) + 1):
                layout.set_text(text[:index], -1)
                widths.append(layout.get_pixel_size()[0])
            window._widths[text] = widths
            if len(window._widths) > 8:
                window._widths.pop(next(iter(window._widths)))
        target = widths[-1] * fraction
        cut = 0
        for index, width in enumerate(widths):
            if index and widths[index - 1] > target + 1:
                break
            cut = index
        if text == window._line and cut == window._cut:
            return
        window._line = text
        window._cut = cut
        markup = (
            f'<span font="Sans Bold 18" foreground="#9EC7F2">{GLib.markup_escape_text(text[:cut])}</span>'
            f'<span font="Sans Bold 18" foreground="#FFFFFF">{GLib.markup_escape_text(text[cut:])}</span>'
        )
        label.set_markup(markup)
    window.add(overlay)
    window.add_events(
        Gdk.EventMask.BUTTON_PRESS_MASK
        | Gdk.EventMask.BUTTON_RELEASE_MASK
        | Gdk.EventMask.POINTER_MOTION_MASK
        | Gdk.EventMask.ENTER_NOTIFY_MASK
        | Gdk.EventMask.LEAVE_NOTIFY_MASK
    )
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS.replace("{RED}", RED).encode())
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    window._placed = False
    window._drag = None

    def saved_position():
        try:
            payload = json.loads(open(LYRIC_POS_PATH, encoding="utf-8").read())
            return int(payload["x"]), int(payload["y"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def remember():
        x, y = window.get_position()
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = LYRIC_POS_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"x": int(x), "y": int(y)}, handle)
            os.replace(tmp, LYRIC_POS_PATH)
        except OSError:
            pass

    def place(*_args):
        if window._placed:
            return False
        saved = saved_position()
        if saved is not None:
            window.move(*saved)
        else:
            try:
                panel = int(Gio.Settings.new("org.ukui.panel.settings").get_int("panelsize") or 48)
            except (GLib.Error, TypeError, ValueError):
                panel = 48
            screen_w, screen_h = 1646, 1029
            monitor = window.get_display().get_monitor(0)
            if monitor is not None:
                geom = monitor.get_geometry()
                logical_w = geom.width / max(scale, 1)
                if 800 < logical_w < 2200:
                    screen_w, screen_h = logical_w, geom.height / max(scale, 1)
            window.move(int(max(0, (screen_w - width) // 2)), int(max(0, screen_h - panel - height - 8)))
        window.resize(width, height)
        window.set_size_request(width, height)
        window._placed = True
        return False

    def show_chrome(shown):
        if shown:
            plate.show()
            close.show()
        else:
            plate.hide()
            close.hide()

    def press(widget, event):
        if event.button != 1 or event.type == Gdk.EventType._2BUTTON_PRESS:
            return True
        widget._drag = (event.x_root, event.y_root, *widget.get_position())
        widget._placed = True
        seat = widget.get_display().get_default_seat()
        if seat is not None and window.get_window() is not None:
            seat.grab(window.get_window(), Gdk.SeatCapabilities.POINTER, False, None, event, None)
        return True

    def release(widget, _event):
        if widget._drag is not None:
            remember()
        widget._drag = None
        seat = widget.get_display().get_default_seat()
        if seat is not None:
            seat.ungrab()
        return True

    def motion(widget, event):
        drag = widget._drag
        if not drag:
            show_chrome(True)
            return False
        x0, y0, wx, wy = drag
        widget.move(int(wx + event.x_root - x0), int(wy + event.y_root - y0))
        return True

    def refresh():
        try:
            payload = json.loads(open(LYRIC_PATH, encoding="utf-8").read())
            window._clock = payload
        except (OSError, json.JSONDecodeError):
            payload = window._clock
        return True

    def advance():
        """颜色在本进程里按时间往前走。读文件只负责换句，避免每个字都等一次磁盘。"""
        clock = window._clock or {}
        line = clock.get("line") or "暂无歌词"
        start = int(clock.get("start") or 0)
        end = int(clock.get("end") or start + 1)
        position = int(clock.get("position") or 0)
        if clock.get("playing"):
            position += int((time.time() - float(clock.get("at") or time.time())) * 1000)
        span = max(1, end - start)
        fraction = max(0.0, min(1.0, (position - start) / span))
        paint_line(line, fraction)
        return True

    close.connect("clicked", lambda *_: (window.hide(), Gtk.main_quit()))
    window.connect("realize", place)
    window.connect("enter-notify-event", lambda *_: show_chrome(True))
    window.connect("leave-notify-event", lambda *_: show_chrome(False))
    window.connect("button-press-event", press)
    window.connect("button-release-event", release)
    window.connect("motion-notify-event", motion)
    window.show_all()
    close.hide()
    plate.hide()
    GLib.timeout_add(1000, refresh)
    GLib.timeout_add(80, advance)
    Gtk.main()


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    if "--desk-lyric" in sys.argv:
        _run_desk_lyric()
        return
    raise SystemExit(MusicApp().run([os.path.abspath(__file__)]))


if __name__ == "__main__":
    main()
