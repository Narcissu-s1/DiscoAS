"""
tests/test_platform_get_json.py
测试各平台 get_json 模块的 JSON 解析逻辑（使用 mock 避免真实 HTTP 请求）
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# NeteaseCloudMusic
# ---------------------------------------------------------------------------


class TestNeteaseCloudMusicPlaylist(unittest.TestCase):
    """测试网易云音乐歌单解析"""

    @patch("platforms.NeteaseCloudMusic.get_json.get_session")
    def test_get_name(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.get.return_value.json.return_value = {
            "playlist": {"name": "测试歌单", "trackIds": [{"id": 123}, {"id": 456}]}
        }

        from platforms.NeteaseCloudMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("999", "playlist").refresh()
        self.assertEqual(obj.get_name(), "测试歌单")

    @patch("platforms.NeteaseCloudMusic.get_json.get_session")
    def test_get_songs(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.get.return_value.json.return_value = {
            "playlist": {"name": "测试歌单", "trackIds": [{"id": 123}, {"id": 456}]}
        }

        from platforms.NeteaseCloudMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("999", "playlist").refresh()
        self.assertEqual(obj.get_songs(), [123, 456])

    @patch("platforms.NeteaseCloudMusic.get_json.get_session")
    def test_get_id(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.get.return_value.json.return_value = {
            "playlist": {"name": "测试歌单", "trackIds": []}
        }

        from platforms.NeteaseCloudMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("888", "playlist").refresh()
        self.assertEqual(obj.get_id(), "888")

    @patch("platforms.NeteaseCloudMusic.get_json.get_session")
    def test_typename_invalid(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        from platforms.NeteaseCloudMusic.get_json import PlaylistAlbumJson

        with self.assertRaises(ValueError):
            PlaylistAlbumJson("999", "invalid_type")


class TestNeteaseCloudMusicAlbum(unittest.TestCase):
    """测试网易云音乐专辑解析"""

    @patch("platforms.NeteaseCloudMusic.get_json.get_session")
    def test_album_get_name(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.get.return_value.json.return_value = {
            "album": {"name": "测试专辑", "songs": [{"id": 789}, {"id": 100}]}
        }

        from platforms.NeteaseCloudMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("555", "album").refresh()
        self.assertEqual(obj.get_name(), "测试专辑")

    @patch("platforms.NeteaseCloudMusic.get_json.get_session")
    def test_album_get_songs(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.get.return_value.json.return_value = {
            "album": {"name": "测试专辑", "songs": [{"id": 789}, {"id": 100}]}
        }

        from platforms.NeteaseCloudMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("555", "album").refresh()
        self.assertEqual(obj.get_songs(), [789, 100])


# ---------------------------------------------------------------------------
# QQMusic
# ---------------------------------------------------------------------------


class TestQQMusicPlaylist(unittest.TestCase):
    """测试 QQ 音乐歌单解析"""

    @patch("platforms.QQMusic.get_json.requests.get")
    def test_get_name(self, mock_get):
        mock_get.return_value.json.return_value = {
            "cdlist": [{"dissname": "QQ歌单", "songlist": [{"songid": 111}, {"songid": 222}]}]
        }

        from platforms.QQMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("333", "playlist").refresh()
        self.assertEqual(obj.get_name(), "QQ歌单")

    @patch("platforms.QQMusic.get_json.requests.get")
    def test_get_songs(self, mock_get):
        mock_get.return_value.json.return_value = {
            "cdlist": [{"dissname": "QQ歌单", "songlist": [{"songid": 111}, {"songid": 222}]}]
        }

        from platforms.QQMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("333", "playlist").refresh()
        self.assertEqual(obj.get_songs(), [111, 222])

    @patch("platforms.QQMusic.get_json.requests.get")
    def test_get_id(self, mock_get):
        mock_get.return_value.json.return_value = {
            "cdlist": [{"dissname": "QQ歌单", "songlist": []}]
        }

        from platforms.QQMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("444", "playlist").refresh()
        self.assertEqual(obj.get_id(), "444")

    @patch("platforms.QQMusic.get_json.requests.get")
    def test_typename_invalid(self, mock_get):
        from platforms.QQMusic.get_json import PlaylistAlbumJson

        with self.assertRaises(ValueError):
            PlaylistAlbumJson("999", "invalid_type")


class TestQQMusicAlbum(unittest.TestCase):
    """测试 QQ 音乐专辑解析"""

    @patch("platforms.QQMusic.get_json.requests.get")
    def test_album_get_name(self, mock_get):
        mock_get.return_value.json.return_value = {
            "data": {"name": "QQ专辑", "list": [{"songid": 333}, {"songid": 444}]}
        }

        from platforms.QQMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("777", "album").refresh()
        self.assertEqual(obj.get_name(), "QQ专辑")

    @patch("platforms.QQMusic.get_json.requests.get")
    def test_album_get_songs(self, mock_get):
        mock_get.return_value.json.return_value = {
            "data": {"name": "QQ专辑", "list": [{"songid": 333}, {"songid": 444}]}
        }

        from platforms.QQMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("777", "album").refresh()
        self.assertEqual(obj.get_songs(), [333, 444])


# ---------------------------------------------------------------------------
# KugouMusic
# ---------------------------------------------------------------------------


class TestKugouMusicPlaylist(unittest.TestCase):
    """测试酷狗音乐歌单解析（使用纯数字 ID 跳过分享码解析）"""

    @patch("platforms.KugouMusic.get_json.get_session")
    def test_get_name(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.get.return_value.json.return_value = {
            "status": 1,
            "data": {
                "info": [
                    {"hash": "abc123", "album_id": "a1", "filename": "歌曲1.mp3"},
                    {"hash": "def456", "album_id": "a2", "filename": "歌曲2.mp3"},
                ]
            },
        }

        from platforms.KugouMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("12345", "playlist").refresh()
        self.assertEqual(obj.get_name(), "12345")

    @patch("platforms.KugouMusic.get_json.get_session")
    def test_get_songs(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.get.return_value.json.return_value = {
            "status": 1,
            "data": {
                "info": [
                    {"hash": "abc123", "album_id": "a1", "filename": "歌曲1.mp3"},
                    {"hash": "def456", "album_id": "a2", "filename": "歌曲2.mp3"},
                ]
            },
        }

        from platforms.KugouMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("12345", "playlist").refresh()
        songs = obj.get_songs()
        self.assertIsInstance(songs, list)
        self.assertEqual(len(songs), 2)
        self.assertEqual(songs[0]["hash"], "abc123")
        self.assertEqual(songs[0]["album_id"], "a1")
        self.assertEqual(songs[0]["name"], "歌曲1.mp3")

    @patch("platforms.KugouMusic.get_json.get_session")
    def test_get_id(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.get.return_value.json.return_value = {
            "status": 1,
            "data": {"info": []},
        }

        from platforms.KugouMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("54321", "playlist").refresh()
        self.assertEqual(obj.get_id(), "54321")

    @patch("platforms.KugouMusic.get_json.get_session")
    def test_typename_invalid(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        from platforms.KugouMusic.get_json import PlaylistAlbumJson

        with self.assertRaises(ValueError):
            PlaylistAlbumJson("12345", "invalid_type")


class TestKugouMusicAlbum(unittest.TestCase):
    """测试酷狗音乐专辑解析（使用纯数字 ID 跳过分享码解析）

    专辑会发两次 HTTP 请求：info（获取专辑名）和 songs（获取歌曲列表）。
    需要 mock 两次 session.get() 调用。
    """

    @patch("platforms.KugouMusic.get_json.get_session")
    def test_album_get_name(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        # 第一次调用：album info → 设置专辑名
        # 第二次调用：album songs → 获取歌曲（此时 playlist_album_name 已被 info 设置）
        mock_session.get.return_value.json.side_effect = [
            {"status": 1, "data": {"albumname": "酷狗专辑", "info": []}},
            {"status": 1, "data": {"info": [{"hash": "h1", "album_id": "al1", "filename": "专辑歌曲1.mp3"}]}},
        ]

        from platforms.KugouMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("99999", "album").refresh()
        self.assertEqual(obj.get_name(), "酷狗专辑")

    @patch("platforms.KugouMusic.get_json.get_session")
    def test_album_get_songs(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        mock_session.get.return_value.json.side_effect = [
            {"status": 1, "data": {"albumname": "酷狗专辑", "info": []}},
            {
                "status": 1,
                "data": {
                    "info": [
                        {"hash": "h1", "album_id": "al1", "filename": "专辑歌曲1.mp3"},
                    ]
                },
            },
        ]

        from platforms.KugouMusic.get_json import PlaylistAlbumJson

        obj = PlaylistAlbumJson("99999", "album").refresh()
        songs = obj.get_songs()
        self.assertIsInstance(songs, list)
        self.assertEqual(songs[0]["hash"], "h1")
        self.assertEqual(songs[0]["name"], "专辑歌曲1.mp3")


# ---------------------------------------------------------------------------
# 平台间差异验证
# ---------------------------------------------------------------------------


class TestPlatformDifferences(unittest.TestCase):
    """验证各平台返回类型差异（Kugou 返回 dict，其他返回 int）"""

    @patch("platforms.NeteaseCloudMusic.get_json.get_session")
    @patch("platforms.KugouMusic.get_json.get_session")
    @patch("platforms.QQMusic.get_json.requests.get")
    def test_kugou_returns_dict(self, mock_qq, mock_kugou, mock_netease):
        # Netease: patch get_session
        mock_netease_sess = MagicMock()
        mock_netease.return_value = mock_netease_sess
        mock_netease_sess.get.return_value.json.return_value = {
            "playlist": {"name": "n", "trackIds": [{"id": 1}]}
        }

        # Kugou: patch get_session（playlist 只发一次 HTTP）
        mock_kugou_sess = MagicMock()
        mock_kugou.return_value = mock_kugou_sess
        mock_kugou_sess.get.return_value.json.return_value = {
            "status": 1,
            "data": {"info": [{"hash": "h", "album_id": "a", "filename": "n"}]},
        }

        # QQMusic: patch requests.get
        mock_qq.return_value.json.return_value = {
            "cdlist": [{"dissname": "q", "songlist": [{"songid": 1}]}]
        }

        from platforms.KugouMusic.get_json import PlaylistAlbumJson as KugouJson
        from platforms.NeteaseCloudMusic.get_json import (
            PlaylistAlbumJson as NeteaseJson,
        )
        from platforms.QQMusic.get_json import PlaylistAlbumJson as QQJson

        netease_songs = NeteaseJson("1", "playlist").refresh().get_songs()
        kugou_songs = KugouJson("1", "playlist").refresh().get_songs()
        qq_songs = QQJson("1", "playlist").refresh().get_songs()

        # Netease 和 QQ 返回 list[int]
        self.assertIsInstance(netease_songs[0], int)
        self.assertIsInstance(qq_songs[0], int)

        # Kugou 返回 list[dict]
        self.assertIsInstance(kugou_songs[0], dict)
        self.assertIn("hash", kugou_songs[0])


if __name__ == "__main__":
    unittest.main()
