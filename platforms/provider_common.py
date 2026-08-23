"""音乐平台数据提供器的公共生命周期与缓存工具。"""

from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from settings.user_data_path import ensure_dir, get_album_dir, get_playlist_dir

COLLECTION_TYPES = {"playlist", "album"}
CACHE_SCHEMA_VERSION = 2


class CollectionProvider(ABC):
    """提供显式刷新和陈旧缓存回退的公共基类。"""

    platform_name: str

    def __init__(self, collection_id: str, collection_type: str):
        if collection_type not in COLLECTION_TYPES:
            raise ValueError("typename must be 'playlist' or 'album'")

        self.playlist_album_id = collection_id
        self.typename = collection_type
        self.is_stale = False
        self.last_refresh_error = ""

    def refresh(self) -> CollectionProvider:
        """刷新远端数据；失败时尝试恢复上一份有效缓存。"""
        try:
            self._fetch_data()
        except Exception as exc:
            if not self._load_from_cache():
                raise
            self.is_stale = True
            self.last_refresh_error = str(exc)
            print(f"远端刷新失败，使用本地缓存: {exc}")
        else:
            self.is_stale = False
            self.last_refresh_error = ""
        return self

    @abstractmethod
    def _fetch_data(self) -> None:
        """从平台获取并解析集合数据。"""

    @abstractmethod
    def _load_from_cache(self) -> bool:
        """恢复本地缓存，成功返回 True。"""

    def _cache_path(self) -> str:
        directory = (
            get_playlist_dir(self.platform_name)
            if self.typename == "playlist"
            else get_album_dir(self.platform_name)
        )
        return os.path.join(directory, f"{self.playlist_album_id}.json")

    def _read_cache(self) -> dict[str, Any] | None:
        path = self._cache_path()
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as cache_file:
            data = json.load(cache_file)
        return data if isinstance(data, dict) else None

    def _write_cache(self, data: dict[str, Any]) -> str:
        """在目标目录内原子替换缓存，避免中途退出留下半个 JSON。"""
        path = self._cache_path()
        directory = os.path.dirname(path)
        ensure_dir(directory)

        record = {
            **data,
            "schema_version": CACHE_SCHEMA_VERSION,
            "fetched_at": datetime.now(UTC).isoformat(),
            "complete": data.get("complete", True),
        }

        fd, temporary_path = tempfile.mkstemp(
            dir=directory,
            prefix=f".{os.path.basename(path)}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as cache_file:
                json.dump(record, cache_file, ensure_ascii=False, indent=4)
                cache_file.flush()
                os.fsync(cache_file.fileno())
            os.replace(temporary_path, path)
        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        return path


def response_json(response: Any) -> dict[str, Any]:
    """校验 HTTP 状态和 JSON 顶层类型。"""
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("平台 API 返回的 JSON 顶层不是对象")
    return data
