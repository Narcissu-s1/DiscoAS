import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from platforms.NeteaseCloudMusic import run


class _SongCard:
    def __init__(self, song_id=123):
        self.song_detail_json = {"id": song_id, "name": "测试歌曲"}
        self._song_id = song_id

    def get_id(self):
        return self._song_id


def test_play_song_uses_background_channel_and_confirms_track():
    card = _SongCard()

    with (
        patch.object(run, "_ensure_control_channel", return_value=False) as ensure_channel,
        patch.object(run, "_play_and_confirm") as play_and_confirm,
    ):
        assert run.play_song(card) is True

    ensure_channel.assert_called_once_with()
    play_and_confirm.assert_called_once_with(123, card.song_detail_json, allow_retry=False)


def test_play_song_does_not_fall_back_to_window_or_scheme():
    with patch.object(
        run,
        "_ensure_control_channel",
        side_effect=run.BackgroundPlaybackUnavailableError("不可用"),
    ):
        assert run.play_song(_SongCard()) is False


def test_running_client_without_control_channel_is_not_restarted():
    with (
        patch.object(run, "_cdp_target", side_effect=run.BackgroundPlaybackUnavailableError("未就绪")),
        patch.object(run, "_is_cloudmusic_running", return_value=True),
        patch.object(run, "_launch_with_background_control") as launch,
        pytest.raises(run.BackgroundPlaybackUnavailableError, match="完全退出一次"),
    ):
        run._ensure_control_channel()

    launch.assert_not_called()


def test_stopped_client_is_launched_with_loopback_cdp():
    target = {"type": "page", "url": "orpheus://main"}
    with (
        patch.object(run, "_cdp_target", side_effect=run.BackgroundPlaybackUnavailableError("未就绪")),
        patch.object(run, "_is_cloudmusic_running", return_value=False),
        patch.object(run, "_launch_with_background_control") as launch,
        patch.object(run, "_wait_for_cdp", return_value=target) as wait_for_cdp,
    ):
        assert run._ensure_control_channel() is True

    launch.assert_called_once_with()
    wait_for_cdp.assert_called_once_with()


def test_existing_control_channel_is_reported_as_warm():
    with patch.object(run, "_cdp_target", return_value={"type": "page"}):
        assert run._ensure_control_channel() is False


def test_launch_uses_hidden_loopback_control_flags():
    executable = Path(__file__).resolve()

    with (
        patch.object(run, "_cloudmusic_executable", return_value=executable),
        patch.object(run, "_cdp_port", return_value=9223),
        patch.object(run.subprocess, "Popen") as popen,
    ):
        run._launch_with_background_control()

    args, kwargs = popen.call_args
    assert args[0] == [
        str(executable),
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=9223",
    ]
    assert kwargs["cwd"] == str(executable.parent)


def test_play_track_dispatches_exact_song_without_clearing_queue():
    states = {
        "status": "playing",
        "current": {"id": 10},
        "queue": [{"id": 10}, {"id": 11}],
    }
    evaluations = []

    def capture(expression, *, await_promise=False):
        evaluations.append((expression, await_promise))
        return True

    with (
        patch.object(run, "_client_state", return_value=states),
        patch.object(run, "_ensure_client_runtime"),
        patch.object(run, "_cdp_evaluate", side_effect=capture),
    ):
        run._play_track(123, {"id": 123, "name": "测试歌曲"})

    expression, await_promise = evaluations[-1]
    assert await_promise is True
    assert "playingList/addItemToCurPlayingList" in expression
    assert '"playId":123' in expression
    assert '"clear":false' in expression


def test_runtime_discovers_store_api_instead_of_using_fixed_module_id():
    with patch.object(run, "_cdp_evaluate", return_value=True) as evaluate:
        run._ensure_client_runtime()

    expression = evaluate.call_args.args[0]
    assert "getStore" in expression
    assert "getDispatch" in expression
    assert "Object.keys(r.c||{})" in expression
    assert "r(12)" not in expression


def test_cold_start_waits_for_player_and_retries_unconfirmed_command():
    card = _SongCard()

    with (
        patch.object(run, "_ensure_control_channel", return_value=True),
        patch.object(run, "_wait_for_player_ready") as wait_for_player_ready,
        patch.object(run, "_play_and_confirm") as play_and_confirm,
    ):
        assert run.play_song(card) is True

    wait_for_player_ready.assert_called_once_with()
    play_and_confirm.assert_called_once_with(123, card.song_detail_json, allow_retry=True)


def test_cold_start_retries_once_when_first_command_is_not_confirmed():
    with (
        patch.object(run, "_play_track") as play_track,
        patch.object(
            run,
            "_wait_until_playing",
            side_effect=[run.BackgroundPlaybackUnavailableError("未确认"), None],
        ) as wait_until_playing,
        patch.object(run.time, "sleep"),
    ):
        run._play_and_confirm(123, {"id": 123}, allow_retry=True)

    assert play_track.call_count == 2
    assert wait_until_playing.call_count == 2


def test_cdp_evaluate_returns_runtime_value():
    connection = MagicMock()
    connection.recv.return_value = json.dumps(
        {"id": 1, "result": {"result": {"value": {"current": 123}}}}
    )
    fake_websocket = SimpleNamespace(create_connection=MagicMock(return_value=connection))

    with (
        patch.object(run, "websocket", fake_websocket),
        patch.object(
            run,
            "_cdp_target",
            return_value={"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/1"},
        ),
    ):
        assert run._cdp_evaluate("1 + 1") == {"current": 123}

    fake_websocket.create_connection.assert_called_once_with(
        "ws://127.0.0.1/devtools/page/1",
        timeout=5,
        suppress_origin=True,
    )
    connection.close.assert_called_once_with()
