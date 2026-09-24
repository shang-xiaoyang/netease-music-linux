#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""网易云音乐 Linux 客户端（银河麒麟 / WebKitGTK 适配）。

官方没有 Linux 版。这个程序用系统自带的 WebKitGTK 打开网页版，
并补上 Linux 上缺的几件事：持久登录、桌面窗口、媒体快捷键、
下载目录，以及在部分内核上关掉会导致白屏的硬件加速。
"""

import os
import sys

APP_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
if os.path.isdir(APP_LIB):
    os.environ["GI_TYPELIB_PATH"] = (
        APP_LIB + os.pathsep + os.environ.get("GI_TYPELIB_PATH", "")
    ).rstrip(os.pathsep)

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")

from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2

APP_ID = "io.github.shangxiaoyang.netease-music"
HOME_URL = "https://music.163.com/"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

DATA_DIR = os.path.join(GLib.get_user_data_dir(), "netease-cloud-music")
CACHE_DIR = os.path.join(GLib.get_user_cache_dir(), "netease-cloud-music")
DOWNLOAD_DIR = os.path.join(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or os.path.expanduser("~/下载"), "网易云音乐")

ACCEL_FIX = """
(function () {
  if (window.__neteaseLinuxAccel) return;
  window.__neteaseLinuxAccel = true;
  var proto = CanvasRenderingContext2D.prototype;
  if (!proto.__neteasePatched) {
    var orig = proto.getImageData;
    proto.getImageData = function () {
      try { return orig.apply(this, arguments); }
      catch (e) {
        var w = arguments[2] || 1, h = arguments[3] || 1;
        return new ImageData(Math.max(1, w | 0), Math.max(1, h | 0));
      }
    };
    proto.__neteasePatched = true;
  }
})();
"""

EXTERNAL_HOSTS = (
    "music.163.com",
    "163.com",
    "netease.com",
    "126.net",
    "127.net",
    "163yun.com",
    "ydstatic.com",
    "nosdn.127.net",
)


def ensure_dirs():
    for path in (DATA_DIR, CACHE_DIR, DOWNLOAD_DIR, os.path.join(DATA_DIR, "cookies")):
        os.makedirs(path, exist_ok=True)


class NeteaseWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="网易云音乐")
        self.set_default_size(1180, 760)
        self.set_position(Gtk.WindowPosition.CENTER)

        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
        if os.path.exists(icon):
            try:
                self.set_icon_from_file(icon)
            except GLib.Error:
                pass

        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        self.header.set_title("网易云音乐")
        self.header.set_subtitle("Linux 适配版")
        self.set_titlebar(self.header)

        back = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
        back.set_tooltip_text("后退")
        back.connect("clicked", lambda *_: self.webview.go_back() if self.webview.can_go_back() else None)
        forward = Gtk.Button.new_from_icon_name("go-next-symbolic", Gtk.IconSize.BUTTON)
        forward.set_tooltip_text("前进")
        forward.connect("clicked", lambda *_: self.webview.go_forward() if self.webview.can_go_forward() else None)
        reload_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        reload_btn.set_tooltip_text("刷新")
        reload_btn.connect("clicked", lambda *_: self.webview.reload())
        home = Gtk.Button.new_from_icon_name("go-home-symbolic", Gtk.IconSize.BUTTON)
        home.set_tooltip_text("音乐馆")
        home.connect("clicked", lambda *_: self.webview.load_uri(HOME_URL))

        self.header.pack_start(back)
        self.header.pack_start(forward)
        self.header.pack_start(reload_btn)
        self.header.pack_start(home)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_tooltip_text("更多")
        try:
            menu_btn.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        except Exception:
            menu_btn.set_label("☰")
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=8)
        for label, handler in (
            ("在浏览器中打开当前页", self.open_external),
            ("打开下载目录", self.open_downloads),
            ("关于", self.about),
        ):
            b = Gtk.ModelButton(text=label)
            b.connect("clicked", handler)
            box.pack_start(b, False, False, 0)
        box.show_all()
        pop.add(box)
        menu_btn.set_popover(pop)
        self.header.pack_end(menu_btn)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(False)
        self.progress.set_fraction(0)

        self.webview = self._make_webview()
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.webview)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(self.progress, False, False, 0)
        root.pack_start(scroll, True, True, 0)
        self.add(root)

        self.connect("key-press-event", self._on_key)
        self.webview.load_uri(HOME_URL)
        self.show_all()
        self.progress.hide()

    def _make_webview(self):
        data_manager = WebKit2.WebsiteDataManager(
            base_data_directory=DATA_DIR,
            base_cache_directory=CACHE_DIR,
        )
        context = WebKit2.WebContext.new_with_website_data_manager(data_manager)
        cookies = data_manager.get_cookie_manager()
        cookies.set_accept_policy(WebKit2.CookieAcceptPolicy.ALWAYS)
        cookies.set_persistent_storage(
            os.path.join(DATA_DIR, "cookies", "cookies.sqlite"),
            WebKit2.CookiePersistentStorage.SQLITE,
        )
        context.connect("download-started", self._on_download_started)

        settings = self._settings()
        webview = WebKit2.WebView.new_with_context(context)
        webview.set_settings(settings)
        self._arm_view(webview)
        return webview

    def _settings(self):
        settings = WebKit2.Settings()
        settings.set_user_agent(USER_AGENT)
        settings.set_enable_javascript(True)
        settings.set_enable_media(True)
        settings.set_enable_webaudio(True)
        settings.set_enable_mediasource(True)
        settings.set_enable_encrypted_media(True)
        settings.set_enable_webgl(False)
        settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)
        settings.set_enable_accelerated_2d_canvas(False)
        settings.set_media_playback_requires_user_gesture(False)
        settings.set_media_playback_allows_inline(True)
        settings.set_javascript_can_open_windows_automatically(True)
        settings.set_enable_developer_extras(False)
        settings.set_enable_write_console_messages_to_stdout(False)
        settings.set_default_font_family("Noto Sans CJK SC")
        settings.set_sans_serif_font_family("Noto Sans CJK SC")
        settings.set_serif_font_family("Noto Serif CJK SC")
        return settings

    def _arm_view(self, webview):
        webview.get_user_content_manager().add_script(
            WebKit2.UserScript.new(
                ACCEL_FIX,
                WebKit2.UserContentInjectedFrames.ALL_FRAMES,
                WebKit2.UserScriptInjectionTime.START,
                None,
                None,
            )
        )
        webview.connect("load-changed", self._on_load_changed)
        webview.connect("notify::title", self._on_title)
        webview.connect("notify::estimated-load-progress", self._on_progress)
        webview.connect("create", self._on_create)
        webview.connect("decide-policy", self._on_decide_policy)
        webview.connect("permission-request", self._on_permission)

    def _on_title(self, webview, _pspec):
        title = webview.get_title()
        if title:
            self.header.set_title(title.replace(" - 网易云音乐", "").strip() or "网易云音乐")
            self.set_title(title)

    def _on_progress(self, webview, _pspec):
        fraction = webview.get_estimated_load_progress()
        if fraction >= 1.0:
            self.progress.hide()
            return
        self.progress.show()
        self.progress.set_fraction(fraction)

    def _on_load_changed(self, webview, event):
        if event == WebKit2.LoadEvent.FINISHED:
            self.progress.hide()

    def _on_create(self, webview, navigation):
        # 登录、支付走共享 Cookie 的小窗口；其它外链交给系统浏览器。
        try:
            uri = navigation.get_request().get_uri() or ""
        except Exception:
            uri = ""
        if uri.startswith(("http://", "https://")) and not self._is_music_host(uri):
            self._open_uri(uri)
            return None

        dialog = Gtk.Window(transient_for=self, title="网易云音乐")
        dialog.set_default_size(520, 680)
        dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        child = WebKit2.WebView.new_with_related_view(webview)
        self._arm_view(child)
        child.connect("close", lambda *_: dialog.destroy())
        dialog.add(child)
        dialog.show_all()
        return child

    def _on_decide_policy(self, webview, decision, decision_type):
        if decision_type != WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        try:
            uri = decision.get_request().get_uri()
        except Exception:
            return False
        if not uri or uri.startswith(("about:", "data:", "blob:")):
            return False
        if uri.startswith(("http://", "https://")) and not self._is_music_host(uri):
            decision.ignore()
            self._open_uri(uri)
            return True
        return False

    def _on_permission(self, webview, request):
        # 网页版播放不需要麦克风；通知和自动播放直接允许。
        name = request.__class__.__name__
        if "UserMedia" in name or "Device" in name:
            request.deny()
        else:
            try:
                request.allow()
            except Exception:
                pass
        return True

    def _on_download_started(self, _context, download):
        def decide(_download, suggested):
            name = suggested or "download"
            name = os.path.basename(name.replace("\\", "/")) or "download"
            dest = os.path.join(DOWNLOAD_DIR, name)
            base, ext = os.path.splitext(dest)
            n = 1
            while os.path.exists(dest):
                dest = f"{base}-{n}{ext}"
                n += 1
            download.set_destination("file://" + dest)
            download.set_allow_overwrite(False)
            self._notify("开始下载", os.path.basename(dest))
            return True

        def finished(_download):
            dest = download.get_destination() or ""
            path = dest[7:] if dest.startswith("file://") else dest
            self._notify("下载完成", os.path.basename(path) or "文件已保存")

        def failed(_download, error):
            self._notify("下载失败", str(error))

        download.connect("decide-destination", decide)
        download.connect("finished", finished)
        download.connect("failed", failed)

    def _on_key(self, _win, event):
        action = {
            "XF86AudioPlay": "play",
            "XF86AudioPause": "play",
            "XF86AudioNext": "next",
            "XF86AudioPrev": "prev",
        }.get(Gdk.keyval_name(event.keyval) or "")
        if not action:
            return False
        self._media(action)
        return True

    def _media(self, action):
        script = {
            "play": """
                (function () {
                  var btn = document.querySelector('.ply, .prv, .nxt, [data-action=play], .m-playbar .ply');
                  var play = document.querySelector('.m-playbar .ply, .btns .ply, .f-cb .ply');
                  if (play) { play.click(); return; }
                  var audio = document.querySelector('audio, video');
                  if (!audio) return;
                  if (audio.paused) audio.play(); else audio.pause();
                })();
            """,
            "next": """
                (function () {
                  var btn = document.querySelector('.m-playbar .nxt, .btns .nxt');
                  if (btn) btn.click();
                })();
            """,
            "prev": """
                (function () {
                  var btn = document.querySelector('.m-playbar .prv, .btns .prv');
                  if (btn) btn.click();
                })();
            """,
        }[action]
        self.webview.run_javascript(script, None, None, None)

    def open_external(self, *_):
        uri = self.webview.get_uri() or HOME_URL
        self._open_uri(uri)

    def open_downloads(self, *_):
        self._open_uri("file://" + DOWNLOAD_DIR)

    def about(self, *_):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="网易云音乐 Linux 适配版",
        )
        dialog.format_secondary_text(
            "网易云没有官方 Linux 客户端。\n"
            "这是基于网页版、为银河麒麟 V11（ARM64）做的独立窗口适配：\n"
            "登录状态会保存在本机，播放使用系统音频。\n\n"
            "会员专享、部分付费歌曲仍受网页版本身的限制。"
        )
        dialog.run()
        dialog.destroy()

    def _notify(self, summary, body):
        try:
            note = Gio.Notification.new(summary)
            note.set_body(body)
            self.get_application().send_notification(None, note)
        except Exception:
            pass

    @staticmethod
    def _is_music_host(uri):
        try:
            host = Gio.File.new_for_uri(uri).get_uri().split("/")[2].split(":")[0].lower()
        except Exception:
            return False
        return any(host == item or host.endswith("." + item) for item in EXTERNAL_HOSTS)

    @staticmethod
    def _is_external(uri):
        return uri.startswith(("http://", "https://"))

    @staticmethod
    def _open_uri(uri):
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error:
            pass


class NeteaseApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )

    def do_startup(self):
        Gtk.Application.do_startup(self)
        ensure_dirs()

    def do_activate(self):
        win = self.get_active_window()
        if win is None:
            win = NeteaseWindow(self)
        win.present()


def main():
    ensure_dirs()
    app = NeteaseApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
