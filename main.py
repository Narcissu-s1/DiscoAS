import ctypes
import os
import sys
import traceback

from Discover import DiscoverASong
from platforms.KugouMusic.run import play_song as kugou_play_song
from platforms.NeteaseCloudMusic.run import play_song as netease_play_song
from platforms.QQMusic.run import play_song as qqmusic_play_song
from platforms.Spotify.run import play_song as spotify_play_song
from settings.gui_setting import GuiSetting
from settings.music_setting import PASetting

PLATFORM_RUN_MAP = {
    'NeteaseCloudMusic': netease_play_song,
    'QQMusic': qqmusic_play_song,
    'KugouMusic': kugou_play_song,
    'Spotify': spotify_play_song,
}

STILL_ACTIVE = 259


def _is_process_alive(pid: int) -> bool:
    """用 Windows API 检查进程是否还在运行（不抛异常）"""
    try:
        _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        return exit_code.value == STILL_ACTIVE
    except Exception:
        return False

sys.path.append(os.path.dirname(__file__))

# GUI导入
try:
    from PyQt6.QtCore import QByteArray, QEasingCurve, QEventLoop, QPropertyAnimation, Qt, QTimer
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import QApplication, QLabel, QWidget
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False
    print("警告: PyQt6未安装")


class SplashScreen(QWidget):
    """启动画面：全屏浮动窗口显示图片，快速淡入淡出"""

    def __init__(self, image_path: str, fade_duration: int = 750, show_duration: int = 500):
        """
        初始化启动画面

        Args:
            image_path: 图片路径
            fade_duration: 淡入淡出持续时间(毫秒)
            show_duration: 图片显示持续时间(毫秒)
        """
        super().__init__()
        self.fade_duration = fade_duration
        self.show_duration = show_duration
        self.animation_finished = False
        self.qApp = QApplication.instance()
        self.image_path = image_path

        # 设置窗口属性：无边框、置顶、不在任务栏显示
        # 使用 FramelessWindowHint 确保无边框，Tool 隐藏任务栏图标
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        # 设置背景完全透明（必须在窗口显示之前设置）
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        # 先创建标签并加载图片
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 加载图片
        self.load_image(image_path)

        # 全屏显示
        self.showFullScreen()

        # 确保标签在窗口中央
        self.label.setGeometry(self.rect())

        # 初始显示（透明度0），然后淡入
        self.setWindowOpacity(0)

        # 强制刷新显示
        self.qApp.processEvents()

        # 开始淡入动画（从1到1其实不动画，直接淡出）
        # 为了视觉效果，我们直接从1开始淡出
        self.start_animation()

    def load_image(self, image_path: str):
        """加载并显示图片"""
        print(f"[SplashScreen] 尝试加载图片: {image_path}")
        print(f"[SplashScreen] 文件存在: {os.path.exists(image_path)}")

        if os.path.exists(image_path):
            # 使用绝对路径
            abs_path = os.path.abspath(image_path)
            print(f"[SplashScreen] 绝对路径: {abs_path}")

            # 尝试加载图片
            pixmap = QPixmap(abs_path)
            if pixmap.isNull():
                print("[SplashScreen] 图片加载失败，尝试其他方式...")
                # 尝试用文件 URL
                pixmap = QPixmap(f"file:///{abs_path.replace(os.sep, '/')}")

            print(f"[SplashScreen] 图片是否为空: {pixmap.isNull()}")
            print(f"[SplashScreen] 图片尺寸: {pixmap.width()}x{pixmap.height()}")

            if not pixmap.isNull():
                # 获取屏幕尺寸
                screen = QApplication.primaryScreen()
                if screen:
                    screen_geometry = screen.geometry()
                    # 缩放到合适大小（屏幕的80%）
                    scaled = pixmap.scaled(
                        int(screen_geometry.width() * 0.45) ,
                        int(screen_geometry.height() * 0.45),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    print(f"[SplashScreen] 缩放后尺寸: {scaled.width()}x{scaled.height()}")
                    self.label.setPixmap(scaled)
                else:
                    self.label.setPixmap(pixmap)
            else:
                print("[SplashScreen] 错误：无法加载图片")
        else:
            print(f"[SplashScreen] 启动画面图片不存在: {image_path}")

    def start_animation(self):
        """开始淡入淡出动画"""
        self.fade_in()

    def fade_in(self):
        """淡入动画"""
        self.anim = QPropertyAnimation(self, QByteArray(b"windowOpacity"))
        self.anim.setDuration(self.fade_duration)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.anim.finished.connect(self.fade_out)
        self.anim.start()

    def fade_out(self):
        """淡出动画"""
        QTimer.singleShot(self.show_duration, self._do_fade_out)

    def _do_fade_out(self):
        """执行淡出"""
        self.anim = QPropertyAnimation(self, QByteArray(b"windowOpacity"))
        self.anim.setDuration(self.fade_duration)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.anim.finished.connect(self._on_animation_finished)
        self.anim.start()

    def _on_animation_finished(self):
        """动画全部完成"""
        self.animation_finished = True
        self.close()

    def wait_for_finish(self):
        """等待动画完成（非阻塞方式，允许事件循环处理后台任务）"""
        # 使用 QEventLoop 而非 time.sleep，让事件循环可以处理后台任务
        loop = QEventLoop()
        # 动画总时长后退出
        QTimer.singleShot(self.fade_duration * 2 + self.show_duration, loop.quit)
        loop.exec()


def get_splash_image_path() -> str:
    """获取启动画面图片路径，支持打包后环境"""
    # 先尝试常规路径
    image_path = os.path.join(os.path.dirname(__file__), "src", "DiscoAS.png")
    if os.path.exists(image_path):
        return image_path

    # 尝试打包后的路径
    try:
        from settings.user_data_path import get_resource_dir
        image_path = os.path.join(get_resource_dir(), "src", "DiscoAS.png")
        if os.path.exists(image_path):
            return image_path
    except ImportError:
        pass

    return ""


class DiscoverApp:
    """DiscovAS应用主类"""

    def __init__(self):
        print("[DiscoverApp] __init__ start")
        self.music_setting = PASetting()
        print("[DiscoverApp] PASetting created")
        self.music_setting.load()
        print("[DiscoverApp] PASetting loaded")

        self.gui_setting = GuiSetting()
        print("[DiscoverApp] GuiSetting created")
        self.gui_setting.load()
        print("[DiscoverApp] GuiSetting loaded")

        print("[DiscoverApp] calling _update_enabled_playlist")
        self._update_enabled_playlist()
        print("[DiscoverApp] _update_enabled_playlist done")

        self._apply_settings()
        print("[DiscoverApp] _apply_settings done")

    def _update_enabled_playlist(self) -> None:
        """启动时自动更新唯一被启用的歌单"""
        # 查找启用的歌单
        enabled_playlist = None
        for pl in self.music_setting.playlist_albums:
            if pl.enabled:
                enabled_playlist = pl
                break

        if not enabled_playlist:
            print("没有启用的歌单，跳过更新")
            return

        print(f"正在更新启用的歌单: {enabled_playlist.playlist_album_id} ({enabled_playlist.typename})")

        try:
            # 根据平台动态导入对应的 get_json 模块
            platform = enabled_playlist.name
            module_path = f"platforms.{platform}.get_json"
            get_json_module = __import__(module_path, fromlist=['PlaylistAlbumJson'])
            PlaylistAlbumJson = get_json_module.PlaylistAlbumJson

            # 获取并保存歌单数据
            playlist_json = PlaylistAlbumJson(
                enabled_playlist.playlist_album_id,
                enabled_playlist.typename
            ).refresh()
            if playlist_json.is_stale:
                print(f"远端更新失败，已使用本地缓存: {playlist_json.last_refresh_error}")
            else:
                playlist_json.save()
            print(f"歌单更新完成: {playlist_json.get_name()}")
        except Exception as e:
            print(f"更新歌单失败: {e}")
            traceback.print_exc()
            # 弹窗提示用户
            try:
                from PyQt6.QtCore import QApplication
                from PyQt6.QtWidgets import QMessageBox

                from settings.i18n import gettext as _
                app = QApplication.instance()
                if app:
                    QMessageBox.critical(
                        None,
                        _("playlist_load_failed"),
                        _("playlist_load_failed_msg").format(error=str(e))
                    )
            except Exception:
                pass

    def _apply_settings(self) -> None:
        """应用设置"""
        # 查找启用的歌单
        enabled_playlist = None
        for pl in self.music_setting.playlist_albums:
            if pl.enabled:
                enabled_playlist = pl
                break

        if enabled_playlist:
            self.platform = enabled_playlist.name
            self.playlist_type = enabled_playlist.typename
            self.playlist_id = enabled_playlist.playlist_album_id
        else:
            # 默认使用网易云音乐
            self.platform = "NeteaseCloudMusic"
            self.playlist_type = "playlist"
            self.playlist_id = "8285082830"

    def discover_songs(self, number: int | None = None) -> list:
        """
        发现歌曲

        Args:
            number: 指定歌曲数量，默认使用设置中的数量

        Returns:
            歌曲卡片列表
        """
        if number is None:
            number = self.music_setting.number_of_discovered_songs

        discover = DiscoverASong(self.platform, self.playlist_type, self.playlist_id)
        songs, total, mystery_count = discover.get_songs(
            number,
            self.music_setting.have_mystery_song,
            self.music_setting.num_of_mystery_song,
            False,                                 # 不再允许歌曲重复
            self.music_setting.mystery_song_cover  # 传递自定义秘密封面
        )

        return songs

    def play_song(self, song_card) -> bool:
        """
        播放歌曲

        Args:
            song_card: 歌曲卡片对象

        Returns:
            是否成功播放
        """
        try:
            if not song_card.have_loaded:
                song_card.load_song_detail()

            run_func = PLATFORM_RUN_MAP.get(self.platform)
            if run_func:
                return run_func(song_card)
            return False
        except Exception as e:
            print(f"播放失败: {e}")
            return False

    def run_gui(self) -> None:
        """GUI模式运行"""
        if not GUI_AVAILABLE:
            print("错误: GUI模式需要安装PyQt6")
            print("请运行: pip install PyQt6")
            return

        # 导入GUI模块
        from Discover_gui import run_gui

        run_gui()


def acquire_single_instance_lock():
    """获取单实例锁。返回 True 表示获得锁并继续启动，False 表示已有实例在运行。"""
    lock_dir = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), "DiscoAS")
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, "single_instance.lock")

    # 清理陈旧锁文件（来自崩溃/强制终止的进程）
    if os.path.exists(lock_path):
        stale = True
        try:
            with open(lock_path) as f:
                old_pid = int(f.read().strip())
            if _is_process_alive(old_pid):
                stale = False  # 进程还活着，锁有效
        except (ValueError, OSError, ProcessLookupError):
            pass  # PID 无效或进程已死，锁为陈旧
        if stale:
            try:
                os.remove(lock_path)
                print(f"[main] 清理陈旧锁文件: {lock_path}")
            except OSError:
                pass

    # 创建新锁
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        print(f"[main] 锁文件创建成功: {lock_path}")
        return True
    except FileExistsError:
        print("[main] DiscoAS 已在运行中，退出。")
        return False


def main():
    """主入口函数"""
    if not acquire_single_instance_lock():
        return

    # 默认启动GUI模式
    if not GUI_AVAILABLE:
        print("错误: GUI模式需要安装PyQt6")
        print("请运行: pip install PyQt6")
        return

    # 运行 GUI（Discover_gui.run_gui 会处理所有初始化）
    from Discover_gui import run_gui
    run_gui()


if __name__ == "__main__":
    main()
