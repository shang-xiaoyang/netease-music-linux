#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""网易云音乐 Linux 原生播放器。

浅色主界面按官方客户端的结构排：左侧导航、推荐卡片、歌单封面、底部播放条。
关闭窗口后留在右下角托盘，右键可以打开或退出。
"""

import hashlib
import json
import os
import subprocess
import threading
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gst", "1.0")

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gst, Gtk

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except (ValueError, ImportError):
    AppIndicator = None

import netease_api as api

Gst.init(None)

APP_ID = "io.github.shangxiaoyang.netease-music"
DATA_DIR = os.path.join(GLib.get_user_data_dir(), "netease-cloud-music")
COOKIE_PATH = os.path.join(DATA_DIR, "cookie")
QUALITY_PATH = os.path.join(DATA_DIR, "quality")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
MODE_PATH = os.path.join(DATA_DIR, "play-mode")
COVER_DIR = os.path.join(DATA_DIR, "covers")
RED = "#EC4141"
def _icon_path():
    """任务栏按图标名找小尺寸。用户主题优先，避免读到源码树里的旧图。"""
    roots = (
        os.path.join(GLib.get_home_dir(), ".local/share/icons/hicolor"),
        "/usr/share/icons/hicolor",
    )
    for root in roots:
        for size in (48, 32, 24, 22, 64, 128, 256):
            path = os.path.join(root, f"{size}x{size}", "apps", "netease-music-linux.png")
            if os.path.exists(path):
                return path
    return "audio-x-generic"


ICON = _icon_path()

CSS = f"""
window {{
    background: #F5F5F7;
    color: #222;
    font-family: "Noto Sans CJK SC";
}}
.side {{
    background: #FFFFFF;
    border-right: 1px solid #ECECEE;
}}
.brand {{
    font-size: 16px;
    font-weight: 700;
    color: #222;
}}
.side-row {{
    border-radius: 8px;
    margin: 1px 10px;
    min-height: 34px;
    color: #333;
    background: transparent;
}}
.side-row:hover {{
    background: #F3F3F5;
}}
.side-row.current {{
    background: {RED};
    color: white;
}}
.section {{
    color: #9A9AA0;
    font-size: 12px;
    padding: 16px 18px 4px 18px;
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
}}
.song-list treeview:selected {{
    background: #FDECEC;
    color: #222;
}}
.player-bar {{
    background: #FFFFFF;
    border-top: 1px solid #ECECEE;
    padding: 6px 14px;
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
    border-radius: 22px;
    min-width: 44px;
    min-height: 44px;
    padding: 0;
    background: transparent;
    color: #222222;
    border: none;
    box-shadow: none;
}}
button.play-main:hover,
button.play-main:active {{
    background: {RED};
    color: white;
}}
button.flat {{
    border: none;
    background: transparent;
    color: #222222;
    box-shadow: none;
}}
button.bar-btn {{
    background: #FFFFFF;
    color: #222222;
    border: 1px solid #E2E2E6;
    border-radius: 8px;
    padding: 4px 10px;
    box-shadow: none;
}}
button.bar-btn:hover {{
    background: #F6F6F8;
    color: #222222;
}}
button.bar-btn:active {{
    background: #FDECEC;
    color: #222222;
}}
button.bar-btn label {{
    color: #222222;
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
.lyric-page {{
    background: #F7F7F8;
}}
.lyric-page textview, .lyric-page text {{
    background: transparent;
    color: #222;
    font-size: 22px;
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


def fmt_time(ms):
    ms = max(0, int(ms or 0))
    seconds = ms // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def cover_cache_path(url, size):
    """封面缓存在当前用户的隐藏目录里，文件名不随进程变化。"""
    os.makedirs(COVER_DIR, exist_ok=True)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return os.path.join(COVER_DIR, f"{digest}-{int(size)}.jpg")


def load_pixbuf(url, size, rounded=8):
    path = cover_cache_path(url, size)
    if not os.path.exists(path) or os.path.getsize(path) < 32:
        req = urllib.request.Request(
            url + f"?param={size * 2}y{size * 2}",
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
    pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, False)
    return pix


class Player:
    def __init__(self, on_end):
        self.playbin = Gst.ElementFactory.make("playbin", "netease")
        self.on_end = on_end
        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

    def _on_message(self, _bus, message):
        if message.type == Gst.MessageType.EOS:
            GLib.idle_add(self.on_end)
        elif message.type == Gst.MessageType.ERROR:
            err, _dbg = message.parse_error()
            GLib.idle_add(self.on_end, str(err))

    def play(self, url):
        self.playbin.set_state(Gst.State.NULL)
        self.playbin.set_property("uri", url)
        self.playbin.set_state(Gst.State.PLAYING)

    def stop(self):
        self.playbin.set_state(Gst.State.NULL)

    def pause(self):
        self.playbin.set_state(Gst.State.PAUSED)

    def resume(self):
        self.playbin.set_state(Gst.State.PLAYING)

    def playing(self):
        _ok, state, _pending = self.playbin.get_state(0)
        return state == Gst.State.PLAYING

    def paused(self):
        _ok, state, _pending = self.playbin.get_state(0)
        return state == Gst.State.PAUSED

    def position_ms(self):
        ok, pos = self.playbin.query_position(Gst.Format.TIME)
        return int(pos / 1_000_000) if ok else 0

    def duration_ms(self):
        ok, dur = self.playbin.query_duration(Gst.Format.TIME)
        return int(dur / 1_000_000) if ok else 0

    def seek_ms(self, ms):
        self.playbin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            int(ms) * Gst.MSECOND,
        )


class AppWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="网易云音乐")
        self.set_default_size(1000, 646)
        self.set_position(Gtk.WindowPosition.CENTER)
        if os.path.exists(ICON) and not ICON.endswith("-generic"):
            try:
                self.set_icon_from_file(ICON)
            except GLib.Error:
                pass

        self.cookie = api.load_cookie(COOKIE_PATH)
        self.profile = None
        self.mine = []
        self.player = Player(self._on_track_end)
        # playing 是正在播放的列表，和左侧正在浏览的列表分开。
        # 只有双击另一份列表里的歌，才会换掉它。
        self.playing = []
        self.playing_title = "当前播放"
        self.playing_index = -1
        self.queue_overlay = None
        self.play_mode = self._load_mode()
        self.lyrics = []
        self.current_song = None
        self.quality = self._load_quality()
        self._applied_quality = self.quality
        self.seeking = False
        self.lyric_open = False
        self.nav_buttons = []

        self._apply_css()
        self._build()
        self._build_tray()
        self._hotkeys = GlobalHotkeys(self._on_hotkey)
        if self._hotkeys.error:
            self._status("全局快捷键未生效：" + self._hotkeys.error)
        elif len(self._hotkeys.ready) == 3:
            self._status("快捷键已生效：Ctrl+Alt+P 播放或暂停，Ctrl+Alt+Home 上一首，Ctrl+Alt+End 下一首")
        self.connect("delete-event", self._on_close)
        GLib.timeout_add(400, self._tick)
        self.show_all()
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
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("搜索歌曲、歌手")
        self.search.set_width_chars(28)
        self.search.connect("activate", self._on_search)
        header.set_custom_title(self.search)
        self.account_btn = Gtk.Button(label="登录")
        self.account_btn.get_style_context().add_class("flat")
        self.account_btn.connect("clicked", self._on_login)
        header.pack_end(self.account_btn)

        self.side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.side.get_style_context().add_class("side")
        self.side.set_size_request(210, -1)
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        brand.set_margin_start(16)
        brand.set_margin_top(14)
        brand.set_margin_bottom(10)
        mark = Gtk.Label(label="♪")
        mark.get_style_context().add_class("brand")
        name = Gtk.Label(label="网易云音乐", xalign=0)
        name.get_style_context().add_class("brand")
        brand.pack_start(mark, False, False, 0)
        brand.pack_start(name, False, False, 0)
        self.side.pack_start(brand, False, False, 0)
        self.nav_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
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
        self.heading.set_margin_start(16)
        self.heading.set_margin_top(12)
        self.store = Gtk.ListStore(str, str, str, str, str, object, GdkPixbuf.Pixbuf)
        self.view = Gtk.TreeView(model=self.store, headers_visible=True)
        self.view.set_fixed_height_mode(False)
        self.view.set_activate_on_single_click(False)
        self.view.connect("row-activated", self._on_activate)
        self.view.connect("button-release-event", self._on_list_click)
        cover_cell = Gtk.CellRendererPixbuf()
        cover_col = Gtk.TreeViewColumn("", cover_cell, pixbuf=6)
        cover_col.set_min_width(44)
        self.view.append_column(cover_col)
        for idx, title, width in ((1, "歌曲", 168), (2, "歌手", 160), (3, "专辑", 160), (4, "时长", 64)):
            renderer = Gtk.CellRendererText(ellipsize=3)
            column = Gtk.TreeViewColumn(title, renderer, text=idx)
            column.set_resizable(True)
            column.set_min_width(width)
            column.set_expand(idx == 1)
            self.view.append_column(column)
        song_scroll = Gtk.ScrolledWindow()
        song_scroll.get_style_context().add_class("song-list")
        song_scroll.add(self.view)
        self.list_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.list_page.pack_start(self.heading, False, False, 0)
        self.list_page.pack_start(song_scroll, True, True, 0)

        self.lyric_buf = Gtk.TextBuffer()
        self.lyric_view = Gtk.TextView(buffer=self.lyric_buf, editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD)
        self.lyric_view.set_justification(Gtk.Justification.CENTER)
        self.lyric_view.set_left_margin(80)
        self.lyric_view.set_right_margin(80)
        self.lyric_view.set_top_margin(28)
        self.lyric_view.set_pixels_above_lines(12)
        self.lyric_title = Gtk.Label(xalign=0.5)
        self.lyric_title.get_style_context().add_class("heading")
        self.lyric_artist = Gtk.Label()
        self.lyric_artist.get_style_context().add_class("dim")
        back = Gtk.Button(label="返回")
        back.get_style_context().add_class("flat")
        back.connect("clicked", lambda *_: self._show_lyric(False))
        lyric_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        lyric_bar.pack_start(back, False, False, 8)
        lyric_scroll = Gtk.ScrolledWindow()
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
        self.stack.add_named(self.lyric_page, "lyric")
        self._build_queue_overlay()

        overlay = Gtk.Overlay()
        overlay.add(self.stack)
        overlay.add_overlay(self.queue_overlay)

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
        self.title_btn = Gtk.Button(label="未在播放")
        self.title_btn.get_style_context().add_class("flat")
        self.title_btn.set_halign(Gtk.Align.START)
        self.title_btn.connect("clicked", lambda *_: self._show_lyric(True))
        self.artist_label = Gtk.Label(label="点封面查看歌词", xalign=0)
        self.artist_label.set_ellipsize(3)
        self.artist_label.get_style_context().add_class("dim")
        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        meta.set_size_request(220, -1)
        meta.pack_start(self.title_btn, False, False, 0)
        meta.pack_start(self.artist_label, False, False, 0)

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
        self.scale.set_size_request(-1, 16)
        self.scale.set_valign(Gtk.Align.CENTER)
        self.scale.connect("button-press-event", self._seek_press)
        self.scale.connect("button-release-event", self._seek_end)
        self.scale.connect("motion-notify-event", self._seek_motion)
        self.time_label = Gtk.Label(label="00:00 / 00:00")
        self.time_label.get_style_context().add_class("dim")
        self.mode_btn = Gtk.Button()
        self.mode_btn.get_style_context().add_class("bar-btn")
        self.mode_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.mode_btn.connect("clicked", lambda *_: self._cycle_mode())
        self._apply_mode_button()
        self.queue_btn = Gtk.Button(label="播放列表")
        self.queue_btn.get_style_context().add_class("bar-btn")
        self.queue_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.queue_btn.set_tooltip_text("查看当前播放列表")
        self.queue_btn.connect("clicked", lambda *_: self._show_queue())
        self.quality_btn = Gtk.MenuButton(label=self._quality_short())
        self.quality_btn.get_style_context().add_class("bar-btn")
        self.quality_btn.set_tooltip_text("播放音质")

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.get_style_context().add_class("player-bar")
        bar.pack_start(self.cover_btn, False, False, 0)
        bar.pack_start(meta, False, False, 0)
        bar.pack_start(self._icon_button("media-skip-backward-symbolic", self._prev), False, False, 0)
        bar.pack_start(self.play_btn, False, False, 0)
        bar.pack_start(self._icon_button("media-skip-forward-symbolic", self._next), False, False, 0)
        bar.pack_start(self.scale, True, True, 8)
        bar.pack_end(self.queue_btn, False, False, 0)
        bar.pack_end(self.mode_btn, False, False, 0)
        bar.pack_end(self.quality_btn, False, False, 0)
        bar.pack_end(self.time_label, False, False, 0)

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

    def _icon_button(self, name, handler):
        button = Gtk.Button.new_from_icon_name(name, Gtk.IconSize.BUTTON)
        button.get_style_context().add_class("flat")
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.connect("clicked", lambda *_: handler())
        return button

    def _quality_short(self):
        for key, name, hint in api.QUALITIES:
            if key == self.quality:
                return name
        return "音质"

    def _rebuild_quality_menu(self):
        menu = Gtk.Menu()
        menu.get_style_context().add_class("menu")
        group = None
        for key, name, hint in api.QUALITIES:
            item = Gtk.RadioMenuItem(label=f"{name}   {hint}", group=group)
            group = item
            item.set_active(key == self.quality)
            item.get_child().override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.13, 0.13, 0.15, 1))
            item.get_child().override_color(Gtk.StateFlags.PRELIGHT, Gdk.RGBA(0.13, 0.13, 0.15, 1))
            menu.append(item)
            item.connect("activate", self._on_quality, key)
        menu.show_all()
        self.quality_btn.set_popup(menu)
        self.quality_btn.set_label(self._quality_short())

    def _on_quality(self, item, key):
        if item is not None and not item.get_active():
            return
        if key == getattr(self, "_applied_quality", None) and self.player.playing():
            return
        self.quality = key
        self._applied_quality = key
        self._save_quality(key)
        self.quality_btn.set_label(self._quality_short())
        song = self.current_song
        if not song:
            self._status(f"音质已设为{api.QUALITY_LABEL.get(key, key)}")
            return
        resume_at = self.player.position_ms() if (self.player.playing() or self.player.paused()) else 0
        self._status(f"正在切换到{api.QUALITY_LABEL.get(key, key)}…")
        self._bg(lambda: self._restart_quality(song, resume_at))

    def _restart_quality(self, song, resume_at):
        try:
            info = api.song_url(song["id"], level=self.quality, cookie=self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        if self.current_song and self.current_song.get("id") != song.get("id"):
            return
        if not info:
            GLib.idle_add(self._status, f"「{song['name']}」没有可播放地址。")
            return
        self.player.play(info["url"])
        if resume_at > 1500:
            GLib.timeout_add(350, self._seek_after_switch, song, resume_at, 0)
        GLib.idle_add(self._quality_started, song, info)

    def _seek_after_switch(self, song, resume_at, tries):
        if not self.current_song or self.current_song.get("id") != song.get("id"):
            return False
        if self.player.duration_ms() > 0 or tries >= 8:
            self.player.seek_ms(resume_at)
            return False
        GLib.timeout_add(200, self._seek_after_switch, song, resume_at, tries + 1)
        return False

    def _quality_started(self, song, info):
        if self.current_song and self.current_song.get("id") != song.get("id"):
            return False
        level = info.get("level") or ""
        label = api.QUALITY_LABEL.get(level, level)
        note = "，已按账号权限降级" if level and level != self.quality else ""
        kbps = int((info.get("br") or 0) / 1000)
        self._status(f"正在播放 · {label} · {kbps}kbps {(info.get('type') or '').upper()}{note}")
        self._set_play_icon(True)
        return False

    def _fill_nav(self):
        for child in self.nav_box.get_children():
            self.nav_box.remove(child)
        self.nav_buttons = []
        self._nav("推荐", lambda: self._show_home(), current=True)
        for cid, name in api.CHARTS[:4]:
            self._nav(name, lambda c=cid, n=name: self._open_playlist(c, n))
        self._nav("热门歌单", self._open_discover)
        if self.profile:
            self._section(self.profile.get("vip") or "我的")
            self._nav("我喜欢的音乐", self._open_liked)
            self._nav("每日推荐", self._open_daily)
            self._nav("刷新收藏", self._refresh_library)
            created = []
            collected = []
            uid = self.profile.get("userId")
            for item in self.mine:
                (created if item.get("creator") == uid else collected).append(item)
            if created:
                self._section("创建的歌单")
                for item in sorted(created, key=lambda row: row.get("added") or 0, reverse=True)[:20]:
                    self._nav(item["name"], lambda i=item: self._open_playlist(i["id"], i["name"], mine=True))
            if collected:
                self._section("收藏的歌单")
                for item in sorted(collected, key=lambda row: row.get("added") or 0, reverse=True)[:30]:
                    self._nav(item["name"], lambda i=item: self._open_playlist(i["id"], i["name"]))
        self.nav_box.show_all()

    def _section(self, text):
        label = Gtk.Label(label=text, xalign=0)
        label.get_style_context().add_class("section")
        self.nav_box.pack_start(label, False, False, 0)

    def _nav(self, text, handler, current=False):
        button = Gtk.Button(label=text)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_halign(Gtk.Align.FILL)
        button.get_style_context().add_class("side-row")
        child = button.get_child()
        if isinstance(child, Gtk.Label):
            child.set_xalign(0)
            child.set_ellipsize(3)
        if current:
            button.get_style_context().add_class("current")
        button.connect("clicked", lambda *_: self._select_nav(button, handler))
        self.nav_buttons.append(button)
        self.nav_box.pack_start(button, False, False, 0)

    def _select_nav(self, button, handler):
        for item in self.nav_buttons:
            item.get_style_context().remove_class("current")
        button.get_style_context().add_class("current")
        self._hide_queue()
        handler()

    def _show_page(self, name):
        child = self.stack.get_child_by_name(name)
        if child is not None:
            child.show()
        self.stack.set_visible_child_name(name)
        self.stack.show_all()
        if self.queue_overlay is not None and self.queue_overlay.get_visible():
            self.queue_overlay.show_all()

    def _show_home(self):
        self.lyric_open = False
        self._show_page("home")

    def _open_playlist(self, ident, name, mine=False):
        self._hide_queue()
        self.heading.set_text(name)
        self._show_page("list")
        self.lyric_open = False
        self._status(f"正在打开{name}…")
        self._bg(lambda: self._show_playlist(ident, name, mine))

    def _open_discover(self):
        self._hide_queue()
        self.heading.set_text("热门歌单")
        self._show_page("list")
        self._status("正在加载热门歌单…")
        self._bg(self._show_discover)

    def _open_liked(self):
        self._hide_queue()
        self.heading.set_text("我喜欢的音乐")
        self._show_page("list")
        self._status("正在同步我喜欢的音乐…")
        self._bg(self._show_liked)

    def _open_daily(self):
        self._hide_queue()
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
        self.heading.set_text(f"搜索「{keyword}」")
        self._show_page("list")
        self._status("正在搜索…")
        self._bg(lambda: self._show_search(keyword))

    def _show_search(self, keyword):
        songs = api.search_songs(keyword, cookie=self.cookie)
        GLib.idle_add(self._set_songs, songs, f"找到 {len(songs)} 首")

    def _show_playlist(self, ident, name, mine=False):
        data = api.playlist_tracks(ident, cookie=self.cookie, by_added=mine)
        liked = mine or data.get("special") == 5 or "喜欢的音乐" in (data.get("name") or name)
        if liked and not mine:
            data["songs"].sort(key=lambda song: song.get("added") or 0, reverse=True)
        GLib.idle_add(self.heading.set_text, data["name"] or name)
        status = f"{len(data['songs'])} 首" + (" · 按收藏时间从新到旧" if liked else "")
        GLib.idle_add(self._set_songs, data["songs"], status)

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
        label, tip = {
            "loop": ("列表循环", "列表循环：播完最后一首回到第一首"),
            "order": ("列表播放", "列表播放：按列表顺序播放，播完停止"),
            "single": ("单曲循环", "单曲循环：重复当前歌曲"),
            "shuffle": ("随机播放", "随机播放：在当前列表里随机下一首"),
        }[self.play_mode]
        self.mode_btn.set_label(label)
        child = self.mode_btn.get_child()
        if isinstance(child, Gtk.Label):
            child.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.13, 0.13, 0.15, 1))
            child.override_color(Gtk.StateFlags.PRELIGHT, Gdk.RGBA(0.13, 0.13, 0.15, 1))
            child.override_color(Gtk.StateFlags.ACTIVE, Gdk.RGBA(0.13, 0.13, 0.15, 1))
        self.mode_btn.set_tooltip_text(tip)
        self._refresh_queue_popup()

    def _hide_queue(self):
        if self.queue_overlay is not None:
            self.queue_overlay.hide()

    def _show_queue(self):
        songs = [song for song in self.playing if isinstance(song, dict) and song.get("name")]
        if not songs:
            self._status("还没有正在播放的列表")
            return
        if self.queue_overlay.get_visible():
            self.queue_overlay.hide()
            return
        self._refresh_queue_popup()
        self.queue_overlay.set_no_show_all(False)
        self.queue_overlay.show_all()
        self.queue_overlay.set_no_show_all(True)

    def _build_queue_overlay(self):
        # 嵌在主窗口右下角，不另开窗口。Wayland 会忽略独立窗口的 move，还会画出标题栏。
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        panel.get_style_context().add_class("queue-overlay")
        panel.set_size_request(300, 340)
        panel.set_margin_end(12)
        panel.set_margin_bottom(12)
        panel.set_halign(Gtk.Align.END)
        panel.set_valign(Gtk.Align.END)
        self.queue_heading = Gtk.Label(xalign=0)
        self.queue_heading.set_margin_start(10)
        self.queue_heading.set_margin_top(8)
        self.queue_heading.set_ellipsize(3)
        self.queue_heading.get_style_context().add_class("heading")
        panel.pack_start(self.queue_heading, False, False, 0)
        self.queue_store = Gtk.ListStore(str, str, str)
        view = Gtk.TreeView(model=self.queue_store, headers_visible=False)
        view.connect("row-activated", self._on_queue_activate)
        title = Gtk.CellRendererText(ellipsize=3)
        artist = Gtk.CellRendererText(ellipsize=3)
        column = Gtk.TreeViewColumn()
        column.pack_start(title, True)
        column.pack_start(artist, False)
        column.add_attribute(title, "text", 0)
        column.add_attribute(artist, "text", 1)
        view.append_column(column)
        scroll = Gtk.ScrolledWindow()
        scroll.set_margin_start(6)
        scroll.set_margin_end(6)
        scroll.set_margin_bottom(8)
        scroll.get_style_context().add_class("song-list")
        scroll.add(view)
        panel.pack_start(scroll, True, True, 0)
        panel.set_no_show_all(True)
        panel.hide()
        self.queue_overlay = panel
        self.queue_view = view

    def _refresh_queue_popup(self):
        if self.queue_overlay is None:
            return
        self.queue_heading.set_text(f"{self.playing_title or '当前播放'} · {self.mode_btn.get_label()}")
        self.queue_store.clear()
        for song in self.playing:
            if not isinstance(song, dict) or not song.get("name"):
                continue
            self.queue_store.append([song.get("name") or "", song.get("artist") or "", str(song.get("id") or "")])
        if 0 <= self.playing_index < len(self.queue_store):
            self.queue_view.set_cursor(Gtk.TreePath(self.playing_index))
            self.queue_view.scroll_to_cell(Gtk.TreePath(self.playing_index), None, True, 0.4, 0)

    def _on_queue_activate(self, _view, path, _column):
        self._play_from_playing(path.get_indices()[0])

    def _save_state(self):
        songs = [song for song in self.playing if song.get("id") and "artist" in song]
        if not songs:
            return
        position = 0
        if self.current_song and (self.player.playing() or self.player.paused()):
            position = self.player.position_ms()
        payload = {
            "title": self.playing_title,
            "index": self.playing_index,
            "position": position,
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
        self.title_btn.set_label(self.current_song.get("name") or "未在播放")
        self.artist_label.set_text(self.current_song.get("artist") or "")
        self._resume_at = int(payload.get("position") or 0)
        self._status(f"已恢复 {self.current_song.get('name') or ''} · {self.playing_title}")
        if self.current_song.get("cover"):
            self._bg(lambda: self._set_remote_image(self.current_song["cover"], self.cover, 46))
        self._bg(lambda: self._resume_playback(self.current_song, self._resume_at))

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

    def _set_playlists(self, playlists):
        self.store.clear()
        for item in playlists:
            self.store.append(["", item["name"], f"{item['count']} 首", "歌单", "", item, self._cover_placeholder()])
        self._status(f"{len(playlists)} 个歌单，双击打开")
        return False

    def _set_songs(self, songs, status, remember=True):
        self.store.clear()
        placeholder = self._cover_placeholder()
        for song in songs:
            self.store.append([
                str(song.get("id") or ""),
                song.get("name") or "",
                song.get("artist") or "",
                song.get("album") or "",
                fmt_time(song.get("duration")),
                song,
                placeholder,
            ])
        self._status(status)
        self._bg(lambda: self._fill_covers(list(songs)))
        return False

    def _cover_placeholder(self):
        if getattr(self, "_placeholder", None) is None:
            self._placeholder = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 36, 36)
            self._placeholder.fill(0xF0F0F2FF)
        return self._placeholder

    def _fill_covers(self, songs):
        wanted = {song.get("id") for song in songs}
        pending = [song for song in songs if song.get("id") in wanted and not song.get("cover")]
        if pending:
            try:
                api.attach_covers(pending, self.cookie)
            except api.ApiError:
                pass
        for song in songs:
            if song.get("id") not in wanted:
                continue
            if self.store is None or len(self.store) == 0:
                return
            # 列表第一列是字符串，歌曲 id 是数字，必须同一类型才能对上。
            visible = {str(row[0]) for row in self.store}
            if not {str(item) for item in wanted}.intersection(visible):
                return
            url = song.get("cover")
            if not url:
                continue
            try:
                pix = load_pixbuf(url, 36, rounded=4)
            except Exception:
                continue
            GLib.idle_add(self._set_row_cover, song.get("id"), pix)

    def _set_row_cover(self, song_id, pix):
        for row in self.store:
            if row[5] and str(row[5].get("id")) == str(song_id):
                row[6] = pix
                break
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
        return False

    def _feature_card(self, name, color, playlist_id):
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_size_request(150, 110)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_margin_start(12)
        box.set_margin_top(16)
        box.set_margin_end(12)
        label = Gtk.Label(label=name, xalign=0)
        label.get_style_context().add_class("card-title")
        sub = Gtk.Label(label="点击打开", xalign=0)
        sub.get_style_context().add_class("card-sub")
        box.pack_start(label, False, False, 0)
        box.pack_start(sub, False, False, 4)
        button.add(box)
        provider = Gtk.CssProvider()
        provider.load_from_data(
            f"button {{ background: {color}; border-radius: 12px; border: none; }}".encode()
        )
        button.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        button.connect("clicked", lambda *_: self._open_playlist(playlist_id, name))
        return button

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

    def _set_remote_image(self, url, widget, size):
        try:
            pix = load_pixbuf(url, size)
        except Exception:
            return
        GLib.idle_add(widget.set_from_pixbuf, pix)

    def _on_list_click(self, view, event):
        if event.button != 1 or event.type != Gdk.EventType.BUTTON_RELEASE:
            return False
        path = view.get_path_at_pos(int(event.x), int(event.y))
        if not path:
            return False
        item = self.store[path[0]][5]
        if item and item.get("artist") is None and item.get("id"):
            self._open_playlist(item["id"], item.get("name") or "歌单")
        return False

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
        self.playing_index = next(
            (i for i, item in enumerate(self.playing) if item.get("id") == song.get("id")),
            0,
        )
        self._play_song(song)
        self._refresh_queue_popup()

    def _play_song(self, song):
        self.current_song = song
        self.title_btn.set_label(song["name"])
        self.artist_label.set_text(song["artist"] or "未知歌手")
        self.lyric_title.set_text(song["name"])
        self.lyric_artist.set_text(song["artist"] or "")
        self.lyric_buf.set_text("歌词加载中…")
        self._status(f"正在获取{api.QUALITY_LABEL.get(self.quality, '')}…")
        self._bg(lambda: self._start_song(song))
        if song.get("cover"):
            self._bg(lambda: self._set_remote_image(song["cover"], self.cover, 46))

    def _start_song(self, song):
        try:
            info = api.song_url(song["id"], level=self.quality, cookie=self.cookie)
            text = api.lyric(song["id"], cookie=self.cookie)
        except api.ApiError as exc:
            GLib.idle_add(self._status, str(exc))
            return
        lines = api.parse_lrc(text)
        if not info:
            GLib.idle_add(self._no_url, song, lines)
            return
        self.player.play(info["url"])
        GLib.idle_add(self._started, song, lines, info)

    def _started(self, song, lines, info):
        if self.current_song and self.current_song.get("id") != song.get("id"):
            return False
        self.lyrics = lines
        self.lyric_buf.set_text("\n".join(line for _, line in lines) or "这首歌没有歌词")
        level = info.get("level") or ""
        label = api.QUALITY_LABEL.get(level, level)
        note = "，已按账号权限降级" if level and level != self.quality else ""
        kbps = int((info.get("br") or 0) / 1000)
        self._status(f"正在播放 · {label} · {kbps}kbps {(info.get('type') or '').upper()}{note}")
        self._set_play_icon(True)
        return False

    def _no_url(self, song, lines):
        self.lyrics = lines
        self.lyric_buf.set_text("\n".join(line for _, line in lines) or "这首歌没有歌词")
        self._status(f"「{song['name']}」没有可播放地址。" + ("" if self.cookie else "请先登录。"))
        return False

    def _toggle(self):
        if self.player.playing():
            self.player.pause()
            self._set_play_icon(False)
        elif self.player.paused() and self.current_song:
            self.player.resume()
            self._set_play_icon(True)
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
        self._set_play_icon(self.player.playing())
        return False

    def _set_play_icon(self, playing):
        image = Gtk.Image.new_from_icon_name(
            "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic",
            Gtk.IconSize.BUTTON,
        )
        color = Gdk.RGBA(1, 1, 1, 1) if self._play_hovered else Gdk.RGBA(0.12, 0.12, 0.14, 1)
        for state in (Gtk.StateFlags.NORMAL, Gtk.StateFlags.PRELIGHT, Gtk.StateFlags.ACTIVE):
            image.override_color(state, color)
        self.play_btn.set_image(image)

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
        nxt = self._neighbor(1, wrap=False)
        if nxt is None:
            self._set_play_icon(False)
            self._status("列表已播放完")
        else:
            self._play_from_playing(nxt)
        return False

    def _tick(self):
        song = self.current_song
        if song and (self.player.playing() or self.player.paused()):
            elapsed = self.player.position_ms()
            total = self.player.duration_ms() or song.get("duration") or 1
            if not self.seeking and total:
                self.scale.set_value(min(1000, elapsed * 1000 / total))
            self.time_label.set_text(f"{fmt_time(elapsed)} / {fmt_time(total)}")
            self._highlight_lyric(elapsed)
        return True

    def _seek_on_trough(self, event):
        trough = self.scale.get_range_rect()
        return trough.y - 4 <= event.y <= trough.y + trough.height + 4

    def _seek_press(self, _scale, event):
        if not self._seek_on_trough(event):
            return True
        self.seeking = True
        return False

    def _seek_motion(self, _scale, event):
        if self.seeking and not self._seek_on_trough(event):
            self.seeking = False
        return False

    def _seek_end(self, _scale, event):
        if not self.seeking:
            return True
        self.seeking = False
        if not self._seek_on_trough(event):
            return True
        total = self.player.duration_ms() or (self.current_song or {}).get("duration") or 0
        if total:
            self.player.seek_ms(total * self.scale.get_value() / 1000)
        return False

    def _highlight_lyric(self, elapsed):
        if not self.lyrics or not self.lyric_open:
            return
        current = 0
        for index, (ms, _line) in enumerate(self.lyrics):
            if ms <= elapsed:
                current = index
            else:
                break
        start = self.lyric_buf.get_iter_at_line(current)
        end = self.lyric_buf.get_iter_at_line(current + 1) if current + 1 < len(self.lyrics) else self.lyric_buf.get_end_iter()
        self.lyric_buf.select_range(start, end)
        self.lyric_view.scroll_to_iter(start, 0.2, True, 0.0, 0.42)

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
                    APP_ID, "netease-music-linux", AppIndicator.IndicatorCategory.APPLICATION_STATUS,
                )
                if os.path.exists(ICON) and not ICON.endswith("-generic"):
                    self.indicator.set_icon_full(os.path.abspath(ICON), "网易云音乐")
                else:
                    self.indicator.set_icon_full("audio-x-generic", "网易云音乐")
                self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
                self.indicator.set_menu(menu)
                self.indicator.set_activate_target(show)
                self.indicator.set_title("网易云音乐")
                return
            except Exception:
                self.indicator = None
        if os.path.exists(ICON) and not ICON.endswith("-generic"):
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
        if self.cookie:
            self._account_dialog()
            return
        self._status("正在生成登录二维码…")
        self._bg(self._start_qr)

    def _account_dialog(self):
        name = self.profile.get("nickname") if self.profile else "已登录"
        vip = self.profile.get("vip") if self.profile else ""
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE, text=name,
        )
        dialog.format_secondary_text((vip + "\n" if vip else "") + "退出后会员音质和收藏列表会消失。")
        dialog.add_button("关闭", Gtk.ResponseType.CANCEL)
        dialog.add_button("退出登录", Gtk.ResponseType.OK)
        if dialog.run() == Gtk.ResponseType.OK:
            self.cookie = ""
            self.profile = None
            self.mine = []
            try:
                os.remove(COOKIE_PATH)
            except OSError:
                pass
            self.account_btn.set_label("登录")
            self._fill_nav()
            self._status("已退出登录")
        dialog.destroy()

    def _start_qr(self):
        try:
            key, cookie = api.login_qr_create()
        except Exception as exc:
            GLib.idle_add(self._status, f"生成二维码失败：{exc}")
            return
        path = os.path.join(DATA_DIR, "login-qr.png")
        os.makedirs(DATA_DIR, exist_ok=True)
        subprocess.check_call(["qrencode", "-o", path, "-s", "8", "-m", "2", "https://music.163.com/login?codekey=" + key])
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
        GLib.idle_add(self._account_ready, profile, playlists)

    def _account_ready(self, profile, playlists):
        vip = profile.get("vip") or ""
        self.account_btn.set_label(profile["nickname"] + (f" · {vip}" if vip else ""))
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
            self.win.player.stop()
        self.quit()


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    raise SystemExit(MusicApp().run([os.path.abspath(__file__)]))


if __name__ == "__main__":
    main()
