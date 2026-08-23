"""
酷狗音乐 API 模块

使用 requests.Session 复用连接，提升响应速度
"""

import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import parse_qs, quote, urljoin, urlparse

import requests

from platforms.provider_common import CollectionProvider, response_json

# 添加 settings 目录到路径，导入统一的路径管理模块
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'settings'))
from settings.user_data_path import ensure_dir, get_album_dir, get_playlist_dir

# 酷狗音乐 API 配置
KUGOU_BASE_URL = "http://mobilecdn.kugou.com"
KUGOU_COLLECTION_URL = (
    "https://gateway.kugou.com/pubsongs/v2/get_other_list_file_nofilt"
)
KUGOU_USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
KUGOU_SHARE_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
KUGOU_COLLECTION_USER_AGENT = "Android15-1070-11083-46-0-DiscoveryDRADProtocol-wifi"
KUGOU_COLLECTION_SIGNATURE_SALT = "OIlwieks28dk2k092lksi2UIkp"
KUGOU_COLLECTION_MID = hashlib.md5(b"DiscoAS-KugouMusic").hexdigest()
KUGOU_COLLECTION_PAGE_SIZE = 300
KUGOU_PAGE_SIZE = 500
KUGOU_MAX_PAGES = 1000
KUGOU_MAX_SHARED_SONGS = 10000
KUGOU_MAX_SHARE_HTML_BYTES = 5 * 1024 * 1024
KUGOU_MAX_SHARE_REDIRECTS = 5
KUGOU_SHARE_HOST_PATTERN = re.compile(r"^t\d*\.kugou\.com$", re.IGNORECASE)
KUGOU_HASH_PATTERN = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)

# 创建全局 Session 用于连接复用
_session: requests.Session | None = None


def get_session() -> requests.Session:
    """获取全局 Session，复用 TCP 连接"""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": KUGOU_USER_AGENT,
        })
    return _session


def _require_data(payload: dict, context: str) -> dict:
    """校验酷狗业务状态，并返回非空的数据对象。"""
    if payload.get("status") != 1:
        raise ValueError(f"{context}返回异常: {payload}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"{context}未返回有效 data")
    return data


def _page_songs(data: dict, context: str) -> list[dict]:
    songs = data.get("info")
    if not isinstance(songs, list):
        raise ValueError(f"{context}的 data.info 不是歌曲列表")
    if not all(isinstance(song, dict) for song in songs):
        raise ValueError(f"{context}包含无效歌曲记录")
    return songs


def _expected_total(data: dict) -> int | None:
    for field in ("total", "total_count", "count"):
        value = data.get(field)
        if isinstance(value, int) and value >= 0:
            return value
    return None


def _normalize_share_input(value: str) -> str:
    """将酷狗完整分享链接转换为可安全用作缓存文件名的短码。"""
    normalized = value.strip()
    if not normalized.lower().startswith(("http://", "https://")):
        return normalized

    parsed = urlparse(normalized)
    if not parsed.hostname or not KUGOU_SHARE_HOST_PATTERN.fullmatch(parsed.hostname):
        raise ValueError("仅支持 t.kugou.com 或 t数字.kugou.com 的分享链接")

    query_id = parse_qs(parsed.query).get("id", [""])[0].strip()
    path_code = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if path_code.endswith(".html"):
        path_code = path_code[:-5]
    share_code = query_id or path_code
    if not share_code or not re.fullmatch(r"[A-Za-z0-9]+", share_code):
        raise ValueError("酷狗分享链接中没有有效短码")
    return share_code


def _is_kugou_host(hostname: str | None) -> bool:
    return bool(hostname and (hostname == "kugou.com" or hostname.endswith(".kugou.com")))


def _fetch_share_page(session: requests.Session, share_url: str):
    """逐跳校验酷狗重定向，避免跟随到外部域名。"""
    current_url = share_url
    headers = {"User-Agent": KUGOU_SHARE_USER_AGENT}
    for _ in range(KUGOU_MAX_SHARE_REDIRECTS + 1):
        if not _is_kugou_host(urlparse(current_url).hostname):
            raise ValueError("酷狗分享链接重定向到了外部域名")
        response = session.get(
            current_url,
            headers=headers,
            allow_redirects=False,
            timeout=10,
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            response.raise_for_status()
            return response
        location = response.headers.get("Location")
        if not location:
            raise ValueError("酷狗分享链接重定向缺少 Location")
        current_url = urljoin(response.url, location)
    raise ValueError("酷狗分享链接重定向次数超过安全上限")


def _parse_collect_songs(html: str) -> list[dict]:
    """读取新版 collect 分享页的 dataFromSmarty 歌曲数组。"""
    if len(html.encode("utf-8")) > KUGOU_MAX_SHARE_HTML_BYTES:
        raise ValueError("酷狗收藏分享页超过安全大小")
    marker = re.search(r"var\s+dataFromSmarty\s*=\s*", html)
    if not marker:
        raise ValueError("酷狗收藏分享页缺少 dataFromSmarty")
    try:
        raw_songs, _ = json.JSONDecoder().raw_decode(html[marker.end():])
    except json.JSONDecodeError as exc:
        raise ValueError("酷狗收藏分享页的歌曲数据无法解析") from exc
    if not isinstance(raw_songs, list) or not raw_songs:
        raise ValueError("酷狗收藏分享页没有歌曲")
    if len(raw_songs) > KUGOU_MAX_SHARED_SONGS:
        raise ValueError("酷狗收藏分享页歌曲数量超过安全上限")

    songs: list[dict] = []
    for raw_song in raw_songs:
        if not isinstance(raw_song, dict):
            raise ValueError("酷狗收藏分享页包含无效歌曲记录")
        song_hash = raw_song.get("hash")
        if not isinstance(song_hash, str) or not KUGOU_HASH_PATTERN.fullmatch(song_hash):
            raise ValueError("酷狗收藏分享页包含无效歌曲 hash")
        album_id = str(raw_song.get("album_id", "")).strip()
        if album_id and not album_id.isdigit():
            raise ValueError("酷狗收藏分享页包含无效 album_id")
        duration = raw_song.get("timelength")
        if duration is not None and (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or duration < 0
        ):
            raise ValueError("酷狗收藏分享页包含无效 timelength")
        filename = raw_song.get("audio_name")
        if not isinstance(filename, str) or not filename.strip():
            author = str(raw_song.get("author_name", "")).strip()
            song_name = str(raw_song.get("song_name", "")).strip()
            filename = f"{author} - {song_name}" if author else song_name
        songs.append(
            {
                "hash": song_hash,
                "album_id": album_id,
                "filename": filename,
            }
        )
    return songs


def _collection_signature(params: dict) -> str:
    raw = KUGOU_COLLECTION_SIGNATURE_SALT
    raw += "".join(f"{key}={params[key]}" for key in sorted(params))
    raw += KUGOU_COLLECTION_SIGNATURE_SALT
    return hashlib.md5(raw.encode()).hexdigest()


def _normalize_collection_song(song: dict) -> dict:
    song_hash = song.get("hash", "")
    if not isinstance(song_hash, str):
        raise ValueError("酷狗收藏集合包含无效歌曲 hash")
    if song_hash and not KUGOU_HASH_PATTERN.fullmatch(song_hash):
        raise ValueError("酷狗收藏集合包含无效歌曲 hash")

    album_id = str(song.get("album_id", "")).strip()
    filename = song.get("name") or song.get("filename") or song.get("remark") or ""
    if not isinstance(filename, str):
        filename = str(filename)
    return {
        "hash": song_hash,
        "album_id": album_id,
        "filename": filename,
    }


def _fetch_collection(
    session: requests.Session, collection_id: str
) -> tuple[list[dict], dict]:
    """使用新版全局集合接口分页拉取全部歌曲。"""
    if not collection_id:
        raise ValueError("酷狗收藏分享缺少 global_collection_id")

    all_songs: list[dict] = []
    expected_total: int | None = None
    list_info: dict = {}
    begin_idx = 0

    for _ in range(KUGOU_MAX_PAGES):
        clienttime = int(time.time())
        params = {
            "dfid": "-",
            "mid": KUGOU_COLLECTION_MID,
            "uuid": "-",
            "appid": 1005,
            "clientver": 20489,
            "clienttime": clienttime,
            "area_code": 1,
            "begin_idx": begin_idx,
            "plat": 1,
            "type": 1,
            "mode": 1,
            "personal_switch": 1,
            "extend_fields": "abtags,hot_cmt,popularization",
            "pagesize": KUGOU_COLLECTION_PAGE_SIZE,
            "global_collection_id": collection_id,
        }
        params["signature"] = _collection_signature(params)
        headers = {
            "User-Agent": KUGOU_COLLECTION_USER_AGENT,
            "dfid": "-",
            "clienttime": str(clienttime),
            "mid": KUGOU_COLLECTION_MID,
            "kg-rc": "1",
            "kg-thash": "5d816a0",
            "kg-rec": "1",
            "kg-rf": "B9EDA08A64250DEFFBCADDEE00F8F25F",
        }
        response = session.get(
            KUGOU_COLLECTION_URL,
            params=params,
            headers=headers,
            timeout=10,
        )
        data = _require_data(response_json(response), "酷狗收藏集合分页接口")
        songs = data.get("songs")
        if not isinstance(songs, list) or not all(
            isinstance(song, dict) for song in songs
        ):
            raise ValueError("酷狗收藏集合分页接口未返回有效歌曲列表")

        total = data.get("count")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ValueError("酷狗收藏集合分页接口未返回有效总数")
        if expected_total is not None and total != expected_total:
            raise ValueError("酷狗收藏集合分页接口返回的总数前后不一致")
        expected_total = total

        if not list_info and isinstance(data.get("list_info"), dict):
            list_info = data["list_info"]
        all_songs.extend(_normalize_collection_song(song) for song in songs)
        if len(all_songs) >= expected_total:
            break
        if not songs:
            break
        begin_idx += len(songs)
    else:
        raise ValueError("酷狗收藏集合分页超过安全上限")

    if expected_total is None or len(all_songs) != expected_total:
        raise ValueError(
            f"酷狗收藏集合分页不完整: 预期 {expected_total} 首，实际 {len(all_songs)} 首"
        )
    return all_songs, list_info


class PlaylistAlbumJson(CollectionProvider):
    """酷狗音乐歌单/专辑 JSON 获取类"""

    platform_name = "KugouMusic"

    def __init__(self, playlist_album_id: str, typename: str):
        super().__init__(_normalize_share_input(playlist_album_id), typename)
        self.specialid: str = ""  # 解析后的 specialid
        self.collection_id: str = ""
        self.source: str = ""
        self.complete_reason: str = ""
        self.playlist_album_name: str = ""
        self.playlist_album_json: dict | list = {}
        self.playlist_info: dict = {}  # 歌单元数据（包含名称、封面等）
        self.album_info: dict = {}
        self.complete = False

    def _fetch_data(self) -> None:
        """获取歌单/专辑数据"""
        session = get_session()
        self.specialid = ""
        self.collection_id = ""
        self.source = ""
        self.complete_reason = ""
        self.playlist_album_name = ""
        self.playlist_album_json = {}
        self.playlist_info = {}
        self.album_info = {}
        self.complete = False

        if self.typename == "playlist":
            # 判断是分享码还是 specialid（纯数字为 specialid）
            if self.playlist_album_id.isdigit():
                specialid = self.playlist_album_id
            else:
                shared = self._resolve_playlist_share(self.playlist_album_id)
                if shared["kind"] == "collect":
                    self.collection_id = str(shared["collection_id"])
                    try:
                        songs, list_info = _fetch_collection(session, self.collection_id)
                    except Exception as exc:
                        self.source = "share_collect_snapshot"
                        self.playlist_album_name = (
                            f"酷狗收藏集合 {self.playlist_album_id}"
                        )
                        self.playlist_album_json = {
                            "data": {"info": shared["songs"]}
                        }
                        self.complete = False
                        self.complete_reason = (
                            f"collection_api_failed_using_share_snapshot: {exc}"
                        )
                    else:
                        self.source = "collection_api"
                        self.playlist_album_name = str(
                            list_info.get("name")
                            or f"酷狗收藏集合 {self.playlist_album_id}"
                        )
                        self.playlist_info = {
                            "imgurl": str(list_info.get("pic") or "")
                        }
                        self.playlist_album_json = {"data": {"info": songs}}
                        self.complete = True
                    print(f"已获取 {self.typename}: {self.playlist_album_name}")
                    return
                specialid = str(shared["specialid"])

            # 获取歌单本身的信息（名称、封面等）
            special_info_url = f"{KUGOU_BASE_URL}/api/v3/special/info"
            info_params = {
                "specialid": specialid,
                "plat": 2,
                "version": 8400,
            }
            info_response = session.get(special_info_url, params=info_params, timeout=10)
            info_data = response_json(info_response)
            self.playlist_info = _require_data(info_data, "酷狗歌单信息接口")
            self.playlist_album_name = self.playlist_info.get("specialname", specialid)

            # 自动翻页拉取歌单
            all_songs = []
            page = 1
            expected_total: int | None = None

            while page <= KUGOU_MAX_PAGES:
                url = f"{KUGOU_BASE_URL}/api/v3/special/song"
                params = {
                    "specialid": specialid,
                    "page": page,
                    "plat": 2,
                    "pagesize": KUGOU_PAGE_SIZE,
                    "version": 8400,
                }
                response = session.get(url, params=params, timeout=10)
                page_data = _require_data(
                    response_json(response), "酷狗歌单分页接口"
                )
                songs_list = _page_songs(page_data, "酷狗歌单分页接口")
                total = _expected_total(page_data)
                if total is not None:
                    if expected_total is not None and total != expected_total:
                        raise ValueError("酷狗歌单分页接口返回的总数前后不一致")
                    expected_total = total

                all_songs.extend(songs_list)
                if expected_total is not None and len(all_songs) >= expected_total:
                    break
                if len(songs_list) < KUGOU_PAGE_SIZE:
                    break
                page += 1
            else:
                raise ValueError("酷狗歌单分页超过安全上限")

            if expected_total is not None and len(all_songs) != expected_total:
                raise ValueError(
                    f"酷狗歌单分页不完整: 预期 {expected_total} 首，实际 {len(all_songs)} 首"
                )

            # 保存到 playlist_album_json，结构与 test.py 一致
            self.playlist_album_json = {
                "data": {
                    "info": all_songs
                }
            }
            # 保存解析后的 specialid
            self.specialid = specialid
            self.source = "api"

        elif self.typename == "album":
            # 判断是分享码还是 album_id（纯数字为 album_id）
            if self.playlist_album_id.isdigit():
                album_id = self.playlist_album_id
            else:
                album_id = self._resolve_album_share_code(self.playlist_album_id)
                if not album_id:
                    raise ValueError("无法解析专辑分享码")

            # 获取专辑封面和名称
            album_info_url = f"{KUGOU_BASE_URL}/api/v3/album/info"
            album_info_params = {
                "albumid": album_id,
                "plat": 2,
                "version": 8400,
            }
            try:
                info_response = session.get(album_info_url, params=album_info_params, timeout=10)
                info_data = response_json(info_response)

                self.album_info = _require_data(info_data, "酷狗专辑信息接口")
                self.playlist_album_name = self.album_info.get('albumname', '未知专辑')
            except Exception as e:
                print(f"获取专辑详情失败: {e}")
                raise

            # 翻页获取专辑内的所有歌曲
            all_songs = []
            page = 1
            expected_total = None

            while page <= KUGOU_MAX_PAGES:
                album_songs_url = f"{KUGOU_BASE_URL}/api/v3/album/song"
                songs_params = {
                    "albumid": album_id,
                    "page": page,
                    "plat": 2,
                    "pagesize": KUGOU_PAGE_SIZE,
                    "version": 8400,
                }
                try:
                    songs_response = session.get(album_songs_url, params=songs_params, timeout=10)
                    songs_data = response_json(songs_response)

                    page_data = _require_data(songs_data, "酷狗专辑分页接口")
                    songs_list = _page_songs(page_data, "酷狗专辑分页接口")
                    total = _expected_total(page_data)
                    if total is not None:
                        if expected_total is not None and total != expected_total:
                            raise ValueError("酷狗专辑分页接口返回的总数前后不一致")
                        expected_total = total
                    all_songs.extend(songs_list)

                    if expected_total is not None and len(all_songs) >= expected_total:
                        break
                    if len(songs_list) < KUGOU_PAGE_SIZE:
                        break
                    page += 1
                except Exception as e:
                    print(f"翻页拉取专辑歌曲异常: {e}")
                    raise
            else:
                raise ValueError("酷狗专辑分页超过安全上限")

            if expected_total is not None and len(all_songs) != expected_total:
                raise ValueError(
                    f"酷狗专辑分页不完整: 预期 {expected_total} 首，实际 {len(all_songs)} 首"
                )

            # 保存到 playlist_album_json，结构与 playlist 分支对齐
            self.playlist_album_json = {
                "data": {
                    "info": all_songs
                }
            }
            self.specialid = album_id
            self.source = "api"
        else:
            raise ValueError("typename must be 'playlist' or 'album'")

        self.complete = True
        print(f"已获取 {self.typename}: {self.playlist_album_name}")

    def _load_from_cache(self) -> bool:
        cache_data = self._read_cache()
        if not cache_data:
            return False

        self.specialid = str(cache_data.get("specialid", ""))
        self.collection_id = str(cache_data.get("collection_id", ""))
        self.source = str(cache_data.get("source", "cache"))
        self.complete_reason = str(cache_data.get("complete_reason", ""))
        self.playlist_album_name = cache_data.get("playlist_album_name", "")
        songs_info = cache_data.get("songs_info", [])
        if not songs_info:
            songs_info = [{"hash": song_id} for song_id in cache_data.get("song_ids", [])]
        self.playlist_album_json = {"data": {"info": songs_info}}
        cover_url = cache_data.get("coverUrl", "")
        if self.typename == "playlist":
            self.playlist_info = {"imgurl": cover_url}
        else:
            self.album_info = {"sizable_cover": cover_url}
        self.complete = bool(cache_data.get("complete", True))
        return True

    def _resolve_playlist_share(self, share_code: str) -> dict:
        """解析旧 special 分享和新版 collect 集合分享。"""
        share_url = f"https://t1.kugou.com/{quote(share_code, safe='')}"
        try:
            session = get_session()
            response = _fetch_share_page(session, share_url)

            parsed_url = urlparse(response.url)
            query = parse_qs(parsed_url.query)
            share_type = query.get("share_type", [""])[0]
            query_id = query.get("id", [""])[0]
            if share_type == "special" and query_id.isdigit():
                return {"kind": "special", "specialid": query_id}

            # 从 URL 中提取 specialid
            url_match = re.search(r'/(?:plist/list|songlist)/(\d+)', response.url)
            if url_match:
                return {"kind": "special", "specialid": url_match.group(1)}

            # 从 HTML 中提取
            html_match = re.search(r'["\']?(?:special[_]?id|global_specialid)["\']?\s*[:=]\s*["\']?(\d+)["\']?', response.text, re.IGNORECASE)
            if html_match:
                return {"kind": "special", "specialid": html_match.group(1)}

            if share_type == "collect" or "dataFromSmarty" in response.text:
                collection_id = query.get("global_collection_id", [""])[0]
                return {
                    "kind": "collect",
                    "collection_id": collection_id,
                    "songs": _parse_collect_songs(response.text),
                }

            raise ValueError("分享页既不包含 specialid，也不包含收藏歌曲数据")
        except Exception as e:
            raise ValueError(f"无法解析酷狗歌单分享: {e}") from e

    def _resolve_album_share_code(self, share_code: str) -> str | None:
        """解析专辑分享码获取 album_id"""
        import re

        share_url = f"https://t.kugou.com/song.html?id={share_code}"
        try:
            session = get_session()
            response = session.get(share_url, allow_redirects=True, timeout=10)
            response.raise_for_status()

            # 从 URL 中提取 album_id（如 /album/info/12345）
            url_match = re.search(r'/album/(?:info/)?(\d+)', response.url)
            if url_match:
                return url_match.group(1)

            # 从 HTML 中提取 albumid
            html_match = re.search(r'["\']?album[_]?id["\']?\s*[:=]\s*["\']?(\d+)["\']?', response.text, re.IGNORECASE)
            if html_match:
                return html_match.group(1)

            return None
        except Exception as e:
            print(f"解析专辑分享码失败: {e}")
            return None

    def get_id(self) -> str:
        return self.playlist_album_id

    def get_name(self) -> str:
        return self.playlist_album_name

    def get_songs(self) -> list[dict]:
        """获取歌曲信息列表（包含 hash 和 album_id）"""
        songs = []

        if self.typename == "playlist":
            # 与 test.py 一致，从 data.info 获取
            for song in self.playlist_album_json.get("data", {}).get("info", []):
                songs.append({
                    "hash": song.get("hash", ""),
                    "album_id": song.get("album_id", song.get("albumid", "")),
                    "name": song.get("filename", song.get("name", "")),
                })

        elif self.typename == "album" and "data" in self.playlist_album_json:
            for song in self.playlist_album_json.get("data", {}).get("info", []):
                songs.append({
                    "hash": song.get("hash", ""),
                    "album_id": song.get("album_id", song.get("albumid", "")),
                    "name": song.get("filename", song.get("name", "")),
                })

        return songs

    def save(self) -> None:
        """保存到本地 JSON 文件"""
        # 使用统一的路径管理
        path = get_playlist_dir("KugouMusic") if self.typename == "playlist" else get_album_dir("KugouMusic")
        ensure_dir(path)

        # 获取歌曲信息列表
        all_songs = self.playlist_album_json.get("data", {}).get("info", [])
        song_ids = [song.get("hash", "") for song in all_songs]
        # 保存完整信息供 card.py 使用
        songs_info = [
            {
                "hash": song.get("hash", ""),
                "album_id": song.get("album_id", song.get("albumid", "")),
                "filename": song.get("filename", "")
            }
            for song in all_songs
        ]

        data = {
            "playlist_album_id": self.playlist_album_id,
            "specialid": self.specialid,
            "collection_id": self.collection_id,
            "source": self.source,
            "complete_reason": self.complete_reason,
            "playlist_album_name": self.playlist_album_name,
            "playlist_album_type": self.typename,
            "song_ids": song_ids,
            "songs_info": songs_info,
            "complete": self.complete,
        }

        # 获取封面 URL
        imgurl = ""
        if self.typename == "playlist":
            # 歌单：playlist_info.imgurl，将 {size} 替换为 500
            imgurl = self.playlist_info.get("imgurl", "")
            if imgurl and "{size}" in imgurl:
                imgurl = imgurl.replace("{size}", "500")
        elif self.typename == "album":
            raw = self.album_info.get("sizable_cover") or self.album_info.get("imgurl", "")
            imgurl = raw.replace("{size}", "400") if raw else ""
        data["coverUrl"] = imgurl

        self._write_cache(data)
        print(f"已保存 {self.typename} {self.playlist_album_id} {self.playlist_album_name} 到 {path}")


if __name__ == '__main__':
    # 测试代码
    import sys
    if len(sys.argv) > 2:
        playlist_id = sys.argv[1]
        typename = sys.argv[2]
    else:
        playlist_id = "7hXh101FZV2"  # 测试用分享码
        typename = "playlist"

    playlist = PlaylistAlbumJson(playlist_id, typename).refresh()
    print(f"名称: {playlist.get_name()}")
    print(f"歌曲数量: {len(playlist.get_songs())}")
    if not playlist.is_stale:
        playlist.save()
