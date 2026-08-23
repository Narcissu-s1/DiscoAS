"""测试平台提供器的公共生命周期和缓存行为。"""

import base64
import importlib
import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
import requests


@pytest.mark.parametrize(
    ("module_name", "network_target"),
    [
        ("platforms.NeteaseCloudMusic.get_json", "get_session"),
        ("platforms.QQMusic.get_json", "requests.get"),
        ("platforms.KugouMusic.get_json", "get_session"),
        ("platforms.Spotify.get_json", "get_session"),
    ],
)
def test_constructor_does_not_access_network(module_name, network_target):
    module = importlib.import_module(module_name)

    with patch(f"{module_name}.{network_target}") as network:
        provider = module.PlaylistAlbumJson("123", "playlist")

    network.assert_not_called()
    assert provider.get_id() == "123"


@pytest.mark.parametrize(
    ("module_name", "network_target"),
    [
        ("platforms.NeteaseCloudMusic.get_json", "get_session"),
        ("platforms.QQMusic.get_json", "requests.get"),
        ("platforms.KugouMusic.get_json", "get_session"),
        ("platforms.Spotify.get_json", "get_session"),
    ],
)
def test_invalid_type_is_rejected_before_network(module_name, network_target):
    module = importlib.import_module(module_name)

    with (
        patch(f"{module_name}.{network_target}") as network,
        pytest.raises(ValueError, match="typename"),
    ):
        module.PlaylistAlbumJson("123", "invalid")

    network.assert_not_called()


def test_http_error_without_cache_is_raised(tmp_path):
    from platforms.NeteaseCloudMusic.get_json import PlaylistAlbumJson

    response = MagicMock()
    response.raise_for_status.side_effect = requests.HTTPError("503 Server Error")
    session = MagicMock()
    session.get.return_value = response

    with (
        patch("platforms.NeteaseCloudMusic.get_json.get_session", return_value=session),
        patch("platforms.provider_common.get_playlist_dir", return_value=str(tmp_path)),
        pytest.raises(requests.HTTPError, match="503"),
    ):
        PlaylistAlbumJson("missing", "playlist").refresh()


def test_refresh_falls_back_to_stale_cache(tmp_path):
    from platforms.NeteaseCloudMusic.get_json import PlaylistAlbumJson

    with ExitStack() as stack:
        stack.enter_context(
            patch("platforms.provider_common.get_playlist_dir", return_value=str(tmp_path))
        )
        stack.enter_context(
            patch(
                "platforms.NeteaseCloudMusic.get_json.get_playlist_dir",
                return_value=str(tmp_path),
            )
        )

        cached = PlaylistAlbumJson("cached", "playlist")
        cached.playlist_album_name = "缓存歌单"
        cached.playlist_album_json = {
            "playlist": {
                "trackIds": [{"id": 1}, {"id": 2}],
                "coverImgUrl": "https://example.com/cover.jpg",
            }
        }
        cached.save()

        cache_file = tmp_path / "cached.json"
        cache_record = json.loads(cache_file.read_text(encoding="utf-8"))
        assert cache_record["schema_version"] == 2
        assert cache_record["complete"] is True
        assert cache_record["fetched_at"]
        assert not list(tmp_path.glob("*.tmp"))

        session = MagicMock()
        session.get.side_effect = requests.Timeout("network timeout")
        stack.enter_context(
            patch("platforms.NeteaseCloudMusic.get_json.get_session", return_value=session)
        )

        provider = PlaylistAlbumJson("cached", "playlist").refresh()

    assert provider.is_stale is True
    assert provider.get_name() == "缓存歌单"
    assert provider.get_songs() == [1, 2]
    assert "network timeout" in provider.last_refresh_error


def test_atomic_write_failure_preserves_previous_cache(tmp_path):
    from platforms.NeteaseCloudMusic.get_json import PlaylistAlbumJson

    cache_file = tmp_path / "atomic.json"
    cache_file.write_text('{"old": true}', encoding="utf-8")

    provider = PlaylistAlbumJson("atomic", "playlist")
    provider.playlist_album_name = "新歌单"
    provider.playlist_album_json = {"playlist": {"trackIds": [{"id": 1}]}}

    with (
        patch("platforms.provider_common.get_playlist_dir", return_value=str(tmp_path)),
        patch(
            "platforms.NeteaseCloudMusic.get_json.get_playlist_dir",
            return_value=str(tmp_path),
        ),
        patch("platforms.provider_common.os.replace", side_effect=OSError("replace failed")),
        pytest.raises(OSError, match="replace failed"),
    ):
        provider.save()

    assert cache_file.read_text(encoding="utf-8") == '{"old": true}'
    assert not list(tmp_path.glob("*.tmp"))


def test_spotify_embed_is_parsed_on_explicit_refresh():
    from platforms.Spotify.get_json import PlaylistAlbumJson

    entity = {
        "name": "Spotify 歌单",
        "trackList": [
            {
                "uri": "spotify:track:track-1",
                "title": "歌曲一",
                "subtitle": "歌手一",
                "duration": 123,
            }
        ],
    }
    payload = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    response = MagicMock()
    response.text = (
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload, ensure_ascii=False)}"
        "</script>"
    )
    session = MagicMock()
    session.get.return_value = response

    with patch("platforms.Spotify.get_json.get_session", return_value=session):
        provider = PlaylistAlbumJson(
            "spotify-id", "playlist", access_token=""
        ).refresh()

    response.raise_for_status.assert_called_once_with()
    assert provider.get_name() == "Spotify 歌单"
    assert provider.get_songs() == ["track-1"]
    assert provider.source == "embed"
    assert provider.complete is False


def _spotify_response(payload, status_code=200, headers=None):
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    response.json.return_value = payload
    return response


def test_spotify_api_playlist_follows_all_pages():
    from platforms.Spotify.get_json import PlaylistAlbumJson

    second_url = "https://api.spotify.com/v1/playlists/playlist-id/items?offset=1"
    session = MagicMock()
    session.get.side_effect = [
        _spotify_response(
            {
                "name": "完整歌单",
                "images": [{"url": "https://example.com/cover.jpg"}],
            }
        ),
        _spotify_response(
            {
                "total": 4,
                "next": second_url,
                "items": [
                    {
                        "item": {
                            "id": "track-1",
                            "name": "歌曲一",
                            "duration_ms": 120000,
                            "artists": [{"name": "歌手一"}],
                        }
                    }
                ],
            }
        ),
        _spotify_response(
            {
                "total": 4,
                "next": None,
                "items": [
                    {
                        "track": {
                            "id": "track-2",
                            "uri": "spotify:track:track-2",
                            "name": "歌曲二",
                            "duration_ms": 130000,
                            "artists": [{"name": "歌手二"}],
                        }
                    },
                    {
                        "item": {
                            "id": "episode-1",
                            "type": "episode",
                            "name": "播客",
                        }
                    },
                    {
                        "item": {
                            "id": "local-1",
                            "type": "track",
                            "is_local": True,
                            "name": "本地歌曲",
                        }
                    },
                ],
            }
        ),
    ]

    with patch("platforms.Spotify.get_json.get_session", return_value=session):
        provider = PlaylistAlbumJson(
            "playlist-id", "playlist", access_token="secret-token"
        ).refresh()

    assert provider.get_songs() == ["track-1", "track-2"]
    assert provider.get_name() == "完整歌单"
    assert provider.complete is True
    assert provider.source == "web_api"
    assert session.get.call_args_list[2].args[0] == second_url
    assert all(
        call.kwargs["headers"]["Authorization"] == "Bearer secret-token"
        for call in session.get.call_args_list
    )


def test_spotify_api_album_follows_all_pages():
    from platforms.Spotify.get_json import PlaylistAlbumJson

    second_url = "https://api.spotify.com/v1/albums/album-id/tracks?offset=1"
    session = MagicMock()
    session.get.side_effect = [
        _spotify_response(
            {
                "name": "完整专辑",
                "images": [{"url": "https://example.com/album.jpg"}],
            }
        ),
        _spotify_response(
            {
                "total": 2,
                "next": second_url,
                "items": [
                    {
                        "id": "album-track-1",
                        "name": "第一首",
                        "artists": [{"name": "歌手"}],
                    }
                ],
            }
        ),
        _spotify_response(
            {
                "total": 2,
                "next": None,
                "items": [
                    {
                        "id": "album-track-2",
                        "name": "第二首",
                        "artists": [{"name": "歌手"}],
                    }
                ],
            }
        ),
    ]

    with patch("platforms.Spotify.get_json.get_session", return_value=session):
        provider = PlaylistAlbumJson(
            "album-id", "album", access_token="secret-token"
        ).refresh()

    assert provider.get_songs() == ["album-track-1", "album-track-2"]
    assert provider.playlist_album_json["coverArt"]["sources"][0]["url"] == (
        "https://example.com/album.jpg"
    )
    assert provider.complete is True


@pytest.mark.parametrize(
    ("status_code", "message"),
    [(401, "无效或已过期"), (403, "只能读取当前账号拥有或协作的歌单")],
)
def test_spotify_api_auth_errors_do_not_silently_use_embed(status_code, message):
    from platforms.Spotify.get_json import PlaylistAlbumJson

    session = MagicMock()
    session.get.return_value = _spotify_response({}, status_code=status_code)
    with (
        patch("platforms.Spotify.get_json.get_session", return_value=session),
        patch.object(PlaylistAlbumJson, "_load_from_cache", return_value=False),
        pytest.raises(RuntimeError, match=message),
    ):
        PlaylistAlbumJson(
            "private-playlist", "playlist", access_token="secret-token"
        ).refresh()

    assert "open.spotify.com/embed" not in str(session.get.call_args_list)


def test_spotify_api_429_retries_once_with_retry_after():
    from platforms.Spotify.get_json import PlaylistAlbumJson

    session = MagicMock()
    session.get.side_effect = [
        _spotify_response({}, status_code=429, headers={"Retry-After": "2"}),
        _spotify_response({"ok": True}),
    ]
    provider = PlaylistAlbumJson("playlist-id", "playlist", access_token="token")

    with (
        patch("platforms.Spotify.get_json.get_session", return_value=session),
        patch("platforms.Spotify.get_json.time.sleep") as sleep,
    ):
        payload = provider._api_get(
            "https://api.spotify.com/v1/playlists/playlist-id"
        )

    assert payload == {"ok": True}
    sleep.assert_called_once_with(2)
    assert session.get.call_count == 2


def test_kugou_status_success_with_null_data_is_not_success():
    from platforms.KugouMusic.get_json import PlaylistAlbumJson

    session = MagicMock()
    session.get.return_value.json.return_value = {"status": 1, "data": None}
    with (
        patch("platforms.KugouMusic.get_json.get_session", return_value=session),
        patch.object(PlaylistAlbumJson, "_load_from_cache", return_value=False),
        pytest.raises(ValueError, match="有效 data"),
    ):
        PlaylistAlbumJson("987654321", "playlist").refresh()


def test_kugou_collect_share_full_url_is_parsed():
    from platforms.KugouMusic.get_json import PlaylistAlbumJson

    share_response = MagicMock()
    share_response.url = (
        "http://wwwapi.kugou.com/share/zlist.html?share_type=collect&"
        "global_collection_id=collection_3_810346276_2_0"
    )
    share_response.text = """
        <script>
        var dataFromSmarty = [
            {
                "hash": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                "audio_name": "歌手甲 - 歌曲甲",
                "album_id": "11"
            },
            {
                "hash": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
                "author_name": "歌手乙",
                "song_name": "歌曲乙",
                "album_id": 22
            }
        ],// 当前页面歌曲信息
        playType = "collect";
        </script>
    """
    first_page_response = MagicMock()
    first_page_response.json.return_value = {
        "status": 1,
        "data": {
            "count": 3,
            "list_info": {
                "name": "完整收藏集合",
                "pic": "https://example.com/{size}.jpg",
            },
            "songs": [
                {
                    "hash": "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
                    "name": "歌手丙 - 歌曲丙",
                    "album_id": "33",
                },
                {
                    "hash": "DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD",
                    "name": "歌手丁 - 歌曲丁",
                    "album_id": "44",
                },
            ],
        },
    }
    second_page_response = MagicMock()
    second_page_response.json.return_value = {
        "status": 1,
        "data": {
            "count": 3,
            "songs": [
                {
                    "hash": "EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE",
                    "name": "歌手戊 - 歌曲戊",
                    "album_id": "55",
                }
            ],
        },
    }
    session = MagicMock()
    session.get.side_effect = [
        share_response,
        first_page_response,
        second_page_response,
    ]

    with patch("platforms.KugouMusic.get_json.get_session", return_value=session):
        provider = PlaylistAlbumJson(
            "https://t1.kugou.com/2mSD912G4V3", "playlist"
        ).refresh()

    assert provider.get_id() == "2mSD912G4V3"
    assert provider.collection_id == "collection_3_810346276_2_0"
    assert provider.source == "collection_api"
    assert provider.complete is True
    assert provider.is_stale is False
    assert provider.get_songs() == [
        {
            "hash": "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
            "album_id": "33",
            "name": "歌手丙 - 歌曲丙",
        },
        {
            "hash": "DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD",
            "album_id": "44",
            "name": "歌手丁 - 歌曲丁",
        },
        {
            "hash": "EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE",
            "album_id": "55",
            "name": "歌手戊 - 歌曲戊",
        },
    ]
    assert session.get.call_count == 3
    assert session.get.call_args_list[0].args[0] == "https://t1.kugou.com/2mSD912G4V3"
    assert session.get.call_args_list[1].kwargs["params"]["begin_idx"] == 0
    assert session.get.call_args_list[2].kwargs["params"]["begin_idx"] == 2
    with (
        patch("platforms.KugouMusic.get_json.ensure_dir"),
        patch.object(provider, "_write_cache") as write_cache,
    ):
        provider.save()
    cache_data = write_cache.call_args.args[0]
    assert cache_data["playlist_album_id"] == "2mSD912G4V3"
    assert cache_data["collection_id"] == "collection_3_810346276_2_0"
    assert cache_data["source"] == "collection_api"
    assert cache_data["complete"] is True
    assert cache_data["complete_reason"] == ""
    assert cache_data["coverUrl"] == "https://example.com/500.jpg"


def test_kugou_collect_api_failure_keeps_explicit_incomplete_snapshot():
    from platforms.KugouMusic.get_json import PlaylistAlbumJson

    share_response = MagicMock()
    share_response.url = (
        "http://wwwapi.kugou.com/share/zlist.html?share_type=collect&"
        "global_collection_id=collection_3_810346276_2_0"
    )
    share_response.text = """
        <script>
        var dataFromSmarty = [{
            "hash": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "audio_name": "歌手甲 - 歌曲甲",
            "album_id": "11"
        }];
        </script>
    """
    api_response = MagicMock()
    api_response.json.return_value = {
        "status": 0,
        "data": None,
        "error_code": 123,
    }
    session = MagicMock()
    session.get.side_effect = [share_response, api_response]

    with patch("platforms.KugouMusic.get_json.get_session", return_value=session):
        provider = PlaylistAlbumJson("2mSD912G4V3", "playlist").refresh()

    assert provider.source == "share_collect_snapshot"
    assert provider.complete is False
    assert provider.complete_reason.startswith(
        "collection_api_failed_using_share_snapshot:"
    )
    assert len(provider.get_songs()) == 1


def test_kugou_legacy_share_still_resolves_specialid():
    from platforms.KugouMusic.get_json import PlaylistAlbumJson

    share_response = MagicMock()
    share_response.url = (
        "http://web.kugou.com?action=single&share_type=special&id=7365552"
    )
    share_response.text = ""
    info_response = MagicMock()
    info_response.json.return_value = {
        "status": 1,
        "data": {"specialname": "旧版歌单"},
    }
    songs_response = MagicMock()
    songs_response.json.return_value = {
        "status": 1,
        "data": {
            "total": 1,
            "info": [
                {
                    "hash": "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
                    "filename": "歌手 - 歌曲",
                }
            ],
        },
    }
    session = MagicMock()
    session.get.side_effect = [share_response, info_response, songs_response]

    with patch("platforms.KugouMusic.get_json.get_session", return_value=session):
        provider = PlaylistAlbumJson("7hXh101FZV2", "playlist").refresh()

    assert provider.specialid == "7365552"
    assert provider.source == "api"
    assert provider.complete is True
    assert provider.get_name() == "旧版歌单"


def test_kugou_rejects_non_kugou_share_url():
    from platforms.KugouMusic.get_json import PlaylistAlbumJson

    with pytest.raises(ValueError, match="仅支持"):
        PlaylistAlbumJson("https://example.com/2mSD912G4V3", "playlist")


def test_kugou_rejects_redirect_to_external_host():
    from platforms.KugouMusic.get_json import PlaylistAlbumJson

    redirect = MagicMock()
    redirect.status_code = 302
    redirect.url = "https://t1.kugou.com/external"
    redirect.headers = {"Location": "https://example.com/private"}
    session = MagicMock()
    session.get.return_value = redirect
    with (
        patch("platforms.KugouMusic.get_json.get_session", return_value=session),
        patch.object(PlaylistAlbumJson, "_load_from_cache", return_value=False),
        pytest.raises(ValueError, match="外部域名"),
    ):
        PlaylistAlbumJson("external", "playlist").refresh()


@pytest.mark.parametrize("total_field", ["total", "count"])
def test_kugou_pagination_uses_total_and_fetches_second_page(total_field):
    from platforms.KugouMusic.get_json import PlaylistAlbumJson

    first_page = [
        {"hash": f"hash-{index}", "filename": f"歌曲{index}"}
        for index in range(500)
    ]
    session = MagicMock()
    session.get.return_value.json.side_effect = [
        {"status": 1, "data": {"specialname": "完整酷狗歌单"}},
        {"status": 1, "data": {total_field: 501, "info": first_page}},
        {
            "status": 1,
            "data": {total_field: 501, "info": [{"hash": "hash-500"}]},
        },
    ]

    with patch("platforms.KugouMusic.get_json.get_session", return_value=session):
        provider = PlaylistAlbumJson("7365552", "playlist").refresh()

    assert len(provider.get_songs()) == 501
    assert provider.complete is True
    assert session.get.call_args_list[1].kwargs["params"]["page"] == 1
    assert session.get.call_args_list[2].kwargs["params"]["page"] == 2


def test_kugou_incomplete_page_is_rejected():
    from platforms.KugouMusic.get_json import PlaylistAlbumJson

    session = MagicMock()
    session.get.return_value.json.side_effect = [
        {"status": 1, "data": {"specialname": "残缺歌单"}},
        {"status": 1, "data": {"total": 2, "info": [{"hash": "only-one"}]}},
    ]
    with (
        patch("platforms.KugouMusic.get_json.get_session", return_value=session),
        patch.object(PlaylistAlbumJson, "_load_from_cache", return_value=False),
        pytest.raises(ValueError, match="分页不完整"),
    ):
        PlaylistAlbumJson("987654322", "playlist").refresh()


def test_kugou_album_save_reuses_fetched_album_info():
    from platforms.KugouMusic.get_json import PlaylistAlbumJson

    session = MagicMock()
    session.get.return_value.json.side_effect = [
        {
            "status": 1,
            "data": {
                "albumname": "酷狗专辑",
                "sizable_cover": "https://example.com/{size}.jpg",
            },
        },
        {
            "status": 1,
            "data": {
                "info": [
                    {"hash": "hash-1", "album_id": "album-1", "filename": "歌曲一"}
                ]
            },
        },
    ]

    with patch("platforms.KugouMusic.get_json.get_session", return_value=session):
        provider = PlaylistAlbumJson("999", "album").refresh()
        with (
            patch("platforms.KugouMusic.get_json.ensure_dir"),
            patch.object(provider, "_write_cache") as write_cache,
        ):
            provider.save()

    assert session.get.call_count == 2
    assert write_cache.call_args.args[0]["coverUrl"] == "https://example.com/400.jpg"


def test_qq_album_uses_mid_from_album_response():
    from platforms.QQMusic.get_json import PlaylistAlbumJson

    response = MagicMock()
    response.json.return_value = {
        "data": {
            "name": "QQ 专辑",
            "list": [{"songid": 1, "album": {"mid": "album-mid"}}],
        }
    }

    with (
        patch("platforms.QQMusic.get_json.requests.get", return_value=response),
        patch.object(PlaylistAlbumJson, "_fetch_first_song_album_mid") as fetch_mid,
    ):
        provider = PlaylistAlbumJson("album-id", "album").refresh()

    fetch_mid.assert_not_called()
    assert provider.album_mid == "album-mid"


def test_qq_scheme_uses_supported_playsong_command():
    from platforms.QQMusic.card import SongCard

    scheme_url = SongCard(102450788).get_scheme_url()

    assert "version==1173" in scheme_url
    assert "cmd_0==playsong" in scheme_url
    assert "id_0==102450788" in scheme_url
    assert "songtype_0==0" in scheme_url
    assert "cmd_0==4002" not in scheme_url


def test_kugou_scheme_appends_to_current_queue_without_default_list():
    from platforms.KugouMusic.card import SongCard

    card = SongCard("A" * 32)
    with patch.object(
        card,
        "_find_song_info",
        return_value={"filename": "歌手 - 歌曲", "album_id": "1"},
    ):
        scheme_url = card.get_scheme_url()

    encoded_payload = scheme_url.removeprefix("kugou://play?p=")
    payload = json.loads(base64.b64decode(encoded_payload).decode("utf-8"))
    assert payload["AddPlayQueue"] == 1
    assert payload["QueueInfo"] == {
        "Play": "1",
        "PlayAll": "0",
        "Clear": "0",
        "Insert": "1",
        "Force": "1",
        "IsMV": "0",
        "Index": "0",
        "AddToDefaultList": "0",
        "climax": "0",
    }


def test_loaded_playlist_name_replaces_existing_placeholder():
    from settings.setting_gui import SettingsWindow

    platform_widget = MagicMock()
    platform_widget.currentData.return_value = "KugouMusic"
    id_widget = MagicMock()
    id_widget.text.return_value = "2mYmBabG4V3"
    type_widget = MagicMock()
    type_widget.currentData.return_value = "playlist"
    name_widget = MagicMock()
    table = MagicMock()
    widgets = {
        (0, 0): platform_widget,
        (0, 1): id_widget,
        (0, 2): type_widget,
        (0, 3): name_widget,
    }
    table.cellWidget.side_effect = lambda row, column: widgets[(row, column)]
    window = MagicMock()
    window.table_pl = table

    provider = MagicMock()
    provider.refresh.return_value = provider
    provider.is_stale = False
    provider.get_id.return_value = "2mYmBabG4V3"
    provider.get_name.return_value = "Νάρκισσος喜欢的音乐"
    provider_class = MagicMock(return_value=provider)

    with (
        patch.dict(
            "settings.setting_gui.PLATFORM_JSON_MAP",
            {"KugouMusic": provider_class},
        ),
        patch("settings.setting_gui.QMessageBox.information"),
    ):
        SettingsWindow.load_playlist_data(window, 0)

    provider.save.assert_called_once_with()
    name_widget.setText.assert_called_once_with("Νάρκισσος喜欢的音乐")
