import os
import subprocess
from unittest.mock import MagicMock, patch

from platforms.QQMusic import run


class _SongCard:
    def __init__(self, song_id=102450788):
        self._song_id = song_id

    def get_id(self):
        return self._song_id


def _mkstemp_in(directory):
    def create(*, prefix, suffix):
        path = directory / f"{prefix}test{suffix}"
        descriptor = os.open(path, os.O_CREAT | os.O_WRONLY)
        return descriptor, str(path)

    return create


def test_protocol_payload_matches_qqmusic_native_format():
    assert run._protocol_payload(102450788) == (
        "QQMusic/?version==1173&&cmd_count==1"
        "&&cmd_0==playsong&&id_0==102450788&&songtype_0==0"
    )


def test_protocol_file_is_utf16_le_without_bom(tmp_path):
    with patch.object(run.tempfile, "mkstemp", side_effect=_mkstemp_in(tmp_path)):
        protocol_file = run._create_protocol_file(944095)

    content = protocol_file.read_bytes()
    assert not content.startswith(b"\xff\xfe")
    assert content.decode("utf-16-le") == run._protocol_payload(944095)


def test_launch_uses_protocol_file_and_hidden_startup(tmp_path):
    executable = tmp_path / "QQMusic.exe"
    protocol_file = tmp_path / "qmc.tmp"
    startupinfo = object()

    with (
        patch.object(run, "_hidden_startupinfo", return_value=startupinfo),
        patch.object(run.subprocess, "Popen") as popen,
    ):
        run._launch_protocol_file(executable, protocol_file)

    popen.assert_called_once_with(
        [str(executable), "/TencentProtocolFile", str(protocol_file)],
        cwd=str(tmp_path),
        startupinfo=startupinfo,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def test_background_launch_uses_qqmusic_official_switch(tmp_path):
    executable = tmp_path / "QQMusic.exe"
    startupinfo = object()

    with (
        patch.object(run, "_hidden_startupinfo", return_value=startupinfo),
        patch.object(run.subprocess, "Popen") as popen,
    ):
        assert run._launch_in_background(executable) is popen.return_value

    popen.assert_called_once_with(
        [str(executable), "/background"],
        cwd=str(tmp_path),
        startupinfo=startupinfo,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def test_background_ready_waits_for_gui_input_idle():
    process = MagicMock()
    process.poll.return_value = None
    with (
        patch.object(run, "_wait_for_input_idle", return_value=0) as wait_for_idle,
        patch.object(run.time, "sleep") as sleep,
    ):
        run._wait_for_background_ready(process)

    wait_for_idle.assert_called_once_with(process, 12000)
    sleep.assert_called_once_with(1)


def test_ui_suppression_hides_main_window_but_keeps_lyrics():
    window_classes = {
        10: "TXGuiFoundation",
        20: "DynamicLyricWindow",
        30: "TXGFLayerMask",
    }
    process_ids = {123}

    def enumerate_windows(callback, parameter):
        for hwnd in window_classes:
            callback(hwnd, parameter)

    with (
        patch.object(run.win32gui, "EnumWindows", side_effect=enumerate_windows),
        patch.object(
            run.win32process,
            "GetWindowThreadProcessId",
            side_effect=lambda hwnd: (1, 999 if hwnd == 30 else 123),
        ),
        patch.object(run.win32gui, "IsWindowVisible", return_value=True),
        patch.object(run.win32gui, "GetClassName", side_effect=lambda hwnd: window_classes[hwnd]),
        patch.object(run.win32gui, "ShowWindow") as show_window,
    ):
        assert run._hide_qqmusic_ui_once(process_ids) is True

    show_window.assert_called_once_with(10, run.win32con.SW_HIDE)


def test_visible_qqmusic_windows_are_recorded_before_protocol_launch():
    window_classes = {10: "TXGuiFoundation", 20: "DynamicLyricWindow", 30: "TXGFLayerMask"}

    def enumerate_windows(callback, parameter):
        for hwnd in window_classes:
            callback(hwnd, parameter)

    with (
        patch.object(run.win32gui, "EnumWindows", side_effect=enumerate_windows),
        patch.object(run.win32process, "GetWindowThreadProcessId", return_value=(1, 123)),
        patch.object(run.win32gui, "IsWindowVisible", return_value=True),
        patch.object(run.win32gui, "GetClassName", side_effect=lambda hwnd: window_classes[hwnd]),
    ):
        assert run._visible_qqmusic_ui_windows({123}) == {10, 30}


def test_ui_suppression_ignores_window_that_was_already_visible():
    with (
        patch.object(run.win32gui, "EnumWindows", side_effect=lambda callback, parameter: callback(10, parameter)),
        patch.object(run.win32process, "GetWindowThreadProcessId", return_value=(1, 123)),
        patch.object(run.win32gui, "IsWindowVisible", return_value=True),
        patch.object(run.win32gui, "GetClassName", return_value="TXGuiFoundation"),
        patch.object(run.win32gui, "ShowWindow") as show_window,
    ):
        assert run._hide_qqmusic_ui_once({123}, ignored_windows={10}) is False

    show_window.assert_not_called()


def test_ui_suppression_waits_for_quiet_period_after_repeated_show_events():
    process_ids = {123}
    with (
        patch.object(run.time, "monotonic", side_effect=[0, 0.1, 0.1, 0.2, 0.25, 0.41]),
        patch.object(run, "_hide_qqmusic_ui_once", side_effect=[True, True]) as hide_once,
        patch.object(run.time, "sleep") as sleep,
    ):
        assert run._suppress_qqmusic_ui_burst(
            process_ids,
            ignored_windows=set(),
            initial_timeout=1.5,
            quiet_period=0.15,
        ) is True

    assert hide_once.call_count == 2
    assert sleep.call_count == 2


def test_ui_suppression_has_a_hard_limit_after_first_hide():
    with (
        patch.object(run.time, "monotonic", side_effect=[0, 0.1, 0.1, 0.86]),
        patch.object(run, "_hide_qqmusic_ui_once", return_value=True) as hide_once,
        patch.object(run.time, "sleep") as sleep,
    ):
        assert run._suppress_qqmusic_ui_burst(
            {123},
            ignored_windows=set(),
            initial_timeout=1.5,
            quiet_period=0.15,
        ) is True

    hide_once.assert_called_once_with({123}, set())
    sleep.assert_called_once_with(0.001)


def test_cold_start_waits_for_background_before_sending_command(tmp_path):
    executable = tmp_path / "QQMusic.exe"
    protocol_file = tmp_path / "qmc.tmp"
    process = object()

    with (
        patch.object(run, "_qqmusic_executable", return_value=executable),
        patch.object(run, "_is_qqmusic_running", return_value=False),
        patch.object(run, "_launch_in_background", return_value=process) as launch_background,
        patch.object(run, "_wait_for_background_ready") as wait_until_ready,
        patch.object(run, "_create_protocol_file", return_value=protocol_file) as create_file,
        patch.object(run, "_start_ui_suppression") as suppress_ui,
        patch.object(run, "_launch_protocol_file") as launch,
        patch.object(run, "_schedule_cleanup") as cleanup,
    ):
        assert run.play_song(_SongCard()) is True

    launch_background.assert_called_once_with(executable)
    wait_until_ready.assert_called_once_with(process)
    create_file.assert_called_once_with(102450788)
    suppress_ui.assert_called_once_with()
    launch.assert_called_once_with(executable, protocol_file)
    cleanup.assert_called_once_with(protocol_file)


def test_warm_start_sends_command_without_relaunching_client(tmp_path):
    executable = tmp_path / "QQMusic.exe"
    protocol_file = tmp_path / "qmc.tmp"

    with (
        patch.object(run, "_qqmusic_executable", return_value=executable),
        patch.object(run, "_is_qqmusic_running", return_value=True),
        patch.object(run, "_launch_in_background") as launch_background,
        patch.object(run, "_wait_for_background_ready") as wait_until_ready,
        patch.object(run, "_create_protocol_file", return_value=protocol_file),
        patch.object(run, "_start_ui_suppression") as suppress_ui,
        patch.object(run, "_launch_protocol_file") as launch,
        patch.object(run, "_schedule_cleanup"),
    ):
        assert run.play_song(_SongCard()) is True

    launch_background.assert_not_called()
    wait_until_ready.assert_not_called()
    suppress_ui.assert_called_once_with()
    launch.assert_called_once_with(executable, protocol_file)


def test_play_song_reports_missing_client_without_creating_command():
    with (
        patch.object(
            run,
            "_qqmusic_executable",
            side_effect=run.QQMusicPlaybackError("未找到客户端"),
        ),
        patch.object(run, "_create_protocol_file") as create_file,
    ):
        assert run.play_song(_SongCard()) is False

    create_file.assert_not_called()
