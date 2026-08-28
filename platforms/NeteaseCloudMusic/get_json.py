"""
网易云音乐 API 模块 - 性能优化版

使用requests.Session复用连接，提升响应速度
"""

import os
import sys
from urllib.parse import parse_qs, urlparse

import requests

from platforms.provider_common import CollectionProvider, response_json

# 添加 settings 目录到路径，导入统一的路径管理模块
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'settings'))
from settings.user_data_path import ensure_dir, get_album_dir, get_playlist_dir

# 网易云音乐API配置
NETEASE_BASE_URL = "https://music.163.com"
NETEASE_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# 创建全局Session用于连接复用
_session: requests.Session | None = None


def _normalize_collection_input(value: str, typename: str) -> str:
    """从网易云歌单/专辑链接中提取内部使用的数字 ID。"""
    normalized = value.strip()
    if not normalized.lower().startswith(("http://", "https://")):
        return normalized

    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower()
    if hostname != "music.163.com" and not hostname.endswith(".music.163.com"):
        raise ValueError("仅支持 music.163.com 的歌单/专辑链接")

    path = parsed.path
    query = parsed.query
    if parsed.fragment.startswith("/"):
        fragment = urlparse(parsed.fragment)
        path = fragment.path
        query = fragment.query or query

    expected_path = f"/{typename}"
    if not path.rstrip("/").endswith(expected_path):
        type_name = "歌单" if typename == "playlist" else "专辑"
        raise ValueError(f"该网易云链接不是{type_name}链接")

    collection_id = parse_qs(query, keep_blank_values=True).get("id", [""])[0].strip()
    if not collection_id.isdigit():
        raise ValueError("网易云链接中没有有效的数字 ID")
    return collection_id


def get_session() -> requests.Session:
    """获取全局Session，复用TCP连接"""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": NETEASE_USER_AGENT,
            "Referer": NETEASE_BASE_URL,
            "Origin": NETEASE_BASE_URL,
        })
    return _session


class PlaylistAlbumJson(CollectionProvider):
    """网易云音乐歌单/专辑JSON获取类"""

    platform_name = "NeteaseCloudMusic"

    def __init__(self, playlist_album_id: str, typename: str):
        super().__init__(playlist_album_id.strip(), typename)
        self.playlist_album_id = _normalize_collection_input(
            self.playlist_album_id, self.typename
        )
        self.playlist_album_name: str = ""
        self.playlist_album_json: dict | list = {}

    def _fetch_data(self) -> None:
        """获取歌单/专辑数据"""
        session = get_session()
        self.playlist_album_name = ""
        self.playlist_album_json = {}

        if self.typename == "playlist":
            # 获取歌单详情
            url = f"{NETEASE_BASE_URL}/api/v6/playlist/detail"
            params = {
                "id": self.playlist_album_id,
                "limit": 20000,
                "offset": 0,
                "total": True,
            }
            try:
                response = session.get(url, params=params, timeout=10)
                data = response_json(response)

                if "playlist" in data:
                    self.playlist_album_name = data["playlist"].get("name", "")
                    self.playlist_album_json = data
                else:
                    raise ValueError("无法获取歌单信息")
            except Exception as e:
                print(f"获取歌单详情失败: {e}")
                raise

        elif self.typename == "album":
            # 获取专辑详情
            url = f"{NETEASE_BASE_URL}/api/album/{self.playlist_album_id}"
            params = {
                "limit": 20000,
            }
            try:
                response = session.get(url, params=params, timeout=10)
                data = response_json(response)

                if "album" in data:
                    self.playlist_album_name = data["album"].get("name", "")
                    self.playlist_album_json = data
                else:
                    raise ValueError("无法获取专辑信息")
            except Exception as e:
                print(f"获取专辑详情失败: {e}")
                raise
        else:
            raise ValueError("typename must be 'playlist' or 'album'")

        print(f"已获取{self.typename}: {self.playlist_album_name}")

    def _load_from_cache(self) -> bool:
        cache_data = self._read_cache()
        if not cache_data:
            return False

        self.playlist_album_name = cache_data.get("playlist_album_name", "")
        song_ids = cache_data.get("song_ids", [])
        cover_url = cache_data.get("coverUrl", "")
        if self.typename == "playlist":
            self.playlist_album_json = {
                "playlist": {
                    "name": self.playlist_album_name,
                    "trackIds": [{"id": song_id} for song_id in song_ids],
                    "coverImgUrl": cover_url,
                }
            }
        else:
            self.playlist_album_json = {
                "album": {
                    "name": self.playlist_album_name,
                    "songs": [{"id": song_id} for song_id in song_ids],
                    "picUrl": cover_url,
                }
            }
        return True

    def get_id(self) -> str:
        return self.playlist_album_id

    def get_name(self) -> str:
        return self.playlist_album_name

    def get_songs(self) -> list[int]:
        """获取歌曲ID列表"""
        songs: list[int] = []

        if self.typename == "playlist":
            # 从歌单中提取歌曲ID
            if "playlist" in self.playlist_album_json:
                playlist = self.playlist_album_json.get("playlist", {})

                # 优先使用trackIds（更完整）
                track_ids = playlist.get("trackIds", [])
                for track in track_ids:
                    if "id" in track:
                        songs.append(track["id"])

                # 如果trackIds为空，使用tracks
                if not songs:
                    for track in playlist.get("tracks", []):
                        if "id" in track:
                            songs.append(track["id"])

        elif self.typename == "album" and "album" in self.playlist_album_json:
            # 从专辑中提取歌曲ID
            for song in self.playlist_album_json["album"].get("songs", []):
                if "id" in song:
                    songs.append(song["id"])

        return songs

    def save(self) -> None:
        """保存到本地JSON文件"""
        # 使用统一的路径管理
        if self.typename == "playlist":
            path = get_playlist_dir("NeteaseCloudMusic")
        else:
            path = get_album_dir("NeteaseCloudMusic")
        ensure_dir(path)

        song_ids = self.get_songs()
        # 获取封面 URL
        if self.typename == "playlist":
            cover_url = self.playlist_album_json.get("playlist", {}).get("coverImgUrl", "")
        else:
            cover_url = self.playlist_album_json.get("album", {}).get("picUrl", "")
        data = {
            "playlist_album_id": self.playlist_album_id,
            "playlist_album_name": self.playlist_album_name,
            "playlist_album_type": self.typename,
            "song_ids": song_ids,
            "coverUrl": cover_url
        }

        self._write_cache(data)
        print(f"已保存{self.typename} {self.playlist_album_id} {self.playlist_album_name} 到 {path}")


if __name__ == '__main__':
    # 测试代码
    import sys
    if len(sys.argv) > 2:
        playlist_id = sys.argv[1]
        typename = sys.argv[2]
    else:
        playlist_id = "8285082830"
        typename = "playlist"

    playlist = PlaylistAlbumJson(playlist_id, typename).refresh()
    print(f"名称: {playlist.get_name()}")
    print(f"歌曲数量: {len(playlist.get_songs())}")
    if not playlist.is_stale:
        playlist.save()
