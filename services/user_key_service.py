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


class UserKeyService:
    ENABLED_STATUS = "启用"
    DISABLED_STATUS = "停用"
    SUPPORTED_MODELS = ("gpt-image-2", "gpt-image-2-2K", "gpt-image-2-4K")
    DEFAULT_PRICING = {
        "gpt-image-2": 2,
        "gpt-image-2-2K": 2,
        "gpt-image-2-4K": 8,
    }

    def __init__(self, store_file: Path):
        self.store_file = store_file
        self.document_name = f"user_keys:{self.store_file.resolve()}"
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

    def _normalize_pricing(self, value: Any) -> dict[str, int]:
        normalized = dict(self.DEFAULT_PRICING)
        if isinstance(value, dict):
            for model in self.SUPPORTED_MODELS:
                if value.get(model) is None:
                    continue
                price = int(value.get(model) or 0)
                normalized[model] = max(0, price)
        return normalized

    def normalize_pricing(self, value: Any) -> dict[str, int]:
        return self._normalize_pricing(value)

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
            "ldc_balance": max(0, int(item.get("ldc_balance") or 0)),
            "status": self._normalize_status(item.get("status")),
            "pricing": self._normalize_pricing(item.get("pricing")),
            "created_at": self._clean_text(item.get("created_at")) or None,
            "updated_at": self._clean_text(item.get("updated_at")) or None,
            "last_used_at": self._clean_text(item.get("last_used_at")) or None,
        }

    @staticmethod
    def _now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _load_user_keys(self) -> list[dict[str, Any]]:
        data = sqlite_store.load_document(self.document_name, [], self.store_file)
        if not isinstance(data, list):
            return []
        return [normalized for item in data if (normalized := self._normalize_user_key(item)) is not None]

    def _save_user_keys(self) -> None:
        sqlite_store.save_document(self.document_name, self._user_keys)
        try:
            self.store_file.resolve().relative_to(DATA_DIR.resolve())
        except ValueError:
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

    def _public_items(self, user_keys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": str(item.get("id") or ""),
                "key": self._clean_text(item.get("key")),
                "label": item.get("label"),
                "quota": max(0, int(item.get("quota") or 0)),
                "ldcBalance": max(0, int(item.get("ldc_balance") or 0)),
                "status": self._normalize_status(item.get("status")),
                "pricing": self._normalize_pricing(item.get("pricing")),
                "createdAt": self._clean_text(item.get("created_at")) or None,
                "updatedAt": self._clean_text(item.get("updated_at")) or None,
                "lastUsedAt": self._clean_text(item.get("last_used_at")) or None,
            }
            for item in user_keys
            if self._clean_text(item.get("key"))
        ]

    def _build_generated_key(self, prefix: str, existing_keys: set[str]) -> str:
        normalized_prefix = self._clean_text(prefix)
        while True:
            random_part = secrets.token_urlsafe(18).replace("-", "").replace("_", "")
            candidate = f"{normalized_prefix}_{random_part}" if normalized_prefix else random_part
            if candidate not in existing_keys:
                return candidate

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

    def list_public_user_keys(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._public_items(self._user_keys)

    def get_pricing(self, key: str) -> dict[str, int] | None:
        item = self.get_user_key(key)
        if item is None:
            return None
        return self._normalize_pricing(item.get("pricing"))

    def resolve_request_cost(self, key: str, model: str, n: int) -> int | None:
        pricing = self.get_pricing(key)
        if pricing is None:
            return None
        normalized_model = self._clean_text(model)
        if normalized_model not in self.SUPPORTED_MODELS:
            return None
        return max(1, int(n or 1)) * max(0, int(pricing.get(normalized_model) or 0))

    def create_user_keys(
            self,
            count: int,
            quota: int,
            prefix: str | None = None,
            label_prefix: str | None = None,
            status: str | None = None,
            pricing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_count = max(0, int(count or 0))
        normalized_quota = max(0, int(quota or 0))
        normalized_status = self._normalize_status(status)
        cleaned_label_prefix = self._clean_text(label_prefix)
        normalized_pricing = self._normalize_pricing(pricing)
        if normalized_count <= 0:
            return {"added": 0, "created_items": [], "items": self.list_public_user_keys()}

        with self._lock:
            existing_keys = {self._clean_text(item.get("key")) for item in self._user_keys if self._clean_text(item.get("key"))}
            created_items: list[dict[str, Any]] = []
            for index in range(normalized_count):
                now = self._now_text()
                generated_key = self._build_generated_key(prefix or "uk", existing_keys)
                existing_keys.add(generated_key)
                next_item = self._normalize_user_key(
                    {
                        "key": generated_key,
                        "label": f"{cleaned_label_prefix}{index + 1}" if cleaned_label_prefix else None,
                        "quota": normalized_quota,
                        "ldc_balance": 0,
                        "status": normalized_status,
                        "pricing": normalized_pricing,
                        "created_at": now,
                        "updated_at": now,
                        "last_used_at": None,
                    }
                )
                if next_item is None:
                    continue
                self._user_keys.append(next_item)
                created_items.append(next_item)
            if created_items:
                self._save_user_keys()
            return {
                "added": len(created_items),
                "created_items": self._public_items(created_items),
                "items": self._public_items(self._user_keys),
            }

    def delete_user_keys(self, keys: list[str]) -> dict[str, Any]:
        target_keys = {self._clean_text(key) for key in keys if self._clean_text(key)}
        if not target_keys:
            return {"removed": 0, "items": self.list_public_user_keys()}
        with self._lock:
            before = len(self._user_keys)
            self._user_keys = [item for item in self._user_keys if self._clean_text(item.get("key")) not in target_keys]
            removed = before - len(self._user_keys)
            if removed:
                self._save_user_keys()
            return {"removed": removed, "items": self._public_items(self._user_keys)}

    def update_user_key(self, key: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        normalized_key = self._clean_text(key)
        if not normalized_key:
            return None
        with self._lock:
            index = self._find_user_key_index(normalized_key)
            if index < 0:
                return None
            current = dict(self._user_keys[index])
            next_item = self._normalize_user_key(
                {
                    **current,
                    **updates,
                    "key": normalized_key,
                    "updated_at": self._now_text(),
                }
            )
            if next_item is None:
                return None
            self._user_keys[index] = next_item
            self._save_user_keys()
            public_items = self._public_items(self._user_keys)
            target_item = next((item for item in public_items if self._clean_text(item.get("key")) == normalized_key), None)
            if target_item is None:
                return None
            return dict(target_item)

    def consume_quota(self, key: str, cost: int) -> dict[str, Any] | None:
        normalized_key = self._clean_text(key)
        normalized_cost = max(0, int(cost or 0))
        if not normalized_key or normalized_cost <= 0:
            return self.get_user_key(normalized_key)
        with self._lock:
            index = self._find_user_key_index(normalized_key)
            if index < 0:
                return None
            current = dict(self._user_keys[index])
            if current.get("status") != self.ENABLED_STATUS:
                return None
            quota = max(0, int(current.get("quota") or 0))
            if quota < normalized_cost:
                return None
            current["quota"] = quota - normalized_cost
            current["updated_at"] = self._now_text()
            normalized = self._normalize_user_key(current)
            if normalized is None:
                return None
            self._user_keys[index] = normalized
            self._save_user_keys()
            return dict(normalized)

    def refund_quota(self, key: str, cost: int) -> dict[str, Any] | None:
        normalized_key = self._clean_text(key)
        normalized_cost = max(0, int(cost or 0))
        if not normalized_key or normalized_cost <= 0:
            return self.get_user_key(normalized_key)
        with self._lock:
            index = self._find_user_key_index(normalized_key)
            if index < 0:
                return None
            current = dict(self._user_keys[index])
            current["quota"] = max(0, int(current.get("quota") or 0)) + normalized_cost
            current["updated_at"] = self._now_text()
            normalized = self._normalize_user_key(current)
            if normalized is None:
                return None
            self._user_keys[index] = normalized
            self._save_user_keys()
            return dict(normalized)

    def set_quota(self, key: str, quota: int) -> dict[str, Any] | None:
        normalized_key = self._clean_text(key)
        if not normalized_key:
            return None
        with self._lock:
            index = self._find_user_key_index(normalized_key)
            if index < 0:
                return None
            current = dict(self._user_keys[index])
            current["quota"] = max(0, int(quota or 0))
            current["updated_at"] = self._now_text()
            normalized = self._normalize_user_key(current)
            if normalized is None:
                return None
            self._user_keys[index] = normalized
            self._save_user_keys()
            return dict(normalized)

    def grant_quota(self, key: str, quota: int) -> dict[str, Any] | None:
        normalized_key = self._clean_text(key)
        normalized_quota = max(0, int(quota or 0))
        if not normalized_key or normalized_quota <= 0:
            return self.get_user_key(normalized_key)
        with self._lock:
            index = self._find_user_key_index(normalized_key)
            if index < 0:
                return None
            current = dict(self._user_keys[index])
            current["quota"] = max(0, int(current.get("quota") or 0)) + normalized_quota
            current["updated_at"] = self._now_text()
            normalized = self._normalize_user_key(current)
            if normalized is None:
                return None
            self._user_keys[index] = normalized
            self._save_user_keys()
            return dict(normalized)

    def spend_ldc(self, key: str, amount: int) -> dict[str, Any] | None:
        normalized_key = self._clean_text(key)
        normalized_amount = max(0, int(amount or 0))
        if not normalized_key or normalized_amount <= 0:
            return self.get_user_key(normalized_key)
        with self._lock:
            index = self._find_user_key_index(normalized_key)
            if index < 0:
                return None
            current = dict(self._user_keys[index])
            if current.get("status") != self.ENABLED_STATUS:
                return None
            ldc_balance = max(0, int(current.get("ldc_balance") or 0))
            if ldc_balance < normalized_amount:
                return None
            current["ldc_balance"] = ldc_balance - normalized_amount
            current["updated_at"] = self._now_text()
            normalized = self._normalize_user_key(current)
            if normalized is None:
                return None
            self._user_keys[index] = normalized
            self._save_user_keys()
            return dict(normalized)

    def grant_ldc(self, key: str, amount: int) -> dict[str, Any] | None:
        normalized_key = self._clean_text(key)
        normalized_amount = max(0, int(amount or 0))
        if not normalized_key or normalized_amount <= 0:
            return self.get_user_key(normalized_key)
        with self._lock:
            index = self._find_user_key_index(normalized_key)
            if index < 0:
                return None
            current = dict(self._user_keys[index])
            current["ldc_balance"] = max(0, int(current.get("ldc_balance") or 0)) + normalized_amount
            current["updated_at"] = self._now_text()
            normalized = self._normalize_user_key(current)
            if normalized is None:
                return None
            self._user_keys[index] = normalized
            self._save_user_keys()
            return dict(normalized)

    def mark_used(self, key: str) -> dict[str, Any] | None:
        normalized_key = self._clean_text(key)
        if not normalized_key:
            return None
        with self._lock:
            index = self._find_user_key_index(normalized_key)
            if index < 0:
                return None
            current = dict(self._user_keys[index])
            now = self._now_text()
            current["updated_at"] = now
            current["last_used_at"] = now
            normalized = self._normalize_user_key(current)
            if normalized is None:
                return None
            self._user_keys[index] = normalized
            self._save_user_keys()
            return dict(normalized)


user_key_service = UserKeyService(config.user_keys_file)
