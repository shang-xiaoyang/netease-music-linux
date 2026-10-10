# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""Qt Quick 播放器入口。主窗口走 Wayland，任务栏用随包音符图标。"""

import json
import os
import signal
import sys

BUS_NAME = "io.netease-music-linux"
BUS_PATH = "/io/netease/music/linux"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PyQt5.QtCore import QEvent, QObject, QSize, Qt, QTimer, QUrl
from PyQt5.QtGui import QGuiApplication, QIcon, QKeyEvent
from PyQt5.QtQuick import QQuickImageProvider
from PyQt5.QtQml import QQmlApplicationEngine

from qt.bridge import AppBridge
from qt.paths import QML_DIR, WINDOW_PATH, icon_path

MIN_WIDTH = 860
MIN_HEIGHT = 560
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 680


def _work_area():
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    return screen.availableGeometry()


def _fit(width, height):
    width = max(MIN_WIDTH, int(width))
    height = max(MIN_HEIGHT, int(height))
    area = _work_area()
    if area is None:
        return width, height
    return min(width, max(MIN_WIDTH, area.width() - 48)), min(height, max(MIN_HEIGHT, area.height() - 32))


def _load_geometry():
    try:
        with open(WINDOW_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
        width = int(data.get("w") or DEFAULT_WIDTH)
        height = int(data.get("h") or DEFAULT_HEIGHT)
        if height < MIN_HEIGHT:
            height = DEFAULT_HEIGHT
        return _fit(width, height), data.get("x"), data.get("y")
    except (OSError, ValueError, TypeError):
        return _fit(DEFAULT_WIDTH, DEFAULT_HEIGHT), None, None


def _save_geometry(window):
    width, height = _fit(window.width(), window.height())
    if width < 200 or height < 200:
        return
    try:
        os.makedirs(os.path.dirname(WINDOW_PATH), exist_ok=True)
        os.chmod(os.path.dirname(WINDOW_PATH), 0o700)
        with open(WINDOW_PATH, "w", encoding="utf-8") as handle:
            json.dump({"w": width, "h": height, "x": window.x(), "y": window.y()}, handle)
    except OSError:
        pass


class IconProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.Pixmap)

    def requestPixmap(self, name, size):
        icon = QIcon.fromTheme(name)
        box = size if size.isValid() else QSize(16, 16)
        pixmap = icon.pixmap(box)
        if pixmap.isNull():
            pixmap = QIcon.fromTheme("image-missing").pixmap(box)
        return pixmap, box


def _name_process():
    """系统监视器读 /proc/pid/comm。prctl 的名字参数必须是字符串地址。"""
    name = b"netease-music"
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        libc.prctl.restype = ctypes.c_int
        if libc.prctl(15, name, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl")
    except (OSError, AttributeError):
        pass
    try:
        sys.argv[0] = "netease-music"
    except Exception:
        pass


class WindowKeys(QObject):
    """窗口内快捷键。Wayland 下按键不一定进这里，全局快捷键另走合成器。"""

    def __init__(self, window, bridge):
        super().__init__(window)
        self._window = window
        self._bridge = bridge
        app = QGuiApplication.instance()
        app.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress and self._window.property("searching"):
            item = self._window.property("searchItem")
            if item is not None:
                local = item.mapFromGlobal(event.globalPos())
                inside = 0 <= local.x() <= item.width() and 0 <= local.y() <= item.height()
                if not inside:
                    self._window.setProperty("blurSearch", True)
            return False
        if event.type() != QEvent.KeyPress or not isinstance(event, QKeyEvent):
            return False
        if QGuiApplication.focusWindow() is not self._window:
            return False
        typing = bool(self._window.property("searching"))
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key_F and mods & Qt.ControlModifier:
            self._window.setProperty("searchWanted", True)
            return True
        if key == Qt.Key_Q and mods & Qt.ControlModifier:
            QGuiApplication.quit()
            return True
        if typing:
            return False
        if key == Qt.Key_Space:
            self._bridge.toggle()
            return True
        if key == Qt.Key_Right:
            self._bridge.seek(int(self._window.property("position") or 0) + 5000)
            return True
        if key == Qt.Key_Left:
            self._bridge.seek(max(0, int(self._window.property("position") or 0) - 5000))
            return True
        if key == Qt.Key_Escape:
            self._window.setProperty("escapeWanted", True)
            return True
        if key == Qt.Key_MediaPlay:
            self._bridge.toggle()
            return True
        if key == Qt.Key_MediaNext:
            self._bridge.next()
            return True
        if key == Qt.Key_MediaPrevious:
            self._bridge.previous()
            return True
        return False


class GlobalHotkeys(QObject):
    """麒麟 Wayland 合成器的全局快捷键。窗口快捷键在这台机器上收不到按键。"""

    def __init__(self, bridge):
        super().__init__()
        self._bridge = bridge
        self.error = ""
        self.ready = []
        try:
            from player import GlobalHotkeys as GtkHotkeys
        except Exception as exc:
            self.error = str(exc)
            return
        self._keys = GtkHotkeys(self._handle)
        self.error = self._keys.error
        self.ready = list(self._keys.ready)

    def _handle(self, action):
        QTimer.singleShot(0, lambda: self._run(action))
        return False

    def _run(self, action):
        if action == "playpause":
            self._bridge.toggle()
        elif action == "next-track":
            self._bridge.next()
        elif action == "prev-track":
            self._bridge.previous()


def _present(window):
    window.show()
    window.raise_()
    window.requestActivate()


def _raise_running():
    """开始菜单会按 D-Bus 名再启动一次。已有实例时只唤起窗口，不再开新进程。"""
    try:
        import dbus
    except ImportError:
        return False
    try:
        bus = dbus.SessionBus()
        if not bus.name_has_owner(BUS_NAME):
            return False
        bus.get_object(BUS_NAME, BUS_PATH).Activate(
            {},
            dbus_interface="org.freedesktop.Application",
        )
    except Exception:
        return False
    return True


class _BusService:
    """占住旧的激活名。已安装的服务文件还会让桌面按这个名字再执行启动脚本。"""

    def __init__(self, on_activate):
        self._on_activate = on_activate
        self._service = None
        try:
            import dbus
            import dbus.service
        except ImportError:
            return
        try:
            bus = dbus.SessionBus()
        except Exception:
            return

        class Service(dbus.service.Object):
            def __init__(self, owner, connection):
                super().__init__(connection, BUS_PATH)
                self._owner = owner

            @dbus.service.method("org.freedesktop.Application", in_signature="a{sv}")
            def Activate(self, _platform_data):
                self._owner._on_activate()

            @dbus.service.method("org.freedesktop.Application", in_signature="asa{sv}")
            def Open(self, _uris, _platform_data):
                self._owner._on_activate()

            @dbus.service.method("org.freedesktop.Application", in_signature="sava{sv}")
            def ActivateAction(self, _action, _parameter, _platform_data):
                self._owner._on_activate()

        try:
            self._name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)
            self._service = Service(self, bus)
            self._bus = bus
        except Exception:
            self._service = None
            self._name = None


def _use_glib_bus():
    try:
        from dbus.mainloop.glib import DBusGMainLoop
    except ImportError:
        return
    DBusGMainLoop(set_as_default=True)


def main():
    _name_process()
    _use_glib_bus()
    if _raise_running():
        return 0
    app = QGuiApplication(sys.argv)
    app.setApplicationName("netease-music")
    app.setDesktopFileName("netease-music-linux")
    app.setApplicationDisplayName("网易云音乐（非官方）")
    app.setOrganizationName("netease-music-linux")
    icon = icon_path()
    if icon:
        app.setWindowIcon(QIcon(icon))
    size, saved_x, saved_y = _load_geometry()
    engine = QQmlApplicationEngine()
    engine.addImageProvider("icon", IconProvider())
    app._bus_service = _BusService(lambda: _present(app.property("playerWindow")))
    bridge = AppBridge()
    context = engine.rootContext()
    context.setContextProperty("navList", bridge.nav)
    context.setContextProperty("cardList", bridge.cards)
    context.setContextProperty("songList", bridge.songs)
    context.setContextProperty("albumList", bridge.albums)
    context.setContextProperty("commentList", bridge.comments)
    context.setContextProperty("downloadList", bridge.downloads)
    context.setContextProperty("queueList", bridge.queue)
    context.setContextProperty("collectList", bridge.collects)
    context.setContextProperty("appBridge", bridge)
    app.aboutToQuit.connect(bridge.stop)
    engine.load(QUrl.fromLocalFile(os.path.join(QML_DIR, "Main.qml")))
    if not engine.rootObjects():
        return 1
    window = engine.rootObjects()[0]
    app.setProperty("playerWindow", window)
    window.setWidth(size[0])
    window.setHeight(size[1])
    area = _work_area()
    if saved_x is None or saved_y is None or area is None:
        if area is not None:
            window.setX(area.x() + max(0, (area.width() - size[0]) // 2))
            window.setY(area.y() + max(0, (area.height() - size[1]) // 2))
    else:
        window.setX(max(area.x(), min(int(saved_x), area.x() + area.width() - 200)))
        window.setY(max(area.y(), min(int(saved_y), area.y() + area.height() - 120)))

    def clamp():
        fitted = _fit(window.width(), window.height())
        if fitted != (window.width(), window.height()):
            window.setWidth(fitted[0])
            window.setHeight(fitted[1])
        _save_geometry(window)

    timer = QTimer()
    timer.setInterval(1500)
    timer.timeout.connect(clamp)
    timer.start()
    app.aboutToQuit.connect(lambda: _save_geometry(window))

    WindowKeys(window, bridge)
    hotkeys = GlobalHotkeys(bridge)

    def report_hotkeys():
        if hotkeys.error:
            bridge.statusChanged.emit("全局快捷键未生效：" + hotkeys.error)
        elif hotkeys.ready:
            bridge.statusChanged.emit("快捷键 " + "、".join(hotkeys.ready))

    QTimer.singleShot(1600, report_hotkeys)
    QTimer.singleShot(0, bridge.start_desktop)

    def present():
        _present(window)

    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator, Gtk
        indicator = AppIndicator.Indicator.new(
            "netease-music-linux",
            icon or "audio-x-generic",
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        menu = Gtk.Menu()

        def on_main(callback):
            def run(_item):
                QTimer.singleShot(0, callback)
            return run

        show = Gtk.MenuItem(label="显示主界面")
        show.connect("activate", on_main(present))
        previous = Gtk.MenuItem(label="上一首")
        previous.connect("activate", on_main(bridge.previous))
        pause = Gtk.MenuItem(label="播放/暂停")
        pause.connect("activate", on_main(bridge.toggle))
        nxt = Gtk.MenuItem(label="下一首")
        nxt.connect("activate", on_main(bridge.next))
        lyric = Gtk.MenuItem(label="桌面歌词")
        lyric.connect("activate", on_main(bridge.toggleDeskLyric))
        quit_item = Gtk.MenuItem(label="退出")
        quit_item.connect("activate", on_main(app.quit))
        for item in (show, previous, pause, nxt, lyric, quit_item):
            menu.append(item)
        menu.show_all()
        indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        indicator.set_menu(menu)
        indicator.set_activate_target(show)
        indicator.set_title("网易云音乐")
        app._indicator = indicator
    except Exception:
        pass
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
