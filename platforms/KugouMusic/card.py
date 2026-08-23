"""
酷狗音乐歌曲卡片模块

用于获取歌曲信息和封面
"""

import base64
import json
import os

# 导入共享的 Session
from platforms.KugouMusic.get_json import get_session


class SongCard:
    """酷狗音乐歌曲卡片类"""

    # 默认神秘歌曲封面
    DEFAULT_MYSTERY_PIC = "https://imgessl.kugou.com/stdmusic/480/20201111/20201111024230620482.jpg"

    def __init__(
        self,
        song_id: str,
        mystery_mode: bool = False,
        mystery_pic_url: str | None = None
    ):
        # song_id 就是 hash
        self.song_id = song_id
        self.song_hash = song_id
        self.mystery_mode = mystery_mode
        self.mystery_pic_url = mystery_pic_url or self.DEFAULT_MYSTERY_PIC

        # 歌曲详情数据
        self.song_name: str | None = None
        self.song_artist_names: list[str] = []
        self.window_name: str | None = None
        self._real_window_name: str | None = ""  # 用于播放器窗口匹配，初始为空字符串防止未初始化
        self.album_pic_url: str | None = None
        self.have_loaded: bool = False

    def load_song_detail(self) -> None:
        """加载歌曲详情"""
        if self.have_loaded:
            return

        try:
            # 从 songs_info 中查找对应歌曲的信息
            song_info = self._find_song_info()
            if not song_info:
                raise ValueError("未找到歌曲信息")

            # filename 格式：歌手1、歌手2 - 歌名
            filename = song_info.get("filename", "")

            if " - " in filename:
                parts = filename.split(" - ")
                artist_part = parts[0].strip()
                self.song_name = " - ".join(parts[1:]).strip()
                self.song_artist_names = [a.strip() for a in artist_part.split("、")]
            else:
                self.song_name = filename
                self.song_artist_names = ["???"]

            # 获取封面
            self.album_pic_url = self._get_cover_url(song_info)

        except Exception as e:
            print(f"加载歌曲详情失败: {e}")
            self._set_error_defaults()

        # 神秘模式下覆盖为假数据用于显示，但真实数据已保存在上述属性中
        if self.mystery_mode:
            self.song_name = "???"
            self.song_artist_names = ["???"]
            self.album_pic_url = self.mystery_pic_url

        # 始终构建真实窗口名（用于播放器窗口匹配，不受 mystery_mode 影响）
        # 酷狗窗口格式：{歌手1}、{歌手2} - {歌名}
        self._real_window_name = "、".join(self.song_artist_names) + " - " + self.song_name if self.song_artist_names else self.song_name
        # window_name 用于 UI 显示（mystery_mode 下为假数据）
        self.window_name = self._real_window_name
        self.have_loaded = True

    def _find_song_info(self) -> dict | None:
        """从 songs_info 中查找歌曲信息"""
        try:
            from settings.user_data_path import get_album_dir, get_playlist_dir

            # 先搜 playlist 目录
            playlist_dir = get_playlist_dir("KugouMusic")
            if os.path.exists(playlist_dir):
                for filename in os.listdir(playlist_dir):
                    if filename.endswith(".json"):
                        filepath = os.path.join(playlist_dir, filename)
                        with open(filepath, encoding="utf-8") as f:
                            data = json.load(f)
                        songs_info = data.get("songs_info", [])
                        for song in songs_info:
                            if song.get("hash", "").upper() == self.song_hash.upper():
                                return song

            # 再搜 album 目录
            album_dir = get_album_dir("KugouMusic")
            if os.path.exists(album_dir):
                for filename in os.listdir(album_dir):
                    if filename.endswith(".json"):
                        filepath = os.path.join(album_dir, filename)
                        with open(filepath, encoding="utf-8") as f:
                            data = json.load(f)
                        songs_info = data.get("songs_info", [])
                        for song in songs_info:
                            if song.get("hash", "").upper() == self.song_hash.upper():
                                return song

            return None
        except Exception as e:
            print(f"查找歌曲信息失败: {e}")
            return None

    def _get_cover_url(self, song_info: dict) -> str:
        """获取封面 URL - 参考 test.py"""
        album_id = str(song_info.get("album_id", song_info.get("albumid", "")))
        session = get_session()
        headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"}

        # 方法1：通过 album_id 获取封面
        if album_id and album_id != '0':
            album_url = f"http://mobilecdn.kugou.com/api/v3/album/info?albumid={album_id}"
            try:
                album_res = session.get(album_url, headers=headers, timeout=10).json()
                if album_res.get('status') == 1 and album_res.get('data'):
                    raw_cover = album_res['data'].get('sizable_cover') or album_res['data'].get('imgurl', '')
                    if raw_cover:
                        return raw_cover.replace('{size}', '400')
            except Exception:
                pass

        # 方法2：通过 hash 获取封面
        fallback_url = f"http://m.kugou.com/app/i/getSongInfo.php?cmd=playInfo&hash={self.song_hash}"
        try:
            fallback_res = session.get(fallback_url, headers=headers, timeout=10).json()
            raw_cover = fallback_res.get('imgUrl', fallback_res.get('pic', ''))
            if raw_cover:
                return raw_cover.replace('{size}', '400')
        except Exception:
            pass

        return self.mystery_pic_url or ""

    def _set_error_defaults(self) -> None:
        """设置错误默认值为未知"""
        self.song_name = "???"
        self.song_artist_names = ["???"]
        self.window_name = "、".join(self.song_artist_names) + " - " + self.song_name
        self._real_window_name = self.window_name
        self.album_pic_url = self.mystery_pic_url
        self.have_loaded = True

    def get_id(self) -> str:
        return self.song_hash

    def get_name(self) -> str:
        if self.mystery_mode:
            return "???"
        return self.song_name or "???"

    def get_artist_names(self) -> list[str]:
        if self.mystery_mode:
            return ["???"]
        return self.song_artist_names or ["???"]

    def get_window_name(self) -> str:
        return self._real_window_name or ""

    def get_album_pic_url(self) -> str:
        if self.mystery_mode:
            return self.mystery_pic_url
        if not self.have_loaded:
            self.load_song_detail()
        return self.album_pic_url or self.mystery_pic_url

    def get_cover_url(self) -> str:
        """获取封面 URL（别名）"""
        return self.get_album_pic_url()

    def get_scheme_url(self) -> str:
        """生成酷狗音乐 scheme URL 用于唤起播放 - 参考 test.py"""
        # 找到歌曲信息
        song_info = self._find_song_info()
        filename = "未知歌曲.mp3"
        if song_info:
            orig_filename = song_info.get("filename", "")
            if orig_filename:
                filename = orig_filename
                if not filename.lower().endswith('.mp3'):
                    filename += ".mp3"

        # 明确要求酷狗保留当前队列，并把所选歌曲插入后立即播放。
        payload = {
            "Files": [
                {
                    "filename": filename,
                    "hash": self.song_hash
                }
            ],
            "Count": "1",
            "AddPlayQueue": 1,
            "NoPlayAds": 1,
            "QueueInfo": {
                "Play": "1",
                "PlayAll": "0",
                "Clear": "0",
                "Insert": "1",
                "Force": "1",
                "IsMV": "0",
                "Index": "0",
                "AddToDefaultList": "0",
                "climax": "0"
            }
        }

        # 1. 转化为紧凑型 JSON 字符串
        json_str = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        # 2. UTF-8 编码后 Base64 转换
        b64_str = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        # 3. 拼接最终协议
        return f"kugou://play?p={b64_str}"

    def get_debug_info(self) -> str:
        """返回歌曲真实信息，用于后台调试输出"""
        song_info = self._find_song_info()
        if song_info:
            filename = song_info.get("filename", "")
            return filename
        return self.get_name() + " - " + "/".join(self.get_artist_names())


# 测试代码
if __name__ == '__main__':
    # 测试歌曲 hash
    test_hash = "4809EE31DEF9945C7751E3FD7BF7C009"

    song = SongCard(test_hash)
    song.load_song_detail()

    print(f"歌曲 ID: {song.get_id()}")
    print(f"歌曲名: {song.get_name()}")
    print(f"艺术家: {song.get_artist_names()}")
    print(f"封面: {song.get_cover_url()}")
    print(f"窗口名: {song.get_window_name()}")
    print(f"Scheme URL: {song.get_scheme_url()}")
