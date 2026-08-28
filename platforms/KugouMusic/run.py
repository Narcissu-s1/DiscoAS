"""酷狗音乐后台播放模块。"""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import win32con
import win32gui
import win32process

try:
    import winreg
except ImportError:  # pragma: no cover - 项目仅在 Windows 上运行
    winreg = None


class KugouPlaybackError(RuntimeError):
    """酷狗音乐后台播放不可用。"""


def _registry_executables() -> list[Path]:
    if winreg is None:
        return []

    executables = []
    for root in (winreg.HKEY_CLASSES_ROOT, winreg.HKEY_CURRENT_USER):
        key_name = r"kugou" if root == winreg.HKEY_CLASSES_ROOT else r"Software\Classes\kugou"
        try:
            with winreg.OpenKey(root, key_name) as key:
                executable, _ = winreg.QueryValueEx(key, "URL Protocol")
        except OSError:
            continue
        if executable:
            executables.append(Path(executable.strip().strip('"')))
    return executables


def _kugou_executable() -> Path:
    candidates = _registry_executables()

    located = shutil.which("KuGou.exe")
    if located:
        candidates.append(Path(located))

    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        program_files = os.environ.get(env_name)
        if program_files:
            candidates.append(Path(program_files) / "KGMusic" / "KuGou.exe")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise KugouPlaybackError("未找到 KuGou.exe，请先安装酷狗音乐桌面版")


def _tasklist_rows() -> list[list[str]]:
    completed = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq KuGou.exe", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return list(csv.reader(io.StringIO(completed.stdout)))


def _kugou_process_ids() -> set[int]:
    process_ids = set()
    for row in _tasklist_rows():
        if len(row) < 2 or row[0].lower() != "kugou.exe":
            continue
        try:
            process_ids.add(int(row[1]))
        except ValueError:
            continue
    return process_ids


def _is_kugou_running() -> bool:
    return bool(_kugou_process_ids())


def _hidden_startupinfo():
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo


def _launch_silent(executable: Path) -> subprocess.Popen:
    """用客户端内置的迷你模式完成冷启动，避免主界面成为前台窗口。"""
    return subprocess.Popen(
        [str(executable), "-Mini"],
        cwd=str(executable.parent),
        startupinfo=_hidden_startupinfo(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _launch_protocol(executable: Path, scheme_url: str) -> subprocess.Popen:
    return subprocess.Popen(
        [str(executable), scheme_url],
        cwd=str(executable.parent),
        startupinfo=_hidden_startupinfo(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _has_top_level_window(process_ids: set[int]) -> bool:
    found = False

    def inspect_window(hwnd, _):
        nonlocal found
        _, process_id = win32process.GetWindowThreadProcessId(hwnd)
        if process_id in process_ids:
            found = True
            return False
        return True

    win32gui.EnumWindows(inspect_window, None)
    return found


def _wait_for_kugou_ready(timeout: float = 12.0) -> None:
    """等待协议接收进程建立；无顶层窗口时以进程稳定时间作为回退。"""
    deadline = time.monotonic() + timeout
    stable_process_ids = set()
    stable_since = None
    while time.monotonic() < deadline:
        process_ids = _kugou_process_ids()
        if process_ids and _has_top_level_window(process_ids):
            return
        if process_ids != stable_process_ids:
            stable_process_ids = process_ids
            stable_since = time.monotonic() if process_ids else None
        elif stable_since is not None and time.monotonic() - stable_since >= 1.0:
            return
        time.sleep(0.1)
    raise KugouPlaybackError("酷狗音乐启动后未能及时就绪")


def _visible_kugou_windows(process_ids: set[int]) -> set[int]:
    visible_windows = set()

    def collect_window(hwnd, _):
        _, process_id = win32process.GetWindowThreadProcessId(hwnd)
        if process_id in process_ids and win32gui.IsWindowVisible(hwnd):
            visible_windows.add(hwnd)
        return True

    win32gui.EnumWindows(collect_window, None)
    return visible_windows


def _is_main_ui_window(hwnd: int, title_prefix: str) -> bool:
    title = win32gui.GetWindowText(hwnd)
    if title_prefix and title.lower().startswith(title_prefix.lower()):
        return True

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width = max(0, right - left)
    height = max(0, bottom - top)
    is_owned = bool(win32gui.GetWindow(hwnd, win32con.GW_OWNER))
    extended_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    is_tool_window = bool(extended_style & win32con.WS_EX_TOOLWINDOW)
    return not is_owned and not is_tool_window and width >= 400 and height >= 280


def _stage_hidden_main_window() -> dict[int, int]:
    """让隐藏的酷狗主窗临时透明，防止播放协议显示出可绘制帧。"""
    process_ids = _kugou_process_ids()
    staged_windows = {}

    def stage_window(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            return True
        _, process_id = win32process.GetWindowThreadProcessId(hwnd)
        if process_id not in process_ids:
            return True
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        if (
            win32gui.GetClassName(hwnd) != "kugou_ui"
            or win32gui.GetWindow(hwnd, win32con.GW_OWNER)
            or not style & win32con.WS_THICKFRAME
        ):
            return True

        original_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if original_style & win32con.WS_EX_LAYERED:
            return True
        try:
            win32gui.SetWindowLong(
                hwnd,
                win32con.GWL_EXSTYLE,
                original_style | win32con.WS_EX_LAYERED,
            )
            win32gui.SetLayeredWindowAttributes(hwnd, 0, 0, win32con.LWA_ALPHA)
        except OSError:
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, original_style)
            raise
        staged_windows[hwnd] = original_style
        return True

    win32gui.EnumWindows(stage_window, None)
    return staged_windows


def _restore_staged_windows(staged_windows: dict[int, int]) -> None:
    for hwnd, original_style in staged_windows.items():
        if win32gui.IsWindow(hwnd):
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, original_style)


def _hide_new_kugou_ui_once(
    process_ids: set[int],
    ignored_windows: set[int],
    title_prefix: str,
) -> bool:
    if not process_ids:
        return False

    hidden = False

    def hide_window(hwnd, _):
        nonlocal hidden
        if hwnd in ignored_windows or not win32gui.IsWindowVisible(hwnd):
            return True
        _, process_id = win32process.GetWindowThreadProcessId(hwnd)
        if process_id in process_ids and _is_main_ui_window(hwnd, title_prefix):
            # 先同步客户端内部的最小化状态，否则再次点击酷狗图标时只会
            # 激活一个实际已隐藏、但客户端仍认为可见的窗口。
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            hidden = True
        return True

    win32gui.EnumWindows(hide_window, None)
    return hidden


def _suppress_kugou_ui(
    ignored_windows: set[int],
    title_prefix: str,
    command_sent: threading.Event,
    stop_suppression: threading.Event,
    startup_timeout: float,
    command_timeout: float,
    quiet_period: float,
) -> None:
    process_ids = set()
    next_process_refresh = 0.0

    def hide_new_ui() -> bool:
        nonlocal process_ids, next_process_refresh
        now = time.monotonic()
        if now >= next_process_refresh:
            process_ids = _kugou_process_ids()
            next_process_refresh = now + 0.1
        return _hide_new_kugou_ui_once(process_ids, ignored_windows, title_prefix)

    startup_deadline = time.monotonic() + startup_timeout
    while (
        not command_sent.is_set()
        and not stop_suppression.is_set()
        and time.monotonic() < startup_deadline
    ):
        hide_new_ui()
        time.sleep(0.002)

    command_deadline = time.monotonic() + command_timeout
    last_hidden_at = None
    while not stop_suppression.is_set() and time.monotonic() < command_deadline:
        if hide_new_ui():
            last_hidden_at = time.monotonic()
        elif last_hidden_at is not None and time.monotonic() - last_hidden_at >= quiet_period:
            return
        time.sleep(0.002)


def _start_ui_suppression(
    title_prefix: str,
    startup_timeout: float = 12.0,
) -> tuple[threading.Event, threading.Event, threading.Thread]:
    process_ids = _kugou_process_ids()
    ignored_windows = _visible_kugou_windows(process_ids)
    command_sent = threading.Event()
    stop_suppression = threading.Event()
    started = threading.Event()

    def suppress():
        started.set()
        _suppress_kugou_ui(
            ignored_windows,
            title_prefix,
            command_sent,
            stop_suppression,
            startup_timeout,
            command_timeout=6.0,
            quiet_period=0.15,
        )

    thread = threading.Thread(target=suppress, daemon=True, name="kugou-ui-suppression")
    thread.start()
    started.wait(timeout=0.2)
    return command_sent, stop_suppression, thread


def play_song(song_card) -> bool:
    """冷启动酷狗后发送一次原生播放协议，并抑制协议唤起的主界面。"""
    suppression = None
    staged_windows = {}
    try:
        scheme_url = song_card.get_scheme_url()
        if not scheme_url.startswith("kugou://play?"):
            raise KugouPlaybackError("歌曲卡片没有生成有效的酷狗播放协议")

        executable = _kugou_executable()
        title_prefix = song_card.get_window_name()
        suppression = _start_ui_suppression(title_prefix)
        command_sent, stop_suppression, suppression_thread = suppression
        if not _is_kugou_running():
            _launch_silent(executable)
            _wait_for_kugou_ready()
        staged_windows = _stage_hidden_main_window()
        _launch_protocol(executable, scheme_url)
        command_sent.set()
        suppression_thread.join(timeout=6.5)
        stop_suppression.set()
        suppression_thread.join(timeout=0.2)
        print(f"[酷狗音乐] 已发送后台播放命令，歌曲 Hash：{song_card.get_id()}")
        return True
    except (OSError, TypeError, ValueError, KugouPlaybackError) as exc:
        if suppression is not None:
            command_sent, stop_suppression, suppression_thread = suppression
            command_sent.set()
            stop_suppression.set()
            suppression_thread.join(timeout=0.2)
        print(f"[酷狗音乐] 后台播放失败：{exc}")
        return False
    finally:
        _restore_staged_windows(staged_windows)
