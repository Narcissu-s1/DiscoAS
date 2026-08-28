"""网易云音乐后台播放控制。"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

try:
    import websocket
except ImportError:  # pragma: no cover - 安装依赖前提供可读错误
    websocket = None


DEFAULT_CDP_PORT = 9223
_CDP_LOCK = threading.Lock()
_PLAY_LOCK = threading.Lock()


class BackgroundPlaybackUnavailableError(RuntimeError):
    """网易云后台播放后端当前不可用。"""


def _cdp_port() -> int:
    raw_port = os.environ.get("DISCOAS_NETEASE_CDP_PORT", str(DEFAULT_CDP_PORT))
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise BackgroundPlaybackUnavailableError("网易云后台控制端口必须是整数") from exc
    if not 1 <= port <= 65535:
        raise BackgroundPlaybackUnavailableError("网易云后台控制端口必须在 1 到 65535 之间")
    return port


def _cloudmusic_executable() -> Path:
    configured = os.environ.get("CLOUDMUSIC_EXE")
    if configured:
        return Path(configured).expanduser()

    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "NetEase"
        / "CloudMusic"
        / "cloudmusic.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "NetEase"
        / "CloudMusic"
        / "cloudmusic.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "NetEase"
        / "CloudMusic"
        / "cloudmusic.exe",
    ]
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def _is_cloudmusic_running() -> bool:
    completed = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq cloudmusic.exe", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return "cloudmusic.exe" in completed.stdout.lower()


def _cdp_target() -> dict:
    endpoint = f"http://127.0.0.1:{_cdp_port()}/json"
    try:
        with urllib.request.urlopen(endpoint, timeout=0.8) as response:
            targets = json.load(response)
    except Exception as exc:
        raise BackgroundPlaybackUnavailableError("网易云本地后台控制通道尚未就绪") from exc

    for target in targets:
        if target.get("type") == "page" and str(target.get("url", "")).startswith("orpheus://"):
            return target
    raise BackgroundPlaybackUnavailableError("网易云后台控制页面不存在")


def _wait_for_cdp(timeout: float = 12.0) -> dict:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return _cdp_target()
        except BackgroundPlaybackUnavailableError as exc:
            last_error = exc
            time.sleep(0.2)
    raise BackgroundPlaybackUnavailableError("网易云启动后未能建立后台控制通道") from last_error


def _launch_with_background_control() -> None:
    executable = _cloudmusic_executable()
    if not executable.is_file():
        raise BackgroundPlaybackUnavailableError(f"未找到网易云音乐：{executable}")

    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    subprocess.Popen(
        [
            str(executable),
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={_cdp_port()}",
        ],
        cwd=str(executable.parent),
        startupinfo=startupinfo,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _ensure_control_channel() -> bool:
    """确保控制通道可用；返回值表示是否刚刚启动了网易云。"""
    try:
        _cdp_target()
        return False
    except BackgroundPlaybackUnavailableError:
        if _is_cloudmusic_running():
            raise BackgroundPlaybackUnavailableError(
                "网易云已在运行，但没有启用后台控制；请先从网易云托盘菜单完全退出一次"
            )
        _launch_with_background_control()
        _wait_for_cdp()
        return True


def _cdp_evaluate(expression: str, *, await_promise: bool = False):
    if websocket is None:
        raise BackgroundPlaybackUnavailableError("缺少 websocket-client，无法连接网易云后台控制通道")

    target = _cdp_target()
    websocket_url = target.get("webSocketDebuggerUrl")
    if not websocket_url:
        raise BackgroundPlaybackUnavailableError("网易云后台控制页面没有 WebSocket 地址")

    with _CDP_LOCK:
        connection = websocket.create_connection(
            websocket_url,
            timeout=5,
            suppress_origin=True,
        )
        try:
            connection.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": expression,
                            "returnByValue": True,
                            "awaitPromise": await_promise,
                        },
                    }
                )
            )
            while True:
                message = json.loads(connection.recv())
                if message.get("id") != 1:
                    continue
                result = message.get("result") or {}
                exception = result.get("exceptionDetails")
                if exception:
                    description = (
                        (exception.get("exception") or {}).get("description")
                        or exception.get("text")
                        or "未知 JavaScript 错误"
                    )
                    raise BackgroundPlaybackUnavailableError(f"网易云后台控制执行失败：{description}")
                return (result.get("result") or {}).get("value")
        finally:
            connection.close()


def _ensure_client_runtime() -> None:
    ready = _cdp_evaluate(
        "(()=>{if(typeof webpackJsonp==='undefined')return false;"
        "webpackJsonp.push([[987660],{987660:function(module,exports,require){"
        "window.__discoas_cm_require__=require;}},[[987660]]]);"
        "const r=window.__discoas_cm_require__;if(typeof r!=='function')return false;"
        "const seen=new Set();const findApi=(root)=>{const queue=[[root,0]];"
        "while(queue.length){const [value,depth]=queue.shift();"
        "if(!value||(typeof value!=='object'&&typeof value!=='function')||seen.has(value))continue;"
        "seen.add(value);if(typeof value.getStore==='function'&&typeof value.getDispatch==='function')return value;"
        "if(depth>=2)continue;let keys=[];try{keys=Object.keys(value).slice(0,120)}catch(e){continue;}"
        "for(const key of keys){try{queue.push([value[key],depth+1])}catch(e){}}}return null};"
        "for(const id of Object.keys(r.c||{})){const module=r.c[id];"
        "const api=module&&findApi(module.exports);if(api){window.__discoas_cm_store_api__=api;return true}}"
        "return false})()"
    )
    if ready is not True:
        raise BackgroundPlaybackUnavailableError("当前网易云版本不兼容后台播放控制")


def _client_state() -> dict:
    _ensure_client_runtime()
    state = _cdp_evaluate(
        "(()=>{const s=__discoas_cm_store_api__.getStore();"
        "return {status:s.playing.playingState,"
        "current:s.playing.curPlaying?{id:Number(s.playing.curPlaying.resourceId)}:null,"
        "queue:s.playingList.curPlayingList.map(x=>({id:Number(x.resourceId)}))}})()"
    )
    if not isinstance(state, dict):
        raise BackgroundPlaybackUnavailableError("网易云返回了无法识别的播放状态")
    return state


def _wait_for_player_ready(timeout: float = 12.0) -> None:
    """冷启动时等待播放器状态连续可读，避免首条播放指令过早丢失。"""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    stable_reads = 0
    while time.monotonic() < deadline:
        try:
            state = _client_state()
            if "status" in state and isinstance(state.get("queue"), list):
                stable_reads += 1
                if stable_reads >= 2:
                    return
            else:
                stable_reads = 0
        except BackgroundPlaybackUnavailableError as exc:
            last_error = exc
            stable_reads = 0
        time.sleep(0.25)
    raise BackgroundPlaybackUnavailableError("网易云播放器启动后未能进入可控制状态") from last_error


def _play_track(song_id: int, track: dict) -> None:
    state = _client_state()
    queue = state.get("queue") or []
    current_id = (state.get("current") or {}).get("id")
    current_index = next(
        (index for index, item in enumerate(queue) if item.get("id") == current_id),
        -1,
    )
    payload = {
        "trackList": [track],
        "trackFrom": {
            "text": "DiscoAS",
            "href": "",
            "resourceType": "track",
            "scene": "search",
            "fromInfo": {
                "originalScene": "search",
                "originalResourceType": "track",
                "computeSourceResourceType": "track",
                "sourceData": {},
            },
        },
        "options": {
            "clear": False,
            "play": True,
            "playId": song_id,
            "offset": current_index,
        },
        "triggerScene": "search",
        "triggerAction": "nextPlay",
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    _ensure_client_runtime()
    _cdp_evaluate(
        "(async()=>{const d=__discoas_cm_store_api__.getDispatch();"
        f"await d({{type:'playingList/addItemToCurPlayingList',payload:{serialized}}});"
        "return true})()",
        await_promise=True,
    )


def _wait_until_playing(song_id: int, timeout: float = 2.5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = (_client_state().get("current") or {}).get("id")
        if current == song_id:
            return
        time.sleep(0.1)
    raise BackgroundPlaybackUnavailableError("网易云已接收播放命令，但当前歌曲校验失败")


def _play_and_confirm(song_id: int, track: dict, *, allow_retry: bool) -> None:
    attempts = 2 if allow_retry else 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        _play_track(song_id, track)
        try:
            _wait_until_playing(song_id, timeout=4.0 if allow_retry else 2.5)
            return
        except BackgroundPlaybackUnavailableError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.35)
    raise BackgroundPlaybackUnavailableError("网易云未能播放所选歌曲") from last_error


def play_song(song_card) -> bool:
    """在不操作网易云窗口的前提下精确播放歌曲。"""
    try:
        with _PLAY_LOCK:
            newly_launched = _ensure_control_channel()
            if newly_launched:
                _wait_for_player_ready()
            song_id = int(song_card.get_id())
            track = song_card.song_detail_json
            if not isinstance(track, dict) or int(track.get("id", 0)) != song_id:
                raise BackgroundPlaybackUnavailableError("歌曲详情尚未加载，无法构造后台播放命令")
            _play_and_confirm(song_id, track, allow_retry=newly_launched)
        print(f"[网易云] 后台播放已确认，歌曲 ID：{song_id}")
        return True
    except Exception as exc:
        print(f"[网易云] 后台播放失败：{exc}")
        return False
