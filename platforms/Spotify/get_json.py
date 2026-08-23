"""Spotify 歌单/专辑数据提供器。

配置访问令牌时使用官方 Web API 完整分页；否则降级读取 Embed 页面。
"""

import json
import os
import re
import sys
import time

import requests

from platforms.provider_common import CollectionProvider

# 添加 settings 目录到路径，导入统一的路径管理模块
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'settings'))
from settings.user_data_path import ensure_dir, get_album_dir, get_playlist_dir

# Spotify 配置
SPOTIFY_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_ENV = "SPOTIFY_ACCESS_TOKEN"
SPOTIFY_PAGE_SIZE = 50
SPOTIFY_MAX_PAGES = 1000

# 创建全局 Session 用于连接复用
_session: requests.Session | None = None


def get_session() -> requests.Session:
    """获取全局 Session，复用 TCP 连接"""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": SPOTIFY_USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
    return _session


class PlaylistAlbumJson(CollectionProvider):
    """Spotify 歌单/专辑 JSON 获取类"""

    platform_name = "Spotify"

    def __init__(
        self,
        playlist_album_id: str,
        typename: str,
        access_token: str | None = None,
    ):
        super().__init__(playlist_album_id, typename)
        token = os.environ.get(SPOTIFY_TOKEN_ENV, "") if access_token is None else access_token
        self.access_token = token.strip()
        self.playlist_album_name: str = ""
        self.playlist_album_json: dict = {}
        self.complete = False
        self.source = ""

    def _fetch_data(self) -> None:
        """优先使用官方 Web API；没有令牌时使用 Embed 降级数据。"""
        self.playlist_album_name = ""
        self.playlist_album_json = {}
        self.complete = False
        self.source = ""
        if self.access_token:
            self._fetch_web_api()
        else:
            self._fetch_embed()

        print(f"已获取 {self.typename}: {self.playlist_album_name}")

    def _fetch_web_api(self) -> None:
        metadata = self._api_get(
            f"{SPOTIFY_API_BASE}/{self.typename}s/{self.playlist_album_id}"
        )
        self.playlist_album_name = str(metadata.get("name", ""))
        if not self.playlist_album_name:
            raise ValueError("Spotify 元数据缺少名称")

        endpoint = (
            f"{SPOTIFY_API_BASE}/playlists/{self.playlist_album_id}/items"
            if self.typename == "playlist"
            else f"{SPOTIFY_API_BASE}/albums/{self.playlist_album_id}/tracks"
        )
        track_list = self._fetch_all_tracks(endpoint, self.typename == "playlist")
        cover_url = self._first_image_url(metadata.get("images"))
        self.playlist_album_json = {
            "name": self.playlist_album_name,
            "trackList": track_list,
            "coverArt": {"sources": [{"url": cover_url}]} if cover_url else {},
        }
        self.source = "web_api"
        self.complete = True

    def _api_get(self, url: str, params: dict | None = None) -> dict:
        if not url.startswith(f"{SPOTIFY_API_BASE}/"):
            raise ValueError("拒绝向非 Spotify API 地址发送访问令牌")

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }
        session = get_session()
        for attempt in range(2):
            try:
                response = session.get(url, params=params, headers=headers, timeout=15)
            except requests.RequestException as exc:
                raise RuntimeError(f"Spotify API 网络请求失败: {exc}") from exc

            if response.status_code != 429:
                break
            if attempt == 1:
                retry_after = response.headers.get("Retry-After", "未知")
                raise RuntimeError(f"Spotify API 请求过于频繁，请在 {retry_after} 秒后重试")
            try:
                retry_after_seconds = max(0, int(response.headers.get("Retry-After", "1")))
            except ValueError:
                retry_after_seconds = 1
            time.sleep(min(retry_after_seconds, 10))

        if response.status_code == 401:
            raise RuntimeError("Spotify 访问令牌无效或已过期")
        if response.status_code == 403:
            raise RuntimeError(
                "Spotify API 拒绝访问；开发模式下只能读取当前账号拥有或协作的歌单"
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Spotify API 返回的 JSON 顶层不是对象")
        return payload

    def _fetch_all_tracks(self, endpoint: str, playlist_items: bool) -> list[dict]:
        next_url: str | None = endpoint
        params: dict | None = {"limit": SPOTIFY_PAGE_SIZE}
        expected_total: int | None = None
        raw_item_count = 0
        track_list: list[dict] = []
        seen_urls: set[str] = set()

        while next_url:
            if len(seen_urls) >= SPOTIFY_MAX_PAGES:
                raise ValueError("Spotify 分页超过安全上限")
            if next_url in seen_urls:
                raise ValueError("Spotify 分页 next 链接形成循环")
            seen_urls.add(next_url)

            page = self._api_get(next_url, params=params)
            params = None
            items = page.get("items")
            if not isinstance(items, list):
                raise ValueError("Spotify 分页响应缺少 items 列表")
            total = page.get("total")
            if isinstance(total, int) and total >= 0:
                if expected_total is not None and total != expected_total:
                    raise ValueError("Spotify 分页返回的总数前后不一致")
                expected_total = total

            raw_item_count += len(items)
            for item in items:
                if not isinstance(item, dict):
                    continue
                track = (
                    item.get("item") or item.get("track")
                    if playlist_items
                    else item
                )
                converted = self._convert_track(track)
                if converted:
                    track_list.append(converted)

            candidate = page.get("next")
            if candidate is not None and not isinstance(candidate, str):
                raise ValueError("Spotify 分页 next 字段格式无效")
            if candidate and not candidate.startswith(f"{SPOTIFY_API_BASE}/"):
                raise ValueError("Spotify 分页返回了非官方 API 地址")
            next_url = candidate

        if expected_total is not None and raw_item_count != expected_total:
            raise ValueError(
                f"Spotify 分页不完整: 预期 {expected_total} 项，实际 {raw_item_count} 项"
            )
        return track_list

    @staticmethod
    def _convert_track(track: object) -> dict | None:
        if not isinstance(track, dict):
            return None
        track_id = track.get("id")
        uri = track.get("uri")
        if track.get("type") not in (None, "track") or track.get("is_local") is True:
            return None
        if not isinstance(track_id, str) or not track_id:
            return None
        if not isinstance(uri, str) or not uri.startswith("spotify:track:"):
            uri = f"spotify:track:{track_id}"
        artists = track.get("artists", [])
        artist_names = [
            str(artist.get("name", ""))
            for artist in artists
            if isinstance(artist, dict) and artist.get("name")
        ] if isinstance(artists, list) else []
        return {
            "uri": uri,
            "title": str(track.get("name", "")),
            "subtitle": ", ".join(artist_names),
            "duration": track.get("duration_ms", 0),
        }

    @staticmethod
    def _first_image_url(images: object) -> str:
        if not isinstance(images, list):
            return ""
        for image in images:
            if isinstance(image, dict) and image.get("url"):
                return str(image["url"])
        return ""

    def _fetch_embed(self) -> None:
        """读取无需令牌但可能截断的 Embed 数据。"""
        session = get_session()
        embed_url = f"https://open.spotify.com/embed/{self.typename}/{self.playlist_album_id}"

        try:
            response = session.get(embed_url, timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"网络请求失败，请检查网络环境或代理设置！具体报错: {e}")

        # 从 HTML 中提取 __NEXT_DATA__ JSON
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            response.text
        )
        if not match:
            raise RuntimeError(
                f"无法在页面源码中找到 __NEXT_DATA__ 节点，Spotify 可能更改了网页结构。\n"
                f"请求的URL: {embed_url}"
            )

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            raise RuntimeError("解析内部 JSON 失败。")

        # 提取 entity
        try:
            entity = data["props"]["pageProps"]["state"]["data"]["entity"]
        except KeyError:
            raise RuntimeError("JSON 结构有变，无法找到 entity 数据。")

        self.playlist_album_json = entity
        self.playlist_album_name = entity.get("name", "")
        self.source = "embed"
        self.complete = False

    def _load_from_cache(self) -> bool:
        cache_data = self._read_cache()
        if not cache_data:
            return False

        self.playlist_album_name = cache_data.get("playlist_album_name", "")
        tracks_info = cache_data.get("tracks_info", [])
        if not tracks_info:
            tracks_info = [{"id": track_id} for track_id in cache_data.get("song_ids", [])]
        track_list = [
            {
                "uri": f"spotify:track:{track.get('id', '')}",
                "title": track.get("title", ""),
                "subtitle": track.get("subtitle", ""),
                "duration": track.get("duration", 0),
            }
            for track in tracks_info
        ]
        cover_url = cache_data.get("coverUrl", "")
        self.playlist_album_json = {
            "name": self.playlist_album_name,
            "trackList": track_list,
            "coverArt": {"sources": [{"url": cover_url}]} if cover_url else {},
        }
        self.complete = bool(cache_data.get("complete", False))
        self.source = str(cache_data.get("source", "cache"))
        return True

    def get_id(self) -> str:
        return self.playlist_album_id

    def get_name(self) -> str:
        return self.playlist_album_name

    def get_songs(self) -> list[str]:
        """获取歌曲 ID 列表（纯 track ID，不带 spotify:track: 前缀）"""
        songs: list[str] = []

        track_list = self.playlist_album_json.get("trackList", [])
        for track in track_list:
            uri = track.get("uri", "")
            # URI 格式: spotify:track:3T0UCGe1Vrfh57fM1B0Mgi
            if uri.startswith("spotify:track:"):
                track_id = uri.replace("spotify:track:", "")
                songs.append(track_id)

        return songs

    def save(self) -> None:
        """保存到本地 JSON 文件"""
        path = get_playlist_dir("Spotify") if self.typename == "playlist" else get_album_dir("Spotify")
        ensure_dir(path)

        song_ids = self.get_songs()

        track_list = self.playlist_album_json.get("trackList", [])
        tracks_info = []
        for track in track_list:
            uri = track.get("uri", "")
            track_id = uri.replace("spotify:track:", "") if uri.startswith("spotify:track:") else uri
            tracks_info.append({
                "id": track_id,
                "title": track.get("title", ""),
                "subtitle": track.get("subtitle", ""),
                "duration": track.get("duration", 0),
            })

        # 获取封面 URL
        cover_art = self.playlist_album_json.get("coverArt", {})
        sources = cover_art.get("sources", [{}])
        cover_url = sources[0].get("url", "") if sources else ""

        # 专辑封面为空时，从第一首歌的 track embed 页面获取
        if not cover_url and self.typename == "album":
            track_list = self.playlist_album_json.get("trackList", [])
            if track_list:
                first_uri = track_list[0].get("uri", "")
                if first_uri.startswith("spotify:track:"):
                    track_id = first_uri.replace("spotify:track:", "")
                    cover_url = self._fetch_track_cover(track_id)

        data = {
            "playlist_album_id": self.playlist_album_id,
            "playlist_album_name": self.playlist_album_name,
            "playlist_album_type": self.typename,
            "song_ids": song_ids,
            "tracks_info": tracks_info,
            "coverUrl": cover_url,
            "complete": self.complete,
            "source": self.source,
        }

        self._write_cache(data)
        print(f"已保存 {self.typename} {self.playlist_album_id} {self.playlist_album_name} 到 {path}")

    def _fetch_track_cover(self, track_id: str) -> str:
        """从 Spotify track embed 页面抓取专辑封面 URL"""
        session = get_session()
        url = f"https://open.spotify.com/embed/track/{track_id}"
        try:
            response = session.get(url, timeout=10)
            response.raise_for_status()
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                response.text
            )
            if not match:
                return ""
            data = json.loads(match.group(1))
            entity = data["props"]["pageProps"]["state"]["data"]["entity"]
            images = entity.get("visualIdentity", {}).get("image", [])
            for img in images:
                if img.get("maxHeight") == 300:
                    return img.get("url", "")
        except Exception:
            pass
        return ""


if __name__ == '__main__':
    # 测试代码
    if len(sys.argv) > 2:
        playlist_id = sys.argv[1]
        typename = sys.argv[2]
    else:
        playlist_id = "37i9dQZF1EIZ9u9vIT9NHT"
        typename = "playlist"

    playlist = PlaylistAlbumJson(playlist_id, typename).refresh()
    print(f"名称: {playlist.get_name()}")
    print(f"歌曲数量: {len(playlist.get_songs())}")
    if not playlist.is_stale:
        playlist.save()
