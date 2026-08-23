"""
QQ音乐歌曲卡片模块 - 使用签名算法

基于 qqmusic-api-python 库的签名算法实现
"""


# 延迟导入签名模块
def _get_make_api_request():
    import sys

    # 清除已缓存的qq_sign模块
    mods_to_remove = [k for k in sys.modules if 'qq_sign' in k]
    for mod in mods_to_remove:
        del sys.modules[mod]

    # 重新导入
    import platforms.QQMusic.qq_sign as qq_sign_module
    return qq_sign_module.make_api_request


class SongCard:
    """QQ音乐歌曲卡片类"""

    # 默认神秘歌曲封面
    DEFAULT_MYSTERY_PIC = "https://y.qq.com/music/photo_new/T002R300x300M000004RT1Bi1Ee6r5_1.jpg"

    def __init__(
        self,
        song_id: int,
        mystery_mode: bool = False,
        mystery_pic_url: str | None = None
    ):
        self.song_id = song_id
        self.mystery_mode = mystery_mode
        self.mystery_pic_url = mystery_pic_url or self.DEFAULT_MYSTERY_PIC

        # 歌曲详情数据
        self.song_detail_json: dict | None = None
        self.song_name: str | None = None
        self.song_artists: list[dict] = []
        self.song_artist_names: list[str] = []
        self.window_name: str | None = None
        self._real_window_name: str | None = ""  # 用于播放器窗口匹配，初始为空字符串防止未初始化
        self.album_mid: str | None = None
        self.album_pic_url: str | None = None
        self.have_loaded: bool = False

    def load_song_detail(self) -> None:
        """加载歌曲详情，失败则使用默认值"""
        if self.have_loaded:
            return

        try:
            params = {
                "types": [0],
                "ids": [self.song_id],
                "modify_stamp": [0],
                "ctx": 0,
                "client": 1,
            }

            import platforms.QQMusic.qq_sign as qs
            api_result = qs.make_api_request("music.trackInfo.UniformRuleCtrl", "CgiGetTrackInfo", params)

            tracks = []
            if isinstance(api_result, dict):
                module_result = api_result.get("music.trackInfo.UniformRuleCtrl", {})
                if isinstance(module_result, dict):
                    data = module_result.get("data", {})
                    if isinstance(data, dict):
                        tracks = data.get("tracks", [])

            if tracks and len(tracks) > 0:
                song_info = tracks[0]

                self.song_detail_json = song_info
                self.song_name = song_info.get("name", "???")
                self.song_artists = song_info.get("singer", [])
                self.song_artist_names = [artist.get("name", "???") for artist in self.song_artists]
                album = song_info.get("album", {})
                self.album_mid = album.get("mid", "")
                if self.album_mid:
                    self.album_pic_url = f"https://y.qq.com/music/photo_new/T002R300x300M000{self.album_mid}_1.jpg"
                else:
                    self.album_pic_url = self.mystery_pic_url
            else:
                self._set_error_defaults()
                return

        except Exception as e:
            print(f"歌曲详情加载失败: {e}")
            self._set_default_from_id()

        # 神秘模式下覆盖为假数据用于显示，但真实数据已保存在上述属性中
        if self.mystery_mode:
            self.song_name = "???"
            self.song_artist_names = ["???"]
            self.album_pic_url = self.mystery_pic_url

        # 始终构建真实窗口名（用于播放器窗口匹配，不受 mystery_mode 影响）
        self._real_window_name = self.song_name + " - " + "/".join(self.song_artist_names)
        # window_name 用于 UI 显示（mystery_mode 下为假数据）
        self.window_name = self._real_window_name
        self.have_loaded = True

    def _set_default_from_id(self) -> None:
        """根据歌曲ID设置默认值"""
        self.song_name = f"歌曲{self.song_id}"
        self.song_artist_names = ["???"]
        self.window_name = "QQ音乐 听我想听"
        self._real_window_name = self.window_name
        self.album_pic_url = self.mystery_pic_url
        self.have_loaded = True

    def _set_error_defaults(self) -> None:
        """设置错误默认值为未知"""
        self.song_name = "未知"
        self.song_artist_names = ["???"]
        self.window_name = "QQ音乐 听我想听"
        self._real_window_name = self.window_name
        self.album_pic_url = self.mystery_pic_url
        self.have_loaded = False

    def get_id(self) -> int:
        return self.song_id

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
        return self.album_pic_url or self.mystery_pic_url

    def get_scheme_url(self) -> str:
        """生成QQ音乐scheme URL用于唤起播放"""
        return (
            "tencent://QQMusic/?version==1173&&cmd_count==1"
            f"&&cmd_0==playsong&&id_0=={self.song_id}&&songtype_0==0"
        )

    def get_debug_info(self) -> str:
        """返回歌曲真实信息，用于后台调试输出"""
        if self.song_detail_json:
            real_name = self.song_detail_json.get("name", "???")
            real_artists = [a.get("name", "???") for a in self.song_detail_json.get("singer", [])]
            return f"{real_name} - {'/'.join(real_artists)}"
        return self.get_name() + " - " + "/".join(self.get_artist_names())


# 测试代码
if __name__ == '__main__':

    # song = SongCard(284218927)
    song = SongCard(127570997)
    song.load_song_detail()

    print(f"歌曲ID: {song.get_id()}")
    print(f"歌曲名: {song.get_name()}")
    print(f"艺术家: {song.get_artist_names()}")
    print(f"窗口名: {song.get_window_name()}")
    print(f"专辑封面: {song.get_album_pic_url()}")
    print(f"Scheme URL: {song.get_scheme_url()}")
