# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""网易云公开接口。只使用网页版本身也会请求的登录、搜索、歌单和播放地址。

本模块是独立客户端，与网易公司没有关联。接口按账号权限返回可播放地址，
不绕过会员或付费限制。
"""

import json
import os
import random
import urllib.parse
import urllib.request

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
    ("sky", "沉浸环绕", "会员"),
    ("jymaster", "超清母带", "SVIP"),
)
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


def search_songs(keyword, limit=30, offset=0, cookie=""):
    payload = request(
        "/api/search/get/web",
        {"s": keyword, "type": 1, "limit": limit, "offset": offset},
        cookie=cookie,
    )
    result = payload.get("result") or {}
    songs = [_song(item) for item in result.get("songs") or []]
    # 网页搜索不返回封面。专辑封面在歌曲详情里，补上后列表才能显示。
    return attach_covers(songs, cookie)


def top_playlist(limit=24, cookie=""):
    payload = request(
        "/api/playlist/list",
        {"cat": "全部", "order": "hot", "limit": limit, "offset": 0},
        cookie=cookie,
    )
    playlists = (payload.get("playlists") or [])
    return [_playlist(item) for item in playlists]


def playlist_tracks(playlist_id, cookie="", by_added=False):
    payload = request("/api/v6/playlist/detail", {"id": playlist_id, "n": 1000}, cookie=cookie)
    playlist = payload.get("playlist") or {}
    tracks = playlist.get("tracks") or []
    added = {item.get("id"): item.get("at") or 0 for item in playlist.get("trackIds") or []}
    if not tracks:
        # 旧接口在未登录时仍返回榜单曲目。
        legacy = request("/api/playlist/detail", {"id": playlist_id}, cookie=cookie)
        playlist = legacy.get("result") or legacy.get("playlist") or {}
        tracks = playlist.get("tracks") or []
    songs = [_song(item, added.get(item.get("id")) or 0) for item in tracks]
    if by_added and any(song.get("added") for song in songs):
        songs.sort(key=lambda song: song.get("added") or 0, reverse=True)
    return {
        "id": playlist.get("id") or playlist_id,
        "name": playlist.get("name") or "",
        "cover": _pic(playlist),
        "special": playlist.get("specialType") or 0,
        "songs": songs,
    }


def song_url(song_id, level="lossless", cookie=""):
    """按音质档请求播放地址。level 见 QUALITIES。"""
    if level not in QUALITY_LABEL:
        level = "lossless"
    payload = request(
        "/api/song/enhance/player/url/v1",
        {"ids": f"[{int(song_id)}]", "level": level, "encodeType": "flac"},
        cookie=cookie,
    )
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
    return {
        "url": item["url"].replace("http://", "https://"),
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
    payload = request(
        "/api/song/lyric",
        {"id": int(song_id), "lv": -1, "tv": -1},
        cookie=cookie,
    )
    return (payload.get("lrc") or {}).get("lyric") or ""


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
    ids = request("/api/song/like/get", cookie=cookie, method="POST", data={})
    song_ids = [int(item) for item in (ids.get("ids") or [])]
    songs = []
    for start in range(0, len(song_ids), 100):
        chunk = song_ids[start:start + 100]
        detail = request("/api/song/detail", {"ids": json.dumps(chunk)}, cookie=cookie)
        by_id = {item.get("id"): _song(item) for item in detail.get("songs") or []}
        songs.extend(by_id[sid] for sid in chunk if sid in by_id)
    return songs


def likelist_playlist(cookie):
    """收藏歌单和创建歌单，登录后填到左侧。"""
    account = user_account(cookie)
    uid = account.get("userId")
    if not uid:
        return account, []
    return account, user_playlists(uid, cookie)


def recommend_songs(cookie):
    payload = request("/api/v1/discovery/recommend/songs", cookie=cookie, method="POST", data={})
    daily = ((payload.get("data") or {}).get("dailySongs") or [])
    return [_song(item) for item in daily]


def _artists(item):
    artists = item.get("ar") or item.get("artists") or []
    names = [a.get("name") for a in artists if a.get("name")]
    return " / ".join(names)


def _album(item):
    album = item.get("al") or item.get("album") or {}
    return album.get("name") or ""


def attach_covers(songs, cookie=""):
    """给缺少封面的歌曲补上专辑图。已有封面的不再请求。"""
    missing = [song for song in songs if song.get("id") and not song.get("cover")]
    for start in range(0, len(missing), 100):
        chunk = missing[start:start + 100]
        ids = [int(song["id"]) for song in chunk]
        detail = request("/api/song/detail", {"ids": json.dumps(ids)}, cookie=cookie)
        by_id = {item.get("id"): _pic(item) for item in detail.get("songs") or []}
        for song in chunk:
            song["cover"] = by_id.get(song["id"]) or song.get("cover") or ""
    return songs


def _pic(item):
    album = item.get("al") or item.get("album") or {}
    return (
        item.get("coverImgUrl")
        or album.get("picUrl")
        or item.get("picUrl")
        or ""
    )


def _song(item, added=0):
    return {
        "id": item.get("id"),
        "name": item.get("name") or "未命名",
        "artist": _artists(item),
        "album": _album(item),
        "cover": _pic(item),
        "duration": item.get("dt") or item.get("duration") or 0,
        "fee": item.get("fee") or 0,
        "added": added or 0,
    }


def _playlist(item):
    creator = item.get("creator") or {}
    return {
        "id": item.get("id"),
        "name": item.get("name") or "歌单",
        "cover": item.get("coverImgUrl") or "",
        "count": item.get("trackCount") or 0,
        "creator": creator.get("userId") or item.get("userId"),
        "special": item.get("specialType") or 0,
        "added": item.get("createTime") or 0,
    }


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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(cookie.strip() + "\n")
    os.chmod(path, 0o600)
