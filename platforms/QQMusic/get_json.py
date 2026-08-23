"""
QQ音乐 API 模块 - 使用签名算法

基于 qqmusic-api-python 库的签名算法实现
支持本地缓存回退
"""

import os
import sys

import requests

from platforms.provider_common import CollectionProvider, response_json

# 添加 settings 目录到路径，导入统一的路径管理模块
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'settings'))
from settings.user_data_path import ensure_dir, get_album_dir, get_playlist_dir


class PlaylistAlbumJson(CollectionProvider):
    """QQ音乐歌单/专辑JSON获取类"""

    platform_name = "QQMusic"

    def __init__(self, playlist_album_id: str, typename: str):
        super().__init__(playlist_album_id, typename)
        self.playlist_album_name: str = ""
        self.playlist_album_json: dict | list = {}
        self.cover_url: str = ""
        self.album_mid: str = ""  # 用于专辑封面 URL 构造

    def _fetch_data(self) -> None:
        """获取歌单/专辑数据"""
        self.playlist_album_name = ""
        self.playlist_album_json = {}
        self.cover_url = ""
        self.album_mid = ""

        if self.typename == "playlist":
            # 获取歌单详情 - 使用 qzone-music API（需要 type=1 和 newcp=1 参数）
            url = "https://i.y.qq.com/qzone-music/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg"
            params = {
                "disstid": int(self.playlist_album_id) if self.playlist_album_id.isdigit() else self.playlist_album_id,
                "json": 1,
                "utf8": 1,
                "noCache": 1,
                "loginUin": 0,
                "hostUin": 0,
                "format": "json",
                "inCharset": "utf8",
                "outCharset": "utf-8",
                "notice": 0,
                "platform": "yqq",
                "needNewCode": 0,
                "type": 1,
                "newcp": 1
            }

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 Edg/116.0.1938.54",
                "Referer": "https://y.qq.com/"
            }

            response = requests.get(url, params=params, headers=headers, timeout=10)
            data = response_json(response)

            # 解析响应
            cdlist = data.get("cdlist", [])
            if cdlist:
                self.playlist_album_name = cdlist[0].get("dissname", "")
                self.playlist_album_json = {"songlist": cdlist[0].get("songlist", [])}
                self.cover_url = cdlist[0].get("logo", "")
            else:
                raise ValueError("无法获取歌单信息")

        elif self.typename == "album":
            # 获取专辑详情 - 使用 v8 API
            url = "https://i.y.qq.com/v8/fcg-bin/fcg_v8_album_info_cp.fcg"

            # 修复：判断是传入了整型 albumid 还是字符串 albummid
            is_digit = self.playlist_album_id.isdigit()
            param_key = "albumid" if is_digit else "albummid"
            param_val = int(self.playlist_album_id) if is_digit else self.playlist_album_id

            params = {
                param_key: param_val, # 动态设置键名
                "json": 1,
                "utf8": 1,
                "loginUin": 0,
                "hostUin": 0,
                "format": "json",
                "inCharset": "utf8",
                "outCharset": "utf-8",
                "notice": 0,
                "platform": "yqq",
                "needNewCode": 0
                # "type" 和 "newcp" 对这个特定的 v8 API 其实不是必需的
            }

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 Edg/116.0.1938.54",
                "Referer": "https://y.qq.com/"
            }

            response = requests.get(url, params=params, headers=headers, timeout=10)
            data = response_json(response)

            # 解析响应
            album_data = data.get("data", {})
            if album_data:
                self.playlist_album_name = album_data.get("name", "")
                # data["list"] 数组里面正常包含了每一首歌的字典，里面拥有 "songid" / "songmid"
                songlist = album_data.get("list", [])
                self.playlist_album_json = {"songlist": songlist}
                # 保存第一首歌的 album.mid 用于构造专辑封面 URL
                if songlist:
                    first_song = songlist[0]
                    self.album_mid = first_song.get("album", {}).get("mid", "")
                    first_song_id = first_song.get("songid") or first_song.get("id")
                    if not self.album_mid and first_song_id:
                        self.album_mid = self._fetch_first_song_album_mid(first_song_id)
            else:
                raise ValueError(f"无法获取专辑信息，API返回: {data}")
        else:
            raise ValueError("typename must be 'playlist' or 'album'")

        print(f"已获取{self.typename}: {self.playlist_album_name}")

    def _load_from_cache(self) -> bool:
        """从本地缓存加载数据"""
        cache_data = self._read_cache()
        if not cache_data:
            return False

        self.playlist_album_name = cache_data.get("playlist_album_name", "")
        self.cover_url = cache_data.get("coverUrl", "")
        self.album_mid = cache_data.get("album_mid", "")
        self.playlist_album_json = {
            "songlist": [{"id": song_id} for song_id in cache_data.get("song_ids", [])]
        }
        print(f"已从缓存加载{self.typename}: {self.playlist_album_name}")
        return True

    def get_id(self) -> str:
        return self.playlist_album_id

    def get_name(self) -> str:
        return self.playlist_album_name

    def get_songs(self) -> list[int]:
        """获取歌曲ID列表"""
        songs: list[int] = []

        if self.typename == "playlist":
            # 从歌单中提取歌曲ID (支持 songid 或 id)
            if "songlist" in self.playlist_album_json:
                for song in self.playlist_album_json.get("songlist", []):
                    # 优先使用 songid（QQ音乐API返回的字段名）
                    if "songid" in song:
                        songs.append(song["songid"])
                    elif "id" in song:
                        songs.append(song["id"])

        elif self.typename == "album" and "songlist" in self.playlist_album_json:
            # 从专辑中提取歌曲ID
            for song in self.playlist_album_json["songlist"]:
                if "songid" in song:
                    songs.append(song["songid"])
                elif "id" in song:
                    songs.append(song["id"])

        return songs

    def _fetch_first_song_album_mid(self, song_id: int) -> str:
        """获取第一首歌的 album.mid 用于构造专辑封面 URL"""
        try:
            import platforms.QQMusic.qq_sign as qs
            params = {
                "types": [0],
                "ids": [song_id],
                "modify_stamp": [0],
                "ctx": 0,
                "client": 1,
            }
            api_result = qs.make_api_request("music.trackInfo.UniformRuleCtrl", "CgiGetTrackInfo", params)
            tracks = api_result.get("tracks", [])
            if not tracks:
                tracks = (
                    api_result.get("music.trackInfo.UniformRuleCtrl", {})
                    .get("data", {})
                    .get("tracks", [])
                )
            if tracks:
                album = tracks[0].get("album", {})
                return album.get("mid", "")
        except Exception as e:
            print(f"获取歌曲专辑信息失败: {e}")
        return ""

    def save(self) -> None:
        """保存到本地JSON文件"""
        # 使用统一的路径管理
        path = get_playlist_dir("QQMusic") if self.typename == "playlist" else get_album_dir("QQMusic")
        ensure_dir(path)

        song_ids = self.get_songs()

        # 获取封面 URL：专辑使用 album_mid 构造 URL
        cover_url = self.cover_url
        if not cover_url and self.typename == "album" and self.album_mid:
            cover_url = f"https://y.qq.com/music/photo_new/T002R300x300M000{self.album_mid}_1.jpg"

        data = {
            "playlist_album_id": self.playlist_album_id,
            "playlist_album_name": self.playlist_album_name,
            "playlist_album_type": self.typename,
            "song_ids": song_ids,
            "coverUrl": cover_url,
            "album_mid": self.album_mid,
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
        playlist_id = "9595891286"
        typename = "playlist"

    playlist = PlaylistAlbumJson(playlist_id, typename).refresh()
    print(f"名称: {playlist.get_name()}")
    print(f"歌曲数量: {len(playlist.get_songs())}")
    if not playlist.is_stale:
        playlist.save()
