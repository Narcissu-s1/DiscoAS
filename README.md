# DiscoAS - 发现一首歌！

<img src="src/DiscoAS.png" width="50%">

## 前言

在经典电子卡牌游戏《炉石传说》中，「发现」特指一种「从多种选项中挑选想要的一种」的操作。「多选一」这类操作早在《万智牌》中便已存在，但在UI、UX交互上，「发现」影响了无数作品，包括但不限于《杀戮尖塔》的卡牌战利品、《黑帝斯》的神明祝福、《吸血鬼幸存者》的升级……

而 **DiscoAS** 便是项目作者边炉边听歌的产物。在他一次次点击音乐软件的“下一首”按钮，试图在他那放了4500+曲目的歌单里随机到一首能符合当前心流的曲子，结果手滑把金铜须卖了，最后组件没凑齐被纯海盗阵营当路边一条踢到第5名，人叫得比金木研还痛之后，这个小项目借助大语言模型的力量，生まれた……

---
## 所以，怎么用？

<img src="src/Cap_showhow.gif" width="100%">

- 按下默认快捷键 `Alt+D`（可在设置中修改），或左键单击系统托盘图标，**发现**一首歌！
- 选择一首歌
- 然后听就完事了！

如果你突然不想选，可以通过ESC或右上角的取消键退出「发现」界面。

---

## 所以，怎么用上呢？

上游 [Releases](https://github.com/caipeilan/DiscoAS/releases) 中有打包版本时，可以下载压缩包，解压后双击 `DiscoAS.exe`。当前源码中的平台解析、播放控制和设置保存功能可能新于已发布版本；需要这些最新改动时，请按下方“Python 环境下运行”从源码启动。

---

## 那啥，前置？

当前仅支持 Windows 桌面系统，主要在 Windows 11 上验证。音乐软件目前支持：

- 网易云音乐
- QQ音乐
- 酷狗音乐
- Spotify

请先安装所使用平台的桌面客户端。QQ 音乐、酷狗音乐和 Spotify 通过 Scheme 唤起客户端；网易云音乐使用本地后台控制通道。

### 各平台当前播放行为

| 平台 | 歌单/专辑 | 选择歌曲后的行为 |
| --- | --- | --- |
| 网易云音乐 | 均支持 | 将歌曲加入当前播放队列并立即播放，不主动操作播放器窗口。若网易云已经在运行但未启用后台控制，需要从托盘完全退出网易云后再试一次。 |
| QQ 音乐 | 均支持 | 可以播放目标歌曲，但当前会切换到 QQ 音乐的“试听列表”，尚不能可靠地追加到原播放队列。 |
| 酷狗音乐 | 均支持 | 保留当前队列，将目标歌曲插入队列并立即播放，不添加到默认列表。 |
| Spotify | 均支持 | 通过 `spotify:track:` 唤起目标歌曲，不保证保留或修改 Spotify 当前队列。 |

程序预设了项目作者他那4500+曲目的小众歌单，如果你想要使用自己的歌单的话：

- 右键系统托盘图标进入「设置」
- 进入「发现设置」，选择「添加歌单」
- 选择对应平台，输入 ID，选择类型（歌单或专辑）
- 点击「加载」验证、获取真实名称并写入本地缓存，然后启用该项
- 设置会自动保存并立即生效，无需重启应用；同一时间只能启用一个歌单或专辑

### 各平台需要填写什么

输入框通常只填写链接中的 ID；只有酷狗歌单支持直接粘贴完整分享链接。

| 平台 | 歌单 | 专辑 |
| --- | --- | --- |
| 网易云音乐 | `https://music.163.com/playlist?id=123` 中的 `123` | `https://music.163.com/album?id=456` 中的 `456` |
| QQ 音乐 | `https://y.qq.com/n/ryqq_v2/playlist/123` 中的 `disstid`：`123` | 专辑链接中的数字 `albumid` 或字符串 `albummid` |
| 酷狗音乐 | 完整的 `https://t1.kugou.com/短码`、其中的短码，或旧版数字 `specialid`；兼容新版 `share_type=collect` 收藏集合 | 数字 `album_id` 或专辑分享短码 |
| Spotify | `https://open.spotify.com/playlist/ID` 中的 `ID` | `https://open.spotify.com/album/ID` 中的 `ID` |

Spotify 未配置访问令牌时会使用 Embed 页面数据，通常最多提供前 50 首，程序会将其标记为不完整。若要通过官方 Web API 完整分页，请先在 PowerShell 中设置访问令牌后再启动：

```powershell
$env:SPOTIFY_ACCESS_TOKEN="你的 Spotify OAuth 访问令牌"
.\start.cmd
```

Spotify 开发模式下，官方 API 只能读取当前账号拥有或参与协作的歌单；令牌过期后需要重新获取。

---

## Python 环境下运行

推荐使用 Python 3.12 和项目虚拟环境。先用 `python --version` 确认当前命令指向 Python 3.12；如果系统安装了多个 Python，请用 Python 3.12 的可执行文件替代下方的 `python`。以下命令在 PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.cmd
```

`start.cmd` 固定使用 `.venv\Scripts\pythonw.exe` 后台启动；如果需要查看调试输出，请直接运行：

```powershell
.\.venv\Scripts\python.exe main.py
```

开发校验：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

### 设置与缓存位置

- 音乐设置：`user_data/settings/music_setting.json`
- 界面设置：`user_data/settings/gui_setting.json`
- 平台缓存：`user_data/<平台>/playlist/` 和 `user_data/<平台>/album/`
- 单实例锁：`%APPDATA%\DiscoAS\single_instance.lock`

远端刷新失败但已有有效缓存时，程序会继续使用上一份缓存，并将本次结果标记为陈旧缓存。

---

## 打包

该项目使用 Nuitka 打包。`requirements.txt` 不包含 Nuitka，打包前需要单独安装：

```powershell
.\.venv\Scripts\python.exe -m pip install Nuitka
.\.venv\Scripts\python.exe -m nuitka --standalone `
  --windows-disable-console `
  --assume-yes-for-downloads `
  --include-package=log `
  --include-data-dir=platforms=platforms `
  --include-data-dir=settings=settings `
  --include-data-dir=src=src `
  --windows-icon-from-ico=src/Icon.ico `
  --output-dir=dist `
  --enable-plugin=pyqt6 `
  --include-plugin-directory=platforms `
  --include-package=settings `
  --follow-imports `
  --output-filename=DiscoAS.exe `
  main.py
```

打包后入口为 `dist/main.dist/DiscoAS.exe`。

---

## Q&A

Q:没有支持我使用的平台/软件诶இдஇ

```bash
A:以后。
```

Q:界面尺寸太大/太小了(#`Д´)ﾉ

```bash
A:设置里面可以调整的说。
```

Q:怎么歌曲播放完后直接停止播放/重复播放/播放歌单外歌曲？

```bash
A:DiscoAS只负责把你选中的歌曲交给对应客户端，不接管客户端的循环/随机播放模式。
当前队列行为因平台而异：网易云和酷狗会追加到当前队列；QQ会切到“试听列表”；Spotify不保证队列行为。
```

Q:为什么不支持同时启用多个歌单( ´•̥̥̥ω•̥̥̥` )

```bash
A:
当前设置模型只允许启用一个歌单或专辑。如果想混合多个来源，建议先在对应音乐平台创建一个合并后的歌单。
```

Q:怎么做到唤起本地应用的？

```bash
A:QQ音乐、酷狗音乐和Spotify使用各自的Scheme协议；网易云音乐使用本机CDP/WebSocket后台控制通道，把歌曲加入当前播放队列。
```

Q:web接口是怎么扒的？

```bash
A:参考现有第三方库和网上的信息，还有大语言模型的帮助。
```

Q:PR怎么说？

```bash
A:无论是人写的还是AI写的都接受，项目里的MD_FOR_AGENT就是为AGENT设置的
（虽然文档被作者自己的AGENT爆改了老大半，还有一些过时的内容）
只要你的AGENT（或者是……）不会在PR被拒后大写文章攻击我就行。
```

~~Q:大切なものって、なあに？~~

```bash
A:充電器
```

---

## 目前已知

- QQ 音乐当前使用 `playsong` Scheme，播放目标歌曲时会切换到“试听列表”，尚未实现保留原播放队列。
- Spotify Embed 降级数据可能只有前 50 首；需要完整分页时必须提供有效的 `SPOTIFY_ACCESS_TOKEN`。
- 网易云后台控制依赖当前客户端内部结构；客户端升级后若结构变化，可能需要同步适配。
- 当前仓库还没有 CI/CD 工作流。

## 未来

- 尝试支持更多平台（目前暂定酷我、汽水）

---

## 最后

本项目使用GPLv3协议，不仅是因为PyQT本身是GPLv3协议，更是因为本项目大量使用了各家音乐平台的web接口。

项目作者：[bilibili@蔡佩兰](https://space.bilibili.com/29285623  "点我去作者的B站空间")
