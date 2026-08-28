# DiscoAS - 发现一首歌！

<img src="src/DiscoAS.png" width="50%">

> 当前版本：`v1.1.0`

## 前言

在经典电子卡牌游戏《炉石传说》中，「发现」特指一种「从多种选项中挑选想要的一种」的操作。「多选一」这类操作早在《万智牌》中便已存在，但在UI、UX交互上，「发现」影响了无数作品，包括但不限于《杀戮尖塔》的卡牌战利品、《黑帝斯》的神明祝福、《吸血鬼幸存者》的升级……

而 **DiscoAS** 便是项目作者边炉边听歌的产物。在他一次次点击音乐软件的“下一首”按钮，试图在他那放了4500+曲目的歌单里随机到一首能符合当前心流的曲子，结果手滑把金铜须卖了，最后组件没凑齐被纯海盗阵营当路边一条踢到第5名，人叫得比金木研还痛之后，这个小项目借助大语言模型的力量，生まれた……

## v1.1.0 更新

- 设置改为自动保存并即时生效，设置窗口不再需要“应用并保存”或重启；保存成功后仅显示“修改已保存”。托盘中的“重启”仍作为手动故障处理入口保留。
- 网易云音乐改用本地 CDP/WebSocket 后台控制，可在不显示主界面的情况下冷启动、加入当前播放队列并确认目标歌曲开始播放。
- QQ 音乐支持后台冷启动和协议切歌，只抑制本次点歌新显示的窗口，不关闭用户原本已经打开的主界面。
- 酷狗音乐支持冷启动首次播放和后台切歌；发送协议前临时透明化隐藏主窗，避免切歌闪窗，并在结束后恢复窗口状态，允许用户主动打开客户端。
- 改进多平台歌单/专辑解析、缓存回退和启动流程，并补充对应的自动化测试。
- Spotify 本轮未调整播放方案，继续沿用现有 Scheme 和数据解析实现。

---
## 所以，怎么用？

<img src="src/Cap_showhow.gif" width="100%">

- 按下默认快捷键 `Alt+D`（可在设置中修改），或左键单击系统托盘图标，**发现**一首歌！
- 选择一首歌
- 然后听就完事了！

如果你突然不想选，可以通过ESC或右上角的取消键退出「发现」界面。

---

## 所以，怎么用上呢？

[本仓库 Releases](https://github.com/Narcissu-s1/DiscoAS/releases) 中有 Windows 打包文件时，可以下载压缩包，解压后双击 `DiscoAS.exe`。`v1.1.0` 标签包含本页所述源码；没有打包文件时，请按下方“Python 环境下运行”从源码启动。

---

## 那啥，前置？

当前仅支持 Windows 桌面系统，主要在 Windows 11 上验证。音乐软件目前支持：

- 网易云音乐
- QQ音乐
- 酷狗音乐
- Spotify

请先安装所使用平台的桌面客户端。QQ 音乐和酷狗音乐使用原生协议配合短时窗口抑制；Spotify 使用 Scheme；网易云音乐使用本地后台控制通道。

### 各平台当前播放行为

| 平台 | 歌单/专辑 | 选择歌曲后的行为 |
| --- | --- | --- |
| 网易云音乐 | 均支持 | 后台冷启动，将歌曲加入当前播放队列并确认立即播放，不显示或操作主界面。若网易云已经在运行但未启用后台控制，需要从托盘完全退出网易云后再试一次。 |
| QQ 音乐 | 均支持 | 后台启动并播放目标歌曲，短时抑制本次协议新显示的主窗口，同时保留用户原本已打开的窗口。目标歌曲仍会进入“试听列表”，尚不能可靠地追加到原播放队列。 |
| 酷狗音乐 | 均支持 | 后台冷启动或切歌，保留当前队列，将目标歌曲插入队列并立即播放，不添加到默认列表；协议触发的主窗口会被透明抑制，之后仍可由用户主动打开。 |
| Spotify | 均支持 | 通过 `spotify:track:` 唤起目标歌曲，不保证保留或修改 Spotify 当前队列。 |

程序预设了项目作者他那4500+曲目的小众歌单，如果你想要使用自己的歌单的话：

- 右键系统托盘图标进入「设置」
- 进入「发现设置」，选择「添加歌单」
- 选择对应平台，粘贴分享链接（或输入原有 ID），选择类型（歌单或专辑）
- 点击「加载」验证、获取真实名称并写入本地缓存，然后启用该项
- 设置会自动保存并立即生效，无需点击保存或重启应用；保存后左下角只显示“修改已保存”
- 同一时间只能启用一个歌单或专辑；歌单必须先“加载”成功，才能启用

### 各平台需要填写什么

输入框可以直接粘贴分享链接，也兼容原有 ID。加载成功后，程序会自动把输入内容规范化为内部使用的 ID 或短码。

| 平台 | 歌单 | 专辑 |
| --- | --- | --- |
| 网易云音乐 | 完整的 `https://music.163.com/playlist?id=123` 分享链接，或 `123` | 完整的 `https://music.163.com/album?id=456` 分享链接，或 `456` |
| QQ 音乐 | 完整的 `https://c6.y.qq.com/...` 短链、`https://y.qq.com/.../playlist/123` 链接，或 `123` | 完整的 QQ 音乐专辑链接、数字 `albumid` 或字符串 `albummid` |
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
A:QQ音乐使用原生临时协议文件，酷狗音乐使用 `kugou://play` 协议，两者配合短时窗口抑制实现后台点歌；Spotify使用自身Scheme；网易云音乐使用本机CDP/WebSocket后台控制通道，把歌曲加入当前播放队列。
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
- QQ 音乐的窗口抑制依赖当前客户端窗口类和启动时序；客户端升级后若窗口实现变化，可能需要重新适配。
- Spotify Embed 降级数据可能只有前 50 首；需要完整分页时必须提供有效的 `SPOTIFY_ACCESS_TOKEN`。
- 网易云后台控制依赖当前客户端内部结构；客户端升级后若结构变化，可能需要同步适配。
- 酷狗后台切歌依赖当前客户端的 `kugou_ui` 窗口类；客户端升级后若窗口实现变化，可能需要同步适配。
- 当前仓库还没有 CI/CD 工作流。

## 未来

- 尝试支持更多平台（目前暂定酷我、汽水）

---

## 最后

本项目使用GPLv3协议，不仅是因为PyQT本身是GPLv3协议，更是因为本项目大量使用了各家音乐平台的web接口。

项目作者：[bilibili@蔡佩兰](https://space.bilibili.com/29285623  "点我去作者的B站空间")
