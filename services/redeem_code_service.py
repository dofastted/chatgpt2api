from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from services.config import DATA_DIR, config
from services.sqlite_store import sqlite_store


class RedeemCodeService:
    UNUSED_STATUS = "未使用"
    USED_STATUS = "已使用"

    def __init__(self, store_file: Path):
        self.store_file = store_file
        self.document_name = f"redeem_codes:{self.store_file.resolve()}"
        self._lock = Lock()
        self._items = self._load_items()

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _normalize_status(self, value: Any) -> str:
        text = self._clean_text(value)
        if text in {self.USED_STATUS, "used"}:
            return self.USED_STATUS
        return self.UNUSED_STATUS

    def _normalize_item(self, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        code = self._clean_text(item.get("code"))
        if not code:
            return None
        target_quota = max(0, int(item.get("target_quota") or 0))
        status = self._normalize_status(item.get("status"))
        used_by_key = self._clean_text(item.get("used_by_key")) or None
        if status == self.USED_STATUS and not used_by_key:
            status = self.UNUSED_STATUS
        return {
            "id": hashlib.sha1(code.encode("utf-8")).hexdigest()[:16],
            "code": code,
            "label": self._clean_text(item.get("label")) or None,
            "target_quota": target_quota,
            "status": status,
            "created_at": self._clean_text(item.get("created_at")) or None,
            "updated_at": self._clean_text(item.get("updated_at")) or None,
            "used_at": self._clean_text(item.get("used_at")) or None,
            "used_by_key": used_by_key,
        }

    def _load_items(self) -> list[dict[str, Any]]:
        data = sqlite_store.load_document(self.document_name, [], self.store_file)
        if not isinstance(data, list):
            return []
        return [normalized for item in data if (normalized := self._normalize_item(item)) is not None]

    def _save_items(self) -> None:
        sqlite_store.save_document(self.document_name, self._items)
        try:
            self.store_file.resolve().relative_to(DATA_DIR.resolve())
        except ValueError:
            self.store_file.parent.mkdir(parents=True, exist_ok=True)
            self.store_file.write_text(
                json.dumps(self._items, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    def _public_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": str(item.get("id") or ""),
                "code": self._clean_text(item.get("code")),
                "label": item.get("label"),
                "targetQuota": max(0, int(item.get("target_quota") or 0)),
                "status": self._normalize_status(item.get("status")),
                "createdAt": self._clean_text(item.get("created_at")) or None,
                "updatedAt": self._clean_text(item.get("updated_at")) or None,
                "usedAt": self._clean_text(item.get("used_at")) or None,
                "usedByKey": self._clean_text(item.get("used_by_key")) or None,
            }
            for item in items
            if self._clean_text(item.get("code"))
        ]

    def _build_code(self, prefix: str, existing_codes: set[str]) -> str:
        normalized_prefix = self._clean_text(prefix)
        while True:
            random_part = secrets.token_urlsafe(8).replace("-", "").replace("_", "").upper()[:10]
            candidate = f"{normalized_prefix}-{random_part}" if normalized_prefix else random_part
            if candidate not in existing_codes:
                return candidate

    def list_public_codes(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._public_items(self._items)

    def create_codes(self, count: int, target_quota: int, prefix: str | None = None, label: str | None = None) -> dict[str, Any]:
        normalized_count = max(0, int(count or 0))
        normalized_quota = max(0, int(target_quota or 0))
        if normalized_count <= 0:
            return {"added": 0, "created_items": [], "items": self.list_public_codes()}
        with self._lock:
            existing_codes = {self._clean_text(item.get("code")) for item in self._items if self._clean_text(item.get("code"))}
            created_items: list[dict[str, Any]] = []
            for _ in range(normalized_count):
                now = self._now_text()
                code = self._build_code(prefix or "RDM", existing_codes)
                existing_codes.add(code)
                next_item = self._normalize_item(
                    {
                        "code": code,
                        "label": label,
                        "target_quota": normalized_quota,
                        "status": self.UNUSED_STATUS,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                if next_item is None:
                    continue
                self._items.append(next_item)
                created_items.append(next_item)
            if created_items:
                self._save_items()
            return {
                "added": len(created_items),
                "created_items": self._public_items(created_items),
                "items": self._public_items(self._items),
            }

    def delete_codes(self, codes: list[str]) -> dict[str, Any]:
        target_codes = {self._clean_text(code) for code in codes if self._clean_text(code)}
        if not target_codes:
            return {"removed": 0, "items": self.list_public_codes()}
        with self._lock:
            before = len(self._items)
            self._items = [item for item in self._items if self._clean_text(item.get("code")) not in target_codes]
            removed = before - len(self._items)
            if removed:
                self._save_items()
            return {"removed": removed, "items": self._public_items(self._items)}

    def redeem_code(self, code: str, user_key: str) -> dict[str, Any] | None:
        normalized_code = self._clean_text(code)
        normalized_user_key = self._clean_text(user_key)
        if not normalized_code or not normalized_user_key:
            return None
        with self._lock:
            for index, item in enumerate(self._items):
                if self._clean_text(item.get("code")) != normalized_code:
                    continue
                current = dict(item)
                if self._normalize_status(current.get("status")) == self.USED_STATUS:
                    return None
                now = self._now_text()
                current["status"] = self.USED_STATUS
                current["used_by_key"] = normalized_user_key
                current["used_at"] = now
                current["updated_at"] = now
                normalized = self._normalize_item(current)
                if normalized is None:
                    return None
                self._items[index] = normalized
                self._save_items()
                return dict(normalized)
        return None


redeem_code_service = RedeemCodeService(config.redeem_codes_file)
