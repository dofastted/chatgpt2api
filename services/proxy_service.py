from __future__ import annotations

import json
import uuid
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import quote

from services.config import DATA_DIR, config
from services.sqlite_store import sqlite_store


class ProxyService:
    SUPPORTED_PROTOCOLS = {"http", "socks5"}
    DEFAULT_PROXY_URL = "http://127.0.0.1:10808"

    def __init__(self, store_file: Path):
        self.store_file = store_file
        self.document_name = f"proxies:{self.store_file.resolve()}"
        self._lock = Lock()
        self._items = self._load_items()

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "").strip()

    def _load_items(self) -> list[dict[str, Any]]:
        data = sqlite_store.load_document(self.document_name, [], self.store_file)
        if not isinstance(data, list):
            return []
        return [
            normalized
            for item in data
            if (normalized := self._normalize_item(item)) is not None
        ]

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

    def _normalize_item(self, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        protocol = self._clean_text(item.get("protocol")).lower()
        if protocol not in self.SUPPORTED_PROTOCOLS:
            return None
        host = self._clean_text(item.get("host"))
        if not host:
            return None
        try:
            port = int(item.get("port") or 0)
        except (TypeError, ValueError):
            return None
        if port <= 0 or port > 65535:
            return None
        name = self._clean_text(item.get("name")) or f"{protocol}://{host}:{port}"
        return {
            "id": self._clean_text(item.get("id")) or uuid.uuid4().hex[:16],
            "name": name,
            "protocol": protocol,
            "host": host,
            "port": port,
            "username": self._clean_text(item.get("username")) or None,
            "password": self._clean_text(item.get("password")) or None,
            "enabled": bool(item.get("enabled")),
        }

    @staticmethod
    def build_proxy_url(item: dict[str, Any] | None) -> str | None:
        if not isinstance(item, dict):
            return None
        protocol = str(item.get("protocol") or "").strip().lower()
        host = str(item.get("host") or "").strip()
        try:
            port = int(item.get("port") or 0)
        except (TypeError, ValueError):
            return None
        if protocol not in ProxyService.SUPPORTED_PROTOCOLS or not host or port <= 0:
            return None
        username = str(item.get("username") or "").strip()
        password = str(item.get("password") or "").strip()
        auth = ""
        if username:
            auth = quote(username, safe="")
            if password:
                auth += f":{quote(password, safe='')}"
            auth += "@"
        return f"{protocol}://{auth}{host}:{port}"

    @classmethod
    def _serialize_public(cls, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "protocol": item.get("protocol"),
            "host": item.get("host"),
            "port": item.get("port"),
            "username": item.get("username"),
            "password": item.get("password"),
            "enabled": bool(item.get("enabled")),
            "url": cls.build_proxy_url(item),
        }

    def list_public_items(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._serialize_public(item) for item in self._items]

    def get_enabled_proxy_url(self) -> str | None:
        with self._lock:
            for item in self._items:
                if item.get("enabled"):
                    proxy_url = self.build_proxy_url(item)
                    if proxy_url:
                        return proxy_url
        return self.DEFAULT_PROXY_URL

    def _disable_all_locked(self) -> None:
        for item in self._items:
            item["enabled"] = False

    def upsert_proxy(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_item(payload)
        if normalized is None:
            raise ValueError("invalid proxy payload")
        with self._lock:
            target_id = str(normalized.get("id") or "").strip()
            replaced = False
            if normalized.get("enabled"):
                self._disable_all_locked()
            for index, current in enumerate(self._items):
                if str(current.get("id") or "").strip() != target_id:
                    continue
                if not normalized.get("enabled") and not any(
                    bool(item.get("enabled"))
                    for item in self._items
                    if str(item.get("id") or "").strip() != target_id
                ):
                    normalized["enabled"] = True
                self._items[index] = normalized
                replaced = True
                break
            if not replaced:
                if not self._items:
                    normalized["enabled"] = True
                self._items.append(normalized)
            self._save_items()
            return self._serialize_public(normalized)

    def delete_proxy(self, proxy_id: str) -> dict[str, Any]:
        normalized_id = self._clean_text(proxy_id)
        with self._lock:
            before = len(self._items)
            removed_enabled = any(
                str(item.get("id") or "").strip() == normalized_id and bool(item.get("enabled"))
                for item in self._items
            )
            self._items = [
                item for item in self._items if str(item.get("id") or "").strip() != normalized_id
            ]
            removed = before - len(self._items)
            if removed_enabled and self._items:
                self._items[0]["enabled"] = True
            if removed:
                self._save_items()
            return {
                "removed": removed,
                "items": [self._serialize_public(item) for item in self._items],
            }


proxy_service = ProxyService(config.proxies_file)
