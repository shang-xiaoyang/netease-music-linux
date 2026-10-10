# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""把现有接口和播放后端交给 QML。QML 只发意图，不直接请求网易。"""

import json
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
from qt.paths import COOKIE_PATH, DATA_DIR, LYRIC_PATH, LYRIC_STATE_PATH, RECENT_PATH, STATE_PATH, VOLUME_PATH, player_script
from qt.playback_cache import lookup as cache_lookup
from qt.playback_cache import store as cache_store
from qt.player_backend import PlayerBackend, allowed_uri

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
    coverChanged = pyqtSignal(str)
    likedChanged = pyqtSignal(bool)
    lyricChanged = pyqtSignal(str)
    deskLyricChanged = pyqtSignal(bool)
    detailChanged = pyqtSignal(str)
    loginKeyChanged = pyqtSignal(str)
    qualitiesChanged = pyqtSignal(str)
    _uiReady = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.player = PlayerBackend()
        self.player.stateChanged.connect(self.stateChanged)
        self.player.positionChanged.connect(self._on_position)
        self.player.errorChanged.connect(self.statusChanged)
        self.player.ended.connect(self._on_ended)
        self.songs = DictListModel(("songId", "name", "artist", "artistId", "artists", "album", "albumId", "cover", "local", "duration", "vip"))
        self.queue = DictListModel(("songId", "name", "artist", "cover", "duration"))
        self.nav = DictListModel(("key", "label", "kind", "section", "cover", "local"))
        self.cards = DictListModel(("itemId", "name", "cover", "local", "count", "kind"))
        self.collects = DictListModel(("itemId", "name", "cover", "local", "count", "kind"))
        self.albums = DictListModel(("itemId", "name", "cover", "local", "publish"))
        self.comments = DictListModel(("nickname", "userId", "avatar", "local", "content", "when", "liked", "hot"))
        self.downloads = DictListModel(("name", "status", "quality", "path"))
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
        self._history = []
        self._detail_text = ""
        self._detail_cover = ""
        self._loading_pos = False
        self._volume = self._saved_volume()
        self._pulse_cache = (0, None)
        self._liked = set()
        self._lyrics = []
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
        self._download_rows = []
        self._download_worker = None
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
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._emit_clock)
        self._clock.start()
        self._uiReady.connect(self._drain_ui, Qt.QueuedConnection)
        self._fill_nav()
        self.accountChanged.emit("登录")
        self.qualityChanged.emit(api.QUALITY_LABEL.get(self._quality, self._quality))
        threading.Thread(target=self._boot, daemon=True).start()

    def start_desktop(self):
        """窗口已经起来。播放栏在界面线程立刻恢复，不跟账号和推荐页抢。"""
        self._restore_state()
        if self._desk_lyric_wanted():
            self._launch_desk_lyric()

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
            elif kind == "albums":
                self._apply_albums(payload)
            elif kind == "detail":
                self._apply_detail(*payload)
            elif kind == "account":
                self.accountChanged.emit(payload)
            elif kind == "status":
                self.statusChanged.emit(payload)
            elif kind == "comments":
                self.comments.replace(payload)
            elif kind == "downloads":
                self.downloads.replace(payload)
            elif kind == "login":
                self.loginKeyChanged.emit(payload)
            elif kind == "qualities":
                self.qualitiesChanged.emit(payload)
            elif kind == "lyric":
                self.lyricChanged.emit(payload)
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
            if target == "comment":
                self._paint_local(self.comments, "avatar", batch)
            if target == "detail" and batch:
                self._detail_cover = batch[-1][1]
                self.detailChanged.emit("cover\n" + self._detail_cover)

    def _paint_local(self, model, field, batch):
        found = {}
        for url, path, _target in batch:
            found[url] = path
        for index, row in enumerate(model._rows):
            path = found.get(row.get(field))
            if path:
                model.set_field(index, "local", path)

    def _fill_nav(self):
        blank = {"cover": "", "local": ""}
        rows = [
            {"key": "home", "label": "推荐", "kind": "home", "section": "", **blank},
            {"key": "discover", "label": "热门歌单", "kind": "discover", "section": "", **blank},
        ]
        rows.extend(
            {"key": str(cid), "label": name, "kind": "chart", "section": "", **blank}
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
        self._queue.pop(row)
        insert_at = min(len(self._queue), self._index + 1)
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
            rows = [item for index, item in enumerate(self.songs._rows) if index != row]
            self._post_songs(rows, f"已从当前歌单移除 {song.get('name') or ''}", max(0, self._list_total - 1), self._list_title)
        else:
            self._post("status", f"已从当前歌单移除 {song.get('name') or ''}")

    @pyqtSlot(int)
    def removeFromQueue(self, row):
        if not (0 <= row < len(self._queue)):
            return
        song = self._queue.pop(row)
        if row < self._index:
            self._index -= 1
        elif row == self._index:
            self._index = min(self._index, len(self._queue) - 1)
        self.queue.replace(self._queue)
        self.statusChanged.emit(f"已从播放列表移除 {song.get('name') or ''}")

    @staticmethod
    def _playlist_nav(items):
        return [
            {
                "key": str(item.get("id") or ""),
                "label": item.get("name") or "歌单",
                "kind": "playlist",
                "section": "",
                "cover": item.get("cover") or "",
                "local": "",
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

    def _show(self, name, title):
        if (self._page, getattr(self, "_page_title", "")) != (name, title):
            self._history.append(self._capture())
            self._history = self._history[-8:]
        self._page = name
        self._page_title = title
        self.pageChanged.emit(name, title)

    def _restore_frame(self, frame):
        self._list_token += 1
        self._list_more = False
        self._page = frame.get("page") or "home"
        self._page_title = frame.get("title") or "推荐"
        self._list_id = frame.get("list_id") or ""
        self._list_total = int(frame.get("list_total") or 0)
        self._list_offset = int(frame.get("list_offset") or 0)
        self._list_title = frame.get("list_title") or ""
        self._list_refs = frame.get("list_refs")
        self._detail_text = frame.get("detail") or ""
        self._detail_cover = frame.get("cover") or ""
        self.songs.replace(frame.get("songs") or [])
        self.albums.replace(frame.get("albums") or [])
        self.detailChanged.emit(self._detail_text or "\n")
        if self._detail_cover:
            self.detailChanged.emit("cover\n" + self._detail_cover)
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
        self._page = "home"
        self._page_title = "推荐"
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
            })
        for item in playlists:
            rows.append({
                "itemId": str(item.get("id") or ""),
                "name": item.get("name") or "歌单",
                "cover": item.get("cover") or "",
                "local": "",
                "count": int(item.get("count") or 0),
                "kind": "playlist",
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
        self._show("list", name or "歌单")
        self._begin_list()
        self._list_id = str(playlist_id)
        self.songs.replace([])
        threading.Thread(target=self._load_playlist, args=(playlist_id, name, self._list_token), daemon=True).start()

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
        rows = self._song_rows(songs)
        shown = len(songs)
        self._post("songs", (
            rows, False, token, shown,
            f"{title} · {shown}/{total} 首" if total > shown else f"{title} · {total} 首",
            total, title, page.get("refs") or [],
        ))
        self._cache_song_covers(rows)

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
        self.statusChanged.emit(status)

    def _cache_song_covers(self, rows):
        self._queue_covers((row.get("cover") for row in rows), 36, "songrow")

    def _queue_covers(self, urls, size, kind):
        pending = [url for url in urls if url]
        if not pending:
            return
        workers = 3 if len(pending) > 8 else 1

        def run(chunk):
            ready = []
            for url in chunk:
                path = self._cache_cover(url, size, kind, post=False)
                if path:
                    ready.append((url, path, kind))
                if len(ready) >= 6:
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
        self._post("downloads", list(self._download_rows))

    @pyqtSlot(str)
    def search(self, keyword):
        text = (keyword or "").strip()
        if not text:
            return
        self._show("list", f"搜索「{text}」")
        token = self._begin_list()
        self.songs.replace([])
        threading.Thread(target=self._search, args=(text, token), daemon=True).start()

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
            }
            for item in playlists
        ], f"热门歌单 {len(playlists)} 个"))
        for item in playlists:
            if item.get("cover"):
                threading.Thread(target=self._cache_cover, args=(item["cover"], 120, "card"), daemon=True).start()

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

    @pyqtSlot(str, str)
    def openArtist(self, artist_id, name):
        artist_id = str(artist_id or "").strip()
        if not artist_id or artist_id in ("0", "None"):
            self.statusChanged.emit(f"{name or '这个歌手'} 没有可打开的主页")
            return
        self._show("artist", name or "歌手")
        token = self._begin_list()
        self.songs.replace([])
        self.albums.replace([])
        threading.Thread(target=self._load_artist, args=(artist_id, token), daemon=True).start()

    def _load_artist(self, artist_id, token):
        try:
            data = api.artist_home(artist_id, cookie=self._cookie)
        except api.ApiError as exc:
            if token == self._list_token:
                self.statusChanged.emit(str(exc))
            return
        if token != self._list_token:
            return
        brief = (data.get("brief") or "").strip()
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
        self._post("albums", [
            {
                "itemId": str(item.get("id") or ""),
                "name": item.get("name") or "专辑",
                "cover": item.get("cover") or "",
                "publish": item.get("publish") or "",
            }
            for item in data.get("albums") or []
        ])
        for item in data.get("albums") or []:
            if item.get("cover"):
                threading.Thread(target=self._cache_cover, args=(item["cover"], 96, "album"), daemon=True).start()
        songs = data.get("songs") or []
        rows = self._song_rows(songs)
        self._post_songs(
            rows,
            f"{data.get('musicCount') or 0} 首歌曲 · {data.get('albumCount') or 0} 张专辑",
            len(songs),
            data.get("name") or "歌手",
            token=token,
        )
        self._cache_song_covers(rows)

    @pyqtSlot(str, str)
    def openAlbum(self, album_id, name):
        if not album_id:
            return
        self._show("album", name or "专辑")
        token = self._begin_list()
        self.songs.replace([])
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
        self._post("detail", (
            "album",
            data.get("name") or "专辑",
            artist.get("name") or "",
            " · ".join(pieces) + ("\n" + desc if desc else ""),
            data.get("cover") or "",
        ))
        rows = self._song_rows(songs)
        self._post_songs(rows, f"{len(songs)} 首", len(songs), data.get("name") or "专辑", token=token)
        self._cache_song_covers(rows)

    @pyqtSlot(object)
    def _apply_albums(self, rows):
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

    @staticmethod
    def _song_rows(songs):
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

    @pyqtSlot(int)
    def playRow(self, row):
        song = self.songs.get(row)
        if not song or not song.get("songId"):
            return
        self._queue = [dict(item) for item in self.songs._rows if item.get("songId")]
        self._queue_source = self._list_id
        self._queue_title = self._page_title or "当前播放"
        self.queue.replace(self._queue)
        index = next((i for i, item in enumerate(self._queue) if item.get("songId") == song.get("songId")), 0)
        self._play_index(index)

    @pyqtSlot(int)
    def playQueue(self, row):
        self._play_index(row)

    def _play_index(self, index):
        if not (0 <= index < len(self._queue)):
            return
        song = self._queue[index]
        self._index = index
        self._token += 1
        token = self._token
        self._song = song
        self._loading_pos = True
        keep = int(getattr(self, "_resume_at", 0) or 0)
        self.player.begin_switch(keep)
        self.songChanged.emit("\n".join((
            song["songId"], song["name"], song.get("artist") or "", song.get("cover") or "",
            str(int(song.get("duration") or 0)), self._artist_payload(song), song.get("album") or "",
        )))
        if self._page == "lyric":
            self._page_title = song.get("name") or "歌词"
            self.pageChanged.emit("lyric", self._page_title)
        self.currentSongChanged.emit(str(song.get("songId") or ""))
        self.likedChanged.emit(str(song.get("songId")) in self._liked)
        kept = int(getattr(self, "_resume_at", 0) or 0)
        self.clockChanged.emit(f"{kept},{int(song.get('duration') or 0)}")
        self._lyrics = []
        self.lyricChanged.emit("")
        self._publish_desk_lyric(0, song.get("name") or "歌词加载中…")
        self.statusChanged.emit(f"正在获取{api.QUALITY_LABEL.get(self._quality, '')}…")
        threading.Thread(target=self._start, args=(token, song), daemon=True).start()

    def _start(self, token, song):
        try:
            info = api.song_url(song["songId"], level=self._quality, cookie=self._cookie)
            original, translated = api.lyric_pair(song["songId"], cookie=self._cookie)
        except api.ApiError as exc:
            if token == self._token:
                self.statusChanged.emit(str(exc))
                self._loading_pos = False
            return
        if token != self._token:
            return
        if not info or not allowed_uri(info.get("url")):
            self._loading_pos = False
            self.statusChanged.emit("没有可播放地址")
            return
        cached = cache_lookup(song["songId"], info.get("level") or self._quality)
        play_url = urllib.parse.urljoin("file:", urllib.request.pathname2url(cached)) if cached else info["url"]
        self._post("play", play_url)
        resume_at = getattr(self, "_resume_at", 0)
        self._resume_at = 0
        if resume_at > 1500:
            threading.Timer(0.7, lambda: self._post("seek", resume_at)).start()
        self._loading_pos = False
        if not cached:
            threading.Thread(
                target=self._store_cache,
                args=(token, song["songId"], info.get("level") or self._quality, info.get("type") or "mp3", info["url"]),
                daemon=True,
            ).start()
        self._apply_volume()
        if song.get("cover"):
            threading.Thread(target=self._cache_cover, args=(song["cover"], 240), daemon=True).start()
        level = info.get("level") or self._quality
        self.qualityChanged.emit(api.QUALITY_LABEL.get(level, level))
        lines = api.merge_lrc(original, translated)
        self._lyrics = lines
        self._post("lyric", "\n".join(f"{ms}\t{text}" for ms, text in lines) or "0\t这首歌没有歌词")
        self._publish_desk_lyric(0)
        label = api.QUALITY_LABEL.get(level, level)
        note = "，已换成这首歌能播的档" if level != self._quality else ""
        self.statusChanged.emit(f"正在播放 · {label}{note}")
        threading.Thread(target=self._load_qualities, args=(token, song["songId"], info), daemon=True).start()

    @pyqtSlot(int)
    def playNext(self, row):
        song = self.songs.get(row)
        if not song or not song.get("songId"):
            return
        if not self._queue:
            self._queue = [song]
            self._index = 0
            self.queue.replace(self._queue)
            self._play_index(0)
            return
        insert_at = min(len(self._queue), self._index + 1)
        self._queue.insert(insert_at, song)
        self.queue.replace(self._queue)
        self.statusChanged.emit(f"下一首播放 {song.get('name') or ''}")

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
        if self._song and str(self._song.get("songId")) == str(song["songId"]):
            self.likedChanged.emit(like)

    def row_liked(self, row):
        song = self.songs.get(row)
        return bool(song) and str(song.get("songId")) in self._liked

    @pyqtSlot()
    def toggle(self):
        if self.player.want() == "playing":
            self._post("pause", None)
            self.statusChanged.emit("已暂停")
            return
        if self._song and self.player.has_source():
            self._post("resume", None)
            self.statusChanged.emit("继续播放")
            return
        if self._song:
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
            choices = [i for i in range(len(self._queue)) if i != self._index]
            index = random.choice(choices) if choices else 0
        elif self._mode == "single" and step > 0:
            index = self._index
        else:
            index = self._index + step
            if not (0 <= index < len(self._queue)):
                if self._mode == "order":
                    self._post("stop", None)
                    self.statusChanged.emit("列表播放结束")
                    return
                index %= len(self._queue)
        self._play_index(index)

    @pyqtSlot(int)
    def seek(self, ms):
        self._post("seek", int(ms))

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

    def _pulse_stream(self):
        cached_at, cached = self._pulse_cache
        if time.time() - cached_at < 3:
            return cached
        try:
            out = subprocess.check_output(["pactl", "list", "sink-inputs"], stderr=subprocess.DEVNULL, timeout=2, text=True)
        except (OSError, subprocess.SubprocessError):
            return None
        current = matched = None
        for line in out.splitlines():
            head = line.strip()
            if head.startswith("Sink Input #"):
                current = head.split("#", 1)[1].strip()
            elif current and "application.process.id" in head and f'= "{os.getpid()}"' in head:
                matched = current
        self._pulse_cache = (time.time(), matched)
        return matched

    def _apply_volume(self):
        self._post("volume", 1.0)
        stream = self._pulse_stream()
        if not stream:
            return
        percent = f"{int(round(self._volume * 100))}%"
        try:
            subprocess.check_call(
                ["pactl", "set-sink-input-volume", stream, percent],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            self.statusChanged.emit("播放音量没有改成功")

    def _load_qualities(self, token, song_id, known):
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

    def _cache_cover(self, url, size, kind="song", post=True):
        if not self._alive or not url:
            return ""
        try:
            from player import cover_cache_path, _https_media_url
            import urllib.parse
            import urllib.request
            path = cover_cache_path(url, size)
            if not os.path.exists(path) or os.path.getsize(path) < 32:
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
                tmp = path + ".part"
                with open(tmp, "wb") as handle:
                    handle.write(data)
                os.replace(tmp, path)
            if not self._alive:
                return ""
            if not post:
                return path
            if kind == "song":
                self.coverChanged.emit(path)
            elif kind in ("card", "nav", "songrow", "collect", "detail", "album", "comment"):
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

    def _publish_desk_lyric(self, elapsed=0, line=None):
        if line is None:
            text, start, end = self._lyric_span(elapsed)
        else:
            text, start, end = line, 0, 1
        playing = self.player.want() == "playing"
        payload = {
            "line": text,
            "start": int(start),
            "end": int(end),
            "position": int(elapsed),
            "at": time.time(),
            "playing": playing,
        }
        previous = self._desk_lyric_payload
        if (
            previous
            and previous.get("line") == text
            and previous.get("playing") == playing
            and abs(previous.get("position", 0) - int(elapsed)) < 250
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
        threading.Thread(target=self._load_user, args=(user_id, name), daemon=True).start()

    def _load_user(self, user_id, name):
        try:
            data = api.user_detail(user_id, cookie=self._cookie)
        except api.ApiError as exc:
            self._post("status", str(exc))
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

    @pyqtSlot(int)
    def enqueueDownload(self, row):
        if not self._require_login("下载"):
            return
        song = self._song if row < 0 else self.songs.get(row)
        if not song or not song.get("songId"):
            self.statusChanged.emit("没有可下载的歌曲")
            return
        item = {
            "name": song.get("name") or "",
            "status": "等待",
            "quality": api.QUALITY_LABEL.get(self._quality, self._quality),
            "path": "",
            "song": dict(song),
            "level": self._quality,
        }
        self._download_rows.append(item)
        self._post("downloads", self._download_view())
        self._post("status", f"已加入下载：{item['name']} · {item['quality']}")
        if self._download_worker is None or not self._download_worker.is_alive():
            self._download_worker = threading.Thread(target=self._download_loop, daemon=True)
            self._download_worker.start()

    def _download_view(self):
        return [
            {"name": item["name"], "status": item["status"], "quality": item["quality"], "path": os.path.basename(item.get("path") or "")}
            for item in self._download_rows
        ]

    def _download_loop(self):
        for item in self._download_rows:
            if item.get("status") != "等待":
                continue
            item["status"] = "下载中"
            self._post("downloads", self._download_view())
            try:
                path, level = self._download_one(item["song"], item["level"])
            except Exception as exc:
                item["status"] = f"失败：{exc}"
                self._post("downloads", self._download_view())
                continue
            item["status"] = "完成"
            item["path"] = path
            item["quality"] = api.QUALITY_LABEL.get(level, level)
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
        req = urllib.request.Request(info["url"], headers={"User-Agent": api.UA, "Referer": "https://music.163.com/"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest + ".part", "wb") as handle:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                handle.write(chunk)
        os.replace(dest + ".part", dest)
        return dest, info.get("level") or level

    def _save_state(self):
        songs = [song for song in self._queue if song.get("songId")]
        if not songs:
            return
        pos, dur = self.player.position()
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
        page = payload.get("page") or ""
        page_title = payload.get("pageTitle") or payload.get("title") or "当前播放"
        list_id = str(payload.get("listId") or payload.get("source") or "")
        if page in ("list", "artist", "album") and page_title:
            self._page = page
            self._page_title = page_title
            self.pageChanged.emit(page, page_title)
            if page == "list" and list_id:
                self._list_id = list_id
                token = self._list_token
                threading.Thread(target=self._load_playlist, args=(list_id, page_title, token), daemon=True).start()
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
        self.stateChanged.emit("paused")
        where = f" · {self._queue_title}" if self._queue_title else ""
        self.statusChanged.emit(f"已恢复 {self._song.get('name') or ''}{where} · 已暂停")
        if self._song.get("cover"):
            threading.Thread(target=self._cache_cover, args=(self._song["cover"], 46), daemon=True).start()
        threading.Thread(target=self._restore_lyric, args=(self._song["songId"],), daemon=True).start()

    def _restore_lyric(self, song_id):
        try:
            original, translated = api.lyric_pair(song_id, cookie=self._cookie)
        except api.ApiError:
            return
        if str((self._song or {}).get("songId")) != str(song_id):
            return
        lines = api.merge_lrc(original, translated)
        self._lyrics = lines
        self._post("lyric", "\n".join(f"{ms}\t{text}" for ms, text in lines) or "0\t这首歌没有歌词")

    @pyqtSlot()
    def hideToTray(self):
        self._save_state()
        self.statusChanged.emit("已在后台运行。托盘左键打开，右键退出。")

    @pyqtSlot()
    def stop(self):
        self._alive = False
        self._login["done"] = True
        self._save_state()
        self._close_desk_lyric()
        self.player.stop()  # 退出时已在界面线程

    def _store_cache(self, token, song_id, level, ext, url):
        if not allowed_uri(url):
            return
        try:
            cache_store(song_id, level, ext, url)
        except (OSError, ValueError):
            return
        if token == self._token:
            self._post("status", "已缓存到本机，下次播放不再拉流")

    def _share_url(self):
        song = self._song or {}
        if not song.get("songId"):
            return ""
        return f"https://music.163.com/song?id={song['songId']}"

    @pyqtSlot(result=str)
    def shareCurrent(self):
        url = self._share_url()
        if not url:
            self.statusChanged.emit("还没有正在播放的歌曲")
        return url

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

    def _on_position(self, pos, dur):
        if self._loading_pos or self.player.want() != "playing":
            return
        total = dur or int((self._song or {}).get("duration") or 0)
        self.clockChanged.emit(f"{pos},{total}")

    def _on_ended(self):
        self._step(1)

    def _emit_clock(self):
        if self.player.want() != "playing":
            return
        if self.player is None:
            return
        if self._loading_pos:
            return
        pos, dur = self.player.position()
        self.clockChanged.emit(f"{pos},{dur or int((self._song or {}).get('duration') or 0)}")
        if self._desk_lyric_alive():
            self._publish_desk_lyric(pos)
