# DiscoAS - 发现一首歌！

<img src=".\src\DiscoAS.png" width="50%">

## 前言

在经典电子卡牌游戏《炉石传说》中，「发现」特指一种「从多种选项中挑选想要的一种」的操作。「多选一」这类操作早在《万智牌》中便已存在，但在UI、UX交互上，「发现」影响了无数作品，包括但不限于《杀戮尖塔》的卡牌战利品、《黑帝斯》的神明祝福、《吸血鬼幸存者》的升级……

而 **DiscoAS** 便是项目作者边炉边听歌的产物。在他一次次点击音乐软件的“下一首”按钮，试图在他那放了4500+曲目的歌单里随机到一首能符合当前心流的曲子，结果手滑把金铜须卖了，最后组件没凑齐被纯海盗阵营当路边一条踢到第5名，人叫得比金木研还痛之后，这个小项目借助大语言模型的力量，生まれた……

---
## 所以，怎么用？

<img src=".\src\Cap_showhow.gif" width="100%">

- 按下快捷键 *（或着通过系统托盘）*，**发现**一首歌！
- 选择一首歌
- 然后听就完事了！

如果你突然不想选，可以通过ESC或右上角的取消键退出「发现」界面。

---

## 所以，怎么用上呢？

右边有一个release的区域，你能在那边下载到压缩包，解压后，双击运行```DiscoAS.exe```文件即可启动程序。

---

## 那啥，前置？

目前操作系统仅支持 Windows 11，音乐软件目前仅支持：

- 网易云音乐
- QQ音乐
- 酷狗音乐
- Spotify

由于是通过scheme url唤起本地应用（用过苹果的快捷指令的话，应该对这些词不陌生吧´-ω-)b），所以还请先安装你所使用的音乐平台对应的桌面软件捏。

程序预设了项目作者他那4500+曲目的小众歌单，如果你想要使用自己的歌单的话：

- 右键系统托盘图标进入「设置」
- 进入「发现设置」，选择「添加歌单」
- 选择歌单对应的平台，输入歌单ID，选择歌单类型（用户歌单or专辑）
- 启用并加载该专辑
- 「应用并保存」，等待应用重启

对于歌单ID↓

```bash
# 网易云音乐歌单id可以通过「分享」「复制链接」的方式获得
https://music.163.com/playlist?id={网易云音乐歌单id}

# QQ音乐歌单id需要将分享链接放在浏览器中才能获得
# 待浏览器跳转后，网址栏会显示如下链接
https://y.qq.com/n/ryqq_v2/playlist/{QQ音乐歌单id}?{问号后的参数不用理会}

# 酷狗音乐支持直接填写完整分享链接或其中的短码
# 兼容旧版 special 歌单和新版 share_type=collect 收藏集合
https://t1.kugou.com/{酷狗音乐分享短码}

# Spotify歌单id可以通过「分享」的方式获得
https://open.spotify.com/playlist/{Spotify歌单id}?si={不用管}

```

Spotify 未配置访问令牌时会使用 Embed 页面数据，这类数据可能只包含前 50 首，程序会将其标记为不完整。若要通过官方 Web API 完整分页，请先在 PowerShell 中设置访问令牌后再启动：

```powershell
$env:SPOTIFY_ACCESS_TOKEN="你的 Spotify OAuth 访问令牌"
.\start.cmd
```

Spotify 开发模式下，官方 API 只能读取当前账号拥有或参与协作的歌单；令牌过期后需要重新获取。

---

## Python环境下运行

在你克隆这个库后，依赖肯定是要安装的

```bash
pip install -r requirements.txt
```

然后

```bash
python main.py
```

即可启动程序

---

## 打包

该项目使用 Nuitka 打包

```bash
python -m nuitka --standalone `
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
A:这个项目管不了音乐平台的播放列表的说（没有那个威能）
确保原本播放列表和启用的歌单一致即可。
```

Q:为什么不支持同时启用多个歌单( ´•̥̥̥ω•̥̥̥` )

```bash
A:
①如果同时启用不同平台的歌单，那么音乐软件之间的声音会冲突（这个项目只管播放，不管暂停）；
②如果需要启用同一平台的不同歌单，那么完全可以在原平台创建一个新歌单；
③需要写大量的逻辑去处理同名歌曲；
④代码不允许，框架一开始就被写死了（
```

Q:怎么做到唤起本地应用的？

```bash
A:通过scheme_url协议，一般来说，通过查看音乐平台对应网页的F12信息(来源、网络)，可以推断出该平台的协议格式。
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

- QQ音乐的窗口无法在选择完成后关闭，确认原因为，没从歌曲json中提取歌曲注释导致窗口名称无法匹配
- 秘密歌曲选择后无法关闭窗口，虽然改起来很快，但是我突然想把这点当 **feature** 保留（毕竟还是要让用户知道自己随机到了什么歌）
- 由于是vibe coding项目，相比于一般python项目缺了许多东西（比如CICD啥的）

## 未来

- 尝试支持更多平台（目前暂定酷我、汽水）

---

## 最后

本项目使用GPLv3协议，不仅是因为PyQT本身是GPLv3协议，更是因为本项目大量使用了各家音乐平台的web接口。

项目作者：[bilibili@蔡佩兰](https://space.bilibili.com/29285623  "点我去作者的B站空间")
