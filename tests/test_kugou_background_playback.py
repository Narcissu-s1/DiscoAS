from pathlib import Path
from unittest.mock import MagicMock, patch


class _SongCard:
    def get_id(self):
        return "A" * 32

    def get_scheme_url(self):
        return "kugou://play?p=payload"

    def get_window_name(self):
        return "歌手 - 歌曲"


def test_cold_start_waits_until_ready_before_sending_protocol():
    from platforms.KugouMusic import run

    command_sent = MagicMock()
    stop_suppression = MagicMock()
    suppression_thread = MagicMock()
    order = []

    with (
        patch.object(run, "_kugou_executable", return_value=Path(r"D:\KGMusic\KuGou.exe")),
        patch.object(
            run,
            "_start_ui_suppression",
            return_value=(command_sent, stop_suppression, suppression_thread),
        ),
        patch.object(run, "_is_kugou_running", return_value=False),
        patch.object(run, "_launch_silent", side_effect=lambda _: order.append("start")),
        patch.object(run, "_wait_for_kugou_ready", side_effect=lambda: order.append("ready")),
        patch.object(run, "_stage_hidden_main_window", side_effect=lambda: order.append("stage") or {}),
        patch.object(run, "_restore_staged_windows") as restore_staged_windows,
        patch.object(run, "_launch_protocol", side_effect=lambda *_: order.append("play")),
    ):
        assert run.play_song(_SongCard()) is True

    assert order == ["start", "ready", "stage", "play"]
    command_sent.set.assert_called_once_with()
    stop_suppression.set.assert_called_once_with()
    assert suppression_thread.join.call_count == 2
    restore_staged_windows.assert_called_once_with({})


def test_running_client_skips_cold_start():
    from platforms.KugouMusic import run

    command_sent = MagicMock()
    stop_suppression = MagicMock()
    suppression_thread = MagicMock()
    with (
        patch.object(run, "_kugou_executable", return_value=Path(r"D:\KGMusic\KuGou.exe")),
        patch.object(
            run,
            "_start_ui_suppression",
            return_value=(command_sent, stop_suppression, suppression_thread),
        ),
        patch.object(run, "_is_kugou_running", return_value=True),
        patch.object(run, "_launch_silent") as launch_silent,
        patch.object(run, "_wait_for_kugou_ready") as wait_for_ready,
        patch.object(run, "_stage_hidden_main_window", return_value={202: 0x100}),
        patch.object(run, "_restore_staged_windows") as restore_staged_windows,
        patch.object(run, "_launch_protocol") as launch_protocol,
    ):
        assert run.play_song(_SongCard()) is True

    launch_silent.assert_not_called()
    wait_for_ready.assert_not_called()
    launch_protocol.assert_called_once_with(Path(r"D:\KGMusic\KuGou.exe"), "kugou://play?p=payload")
    command_sent.set.assert_called_once_with()
    stop_suppression.set.assert_called_once_with()
    assert suppression_thread.join.call_count == 2
    restore_staged_windows.assert_called_once_with({202: 0x100})


def test_invalid_scheme_is_rejected_before_launch():
    from platforms.KugouMusic import run

    card = _SongCard()
    card.get_scheme_url = MagicMock(return_value="https://example.com")
    with patch.object(run, "_kugou_executable") as executable:
        assert run.play_song(card) is False

    executable.assert_not_called()


def test_launch_failure_stops_ui_suppression():
    from platforms.KugouMusic import run

    command_sent = MagicMock()
    stop_suppression = MagicMock()
    suppression_thread = MagicMock()
    with (
        patch.object(run, "_kugou_executable", return_value=Path(r"D:\KGMusic\KuGou.exe")),
        patch.object(
            run,
            "_start_ui_suppression",
            return_value=(command_sent, stop_suppression, suppression_thread),
        ),
        patch.object(run, "_is_kugou_running", return_value=True),
        patch.object(run, "_launch_protocol", side_effect=OSError("boom")),
    ):
        assert run.play_song(_SongCard()) is False

    command_sent.set.assert_called_once_with()
    stop_suppression.set.assert_called_once_with()
    suppression_thread.join.assert_called_once_with(timeout=0.2)


def test_existing_visible_windows_are_preserved():
    from platforms.KugouMusic import run

    show_commands = []

    def enumerate_windows(callback, extra):
        callback(101, extra)
        callback(202, extra)

    with (
        patch.object(run, "_kugou_process_ids", return_value={9}),
        patch.object(run.win32gui, "EnumWindows", side_effect=enumerate_windows),
        patch.object(run.win32gui, "IsWindowVisible", return_value=True),
        patch.object(run.win32process, "GetWindowThreadProcessId", return_value=(1, 9)),
        patch.object(run, "_is_main_ui_window", return_value=True),
        patch.object(
            run.win32gui,
            "ShowWindow",
            side_effect=lambda hwnd, command: show_commands.append((hwnd, command)),
        ),
    ):
        assert run._hide_new_kugou_ui_once({9}, {101}, "歌手 - 歌曲") is True

    assert show_commands == [
        (202, run.win32con.SW_MINIMIZE),
        (202, run.win32con.SW_HIDE),
    ]


def test_hidden_main_window_is_made_transparent_before_protocol():
    from platforms.KugouMusic import run

    def enumerate_windows(callback, extra):
        callback(202, extra)

    with (
        patch.object(run, "_kugou_process_ids", return_value={9}),
        patch.object(run.win32gui, "EnumWindows", side_effect=enumerate_windows),
        patch.object(run.win32gui, "IsWindowVisible", return_value=False),
        patch.object(run.win32process, "GetWindowThreadProcessId", return_value=(1, 9)),
        patch.object(run.win32gui, "GetClassName", return_value="kugou_ui"),
        patch.object(run.win32gui, "GetWindow", return_value=0),
        patch.object(
            run.win32gui,
            "GetWindowLong",
            side_effect=[run.win32con.WS_THICKFRAME, 0x100],
        ),
        patch.object(run.win32gui, "SetWindowLong") as set_window_long,
        patch.object(run.win32gui, "SetLayeredWindowAttributes") as set_layered_attributes,
    ):
        assert run._stage_hidden_main_window() == {202: 0x100}

    set_window_long.assert_called_once_with(
        202,
        run.win32con.GWL_EXSTYLE,
        0x100 | run.win32con.WS_EX_LAYERED,
    )
    set_layered_attributes.assert_called_once_with(202, 0, 0, run.win32con.LWA_ALPHA)


def test_staged_window_style_is_restored_exactly():
    from platforms.KugouMusic import run

    with (
        patch.object(run.win32gui, "IsWindow", return_value=True),
        patch.object(run.win32gui, "SetWindowLong") as set_window_long,
    ):
        run._restore_staged_windows({202: 0x100})

    set_window_long.assert_called_once_with(202, run.win32con.GWL_EXSTYLE, 0x100)


def test_small_tool_window_is_not_treated_as_main_ui():
    from platforms.KugouMusic import run

    with (
        patch.object(run.win32gui, "GetWindowText", return_value="桌面歌词"),
        patch.object(run.win32gui, "GetWindowRect", return_value=(0, 0, 900, 100)),
        patch.object(run.win32gui, "GetWindow", return_value=0),
        patch.object(run.win32gui, "GetWindowLong", return_value=run.win32con.WS_EX_TOOLWINDOW),
    ):
        assert run._is_main_ui_window(100, "歌手 - 歌曲") is False
