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
    cache = os.path.join(os.path.expanduser("~/.cache"), "netease-cloud-music", "playback")
    return _under(path, music) or _under(path, cache)


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
        self._lock = threading.Lock()
        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

    def want(self):
        return self._want

    def position(self):
        with self._lock:
            if self._want == "playing" and self._started_at:
                guessed = self._anchor + int((time.time() - self._started_at) * 1000)
                if guessed > self._position:
                    self._position = guessed
            return self._position, self._duration

    def begin_switch(self, keep=0):
        keep = max(0, int(keep or 0))
        with self._lock:
            self._want = "playing"
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
            if not keep:
                self._seek_target = None
        self.playbin.set_property("uri", url)
        self._uri = url
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
            self._position = held
            self._anchor = held
            self._started_at = 0
        self.playbin.set_state(Gst.State.PAUSED)
        self.stateChanged.emit("paused")

    @pyqtSlot()
    def has_source(self):
        if self._uri:
            return True
        try:
            return bool(self.playbin.get_property("uri"))
        except Exception:
            return False

    def resume(self):
        if not self.has_source():
            return False
        with self._lock:
            held = self._position
            self._want = "playing"
            self._anchor = held
            # 续播定位还没落地。先不走进度，等 ASYNC_DONE 或定位到达再开始。
            self._started_at = 0
            self._seek_target = held if held > 500 else None
            self._seek_stamp = time.time()
        state = Gst.State.NULL
        try:
            _ok, state, _pending = self.playbin.get_state(0)
        except Exception:
            state = Gst.State.NULL
        if state == Gst.State.NULL and self._uri:
            self.playbin.set_property("uri", self._uri)
        self.playbin.set_state(Gst.State.PLAYING)
        self._ensure_clock()
        if held > 500:
            threading.Thread(target=self._seek_worker, args=(held,), daemon=True).start()
        return True

    @pyqtSlot()
    def stop(self):
        with self._lock:
            self._want = "stopped"
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
                self._want = "paused"
                self._started_at = 0
            self.stateChanged.emit("paused")
            self.ended.emit()
        elif message.type == Gst.MessageType.ERROR:
            err, _debug = message.parse_error()
            with self._lock:
                self._want = "stopped"
                self._started_at = 0
            self.stateChanged.emit("stopped")
            self.errorChanged.emit(str(err).split("\n", 1)[0])
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

    def _store(self, pos, dur):
        emit = False
        with self._lock:
            if self._want != "playing":
                pos = 0
            landed = self._seek_landed(pos)
            if landed:
                if pos:
                    self._position = pos
                    self._anchor = pos
                self._started_at = time.time()
                was_seeking = self._seek_target is not None
                self._seek_target = None
                emit = True
            else:
                was_seeking = False
            if dur and dur != self._duration:
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
            # 跳完后恢复播放。上面为了能定位可能停在暂停。
            if self._want == "playing":
                self.playbin.set_state(Gst.State.PLAYING)
        except Exception:
            with self._lock:
                if self._seek_target == target:
                    self._seek_target = None
                    self._started_at = time.time()
            if self._want == "playing":
                self.stateChanged.emit("playing")
