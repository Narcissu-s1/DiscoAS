"""QQ 音乐后台播放模块。"""

import csv
import ctypes
import io
import os
import shutil
import subprocess
import tempfile
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


class QQMusicPlaybackError(RuntimeError):
    """QQ 音乐后台播放不可用。"""


def _registry_install_dirs() -> list[Path]:
    if winreg is None:
        return []

    key_names = (
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQMusic",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQMusic",
    )
    install_dirs = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for key_name in key_names:
            try:
                with winreg.OpenKey(root, key_name) as key:
                    install_dir, _ = winreg.QueryValueEx(key, "InstallLocation")
            except OSError:
                continue
            if install_dir:
                install_dirs.append(Path(install_dir))
    return install_dirs


def _qqmusic_executable() -> Path:
    candidates = [directory / "QQMusic.exe" for directory in _registry_install_dirs()]

    located = shutil.which("QQMusic.exe")
    if located:
        candidates.append(Path(located))

    for env_name in ("ProgramFiles(x86)", "ProgramFiles"):
        program_files = os.environ.get(env_name)
        if program_files:
            candidates.append(Path(program_files) / "Tencent" / "QQMusic" / "QQMusic.exe")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise QQMusicPlaybackError("未找到 QQMusic.exe，请先安装 QQ 音乐桌面版")


def _protocol_payload(song_id: int) -> str:
    return (
        "QQMusic/?version==1173&&cmd_count==1"
        f"&&cmd_0==playsong&&id_0=={song_id}&&songtype_0==0"
    )


def _create_protocol_file(song_id: int) -> Path:
    file_descriptor, file_name = tempfile.mkstemp(prefix="qmc", suffix=".tmp")
    protocol_file = Path(file_name)
    try:
        with os.fdopen(file_descriptor, "wb") as file:
            file.write(_protocol_payload(song_id).encode("utf-16-le"))
    except Exception:
        protocol_file.unlink(missing_ok=True)
        raise
    return protocol_file


def _hidden_startupinfo():
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo


def _launch_protocol_file(executable: Path, protocol_file: Path) -> None:
    subprocess.Popen(
        [str(executable), "/TencentProtocolFile", str(protocol_file)],
        cwd=str(executable.parent),
        startupinfo=_hidden_startupinfo(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _is_qqmusic_running() -> bool:
    completed = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq QQMusic.exe", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return "qqmusic.exe" in completed.stdout.lower()


def _qqmusic_process_ids() -> set[int]:
    completed = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq QQMusic.exe", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    process_ids = set()
    for row in csv.reader(io.StringIO(completed.stdout)):
        if len(row) >= 2 and row[0].lower() == "qqmusic.exe":
            try:
                process_ids.add(int(row[1]))
            except ValueError:
                continue
    return process_ids


_QQMUSIC_UI_CLASSES = {"TXGuiFoundation", "TXGFLayerMask"}


def _visible_qqmusic_ui_windows(process_ids: set[int]) -> set[int]:
    visible_windows = set()

    def collect_window(hwnd, _):
        _, process_id = win32process.GetWindowThreadProcessId(hwnd)
        if (
            process_id in process_ids
            and win32gui.IsWindowVisible(hwnd)
            and win32gui.GetClassName(hwnd) in _QQMUSIC_UI_CLASSES
        ):
            visible_windows.add(hwnd)
        return True

    win32gui.EnumWindows(collect_window, None)
    return visible_windows


def _hide_qqmusic_ui_once(
    process_ids: set[int] | None = None,
    ignored_windows: set[int] | None = None,
) -> bool:
    process_ids = process_ids or _qqmusic_process_ids()
    if not process_ids:
        return False
    ignored_windows = ignored_windows or set()

    main_window_hidden = False

    def hide_window(hwnd, _):
        nonlocal main_window_hidden
        if hwnd in ignored_windows:
            return True
        _, process_id = win32process.GetWindowThreadProcessId(hwnd)
        if process_id not in process_ids or not win32gui.IsWindowVisible(hwnd):
            return True

        window_class = win32gui.GetClassName(hwnd)
        if window_class in _QQMUSIC_UI_CLASSES:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            if window_class == "TXGuiFoundation":
                main_window_hidden = True
        return True

    win32gui.EnumWindows(hide_window, None)
    return main_window_hidden


def _suppress_qqmusic_ui_burst(
    process_ids: set[int],
    ignored_windows: set[int],
    initial_timeout: float,
    quiet_period: float,
) -> bool:
    initial_deadline = time.monotonic() + initial_timeout
    first_hidden_at = None
    last_hidden_at = None
    while True:
        now = time.monotonic()
        if last_hidden_at is None and now >= initial_deadline:
            return False
        if first_hidden_at is not None and now - first_hidden_at >= 0.75:
            return True
        if last_hidden_at is not None and now - last_hidden_at >= quiet_period:
            return True
        if _hide_qqmusic_ui_once(process_ids, ignored_windows):
            last_hidden_at = time.monotonic()
            if first_hidden_at is None:
                first_hidden_at = last_hidden_at
        time.sleep(0.001)


def _start_ui_suppression(initial_timeout: float = 1.5, quiet_period: float = 0.15) -> None:
    """隐藏协议新显示的 QQ 窗口，并保护此前已打开的窗口。"""
    process_ids = _qqmusic_process_ids()
    ignored_windows = _visible_qqmusic_ui_windows(process_ids)
    started = threading.Event()

    def suppress():
        started.set()
        _suppress_qqmusic_ui_burst(
            process_ids,
            ignored_windows,
            initial_timeout,
            quiet_period,
        )

    thread = threading.Thread(target=suppress, daemon=True, name="qqmusic-ui-suppression")
    thread.start()
    started.wait(timeout=0.2)


def _launch_in_background(executable: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [str(executable), "/background"],
        cwd=str(executable.parent),
        startupinfo=_hidden_startupinfo(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _wait_for_input_idle(process: subprocess.Popen, timeout_ms: int) -> int:
    return ctypes.windll.user32.WaitForInputIdle(process._handle, timeout_ms)


def _wait_for_background_ready(process: subprocess.Popen, timeout: float = 12.0) -> None:
    """等待 QQ 音乐完成 GUI 消息循环初始化。"""
    result = _wait_for_input_idle(process, int(timeout * 1000))
    if result != 0 or process.poll() is not None:
        raise QQMusicPlaybackError("QQ 音乐后台启动后未能及时就绪")
    time.sleep(1)


def _schedule_cleanup(protocol_file: Path) -> None:
    timer = threading.Timer(60, protocol_file.unlink, kwargs={"missing_ok": True})
    timer.daemon = True
    timer.start()


def play_song(song_card) -> bool:
    """通过 QQ 原生协议播放，并抑制协议自动显示的一次主窗口。"""
    protocol_file = None
    try:
        song_id = int(song_card.get_id())
        executable = _qqmusic_executable()
        if not _is_qqmusic_running():
            process = _launch_in_background(executable)
            _wait_for_background_ready(process)
        protocol_file = _create_protocol_file(song_id)
        _start_ui_suppression()
        _launch_protocol_file(executable, protocol_file)
        _schedule_cleanup(protocol_file)
        print(f"[QQ 音乐] 已发送后台播放命令，歌曲 ID：{song_id}")
        return True
    except (OSError, TypeError, ValueError, QQMusicPlaybackError) as exc:
        if protocol_file is not None:
            protocol_file.unlink(missing_ok=True)
        print(f"[QQ 音乐] 后台播放失败：{exc}")
        return False
