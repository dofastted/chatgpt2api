from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

from services.config import config


class UserKeyService:
    ENABLED_STATUS = "启用"
    DISABLED_STATUS = "停用"

    def __init__(self, store_file: Path):
        self.store_file = store_file
        self._lock = Lock()
        self._user_keys = self._load_user_keys()

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "").strip()

    def _normalize_status(self, value: Any) -> str:
        text = self._clean_text(value)
        if text in {self.DISABLED_STATUS, "disabled"}:
            return self.DISABLED_STATUS
        return self.ENABLED_STATUS

    def _normalize_user_key(self, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        key = self._clean_text(item.get("key"))
        if not key:
            return None
        quota = int(item.get("quota") if item.get("quota") is not None else 0)
        if quota < 0:
            quota = 0
        return {
            "id": hashlib.sha1(key.encode("utf-8")).hexdigest()[:16],
            "key": key,
            "label": self._clean_text(item.get("label")) or None,
            "quota": quota,
            "status": self._normalize_status(item.get("status")),
            "created_at": self._clean_text(item.get("created_at")) or None,
            "updated_at": self._clean_text(item.get("updated_at")) or None,
            "last_used_at": self._clean_text(item.get("last_used_at")) or None,
        }

    def _load_user_keys(self) -> list[dict[str, Any]]:
        if not self.store_file.exists():
            return []
        try:
            data = json.loads(self.store_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [normalized for item in data if (normalized := self._normalize_user_key(item)) is not None]

    def _save_user_keys(self) -> None:
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        self.store_file.write_text(
            json.dumps(self._user_keys, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _find_user_key_index(self, key: str) -> int:
        for index, item in enumerate(self._user_keys):
            if self._clean_text(item.get("key")) == key:
                return index
        return -1

    def get_user_key(self, key: str) -> dict[str, Any] | None:
        normalized_key = self._clean_text(key)
        if not normalized_key:
            return None
        with self._lock:
            index = self._find_user_key_index(normalized_key)
            if index < 0:
                return None
            return dict(self._user_keys[index])

    def is_enabled(self, key: str) -> bool:
        item = self.get_user_key(key)
        if item is None:
            return False
        return item.get("status") == self.ENABLED_STATUS

    def list_user_keys(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._user_keys]


user_key_service = UserKeyService(config.user_keys_file)
