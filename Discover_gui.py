"""
DiscoAS - 音乐选择器GUI (极简透明浮窗)

- 全屏透明浮窗，无边框
- 只显示歌曲卡片和关闭按钮
- 缓存机制：预加载下一批歌曲
"""

import json
import os
import sys
import threading
import time
import traceback

import keyboard
import requests
from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from load_playlist_json import Playlist

# 添加项目根目录到路径
sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__), 'settings'))

# 导入统一的路径管理模块
import contextlib

from settings.user_data_path import get_resource_dir, get_settings_dir

# 导入设置界面模块
with contextlib.suppress(ImportError):
    from settings.setting_gui import SettingsWindow

# 导入 i18n 模块
try:
    from settings import i18n
    _ = i18n.t
    print(f"[Discover_gui] i18n imported OK, lang={i18n.get_language()}")
    # 加载保存的语言设置
    try:
        gui_settings_file = os.path.join(get_settings_dir(), 'gui_settings.json')
        print(f"[Discover_gui] gui_settings_file={gui_settings_file}, exists={os.path.exists(gui_settings_file)}")
        if os.path.exists(gui_settings_file):
            with open(gui_settings_file, encoding='utf-8') as f:
                settings = json.load(f)
            lang = settings.get('language', 'zh_CN')
            print(f"[Discover_gui] setting lang to {lang}")
            i18n.set_language(lang)
    except Exception as e:
        print(f"[Discover_gui] i18n lang setting failed: {e}")
        pass
except ImportError as e:
    print(f"[Discover_gui] i18n ImportError: {e}")
    # 如果导入失败，创建一个简单的翻译函数
    def _(key):
        return key
except Exception as e:
    print(f"[Discover_gui] i18n Exception: {e}")
    def _(key):
        return key

# 全局引用，用于托盘控制
_main_window = None
_settings_window = None
_tray_icon = None
_shortcut_enabled = True
_hotkey_id = None
_shortcut_action = None  # 托盘菜单中的快捷键开关项
_discover_action = None
_settings_action = None
_restart_action = None
_quit_action = None
_network_manager = None  # 全局网络管理器

# 全局图片缓存 {url_or_path: bytes}
_image_cache = {}


def _fetch_image_data(url_or_path: str) -> bytes:
    """
    获取图片原始字节，同时支持：
    - 本地文件路径（绝对路径 / 相对路径，os.path.isfile 为真时直接读取）
    - http/https 网络 URL（使用 requests 下载）
    返回 bytes；失败时抛出异常。
    """
    if os.path.isfile(url_or_path):
        with open(url_or_path, 'rb') as f:
            return f.read()
    else:
        response = requests.get(url_or_path, timeout=10)
        if response.status_code == 200:
            return response.content
        raise Exception(f"HTTP 错误 {response.status_code}: {url_or_path[:80]}")

# 全局歌曲缓存（多批歌曲对象列表）
# 每批是一个 discover_songs() 返回的列表
_cached_song_batches = []

# 设置变化时递增代次，旧线程只能完成请求，不能提交旧结果。
_runtime_generation = 0
_cache_lock = threading.RLock()

# 预加载目标批数
_preload_target_batches = 0

# 全局标记：用户是否播放了歌曲
_user_played_song = False

# 全局 discover_app 实例，用于预加载
_global_discover_app_instance = None

# 预加载线程
_preload_thread = None
_preload_thread_generation = None

# 预加载歌曲数据线程
_preload_songs_thread = None


def get_runtime_generation():
    """返回当前运行态代次。"""
    with _cache_lock:
        return _runtime_generation


def invalidate_song_cache():
    """使旧歌曲任务失效，并原子清空运行时缓存。"""
    global _runtime_generation, _need_refresh_songs

    with _cache_lock:
        _runtime_generation += 1
        _cached_song_batches.clear()
        _image_cache.clear()
        generation = _runtime_generation
    _need_refresh_songs = True
    Playlist.clear_cache()
    return generation


def _take_cached_song_batch():
    with _cache_lock:
        if not _cached_song_batches:
            return None
        return _cached_song_batches.pop(0)


def preload_next_batch(discover_app):
    """
    在后台线程预加载多批歌曲（歌曲详情 + 封面图片），
    并将结果存入 _cached_song_batches，支持缓存批数设置。
    """
    global _preload_thread, _preload_target_batches, _preload_thread_generation

    # 获取缓存批数设置
    cache_batches = discover_app.music_setting.cache_batches

    # 如果缓存批数为0，禁用预加载
    if cache_batches <= 0:
        print("缓存批数设置为0，禁用预加载")
        return

    generation = get_runtime_generation()
    _preload_target_batches = cache_batches
    print(f"开始预加载，目标缓存批数: {cache_batches}")

    with _cache_lock:
        if (
            _preload_thread
            and _preload_thread.is_alive()
            and _preload_thread_generation == generation
        ):
            print("当前设置的预加载线程已在运行")
            return
        current_batches = len(_cached_song_batches)
        _preload_thread_generation = generation

    def _preload():
        try:
            # 计算还需要加载多少批
            batches_to_load = cache_batches - current_batches

            if batches_to_load <= 0:
                print(f"缓存已足够，当前 {current_batches} 批 >= 目标 {cache_batches} 批")
                return

            print(f"需要补充 {batches_to_load} 批歌曲...")

            for i in range(batches_to_load):
                if generation != get_runtime_generation():
                    print("预加载设置已变化，丢弃旧任务")
                    return
                print(f"开始预加载第 {i+1} 批歌曲...")
                # 1. 获取下一批歌曲
                songs = discover_app.discover_songs()
                if generation != get_runtime_generation():
                    return
                # 2. 加载每首歌的详情（含图片URL）
                for song in songs:
                    if not song.have_loaded:
                        song.load_song_detail()
                    if generation != get_runtime_generation():
                        return
                # 3. 下载封面图片到缓存（支持URL和本地路径）
                loaded_images = {}
                for song in songs:
                    url = song.get_album_pic_url()
                    with _cache_lock:
                        already_cached = url in _image_cache
                    if url and not already_cached:
                        try:
                            loaded_images[url] = _fetch_image_data(url)
                        except Exception as e:
                            print(f"图片预加载失败: {url[:50]}... - {e}")
                # 4. 仅允许当前代次原子提交结果
                with _cache_lock:
                    if generation != _runtime_generation:
                        print("预加载设置已变化，拒绝提交旧缓存")
                        return
                    _image_cache.update(loaded_images)
                    _cached_song_batches.append(songs)
                print(f"第 {i+1} 批预加载完成：{len(songs)} 首歌曲，新增 {len(loaded_images)} 张图片")

                # 每批之间稍作延迟，避免过于频繁
                time.sleep(0.1)

            with _cache_lock:
                total_songs = sum(len(batch) for batch in _cached_song_batches)
                batch_count = len(_cached_song_batches)
                image_count = len(_image_cache)
            print(f"所有预加载完成：共 {batch_count} 批，总计 {total_songs} 首歌曲，缓存共 {image_count} 张图片")
        except Exception as e:
            print(f"预加载失败: {e}")
            traceback.print_exc()

    _preload_thread = threading.Thread(target=_preload, daemon=True)
    _preload_thread.start()


class ImageLoader(QObject):
    """使用requests异步加载图片"""
    image_loaded = pyqtSignal(str, QPixmap)
    load_failed = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self._thread = None

    def load(self):
        # 使用线程加载图片
        self._thread = threading.Thread(target=self._load_image, daemon=True)
        self._thread.start()

    def _load_image(self):
        try:
            data = _fetch_image_data(self.url)
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self.image_loaded.emit(self.url, pixmap)
            else:
                self.load_failed.emit(self.url)
        except Exception as e:
            print(f"图片加载异常: {self.url} - {e}")
            self.load_failed.emit(self.url)


class SongCardWidget(QFrame):
    """歌曲卡片widget"""

    play_requested = pyqtSignal(object)  # 发送歌曲对象

    def __init__(self, song_card, index: int, gui_setting=None, preloaded_pixmap=None, parent=None, card_size=1.0):
        super().__init__(parent)
        self.song_card = song_card
        self.index = index
        self.image_loaded = False
        self.current_pixmap: QPixmap | None = None
        self.gui_setting = gui_setting
        self.image_loader = None
        self.card_size = card_size
        self._lift_anim = None
        self._original_pos = None

        self._setup_ui()

        # 如果有预加载的图片，直接使用圆角裁剪后显示
        if preloaded_pixmap:
            self.current_pixmap = preloaded_pixmap
            rounded = self._make_rounded_pixmap(preloaded_pixmap, self._cover_size, self._cover_radius)
            self.cover_label.setPixmap(rounded)
            self.image_loaded = True
        else:
            self._load_cover_image()

    def _get_card_style(self):
        """获取卡片样式"""
        if self.gui_setting:
            # 根据night_mode获取配置
            card_config = self.gui_setting.card_night_mode if self.gui_setting.night_mode else self.gui_setting.card
        else:
            # 默认配置
            card_config = {
                "background": "#FFFFFF",
                "background_hover": "#d0ebf0",
                "border": "#76e8fd",
                "font_color": "#000000"
            }

        bg = card_config.get("background", "#FFFFFF")
        bg_hover = card_config.get("background_hover", "#d0ebf0")
        border = card_config.get("border", "#76e8fd")

        return f"""
            QFrame {{
                background-color: {bg};
                border: 0px solid {border};
                border-radius: 16px;
            }}
            QFrame:hover {{
                background-color: {bg_hover};
                border: 4px solid {border};
            }}
        """

    def _get_font_color(self):
        """获取字体颜色"""
        if self.gui_setting:
            if self.gui_setting.night_mode:
                return self.gui_setting.card_night_mode.get("font_color", "#ffffff")
            else:
                return self.gui_setting.card.get("font_color", "#000000")
        return "#000000"

    def _get_secondary_font_color(self):
        """获取次级字体颜色（作者名）"""
        if self.gui_setting:
            if self.gui_setting.night_mode:
                color = self.gui_setting.card_night_mode.get("font_color", "#ffffff")
            else:
                color = self.gui_setting.card.get("font_color", "#000000")
            # 使用半透明
            if color.startswith("#") and len(color) == 7:
                r = int(color[1:3], 16)
                g = int(color[3:5], 16)
                b = int(color[5:7], 16)
                return f"rgba({r}, {g}, {b}, 0.7)"
        return "rgba(0, 0, 0, 0.7)"

    def _setup_ui(self):
        """设置UI"""
        # 基础尺寸（1.0时的值）
        base_width = 200
        base_height = 280
        base_cover_size = 175

        # 应用 card_size 缩放
        width = int(base_width * self.card_size)
        height = int(base_height * self.card_size)
        cover_size = int(base_cover_size * self.card_size)

        self.setFixedSize(width, height)
        self.setFrameStyle(QFrame.Shape.NoFrame)

        # 布局 - 内部间距也按比例缩放，缩小间距
        spacing = int(8 * self.card_size)  # 从 12 缩小到 8
        margin = int(10 * self.card_size)  # 从 15 缩小到 10
        layout = QVBoxLayout(self)
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)

        font_color = self._get_font_color()

        # 封面 - 添加右下角阴影
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(cover_size, cover_size)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 不使用 setScaledContents，改为手动生成圆角 pixmap
        self.cover_label.setScaledContents(False)
        # 强制设置透明背景
        self.cover_label.setAutoFillBackground(False)
        palette = self.cover_label.palette()
        palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.transparent)
        self.cover_label.setPalette(palette)
        # 圆角也按比例缩放（用于占位背景和 _make_rounded_pixmap）
        radius = int(12 * self.card_size)
        self._cover_radius = radius          # 供 _make_rounded_pixmap 使用
        self._cover_size = cover_size        # 供 _make_rounded_pixmap 使用
        self.cover_label.setStyleSheet(f"""
            background-color: rgba(200, 200, 200, 0.3);
            border-radius: {radius}px;
        """)

        # 添加右下角阴影
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(int(15 * self.card_size))
        shadow.setOffset(int(5 * self.card_size), int(5 * self.card_size))
        shadow.setColor(QColor(0, 0, 0, 80))  # 半透明黑色
        self.cover_label.setGraphicsEffect(shadow)

        layout.addWidget(self.cover_label)

        # 歌曲名 - 字体调小，随 card_size 缩放
        self.name_label = QLabel(self.song_card.get_name())
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        font = QFont()
        font.setBold(True)
        font.setPointSize(int(9 * self.card_size))  # 从 11 改为随 card_size 缩放
        self.name_label.setFont(font)
        # 强制设置透明背景
        self.name_label.setAutoFillBackground(False)
        palette = self.name_label.palette()
        palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.transparent)
        self.name_label.setPalette(palette)
        self.name_label.setStyleSheet(f"color: {font_color}; background-color: transparent; border: none;")
        layout.addWidget(self.name_label)

        # 艺术家 - 字体调小，随 card_size 缩放
        artist_names = self.song_card.get_artist_names()
        secondary_color = self._get_secondary_font_color()
        self.artist_label = QLabel("/".join(artist_names))
        self.artist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artist_label.setWordWrap(True)
        font_small = QFont()
        font_small.setPointSize(int(7 * self.card_size))  # 从 9 改为随 card_size 缩放
        self.artist_label.setFont(font_small)
        # 强制设置透明背景
        self.artist_label.setAutoFillBackground(False)
        palette = self.artist_label.palette()
        palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.transparent)
        self.artist_label.setPalette(palette)
        self.artist_label.setStyleSheet(f"color: {secondary_color}; background-color: transparent; border: none;")
        layout.addWidget(self.artist_label)

        # 样式 - 应用配置
        self.setStyleSheet(self._get_card_style())

        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # 添加整卡片阴影（与封面阴影样式一致）
        card_shadow = QGraphicsDropShadowEffect()
        card_shadow.setBlurRadius(int(30 * self.card_size))
        card_shadow.setOffset(int(10 * self.card_size), int(10 * self.card_size))
        card_shadow.setColor(QColor(0, 0, 0, 80))  # 半透明黑色
        self.setGraphicsEffect(card_shadow)

    def enterEvent(self, event):
        """鼠标进入卡片：向上浮起动画"""
        super().enterEvent(event)
        # 如果正在执行恢复动画，先停止，不更新 _original_pos（防止重复 hover 累积偏移）
        if self._lift_anim and self._lift_anim.state() == QPropertyAnimation.State.Running:
            self._lift_anim.stop()
        elif self._original_pos is None:
            # 正常情况：记录浮起前的位置
            self._original_pos = self.pos()

        self._lift_anim = QPropertyAnimation(self, b"pos")
        self._lift_anim.setDuration(180)
        self._lift_anim.setStartValue(self.pos())
        self._lift_anim.setEndValue(QPoint(self.pos().x(), self.pos().y() - 8))
        self._lift_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._lift_anim.start()

    def leaveEvent(self, event):
        """鼠标离开卡片：恢复原位动画"""
        super().leaveEvent(event)
        if self._lift_anim and self._lift_anim.state() == QPropertyAnimation.State.Running:
            self._lift_anim.stop()

        if self._original_pos is not None:
            self._lift_anim = QPropertyAnimation(self, b"pos")
            self._lift_anim.setDuration(200)
            self._lift_anim.setStartValue(self.pos())
            self._lift_anim.setEndValue(self._original_pos)
            self._lift_anim.setEasingCurve(QEasingCurve.Type.InCubic)
            self._lift_anim.start()

    @staticmethod
    def _make_rounded_pixmap(pixmap: QPixmap, size: int, radius: int) -> QPixmap:
        """
        将任意 QPixmap 缩放到 size×size 并裁剪为圆角矩形。
        返回带透明通道的圆角 QPixmap，不依赖 CSS border-radius。
        """
        # 目标画布：透明背景
        rounded = QPixmap(size, size)
        rounded.fill(Qt.GlobalColor.transparent)

        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 建立圆角裁剪路径
        path = QPainterPath()
        path.addRoundedRect(0, 0, size, size, radius, radius)
        painter.setClipPath(path)

        # 使用 KeepAspectRatio 模式，保持纵横比，完整显示在目标区域内
        scaled = pixmap.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        # 居中绘制
        x_off = (size - scaled.width()) // 2
        y_off = (size - scaled.height()) // 2
        painter.drawPixmap(x_off, y_off, scaled)
        painter.end()

        return rounded

    def _load_cover_image(self):
        """异步加载封面图"""
        url = self.song_card.get_album_pic_url()

        self.image_loader = ImageLoader(url, self)
        self.image_loader.image_loaded.connect(self._on_image_loaded)
        self.image_loader.load_failed.connect(self._on_load_failed)

        # 延迟加载
        QTimer.singleShot(50, self.image_loader.load)

    def _on_image_loaded(self, url: str, pixmap: QPixmap):
        """图片加载完成"""
        if url == self.song_card.get_album_pic_url():
            self.current_pixmap = pixmap
            # 使用圆角裁剪后再显示
            rounded = self._make_rounded_pixmap(pixmap, self._cover_size, self._cover_radius)
            self.cover_label.setPixmap(rounded)
            self.image_loaded = True

    def _on_load_failed(self, url: str):
        """图片加载失败"""
        print(f"图片加载失败: {url}")

    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.play_requested.emit(self.song_card)
        super().mousePressEvent(event)


# 全局标记：是否需要刷新歌曲
_need_refresh_songs = False


class DiscoverOverlay(QMainWindow):
    """极简全屏透明浮窗主界面"""

    # 自定义信号：歌曲加载完成
    songs_loaded = pyqtSignal(int, int, list, list)

    # 窗口透明度属性
    window_opacity = 1.0

    def __init__(self, discover_app, parent=None):
        super().__init__(parent)
        self.discover_app = discover_app
        self.songs: list = []
        self.next_songs: list = []  # 缓存下一批歌曲
        self.load_thread = None
        self._load_generation = 0
        self._runtime_generation = get_runtime_generation()

        # 每次创建窗口时重新加载音乐设置，确保使用最新设置
        self.discover_app.music_setting.load()

        # 获取GUI设置
        self.gui_setting = discover_app.gui_setting

        # 动画相关
        self._open_anim = None
        self._close_anim = None
        self._closing = False  # 防止关闭动画期间重复触发

        self._setup_ui()

        # 连接信号
        self.songs_loaded.connect(self._on_songs_loaded)

        # 检查是否需要刷新歌曲
        global _need_refresh_songs, _user_played_song

        # 如果用户播放了歌曲，下次进入需要刷新（清除缓存）
        if _user_played_song:
            _user_played_song = False  # 重置标记
            _need_refresh_songs = True
            print("用户播放过歌曲，下次进入将刷新")

        should_refresh = _need_refresh_songs
        if not should_refresh:
            # 检查设置：refreshing_after_cancel
            should_refresh = self.discover_app.music_setting.refreshing_after_cancel

        # 优先判断：预加载是否已经准备好了新歌曲
        # 只要 _cached_song_batches 不为空，说明预加载线程已经完成，
        # 直接使用，避免重新异步加载导致"加载中..."延迟
        batch = _take_cached_song_batch()
        if batch is not None:
            # 取出一批歌曲使用
            with _cache_lock:
                remaining_batches = len(_cached_song_batches)
            print(f"使用预加载缓存的歌曲，共 {len(batch)} 首（跳过刷新逻辑），剩余 {remaining_batches} 批")
            _need_refresh_songs = False
            self.songs = batch
            # 保留剩余的缓存，用于下次使用
            # 触发预加载补充缓存
            preload_next_batch(self.discover_app)
            self._display_songs()
        elif should_refresh:
            # 没有预加载缓存，且需要刷新：清除 Playlist 缓存后重新加载
            _need_refresh_songs = False
            Playlist.clear_cache()
            print("无预加载缓存，需要刷新，重新加载歌曲...")
            self._load_songs()
        else:
            # 没有缓存，也不需要刷新：直接加载
            print("无预加载缓存，直接加载歌曲...")
            self._load_songs()

    def _get_close_button_style(self):
        """获取关闭按钮样式"""
        if self.gui_setting:
            # 根据night_mode获取配置
            if self.gui_setting.night_mode:
                btn_config = self.gui_setting.cancel_button_night_mode
            else:
                btn_config = self.gui_setting.cancel_button
            cancel_btn_size = self.gui_setting.cancel_button_size
        else:
            # 默认配置
            btn_config = {
                "background": "#FFFFFF",
                "background_hover": "#f5d5d0",
                "border": "#d6533e",
                "font_color": "#000000"
            }
            cancel_btn_size = 1.0

        bg = btn_config.get("background", "#FFFFFF")
        bg_hover = btn_config.get("background_hover", "#f5d5d0")
        border = btn_config.get("border", "#d6533e")
        font_color = btn_config.get("font_color", "#000000")

        # 圆角和字体大小也按比例缩放
        radius = int(25 * cancel_btn_size)
        font_size = int(20 * cancel_btn_size)

        return f"""
            QPushButton {{
                background-color: {bg};
                color: {font_color};
                border: 2px solid {border};
                border-radius: {radius}px;
                font-size: {font_size}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {bg_hover};
                border: 4px solid {border};
            }}
            QPushButton:pressed {{
                background-color: {bg_hover};
                border: 4px solid {border};
            }}
        """

    def _setup_ui(self):
        """设置极简UI"""
        # 全屏无边框透明窗口 - 使用 FramelessWindowHint + WindowStaysOnTopHint
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        # 不在这里调用 showFullScreen()，由 show_overlay 控制

        # 中央widget - 完全透明
        central = QWidget()
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        central.setStyleSheet("background: transparent;")
        self.setCentralWidget(central)

        # 主布局 - 使用 QGridLayout 让按钮和卡片区域独立定位
        main_layout = QGridLayout(central)
        main_layout.setContentsMargins(50, 50, 50, 50)
        main_layout.setRowStretch(0, 0)   # 按钮行不拉伸
        main_layout.setRowStretch(1, 1)   # 卡片行占满剩余空间
        main_layout.setColumnStretch(0, 1)  # 列全拉伸

        # 右上角关闭按钮 - 应用 cancel_button_size 配置
        close_btn_size = int(50 * (self.gui_setting.cancel_button_size if self.gui_setting else 1.0))
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(close_btn_size, close_btn_size)
        close_btn.setStyleSheet(self._get_close_button_style())
        close_btn.clicked.connect(self._on_close)

        # 歌曲卡片区域 - 可滚动 - 完全透明
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollArea QWidget QScrollBar:vertical {
                background: rgba(255, 255, 255, 0.1);
                width: 8px;
                border-radius: 4px;
            }
            QScrollArea QWidget QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.3);
                border-radius: 4px;
            }
        """)

        # 卡片容器 - 完全透明
        self.song_container = QWidget()
        self.song_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.song_container.setStyleSheet("background: transparent;")
        self.song_layout = QGridLayout(self.song_container)
        # 增加间距到 45 (原 25 + 额外 20)
        self.song_layout.setSpacing(45)

        scroll.setWidget(self.song_container)

        # Grid 布局：按钮在右上角(0,1)，卡片在下方占满(1,0)-(1,1)
        main_layout.addWidget(close_btn, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        main_layout.addWidget(scroll, 1, 0, 1, 2)

    def paintEvent(self, event):
        """完全透明背景"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 完全透明
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect())

    def _load_songs(self):
        """加载歌曲（显示用 + 缓存用）"""
        # 显示加载状态
        self._display_loading()

        # 新代次可与旧线程并行；旧线程的结果会在信号回调处被丢弃。
        self._load_generation += 1
        load_generation = self._load_generation
        runtime_generation = self._runtime_generation
        self.load_thread = threading.Thread(
            target=self._load_songs_async,
            args=(load_generation, runtime_generation),
            daemon=True,
        )
        self.load_thread.start()

    def _preload_images(self):
        """预加载所有歌曲封面图片到缓存"""

        for song in self.songs:
            url = song.get_album_pic_url()
            print(f"图片URL: {url}")
            if url and url not in _image_cache:
                try:
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        _image_cache[url] = response.content
                        print(f"预加载成功: {url[:50]}...")
                except Exception as e:
                    print(f"预加载失败: {url[:50]}... - {e}")

        print(f"预加载完成，共 {len(_image_cache)} 张图片")

    def _load_songs_async(self, load_generation, runtime_generation):
        """异步加载歌曲"""
        try:
            print("开始加载歌曲...")
            # 加载显示用歌曲
            songs = self.discover_app.discover_songs()
            if runtime_generation != get_runtime_generation():
                return
            print(f"加载到 {len(songs)} 首歌曲")

            # 先加载歌曲详情（这样才能获取到图片URL）
            for song in songs:
                if not song.have_loaded:
                    song.load_song_detail()
                if runtime_generation != get_runtime_generation():
                    return

            # 加载下一批缓存（只加载歌曲，不下载图片）
            next_songs = self.discover_app.discover_songs()
            if runtime_generation != get_runtime_generation():
                return
            print("缓存加载完成")

            # 使用信号槽更新UI - 确保使用 QueuedConnection
            self.songs_loaded.emit(load_generation, runtime_generation, songs, next_songs)
            print("信号已发送")
        except Exception as e:
            print(f"加载歌曲失败: {e}")
            traceback.print_exc()
            if runtime_generation != get_runtime_generation():
                print("忽略已失效加载任务的错误提示")
                return
            # 根据异常类型弹窗
            if isinstance(e, FileNotFoundError):
                try:
                    app = QApplication.instance()
                    if app:
                        QMessageBox.warning(
                            None,
                            _("playlist_file_not_found"),
                            _("playlist_file_not_found_msg")
                        )
                except Exception:
                    pass
            if runtime_generation == get_runtime_generation():
                self.songs_loaded.emit(load_generation, runtime_generation, [], [])

    def _on_songs_loaded(self, load_generation, runtime_generation, songs, next_songs):
        """歌曲加载完成回调"""
        if (
            load_generation != self._load_generation
            or runtime_generation != self._runtime_generation
            or runtime_generation != get_runtime_generation()
        ):
            print("忽略已失效的浮窗歌曲加载结果")
            return
        self.songs = songs
        self.next_songs = next_songs
        self._display_songs()

    def invalidate_pending_loads(self):
        """让当前浮窗仍在运行的旧加载任务失效。"""
        self._load_generation += 1
        self._runtime_generation = get_runtime_generation()

    def reload_for_settings(self):
        """在当前进程内按新设置重新加载歌曲与界面。"""
        self.invalidate_pending_loads()
        self.discover_app.gui_setting.load()
        self.discover_app.music_setting.load()
        self.gui_setting = self.discover_app.gui_setting
        self.songs = []
        self.next_songs = []
        self._setup_ui()
        self._load_songs()

    def apply_visual_settings(self):
        """不重新抽取歌曲，只重建当前浮窗的样式与尺寸。"""
        self.discover_app.gui_setting.load()
        self.gui_setting = self.discover_app.gui_setting
        self._setup_ui()
        if self.songs:
            self._display_songs()
        else:
            self._display_loading()

    def _get_loading_style(self):
        """获取加载中小长方形的样式"""
        # 获取卡片尺寸设置
        card_size = self.gui_setting.card_size if self.gui_setting else 1.0

        if self.gui_setting:
            card_config = self.gui_setting.card_night_mode if self.gui_setting.night_mode else self.gui_setting.card
        else:
            card_config = {
                "background": "#FFFFFF",
                "font_color": "#000000"
            }

        bg = card_config.get("background", "#FFFFFF")
        font_color = card_config.get("font_color", "#000000")

        # 基础尺寸，随 card_size 缩放
        width = int(100 * card_size)
        height = int(40 * card_size)
        radius = int(8 * card_size)
        font_size = int(12 * card_size)

        return bg, font_color, width, height, radius, font_size

    def _display_loading(self):
        """显示加载中状态"""
        # 清空现有卡片
        while self.song_layout.count():
            item = self.song_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 获取加载中样式配置
        bg, font_color, width, height, radius, font_size = self._get_loading_style()

        # 创建小长方形加载中容器
        loading_card = QFrame()
        loading_card.setFixedSize(width, height)
        loading_card.setFrameStyle(QFrame.Shape.NoFrame)
        loading_card.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: none;
                border-radius: {radius}px;
            }}
        """)

        # 加载中文字
        loading_label = QLabel(_("loading"))
        loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setBold(True)
        font.setPointSize(font_size)
        loading_label.setFont(font)
        loading_label.setStyleSheet(f"color: {font_color}; background-color: transparent;")

        # 使用水平布局居中
        layout = QHBoxLayout(loading_card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(loading_label)

        self.song_layout.addWidget(loading_card, 0, 0)

    def _display_no_cards(self):
        """显示没有卡牌提示"""
        # 清空现有卡片
        while self.song_layout.count():
            item = self.song_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 获取样式配置
        card_size = self.gui_setting.card_size if self.gui_setting else 1.0

        if self.gui_setting:
            card_config = self.gui_setting.card_night_mode if self.gui_setting.night_mode else self.gui_setting.card
        else:
            card_config = {
                "background": "#FFFFFF",
                "font_color": "#000000"
            }

        bg = card_config.get("background", "#FFFFFF")
        font_color = card_config.get("font_color", "#000000")

        # 基础尺寸，随 card_size 缩放
        width = int(280 * card_size)
        height = int(100 * card_size)
        radius = int(12 * card_size)
        font_size = int(11 * card_size)

        # 创建提示卡片容器
        no_cards_card = QFrame()
        no_cards_card.setFixedSize(width, height)
        no_cards_card.setFrameStyle(QFrame.Shape.NoFrame)
        no_cards_card.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: none;
                border-radius: {radius}px;
            }}
        """)

        # 提示文字 - 使用换行符
        no_cards_label = QLabel(_("no_cards"))
        no_cards_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_cards_label.setWordWrap(True)  # 启用自动换行
        font = QFont()
        font.setBold(True)
        font.setPointSize(font_size)
        no_cards_label.setFont(font)
        no_cards_label.setStyleSheet(f"color: {font_color}; background-color: transparent;")

        # 使用水平布局居中
        layout = QHBoxLayout(no_cards_card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(no_cards_label)

        self.song_layout.addWidget(no_cards_card, 0, 0)

    def _get_font_color_for_label(self):
        """获取标签字体颜色"""
        if self.gui_setting:
            if self.gui_setting.night_mode:
                return self.gui_setting.card_night_mode.get("font_color", "#ffffff")
            else:
                return self.gui_setting.card.get("font_color", "#000000")
        return "#ffffff"

    def _display_songs(self):
        """显示歌曲卡片"""
        # 清空现有卡片
        while self.song_layout.count():
            item = self.song_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 检查是否有歌曲，没有则显示提示
        if not self.songs or len(self.songs) == 0:
            self._display_no_cards()
            return

        # 不再等待预加载完成，直接使用缓存图片，没有则异步加载
        columns = 5
        # 获取卡片尺寸设置
        card_size = self.gui_setting.card_size if self.gui_setting else 1.0

        for i, song in enumerate(self.songs):
            if not song.have_loaded:
                song.load_song_detail()

            # 检查是否有缓存的图片数据
            url = song.get_album_pic_url()
            cached_data = _image_cache.get(url)

            # 如果有缓存，直接使用
            if cached_data:
                pixmap = QPixmap()
                pixmap.loadFromData(cached_data)
                card = SongCardWidget(song, i, self.gui_setting, pixmap, card_size=card_size)
            else:
                # 没有缓存，让卡片自己加载
                card = SongCardWidget(song, i, self.gui_setting, card_size=card_size)

            card.play_requested.connect(self._on_song_play)

            tag = "[秘密歌曲]" if song.mystery_mode else ""
            debug_info = song.get_debug_info()
            print(f"[调试] 展示歌曲 {i+1}: {debug_info} {tag}")

            row = i // columns
            col = i % columns
            self.song_layout.addWidget(card, row, col)

    def _on_song_play(self, song_card):
        """播放歌曲"""
        # 标记用户播放了歌曲，下次进入需要刷新
        global _user_played_song
        _user_played_song = True
        print(f"[调试] 用户选择歌曲，窗口名称: {song_card.get_window_name()}")
        print("用户播放了歌曲，标记为已播放")

        # 立即触发关闭动画（不等播放完成）
        self._on_close()

        # 播放和预加载放到后台线程
        def _background():
            self.discover_app.play_song(song_card)
            preload_next_batch(self.discover_app)
        threading.Thread(target=_background, daemon=True).start()

    def _handle_cancel_state(self):
        """处理用户取消/关闭时的缓存状态，供 _on_close 和 keyPressEvent 共用"""
        global _need_refresh_songs, _user_played_song

        if self.discover_app.music_setting.refreshing_after_cancel:
            _need_refresh_songs = True
            print("取消选择后刷新=True，下次进入将刷新")
        elif not _user_played_song and self._runtime_generation == get_runtime_generation():
            with _cache_lock:
                _cached_song_batches.insert(0, self.songs.copy())
            print("用户未选歌，将当前歌曲插回队头")
        else:
            print("用户已选歌，当前歌曲已释放，保留其他预加载批次")

    def _on_close(self):
        """关闭/退出时触发"""
        print("关闭窗口被触发")
        self._handle_cancel_state()

        def _do_hide():
            self.hide()
            preload_next_batch(self.discover_app)

        self.play_close_animation(_do_hide)

    def closeEvent(self, event):
        """窗口关闭事件"""
        print("closeEvent 被触发")
        event.ignore()  # 忽略关闭事件，只隐藏
        self.hide()

    def keyPressEvent(self, event):
        """键盘按键事件"""
        print(f"按键被按下: {event.key()}")
        # ESC 键不关闭窗口，直接隐藏
        if event.key() == Qt.Key.Key_Escape:
            print("ESC 被按下，隐藏窗口")
            self._handle_cancel_state()

            def _do_hide():
                self.hide()
                preload_next_batch(self.discover_app)

            self.play_close_animation(_do_hide)
            return
        super().keyPressEvent(event)

    def play_open_animation(self):
        """弹入淡入动画（打开时）"""
        # 停止任何正在播放的关闭动画
        if self._close_anim and self._close_anim.state() == QPropertyAnimation.State.Running:
            self._close_anim.stop()
        if hasattr(self, '_close_pos_anim') and self._close_pos_anim and \
                self._close_pos_anim.state() == QPropertyAnimation.State.Running:
            self._close_pos_anim.stop()
        self._closing = False

        # 记录窗口正常位置
        normal_pos = self.pos()
        start_pos = QPoint(normal_pos.x(), normal_pos.y() + 40)

        # --- 弹入位移动画（窗口 pos：从 y+40 弹入到 y）---
        self._open_pos_anim = QPropertyAnimation(self, b"pos")
        self._open_pos_anim.setDuration(380)
        self._open_pos_anim.setStartValue(start_pos)
        self._open_pos_anim.setEndValue(normal_pos)
        self._open_pos_anim.setEasingCurve(QEasingCurve.Type.OutBack)

        # --- 淡入动画（windowOpacity: 0 → 1）---
        self.setWindowOpacity(0.0)
        self.move(start_pos)  # 先移到起始位置
        self._open_anim = QPropertyAnimation(self, b"windowOpacity")
        self._open_anim.setDuration(320)
        self._open_anim.setStartValue(0.0)
        self._open_anim.setEndValue(1.0)
        self._open_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._open_pos_anim.start()
        self._open_anim.start()

    def play_close_animation(self, callback):
        """弹出淡出动画（关闭时），动画结束后执行 callback"""
        if self._closing:
            return
        self._closing = True

        # 停止任何正在播放的打开动画
        if self._open_anim and self._open_anim.state() == QPropertyAnimation.State.Running:
            self._open_anim.stop()
        if hasattr(self, '_open_pos_anim') and self._open_pos_anim and \
                self._open_pos_anim.state() == QPropertyAnimation.State.Running:
            self._open_pos_anim.stop()

        normal_pos = self.pos()
        end_pos = QPoint(normal_pos.x(), normal_pos.y() + 20)

        # --- 弹出位移动画（窗口 pos：向下 +20px）---
        self._close_pos_anim = QPropertyAnimation(self, b"pos")
        self._close_pos_anim.setDuration(220)
        self._close_pos_anim.setStartValue(normal_pos)
        self._close_pos_anim.setEndValue(end_pos)
        self._close_pos_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        # --- 淡出动画（windowOpacity: 当前 → 0）---
        self._close_anim = QPropertyAnimation(self, b"windowOpacity")
        self._close_anim.setDuration(220)
        self._close_anim.setStartValue(self.windowOpacity())
        self._close_anim.setEndValue(0.0)
        self._close_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        # 动画结束后执行回调
        self._close_anim.finished.connect(callback)

        self._close_pos_anim.start()
        self._close_anim.start()

    def focusOutEvent(self, event):
        """窗口失去焦点事件"""
        print("窗口失去焦点")
        # 不自动隐藏，只打印日志
        super().focusOutEvent(event)


# 全局app实例，用于快捷键回调
_global_app = None
_global_discover_app = None


def create_tray_icon(app, discover_app):
    """创建系统托盘"""
    global _tray_icon, _main_window, _shortcut_enabled, _shortcut_action, _global_app, _global_discover_app
    global _discover_action, _settings_action, _restart_action, _quit_action

    # _main_window 应该是 DiscoverOverlay 窗口对象，不是 discover_app
    # _main_window 在 show_overlay 中设置
    _global_app = app
    _global_discover_app = discover_app

    # 创建托盘图标
    tray = QSystemTrayIcon()

    # 尝试加载图标，如果失败使用默认
    icon_path = os.path.join(get_resource_dir(), "src", "Icon.ico")
    if os.path.exists(icon_path):
        tray.setIcon(QIcon(icon_path))
    else:
        # 创建一个简单的图标
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(0, 0, 0, 0))
        p = QPainter(pixmap)
        p.setBrush(QColor(118, 232, 253))
        p.drawEllipse(8, 8, 48, 48)
        p.end()
        tray.setIcon(QIcon(pixmap))

    tray.setToolTip("DiscoAS - " + _("discover"))

    # 创建右键菜单
    menu = QMenu()

    # 发现歌曲
    discover_action = QAction(_("discover"), menu)
    _discover_action = discover_action
    font = QFont()
    font.setBold(True)
    discover_action.setFont(font)
    discover_action.triggered.connect(lambda: show_overlay(app, discover_app))
    menu.addAction(discover_action)

    menu.addSeparator()

    # 设置
    settings_action = QAction(_("settings"), menu)
    _settings_action = settings_action
    settings_action.triggered.connect(open_settings)
    menu.addAction(settings_action)

    menu.addSeparator()

    # 暂停/启用快捷键
    _shortcut_action = QAction(_("pause_shortcut"), menu)
    _shortcut_action.triggered.connect(lambda: toggle_shortcut(app, discover_app))
    menu.addAction(_shortcut_action)

    menu.addSeparator()

    # 重启
    restart_action = QAction(_("restart"), menu)
    _restart_action = restart_action
    restart_action.triggered.connect(restart_from_tray)
    menu.addAction(restart_action)

    menu.addSeparator()

    # 退出
    quit_action = QAction(_("quit"), menu)
    _quit_action = quit_action
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)

    # 左键点击显示浮窗 - 使用队列连接确保线程安全
    def on_tray_clicked(reason):
        # 只响应左键单击（Trigger），忽略右键菜单（Context）和其他事件
        if reason == QSystemTrayIcon.ActivationReason.Context:
            # 右键点击不处理，让系统显示上下文菜单
            return
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            show_overlay(app, discover_app)

    tray.activated.connect(on_tray_clicked)

    tray.show()
    _tray_icon = tray

    return tray


def refresh_translated_ui():
    """即时刷新无需重建进程的托盘文字。"""
    if _tray_icon:
        _tray_icon.setToolTip("DiscoAS - " + _("discover"))
    if _discover_action:
        _discover_action.setText(_("discover"))
    if _settings_action:
        _settings_action.setText(_("settings"))
    if _shortcut_action:
        _shortcut_action.setText(_("pause_shortcut") if _shortcut_enabled else _("enable_shortcut"))
    if _restart_action:
        _restart_action.setText(_("restart"))
    if _quit_action:
        _quit_action.setText(_("quit"))


# 全局快捷键widget
_shortcut_widget = None
_shortcut_parent = None  # 隐藏的父窗口


def toggle_shortcut(app, discover_app):
    """切换快捷键启用状态"""
    global _shortcut_enabled, _shortcut_widget

    _shortcut_enabled = not _shortcut_enabled

    if _shortcut_enabled:
        # 启用快捷键 - 使用PyQt全局快捷键
        shortcut = discover_app.music_setting.shortcut_key
        if _shortcut_widget:
            _shortcut_widget.setEnabled(True)
        print(f"快捷键已启用: {shortcut}")
    else:
        # 禁用快捷键
        if _shortcut_widget:
            _shortcut_widget.setEnabled(False)
        print("快捷键已暂停")

    # 更新托盘菜单文字 - 直接更新 _shortcut_action 的文本
    if _shortcut_action:
        _shortcut_action.setText(_("pause_shortcut") if _shortcut_enabled else _("enable_shortcut"))


def show_overlay(app, discover_app):
    """显示全屏浮窗"""
    global _main_window

    print("show_overlay 被调用")

    # 每次显示浮窗时，重新加载所有设置，确保使用最新设置
    discover_app.gui_setting.load()
    discover_app.music_setting.load()

    # 应用语言设置到 i18n
    with contextlib.suppress(BaseException):
        i18n.set_language(discover_app.gui_setting.language)

    print(f"已重新加载设置: GUI card_size={discover_app.gui_setting.card_size}, night_mode={discover_app.gui_setting.night_mode}, language={discover_app.gui_setting.language}, refreshing_after_cancel={discover_app.music_setting.refreshing_after_cancel}")

    # 检查是否已有窗口显示
    if _main_window is not None and _main_window.isVisible():
        print("窗口已存在，直接显示")
        _main_window.show()
        _main_window.raise_()
        _main_window.activateWindow()
        return

    # 每次都创建新窗口，确保全新的歌曲列表
    _main_window = DiscoverOverlay(discover_app)
    print("DiscoverOverlay 创建完成")

    # 设置窗口图标为托盘图标
    if _tray_icon:
        _main_window.setWindowIcon(_tray_icon.icon())

    # 显示窗口并播放弹入淡入动画
    _main_window.show()
    _main_window.showFullScreen()
    _main_window.raise_()
    _main_window.activateWindow()
    _main_window.play_open_animation()

    print("窗口已显示")


def apply_runtime_settings(discover_app, *, reload_songs=False, reload_visual=False):
    """在当前进程内重新加载配置，并只刷新受影响的运行态。"""
    discover_app.gui_setting.load()
    discover_app.music_setting.load()
    discover_app._apply_settings()

    with contextlib.suppress(BaseException):
        i18n.set_language(discover_app.gui_setting.language)

    if reload_songs:
        invalidate_song_cache()
        if _main_window is not None:
            if _main_window.isVisible():
                _main_window.reload_for_settings()
            else:
                _main_window.invalidate_pending_loads()
        preload_next_batch(discover_app)
    elif reload_visual and _main_window is not None and _main_window.isVisible():
        _main_window.apply_visual_settings()


def open_settings():
    """打开设置窗口"""
    global _settings_window
    try:
        if _settings_window is not None and _settings_window.isVisible():
            _settings_window.raise_()
            _settings_window.activateWindow()
            return
        _settings_window = SettingsWindow()
        _settings_window.show()
    except Exception as e:
        print(f"打开设置窗口失败: {e}")


def reopen_settings_window(old_window):
    """语言变化后用新窗口替换旧窗口，避免在同一 Qt 对象上重复初始化。"""
    global _settings_window

    geometry = old_window.geometry()
    page_index = old_window.stack.currentIndex()
    old_window.close()
    _settings_window = SettingsWindow()
    _settings_window.setGeometry(geometry)
    _settings_window.stack.setCurrentIndex(page_index)
    button = _settings_window.btn_group.button(page_index)
    if button:
        button.setChecked(True)
    _settings_window.show()


def restart_from_tray() -> None:
    """从托盘菜单手动重启应用。"""
    import os
    import subprocess
    import sys

    exe_dir = os.path.dirname(sys.executable)
    exe_path = os.path.join(exe_dir, "DiscoAS.exe")
    if os.path.exists(exe_path):
        subprocess.Popen([exe_path])
    else:
        # fallback：开发环境用 python main.py
        script_path = os.path.join(os.path.dirname(__file__), "main.py")
        subprocess.Popen([sys.executable, script_path])
    QApplication.instance().quit()


# 全局变量用于跨线程调用
_global_app_ref = None
_global_discover_app_ref = None

# 全局信号：设置已保存，需要重新加载
_settings_changed_signal = None


class ShortcutSignalEmitter(QObject):
    """用于在主线程中触发快捷键回调的信号发射器"""
    shortcut_triggered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.shortcut_triggered.connect(self._on_shortcut_triggered)

    def _on_shortcut_triggered(self):
        """在主线程中执行的回调"""
        if _global_app_ref and _global_discover_app_ref:
            show_overlay(_global_app_ref, _global_discover_app_ref)


# 全局信号发射器
_shortcut_emitter = None

# 保存快捷键回调和keyboard句柄，用于重新注册
_shortcut_callback = None
_keyboard_handle = None
_current_shortcut = "alt+d"


_keyboard_hook_check_timer = None


def _start_keyboard_hook_monitor(app, discover_app):
    """启动键盘钩子健康检查定时器，每 30 秒检测一次"""
    global _keyboard_hook_check_timer

    if _keyboard_hook_check_timer is not None:
        _keyboard_hook_check_timer.stop()

    def check_and_reregister():
        global _keyboard_handle, _shortcut_callback, _current_shortcut
        try:
            # 尝试读取 Alt 键状态，如果键盘钩子失效会抛异常
            keyboard.is_pressed('alt')
        except Exception:
            print("[快捷键] 钩子失效，重新注册")
            with contextlib.suppress(Exception):
                keyboard.remove_hotkey(_keyboard_handle)
            try:
                _keyboard_handle = keyboard.add_hotkey(_current_shortcut, _shortcut_callback)
                print("[快捷键] 重新注册成功")
            except Exception as e:
                print(f"[快捷键] 重新注册失败: {e}")

    _keyboard_hook_check_timer = QTimer()
    _keyboard_hook_check_timer.timeout.connect(check_and_reregister)
    _keyboard_hook_check_timer.start(30000)  # 每 30 秒检查一次


def register_global_shortcut(app, discover_app, shortcut="alt+d"):
    """注册全局快捷键 - 使用keyboard库"""
    global _shortcut_enabled, _global_app_ref, _global_discover_app_ref, _shortcut_emitter, _shortcut_parent, _shortcut_widget
    global _shortcut_callback, _keyboard_handle, _current_shortcut

    # 保存全局引用
    _global_app_ref = app
    _global_discover_app_ref = discover_app
    _current_shortcut = shortcut

    # 创建信号发射器（在主线程中创建）
    _shortcut_emitter = ShortcutSignalEmitter()

    try:
        # 先移除旧的快捷键（如果存在）
        if _keyboard_handle is not None:
            with contextlib.suppress(BaseException):
                keyboard.remove_hotkey(_keyboard_handle)

        def on_shortcut():
            if _shortcut_enabled:
                # 检查修饰键是否实际按下（防止单独按字母键时误触发）
                try:
                    if not keyboard.is_pressed('alt'):
                        return
                except Exception:
                    pass  # is_pressed 失败时继续执行
                print(f"快捷键 {shortcut} 被触发")
                # 通过信号机制在主线程中调用
                # PyQt 信号发射是线程安全的
                _shortcut_emitter.shortcut_triggered.emit()

        _shortcut_callback = on_shortcut
        # 注册全局快捷键
        _keyboard_handle = keyboard.add_hotkey(shortcut, on_shortcut)
        print(f"全局快捷键已注册: {shortcut}")

        # 启动键盘钩子健康检查（每 30 秒检测一次）
        _start_keyboard_hook_monitor(app, discover_app)
    except Exception as e:
        print(f"注册全局快捷键失败: {e}")
        print("将使用PyQt快捷键作为后备方案")
        # 后备：使用 PyQt 的全局快捷键
        # 创建一个不可见但可接收事件的窗口
        _shortcut_parent = QWidget()
        _shortcut_parent.setWindowTitle("ShortcutHost")
        # 使用 FramelessWindowHint 和 始终在最前，但不显示
        _shortcut_parent.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        # 将窗口移到屏幕外但保持活动状态
        _shortcut_parent.move(-10000, -10000)
        _shortcut_parent.show()
        _shortcut_parent.hide()  # 立即隐藏但窗口仍然存在

        # 删除旧的快捷键widget
        if _shortcut_widget:
            _shortcut_widget.deleteLater()

        _shortcut_widget = QShortcut(QKeySequence(shortcut), _shortcut_parent)
        _shortcut_widget.activated.connect(lambda: show_overlay(app, discover_app))
        print(f"PyQt全局快捷键已注册: {shortcut}")


def reregister_shortcut(app, discover_app):
    """重新注册快捷键（当设置更改时调用）"""
    global _current_shortcut

    # 重新加载设置获取最新快捷键
    discover_app.music_setting.load()
    new_shortcut = discover_app.music_setting.shortcut_key

    print(f"重新注册快捷键: {_current_shortcut} -> {new_shortcut}")

    # 只有当快捷键真正改变时才重新注册
    if new_shortcut.lower() != _current_shortcut.lower():
        register_global_shortcut(app, discover_app, new_shortcut)
    else:
        print("快捷键未改变，无需重新注册")


def run_gui():
    """运行GUI模式"""
    from main import DiscoverApp, get_splash_image_path

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 全局变量，用于后台加载完成后存储
    discover_app_holder = [None]  # 使用列表以便在嵌套函数中修改

    # 显示启动画面
    image_path = get_splash_image_path()
    splash = None
    if image_path:
        from main import SplashScreen
        splash = SplashScreen(image_path)

    # 定义后台加载函数
    def background_load():
        """在事件循环中后台加载应用"""
        # 创建应用实例
        discover_app = DiscoverApp()
        discover_app_holder[0] = discover_app

        # 加载语言设置到 i18n（必须在创建托盘之前）
        with contextlib.suppress(BaseException):
            i18n.set_language(discover_app.gui_setting.language)

        # 创建托盘
        create_tray_icon(app, discover_app)

        # 注册全局快捷键
        try:
            register_global_shortcut(app, discover_app, discover_app.music_setting.shortcut_key)
        except Exception:
            register_global_shortcut(app, discover_app, "Alt+D")

    # 使用 QTimer.singleShot(0, ...) 让后台加载在事件循环开始后执行
    # 这样启动画面和后台加载可以并行进行
    QTimer.singleShot(0, background_load)

    # 等待启动画面动画完成（主线程阻塞，但后台加载已在事件循环中执行）
    if splash:
        splash.wait_for_finish()

    # 运行应用事件循环
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
