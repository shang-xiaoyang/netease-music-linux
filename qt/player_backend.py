# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""GStreamer 播放后端。界面只收信号，不在界面线程查询管道。"""

import os
import threading
import time
import urllib.parse
import urllib.request

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

Gst.init(None)


def _under(path, root):
    root = os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def allowed_uri(url):
    """远程只允许网易云的 https。本地只允许音乐目录或播放缓存里的真实文件。"""
    parsed = urllib.parse.urlparse(str(url or ""))
    host = parsed.hostname or ""
    remote = parsed.scheme == "https" and (
        host == "music.163.com" or host.endswith(".music.163.com") or host.endswith(".126.net")
    )
    if remote:
        return True
    if parsed.scheme != "file":
        return False
    path = os.path.realpath(urllib.request.url2pathname(parsed.path))
    if not os.path.isfile(path):
        return False
    music = os.path.join(os.path.expanduser("~/Music"), "网易云音乐")
    legacy = os.path.join(os.path.expanduser("~"), "音乐", "网易云音乐")
    cache = os.path.join(os.path.expanduser("~/.cache"), "netease-cloud-music", "playback")
    return _under(path, music) or _under(path, legacy) or _under(path, cache)


class PlayerBackend(QObject):
    stateChanged = pyqtSignal(str)
    positionChanged = pyqtSignal(int, int)
    errorChanged = pyqtSignal(str)
    ended = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.playbin = Gst.ElementFactory.make("playbin", "netease-qt")
        if self.playbin is None:
            raise RuntimeError("GStreamer playbin 不可用")
        # 只留 1 秒缓冲。攒太久时，母带流会先空等十几秒才出声。
        # BUFFERING 打开后，缓冲见底会发消息，由下面先暂停、够了再接着播。
        flags = int(self.playbin.get_property("flags"))
        self.playbin.set_property("flags", flags | (1 << 8))
        self.playbin.set_property("buffer-duration", 1 * Gst.SECOND)
        self.playbin.set_property("buffer-size", 512 * 1024)
        self._want = "stopped"
        self._uri = ""
        self._position = 0
        self._duration = 0
        self._anchor = 0
        self._started_at = 0.0
        self._seek_target = None
        self._seek_stamp = 0.0
        self._rate = 1.0
        self._clock = None
        self._held_pause = False
        self._paused_at = 0.0
        self._buffering = False
        self._lock = threading.Lock()
        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

    def want(self):
        return self._want

    def position(self):
        # 只返回管道报过的位置。按时钟往前猜的话，网络卡住没声音，进度还会自己走。
        with self._lock:
            return self._position, self._duration

    def begin_switch(self, keep=0):
        keep = max(0, int(keep or 0))
        with self._lock:
            self._want = "playing"
            self._held_pause = False
            self._paused_at = 0.0
            self._position = keep
            self._duration = 0
            self._anchor = keep
            self._started_at = 0
            self._seek_target = keep if keep else None
            self._seek_stamp = time.time()
        self.playbin.set_state(Gst.State.NULL)
        # 管道还没出声，图标和进度先停住。真正开始后再标成播放中。
        self.stateChanged.emit("paused")
        if not keep:
            self.positionChanged.emit(0, 0)

    @pyqtSlot(str)
    def play(self, url):
        if not allowed_uri(url):
            self.errorChanged.emit("播放地址不被允许")
            return
        self.playbin.set_state(Gst.State.NULL)
        with self._lock:
            keep = self._position if self._seek_target else 0
            self._position = keep
            self._duration = 0
            self._anchor = keep
            # 管道还没出声。锚点留空，进度停在上次位置，等真正开始再走。
            self._started_at = 0
            self._want = "playing"
            self._held_pause = False
            self._paused_at = 0.0
            self._buffering = False
            if not keep:
                self._seek_target = None
        self.playbin.set_property("uri", url)
        self._uri = url
        # 本机缓存不用等。网络流只留 1 秒，避免母带还没出声就空等。
        self.playbin.set_property("buffer-duration", 0 if url.startswith("file:") else 1 * Gst.SECOND)
        self.playbin.set_state(Gst.State.PLAYING)
        # 续播还没跳到原进度时，不要把时长发成 0，否则界面会停在暂停。
        if not keep:
            self.positionChanged.emit(0, 0)
        self._ensure_clock()
        # 续播位置已经在 begin_switch 里记下了。等管道能定位再跳，不要另起一次。
        if keep > 500:
            threading.Thread(target=self._seek_worker, args=(keep,), daemon=True).start()

    @pyqtSlot()
    def pause(self):
        held = self._position
        try:
            ok, value = self.playbin.query_position(Gst.Format.TIME)
            if ok and value > 0:
                held = int(value / 1_000_000)
        except Exception:
            pass
        with self._lock:
            self._want = "paused"
            self._held_pause = True
            self._paused_at = time.time()
            self._position = held
            self._anchor = held
            self._started_at = 0
        self.playbin.set_state(Gst.State.PAUSED)
        self.stateChanged.emit("paused")

    @pyqtSlot()
    def has_source(self):
        with self._lock:
            if not self._uri:
                return False
            # 暂停超过 20 分钟，流地址多半已经被服务器掐掉。当作没有源，让调用方重开这首。
            paused_at = self._paused_at
        return not paused_at or time.time() - paused_at <= 20 * 60

    def heard(self):
        """管道实际播到的位置。不把时钟猜出来的进度算进去。"""
        try:
            ok, value = self.playbin.query_position(Gst.Format.TIME)
        except Exception:
            return 0
        if not ok or value <= 0:
            return 0
        return int(value / 1_000_000)

    def drop_source(self):
        """旧流已经不能续播。进度留下，地址清掉，避免失败被当成唱完。"""
        with self._lock:
            self._uri = ""
            self._held_pause = False
            self._paused_at = 0.0
            self._started_at = 0
        try:
            self.playbin.set_state(Gst.State.NULL)
        except Exception:
            pass

    def resume(self):
        if not self.has_source():
            return False
        with self._lock:
            held = self._position
            self._want = "playing"
            self._held_pause = False
            self._paused_at = 0.0
            self._anchor = held
            # 暂停只是把同一条管道停住。接着播不要再定位，定位会把缓冲冲掉，听起来又卡一下。
            self._started_at = time.time()
            self._seek_target = None
        state = Gst.State.NULL
        try:
            _ok, state, _pending = self.playbin.get_state(0)
        except Exception:
            state = Gst.State.NULL
        if state == Gst.State.NULL and self._uri:
            self.playbin.set_property("uri", self._uri)
        self.playbin.set_state(Gst.State.PLAYING)
        self._ensure_clock()
        self.stateChanged.emit("playing")
        return True

    @pyqtSlot()
    def stop(self):
        # 管道停到 NULL 之后再问位置会得到 0。退出前先把听到的进度留下。
        heard = self.heard()
        with self._lock:
            if heard > 0:
                self._position = heard
                self._anchor = heard
            self._want = "stopped"
            self._held_pause = False
            self._paused_at = 0.0
            self._started_at = 0
        self.playbin.set_state(Gst.State.NULL)
        self._uri = ""
        self.stateChanged.emit("stopped")

    def set_rate(self, rate):
        rate = float(rate)
        with self._lock:
            self._rate = rate
            position = self._position
        try:
            self.playbin.seek(
                rate,
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                Gst.SeekType.SET,
                int(position) * Gst.MSECOND,
                Gst.SeekType.NONE,
                0,
            )
        except Exception:
            return False
        return True

    @pyqtSlot(int)
    def seek(self, ms):
        target = max(0, int(ms))
        with self._lock:
            self._position = target
            self._anchor = target
            # 定位完成前不外推，避免进度先于声音往前走。
            self._started_at = 0
            self._seek_target = target
            self._seek_stamp = time.time()
            duration = self._duration
        self.positionChanged.emit(target, duration)
        threading.Thread(target=self._seek_worker, args=(target,), daemon=True).start()

    def _on_message(self, _bus, message):
        if message.type == Gst.MessageType.EOS:
            with self._lock:
                held = self._held_pause or self._want != "playing"
                kept = self._position
                if held:
                    # 暂停太久时连接会被掐断。这不是唱完，进度留在暂停处，下次重开这首。
                    self._want = "paused"
                    self._held_pause = True
                    self._paused_at = time.time()
                    self._started_at = 0
                    self._uri = ""
                    self._position = kept
                    self._anchor = kept
                else:
                    self._want = "paused"
                    self._started_at = 0
                    # 文件结束时管道位置经常是 0。先记下结束前的进度，否则截断的缓存会被当成从头唱完。
                    try:
                        ok, value = self.playbin.query_position(Gst.Format.TIME)
                    except Exception:
                        ok, value = False, 0
                    if ok and value > 0:
                        heard = int(value / 1_000_000)
                        self._position = heard
                        self._anchor = heard
            if held:
                self.playbin.set_state(Gst.State.NULL)
                self.stateChanged.emit("paused")
                return
            self.stateChanged.emit("paused")
            self.ended.emit()
        elif message.type == Gst.MessageType.ERROR:
            err, _debug = message.parse_error()
            with self._lock:
                held = self._held_pause
                if held:
                    self._want = "paused"
                    self._paused_at = time.time()
                    self._started_at = 0
                    self._uri = ""
                else:
                    self._want = "stopped"
                    self._started_at = 0
            if held:
                self.playbin.set_state(Gst.State.NULL)
                self.stateChanged.emit("paused")
                return
            self.stateChanged.emit("stopped")
            self.errorChanged.emit(str(err).split("\n", 1)[0])
        elif message.type == Gst.MessageType.BUFFERING and self._want == "playing" and not self._held_pause:
            # 本机文件不用这一套。网络流缓冲不够时先停住，超前播放位置再接着播。
            if str(self._uri).startswith("file:"):
                return
            percent = int(message.parse_buffering())
            if percent < self._resume_percent():
                if not self._buffering:
                    self._buffering = True
                    self.playbin.set_state(Gst.State.PAUSED)
                    self.stateChanged.emit("buffering")
            elif self._buffering:
                self._buffering = False
                if self._want == "playing" and not self._held_pause:
                    self.playbin.set_state(Gst.State.PLAYING)
                    self.stateChanged.emit("playing")
        elif message.type == Gst.MessageType.ASYNC_DONE and self._want == "playing":
            with self._lock:
                if self._want == "playing" and not self._seek_target:
                    self._started_at = time.time()
                    position = self._position
                    duration = self._duration
                else:
                    position = None
            if position is not None:
                self.stateChanged.emit("playing")
                self.positionChanged.emit(position, duration)

    def _ensure_clock(self):
        if self._clock and self._clock.is_alive():
            return
        self._clock = threading.Thread(target=self._clock_loop, daemon=True)
        self._clock.start()

    def _clock_loop(self):
        while self._want in ("playing", "paused"):
            # 暂停时进度已经停住，不用再问管道。
            if self._want != "playing":
                time.sleep(0.4)
                continue
            # 缓冲见底由总线消息在界面线程暂停。这里再改状态会和它抢管道。
            if self._buffering:
                time.sleep(0.3)
                continue
            pos = dur = 0
            try:
                ok, value = self.playbin.query_position(Gst.Format.TIME)
                if ok and value > 0:
                    pos = int(value / 1_000_000)
                ok, value = self.playbin.query_duration(Gst.Format.TIME)
                if ok and value > 0:
                    dur = int(value / 1_000_000)
            except Exception:
                pos = dur = 0
            self._store(pos, dur)
            # 正在跳转时勤一点，出声后界面才能马上从暂停变成播放。
            time.sleep(0.2 if self._seek_target else 1.0)

    def _resume_percent(self):
        """缓冲比当前播放位置超前约 2% 就可以接着播，最多不超过整首的 30%。"""
        with self._lock:
            position = self._position
            duration = self._duration
        if duration <= 0:
            return 2
        ahead = int(100 * position / duration) + 2
        return min(30, max(2, ahead))

    def _store(self, pos, dur):
        emit = False
        with self._lock:
            if self._want != "playing":
                pos = 0
            landed = self._seek_landed(pos)
            if landed and pos > 0:
                # 缓冲没稳时位置会一下跳到很后面再回到开头。这种回跳不往外发。
                # 回跳只在回到开头时收下。卡在中间时位置来回抖，不能把进度和歌词带着循环。
                backward = self._position and pos + 1500 < self._position
                if not (backward and pos > 8000):
                    self._position = pos
                    self._anchor = pos
                self._started_at = time.time()
                was_seeking = self._seek_target is not None
                self._seek_target = None
                emit = True
            else:
                was_seeking = False
            # 刚开播时管道会先报一个接近整首的位置。那不是真的唱完，不能拿去切歌。
            if dur and pos and pos < dur - 1500 and dur != self._duration:
                self._duration = dur
                emit = True
            current = self._position
            duration = self._duration
        if emit and was_seeking:
            self.stateChanged.emit("playing")
        if emit:
            self.positionChanged.emit(current, duration)

    def _seek_landed(self, pos):
        target = self._seek_target
        if target is None:
            return True
        if time.time() - self._seek_stamp > 4:
            self._seek_target = None
            return True
        return abs(pos - target) < 1500

    def _seek_worker(self, target):
        """管道从空切到播放时，定位请求会直接失败。等到能暂停或播放再跳。"""
        try:
            ready = False
            for _ in range(16):
                with self._lock:
                    if self._seek_target is None or self._want != "playing":
                        return
                _ok, state, pending = self.playbin.get_state(250 * Gst.MSECOND)
                if state in (Gst.State.PAUSED, Gst.State.PLAYING) or pending in (Gst.State.PAUSED, Gst.State.PLAYING):
                    ready = True
                    break
                if state == Gst.State.NULL:
                    time.sleep(0.12)
                    continue
                self.playbin.set_state(Gst.State.PAUSED)
            if not ready:
                with self._lock:
                    if self._seek_target == target:
                        self._seek_target = None
                        self._started_at = time.time()
                if self._want == "playing":
                    self.stateChanged.emit("playing")
                return
            flags = Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE
            ok = self.playbin.seek_simple(Gst.Format.TIME, flags, int(target) * Gst.MSECOND)
            if not ok:
                self.playbin.seek_simple(
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    int(target) * Gst.MSECOND,
                )
            # 已经在播放时再切一次 PLAYING，会把刚跳到的位置清回开头。
            if self._want != "playing":
                return
            _ok, state, _pending = self.playbin.get_state(0)
            if state != Gst.State.PLAYING:
                self.playbin.set_state(Gst.State.PLAYING)
        except Exception:
            with self._lock:
                if self._seek_target == target:
                    self._seek_target = None
                    self._started_at = time.time()
            if self._want == "playing":
                self.stateChanged.emit("playing")
