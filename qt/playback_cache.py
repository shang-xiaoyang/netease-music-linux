# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""已播放音频的本机缓存。同一首、同一音质再播时不再拉流，总量不超过 1GB。"""

import json
import os
import urllib.request

LIMIT = 1024 * 1024 * 1024
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
    item["played"] = int(__import__("time").time())
    index[key] = item
    _save(index)
    return path


def store(song_id, level, ext, url, current_path=""):
    """整首下完才记入索引。正在播放的文件不参与清理。"""
    name = _safe_name(song_id, level, ext)
    dest = os.path.join(CACHE_DIR, name)
    os.makedirs(CACHE_DIR, exist_ok=True)
    part = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "netease-music-linux", "Referer": "https://music.163.com/"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as handle:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            handle.write(chunk)
    os.replace(part, dest)
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


def _trim(index, current_path):
    current = os.path.realpath(current_path) if current_path else ""
    items = sorted(index.items(), key=lambda item: item[1].get("played") or 0)
    total = sum(int(item.get("size") or 0) for _key, item in items)
    for key, item in items:
        if total <= LIMIT:
            break
        path = os.path.realpath(item.get("path") or "")
        if path and path == current:
            continue
        size = int(item.get("size") or 0)
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
        index.pop(key, None)
        total -= size
