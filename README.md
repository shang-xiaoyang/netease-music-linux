# 网易云音乐 Linux 原生播放器

非官方播放器。在本地 GTK 窗口里播放网易云音乐，不套网页，不使用 Wine。同一份纯 Python 代码可在 x86、x86_64 和 ARM 的 Debian 系桌面运行。

本项目与网易公司没有关联，也未获授权。「网易云音乐」名称和官方标志归网易所有。安装包里的图标由打包脚本生成，是一张红底音符，不是官方唱片标志。歌曲、歌词和会员音质仍由网易云音乐按账号权限提供，本程序不绕过这些限制。

许可证是 [MIT](LICENSE)。第三方权利说明见 [NOTICE.md](NOTICE.md)。

## 从源码运行

```sh
sudo apt install python3 python3-gi python3-dbus python3-pil \
  gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 \
  gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
  gir1.2-ayatanaappindicator3-0.1 \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-libav gstreamer1.0-pulseaudio \
  qrencode libayatana-appindicator3-1 fonts-noto-cjk
./netease-music
```

运行时使用发行版自己的 GObject introspection 数据，不附带 typelib。

## 打包

```sh
dpkg-buildpackage -us -uc -b
```

产物是 `Architecture: all` 的 deb。安装：

```sh
sudo apt install ./netease-music-linux_*_all.deb
```

安装后在应用菜单里打开「网易云音乐（非官方）」，或运行 `netease-music`。

关闭窗口不会停止播放，图标留在托盘。左键打开主窗口，右键可选「显示主界面」或「退出」。也可以用 Ctrl+Q，或在终端执行：

```sh
gapplication action io.github.shangxiaoyang.netease-music quit
```

应用 ID 是独立反向域名，不用 `cn.netease`，避免和官方客户端抢 D-Bus 名。

## 功能

- 扫码登录。登录后显示昵称、会员类型、我喜欢的音乐、每日推荐和收藏歌单
- 「我喜欢的音乐」按云端红心时间从新到旧排列。左侧「刷新收藏」可重新拉取
- 关闭窗口后留在托盘继续运行
- 音质可选标准、极高、无损、Hi-Res、高清臻音、沉浸环绕、超清母带。账号没有对应权限时，服务端会降到实际能听的档。切换后按新音质重播当前歌曲，并从原来的进度继续
- 全局快捷键：Ctrl+Alt+P 播放或暂停，Ctrl+Alt+Home 上一首，Ctrl+Alt+End 下一首。窗口在后台时也能用。快捷键通过桌面的全局快捷键服务登记，没有这项服务的桌面环境会跳过
- 播放模式可在列表循环、列表播放、单曲循环、随机播放之间切换
- 底部「播放列表」弹出当前播放列表。退出后再打开会恢复歌曲、列表、音质和进度
- 点进度条跳到对应位置
- 点底部封面或歌名看歌词
- 歌曲和歌单封面缓存在本机，下次打开直接读本地文件

登录状态和封面缓存都在当前用户的数据目录里，只保存在本机。

## 目录

| 路径 | 作用 |
| --- | --- |
| `player.py` | GTK 主界面和播放 |
| `netease_api.py` | 登录、搜索、歌单、播放地址 |
| `netease_music.py` | 旧的网页套壳，默认不启动 |
| `netease-music` | 从源码树启动 |
| `packaging/` | 安装后的启动脚本、desktop、D-Bus service |
| `debian/` | Debian 打包目录 |
