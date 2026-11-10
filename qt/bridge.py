# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""把现有接口和播放后端交给 QML。QML 只发意图，不直接请求网易。

AppBridge 仍是一个对象：界面、播放和下载要看同一份当前歌曲。
按职责分段，方便接着加功能，不把互相调用拆散：

- 窗口和账号：bind_window 到 openNav
- 页面和歌单：_capture 到 openUser
- 播放和缓存：playRow 到 _cache_ended_early
- 下载管理：enqueueDownload 到 retryFailedDownloads
"""

import json
import logging
import os
import random
import urllib.parse
import urllib.request
import subprocess
import sys
import threading
import time

from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal, pyqtSlot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import netease_api as api

from qt.models import DictListModel
from qt.paths import COOKIE_PATH, DATA_DIR, DOWNLOAD_INDEX, LOG_PATH, LYRIC_PATH, LYRIC_STATE_PATH, LYRIC_TRACK_PATH, RECENT_PATH, SEARCH_HISTORY_PATH, STATE_PATH, VOLUME_PATH, player_script
from qt.playback_cache import lookup as cache_lookup
from qt.playback_cache import network_down as cache_network_down
from qt.playback_cache import store as cache_store
from qt.player_backend import PlayerBackend, allowed_uri

def _logger():
    """每次运行都写到数据目录。出问题时不用再靠界面上那一行状态猜。"""
    log = logging.getLogger("netease.qt")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        handle = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handle.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handle)
    except OSError:
        log.addHandler(logging.NullHandler())
    return log


LOG = _logger()

MODES = ("loop", "order", "single", "shuffle")
MODE_LABEL = {
    "loop": "列表循环",
    "order": "列表播放",
    "single": "单曲循环",
    "shuffle": "随机播放",
}


class AppBridge(QObject):
    statusChanged = pyqtSignal(str)
    stateChanged = pyqtSignal(str)
    clockChanged = pyqtSignal(str)
    songChanged = pyqtSignal(str)
    pageChanged = pyqtSignal(str, str)
    currentSongChanged = pyqtSignal(str)
    accountChanged = pyqtSignal(str)
    modeChanged = pyqtSignal(str)
    qualityChanged = pyqtSignal(str)
    volumeChanged = pyqtSignal(float)
    rateChanged = pyqtSignal(float)
    coverChanged = pyqtSignal(str)
    historyChanged = pyqtSignal(str)
    likedChanged = pyqtSignal(bool)
    lyricChanged = pyqtSignal(str)
    deskLyricChanged = pyqtSignal(bool)
    detailChanged = pyqtSignal(str)
    artistTabChanged = pyqtSignal(str)
    playlistMetaChanged = pyqtSignal(str)
    loginKeyChanged = pyqtSignal(str)
    qualitiesChanged = pyqtSignal(str)
    suggestChanged = pyqtSignal(str)
    listCountChanged = pyqtSignal(int)
    _uiReady = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.player = PlayerBackend()
        self.player.stateChanged.connect(self._on_player_state)
        self.player.positionChanged.connect(self._on_position)
        self.player.errorChanged.connect(self._on_player_error)
        self.player.ended.connect(self._on_ended)
        self.songs = DictListModel(("songId", "name", "artist", "artistId", "artists", "album", "albumId", "cover", "local", "duration", "vip", "playable", "saved"))
        self.queue = DictListModel(("songId", "name", "artist", "cover", "duration", "playable"))
        self.nav = DictListModel(("key", "label", "kind", "section", "cover", "local", "owned"))
        self.cards = DictListModel(("itemId", "name", "cover", "local", "count", "kind", "creator", "creatorId"))
        self.collects = DictListModel(("itemId", "name", "cover", "local", "count", "kind"))
        self.albums = DictListModel(("itemId", "name", "cover", "local", "publish", "size"))
        self.events = DictListModel(("title", "summary", "when", "cover", "local", "read"))
        self.comments = DictListModel(("nickname", "userId", "avatar", "local", "content", "when", "liked", "hot"))
        self.downloads = DictListModel(("name", "status", "quality", "path", "songId", "group"))
        self._cookie = ""
        self._song = None
        self._queue = []
        self._index = -1
        self._token = 0
        self._mode = "loop"
        self._quality = "sky"
        self._rate = 1.0
        self._page = "home"
        self._page_title = "推荐"
        self._album_id = ""
        self._navigation_revision = 0
        self._history = []
        self._detail_text = ""
        self._detail_cover = ""
        self._artist_id = ""
        self._artist_tab = "songs"
        self._artist_desc_loaded = False
        self._loading_pos = False
        self._ui_playing = False
        self._volume = self._saved_volume()
        self.player.playbin.set_property("volume", self._volume)
        self._liked = set()
        self._lyrics = []
        self._lyric_words = []
        self._desk_lyric_proc = None
        self._desk_lyric_payload = None
        self._profile = None
        self._login = {"done": True, "key": "", "cookie": ""}
        self._mine = []
        self._comment_offset = 0
        self._comment_song = None
        self._comment_tab = "hot"
        self._comment_data = {}
        self._can_remove = False
        self._download_rows = self._load_downloads()
        self._download_worker = None
        self._download_lock = threading.Lock()
        self._download_paused = False
        self._download_wake = threading.Event()
        self._supported = []
        self._list_token = 0
        self._list_id = ""
        self._list_total = 0
        self._list_offset = 0
        self._list_title = ""
        self._list_more = False
        self._list_refs = None
        self._restore_after_boot = False
        self._queue_source = ""
        self._queue_title = ""
        self._ui_queue = []
        self._ui_lock = threading.Lock()
        self._alive = True
        self._cache_job = None
        self._cache_wake = threading.Event()
        self._cache_worker_on = False
        self._cache_net_down = False
        self._prefetch_job = None
        self._prefetch_wake = threading.Event()
        self._prefetch_on = False
        self._clock = QTimer(self)
        # 进度条自己按墙钟走。这一拍只校正漂移，并偶尔把桌面歌词的进度对一下。
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._emit_clock)
        self._clock.start()
        self._lyric_sync_at = 0.0
        self._uiReady.connect(self._drain_ui, Qt.QueuedConnection)
        self._window = None
        self._pending_window = {}
        self._bind_window_signals()
        self._fill_nav()
        if any(item.get("status") == "等待" and item.get("song") for item in self._download_rows):
            self._ensure_download_worker()
        self.historyChanged.emit("\n".join(self._load_search_history()))
        self.accountChanged.emit("登录")
        self.qualityChanged.emit(api.QUALITY_LABEL.get(self._quality, self._quality))
        threading.Thread(target=self._boot, daemon=True).start()

    def start_desktop(self):
        """窗口已经起来。播放栏在界面线程立刻恢复，不跟账号和推荐页抢。"""
        self._restore_state()
        if self._desk_lyric_wanted():
            self._launch_desk_lyric()

    def bind_window(self, window):
        """界面信号改写成窗口属性。Connections 的两种写法分别只认 Qt 5.12 或 5.15。"""
        self._window = window
        pending = self._pending_window
        self._pending_window = {}
        for name, value in pending.items():
            window.setProperty(name, value)

    def _bind_window_signals(self):
        pairs = (
            (self.statusChanged, "bridgeStatus"),
            (self.suggestChanged, "bridgeSuggest"),
            (self.stateChanged, "bridgeState"),
            (self.clockChanged, "bridgeClock"),
            (self.songChanged, "bridgeSong"),
            (self.accountChanged, "bridgeAccount"),
            (self.modeChanged, "bridgeMode"),
            (self.qualityChanged, "bridgeQuality"),
            (self.coverChanged, "bridgeCover"),
            (self.detailChanged, "bridgeDetail"),
            (self.lyricChanged, "bridgeLyric"),
            (self.artistTabChanged, "bridgeArtistTab"),
            (self.historyChanged, "bridgeHistory"),
            (self.loginKeyChanged, "bridgeLoginKey"),
            (self.qualitiesChanged, "bridgeQualities"),
            (self.currentSongChanged, "bridgeCurrentSong"),
            (self.playlistMetaChanged, "bridgePlaylistMeta"),
            (self.listCountChanged, "bridgeListCount"),
        )
        for signal, prop in pairs:
            signal.connect(
                lambda value, name=prop: self._write_window(name, value),
                Qt.QueuedConnection,
            )
        self.pageChanged.connect(
            lambda name, title: self._write_window("bridgePage", f"{name}\n{title}"),
            Qt.QueuedConnection,
        )
        self.listCountChanged.connect(
            lambda count: self._write_window("bridgeListCount", count),
            Qt.QueuedConnection,
        )
        self.rateChanged.connect(
            lambda value: self._write_window("bridgeRate", value),
            Qt.QueuedConnection,
        )
        self.volumeChanged.connect(
            lambda value: self._write_window("bridgeVolume", value),
            Qt.QueuedConnection,
        )
        self.likedChanged.connect(
            lambda value: self._write_window("bridgeLiked", "1" if value else "0"),
            Qt.QueuedConnection,
        )

    def _write_window(self, name, value):
        text = "" if value is None else str(value)
        window = self._window
        if window is None:
            self._pending_window[name] = text
            return
        window.setProperty(name, text)

    def _post(self, kind, payload):
        if not self._alive:
            return
        with self._ui_lock:
            self._ui_queue.append((kind, payload))
        self._uiReady.emit(kind)

    @pyqtSlot(str)
    def _drain_ui(self, _kind):
        with self._ui_lock:
            batch = self._ui_queue
            self._ui_queue = []
        for kind, payload in batch:
            if kind == "cards":
                self._apply_cards(*payload)
            elif kind == "songs":
                self._apply_songs(*payload[:7], refs=payload[7] if len(payload) > 7 else None)
            elif kind == "dropSong":
                self._drop_song_row(*payload)
            elif kind == "dropSongs":
                self._drop_songs(*payload)
            elif kind == "listCount":
                token, count = payload
                if token == self._list_token:
                    self.listCountChanged.emit(int(count or 0))
            elif kind == "albums":
                self._apply_albums(payload)
            elif kind == "events":
                self.events.replace(payload)
            elif kind == "artistDesc":
                self._apply_artist_desc(payload)
            elif kind == "detail":
                self._apply_detail(*payload)
            elif kind == "detailPage":
                token, detail = payload
                if token == self._list_token:
                    self._apply_detail(*detail)
            elif kind == "playlistMeta":
                if isinstance(payload, tuple) and len(payload) == 2:
                    token, meta = payload
                    if token != self._list_token:
                        continue
                else:
                    meta = payload
                self._playlist_meta = dict(meta or {})
                self.playlistMetaChanged.emit("|".join((
                    "1" if self._playlist_meta.get("owned") else "0",
                    "1" if self._playlist_meta.get("collected") else "0",
                    str(self._playlist_meta.get("special") or 0),
                    str(self._playlist_meta.get("creator") or ""),
                    str(self._playlist_meta.get("creatorName") or "").replace("|", " "),
                )))
            elif kind == "queueNext":
                songs, name = payload[0], payload[1]
                append = payload[2] if len(payload) > 2 else False
                self._queue_songs_next(songs, name, append=append)
            elif kind == "batchPlay":
                songs, name, revision, token = payload
                if revision == self._navigation_revision and token == self._list_token:
                    self._play_batch_songs(songs, name)
            elif kind == "batchQueue":
                songs, name, revision, token = payload
                if revision == self._navigation_revision and token == self._list_token:
                    self._queue_songs_next(songs, name)
            elif kind == "batchDownload":
                songs, revision, token = payload
                if revision == self._navigation_revision and token == self._list_token:
                    self._enqueue_download_songs(songs)
            elif kind == "batchCollectPopup":
                revision, token = payload
                if revision == self._navigation_revision and token == self._list_token:
                    self._write_window("batchCollectOpen", "1")
            elif kind == "batchStatus":
                revision, token, message = payload
                if revision == self._navigation_revision and token == self._list_token:
                    self.statusChanged.emit(message)
            elif kind == "home":
                self.openHome()
            elif kind == "renamed":
                playlist_id, name = payload
                if str(self._list_id) == playlist_id and self._page == "playlist":
                    self._page_title = name
                    self.pageChanged.emit("playlist", name)
                self.statusChanged.emit(f"已重命名为「{name}」")
            elif kind == "account":
                self.accountChanged.emit(payload)
            elif kind == "status":
                self.statusChanged.emit(payload)
            elif kind == "comments":
                self.comments.replace(payload)
            elif kind == "downloads":
                self.downloads.replace(payload)
                self._mark_downloaded()
            elif kind == "login":
                self.loginKeyChanged.emit(payload)
            elif kind == "suggest":
                self.suggestChanged.emit(payload)
            elif kind == "qualities":
                self.qualitiesChanged.emit(payload)
            elif kind == "lyric":
                self.lyricChanged.emit(payload)
            elif kind == "history":
                self.historyChanged.emit(payload or "")
            elif kind == "play":
                self.player.play(payload)
            elif kind == "pause":
                self.player.pause()
            elif kind == "resume":
                self.player.resume()
            elif kind == "seek":
                self.player.seek(payload)
            elif kind == "stop":
                self.player.stop()
            elif kind == "volume":
                self.player.playbin.set_property("volume", payload)
            elif kind == "nav":
                self._fill_nav()
            elif kind == "collects":
                self._fill_collects()
            elif kind == "cardLocal":
                self._apply_locals(payload)
            elif kind == "restore":
                self._restore_state()

    def _apply_locals(self, updates):
        if updates and isinstance(updates[0], str):
            updates = [updates]
        buckets = {}
        for item in updates:
            if len(item) < 3:
                continue
            buckets.setdefault(item[2], []).append(item)
        for target, batch in buckets.items():
            if target in ("card", "nav", "collect"):
                self._paint_local(self.cards, "cover", batch)
                self._paint_local(self.nav, "cover", batch)
            if target == "songrow":
                self._paint_local(self.songs, "cover", batch)
            if target == "collect":
                self._paint_local(self.collects, "cover", batch)
            if target == "album":
                self._paint_local(self.albums, "cover", batch)
            if target == "event":
                self._paint_local(self.events, "cover", batch)
            if target == "comment":
                self._paint_local(self.comments, "avatar", batch)
            if target == "detail" and batch:
                self._detail_cover = batch[-1][1]
                self.detailChanged.emit("cover\n" + self._detail_cover)

    def _paint_local(self, model, field, batch):
        found = {}
        for url, path, _target in batch:
            found[url] = path
        updates = []
        for index, row in enumerate(model._rows):
            path = found.get(row.get(field))
            if path and row.get("local") != path:
                updates.append((index, "local", path))
        if updates:
            model.set_fields(updates)

    # --- 窗口和账号 ---

    def _fill_nav(self):
        blank = {"cover": "", "local": "", "owned": False}
        rows = [
            {"key": "home", "label": "推荐", "kind": "home", "section": "", **blank},
            {"key": "discover", "label": "热门歌单", "kind": "discover", "section": "", **blank},
        ]
        rows.extend(
            {"key": str(cid), "label": name, "kind": "chart", "section": "", "owned": False, **blank}
            for cid, name in api.CHARTS[:4]
        )
        if self._profile:
            rows.append({"key": "", "label": self._profile.get("vip") or "我的", "kind": "section", "section": "mine", **blank})
            rows.extend((
                {"key": "liked", "label": "我喜欢的音乐", "kind": "liked", "section": "", **blank},
                {"key": "daily", "label": "每日推荐", "kind": "daily", "section": "", **blank},
                {"key": "fm", "label": "私人 FM", "kind": "fm", "section": "", **blank},
                {"key": "record", "label": "听歌排行", "kind": "record", "section": "", **blank},
                {"key": "downloads", "label": "下载管理", "kind": "downloads", "section": "", **blank},
                {"key": "refresh", "label": "刷新收藏", "kind": "refresh", "section": "", **blank},
            ))
            uid = str(self._profile.get("userId") or "")
            created = [item for item in self._mine if str(item.get("creator") or "") == uid and item.get("special") != 5]
            collected = [item for item in self._mine if str(item.get("creator") or "") != uid]
            created = self._sort_recent(created)[:20]
            collected = self._sort_recent(collected)[:30]
            if created:
                rows.append({"key": "", "label": "创建的歌单", "kind": "section", "section": "created", **blank})
                rows.extend(self._playlist_nav(created[:20]))
            if collected:
                rows.append({"key": "", "label": "收藏的歌单", "kind": "section", "section": "collected", **blank})
                rows.extend(self._playlist_nav(collected[:30]))
        self.nav.replace(rows)
        self._queue_covers((item.get("cover") for item in rows), 28, "nav")

    def _recent_map(self):
        try:
            payload = json.loads(open(RECENT_PATH, encoding="utf-8").read())
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _sort_recent(self, items):
        recent = self._recent_map()

        def key(item):
            stamp = recent.get(str(item.get("id"))) or 0
            return (1 if stamp else 0, stamp, item.get("added") or 0)

        return sorted(items, key=key, reverse=True)

    def _touch_playlist(self, playlist_id):
        if not playlist_id:
            return
        recent = self._recent_map()
        recent[str(playlist_id)] = int(time.time())
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = RECENT_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(recent, handle)
            os.replace(tmp, RECENT_PATH)
        except OSError:
            return

    def _created_playlists(self):
        uid = str((self._profile or {}).get("userId") or "")
        if not uid:
            return []
        return [
            item for item in self._mine
            if str(item.get("creator") or "") == uid and item.get("special") != 5 and item.get("id")
        ]

    @pyqtSlot(result=str)
    def createdPlaylists(self):
        return "\n".join(
            f"{item.get('id')}|{item.get('name') or '歌单'}" for item in self._created_playlists()
        )

    @pyqtSlot()
    def openCollect(self):
        if not self._require_login("收藏到歌单"):
            return
        self._fill_collects()

    def _fill_collects(self):
        rows = [{"itemId": "", "name": "创建新歌单", "cover": "", "local": "", "count": 0, "kind": "create"}]
        liked = next((item for item in self._mine if item.get("special") == 5 or "喜欢的音乐" in (item.get("name") or "")), None)
        if liked:
            rows.append(self._collect_row(liked, "liked"))
        rows.extend(self._collect_row(item, "playlist") for item in self._created_playlists())
        self.collects.replace(rows)
        for item in rows:
            if item.get("cover"):
                threading.Thread(target=self._cache_cover, args=(item["cover"], 40, "collect"), daemon=True).start()

    def _collect_row(self, item, kind):
        return {
            "itemId": str(item.get("id") or ""),
            "name": item.get("name") or "歌单",
            "cover": item.get("cover") or "",
            "local": "",
            "count": int(item.get("count") or 0),
            "kind": kind,
        }

    @pyqtSlot(str, str)
    def createPlaylistAndCollect(self, name, selected_ids=""):
        if not self._require_login("创建歌单"):
            return
        if self._page not in ("playlist", "album"):
            return
        all_songs, ids = self._parse_batch_selection(selected_ids)
        if not all_songs and not ids:
            self.statusChanged.emit("请先选择歌曲")
            return
        revision = self._navigation_revision
        token = self._list_token
        page = self._page
        source_id = str(self._list_id or "")
        rows = [dict(song) for song in self.songs._rows]
        threading.Thread(
            target=self._create_playlist_and_collect,
            args=(name, revision, token, page, source_id, rows, all_songs, ids),
            daemon=True,
        ).start()

    def _create_playlist_and_collect(self, name, revision, token, page, source_id, rows, all_songs, ids):
        try:
            songs = [
                song for song in self._resolve_batch_songs(page, source_id, rows, all_songs, ids)
                if song.get("playable") is not False
            ]
            if not songs:
                self._post("status", "没有可加入歌单的歌曲")
                return
            title = (name or "").strip()
            if not title:
                self._post("status", "歌单名称不能为空")
                return
            playlist_id = api.create_playlist(title, self._cookie)
            song_ids = [song["songId"] for song in songs]
            api.manipulate_playlist_tracks(playlist_id, song_ids, "add", self._cookie)
            uid = (self._profile or {}).get("userId")
            if uid:
                self._mine = api.user_playlists(uid, self._cookie)
            self._post("nav", None)
            self._post("status", f"已创建歌单并加入 {len(song_ids)} 首")
        except api.ApiError as exc:
            self._post("status", str(exc))

    @pyqtSlot(str)
    def createAndCollect(self, name):
        song = self._song
        name = (name or "").strip()
        if not song or not song.get("songId"):
            self.statusChanged.emit("还没有正在播放的歌曲")
            return
        if not name:
            self.statusChanged.emit("歌单名称不能为空")
            return
        if not self._require_login("创建歌单"):
            return
        threading.Thread(target=self._create_and_collect, args=(song, name[:40]), daemon=True).start()

    def _create_and_collect(self, song, name):
        try:
            playlist_id = api.create_playlist(name, self._cookie)
            api.add_playlist_track(playlist_id, song["songId"], self._cookie)
            uid = (self._profile or {}).get("userId")
            self._mine = api.user_playlists(uid, self._cookie) if uid else self._mine
        except api.ApiError as exc:
            self._post("status", str(exc))
            return
        self._post("nav", None)
        self._post("status", f"已创建并加入「{name}」")

    @pyqtSlot()
    def refreshLibrary(self):
        if not self._require_login("刷新收藏"):
            return
        self.statusChanged.emit("正在从云端刷新收藏…")
        threading.Thread(target=self._refresh_library, daemon=True).start()

    def _refresh_library(self):
        try:
            self._liked = {str(item) for item in api.liked_ids(self._cookie)}
            uid = (self._profile or {}).get("userId")
            self._mine = api.user_playlists(uid, self._cookie) if uid else []
        except api.ApiError as exc:
            self._post("status", str(exc))
            return
        self._post("nav", None)
        self._post("collects", None)
        self._post("status", "收藏已刷新")

    @pyqtSlot(str, result=bool)
    def songLiked(self, song_id):
        return str(song_id or "") in self._liked

    @pyqtSlot(result=bool)
    def canRemoveCurrent(self):
        playlist_id = str(self._list_id or "")
        if not playlist_id:
            return False
        return any(str(item.get("id")) == playlist_id for item in self._created_playlists())

    @pyqtSlot(int, str)
    def collectQueue(self, row, playlist_id):
        if row < 0 or row >= len(self._queue):
            return
        song = self._queue[row]
        if not song or not song.get("songId"):
            return
        if not self._require_login("收藏到歌单"):
            return
        threading.Thread(target=self._collect, args=(song, playlist_id), daemon=True).start()

    @pyqtSlot(int)
    def toggleQueueLike(self, row):
        if row < 0 or row >= len(self._queue):
            return
        song = self._queue[row]
        if not song or not song.get("songId"):
            return
        if not self._cookie:
            self.statusChanged.emit("请先登录再收藏")
            return
        like = str(song["songId"]) not in self._liked
        threading.Thread(target=self._like, args=(song, like), daemon=True).start()

    @pyqtSlot(int)
    def playNextQueue(self, row):
        if row < 0 or row >= len(self._queue):
            return
        song = self._queue[row]
        if not song or not song.get("songId") or row == self._index + 1:
            return
        if self._refuse_unplayable(song):
            return
        self._queue.pop(row)
        if row < self._index:
            self._index -= 1
        insert_at = min(len(self._queue), self._index + 1)
        self._queue.insert(insert_at, song)
        self.queue.replace(self._queue)
        self.statusChanged.emit(f"下一首播放 {song.get('name') or ''}")

    @pyqtSlot(int, str)
    def collectTo(self, row, playlist_id):
        song = self._song if row < 0 else self.songs.get(row)
        if not song or not song.get("songId"):
            return
        if not self._require_login("收藏到歌单"):
            return
        threading.Thread(
            target=self._collect, args=(song, playlist_id), daemon=True,
        ).start()

    def _collect(self, song, playlist_id):
        try:
            api.add_playlist_track(playlist_id, song["songId"], self._cookie)
        except api.ApiError as exc:
            self._post("status", str(exc))
            return
        self._post("status", f"已收藏到歌单：{song.get('name') or ''}")

    @pyqtSlot(int)
    def removeFromPlaylist(self, row):
        song = self.songs.get(row)
        playlist_id = self._list_id
        if not song or not song.get("songId") or not playlist_id:
            return
        if not self._require_login("从当前歌单移除"):
            return
        if not any(str(item.get("id")) == str(playlist_id) for item in self._created_playlists()):
            self.statusChanged.emit("只能从自己创建的歌单移除")
            return
        threading.Thread(target=self._remove_track, args=(song, playlist_id, row), daemon=True).start()

    def _remove_track(self, song, playlist_id, row):
        try:
            api.remove_playlist_track(playlist_id, song["songId"], self._cookie)
        except api.ApiError as exc:
            self._post("status", str(exc))
            return
        if str(self._list_id) == str(playlist_id) and 0 <= row < len(self.songs._rows):
            self._post("dropSong", (row, self._list_token, f"已从当前歌单移除 {song.get('name') or ''}"))
        else:
            self._post("status", f"已从当前歌单移除 {song.get('name') or ''}")

    @pyqtSlot(int)
    def removeFromQueue(self, row):
        if not (0 <= row < len(self._queue)):
            return
        was_current = row == self._index
        song = self._queue.pop(row)
        if row < self._index:
            self._index -= 1
        elif was_current:
            self._index = min(row, len(self._queue) - 1)
        self.queue.remove_at(row)
        self.statusChanged.emit(f"已从播放列表移除 {song.get('name') or ''}")
        if was_current:
            if self._queue:
                self._play_index(self._index)
            else:
                self._index = -1
                self._song = None
                self.player.stop()
                self.currentSongChanged.emit("")

    def _playlist_nav(self, items):
        uid = str((self._profile or {}).get("userId") or "")
        return [
            {
                "key": str(item.get("id") or ""),
                "label": item.get("name") or "歌单",
                "kind": "playlist",
                "section": "",
                "cover": item.get("cover") or "",
                "local": "",
                "owned": bool(uid) and str(item.get("creator") or "") == uid and item.get("special") != 5,
            }
            for item in items
        ]

    def _boot(self):
        try:
            self._cookie = api.load_cookie(COOKIE_PATH)
        except OSError:
            self._cookie = ""
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            os.chmod(DATA_DIR, 0o700)
        except OSError:
            pass
        if not self._cookie:
            self._post("account", "登录")
            threading.Thread(target=self._load_home, daemon=True).start()
            return
        threading.Thread(target=self._load_account, daemon=True).start()
        threading.Thread(target=self._load_home, daemon=True).start()

    def _load_account(self):
        try:
            self._profile = api.user_account(self._cookie)
            self._post("account", self._account_label(self._profile))
        except api.ApiError as exc:
            self._post("account", "登录")
            self._post("status", str(exc))
            return
        try:
            self._liked = {str(item) for item in api.liked_ids(self._cookie)}
            if self._song and str(self._song.get("songId")) in self._liked:
                self.likedChanged.emit(True)
        except api.ApiError:
            pass
        try:
            uid = self._profile.get("userId")
            self._mine = api.user_playlists(uid, self._cookie) if uid else []
            self._post("nav", None)
            self._post("collects", None)
        except api.ApiError:
            pass

    @staticmethod
    def _account_label(profile):
        name = profile.get("nickname") or "已登录"
        vip = profile.get("vip") or ""
        return name + (f" · {vip}" if vip else "")

    @pyqtSlot(str)
    def openNav(self, key):
        row = next((item for item in self.nav._rows if item["key"] == key), None)
        if not row:
            return
        kind = row["kind"]
        if kind == "home":
            self.openHome()
        elif kind in ("chart", "playlist"):
            self.openPlaylist(key, row["label"])
        elif kind == "discover":
            self.openDiscover()
        elif kind == "refresh":
            self.refreshLibrary()
        elif kind == "section":
            return
        elif kind == "liked":
            self.openLiked()
        elif kind == "daily":
            self.openDaily()
        elif kind == "record":
            self.openRecord()
        elif kind == "downloads":
            self.openDownloads()
        elif kind == "fm":
            self.openFm()

    def _capture(self):
        return {
            "page": self._page,
            "title": self._page_title,
            "album_id": self._album_id,
            "playlist_meta": dict(getattr(self, "_playlist_meta", {}) or {}),
            "songs": [dict(row) for row in self.songs._rows],
            "albums": [dict(row) for row in self.albums._rows],
            "detail": self._detail_text,
            "cover": self._detail_cover,
            "list_id": self._list_id,
            "list_total": self._list_total,
            "list_offset": self._list_offset,
            "list_title": self._list_title,
            "list_refs": self._list_refs,
        }

    # --- 页面和歌单 ---

    def _show(self, name, title, identity=""):
        current_identity = self._album_id if self._page == "album" else self._list_id if self._page == "playlist" else ""
        changed = (self._page, getattr(self, "_page_title", "")) != (name, title)
        if identity and name in ("playlist", "album"):
            changed = changed or current_identity != str(identity)
        if changed:
            self._history.append(self._capture())
            self._history = self._history[-8:]
            self._list_token += 1
            self._list_more = False
        self._navigation_revision += 1
        self._write_window("bridgeNavigation", f"{self._navigation_revision}:{name}")
        self._user_token = getattr(self, "_user_token", 0) + 1
        self._page = name
        self._page_title = title
        if name == "album":
            self._album_id = str(identity or "")
        else:
            self._album_id = ""
        if name == "playlist":
            self._list_id = str(identity or "")
        else:
            self._playlist_meta = {}
            self.playlistMetaChanged.emit("0|0|0||")
        # 新页的数据还在路上。先把上一页的封面和简介清掉，避免慢加载时看起来像打开了旧内容。
        if name in ("playlist", "album", "artist", "user"):
            self._detail_text = "\n".join((title, "", ""))
            self._detail_cover = ""
            self.detailChanged.emit(self._detail_text)
            self.detailChanged.emit("cover\n")
            if name == "user":
                self.cards.replace([])
        self.pageChanged.emit(name, title)
        LOG.info("open page=%s title=%s", name, title)

    def _restore_frame(self, frame):
        self._list_token += 1
        self._list_more = False
        self._page = frame.get("page") or "home"
        self._page_title = frame.get("title") or "推荐"
        self._album_id = str(frame.get("album_id") or "")
        self._playlist_meta = dict(frame.get("playlist_meta") or {})
        self._navigation_revision += 1
        self._write_window("bridgeNavigation", f"{self._navigation_revision}:{self._page}")
        self._list_id = frame.get("list_id") or ""
        self._list_total = int(frame.get("list_total") or 0)
        self._list_offset = int(frame.get("list_offset") or 0)
        self._list_title = frame.get("list_title") or ""
        self._list_refs = frame.get("list_refs")
        self._detail_text = frame.get("detail") or ""
        self._detail_cover = frame.get("cover") or ""
        self.songs.replace(frame.get("songs") or [])
        self.listCountChanged.emit(self._list_total)
        self.albums.replace(frame.get("albums") or [])
        self.detailChanged.emit(self._detail_text or "\n")
        if self._detail_cover:
            self.detailChanged.emit("cover\n" + self._detail_cover)
        self.playlistMetaChanged.emit("|".join((
            "1" if self._playlist_meta.get("owned") else "0",
            "1" if self._playlist_meta.get("collected") else "0",
            str(self._playlist_meta.get("special") or 0),
            str(self._playlist_meta.get("creator") or ""),
            str(self._playlist_meta.get("creatorName") or "").replace("|", " "),
        )))
        self.pageChanged.emit(self._page, self._page_title)

    @pyqtSlot()
    def goBack(self):
        if not self._history:
            self.openHome()
            return
        self._restore_frame(self._history.pop())

    @pyqtSlot()
    def openHome(self):
        self._history = []
        self._list_token += 1
        self._list_more = False
        self._user_token = getattr(self, "_user_token", 0) + 1
        self._navigation_revision += 1
        self._write_window("bridgeNavigation", f"{self._navigation_revision}:home")
        self._page = "home"
        self._page_title = "推荐"
        self._album_id = ""
        self._list_id = ""
        self._playlist_meta = {}
        self.playlistMetaChanged.emit("0|0|0||")
        self.listCountChanged.emit(0)
        self.pageChanged.emit("home", "推荐")
        threading.Thread(target=self._load_home, daemon=True).start()

    def _load_home(self):
        try:
            playlists = api.top_playlist(limit=12, cookie=self._cookie)
        except api.ApiError as exc:
            self.statusChanged.emit(str(exc))
            return
        covers = self._chart_covers([cid for cid, _name in api.CHARTS[:5]])
        rows = []
        for cid, name in api.CHARTS[:5]:
            rows.append({
                "itemId": str(cid),
                "name": name,
                "cover": covers.get(str(cid), ""),
                "local": "",
                "count": 0,
                "kind": "chart",
                "creator": "",
                "creatorId": "",
            })
        for item in playlists:
            rows.append({
                "itemId": str(item.get("id") or ""),
                "name": item.get("name") or "歌单",
                "cover": item.get("cover") or "",
                "local": "",
                "count": int(item.get("count") or 0),
                "kind": "playlist",
                "creator": item.get("creatorName") or "",
                "creatorId": str(item.get("creator") or ""),
            })
        self._post("cards", (rows, "推荐已更新"))
        self._queue_covers((item.get("cover") for item in rows), 148, "card")

    def _chart_covers(self, playlist_ids):
        # 批量 ids 只会带回第一张封面。和 GTK 一样，每个榜单独取。
        found = {}
        for playlist_id in playlist_ids:
            try:
                payload = api.request(
                    "/api/v6/playlist/detail", {"id": int(playlist_id), "n": 0}, cookie=self._cookie,
                )
            except (api.ApiError, ValueError, TypeError):
                continue
            item = payload.get("playlist") or {}
            found[str(playlist_id)] = item.get("coverImgUrl") or ""
        return found

    @pyqtSlot(object, str)
    def _apply_cards(self, rows, status):
        self.cards.replace(rows)
        self.statusChanged.emit(status)

    @pyqtSlot(str, str)
    def openPlaylist(self, playlist_id, name):
        playlist_id = str(playlist_id or "").strip()
        if not playlist_id:
            return
        # 先记下旧页，再换新的列表编号。反过来会把旧页的编号清掉，新请求也会被丢掉。
        self._show("playlist", name or "歌单", playlist_id)
        token = self._begin_list()
        self._list_id = playlist_id
        self._playlist_meta = {}
        self.playlistMetaChanged.emit("0|0|0||")
        self.songs.replace([])
        self.listCountChanged.emit(0)
        threading.Thread(target=self._load_playlist, args=(playlist_id, name, token), daemon=True).start()

    def _load_playlist(self, playlist_id, name, token):
        self._touch_playlist(playlist_id)
        self._post("status", "正在加载歌单…")
        try:
            page = api.playlist_page(playlist_id, cookie=self._cookie, limit=40, offset=0)
        except api.ApiError as exc:
            if token == self._list_token:
                self._post("status", str(exc))
            return
        if token != self._list_token:
            return
        songs = page.get("songs") or []
        total = page.get("total") or len(songs)
        title = name or page.get("name") or "歌单"
        creator = page.get("creatorName") or ""
        desc = (page.get("description") or "").strip().replace("\n", " ")
        if len(desc) > 160:
            desc = desc[:160] + "…"
        mine = self._playlist_relation(page.get("id") or playlist_id, page.get("creator"))
        sub = " · ".join(item for item in (creator, f"{total} 首") if item)
        self._post("detailPage", (token, (
            "playlist",
            title,
            sub,
            desc,
            page.get("cover") or "",
        )))
        meta = {
            "id": str(page.get("id") or playlist_id),
            "owned": mine == "owned",
            "collected": mine == "collected" or bool(page.get("subscribed")),
            "special": int(page.get("special") or 0),
            "creator": str(page.get("creator") or ""),
            "creatorName": creator,
        }
        self._post("playlistMeta", (token, meta))
        self._post("listCount", (token, total))
        rows = self._song_rows(songs)
        shown = len(songs)
        self._post("songs", (
            rows, False, token, shown,
            f"{title} · {shown}/{total} 首" if total > shown else f"{title} · {total} 首",
            total, title, page.get("refs") or [],
        ))
        self._cache_song_covers(rows)

    def _playlist_relation(self, playlist_id, creator):
        """owned 是自己创建的，collected 是收藏来的。我喜欢不算可删除的自建歌单。"""
        uid = str((self._profile or {}).get("userId") or "")
        found = next((item for item in self._mine if str(item.get("id")) == str(playlist_id)), None)
        owner = str((found or {}).get("creator") or creator or "")
        special = int((found or {}).get("special") or 0)
        if uid and owner == uid and special != 5:
            return "owned"
        if found and owner != uid:
            return "collected"
        return ""

    @pyqtSlot()
    def moreSongs(self):
        if self._list_more or self._list_offset >= self._list_total or not self._list_id:
            return
        token = self._list_token
        playlist_id = self._list_id
        title = self._list_title
        offset = self._list_offset
        total = self._list_total
        refs = self._list_refs
        self._list_more = True
        threading.Thread(
            target=self._continue_playlist,
            args=(token, playlist_id, title, offset, total, refs),
            daemon=True,
        ).start()

    def _continue_playlist(self, token, playlist_id, title, offset, total, refs):
        try:
            nxt = api.playlist_page(
                playlist_id, cookie=self._cookie, limit=40, offset=offset, refs=refs,
            )
        except api.ApiError as exc:
            if token == self._list_token:
                self._list_more = False
                self._post("status", str(exc))
            return
        if token != self._list_token or not nxt.get("songs"):
            if token == self._list_token:
                self._list_more = False
            return
        rows = self._song_rows(nxt["songs"])
        shown = offset + len(nxt["songs"])
        self._post("songs", (rows, True, token, shown, f"{title} · {shown}/{total} 首", total, title))
        self._cache_song_covers(rows)

    def _begin_list(self):
        self._list_token += 1
        self._list_id = ""
        self._list_total = 0
        self._list_offset = 0
        self._list_title = ""
        self._list_more = False
        self._list_refs = None
        return self._list_token

    def _post_songs(self, rows, status, total, title="", append=False, token=None, refs=None):
        self._post("songs", (
            rows, append, self._list_token if token is None else token,
            len(rows) if not append else self._list_offset + len(rows),
            status, total, title, refs,
        ))

    @pyqtSlot(object, bool, int, int, str, int, str, object)
    def _apply_songs(self, rows, append, token, shown, status, total, title, refs=None):
        if token != self._list_token:
            return
        self._list_total = total
        self._list_offset = shown
        self._list_title = title
        if refs is not None:
            self._list_refs = refs
        self._list_more = False
        if append:
            self.songs.append(rows)
        else:
            self.songs.replace(rows)
        self.listCountChanged.emit(self._list_total)
        self._mark_downloaded()
        self.statusChanged.emit(status)

    def _drop_song_row(self, row, token, status):
        """只删这一行。整表替换会把列表滚回第一行。"""
        if token != self._list_token or not (0 <= row < len(self.songs._rows)):
            return
        self.songs.remove_at(row)
        self._list_total = max(0, self._list_total - 1)
        self._list_offset = max(0, self._list_offset - 1)
        self.listCountChanged.emit(self._list_total)
        self.statusChanged.emit(status)

    def _drop_songs(self, song_ids, token, status):
        """按歌曲编号增量移除成功项，保留列表滚动位置和分页游标。"""
        if token != self._list_token or not song_ids:
            return
        wanted = {str(song_id) for song_id in song_ids}
        rows = [i for i, song in enumerate(self.songs._rows) if str(song.get("songId") or "") in wanted]
        loaded_removed = len(rows)
        for row in reversed(rows):
            self.songs.remove_at(row)
        if self._list_refs:
            before = self._list_refs[:self._list_offset]
            removed_before = sum(1 for ref in before if str(ref.get("id") or "") in wanted)
            self._list_refs = [ref for ref in self._list_refs if str(ref.get("id") or "") not in wanted]
            self._list_total = len(self._list_refs)
            self._list_offset = max(0, self._list_offset - removed_before)
        else:
            self._list_total = max(0, self._list_total - len(wanted))
            self._list_offset = max(0, self._list_offset - loaded_removed)
        self.listCountChanged.emit(self._list_total)
        self.statusChanged.emit(status)

    def _cache_song_covers(self, rows):
        self._queue_covers((row.get("cover") for row in rows), 36, "songrow")

    def _queue_covers(self, urls, size, kind):
        pending = [url for url in urls if url]
        if not pending:
            return
        workers = 2 if len(pending) > 12 else 1

        def run(chunk):
            ready = []
            for url in chunk:
                path = self._cache_cover(url, size, kind, post=False)
                if path:
                    ready.append((url, path, kind))
                if len(ready) >= 8:
                    self._post("cardLocal", ready)
                    ready = []
            if ready:
                self._post("cardLocal", ready)

        step = max(1, (len(pending) + workers - 1) // workers)
        for start in range(0, len(pending), step):
            threading.Thread(target=run, args=(pending[start:start + step],), daemon=True).start()

    def _require_login(self, action):
        if self._cookie:
            return True
        self.statusChanged.emit(f"{action}需要先登录")
        return False

    @pyqtSlot()
    def openLiked(self):
        if not self._require_login("我喜欢的音乐"):
            return
        self._show("list", "我喜欢的音乐")
        token = self._begin_list()
        self.songs.replace([])
        threading.Thread(target=self._load_liked, args=(token,), daemon=True).start()

    def _load_liked(self, token):
        try:
            songs = api.liked_songs(self._cookie)
        except api.ApiError as exc:
            if token == self._list_token:
                self._post("status", str(exc))
            return
        if token != self._list_token:
            return
        rows = self._song_rows(songs)
        self._post_songs(rows, f"我喜欢的音乐 · {len(rows)} 首", len(rows), "我喜欢的音乐", token=token)
        self._cache_song_covers(rows)

    @pyqtSlot()
    def openDaily(self):
        if not self._require_login("每日推荐"):
            return
        self._show("list", "每日推荐")
        token = self._begin_list()
        self.songs.replace([])
        threading.Thread(target=self._load_daily, args=(token,), daemon=True).start()

    def _load_daily(self, token):
        try:
            songs = api.recommend_songs(self._cookie)
        except api.ApiError as exc:
            if token == self._list_token:
                self._post("status", str(exc))
            return
        if token != self._list_token:
            return
        rows = self._song_rows(songs)
        self._post_songs(rows, f"每日推荐 · {len(rows)} 首", len(rows), "每日推荐", token=token)
        self._cache_song_covers(rows)

    @pyqtSlot()
    def openRecord(self):
        if not self._require_login("听歌排行") or not (self._profile or {}).get("userId"):
            if self._cookie and not (self._profile or {}).get("userId"):
                self.statusChanged.emit("听歌排行需要先登录")
            return
        self._show("list", "听歌排行 · 最近一周")
        token = self._begin_list()
        self.songs.replace([])
        threading.Thread(target=self._load_record, args=(token,), daemon=True).start()

    def _load_record(self, token):
        try:
            songs = api.play_record(self._profile["userId"], self._cookie, weekly=True)
        except api.ApiError as exc:
            if token == self._list_token:
                self._post("status", str(exc))
            return
        if token != self._list_token:
            return
        rows = self._song_rows(songs)
        self._post_songs(rows, f"最近一周播放 {len(rows)} 首", len(rows), "听歌排行", token=token)
        self._cache_song_covers(rows)

    @pyqtSlot()
    def openFm(self):
        if not self._require_login("私人 FM"):
            return
        self._show("list", "私人FM")
        token = self._begin_list()
        self.songs.replace([])
        threading.Thread(target=self._load_fm, args=(token,), daemon=True).start()

    def _load_fm(self, token):
        try:
            songs = api.personal_fm(self._cookie)
        except api.ApiError as exc:
            if token == self._list_token:
                self._post("status", str(exc))
            return
        if token != self._list_token:
            return
        rows = self._song_rows(songs)
        self._post_songs(rows, f"私人 FM {len(rows)} 首，播完自动换一批", len(rows), "私人FM", token=token)
        self._cache_song_covers(rows)
        if rows:
            self._queue = rows
            self.queue.replace(rows)
            self._mode = "order"
            self.modeChanged.emit(MODE_LABEL[self._mode])
            self._play_index(0)

    @pyqtSlot()
    def openDownloads(self):
        self._show("downloads", "下载管理")
        self._post("downloads", self._download_view())

    @pyqtSlot(result=str)
    def downloadFolder(self):
        return self._music_folder()

    @pyqtSlot()
    def openDownloadFolder(self):
        folder = self.downloadFolder()
        try:
            os.makedirs(folder, exist_ok=True)
            subprocess.Popen(["xdg-open", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.statusChanged.emit("打不开下载目录")

    @pyqtSlot(str)
    def suggest(self, keyword):
        text = (keyword or "").strip()
        self._suggest_token = getattr(self, "_suggest_token", 0) + 1
        token = self._suggest_token
        if not text:
            self.suggestChanged.emit("")
            return
        threading.Thread(target=self._suggest, args=(text, token), daemon=True).start()

    def _suggest(self, keyword, token):
        try:
            songs = api.search_suggest(keyword, cookie=self._cookie, limit=8)
        except api.ApiError:
            songs = []
        if token != getattr(self, "_suggest_token", 0):
            return
        lines = []
        for song in songs:
            lines.append("\t".join((
                str(song.get("id") or ""),
                song.get("name") or "",
                song.get("artist") or "",
                str(song.get("artistId") or ""),
            )))
        self._post("suggest", "\n".join(lines))

    @pyqtSlot(str, str, str)
    def playSuggestion(self, song_id, name, artist):
        song_id = str(song_id or "").strip()
        if not song_id:
            return
        self.suggestChanged.emit("")
        song = {
            "songId": song_id,
            "name": name or "未命名",
            "artist": artist or "",
            "artistId": "",
            "artists": "",
            "album": "",
            "albumId": "",
            "cover": "",
            "local": "",
            "duration": 0,
            "vip": False,
            "playable": True,
        }
        self._suggest_play = song_id
        self._remember_search(name or song_id)
        self.search(name or song_id)

    def _load_search_history(self):
        try:
            payload = json.loads(open(SEARCH_HISTORY_PATH, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            return []
        rows = []
        for item in payload if isinstance(payload, list) else []:
            text = str(item or "").strip()
            if text and text not in rows:
                rows.append(text[:40])
        return rows[:10]

    def _remember_search(self, keyword):
        text = (keyword or "").strip()[:40]
        if not text:
            return
        rows = [item for item in self._load_search_history() if item != text]
        rows.insert(0, text)
        rows = rows[:10]
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            os.chmod(DATA_DIR, 0o700)
            tmp = SEARCH_HISTORY_PATH + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(rows, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, SEARCH_HISTORY_PATH)
            os.chmod(SEARCH_HISTORY_PATH, 0o600)
        except OSError:
            return
        self._post("history", "\n".join(rows))

    @pyqtSlot()
    def clearSearchHistory(self):
        try:
            os.remove(SEARCH_HISTORY_PATH)
        except OSError:
            pass
        self.historyChanged.emit("")

    @pyqtSlot(str)
    def search(self, keyword):
        text = (keyword or "").strip()
        if not text:
            return
        self._remember_search(text)
        self._show("list", f"搜索「{text}」")
        token = self._begin_list()
        self._search_keyword = text
        self.songs.replace([])
        threading.Thread(target=self._search, args=(text, token), daemon=True).start()

    @pyqtSlot(str)
    def searchTab(self, tab):
        """搜索结果里切换单曲和歌单。歌单只在点开时才请求。"""
        keyword = getattr(self, "_search_keyword", "")
        if not keyword or tab not in ("songs", "playlists"):
            return
        if tab == "songs":
            self._show("list", f"搜索「{keyword}」")
            token = self._begin_list()
            self.songs.replace([])
            threading.Thread(target=self._search, args=(keyword, token), daemon=True).start()
            return
        self._show("discover", f"歌单「{keyword}」")
        # 换一个列表记号，晚到的单曲结果就不会画到歌单页上。
        token = self._begin_list()
        self.cards.replace([])
        threading.Thread(target=self._search_playlists, args=(keyword, token), daemon=True).start()

    def _search_playlists(self, keyword, token):
        try:
            playlists = api.search_playlists(keyword, cookie=self._cookie)
        except api.ApiError as exc:
            if token == self._list_token:
                self._post("status", str(exc))
            return
        if token != self._list_token:
            return
        rows = [
            {
                "itemId": str(item.get("id") or ""),
                "name": item.get("name") or "歌单",
                "cover": item.get("cover") or "",
                "local": "",
                "count": int(item.get("count") or 0),
                "kind": "playlist",
                "creator": item.get("creatorName") or "",
                "creatorId": str(item.get("creator") or ""),
            }
            for item in playlists
        ]
        self._post("cards", (rows, f"找到 {len(rows)} 个歌单"))
        self._queue_covers((item.get("cover") for item in playlists), 120, "card")

    @pyqtSlot()
    def openDiscover(self):
        self._show("discover", "热门歌单")
        token = self._begin_list()
        self.songs.replace([])
        threading.Thread(target=self._load_discover, args=(token,), daemon=True).start()

    def _load_discover(self, token):
        try:
            playlists = api.top_playlist(limit=40, cookie=self._cookie)
        except api.ApiError as exc:
            if token == self._list_token:
                self._post("status", str(exc))
            return
        if token != self._list_token:
            return
        self._post_songs([], f"热门歌单 {len(playlists)} 个", 0, "热门歌单", token=token)
        self._post("cards", ([
            {
                "itemId": str(item.get("id") or ""),
                "name": item.get("name") or "歌单",
                "cover": item.get("cover") or "",
                "local": "",
                "count": int(item.get("count") or 0),
                "kind": "playlist",
                "creator": item.get("creatorName") or "",
                "creatorId": str(item.get("creator") or ""),
            }
            for item in playlists
        ], f"热门歌单 {len(playlists)} 个"))
        self._queue_covers((item.get("cover") for item in playlists), 120, "card")

    def _search(self, keyword, token):
        try:
            songs = api.search_songs(keyword, cookie=self._cookie)
        except api.ApiError as exc:
            if token == self._list_token:
                self.statusChanged.emit(str(exc))
            return
        if token != self._list_token:
            return
        rows = self._song_rows(songs)
        self._post_songs(rows, f"找到 {len(songs)} 首", len(songs), "搜索", token=token)
        self._cache_song_covers(rows)
        wanted = getattr(self, "_suggest_play", "")
        self._suggest_play = ""
        if wanted and token == self._list_token:
            index = next((i for i, row in enumerate(rows) if row.get("songId") == wanted), -1)
            if index >= 0:
                self._queue = [dict(item) for item in rows if item.get("songId")]
                self._queue_source = ""
                self._queue_title = "搜索"
                self.queue.replace(self._queue)
                self._play_index(index)

    @pyqtSlot(str, str)
    def openArtist(self, artist_id, name):
        artist_id = str(artist_id or "").strip()
        if not artist_id or artist_id in ("0", "None"):
            self.statusChanged.emit(f"{name or '这个歌手'} 没有可打开的主页")
            return
        self._artist_id = artist_id
        self._artist_desc_loaded = False
        # 点开歌手先看热门歌曲。主页、专辑和博客在分页里再取。
        self._artist_tab = "songs"
        self.artistTabChanged.emit("songs")
        self._show("artist", name or "歌手")
        token = self._begin_list()
        self.songs.replace([])
        self.albums.replace([])
        self.events.replace([])
        threading.Thread(target=self._load_artist, args=(artist_id, token), daemon=True).start()

    @pyqtSlot(str)
    def setArtistTab(self, tab):
        tab = tab if tab in ("home", "songs", "albums", "blog") else "songs"
        if tab == self._artist_tab and self._page == "artist":
            return
        self._artist_tab = tab
        self.artistTabChanged.emit(tab)
        artist_id = self._artist_id
        if not artist_id or self._page != "artist":
            return
        if tab == "home" and not self._artist_desc_loaded:
            threading.Thread(target=self._load_artist_profile, args=(artist_id, self._list_token), daemon=True).start()
        elif tab == "albums" and not self.albums._rows:
            threading.Thread(target=self._load_artist_albums, args=(artist_id, self._list_token), daemon=True).start()
        elif tab == "blog" and not self._artist_desc_loaded:
            threading.Thread(target=self._load_artist_profile, args=(artist_id, self._list_token), daemon=True).start()

    def _load_artist(self, artist_id, token):
        try:
            data = api.artist_home(artist_id, cookie=self._cookie)
        except api.ApiError as exc:
            if token == self._list_token:
                self.statusChanged.emit(str(exc))
            return
        if token != self._list_token:
            return
        brief = (data.get("brief") or data.get("desc") or "").strip()
        if len(brief) > 220:
            brief = brief[:220] + "…"
        counts = f"歌曲 {data.get('musicCount') or 0} · 专辑 {data.get('albumCount') or 0}"
        self._post("detail", (
            "artist",
            data.get("name") or "歌手",
            " · ".join(item for item in (data.get("alias") or "", counts) if item),
            brief,
            data.get("avatar") or "",
        ))
        self._post("albums", self._album_rows(data.get("albums") or []))
        self._cache_album_covers(data.get("albums") or [])
        threading.Thread(target=self._load_artist_playlists, args=(artist_id, token), daemon=True).start()
        songs = data.get("songs") or []
        rows = self._song_rows(songs)
        self._post_songs(
            rows,
            f"热门 {len(songs)} 首",
            len(songs),
            data.get("name") or "歌手",
            token=token,
        )
        self._cache_song_covers(rows)

    def _load_artist_playlists(self, artist_id, token):
        try:
            playlists = api.artist_playlists(artist_id, cookie=self._cookie)
        except api.ApiError as exc:
            LOG.info("artist playlists failed id=%s %s", artist_id, exc)
            return
        if token != self._list_token or artist_id != self._artist_id:
            return
        rows = [
            {
                "itemId": str(item.get("id") or ""),
                "name": item.get("name") or "歌单",
                "cover": item.get("cover") or "",
                "local": "",
                "count": int(item.get("count") or 0),
                "kind": "playlist",
                "creator": item.get("creatorName") or "",
                "creatorId": str(item.get("creator") or ""),
            }
            for item in playlists
            if item.get("id")
        ]
        self._post("cards", (rows, f"相关歌单 {len(rows)} 个"))
        self._queue_covers((item.get("cover") for item in rows), 120, "card")

    def _load_artist_profile(self, artist_id, token):
        try:
            profile = api.artist_profile(artist_id, cookie=self._cookie)
        except api.ApiError:
            return
        if token != self._list_token or artist_id != self._artist_id:
            return
        self._artist_desc_loaded = True
        self._post("artistDesc", profile.get("desc") or "")
        topics = profile.get("topics") or []
        self._post("events", [
            {
                "title": item.get("title") or "",
                "summary": item.get("summary") or "",
                "when": item.get("when") or "",
                "cover": item.get("cover") or "",
                "local": "",
                "read": str(item.get("read") or 0),
            }
            for item in topics
        ])
        self._queue_covers((item.get("cover") for item in topics), 96, "event")

    def _apply_artist_desc(self, text):
        parts = (self._detail_text or "").split("\n", 2)
        name = parts[0] if parts else ""
        sub = parts[1] if len(parts) > 1 else ""
        self._detail_text = "\n".join((name, sub, text or ""))
        self.detailChanged.emit(self._detail_text)

    def _load_artist_albums(self, artist_id, token):
        albums = []
        offset = 0
        while offset < 500:
            try:
                batch = api.artist_albums(artist_id, cookie=self._cookie, limit=100, offset=offset)
            except api.ApiError as exc:
                if token == self._list_token and not albums:
                    self.statusChanged.emit(str(exc))
                break
            if token != self._list_token or artist_id != self._artist_id:
                return
            if not batch:
                break
            albums.extend(batch)
            if len(batch) < 100:
                break
            offset += len(batch)
        if token != self._list_token or artist_id != self._artist_id:
            return
        self._post("albums", self._album_rows(albums))
        self._cache_album_covers(albums)
        self._post("status", f"{len(albums)} 张专辑")

    @staticmethod
    def _album_rows(albums):
        return [
            {
                "itemId": str(item.get("id") or ""),
                "name": item.get("name") or "专辑",
                "cover": item.get("cover") or "",
                "publish": item.get("publish") or "",
                "size": str(item.get("size") or ""),
            }
            for item in albums
        ]

    def _cache_album_covers(self, albums):
        self._queue_covers((item.get("cover") for item in albums), 96, "album")

    @pyqtSlot(str, str)
    def openAlbum(self, album_id, name):
        if not album_id:
            return
        self._show("album", name or "专辑", album_id)
        token = self._begin_list()
        self.songs.replace([])
        token = self._list_token
        self._post("listCount", (token, 0))
        threading.Thread(target=self._load_album, args=(album_id, token), daemon=True).start()

    def _load_album(self, album_id, token):
        try:
            data = api.album_detail(album_id, cookie=self._cookie)
        except api.ApiError as exc:
            if token == self._list_token:
                self.statusChanged.emit(str(exc))
            return
        if token != self._list_token:
            return
        artist = data.get("artist") or {}
        songs = data.get("songs") or []
        pieces = [item for item in (data.get("company"), data.get("publish"), f"{len(songs)} 首") if item]
        desc = (data.get("description") or "").strip()
        if len(desc) > 180:
            desc = desc[:180] + "…"
        self._post("detailPage", (token, (
            "album",
            data.get("name") or "专辑",
            artist.get("name") or "",
            " · ".join(pieces) + ("\n" + desc if desc else ""),
            data.get("cover") or "",
        )))
        rows = self._song_rows(songs)
        self._post("listCount", (token, len(rows)))
        self._post_songs(rows, f"{len(songs)} 首", len(songs), data.get("name") or "专辑", token=token)
        self._cache_song_covers(rows)

    @pyqtSlot(object)
    def _apply_albums(self, rows):
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            return
        self.albums.replace(rows)

    @pyqtSlot(str, str, str, str, str)
    def _apply_detail(self, page, name, sub, brief, cover):
        self._page_title = name
        self._detail_text = "\n".join((name, sub, brief))
        self._detail_cover = ""
        self.pageChanged.emit(page, name)
        self.detailChanged.emit(self._detail_text)
        if cover:
            size = 132 if page == "artist" else 96 if page == "user" else 168
            threading.Thread(target=self._cache_cover, args=(cover, size, "detail"), daemon=True).start()

    def _song_rows(self, songs):
        rows = []
        for song in songs:
            rows.append({
                "songId": str(song.get("id") or ""),
                "name": song.get("name") or "未命名",
                "artist": song.get("artist") or "",
                "artistId": str(song.get("artistId") or ""),
                "artists": "|".join(
                    f"{item.get('id') or ''},{item.get('name') or ''}"
                    for item in (song.get("artists") or [])
                    if item.get("name")
                ),
                "album": song.get("album") or "",
                "albumId": str(song.get("albumId") or ""),
                "cover": song.get("cover") or "",
                "local": "",
                "duration": int(song.get("duration") or 0),
                "vip": int(song.get("fee") or 0) == 1,
                "playable": song.get("playable") is not False,
                "saved": self._song_saved(song.get("id")),
            })
        return rows

    @staticmethod
    def _artist_payload(song):
        people = song.get("artists") or []
        if isinstance(people, str):
            return people
        if not isinstance(people, list):
            return ""
        return "|".join(
            f"{item.get('id') or ''},{item.get('name') or ''}"
            for item in people
            if isinstance(item, dict) and item.get("name")
        )

    def _refuse_unplayable(self, song):
        if song and song.get("playable") is False:
            self.statusChanged.emit(f"暂时没有版权：{song.get('name') or ''}")
            return True
        return False

    # --- 播放和缓存 ---

    @pyqtSlot(int)
    def playRow(self, row):
        song = self.songs.get(row)
        if not song or not song.get("songId"):
            return
        if self._refuse_unplayable(song):
            return
        self._queue = [
            dict(item) for item in self.songs._rows
            if item.get("songId") and item.get("playable") is not False
        ]
        self._queue_source = self._list_id
        self._queue_title = self._page_title or "当前播放"
        self.queue.replace(self._queue)
        index = next((i for i, item in enumerate(self._queue) if item.get("songId") == song.get("songId")), 0)
        self._play_index(index)

    @pyqtSlot(result=int)
    def queueIndex(self):
        return self._index

    @pyqtSlot(int)
    def playQueue(self, row):
        if not (0 <= row < len(self._queue)):
            return
        if self._refuse_unplayable(self._queue[row]):
            return
        self._play_index(row)

    def _play_index(self, index):
        if not (0 <= index < len(self._queue)):
            return
        song = self._queue[index]
        self._index = index
        LOG.info("play index=%s id=%s name=%s queue=%s", index, song.get("songId"), song.get("name"), len(self._queue))
        self._token += 1
        token = self._token
        self._song = song
        self._loading_pos = True
        keep = int(getattr(self, "_resume_at", 0) or 0)
        self._cache_hold = 0
        self.player.begin_switch(keep)
        self.songChanged.emit("\n".join((
            song["songId"], song["name"], song.get("artist") or "", song.get("cover") or "",
            str(int(song.get("duration") or 0)), self._artist_payload(song), song.get("album") or "",
        )))
        # 歌名信号会晚于播放状态到达界面。先把按钮写成正在播放，避免被换歌处理盖成暂停。
        self.stateChanged.emit("playing")
        if self._page == "lyric":
            self._page_title = song.get("name") or "歌词"
            self.pageChanged.emit("lyric", self._page_title)
        self.currentSongChanged.emit(str(song.get("songId") or ""))
        self.likedChanged.emit(str(song.get("songId")) in self._liked)
        kept = int(getattr(self, "_resume_at", 0) or 0)
        self.clockChanged.emit(f"{kept},{int(song.get('duration') or 0)}")
        self._lyrics = []
        self._lyric_words = []
        self._clock_pos = kept
        self.lyricChanged.emit("")
        # 整首先清掉。新歌词还没到时，桌面歌词不能继续按上一首的时间轴往前走。
        self._publish_track()
        self._publish_desk_lyric(kept, "歌词加载中…")
        self._show_cover(song)
        local = self._local_download(song, self._quality)
        cached = local or cache_lookup(song["songId"], self._quality)
        if cached:
            self.statusChanged.emit("正在打开本机文件" if local else "正在打开本机缓存")
            self._post("play", urllib.parse.urljoin("file:", urllib.request.pathname2url(cached)))
            if keep <= 1500:
                self._loading_pos = False
            self.qualityChanged.emit(api.QUALITY_LABEL.get(self._quality, self._quality))
            threading.Thread(target=self._start_cached, args=(token, song), daemon=True).start()
            # 下载文件缺了会直接失败。播放缓存读到一半会停住，和网络流一样等大约 10 秒再切。
            if not local:
                threading.Thread(target=self._watch_stall, args=(token, song), daemon=True).start()
            if str(song.get("songId") or "").isdigit():
                threading.Thread(target=self._load_qualities, args=(token, song["songId"], None), daemon=True).start()
            return
        self.statusChanged.emit(f"正在获取{api.QUALITY_LABEL.get(self._quality, '')}…")
        threading.Thread(target=self._start, args=(token, song), daemon=True).start()
        threading.Thread(target=self._watch_stall, args=(token, song), daemon=True).start()

    def _start_cached(self, token, song):
        """声音已经从缓存开了。只补歌词，不再等播放地址。"""
        label = api.QUALITY_LABEL.get(self._quality, self._quality)
        local = str(getattr(self.player, "_uri", "") or "").startswith("file:") and self._playing_download()
        self.statusChanged.emit(f"正在播放 · {label} · {'本机下载' if local else '本机缓存'}")
        song_id = str(song.get("songId") or "")
        if not song_id.isdigit():
            self._post("lyric", "0\t本地文件没有歌词")
            return
        try:
            original, translated, words = api.lyric_pair(song_id, cookie=self._cookie)
        except api.ApiError:
            return
        if token != self._token:
            return
        lines = api.merge_lrc(original, translated)
        self._lyrics = lines
        self._lyric_words = words
        self._post("lyric", "\n".join(f"{ms}\t{text}" for ms, text in lines) or "0\t这首歌没有歌词")
        self._publish_track()
        self._publish_desk_lyric(self.player.position()[0] or int(getattr(self, "_resume_at", 0) or 0))

    def _watch_stall(self, token, song):
        """只在已经播到某个位置、又停在那里时才切歌。开头没出声、暂停、拖动进度都不算卡住。"""
        stalled_at = 0.0
        stalled_pos = None
        while token == self._token:
            time.sleep(1)
            if token != self._token:
                return
            # 缓冲中声音是停着的。已经出过声就继续计时，大约 10 秒还补不回来再切。
            # 开头还没出声、用户暂停、正在拖动，都不计。
            # 暂停时管道还可能留着缓冲标记。只要用户已经停了，就不能再按卡住切歌。
            held_cache = int(getattr(self, "_cache_hold", 0) or 0)
            if (
                not held_cache
                and (
                    self.player.want() != "playing"
                    or getattr(self.player, "_held_pause", False)
                    or self.player._seek_target is not None
                    or (self._loading_pos and not self.player._buffering)
                )
            ):
                stalled_at = 0.0
                stalled_pos = None
                continue
            heard = held_cache or self.player.heard()
            # 缓存文件提前读完后，管道位置会变成 0。用结束前记下的进度接着计时。
            if heard <= 0:
                heard = self.player.position()[0]
            if heard <= 0:
                stalled_at = 0.0
                stalled_pos = None
                continue
            if stalled_pos is None or abs(heard - stalled_pos) > 500:
                stalled_pos = heard
                stalled_at = time.time()
                continue
            # 缓存停不停都不切歌。只有声音自己停在一个位置，大约 10 秒还出不来，才切下一首。
            if time.time() - stalled_at < 10:
                continue
            # 卡住时歌词停在这一句。界面不再按自己的时钟往前猜。
            self._loading_pos = True
            self._publish_desk_lyric(heard)
            if token != self._token:
                return
            LOG.info("play stalled id=%s name=%s pos=%s", song.get("songId"), song.get("name"), heard)
            self.statusChanged.emit(f"播放卡住，切换下一首：{song.get('name') or ''}")
            self.next()
            return

    def _start(self, token, song):
        try:
            info = api.song_url(song["songId"], level=self._quality, cookie=self._cookie)
        except api.ApiError as exc:
            if token == self._token:
                LOG.info("play url failed id=%s %s", song.get("songId"), exc)
                self.statusChanged.emit(f"{exc}，切换下一首")
                self._loading_pos = False
                self.next()
            return
        if token != self._token:
            return
        if not info or not allowed_uri(info.get("url")):
            self._loading_pos = False
            LOG.info("play url missing id=%s", song.get("songId"))
            self.statusChanged.emit("没有可播放地址，切换下一首")
            self.next()
            return
        level = info.get("level") or self._quality
        local = self._local_download(song, level)
        cached = local or cache_lookup(song["songId"], level)
        play_url = urllib.parse.urljoin("file:", urllib.request.pathname2url(cached)) if cached else info["url"]
        resume_at = int(getattr(self, "_resume_at", 0) or 0)
        self._resume_at = 0
        self._post("play", play_url)
        if resume_at <= 1500:
            self._loading_pos = False
        self._apply_volume()
        self.qualityChanged.emit(api.QUALITY_LABEL.get(level, level))
        label = api.QUALITY_LABEL.get(level, level)
        note = "，已换成这首歌能播的档" if level != self._quality else ""
        source = " · 本机下载" if local else (" · 本机缓存" if cached else "")
        self.statusChanged.emit(f"正在播放 · {label}{note}{source}")
        # 歌词和整首缓存都在出声之后再取。歌词接口慢时不能挡着播放。
        threading.Thread(target=self._load_lyric, args=(token, song), daemon=True).start()
        threading.Thread(target=self._load_qualities, args=(token, song["songId"], info), daemon=True).start()
        if not cached:
            self._queue_cache(token, song["songId"], level, info.get("type") or "mp3", info["url"])

    def _load_lyric(self, token, song):
        """播放已经开始。歌词到了再补上，失败就留着“歌词加载中”。"""
        try:
            original, translated, words = api.lyric_pair(song["songId"], cookie=self._cookie)
        except api.ApiError as exc:
            LOG.info("lyric failed id=%s %s", song.get("songId"), exc)
            return
        if token != self._token:
            return
        lines = api.merge_lrc(original, translated)
        self._lyrics = lines
        self._lyric_words = words
        self._post("lyric", "\n".join(f"{ms}\t{text}" for ms, text in lines) or "0\t这首歌没有歌词")
        self._publish_track()
        self._publish_desk_lyric(self.player.position()[0])

    @pyqtSlot(int)
    def playNext(self, row):
        song = self.songs.get(row)
        if not song or not song.get("songId"):
            return
        if self._refuse_unplayable(song):
            return
        # 歌单行和播放队列必须各持一份。共用同一份时，稍后刷新歌单会把队列里的歌改掉。
        song = dict(song)
        if not self._queue:
            self._queue = [song]
            self._index = 0
            self.queue.replace(self._queue)
            self._play_index(0)
            return
        self._place_next(song)
        self.queue.replace(self._queue)
        self.statusChanged.emit(f"下一首播放 {song.get('name') or ''}")

    @pyqtSlot()
    def playAll(self):
        first = next((i for i, item in enumerate(self.songs._rows) if item.get("songId") and item.get("playable") is not False), -1)
        if first < 0:
            self.statusChanged.emit("没有可播放的歌曲")
            return
        self.playRow(first)

    @pyqtSlot()
    def playListNext(self):
        playlist_id = str(self._list_id or "")
        loaded = [
            dict(item) for item in self.songs._rows
            if item.get("songId") and item.get("playable") is not False
        ]
        # 歌单还没翻完时，已显示的先插进去，剩下的在后台补上。
        if playlist_id and self._list_refs and self._list_offset < self._list_total:
            self._queue_songs_next(loaded, self._page_title or "歌单")
            self.statusChanged.emit("正在加入整张歌单…")
            threading.Thread(
                target=self._play_nav_next,
                args=(playlist_id, self._page_title or "歌单", {item.get("songId") for item in loaded}),
                daemon=True,
            ).start()
            return
        self._queue_songs_next(loaded, self._page_title or "歌单")

    @pyqtSlot()
    def playAlbumNext(self):
        if self._page != "album":
            return
        songs = [
            dict(item) for item in self.songs._rows
            if item.get("songId") and item.get("playable") is not False
        ]
        self._queue_songs_next(songs, self._page_title or "专辑")

    @pyqtSlot(str)
    def playNavNext(self, key):
        row = next((item for item in self.nav._rows if item.get("key") == key), None)
        if not row or row.get("kind") not in ("playlist", "liked", "chart"):
            return
        playlist_id = key if row.get("kind") != "liked" else ""
        if row.get("kind") == "liked":
            liked = next((item for item in self._mine if item.get("special") == 5), None)
            playlist_id = str((liked or {}).get("id") or "")
        if not playlist_id:
            self.statusChanged.emit("还没有可加入的歌单")
            return
        self.statusChanged.emit("正在加入播放列表…")
        threading.Thread(target=self._play_nav_next, args=(playlist_id, row.get("label") or "歌单"), daemon=True).start()

    def _play_nav_next(self, playlist_id, name, skip=None):
        try:
            data = api.playlist_tracks(playlist_id, cookie=self._cookie)
        except api.ApiError as exc:
            self._post("status", str(exc))
            return
        seen = set(skip or ())
        songs = [
            item for item in self._song_rows(data.get("songs") or [])
            if item.get("songId") and item.get("playable") is not False and item.get("songId") not in seen
        ]
        self._post("queueNext", (songs, name, bool(skip)))

    def _place_next(self, song):
        """同一首歌只留一条，并放到当前这首的后面。"""
        song_id = str(song.get("songId") or "")
        playing_id = str((self._song or {}).get("songId") or "")
        kept = [item for item in self._queue if str(item.get("songId") or "") != song_id]
        if playing_id and playing_id != song_id:
            at = next((i for i, item in enumerate(kept) if str(item.get("songId") or "") == playing_id), len(kept) - 1)
            at = min(len(kept), at + 1)
        else:
            at = 0
        kept.insert(at, song)
        self._queue = kept
        if playing_id:
            found = next((i for i, item in enumerate(kept) if str(item.get("songId") or "") == playing_id), None)
            if found is not None:
                self._index = found

    def _unique_songs(self, songs):
        seen = set()
        rows = []
        for item in songs:
            song_id = str(item.get("songId") or "")
            if not song_id or song_id in seen:
                continue
            seen.add(song_id)
            rows.append(dict(item))
        return rows

    def _queue_songs_next(self, songs, name, append=False):
        songs = self._unique_songs(songs)
        if not songs:
            if not append:
                self.statusChanged.emit("没有可播放的歌曲")
            return
        if not self._queue:
            self._queue = songs
            self.queue.replace(self._queue)
            LOG.info("queue start %s songs=%s", name, len(songs))
            self._play_index(0)
            return
        playing_id = str((self._song or {}).get("songId") or "")
        if append:
            insert_at = len(self._queue)
        else:
            insert_at = next(
                (i for i, item in enumerate(self._queue) if str(item.get("songId") or "") == playing_id),
                self._index,
            ) + 1
            insert_at = min(len(self._queue), max(0, insert_at))
        existing = {str(item.get("songId") or "") for item in self._queue}
        songs = [item for item in songs if str(item.get("songId") or "") not in existing]
        if not songs:
            self.statusChanged.emit(f"「{name}」里的歌已经在播放列表中")
            return
        self._queue[insert_at:insert_at] = songs
        if playing_id:
            found = next(
                (i for i, item in enumerate(self._queue) if str(item.get("songId") or "") == playing_id),
                None,
            )
            if found is not None:
                self._index = found
        self.queue.replace(self._queue)
        LOG.info(
            "queue insert %s songs=%s at=%s index=%s playing=%s",
            name, len(songs), insert_at, self._index, playing_id,
        )
        if append:
            self.statusChanged.emit(f"「{name}」又加入 {len(songs)} 首")
        else:
            self.statusChanged.emit(f"已将「{name}」{len(songs)} 首加到下一首")

    @pyqtSlot()
    def toggleSubscribe(self):
        playlist_id = str(self._list_id or "")
        if not playlist_id:
            return
        if not self._require_login("收藏歌单"):
            return
        meta = getattr(self, "_playlist_meta", {}) or {}
        if meta.get("owned") or int(meta.get("special") or 0) == 5:
            self.statusChanged.emit("这是自己的歌单")
            return
        subscribe = not meta.get("collected")
        threading.Thread(target=self._subscribe, args=(playlist_id, subscribe), daemon=True).start()

    def _subscribe(self, playlist_id, subscribe):
        try:
            api.subscribe_playlist(playlist_id, subscribe, self._cookie)
            uid = (self._profile or {}).get("userId")
            self._mine = api.user_playlists(uid, self._cookie) if uid else self._mine
        except api.ApiError as exc:
            self._post("status", str(exc))
            return
        meta = dict(getattr(self, "_playlist_meta", {}) or {})
        if str(meta.get("id") or "") == str(playlist_id):
            meta["collected"] = subscribe
            self._playlist_meta = meta
            self._post("playlistMeta", meta)
        self._post("nav", None)
        self._post("status", "已收藏歌单" if subscribe else "已取消收藏")

    @pyqtSlot(str, str)
    def renameNavPlaylist(self, key, name):
        name = (name or "").strip()
        if not name:
            self.statusChanged.emit("歌单名称不能为空")
            return
        if not self._owned_playlist(key):
            self.statusChanged.emit("只能重命名自己创建的歌单")
            return
        threading.Thread(target=self._rename_playlist, args=(key, name[:40]), daemon=True).start()

    def _rename_playlist(self, playlist_id, name):
        try:
            api.rename_playlist(playlist_id, name, self._cookie)
            uid = (self._profile or {}).get("userId")
            self._mine = api.user_playlists(uid, self._cookie) if uid else self._mine
        except api.ApiError as exc:
            self._post("status", str(exc))
            return
        self._post("nav", None)
        self._post("renamed", (str(playlist_id), name))

    @pyqtSlot(str)
    def deleteNavPlaylist(self, key):
        if not self._owned_playlist(key):
            self.statusChanged.emit("只能删除自己创建的歌单")
            return
        threading.Thread(target=self._delete_playlist, args=(key,), daemon=True).start()

    def _delete_playlist(self, playlist_id):
        try:
            api.delete_playlist(playlist_id, self._cookie)
            uid = (self._profile or {}).get("userId")
            self._mine = api.user_playlists(uid, self._cookie) if uid else self._mine
        except api.ApiError as exc:
            self._post("status", str(exc))
            return
        self._post("nav", None)
        if str(self._list_id) == str(playlist_id):
            self._post("home", None)
        self._post("status", "歌单已删除")

    @pyqtSlot(str)
    def unsubscribeNav(self, key):
        if self._owned_playlist(key) or not any(str(item.get("id")) == str(key) for item in self._mine):
            self.statusChanged.emit("只能取消收藏别人的歌单")
            return
        if not self._require_login("取消收藏"):
            return
        threading.Thread(target=self._subscribe, args=(key, False), daemon=True).start()

    def _owned_playlist(self, playlist_id):
        uid = str((self._profile or {}).get("userId") or "")
        return any(
            str(item.get("id")) == str(playlist_id)
            and uid
            and str(item.get("creator") or "") == uid
            and item.get("special") != 5
            for item in self._mine
        )

    @pyqtSlot(int)
    def toggleLike(self, row):
        song = self._song if row < 0 else self.songs.get(row)
        if not song or not song.get("songId"):
            return
        if not self._cookie:
            self.statusChanged.emit("请先登录再收藏")
            return
        like = str(song["songId"]) not in self._liked
        threading.Thread(target=self._like, args=(song, like), daemon=True).start()

    def _like(self, song, like):
        try:
            api.like_song(song["songId"], like, self._cookie)
        except api.ApiError as exc:
            self.statusChanged.emit(str(exc))
            return
        if like:
            self._liked.add(str(song["songId"]))
        else:
            self._liked.discard(str(song["songId"]))
        self.statusChanged.emit(("已加入我喜欢" if like else "已取消喜欢") + f"：{song.get('name') or ''}")
        if self._song and str(self._song.get("songId")) == str(song["songId"]):
            self.likedChanged.emit(like)

    def row_liked(self, row):
        song = self.songs.get(row)
        return bool(song) and str(song.get("songId")) in self._liked

    @pyqtSlot()
    def toggle(self):
        # 跟播放按钮用同一个状态。内部“想播放”在出声前就会置上，不能拿它判断能不能暂停。
        if self._ui_playing:
            held = self.player.position()[0]
            self._clock_pos = held
            self.player.pause()
            self.clockChanged.emit(f"{held},{int((self._song or {}).get('duration') or self.player.position()[1] or 0)}")
            self._publish_desk_lyric(held)
            if self._cache_net_down:
                self.statusChanged.emit("已暂停，网络不可用")
            elif self._cache_job:
                self.statusChanged.emit("已暂停，继续缓存这首")
            else:
                self.statusChanged.emit("已暂停")
            return
        if self._song and self.player.has_source():
            held = self.player.position()[0]
            if self.player.resume():
                self._clock_pos = held
                self._publish_desk_lyric(held)
                self.statusChanged.emit("继续播放")
                return
        if self._song:
            # 暂停太久后流地址会失效。丢掉旧源，从记下的进度重开这首。
            self.player.drop_source()
            self._resume_at = self.player.position()[0]
            self._play_index(self._index)

    @pyqtSlot()
    def next(self):
        self._step(1)

    @pyqtSlot()
    def previous(self):
        self._step(-1)

    def _step(self, step):
        if not self._queue:
            return
        if self._mode == "shuffle":
            choices = [
                i for i in range(len(self._queue))
                if i != self._index and self._queue[i].get("playable") is not False
            ]
            if not choices:
                self.statusChanged.emit("没有可播放的下一首")
                return
            index = random.choice(choices)
        elif self._mode == "single" and step > 0:
            index = self._index
        else:
            index = self._index + step
            limit = len(self._queue)
            for _ in range(limit):
                if 0 <= index < limit and self._queue[index].get("playable") is not False:
                    break
                index += 1 if step >= 0 else -1
                if not (0 <= index < limit):
                    if self._mode == "order":
                        self._post("stop", None)
                        self.statusChanged.emit("列表播放结束")
                        return
                    index %= limit
            else:
                self.statusChanged.emit("没有可播放的下一首")
                return
        self._play_index(index)

    @pyqtSlot(int)
    def seek(self, ms):
        target = int(ms)
        self._post("seek", target)
        self._publish_desk_lyric(target)

    @pyqtSlot()
    def cycleMode(self):
        self._mode = MODES[(MODES.index(self._mode) + 1) % len(MODES)]
        self.modeChanged.emit(MODE_LABEL[self._mode])
        self.statusChanged.emit(MODE_LABEL[self._mode])

    @pyqtSlot(float)
    def setVolume(self, value):
        self._volume = max(0.0, min(1.0, float(value)))
        self.volumeChanged.emit(self._volume)
        self._apply_volume()
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(VOLUME_PATH, "w", encoding="utf-8") as handle:
                handle.write(f"{self._volume:.3f}")
        except OSError:
            pass

    def _saved_volume(self):
        try:
            return max(0.0, min(1.0, float(open(VOLUME_PATH, encoding="utf-8").read().strip())))
        except (OSError, ValueError):
            return 0.8

    def _apply_volume(self):
        # 只改这个播放器的增益，不改整机输出。播放流还没出现时也能生效。
        self._post("volume", self._volume)

    def _load_qualities(self, token, song_id, known):
        if not str(song_id or "").isdigit():
            return
        try:
            supported = api.song_qualities(song_id, cookie=self._cookie, known={known.get("level"): known} if known else None)
        except api.ApiError:
            return
        if token != self._token:
            return
        self._supported = supported
        labels = [f"{key}|{api.QUALITY_LABEL.get(key, key)}" for key in supported]
        self._post("qualities", "\n".join(labels))

    @pyqtSlot(str)
    def setQuality(self, level):
        if level not in api.QUALITY_LABEL or not self._song:
            return
        self._quality = level
        position = self.player.position()[0]
        self._play_index(self._index)
        if position > 1500:
            threading.Timer(0.8, lambda: self._post("seek", position)).start()

    def _show_cover(self, song):
        """切歌就换封面。本机缓存开播不再请求播放地址，封面不能等那一步。"""
        url = (song or {}).get("cover") or ""
        if not url:
            self.coverChanged.emit("")
            return
        threading.Thread(target=self._cache_cover, args=(url, 240), daemon=True).start()

    def _cache_cover(self, url, size, kind="song", post=True):
        if not self._alive or not url:
            return ""
        try:
            from io import BytesIO
            from PIL import Image
            from player import cover_cache_path, _https_media_url
            import urllib.parse
            import urllib.request
            path = cover_cache_path(url, size)

            def write_jpeg(image):
                # 路径是 .jpg。Qt 5.12 按后缀选解码器，内容必须真的是 JPEG。
                tmp = f"{path}.{threading.get_ident()}.part"
                try:
                    image.convert("RGB").save(tmp, format="JPEG", quality=85)
                    os.replace(tmp, path)
                finally:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

            cached = os.path.exists(path) and os.path.getsize(path) >= 32
            if cached:
                try:
                    with open(path, "rb") as handle:
                        cached = handle.read(3) == b"\xff\xd8\xff"
                except OSError:
                    cached = False
            if not cached:
                safe = _https_media_url(url)
                parsed = urllib.parse.urlparse(safe)
                query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
                query["param"] = f"{size * 2}y{size * 2}"
                req = urllib.request.Request(
                    urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query))),
                    headers={"User-Agent": api.UA, "Referer": "https://music.163.com/"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read(2 * 1024 * 1024 + 1)
                if len(data) > 2 * 1024 * 1024:
                    raise OSError("封面过大")
                with Image.open(BytesIO(data)) as image:
                    image.load()
                    write_jpeg(image)
            if not self._alive:
                return ""
            if not post:
                return path
            if kind == "song":
                self.coverChanged.emit(path)
            elif kind in ("card", "nav", "songrow", "collect", "detail", "album", "comment", "event"):
                self._post("cardLocal", (url, path, kind))
            return path
        except (OSError, ValueError):
            return ""

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

    def _desk_lyric_alive(self):
        proc = self._desk_lyric_proc
        return proc is not None and proc.poll() is None

    def _launch_desk_lyric(self):
        if self._desk_lyric_alive():
            return
        env = os.environ.copy()
        env["GDK_BACKEND"] = "x11"
        env.pop("WAYLAND_DISPLAY", None)
        def _arm():
            try:
                import ctypes
                libc = ctypes.CDLL("libc.so.6", use_errno=True)
                libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
                libc.prctl.restype = ctypes.c_int
                libc.prctl(1, 15, 0, 0, 0)
                libc.prctl.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
                libc.prctl(15, b"desk-lyric", 0, 0, 0)
            except (OSError, AttributeError):
                pass
        self._desk_lyric_proc = subprocess.Popen(
            ["/usr/bin/python3", player_script(), "--desk-lyric"],
            env=env,
            preexec_fn=_arm,
        )
        self.deskLyricChanged.emit(True)
        self._publish_track()
        self._publish_desk_lyric(self.player.position()[0])

    def _lyric_pids(self):
        found = []
        proc = self._desk_lyric_proc
        if proc is not None and proc.poll() is None:
            found.append(proc.pid)
        try:
            listing = subprocess.run(
                ["ps", "-eo", "pid,args"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return found
        me = os.getpid()
        for line in listing.stdout.splitlines():
            if "--desk-lyric" not in line or "player.py" not in line:
                continue
            parts = line.split(None, 1)
            if not parts or not parts[0].isdigit():
                continue
            pid = int(parts[0])
            if pid == me or pid in found:
                continue
            try:
                parent = int(open(f"/proc/{pid}/stat", encoding="utf-8").read().split()[3])
            except (OSError, IndexError, ValueError):
                parent = 0
            if parent in (me, 1) or (proc is not None and pid == proc.pid):
                found.append(pid)
        return found

    def _close_desk_lyric(self):
        pids = self._lyric_pids()
        for pid in pids:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        proc = self._desk_lyric_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
        for pid in pids:
            try:
                os.kill(pid, 0)
            except OSError:
                continue
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        self._desk_lyric_proc = None
        self.deskLyricChanged.emit(False)

    @pyqtSlot()
    def toggleDeskLyric(self):
        if self._desk_lyric_alive():
            self._close_desk_lyric()
            self._remember_desk_lyric(False)
            self.statusChanged.emit("桌面歌词已关闭")
            return
        self._launch_desk_lyric()
        self._remember_desk_lyric(True)
        self.statusChanged.emit("桌面歌词已打开")

    def _lyric_span(self, elapsed):
        lines = self._lyrics or []
        heard = max(0, int(elapsed))
        index = -1
        for i, (ms, text) in enumerate(lines):
            if text and ms <= heard:
                index = i
            elif ms > heard:
                break
        if index < 0:
            title = (self._song or {}).get("name") or "暂无歌词"
            return title, 0, 1
        start, text = lines[index]
        if index + 1 < len(lines):
            nxt = lines[index + 1][0]
            end = nxt
        else:
            end = start + 4000
        return text, start, max(start + 1, end)

    def _write_lyric_file(self, path, payload):
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, path)

    def _publish_track(self):
        """整首交给歌词窗口。换句和逐字变色都在那边按时间走，不再等这一拍写盘。"""
        lines = [[int(ms), text] for ms, text in (self._lyrics or []) if text]
        words = [
            [int(start), int(end), [[glyph, int(at), int(duration)] for glyph, at, duration in glyphs]]
            for start, end, glyphs in (getattr(self, "_lyric_words", None) or [])
        ]
        payload = {"id": str((self._song or {}).get("songId") or ""), "lines": lines, "words": words}
        if payload == getattr(self, "_desk_track_payload", None):
            return
        self._desk_track_payload = payload
        try:
            self._write_lyric_file(LYRIC_TRACK_PATH, payload)
        except OSError:
            pass

    def _word_span(self, elapsed):
        """有逐字时间就按字头切。没有就退回整句时长。"""
        heard = max(0, int(elapsed))
        words = getattr(self, "_lyric_words", None) or []
        chosen = None
        nearest = None
        nearest_gap = None
        for start, end, glyphs in words:
            if start <= heard:
                chosen = (start, end, glyphs)
            gap = abs(start - heard)
            if nearest is None or gap < nearest_gap:
                nearest = (start, end, glyphs)
                nearest_gap = gap
            elif start > heard and chosen:
                break
        if not chosen and nearest and nearest_gap is not None and nearest_gap <= 80:
            chosen = nearest
        if not chosen:
            return None
        start, end, glyphs = chosen
        cut = 0
        for glyph, glyph_at, _duration in glyphs:
            if glyph_at <= heard:
                cut += len(glyph)
            else:
                break
        return "".join(glyph for glyph, _at, _duration in glyphs), int(start), int(end), int(cut)

    def _publish_desk_lyric(self, elapsed=0, line=None):
        words = None
        if line is None:
            timed = self._word_span(elapsed)
            if timed:
                text, start, end, words = timed
            else:
                text, start, end = self._lyric_span(elapsed)
        else:
            text, start, end = line, 0, 1
        playing = self.player.want() == "playing" and not self._loading_pos and not self.player._seek_target
        payload = {
            "id": str((self._song or {}).get("songId") or ""),
            "line": text,
            "start": int(start),
            "end": int(end),
            "position": int(elapsed),
            "at": time.time(),
            "playing": playing,
        }
        if words is not None:
            payload["words"] = words
        previous = self._desk_lyric_payload
        if (
            previous
            and previous.get("id") == payload["id"]
            and previous.get("line") == text
            and previous.get("playing") == playing
            and previous.get("words") == payload.get("words")
            and playing
            and abs(previous.get("position", 0) - int(elapsed)) < 400
        ):
            return
        self._desk_lyric_payload = payload
        try:
            self._write_lyric_file(LYRIC_PATH, payload)
        except OSError:
            pass

    @pyqtSlot(str, result=str)
    def loginQrPath(self, key):
        token = "".join(ch for ch in str(key) if ch.isalnum() or ch in "-_")
        if not token or token != str(key):
            return ""
        path = os.path.join(DATA_DIR, "login-qr.png")
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            subprocess.check_call(
                ["qrencode", "-o", path, "-s", "8", "-m", "2", "https://music.163.com/login?codekey=" + token],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return path

    @pyqtSlot()
    def startLogin(self):
        if self._cookie:
            self.statusChanged.emit("已登录，可在账号菜单退出")
            return
        self._login = {"done": False, "key": "", "cookie": ""}
        threading.Thread(target=self._create_login, daemon=True).start()

    def _create_login(self):
        try:
            key, cookie = api.login_qr_create()
        except Exception as exc:
            self._post("status", f"生成二维码失败：{exc}")
            return
        token = "".join(ch for ch in str(key) if ch.isalnum() or ch in "-_")
        if token != str(key):
            self._post("status", "登录二维码无效")
            return
        self._login = {"done": False, "key": key, "cookie": cookie}
        self._post("login", token)
        self._poll_login()

    def _poll_login(self):
        while not self._login.get("done"):
            time.sleep(1.5)
            if self._login.get("done"):
                return
            try:
                result = api.login_qr_check(self._login["key"], self._login["cookie"])
            except api.ApiError as exc:
                self._post("status", str(exc))
                continue
            code = result.get("code")
            if code == 802:
                self._post("status", "已扫码，请在手机上确认。")
            elif code == 803 and result.get("cookie"):
                self._login["done"] = True
                api.save_cookie(COOKIE_PATH, result["cookie"])
                self._cookie = result["cookie"]
                self._post("status", "登录成功，正在读取账号…")
                self._post("login", "")
                self._boot_account()
                return
            elif code == 800:
                self._login["done"] = True
                self._post("status", "二维码已过期，请重新登录。")
                self._post("login", "")

    @pyqtSlot()
    def cancelLogin(self):
        self._login["done"] = True
        self.loginKeyChanged.emit("")

    @pyqtSlot()
    def logout(self):
        self._cookie = ""
        self._profile = None
        self._mine = []
        self._liked = set()
        self._fill_nav()
        try:
            os.remove(COOKIE_PATH)
        except OSError:
            pass
        self.accountChanged.emit("登录")
        self.statusChanged.emit("已退出登录")

    def _boot_account(self):
        try:
            self._profile = api.user_account(self._cookie)
            self._post("account", self._account_label(self._profile))
            self._liked = {str(item) for item in api.liked_ids(self._cookie)}
            uid = self._profile.get("userId")
            self._mine = api.user_playlists(uid, self._cookie) if uid else []
            self._post("nav", None)
        except api.ApiError as exc:
            self._post("status", str(exc))
            self._post("account", "登录")

    @pyqtSlot(int)
    def openComments(self, row):
        song = self._song if row < 0 else self.songs.get(row)
        if not song or not song.get("songId"):
            self.statusChanged.emit("先选一首歌再看评论")
            return
        self._comment_song = song
        self._comment_offset = 0
        self._show("comments", song.get("name") or "评论")
        threading.Thread(target=self._fetch_comments, args=(song, 0), daemon=True).start()

    @pyqtSlot()
    def moreComments(self):
        song = self._comment_song
        if not song:
            return
        self._comment_offset += 20
        threading.Thread(target=self._fetch_comments, args=(song, self._comment_offset), daemon=True).start()

    def _fetch_comments(self, song, offset):
        try:
            data = api.comments(song["songId"], offset=offset, cookie=self._cookie)
        except api.ApiError as exc:
            self._post("status", str(exc))
            return
        if offset == 0:
            self._comment_data = data
        else:
            latest = list(self._comment_data.get("latest") or [])
            latest.extend(data.get("latest") or [])
            self._comment_data["latest"] = latest
            self._comment_data["more"] = data.get("more")
        self._apply_comment_tab()
        self._post("status", f"评论 {data.get('total') or 0} 条")

    def _apply_comment_tab(self):
        data = self._comment_data or {}
        source = data.get("hot") if self._comment_tab == "hot" else data.get("latest")
        rows = []
        for item in source or []:
            stamp = int(item.get("time") or 0) / 1000
            when = time.strftime("%Y-%m-%d", time.localtime(stamp)) if stamp else ""
            rows.append({
                "nickname": item.get("nickname") or "用户",
                "userId": str(item.get("userId") or ""),
                "avatar": item.get("avatar") or "",
                "local": "",
                "content": item.get("content") or "",
                "when": when,
                "liked": str(item.get("liked") or 0),
                "hot": self._comment_tab == "hot",
            })
        self._post("comments", rows)
        for item in source or []:
            if item.get("avatar"):
                threading.Thread(
                    target=self._cache_cover, args=(item["avatar"], 36, "comment"), daemon=True,
                ).start()

    @pyqtSlot(str)
    def setCommentTab(self, tab):
        self._comment_tab = "latest" if tab == "latest" else "hot"
        self._apply_comment_tab()

    @pyqtSlot(str)
    def sendComment(self, text):
        song = self._comment_song
        if not song or not song.get("songId"):
            self.statusChanged.emit("先选一首歌再写评论")
            return
        if not self._require_login("写评论"):
            return
        threading.Thread(target=self._send_comment, args=(song, text), daemon=True).start()

    def _send_comment(self, song, text):
        try:
            api.add_comment(song["songId"], text, self._cookie)
        except api.ApiError as exc:
            self._post("status", str(exc))
            return
        self._post("status", "评论已发送")
        self._fetch_comments(song, 0)

    @pyqtSlot()
    def openVip(self):
        if not self._cookie:
            self.statusChanged.emit("请先登录再查看会员")
            return
        self._show("user", "会员信息")
        threading.Thread(target=self._load_vip, daemon=True).start()

    def _load_vip(self):
        try:
            profile = api.user_account(self._cookie)
        except api.ApiError as exc:
            self._post("status", str(exc))
            return
        self._profile = profile
        expire = int(profile.get("vipExpire") or 0)
        when = time.strftime("%Y-%m-%d", time.localtime(expire / 1000)) if expire > 10_000_000_000 else ""
        name = profile.get("vip") or "普通用户"
        level = profile.get("vipLevel") or 0
        line = name + (f" · 等级 {level}" if level else "")
        if when:
            line += f" · 到期 {when}"
        self._post("detail", (
            "user",
            profile.get("nickname") or "已登录",
            line,
            "开通、续费在网易云音乐官方页面完成。这里只显示当前身份，不改变会员权限。",
            profile.get("avatar") or "",
        ))

    @pyqtSlot(str, str)
    def openUser(self, user_id, name):
        if not user_id:
            return
        self._show("user", name or "用户")
        self._user_token = getattr(self, "_user_token", 0) + 1
        token = self._user_token
        revision = self._navigation_revision
        threading.Thread(target=self._load_user, args=(user_id, name, token, revision), daemon=True).start()

    def _load_user(self, user_id, name, token, revision):
        try:
            data = api.user_detail(user_id, cookie=self._cookie)
        except api.ApiError as exc:
            LOG.info("user detail failed id=%s %s", user_id, exc)
            self._post("status", str(exc))
            return
        if token != getattr(self, "_user_token", 0) or revision != self._navigation_revision or self._page != "user":
            return
        brief = data.get("signature") or ""
        counts = f"关注 {data.get('follows') or 0} · 粉丝 {data.get('followers') or 0}"
        self._post("detail", (
            "user",
            data.get("nickname") or name or "用户",
            counts,
            brief,
            data.get("avatar") or "",
        ))
        try:
            playlists = api.user_playlists(user_id, self._cookie)
        except api.ApiError as exc:
            LOG.info("user playlists failed id=%s %s", user_id, exc)
            return
        if token != getattr(self, "_user_token", 0) or revision != self._navigation_revision or self._page != "user":
            return
        rows = [
            {
                "itemId": str(item.get("id") or ""),
                "name": item.get("name") or "歌单",
                "cover": item.get("cover") or "",
                "local": "",
                "count": int(item.get("count") or 0),
                "kind": "playlist",
                "creator": item.get("creatorName") or "",
                "creatorId": str(item.get("creator") or ""),
            }
            for item in playlists
            if item.get("id")
        ]
        self._post("cards", (rows, f"{data.get('nickname') or name or '用户'} 的歌单 {len(rows)} 个"))
        self._queue_covers((item.get("cover") for item in rows), 120, "card")

    # --- 下载管理 ---

    @pyqtSlot(int)
    def enqueueDownload(self, row):
        if row < 0:
            song = self._song
        else:
            song = self.songs.get(row)
        if not song or not song.get("songId"):
            self.statusChanged.emit("没有可下载的歌曲")
            return
        if not self._require_login("下载"):
            return
        self._enqueue_download_songs([song])

    @pyqtSlot(str)
    def enqueueDownloads(self, rows):
        if not self._require_login("下载"):
            return
        self._enqueue_download_songs(self._songs_for_batch(rows))

    def _enqueue_download_songs(self, songs):
        picked = [
            dict(song) for song in songs
            if song.get("songId") and song.get("playable") is not False and not song.get("saved")
            and not self._local_download(song, "")
        ]
        if not picked:
            self.statusChanged.emit("选中的歌曲都已下载" if songs else "没有可下载的歌曲")
            return
        added = 0
        with self._download_lock:
            waiting = {
                str(item.get("songId") or "")
                for item in self._download_rows
                if item.get("status") in ("等待", "下载中")
            }
            for song in picked:
                song_id = str(song.get("songId") or "")
                if song_id in waiting:
                    continue
                waiting.add(song_id)
                self._download_rows.append({
                    "name": song.get("name") or "",
                    "status": "等待",
                    "quality": api.QUALITY_LABEL.get(self._quality, self._quality),
                    "path": "",
                    "songId": song_id,
                    "song": song,
                    "level": self._quality,
                })
                added += 1
            self._save_downloads()
        if added == 0:
            self.statusChanged.emit("这些歌已经在下载队列里")
            return
        self._post("downloads", self._download_view())
        if added == 1:
            self._post("status", f"已加入下载：{picked[0].get('name') or ''} · {api.QUALITY_LABEL.get(self._quality, self._quality)}")
        else:
            self._post("status", f"已加入下载 {added} 首 · {api.QUALITY_LABEL.get(self._quality, self._quality)}")
        self._ensure_download_worker()

    def _songs_for_batch(self, encoded_ids):
        ids = {str(song_id).strip() for song_id in str(encoded_ids or "").split(",") if str(song_id).strip()}
        return [dict(song) for song in self.songs._rows if str(song.get("songId") or "") in ids]

    def _parse_batch_selection(self, value):
        text = str(value or "")
        if text.startswith("*"):
            return True, [item for item in text[1:].lstrip(":").split(",") if item]
        return False, [item for item in text.split(",") if item]

    def _resolve_batch_songs(self, page, playlist_id, rows, all_songs, selected_ids):
        """在工作线程解析批量歌曲；rows 是主线程进入动作时的快照。"""
        selected = {str(item) for item in (selected_ids or [])}
        if page == "playlist" and all_songs and playlist_id:
            data = api.playlist_tracks(playlist_id, cookie=self._cookie)
            songs = self._song_rows(data.get("songs") or [])
        else:
            songs = [dict(song) for song in rows]
        if selected and all_songs:
            songs = [song for song in songs if str(song.get("songId") or "") not in selected]
        elif selected:
            songs = [song for song in songs if str(song.get("songId") or "") in selected]
        return [song for song in songs if song.get("songId")]

    def _start_batch_worker(self, action, all_songs, ids, revision, token, page, playlist_id, meta_id, rows, target=""):
        threading.Thread(
            target=self._batch_worker,
            args=(action, all_songs, ids, revision, token, page, playlist_id, meta_id, rows, target),
            daemon=True,
        ).start()

    @pyqtSlot(str, str)
    def batchAction(self, action, selected_ids=""):
        action = str(action or "").strip()
        if action not in ("play", "queue", "download", "remove"):
            return
        if self._page not in ("playlist", "album"):
            return
        if action in ("download", "remove") and not self._require_login("批量操作"):
            return
        if action == "remove" and (self._page != "playlist" or not self.canRemoveCurrent()):
            self.statusChanged.emit("只能从自己创建的歌单移除")
            return
        revision = self._navigation_revision
        token = self._list_token
        page = self._page
        playlist_id = str(self._list_id or "")
        meta_id = str((self._playlist_meta or {}).get("id") or "")
        all_songs, ids = self._parse_batch_selection(selected_ids)
        if not all_songs and not ids:
            self.statusChanged.emit("请先选择歌曲")
            return
        rows = [dict(song) for song in self.songs._rows]
        self._start_batch_worker(
            action, all_songs, ids, revision, token, page, playlist_id, meta_id, rows,
        )

    @pyqtSlot(str)
    def openBatchCollect(self, selected_ids=""):
        if not self._require_login("收藏到歌单"):
            return
        if self._page not in ("playlist", "album"):
            return
        all_songs, ids = self._parse_batch_selection(selected_ids)
        if not all_songs and not ids:
            self.statusChanged.emit("请先选择歌曲")
            return
        revision = self._navigation_revision
        token = self._list_token
        page = self._page
        playlist_id = str(self._list_id or "")
        rows = [dict(song) for song in self.songs._rows]
        threading.Thread(
            target=self._prepare_batch_collect,
            args=(revision, token, page, playlist_id, rows, all_songs, ids),
            daemon=True,
        ).start()

    def _prepare_batch_collect(self, revision, token, page, playlist_id, rows, all_songs, ids):
        self._post("batchCollectPopup", (revision, token))

    @pyqtSlot(str, str)
    def batchCollect(self, playlist_id, selected_ids=""):
        if not self._require_login("收藏到歌单"):
            return
        if self._page not in ("playlist", "album"):
            return
        playlist_id = str(playlist_id or "").strip()
        allowed = {
            str(item.get("id") or "")
            for item in self._mine
            if item.get("id") and (item.get("special") == 5 or self._owned_playlist(item.get("id")))
        }
        if not playlist_id or playlist_id not in allowed:
            self.statusChanged.emit("只能收藏到自己的歌单")
            return
        revision = self._navigation_revision
        token = self._list_token
        all_songs, ids = self._parse_batch_selection(selected_ids)
        if not all_songs and not ids:
            self.statusChanged.emit("请先选择歌曲")
            return
        rows = [dict(song) for song in self.songs._rows]
        self._start_batch_worker(
            "collect", all_songs, ids, revision, token, self._page,
            str(self._list_id or ""), str((self._playlist_meta or {}).get("id") or ""),
            rows, playlist_id,
        )

    def _batch_worker(self, action, all_songs, ids, revision, token, page, playlist_id, meta_id, rows, target):
        try:
            songs = self._resolve_batch_songs(page, playlist_id, rows, all_songs, ids)
        except api.ApiError as exc:
            self._post("status", str(exc))
            return
        songs = [song for song in songs if song.get("playable") is not False]
        if not songs:
            self._post("status", "没有可操作的歌曲")
            return
        if action in ("play", "queue"):
            self._post("batchPlay" if action == "play" else "batchQueue", (
                songs, self._page_title, revision, token,
            ))
            return
        if action == "download":
            self._post("batchDownload", (songs, revision, token))
            return
        if action == "collect":
            song_ids = [song["songId"] for song in songs]
            try:
                completed = api.manipulate_playlist_tracks(target, song_ids, "add", self._cookie)
            except api.ApiError as exc:
                self._post("status", str(exc))
                return
            if revision == self._navigation_revision:
                self._post("status", f"已加入歌单 {completed} 首")

            return
        if action == "remove":
            if page != "playlist" or not playlist_id or playlist_id != meta_id:
                self._post("status", "当前页面不能移除歌曲")
                return
            if not self._owned_playlist(playlist_id):
                self._post("status", "只能从自己创建的歌单移除")
                return
            song_ids = [str(song["songId"]) for song in songs]
            try:
                completed = api.manipulate_playlist_tracks(playlist_id, song_ids, "del", self._cookie)
            except api.ApiError as exc:
                self._post("status", str(exc))
                return
            self._post("dropSongs", (song_ids[:completed], token, f"已从歌单移除 {completed} 首"))

    def _play_batch_songs(self, songs, name):
        songs = [dict(song) for song in self._unique_songs(songs) if song.get("playable") is not False]
        if not songs:
            self.statusChanged.emit("没有可播放的歌曲")
            return
        self._queue = songs
        self._queue_title = name or self._page_title or "当前播放"
        self._queue_source = self._list_id if self._page == "playlist" else ""
        self.queue.replace(songs)
        self._play_index(0)

    def _ensure_download_worker(self):
        self._download_wake.set()
        with self._download_lock:
            alive = self._download_worker is not None and self._download_worker.is_alive()
            if alive:
                return
            self._download_worker = threading.Thread(target=self._download_loop, daemon=True)
            self._download_worker.start()

    def _download_group(self, status):
        if status in ("下载中", "等待"):
            return "正在下载"
        if status == "完成":
            return "已下载"
        return "下载失败"

    def _download_view(self):
        """保持下载记录原来的顺序。同一首已完成的歌只留最新一条，文件不在了就不显示。

        下载目录里已有、但记录里没有的文件补在后面。记录只认完成时写下的编号，
        所以以前下好的歌一直不出现。
        """
        latest = {}
        known_paths = set()
        for index, item in enumerate(self._download_rows):
            path = os.path.realpath(item.get("path") or "") if item.get("path") else ""
            if path:
                known_paths.add(path)
            if item.get("status") != "完成":
                continue
            song_id = str(item.get("songId") or "")
            key = song_id or path or (item.get("name") or "")
            if not key:
                continue
            if not self._download_file(item):
                continue
            latest[key] = index
        rows = []
        for index, item in enumerate(self._download_rows):
            status = item.get("status") or ""
            if status == "完成":
                song_id = str(item.get("songId") or "")
                path = os.path.realpath(item.get("path") or "") if item.get("path") else ""
                key = song_id or path or (item.get("name") or "")
                if latest.get(key) != index:
                    continue
            path = item.get("path") or ""
            rows.append({
                "name": item.get("name") or "",
                "status": status,
                "quality": item.get("quality") or "",
                "path": os.path.basename(path) if path else "",
                "songId": str(item.get("songId") or "") or path,
                "group": self._download_group(status),
            })
        for path in self._folder_audio():
            if path in known_paths:
                continue
            name = os.path.splitext(os.path.basename(path))[0]
            rows.append({
                "name": name,
                "status": "完成",
                "quality": "本地文件",
                "path": os.path.basename(path),
                "songId": path,
                "group": "已下载",
            })
        return rows

    def _load_downloads(self):
        try:
            payload = json.loads(open(DOWNLOAD_INDEX, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            return []
        rows = []
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            status = item.get("status") or ""
            if status == "下载中":
                status = "等待"
            rows.append({
                "name": item.get("name") or "",
                "status": status,
                "quality": item.get("quality") or "",
                "path": item.get("path") or "",
                "songId": str(item.get("songId") or ""),
                "level": item.get("level") or "",
                "song": item.get("song") if isinstance(item.get("song"), dict) else {},
            })
        return rows[-200:]

    def _save_downloads(self):
        payload = [
            {
                "name": item.get("name") or "",
                "status": item.get("status") or "",
                "quality": item.get("quality") or "",
                "path": item.get("path") or "",
                "songId": str(item.get("songId") or ""),
                "level": item.get("level") or "",
                "song": item.get("song") if isinstance(item.get("song"), dict) else {},
            }
            for item in self._download_rows[-200:]
        ]
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = DOWNLOAD_INDEX + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp, DOWNLOAD_INDEX)
        except OSError:
            pass

    def _download_loop(self):
        """一直守着队列。暂停或暂时没有任务时不能退出，否则点了继续也没有线程再拉。"""
        while self._alive:
            with self._download_lock:
                if self._download_paused:
                    item = None
                else:
                    item = next((row for row in self._download_rows if row.get("status") == "等待" and row.get("song")), None)
                    if item is not None:
                        item["status"] = "下载中"
                        self._save_downloads()
            if item is None:
                if not self._download_wake.wait(1):
                    continue
                self._download_wake.clear()
                continue
            existing = self._local_download({"songId": item.get("songId")}, item.get("level") or "") or self._named_download(item)
            if existing:
                item["status"] = "完成"
                item["path"] = existing
                item["quality"] = item.get("quality") or "本地文件"
                self._save_downloads()
                self._mark_downloaded()
                self._post("downloads", self._download_view())
                continue
            self._post("downloads", self._download_view())
            try:
                path, level = self._download_one(item["song"], item.get("level") or self._quality)
            except Exception as exc:
                LOG.info("download failed id=%s name=%s %s", item.get("songId"), item.get("name"), exc)
                item["status"] = f"失败：{exc}"
                self._save_downloads()
                self._post("downloads", self._download_view())
                continue
            item["status"] = "完成"
            item["path"] = path
            item["songId"] = str((item.get("song") or {}).get("songId") or item.get("songId") or "")
            item["level"] = level
            item["quality"] = api.QUALITY_LABEL.get(level, level)
            self._save_downloads()
            self._mark_downloaded()
            # 下完就换列表。正在看「正在下载」时，这首会离开，出现在「已下载」。
            self._post("downloads", self._download_view())
            self._post("status", f"下载完成：{os.path.basename(path)}")

    def _download_one(self, song, level):
        info = api.song_url(song["songId"], level=level, cookie=self._cookie)
        if not info or not allowed_uri(info.get("url")):
            raise api.ApiError("没有可下载地址")
        music = os.path.join(os.path.expanduser("~/Music"), "网易云音乐")
        os.makedirs(music, exist_ok=True)
        ext = "".join(ch for ch in str(info.get("type") or "mp3") if ch.isalnum()) or "mp3"
        raw = f"{song.get('artist') or '未知'} - {song.get('name') or song['songId']}"
        raw = raw.replace("/", " ").replace("\\", " ").replace("\x00", "").strip(" .") or str(song["songId"])
        dest = os.path.join(music, raw + "." + ext)
        if os.path.commonpath((os.path.abspath(music), os.path.abspath(dest))) != os.path.abspath(music):
            raise OSError("下载文件名无效")
        part = dest + ".part"
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        if have >= 200 * 1024 * 1024:
            try:
                os.remove(part)
            except OSError:
                pass
            have = 0
        headers = {"User-Agent": api.UA, "Referer": "https://music.163.com/"}
        if have:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(info["url"], headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                code = getattr(resp, "status", None) or resp.getcode()
                resume = bool(have and code == 206)
                written = have if resume else 0
                with open(part, "ab" if resume else "wb") as handle:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > 200 * 1024 * 1024:
                            raise OSError("下载文件过大")
                        handle.write(chunk)
        except Exception:
            # 网络中断时留下已写的部分，下次从断点继续。空文件才删。
            try:
                if os.path.isfile(part) and os.path.getsize(part) <= 0:
                    os.remove(part)
            except OSError:
                pass
            raise
        os.replace(part, dest)
        return dest, info.get("level") or level

    def _music_folder(self):
        return os.path.join(os.path.expanduser("~/Music"), "网易云音乐")

    def _music_folders(self):
        """现在写到 ~/Music。旧版写到 ~/音乐，同一台机器上两处都要认。"""
        folders = [self._music_folder(), os.path.join(os.path.expanduser("~"), "音乐", "网易云音乐")]
        seen = []
        for folder in folders:
            real = os.path.realpath(folder)
            if real not in seen:
                seen.append(real)
        return seen

    def _in_music_folder(self, path):
        path = os.path.realpath(path or "")
        if not path or path.endswith(".part") or not os.path.isfile(path):
            return False
        return any(path.startswith(root + os.sep) for root in self._music_folders())

    def _download_file(self, item):
        """完成记录指向的真实文件。必须在下载目录里，不能是半截文件。"""
        if (item or {}).get("status") != "完成":
            return ""
        path = os.path.realpath((item or {}).get("path") or "")
        if not self._in_music_folder(path):
            return ""
        return path

    def _folder_audio(self):
        """下载目录里记录没有的音频。半截 .part 不算下完。"""
        found = []
        seen = set()
        for root in self._music_folders():
            if not os.path.isdir(root):
                continue
            try:
                names = os.listdir(root)
            except OSError:
                continue
            for name in sorted(names):
                if name.startswith(".") or name.endswith(".part"):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in (".mp3", ".flac", ".ogg", ".m4a", ".wav", ".aac"):
                    continue
                path = os.path.realpath(os.path.join(root, name))
                if path in seen or not self._in_music_folder(path):
                    continue
                seen.add(path)
                found.append(path)
        return found

    def _named_download(self, item):
        """记录还没有路径时，用「歌手 - 歌名」对上下载目录里已经下完的文件。"""
        song = item.get("song") if isinstance(item.get("song"), dict) else {}
        artist = song.get("artist") or ""
        name = song.get("name") or item.get("name") or ""
        if not name:
            return ""
        stem = f"{artist} - {name}" if artist else name
        stem = stem.replace("/", " ").replace("\\", " ").replace("\x00", "").strip(" .")
        if not stem:
            return ""
        for path in self._folder_audio():
            if os.path.splitext(os.path.basename(path))[0] == stem:
                return path
        return ""

    def _song_saved(self, song_id):
        return bool(AppBridge._local_download(self, {"songId": song_id}, ""))

    def _mark_downloaded(self):
        """歌单里已经有本机文件的歌，标成已下载。记录里没有编号的旧文件对不上，不乱标。"""
        saved = {
            str(item.get("songId") or "")
            for item in self._download_rows
            if item.get("songId") and self._local_download({"songId": item.get("songId")}, "")
        }
        updates = []
        for index, row in enumerate(self.songs._rows):
            flag = str(row.get("songId") or "") in saved
            if bool(row.get("saved")) != flag:
                updates.append((index, "saved", flag))
        if updates:
            self.songs.set_fields(updates)

    def _local_download(self, song, level):
        """同一首歌、同一音质的下载文件优先于播放缓存。音质对不上就继续走缓存或网络。"""
        song_id = str((song or {}).get("songId") or "")
        if not song_id:
            return ""
        # 已下载页里没有编号的旧文件，编号栏放的就是文件路径。
        direct = self._download_file({"status": "完成", "path": song_id})
        if direct:
            return direct
        for item in reversed(self._download_rows):
            if str(item.get("songId") or "") != song_id or item.get("status") != "完成":
                continue
            if level and item.get("level") and item.get("level") != level:
                continue
            path = self._download_file(item)
            if path:
                return path
        return ""

    def _playing_download(self):
        uri = urllib.parse.urlparse(str(getattr(self.player, "_uri", "") or ""))
        if uri.scheme != "file":
            return False
        path = os.path.realpath(urllib.request.url2pathname(uri.path))
        return self._in_music_folder(path)

    def _completed_download(self, song_id):
        song_id = str(song_id or "")
        if not song_id:
            return None
        direct = self._download_file({"status": "完成", "path": song_id})
        if direct:
            return {
                "name": os.path.splitext(os.path.basename(direct))[0],
                "status": "完成",
                "path": direct,
                "songId": "",
                "song": {},
            }, direct
        for item in reversed(self._download_rows):
            if str(item.get("songId") or "") != song_id or item.get("status") != "完成":
                continue
            path = self._local_download({"songId": song_id}, item.get("level") or "")
            if path:
                return item, path
        return None

    def _song_from_download(self, item):
        song = item.get("song") if isinstance(item.get("song"), dict) else {}
        song = dict(song or {})
        song["songId"] = str(song.get("songId") or item.get("songId") or "")
        song.setdefault("name", item.get("name") or "未命名")
        song.setdefault("playable", True)
        return song

    def _downloaded_songs(self):
        songs = []
        seen = set()
        for row in self._download_view():
            if row.get("group") != "已下载":
                continue
            key = str(row.get("songId") or "")
            if not key or key in seen:
                continue
            path = self._local_download({"songId": key}, "")
            if not path:
                continue
            seen.add(key)
            song = self._song_from_download({"songId": key, "name": row.get("name") or "", "path": path, "song": {}})
            if os.path.realpath(key) == path:
                song["songId"] = path
            songs.append(song)
        return songs

    @pyqtSlot(str)
    def playDownload(self, song_id):
        found = self._completed_download(song_id)
        if not found:
            self.statusChanged.emit("本地文件不在了，请重新下载")
            return
        item, path = found
        song = self._song_from_download(item)
        if not song.get("songId"):
            song["songId"] = path
            song["name"] = os.path.splitext(os.path.basename(path))[0]
        others = self._downloaded_songs() or [song]
        self._queue = others
        self._queue_source = "downloads"
        self._queue_title = "下载管理"
        self.queue.replace(self._queue)
        index = next((i for i, row in enumerate(self._queue) if str(row.get("songId")) == str(song.get("songId"))), 0)
        if item.get("level"):
            self._quality = item["level"]
        self._play_index(index)

    @pyqtSlot(str)
    def queueDownloadNext(self, song_id):
        found = self._completed_download(song_id)
        if not found:
            self.statusChanged.emit("本地文件不在了，请重新下载")
            return
        item, path = found
        song = self._song_from_download(item)
        if not song.get("songId"):
            song["songId"] = path
            song["name"] = os.path.splitext(os.path.basename(path))[0]
        if self._refuse_unplayable(song):
            return
        if item.get("level"):
            self._quality = item["level"]
        self._place_next(song)
        self.queue.replace(self._queue)
        self.statusChanged.emit(f"下一首播放 {song.get('name') or ''}")

    @pyqtSlot()
    def pauseDownloads(self):
        with self._download_lock:
            self._download_paused = True
            current = any(item.get("status") == "下载中" for item in self._download_rows)
        self._post("downloads", self._download_view())
        self._post("status", "当前这首下完后暂停" if current else "已暂停下载")

    @pyqtSlot()
    def resumeDownloads(self):
        with self._download_lock:
            self._download_paused = False
        self._ensure_download_worker()
        self._post("downloads", self._download_view())
        self._post("status", "继续下载")

    @pyqtSlot(result=bool)
    def downloadsPaused(self):
        return bool(self._download_paused)

    @pyqtSlot(str)
    def retryDownload(self, song_id):
        song_id = str(song_id or "")
        if not song_id:
            return
        if not self._require_login("下载"):
            return
        with self._download_lock:
            item = next((
                row for row in reversed(self._download_rows)
                if str(row.get("songId") or "") == song_id and str(row.get("status") or "").startswith("失败")
            ), None)
            if item is None or not item.get("song"):
                self.statusChanged.emit("这条失败记录没法重新下载")
                return
            if any(
                str(row.get("songId") or "") == song_id and row.get("status") in ("等待", "下载中")
                for row in self._download_rows
            ):
                self.statusChanged.emit("这首已经在下载队列里")
                return
            item["status"] = "等待"
            item["path"] = ""
            self._download_paused = False
            self._save_downloads()
        self._post("downloads", self._download_view())
        self._post("status", f"重新下载：{item.get('name') or ''}")
        self._ensure_download_worker()

    @pyqtSlot()
    def retryFailedDownloads(self):
        if not self._require_login("下载"):
            return
        added = 0
        with self._download_lock:
            waiting = {
                str(row.get("songId") or "")
                for row in self._download_rows
                if row.get("status") in ("等待", "下载中")
            }
            for item in self._download_rows:
                song_id = str(item.get("songId") or "")
                if not song_id or not str(item.get("status") or "").startswith("失败") or not item.get("song"):
                    continue
                if song_id in waiting:
                    continue
                item["status"] = "等待"
                item["path"] = ""
                waiting.add(song_id)
                added += 1
            if added:
                self._download_paused = False
                self._save_downloads()
        if added == 0:
            self.statusChanged.emit("没有可以重新下载的歌曲")
            return
        self._post("downloads", self._download_view())
        self._post("status", f"重新下载 {added} 首")
        self._ensure_download_worker()

    def _save_state(self):
        songs = [song for song in self._queue if song.get("songId")]
        if not songs:
            return
        pos, dur = self.player.position()
        # 播放器还没出声时位置是 0。恢复后的进度在 _resume_at，不能用 0 把它盖掉。
        if not pos:
            pos = int(getattr(self, "_resume_at", 0) or 0)
        payload = {
            "index": self._index,
            "position": int(pos or 0),
            "duration": int(dur or (self._song or {}).get("duration") or 0),
            "quality": self._quality,
            "mode": self._mode,
            "title": self._queue_title or self._page_title or "当前播放",
            "source": self._queue_source or "",
            "page": self._page,
            "pageTitle": self._page_title,
            "listId": self._list_id,
            "songs": songs,
        }
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = STATE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp, STATE_PATH)
        except OSError:
            pass

    def _restore_state(self):
        try:
            payload = json.loads(open(STATE_PATH, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            return
        songs = [song for song in payload.get("songs") or [] if song.get("songId")]
        if not songs:
            return
        index = payload.get("index") if isinstance(payload.get("index"), int) else 0
        index = min(max(index, 0), len(songs) - 1)
        # 只在这次运行里记住页面。退出再打开回到首页，不恢复上次的歌单或搜索页。
        page_title = payload.get("pageTitle") or payload.get("title") or "当前播放"
        self._queue = songs
        self._queue_title = payload.get("title") or page_title
        self._queue_source = str(payload.get("source") or "")
        self.queue.replace(songs)
        self._index = index
        self._song = songs[index]
        self._quality = payload.get("quality") or self._quality
        if payload.get("mode") in MODES:
            self._mode = payload["mode"]
            self.modeChanged.emit(MODE_LABEL[self._mode])
        position = int(payload.get("position") or 0)
        duration = int(payload.get("duration") or self._song.get("duration") or 0)
        self.player._position = position
        self.player._anchor = position
        self.player._duration = duration
        self.player._want = "paused"
        self._resume_at = position
        song_id = str(self._song.get("songId") or "")
        self.currentSongChanged.emit(song_id)
        # 进度要在歌曲前面到界面。换歌会把进度条清成 0，后到的进度才能留住。
        self.clockChanged.emit(f"{position},{duration}")
        self.songChanged.emit("\n".join((
            song_id, self._song.get("name") or "", self._song.get("artist") or "",
            self._song.get("cover") or "", str(duration), self._artist_payload(self._song),
            self._song.get("album") or "",
        )))
        if self._page == "lyric":
            self._page_title = self._song.get("name") or "歌词"
            self.pageChanged.emit("lyric", self._page_title)
        self.clockChanged.emit(f"{position},{duration}")
        self.likedChanged.emit(song_id in self._liked)
        self._ui_playing = False
        self._clock_pos = position
        self.stateChanged.emit("paused")
        self.qualityChanged.emit(api.QUALITY_LABEL.get(self._quality, self._quality))
        where = f" · {self._queue_title}" if self._queue_title else ""
        self.statusChanged.emit(f"已恢复 {self._song.get('name') or ''}{where} · 已暂停")
        if self._song.get("cover"):
            threading.Thread(target=self._cache_cover, args=(self._song["cover"], 46), daemon=True).start()
        threading.Thread(target=self._restore_lyric, args=(self._song["songId"],), daemon=True).start()
        threading.Thread(target=self._load_qualities, args=(self._token, self._song["songId"], None), daemon=True).start()

    def _restore_lyric(self, song_id):
        try:
            original, translated, words = api.lyric_pair(song_id, cookie=self._cookie)
        except api.ApiError:
            return
        if str((self._song or {}).get("songId")) != str(song_id):
            return
        lines = api.merge_lrc(original, translated)
        self._lyrics = lines
        self._lyric_words = words
        self._publish_track()
        self._publish_desk_lyric(int(getattr(self, "_resume_at", 0) or 0))
        self._post("lyric", "\n".join(f"{ms}\t{text}" for ms, text in lines) or "0\t这首歌没有歌词")

    @pyqtSlot()
    def hideToTray(self):
        self._save_state()
        self.statusChanged.emit("已在后台运行。托盘左键打开，右键退出。")

    @pyqtSlot()
    def stop(self):
        self._alive = False
        self._login["done"] = True
        # 先记下进度再停管道。停掉之后位置是 0，再保存就会把上次听到的地方盖掉。
        self._save_state()
        self._close_desk_lyric()
        self.player.stop()  # 退出时已在界面线程

    def _queue_cache(self, token, song_id, level, ext, url):
        """记下要缓存的这一首。播放和暂停都接着下，换歌才停掉上一首。"""
        if not allowed_uri(url):
            return
        old = self._cache_job
        if old and old.get("cancel") is not None:
            old["cancel"].set()
        self._cache_job = {
            "token": token,
            "song_id": str(song_id),
            "level": level,
            "ext": ext,
            "url": url,
            "tries": 0,
            "cancel": threading.Event(),
            "progress": {"bytes": 0, "total": 0, "mark": 0},
        }
        self._cache_wake.set()
        if self._cache_worker_on:
            return
        self._cache_worker_on = True
        threading.Thread(target=self._cache_worker, daemon=True).start()

    def _network_up(self):
        """探测网易云本身。能连上（哪怕返回错误页）说明不是本机网络断了。"""
        req = urllib.request.Request(
            "https://music.163.com/",
            method="HEAD",
            headers={"User-Agent": "netease-music-linux"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status < 500
        except urllib.error.HTTPError as exc:
            return exc.code < 500
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            return False

    def _cache_worker(self):
        while self._alive:
            job = self._cache_job
            if not job or (job.get("cancel") is not None and job["cancel"].is_set()):
                if job and self._cache_job is job:
                    self._cache_job = None
                self._cache_wake.wait(1)
                self._cache_wake.clear()
                continue
            if self._cache_net_down:
                if self._network_up():
                    self._cache_net_down = False
                    if job.get("token") == self._token:
                        self._post("status", "网络已恢复，继续缓存")
                else:
                    self._cache_wake.wait(3)
                    self._cache_wake.clear()
                    continue
            if cache_lookup(job["song_id"], job["level"]):
                if self._cache_job is job:
                    self._cache_job = None
                continue
            try:
                cache_store(
                    job["song_id"], job["level"], job["ext"], job["url"],
                    cancel=job["cancel"], progress=job["progress"],
                )
            except OSError as exc:
                if job.get("cancel") is not None and job["cancel"].is_set():
                    continue
                text = str(exc)
                if "已有缓存" in text:
                    time.sleep(0.4)
                    continue
                if cache_network_down(exc):
                    self._cache_net_down = True
                    LOG.info("cache network id=%s %s", job["song_id"], text)
                    if job.get("token") == self._token:
                        self._post("status", "网络不可用，缓存已暂停")
                    continue
                job["tries"] += 1
                LOG.info("cache failed id=%s %s", job["song_id"], text)
                if job["tries"] < 3:
                    time.sleep(2)
                    continue
                if self._cache_job is job:
                    self._cache_job = None
                if job.get("token") == self._token:
                    self._post("status", "缓存失败，下次播放再试")
                continue
            LOG.info("cache stored id=%s level=%s", job["song_id"], job["level"])
            if self._cache_job is job:
                self._cache_job = None
            if job.get("token") == self._token:
                self._post("status", "已缓存到本机，下次播放不再拉流")
                self._prefetch_next(job["token"])

    def _prefetch_next(self, token):
        """当前这首已经进缓存。下一首按同样音质先下好，切过去时不用再等。"""
        if token != self._token or not self._queue:
            return
        index = self._index + 1
        if not (0 <= index < len(self._queue)):
            if self._mode == "loop" and len(self._queue) > 1:
                index = 0
            else:
                return
        song = self._queue[index]
        if not song or song.get("playable") is False or not song.get("songId"):
            return
        if str(song.get("songId")) == str((self._song or {}).get("songId") or ""):
            return
        self._prefetch_job = {"token": token, "song": dict(song), "level": self._quality}
        self._prefetch_wake.set()
        if self._prefetch_on:
            return
        self._prefetch_on = True
        threading.Thread(target=self._prefetch_worker, daemon=True).start()

    def _prefetch_worker(self):
        while self._alive:
            job = self._prefetch_job
            if not job:
                self._prefetch_wake.wait(1)
                self._prefetch_wake.clear()
                continue
            self._prefetch_job = None
            token = job.get("token")
            song = job.get("song") or {}
            level = job.get("level") or self._quality
            song_id = str(song.get("songId") or "")
            if token != self._token or not song_id:
                continue
            if self._local_download(song, level) or cache_lookup(song_id, level):
                continue
            try:
                info = api.song_url(song_id, level=level, cookie=self._cookie)
            except api.ApiError as exc:
                LOG.info("prefetch url failed id=%s %s", song_id, exc)
                continue
            if token != self._token or not info or not allowed_uri(info.get("url")):
                continue
            actual = info.get("level") or level
            if self._local_download(song, actual) or cache_lookup(song_id, actual):
                continue
            # 用户已经切走，或当前这首还在缓存，就先不抢带宽。
            if token != self._token or self._cache_job:
                continue
            try:
                cache_store(song_id, actual, info.get("type") or "mp3", info["url"])
            except OSError as exc:
                LOG.info("prefetch failed id=%s %s", song_id, exc)
                continue
            if token != self._token:
                continue
            LOG.info("prefetch stored id=%s level=%s", song_id, actual)
            self._post("status", f"已缓存下一首：{song.get('name') or ''}")

    def _share_url(self):
        song = self._song or {}
        if not song.get("songId"):
            return ""
        return f"https://music.163.com/song?id={song['songId']}"

    @pyqtSlot()
    def sharePage(self):
        if self._page == "playlist" and self._list_id:
            url = f"https://music.163.com/playlist?id={self._list_id}"
            label = "歌单"
        elif self._page == "album" and self._album_id:
            url = f"https://music.163.com/album?id={self._album_id}"
            label = "专辑"
        else:
            self.statusChanged.emit("当前页面没有可分享的内容")
            return
        try:
            from PyQt5.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(url)
        except Exception:
            self.statusChanged.emit("复制失败")
            return
        self.statusChanged.emit(label + "链接已复制")

    @pyqtSlot()
    def copyShare(self):
        url = self._share_url()
        if not url:
            self.statusChanged.emit("还没有正在播放的歌曲")
            return
        try:
            from PyQt5.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(url)
        except Exception:
            self.statusChanged.emit("复制失败")
            return
        self.statusChanged.emit("歌曲链接已复制")

    @pyqtSlot()
    def cycleRate(self):
        rates = (1.0, 1.25, 1.5, 0.75)
        self._rate = rates[(rates.index(self._rate) + 1) % len(rates)] if self._rate in rates else 1.0
        if self.player.set_rate(self._rate):
            self.rateChanged.emit(self._rate)
            self.statusChanged.emit(f"播放倍速 {self._rate:g}x")
        else:
            self.statusChanged.emit("当前还不能切换倍速")

    @pyqtSlot()
    def openCurrentArtist(self):
        song = self._song or {}
        if song.get("artistId"):
            self.openArtist(str(song["artistId"]), song.get("artist") or "歌手")

    @pyqtSlot()
    def openCurrentAlbum(self):
        song = self._song or {}
        if song.get("albumId"):
            self.openAlbum(str(song["albumId"]), song.get("album") or "专辑")

    @pyqtSlot()
    def openLyric(self):
        self._show("lyric", (self._song or {}).get("name") or "歌词")

    def _on_player_error(self, message):
        text = str(message or "播放失败")
        LOG.info("player error %s", text)
        self.statusChanged.emit(text)
        # 还没出声的失败留在这一首。只有已经播到某个位置才切，避免一加载就跳歌。
        if self._queue and self._song and self.player.heard() > 0:
            self.statusChanged.emit(f"{text}，切换下一首")
            self._loading_pos = False
            self.next()

    def _on_player_state(self, state):
        if state == "buffering":
            # 按钮仍是暂停键。进度和歌词先停住，数据回来再接着走。
            self._loading_pos = True
            self._publish_desk_lyric(self.player.position()[0])
            self.stateChanged.emit("buffering")
            self.statusChanged.emit("正在缓冲…")
            LOG.info("player state=buffering pos=%s", self.player.position()[0])
            return
        self._ui_playing = state == "playing"
        self.stateChanged.emit(state)
        # 桌面歌词和界面歌词都看这个状态。只在按钮上改，暂停和真正出声会对不齐。
        self._publish_desk_lyric(self.player.position()[0])
        LOG.info("player state=%s pos=%s", state, self.player.position()[0])

    def _on_position(self, pos, dur):
        if self.player.want() != "playing":
            return
        target = self.player._seek_target
        # 定位没落地，或时长还是 0，都先别把界面标成已经在播。
        if target is not None and (not dur or abs(pos - target) > 1500):
            return
        self._loading_pos = False
        # 还没出声时位置是 0。这时候发进度，界面会拿整首时长自己往前走。
        if pos <= 0 or self.player._buffering:
            return
        # 进度贴到时长上时先不往外发。开播瞬间的误报会让界面以为这首已经唱完。
        if dur and pos >= dur - 1500 and pos < 8000:
            return
        # 缓冲抖动会让位置在两句歌词之间来回跳。只接受往前走，或用户拖回开头。
        if self._clock_pos and pos + 1500 < self._clock_pos and pos > 8000:
            return
        self._clock_pos = pos
        total = dur or int((self._song or {}).get("duration") or 0)
        self.clockChanged.emit(f"{pos},{total}")
        if self._desk_lyric_alive():
            self._publish_desk_lyric(pos)

    def _on_ended(self):
        if getattr(self.player, "_held_pause", False):
            return
        heard = self.player.heard() or self.player.position()[0]
        song = self._song or {}
        duration = int(song.get("duration") or 0)
        # 本机缓存读完了，但还没到这首歌的时长。文件停在这里，和网络卡住是同一件事。
        # 重开这首会从缓存开头再播一遍。留给卡住检测，大约 10 秒后切下一首。
        if duration and heard < duration - 3000 and self._cache_ended_early(song):
            LOG.info("cache short id=%s heard=%s duration=%s", song.get("songId"), heard, duration)
            self.statusChanged.emit("缓存停住了，等待切换下一首")
            # 文件结束后管道不再是播放中，位置也会变成 0。卡住检测只认这个记下的进度。
            self._cache_hold = heard
            self._publish_desk_lyric(heard)
            return
        self._step(1)

    def _cache_ended_early(self, song):
        """正在播的是播放缓存里的文件，而且在整首结束前就读完了。"""
        uri = urllib.parse.urlparse(str(getattr(self.player, "_uri", "") or ""))
        if uri.scheme != "file":
            return False
        real = os.path.realpath(urllib.request.url2pathname(uri.path))
        folder = os.path.realpath(os.path.join(os.path.expanduser("~/.cache"), "netease-cloud-music", "playback"))
        return real.startswith(folder + os.sep) and os.path.isfile(real)

    def _emit_clock(self):
        if self.player.want() != "playing":
            return
        if self.player is None:
            return
        if self._loading_pos or self.player._buffering:
            return
        pos, dur = self.player.position()
        if pos <= 0:
            return
        self.clockChanged.emit(f"{pos},{dur or int((self._song or {}).get('duration') or 0)}")
        # 歌词窗口自己按时间切句。这里只偶尔对一次进度，避免暂停和拖动之后越走越偏。
        if self._desk_lyric_alive() and time.time() - getattr(self, "_lyric_sync_at", 0) >= 2.5:
            self._lyric_sync_at = time.time()
            self._publish_desk_lyric(pos)
