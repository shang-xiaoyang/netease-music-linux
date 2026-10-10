# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Shang Xiaoyang
"""Qt Quick 播放器的本机路径。登录和窗口数据沿用 GTK 版的数据目录。"""

import os

DATA_DIR = os.path.join(os.path.expanduser("~/.local/share"), "netease-cloud-music")
WINDOW_PATH = os.path.join(DATA_DIR, "qt-window.json")
COOKIE_PATH = os.path.join(DATA_DIR, "cookie")
VOLUME_PATH = os.path.join(DATA_DIR, "volume")
LYRIC_PATH = os.path.join(DATA_DIR, "desk-lyric.json")
LYRIC_STATE_PATH = os.path.join(DATA_DIR, "desk-lyric-state.json")
DOWNLOAD_INDEX = os.path.join(DATA_DIR, "qt-downloads.json")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
RECENT_PATH = os.path.join(DATA_DIR, "recent-playlists.json")
QML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml")
PLAYER_SCRIPT = os.environ.get("NETEASE_PLAYER_SCRIPT") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "player.py",
)


def player_script():
    """歌词进程必须用脚本路径启动。python -m qt.app 会把 argv[0] 留在子进程里。"""
    path = os.path.abspath(PLAYER_SCRIPT)
    if os.path.isfile(path):
        return path
    installed = "/usr/lib/netease-music/player.py"
    if os.path.isfile(installed):
        return installed
    return path


def icon_path():
    """任务栏只用随程序生成的音符图标，不读主题或网易商标。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("icon.png", "netease-music-linux.png"):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    return ""
