# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""已播放音频的本机缓存。同一首、同一音质再播时不再拉流，总量不超过 1GB。"""

import json
import os
import threading
import urllib.request

LIMIT = 1024 * 1024 * 1024
# 快到 1GB 时一次腾出 200MB，而不是顶满了才一点点删。
HEADROOM = 200 * 1024 * 1024
# 单首缓存不再往下读。母带再大也远小于这个值，异常响应不能写满磁盘。
MAX_TRACK = 200 * 1024 * 1024
CACHE_DIR = os.path.join(os.path.expanduser("~/.cache"), "netease-cloud-music", "playback")
INDEX_PATH = os.path.join(CACHE_DIR, "index.json")


def _load():
    try:
        with open(INDEX_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(index):
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = INDEX_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(index, handle, ensure_ascii=False)
    os.replace(tmp, INDEX_PATH)


def _safe_name(song_id, level, ext):
    song = "".join(ch for ch in str(song_id) if ch.isdigit())
    level = "".join(ch for ch in str(level) if ch.isalnum()) or "audio"
    ext = "".join(ch for ch in str(ext) if ch.isalnum()) or "mp3"
    if not song:
        raise OSError("缓存歌曲编号无效")
    return f"{song}-{level}.{ext}"


def _complete(path):
    """FLAC 必须有正常的帧头，并且不是下到一半的文件。MP3 只认文件头。"""
    try:
        with open(path, "rb") as handle:
            head = handle.read(4)
        if head == b"fLaC":
            return _flac_frames(path)
        if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
            return True
    except OSError:
        return False
    return False


def _flac_frames(path):
    """从元数据块走到第一帧。下到一半的文件走不到，或者采样数对不上文件大小。"""
    try:
        with open(path, "rb") as handle:
            if handle.read(4) != b"fLaC":
                return False
            size = os.path.getsize(path)
            samples = 0
            rate = 0
            last = False
            for _ in range(16):
                header = handle.read(4)
                if len(header) < 4:
                    return False
                last = bool(header[0] & 0x80)
                block = header[0] & 0x7F
                length = int.from_bytes(header[1:4], "big")
                if length > 1024 * 1024:
                    return False
                body = handle.read(length)
                if len(body) < length:
                    return False
                if block == 0 and len(body) >= 18:
                    rate = int.from_bytes(body[10:13], "big") >> 4
                    samples = int.from_bytes(body[13:18], "big") & 0xFFFFFFFFF
                if last:
                    break
            else:
                return False
            if not last or samples <= 0 or rate <= 0:
                return False
            # 母带大约 1MB 能播两秒。采样数对应的时长和文件大小差一个数量级，就是截断的。
            seconds = samples / rate
            return size > seconds * 16 * 1024
    except OSError:
        return False


def lookup(song_id, level):
    index = _load()
    key = f"{song_id}:{level}"
    item = index.get(key)
    if not item:
        return ""
    path = os.path.realpath(item.get("path") or "")
    root = os.path.realpath(CACHE_DIR)
    if not path.startswith(root + os.sep) or not os.path.isfile(path):
        index.pop(key, None)
        _save(index)
        return ""
    if os.path.splitext(path)[1].lstrip(".") != item.get("ext"):
        index.pop(key, None)
        _save(index)
        return ""
    # 下到一半就被记进索引的文件，读完会被当成唱完。这种不能再当成本机缓存。
    size = os.path.getsize(path)
    if size < 256 * 1024 or size != int(item.get("size") or 0) or not _complete(path):
        index.pop(key, None)
        _save(index)
        try:
            os.remove(path)
        except OSError:
            pass
        return ""
    item["played"] = int(__import__("time").time())
    index[key] = item
    _save(index)
    return path


_STORE_LOCK = threading.Lock()


def network_down(exc):
    """和接口请求里的「网络不可用」是同一类：超时、连不上、对端把连接掐断。

    地址过期、没有权限、文件本身不完整都不算网络断开。
    """
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (408, 429) or exc.code >= 500
    if isinstance(exc, (TimeoutError, ConnectionError, BrokenPipeError)):
        return True
    if isinstance(exc, urllib.error.URLError):
        return True
    text = str(exc).lower()
    return any(word in text for word in (
        "timed out", "timeout", "network is unreachable", "name or service not known",
        "temporary failure", "connection reset", "connection refused", "broken pipe",
        "unexpected_eof", "eof occurred",
    ))


def store(song_id, level, ext, url, current_path="", cancel=None, progress=None):
    """整首下完才记入索引。正在播放的文件不参与清理。同一时间只缓存一首。"""
    if not _STORE_LOCK.acquire(blocking=False):
        raise OSError("已有缓存在下载")
    try:
        return _store(song_id, level, ext, url, current_path, cancel, progress)
    finally:
        _STORE_LOCK.release()


def _store(song_id, level, ext, url, current_path="", cancel=None, progress=None):
    name = _safe_name(song_id, level, ext)
    dest = os.path.join(CACHE_DIR, name)
    os.makedirs(CACHE_DIR, exist_ok=True)
    part = dest + ".part"
    # 上次没下完的半截留着。服务器认 Range 时从断点接着下，不认再从头写。
    have = os.path.getsize(part) if os.path.isfile(part) else 0
    if have >= MAX_TRACK:
        try:
            os.remove(part)
        except OSError:
            pass
        have = 0
    headers = {"User-Agent": "netease-music-linux", "Referer": "https://music.163.com/"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            resume = bool(have and code == 206)
            with open(part, "ab" if resume else "wb") as handle:
                _read_cache(resp, handle, have if resume else 0, cancel, progress)
    except Exception:
        # 断网、退出时留下已写的部分。只有空文件才删。
        try:
            if os.path.isfile(part) and os.path.getsize(part) <= 0:
                os.remove(part)
        except OSError:
            pass
        raise
    os.replace(part, dest)
    if not _complete(dest):
        try:
            os.remove(dest)
        except OSError:
            pass
        raise OSError("缓存文件不完整")
    index = _load()
    index[f"{song_id}:{level}"] = {
        "path": dest,
        "ext": os.path.splitext(name)[1].lstrip("."),
        "size": os.path.getsize(dest),
        "played": int(__import__("time").time()),
    }
    _trim(index, current_path)
    _save(index)
    return dest


def _read_cache(resp, handle, written, cancel, progress):
    total = int(resp.headers.get("Content-Length") or 0)
    if progress is not None:
        progress["total"] = total + written if written else total
        progress["bytes"] = written
    while True:
        if cancel is not None and cancel.is_set():
            raise OSError("缓存已取消")
        chunk = resp.read(65536)
        if not chunk:
            break
        written += len(chunk)
        if written > MAX_TRACK:
            raise OSError("缓存文件过大")
        handle.write(chunk)
        if progress is not None:
            progress["bytes"] = written
    return written


def _trim(index, current_path):
    """总量超过 800MB 时，按最久没播放的顺序腾出 200MB。正在播放的文件不动。"""
    current = os.path.realpath(current_path) if current_path else ""
    items = sorted(index.items(), key=lambda item: item[1].get("played") or 0)
    total = sum(int(item.get("size") or 0) for _key, item in items)
    if total <= LIMIT - HEADROOM:
        return
    target = total - HEADROOM
    for key, item in items:
        if total <= target or total <= LIMIT - HEADROOM:
            break
        path = os.path.realpath(item.get("path") or "")
        root = os.path.realpath(CACHE_DIR)
        if path and path == current:
            continue
        size = int(item.get("size") or 0)
        try:
            if path.startswith(root + os.sep) and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
        index.pop(key, None)
        total -= size
