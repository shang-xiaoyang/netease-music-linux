# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""网易云公开接口。只使用网页版本身也会请求的登录、搜索、歌单和播放地址。

本模块是独立客户端，与网易公司没有关联。接口按账号权限返回可播放地址，
不绕过会员或付费限制。
"""

import hashlib
import json
import os
import random
import time
import urllib.parse
import urllib.request

from Cryptodome.Cipher import AES

API = "https://music.163.com"
UA = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

CHARTS = (
    (3778678, "热歌榜"),
    (3779629, "新歌榜"),
    (2884035, "原创榜"),
    (19723756, "飙升榜"),
    (991319590, "说唱榜"),
    (71385702, "ACG榜"),
)

# 官方播放接口的 level。未登录或权限不够时，服务端会降到账号实际能听的档。
QUALITIES = (
    ("standard", "标准", "128kbps"),
    ("exhigh", "极高", "320kbps"),
    ("lossless", "无损", "FLAC"),
    ("hires", "Hi-Res", "高解析"),
    ("jyeffect", "高清臻音", "会员"),
    ("sky", "臻音全景声", "SVIP"),
    ("jymaster", "超清母带", "SVIP"),
)
# 请求参数和菜单档位不是同一个字符串。沉浸环绕要带声道，否则服务端会降成高清臻音。
QUALITY_REQUEST = {
    "sky": {"level": "sky", "encodeType": "flac", "immerseType": "ste"},
}
QUALITY_LABEL = {key: f"{name} {hint}" for key, name, hint in QUALITIES}


class ApiError(RuntimeError):
    pass


PC_COOKIE = "os=pc; appver=8.9.75; osver=Microsoft-Windows-10-Professional-build-19041-64bit"


def _cookie_header(cookie):
    text = (cookie or "").strip()
    if "os=" not in text:
        text = (text + "; " + PC_COOKIE).strip("; ")
    elif "appver=" not in text:
        text += "; appver=8.9.75"
    return text


def request(path, data=None, cookie="", method=None):
    if path.startswith(("http://", "https://")) and not path.startswith(API + "/"):
        raise ApiError("只请求网易云音乐接口")
    url = path if path.startswith("http") else API + path
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data, doseq=True).encode()
        method = method or "POST"
    req = urllib.request.Request(
        url,
        data=body,
        method=method or "GET",
        headers={
            "User-Agent": UA,
            "Referer": "https://music.163.com/",
            "Cookie": _cookie_header(cookie),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        if not raw:
            raise ApiError(f"接口返回 {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"网络不可用：{exc.reason}") from exc
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ApiError("接口返回的不是 JSON") from exc
    if isinstance(payload, dict) and payload.get("code") not in (None, 200):
        raise ApiError(payload.get("message") or payload.get("msg") or f"接口错误 {payload.get('code')}")
    return payload


def search_suggest(keyword, cookie="", limit=8):
    """输入时的下拉建议。只取歌名和歌手，不补封面，避免每敲一个字都拉详情。"""
    text = (keyword or "").strip()
    if not text:
        return []
    payload = request(
        "/api/search/suggest/web",
        {"s": text, "limit": limit},
        cookie=cookie,
    )
    result = payload.get("result") or {}
    rows = []
    for item in (result.get("songs") or [])[:limit]:
        song = _song(item)
        if song.get("id") and song.get("name"):
            rows.append(song)
    return _mark_playable(rows, cookie)


def search_songs(keyword, limit=30, offset=0, cookie=""):
    payload = request(
        "/api/search/get/web",
        {"s": keyword, "type": 1, "limit": limit, "offset": offset},
        cookie=cookie,
    )
    result = payload.get("result") or {}
    songs = [_song(item) for item in result.get("songs") or []]
    # 网页搜索不返回封面，也不带播放权限。一次详情请求把两样都补上。
    return _complete_songs(songs, cookie)


def top_playlist(limit=24, cookie=""):
    payload = request(
        "/api/playlist/list",
        {"cat": "全部", "order": "hot", "limit": limit, "offset": 0},
        cookie=cookie,
    )
    playlists = (payload.get("playlists") or [])
    return [_playlist(item) for item in playlists]


def playlist_page(playlist_id, cookie="", limit=80, offset=0, refs=None):
    """歌单的一页歌曲。先拿 id，再按页补详情，避免一次拉完整张歌单。

    refs 是上一页已经取回的曲目编号。传入后不再重复请求歌单详情。
    """
    playlist_id = int(playlist_id)
    playlist = {}
    if refs is None:
        payload = request("/api/v6/playlist/detail", {"id": playlist_id, "n": 0}, cookie=cookie)
        playlist = payload.get("playlist") or {}
        refs = playlist.get("trackIds") or []
    if not refs:
        songs = _chart_songs(playlist_id, cookie)
        return _playlist_result(playlist, playlist_id, songs, len(songs))
    page = refs[offset:offset + limit]
    songs = _songs_by_ids(page, cookie)
    result = _playlist_result(playlist, playlist_id, songs, len(refs))
    result["refs"] = refs
    return result


def playlist_tracks(playlist_id, cookie="", by_added=False):
    """整张歌单。收藏排序仍要全部收藏时间，其余调用应优先用 playlist_page。"""
    playlist_id = int(playlist_id)
    payload = request("/api/v6/playlist/detail", {"id": playlist_id, "n": 0}, cookie=cookie)
    playlist = payload.get("playlist") or {}
    refs = playlist.get("trackIds") or []
    if not refs:
        songs = _chart_songs(playlist_id, cookie)
    else:
        songs = []
        for start in range(0, len(refs), 100):
            songs.extend(_songs_by_ids(refs[start:start + 100], cookie))
        if by_added and any(song.get("added") for song in songs):
            songs.sort(key=lambda song: song.get("added") or 0, reverse=True)
    return _playlist_result(playlist, playlist_id, songs, len(refs) or len(songs))


def _playlist_result(playlist, playlist_id, songs, total):
    return {
        "id": playlist.get("id") or playlist_id,
        "name": playlist.get("name") or "",
        "cover": _pic(playlist),
        "special": playlist.get("specialType") or 0,
        "total": total,
        "songs": songs,
    }


def _songs_by_ids(refs, cookie):
    ids = [item.get("id") for item in refs if item.get("id")]
    added = {item.get("id"): item.get("at") or 0 for item in refs}
    if not ids:
        return []
    detail = request("/api/v3/song/detail", {"c": json.dumps([{"id": int(sid)} for sid in ids])}, cookie=cookie)
    privileges = {item.get("id"): item for item in detail.get("privileges") or []}
    by_id = {}
    for item in detail.get("songs") or []:
        song = _song(item, added.get(item.get("id")) or 0)
        _apply_privilege(song, privileges.get(item.get("id")))
        by_id[item.get("id")] = song
    songs = [by_id[sid] for sid in ids if sid in by_id]
    if len(songs) < len(ids) // 2:
        # v3 对部分榜单只回一半。旧详情接口能补上歌名，封面仍走 v3 已有的结果。
        legacy = request("/api/song/detail", {"ids": json.dumps([int(sid) for sid in ids])}, cookie=cookie)
        privileges.update({item.get("id"): item for item in legacy.get("privileges") or []})
        for item in legacy.get("songs") or []:
            if item.get("id") in by_id:
                continue
            song = _song(item, added.get(item.get("id")) or 0)
            song["cover"] = by_id.get(item.get("id"), {}).get("cover") or song.get("cover") or ""
            _apply_privilege(song, privileges.get(item.get("id")))
            by_id[item.get("id")] = song
        songs = [by_id[sid] for sid in ids if sid in by_id]
    return songs


def _chart_songs(playlist_id, cookie):
    """官方榜的 v6 详情没有曲目。榜单接口一次返回榜上的歌。"""
    payload = request("/api/playlist/detail", {"id": int(playlist_id)}, cookie=cookie)
    playlist = payload.get("result") or payload.get("playlist") or {}
    privileges = {item.get("id"): item for item in playlist.get("privileges") or payload.get("privileges") or []}
    songs = []
    for item in playlist.get("tracks") or []:
        song = _song(item)
        _apply_privilege(song, privileges.get(item.get("id")))
        songs.append(song)
    return songs


def song_qualities(song_id, cookie="", known=None):
    """逐档请求播放地址，只保留服务端原样返回的档。

    不支持的档会被降到更低的 level，那种结果不记入可选项。
    调用方已经持有某一档时传入 known，可少打一次请求。
    """
    known = dict(known or {})
    supported = []
    for key, _name, _hint in QUALITIES:
        cached = known.get(key)
        if cached is None:
            cached = song_url(song_id, level=key, cookie=cookie)
            if cached and cached.get("level"):
                known[cached["level"]] = cached
        if cached and cached.get("level") == key and cached.get("url"):
            supported.append(key)
    return supported


def song_url(song_id, level="lossless", cookie=""):
    """按音质档请求播放地址。level 见 QUALITIES。"""
    if level not in QUALITY_LABEL:
        level = "lossless"
    body = {"ids": f"[{int(song_id)}]", "level": level, "encodeType": "flac"}
    body.update(QUALITY_REQUEST.get(level) or {})
    payload = request("/api/song/enhance/player/url/v1", body, cookie=cookie)
    item = (payload.get("data") or [None])[0] or {}
    if not item.get("url"):
        # 新接口没给地址时，退回旧接口，避免整首直接失败。
        legacy = request(
            "/api/song/enhance/player/url",
            {"ids": f"[{int(song_id)}]", "br": 320000},
            cookie=cookie,
        )
        item = (legacy.get("data") or [None])[0] or {}
    if not item.get("url"):
        return None
    url = str(item["url"]).replace("http://", "https://", 1)
    host = urllib.parse.urlparse(url).hostname or ""
    if urllib.parse.urlparse(url).scheme != "https" or not (
        host == "music.163.com" or host.endswith(".music.163.com") or host.endswith(".126.net")
    ):
        return None
    return {
        "url": url,
        "br": item.get("br") or 0,
        "size": item.get("size") or 0,
        "type": item.get("type") or "mp3",
        "fee": item.get("fee") or 0,
        "level": item.get("level") or level,
    }


def vip_info(cookie):
    """读取会员身份。未登录会抛 ApiError。"""
    payload = request("/api/music-vip-membership/front/vip/info", cookie=cookie)
    data = payload.get("data") or {}
    music = data.get("musicPackage") or {}
    associator = data.get("associator") or {}
    red_vip = data.get("redVipLevel") or associator.get("vipLevel") or 0
    now = int(data.get("now") or 0)
    expire = int(associator.get("expireTime") or 0)
    active = bool(expire and (now == 0 or expire > now))
    name = "普通用户"
    if data.get("redplus") or (associator.get("vipCode") or 0) >= 300:
        name = "黑胶SVIP"
    elif active or red_vip:
        name = "黑胶VIP"
    elif music.get("expireTime"):
        name = "音乐包"
    return {
        "name": name,
        "level": red_vip,
        "active": active or bool(red_vip),
        "expire": expire,
    }


def lyric(song_id, cookie=""):
    original, _translated, _words = lyric_pair(song_id, cookie)
    return original


def lyric_pair(song_id, cookie=""):
    """原文、翻译和逐字时间。逐字时间可能为空。"""
    payload = lyric_payload(song_id, cookie)
    yrc = (payload.get("yrc") or {}).get("lyric") or ""
    original = (payload.get("lrc") or {}).get("lyric") or ""
    words = parse_yrc(yrc)
    if not words and _has_word_times(original):
        words = parse_yrc(original)
    return (
        lrc_text(original),
        (payload.get("tlyric") or {}).get("lyric") or "",
        words,
    )


def lrc_text(text):
    """歌词页认 [分:秒] 行。v1 接口的 JSON 行转成同样的格式。"""
    text = text or ""
    if not text.strip().startswith("{"):
        return text
    lines = []
    for raw in text.splitlines():
        raw = raw.strip()
        if raw.startswith("{"):
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            lyric = "".join(char.get("tx") or "" for char in item.get("c") or []).strip()
            if lyric:
                lines.append(f"[{_stamp(int(item.get('t') or 0))}]{lyric}")
            continue
        if raw.startswith("["):
            lines.append(raw)
    return "\n".join(lines)


def _stamp(ms):
    ms = max(0, int(ms))
    minute, rest = divmod(ms, 60000)
    second, milli = divmod(rest, 1000)
    return f"{minute:02d}:{second:02d}.{milli:03d}"


def _has_word_times(text):
    return "(0," in (text or "") or "\"t\":" in (text or "") and "\"d\":" in (text or "")


def lyric_payload(song_id, cookie=""):
    """网页接口没有逐字时间。桌面歌词用的是加密的 v1 接口。"""
    try:
        return _eapi(
            "/api/song/lyric/v1",
            {
                "id": int(song_id),
                "cp": False,
                "lv": 0,
                "tv": 0,
                "rv": 0,
                "kv": 0,
                "yv": 0,
                "ytv": 0,
                "yrv": 0,
            },
            cookie,
        )
    except ApiError:
        return request(
            "/api/song/lyric",
            {"id": int(song_id), "lv": -1, "tv": -1},
            cookie=cookie,
        )


_EAPI_KEY = b"e82ckenh8dichen8"


def _eapi(path, data, cookie=""):
    """网易云桌面端的加密接口。只用来取歌词，不改播放地址。"""
    if path != "/api/song/lyric/v1":
        raise ApiError("只请求网易云音乐歌词接口")
    text = json.dumps(data, separators=(",", ":"))
    digest = hashlib.md5(f"nobody{path}use{text}md5forencrypt".encode()).hexdigest()
    message = f"{path}-36cd479b6b5-{text}-36cd479b6b5-{digest}"
    padded = message.encode()
    padded += bytes([16 - len(padded) % 16]) * (16 - len(padded) % 16)
    params = AES.new(_EAPI_KEY, AES.MODE_ECB).encrypt(padded).hex()
    url = "https://interface.music.163.com/eapi" + path[4:]
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode({"params": params}).encode(),
        method="POST",
        headers={
            "User-Agent": UA,
            "Referer": "https://music.163.com/",
            "Cookie": _cookie_header(cookie),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        if not raw:
            raise ApiError(f"接口返回 {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"网络不可用：{exc.reason}") from exc
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ApiError("接口返回的不是 JSON") from exc
    if isinstance(payload, dict) and payload.get("code") not in (None, 200):
        raise ApiError(payload.get("message") or payload.get("msg") or f"接口错误 {payload.get('code')}")
    return payload


def parse_yrc(text):
    """逐字歌词。每句是开始时间、结束时间和每个字的 (字, 开始, 时长)。"""
    lines = []
    for raw in (text or "").splitlines():
        raw = raw.strip()
        if raw.startswith("{"):
            parsed = _parse_json_yrc(raw)
            if parsed:
                lines.append(parsed)
            continue
        if not raw.startswith("[") or "]" not in raw:
            continue
        header, rest = raw[1:].split("]", 1)
        fields = {}
        for part in header.split(","):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            try:
                fields[key] = int(value)
            except ValueError:
                continue
        words = []
        for chunk in rest.split("("):
            if ")" not in chunk:
                continue
            stamp, glyph = chunk.split(")", 1)
            bits = stamp.split(",")
            if len(bits) < 2 or not glyph:
                continue
            try:
                start = int(bits[0])
                duration = int(bits[1])
            except ValueError:
                continue
            words.append((glyph, start, max(1, duration)))
        if not words:
            continue
        if "t" in fields:
            start = fields["t"]
            end = start + max(1, fields.get("d") or 1)
        else:
            bits = [int(part) for part in header.split(",") if part.lstrip("-").isdigit()]
            start = bits[0] if bits else words[0][1]
            end = bits[1] if len(bits) > 1 else start + words[-1][2]
        lines.append((start, max(start + 1, end), words))
    lines.sort()
    return lines


def _parse_json_yrc(raw):
    try:
        item = json.loads(raw)
    except json.JSONDecodeError:
        return None
    chars = item.get("c") or []
    words = []
    cursor = int(item.get("t") or 0)
    for char in chars:
        glyph = char.get("tx") or ""
        if not glyph:
            continue
        start = char.get("t")
        duration = char.get("d")
        if start is None:
            start = cursor
        if duration is None:
            duration = 1
        words.append((glyph, int(start), max(1, int(duration))))
        cursor = int(start) + max(1, int(duration))
    if not words or not any("t" in char or "d" in char for char in chars):
        return None
    start = int(item.get("t") or words[0][1])
    end = int(item.get("t") or 0) + max(1, int(item.get("d") or 1))
    if end <= start:
        end = words[-1][1] + words[-1][2]
    return start, max(start + 1, end), words


def like_song(song_id, like, cookie):
    # 这个接口认 trackId。传 id 会直接返回「请求参数错误」。
    request(
        "/api/song/like",
        {"trackId": int(song_id), "like": "true" if like else "false"},
        cookie=cookie,
    )


def liked_ids(cookie):
    """红心歌曲 id。顺序不是收藏时间，只用来同步爱心状态。"""
    payload = request("/api/song/like/get", cookie=cookie, method="POST", data={})
    return [int(item) for item in (payload.get("ids") or [])]


def add_playlist_track(playlist_id, song_id, cookie):
    """把歌曲加进自己创建的歌单。没有权限时接口会返回错误。"""
    _manipulate_track(playlist_id, song_id, "add", cookie)


def remove_playlist_track(playlist_id, song_id, cookie):
    """从自己创建的歌单移除。歌单里没有这首歌时接口也返回成功，调用前要自己确认。"""
    _manipulate_track(playlist_id, song_id, "del", cookie)


def playlist_track_ids(playlist_id, cookie=""):
    """只取曲目 id，用来判断歌曲在不在自建歌单里。"""
    payload = request("/api/v6/playlist/detail", {"id": int(playlist_id), "n": 0}, cookie=cookie)
    playlist = payload.get("playlist") or {}
    return [int(item.get("id")) for item in playlist.get("trackIds") or [] if item.get("id")]


def create_playlist(name, cookie):
    """创建自己的歌单。名称来自输入框，接口按登录账号归属。"""
    name = (name or "").strip()
    if not name:
        raise ApiError("歌单名称不能为空")
    payload = request("/api/playlist/create", {"name": name[:40]}, cookie=cookie)
    playlist = payload.get("playlist") or payload.get("result") or {}
    playlist_id = playlist.get("id") or payload.get("id")
    if not playlist_id:
        raise ApiError("歌单已创建，但没有返回编号")
    return int(playlist_id)


def _manipulate_track(playlist_id, song_id, op, cookie):
    request(
        "/api/playlist/manipulate/tracks",
        {"op": op, "pid": int(playlist_id), "trackIds": f"[{int(song_id)}]"},
        cookie=cookie,
    )


def comments(song_id, offset=0, limit=20, cookie=""):
    payload = request(
        f"/api/v1/resource/comments/R_SO_4_{int(song_id)}",
        {"limit": limit, "offset": offset},
        cookie=cookie,
    )
    return {
        "hot": [_comment(item) for item in payload.get("hotComments") or []],
        "latest": [_comment(item) for item in payload.get("comments") or []],
        "total": payload.get("total") or 0,
        "more": bool(payload.get("more")),
    }


def _comment(item):
    user = item.get("user") or {}
    return {
        "id": item.get("commentId"),
        "content": item.get("content") or "",
        "nickname": user.get("nickname") or "",
        "userId": user.get("userId") or "",
        "avatar": user.get("avatarUrl") or "",
        "liked": item.get("likedCount") or 0,
        "time": item.get("time") or 0,
    }


def add_comment(song_id, content, cookie):
    """发表歌曲评论。内容来自输入框，接口按登录账号归属。"""
    text = (content or "").strip()
    if not text:
        raise ApiError("评论不能为空")
    if len(text) > 140:
        raise ApiError("评论不能超过 140 字")
    request(
        "/api/resource/comments/add",
        {"threadId": f"R_SO_4_{int(song_id)}", "content": text, "t": "1", "type": "0"},
        cookie=cookie,
    )


def personal_fm(cookie):
    payload = request("/api/v1/radio/get", cookie=cookie)
    return _mark_playable([_song(item) for item in payload.get("data") or []], cookie)


def fm_trash(song_id, cookie):
    request("/api/radio/trash/add", {"songId": int(song_id)}, cookie=cookie)


def play_record(uid, cookie, weekly=True):
    payload = request(
        "/api/v1/play/record",
        {"uid": uid, "type": 1 if weekly else 0},
        cookie=cookie,
    )
    key = "weekData" if weekly else "allData"
    songs = []
    for item in payload.get(key) or []:
        song = _song(item.get("song") or {})
        song["playCount"] = item.get("playCount") or 0
        songs.append(song)
    return songs


def login_qr_key():
    payload = request("/api/login/qrcode/unikey", {"type": 1})
    key = payload.get("unikey")
    if not key:
        raise ApiError("没有拿到登录二维码")
    return key


def _cookie_from_headers(headers):
    pieces = []
    # 登录成功时 MUSIC_U 可能和别的字段分在多条 Set-Cookie 里，不能只取第一条。
    values = []
    if hasattr(headers, "get_all"):
        values = headers.get_all("Set-Cookie") or []
    elif headers.get("Set-Cookie"):
        values = [headers.get("Set-Cookie")]
    for value in values:
        pair = value.split(";", 1)[0].strip()
        if "=" in pair and not pair.endswith("="):
            pieces.append(pair)
    return "; ".join(pieces)


def login_qr_check(key, cookie=""):
    # 801 等待扫码，802 已扫待确认，803 成功，800 过期。
    # 必须带上生成二维码时的 Cookie，否则确认后服务端不回 MUSIC_U。
    url = API + "/api/login/qrcode/client/login?key=" + urllib.parse.quote(key) + "&type=1"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": "https://music.163.com/",
            "Cookie": _cookie_header(cookie),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            found = _cookie_from_headers(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        found = _cookie_from_headers(exc.headers)
    payload = json.loads(raw.decode("utf-8", "replace") or "{}")
    merged = cookie or ""
    if found:
        merged = (merged + "; " + found).strip("; ")
    if payload.get("cookie") and "MUSIC_U=" in payload["cookie"]:
        merged = payload["cookie"]
    return {
        "code": payload.get("code"),
        "cookie": merged if "MUSIC_U=" in merged else "",
        "message": payload.get("message") or "",
    }


def login_qr_create():
    """生成二维码，并保留这次请求的 Cookie。确认登录时要原样带回去。"""
    req = urllib.request.Request(
        API + "/api/login/qrcode/unikey",
        data=urllib.parse.urlencode({"type": 1}).encode(),
        headers={
            "User-Agent": UA,
            "Referer": "https://music.163.com/",
            "Cookie": PC_COOKIE,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode())
        base = _cookie_from_headers(resp.headers)
    key = payload.get("unikey")
    if not key:
        raise ApiError("没有拿到登录二维码")
    return key, _cookie_header(base)


def user_account(cookie):
    payload = request("/api/nuser/account/get", cookie=cookie)
    profile = (payload.get("profile") or {})
    account = payload.get("account") or {}
    vip = {}
    try:
        vip = vip_info(cookie)
    except ApiError:
        vip = {"name": "", "level": 0, "active": False, "expire": 0}
    return {
        "nickname": profile.get("nickname") or account.get("userName") or "已登录",
        "userId": profile.get("userId"),
        "avatar": profile.get("avatarUrl") or "",
        "vip": vip.get("name") or "",
        "vipLevel": vip.get("level") or 0,
        "vipExpire": vip.get("expire") or 0,
    }


def user_detail(uid, cookie=""):
    payload = request(f"/api/v1/user/detail/{int(uid)}", cookie=cookie)
    profile = payload.get("profile") or {}
    return {
        "userId": profile.get("userId") or uid,
        "nickname": profile.get("nickname") or "用户",
        "avatar": profile.get("avatarUrl") or "",
        "signature": profile.get("signature") or "",
        "follows": profile.get("follows") or 0,
        "followers": profile.get("followeds") or 0,
    }


def user_playlists(uid, cookie):
    playlists = []
    offset = 0
    while offset < 500:
        payload = request(
            "/api/user/playlist",
            {"uid": uid, "limit": 50, "offset": offset},
            cookie=cookie,
        )
        batch = [_playlist(item) for item in payload.get("playlist") or []]
        playlists.extend(batch)
        if not batch or not payload.get("more"):
            break
        offset += len(batch)
    return playlists


def liked_songs(cookie):
    """「我喜欢的音乐」，按收藏时间从新到旧。

    红心 id 列表的顺序不是收藏时间。收藏时间在歌单 trackIds 的 at 字段里。
    """
    account = user_account(cookie)
    uid = account.get("userId")
    playlist_id = None
    if uid:
        for item in user_playlists(uid, cookie):
            if item.get("special") == 5 or "喜欢的音乐" in (item.get("name") or ""):
                playlist_id = item["id"]
                break
    if playlist_id:
        data = playlist_tracks(playlist_id, cookie=cookie, by_added=True)
        if data["songs"]:
            return data["songs"]
    song_ids = liked_ids(cookie)
    songs = []
    for start in range(0, len(song_ids), 100):
        chunk = song_ids[start:start + 100]
        detail = request("/api/song/detail", {"ids": json.dumps(chunk)}, cookie=cookie)
        privileges = {item.get("id"): item for item in detail.get("privileges") or []}
        by_id = {}
        for item in detail.get("songs") or []:
            song = _song(item)
            _apply_privilege(song, privileges.get(item.get("id")))
            by_id[item.get("id")] = song
        songs.extend(by_id[sid] for sid in chunk if sid in by_id)
    return songs


def likelist_playlist(cookie):
    """收藏歌单和创建歌单，登录后填到左侧。"""
    account = user_account(cookie)
    uid = account.get("userId")
    if not uid:
        return account, []
    return account, user_playlists(uid, cookie)


def artist_home(artist_id, cookie=""):
    """歌手首页：头像、简介、热门歌曲和专辑。没有主页的 id 会抛 ApiError。"""
    artist_id = int(artist_id)
    payload = request("/api/artist/head/info/get", {"id": artist_id}, cookie=cookie)
    data = payload.get("data") or {}
    artist = data.get("artist") or {}
    user = data.get("user") or {}
    if not artist and not user:
        raise ApiError("这个歌手没有主页")
    songs = []
    try:
        songs = artist_songs(artist_id, cookie)
    except ApiError:
        songs = []
    albums = []
    try:
        albums = artist_albums(artist_id, cookie)
    except ApiError:
        albums = []
    return {
        "id": artist.get("id") or artist_id,
        "name": artist.get("name") or user.get("nickname") or "歌手",
        "avatar": artist.get("cover") or artist.get("avatar") or user.get("avatarUrl") or "",
        "alias": " / ".join(artist.get("alias") or []),
        "brief": artist.get("briefDesc") or "",
        "albumCount": artist.get("albumSize") or len(albums),
        "musicCount": artist.get("musicSize") or len(songs),
        "songs": songs,
        "albums": albums,
    }


def artist_songs(artist_id, cookie="", limit=50):
    """歌手热门歌曲。公开接口，不需要登录。"""
    payload = request(
        "/api/v1/artist/songs",
        {"id": int(artist_id), "limit": limit, "offset": 0, "order": "hot"},
        cookie=cookie,
    )
    songs = payload.get("songs") or []
    if not songs:
        legacy = request("/api/artist/top/song", {"id": int(artist_id)}, cookie=cookie)
        songs = legacy.get("songs") or []
    return _mark_playable([_song(item) for item in songs], cookie)


def artist_albums(artist_id, cookie="", limit=12):
    payload = request(
        "/api/artist/albums/" + str(int(artist_id)),
        {"limit": limit, "offset": 0},
        cookie=cookie,
    )
    albums = []
    for item in payload.get("hotAlbums") or []:
        albums.append({
            "id": item.get("id"),
            "name": item.get("name") or "专辑",
            "cover": item.get("picUrl") or "",
            "publish": _date(item.get("publishTime")),
        })
    return albums


def album_detail(album_id, cookie=""):
    payload = request("/api/v1/album/" + str(int(album_id)), cookie=cookie, method="GET")
    album = payload.get("album") or {}
    songs = _mark_playable([_song(item) for item in payload.get("songs") or []], cookie)
    artist = (album.get("artist") or (album.get("artists") or [None])[0] or {})
    return {
        "id": album.get("id") or album_id,
        "name": album.get("name") or "专辑",
        "cover": album.get("picUrl") or "",
        "company": album.get("company") or "",
        "publish": _date(album.get("publishTime")),
        "description": album.get("description") or album.get("briefDesc") or "",
        "artist": {"id": artist.get("id"), "name": artist.get("name") or ""},
        "songs": songs,
    }


def recommend_songs(cookie):
    payload = request("/api/v1/discovery/recommend/songs", cookie=cookie, method="POST", data={})
    daily = ((payload.get("data") or {}).get("dailySongs") or [])
    return _mark_playable([_song(item) for item in daily], cookie)


def _artist_rows(item):
    artists = item.get("ar") or item.get("artists") or []
    return [{"id": artist.get("id"), "name": artist.get("name") or ""} for artist in artists if artist.get("name")]


def _artists(item):
    return " / ".join(artist["name"] for artist in _artist_rows(item))


def _album(item):
    album = item.get("al") or item.get("album") or {}
    return album.get("name") or ""


def attach_covers(songs, cookie=""):
    """按歌曲详情补齐专辑图。旧的 /api/song/detail 不再返回封面，不能拿来覆盖已有地址。"""
    return _complete_songs(songs, cookie)


def _complete_songs(songs, cookie=""):
    """一次详情请求补封面和播放权限。搜索原来这两步各打一遍同一接口。"""
    missing = [
        song for song in songs
        if song.get("id") and (not song.get("cover") or song.get("playable") is None)
    ]
    for start in range(0, len(missing), 100):
        chunk = missing[start:start + 100]
        body = json.dumps([{"id": int(song["id"])} for song in chunk])
        try:
            detail = request("/api/v3/song/detail", {"c": body}, cookie=cookie)
        except ApiError:
            continue
        covers = {item.get("id"): _pic(item) for item in detail.get("songs") or []}
        privileges = {item.get("id"): item for item in detail.get("privileges") or []}
        for song in chunk:
            if not song.get("cover"):
                song["cover"] = covers.get(song["id"]) or ""
            if song.get("playable") is None:
                _apply_privilege(song, privileges.get(song["id"]))
    return songs


def _date(value):
    if not value:
        return ""
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return str(value)[:10]
    if stamp > 10_000_000_000:
        stamp //= 1000
    return time.strftime("%Y-%m-%d", time.localtime(stamp))


def _pic(item):
    album = item.get("al") or item.get("album") or {}
    return (
        item.get("coverImgUrl")
        or album.get("picUrl")
        or item.get("picUrl")
        or ""
    )


def _mark_playable(songs, cookie=""):
    """专辑、电台这些接口不带 privileges。按歌曲详情补上能不能播。"""
    return _complete_songs(songs, cookie)


def _apply_privilege(song, privilege):
    """无版权、下架、不能试听的歌标记为不可播放。没有权限数据时不当成不能播。"""
    if not privilege:
        return song
    st = int(privilege.get("st") or 0)
    song["playable"] = st >= 0 and int(privilege.get("pl") or 0) > 0
    return song


def _song(item, added=0):
    album = item.get("al") or item.get("album") or {}
    artists = _artist_rows(item)
    return {
        "id": item.get("id"),
        "name": item.get("name") or "未命名",
        "artist": " / ".join(artist["name"] for artist in artists),
        "artists": artists,
        "artistId": artists[0]["id"] if artists else None,
        "album": album.get("name") or "",
        "albumId": album.get("id"),
        "cover": _pic(item),
        "duration": item.get("dt") or item.get("duration") or 0,
        "fee": item.get("fee") or 0,
        "added": added or 0,
        "playable": None,
    }


def _playlist(item):
    creator = item.get("creator") or {}
    return {
        "id": item.get("id"),
        "name": item.get("name") or "歌单",
        "cover": item.get("coverImgUrl") or "",
        "count": item.get("trackCount") or 0,
        "creator": creator.get("userId") or item.get("userId"),
        "mine": bool(item.get("mine")),
        "special": item.get("specialType") or 0,
        "added": item.get("createTime") or 0,
    }


def merge_lrc(original, translation):
    """同一时间戳的翻译紧跟原文，方便歌词页同屏显示。"""
    translated = {ms: line for ms, line in parse_lrc(translation)}
    merged = []
    for ms, line in parse_lrc(original):
        merged.append((ms, line))
        extra = translated.get(ms)
        if extra and extra != line:
            merged.append((ms, extra))
    return merged


def parse_lrc(text):
    lines = []
    for raw in (text or "").splitlines():
        raw = raw.strip()
        if not raw.startswith("["):
            continue
        stamps = []
        rest = raw
        while rest.startswith("[") and "]" in rest:
            stamp, rest = rest[1:].split("]", 1)
            parts = stamp.split(":")
            if len(parts) != 2 or not parts[0].isdigit():
                break
            try:
                ms = int(parts[0]) * 60000 + int(float(parts[1]) * 1000)
            except ValueError:
                break
            stamps.append(ms)
        lyric = rest.strip()
        if lyric:
            lines.extend((ms, lyric) for ms in stamps)
    lines.sort()
    return lines


def anonymous_device_id():
    return "".join(random.choice("0123456789abcdef") for _ in range(32))


def load_cookie(path):
    if not os.path.exists(path):
        return ""
    return open(path, encoding="utf-8").read().strip()


def save_cookie(path, cookie):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    os.chmod(folder, 0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(cookie.strip() + "\n")
    os.chmod(path, 0o600)
