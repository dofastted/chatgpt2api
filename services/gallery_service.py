from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from base64 import b64decode
from binascii import Error as BinasciiError
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from services.sqlite_store import SQLiteStore, sqlite_store


BASE_DIR = Path(__file__).resolve().parents[1]
SEED_FILE = BASE_DIR / "web" / "src" / "data" / "gallery-ui-seed.json"
DIMENSIONS_FILE = BASE_DIR / "web" / "src" / "data" / "gallery-image-dimensions.json"

PUBLISHED_STATUSES = {"published"}
VISIBLE_STATUSES = {"published", "pending", "rejected", "hidden"}
ADMIN_STATUSES = {"pending", "published", "rejected", "hidden", "deleted"}
GALLERY_SOURCES = {"seed", "user_submission", "admin"}

PLACEHOLDER_PROMPTS = {
    "未提供",
    "提示词",
    "补一张",
    "陪一张",
    "我的第一个作品",
    "第二个作品",
    "何意味",
}
CHATTER_PATTERNS = (
    "点赞",
    "转发",
    "网络",
    "回复",
    "邀请码",
    "兑换码",
    "评论区",
    "不计入",
    "奖品",
    "截止",
    "哈哈",
    "试了一下",
    "求一个",
    "借楼",
)
GENERATION_INTENT_PATTERNS = (
    "生成",
    "画",
    "图",
    "照片",
    "海报",
    "插画",
    "风格",
    "人物",
    "场景",
    "设计",
    "portrait",
    "photo",
    "image",
    "poster",
    "illustration",
    "cinematic",
    "render",
)


def now_text() -> str:
    return SQLiteStore.now_text()


def normalize_prompt(prompt: str) -> str:
    return re.sub(r"\s+", " ", str(prompt or "")).strip()


def build_prompt_preview(prompt: str, limit: int = 160) -> str:
    normalized = normalize_prompt(prompt)
    return normalized if len(normalized) <= limit else f"{normalized[:limit]}..."


def stable_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def owner_id_from_token(auth_token: str) -> str:
    return stable_hash(str(auth_token or "").strip())


def is_data_image_url(url: str) -> bool:
    return str(url or "").lower().startswith("data:image/")


def is_base64_data_image_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return lowered.startswith("data:image/") and ";base64," in lowered


def is_seed_prompt_usable(prompt: str) -> bool:
    normalized = normalize_prompt(prompt)
    if not normalized:
        return False
    if normalized in PLACEHOLDER_PROMPTS:
        return False
    lowered = normalized.lower()
    has_intent = any(pattern.lower() in lowered for pattern in GENERATION_INTENT_PATTERNS)
    if len(normalized) < 20 and not has_intent:
        return False
    chatter_hits = sum(1 for pattern in CHATTER_PATTERNS if pattern.lower() in lowered)
    if chatter_hits >= 2 and len(normalized) < 420:
        return False
    if chatter_hits >= 3 and not has_intent:
        return False
    return True


class GalleryService:
    def __init__(
            self,
            store: SQLiteStore = sqlite_store,
            *,
            seed_file: Path = SEED_FILE,
            dimensions_file: Path = DIMENSIONS_FILE,
    ):
        self.store = store
        self.seed_file = seed_file
        self.dimensions_file = dimensions_file
        self._lock = Lock()
        self.initialize()

    def initialize(self) -> None:
        with self._lock:
            with self.store.connect() as connection:
                self._ensure_schema(connection)

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS gallery_items (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                visibility INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL,
                prompt TEXT NOT NULL,
                prompt_preview TEXT NOT NULL,
                title TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_pinned INTEGER NOT NULL DEFAULT 0,
                submitted_by_owner_id TEXT,
                submitted_at TEXT,
                reviewed_at TEXT,
                reviewed_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                published_at TEXT,
                last_clicked_at TEXT,
                last_used_at TEXT,
                click_count INTEGER NOT NULL DEFAULT 0,
                use_count INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_gallery_items_public_order
                ON gallery_items(status, visibility, is_pinned DESC, sort_order ASC, published_at DESC);
            CREATE INDEX IF NOT EXISTS idx_gallery_items_admin_status
                ON gallery_items(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_gallery_items_submitter
                ON gallery_items(submitted_by_owner_id, submitted_at DESC);
            CREATE TABLE IF NOT EXISTS gallery_assets (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                url TEXT NOT NULL,
                file_id TEXT,
                mime_type TEXT,
                width INTEGER,
                height INTEGER,
                size_bytes INTEGER,
                created_at TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(item_id) REFERENCES gallery_items(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_gallery_assets_item
                ON gallery_assets(item_id, sort_order ASC);
            """
        )

    def ensure_seed_imported(self) -> None:
        with self._lock:
            with self.store.connect() as connection:
                self._ensure_schema(connection)
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM gallery_items WHERE source = 'seed'"
                ).fetchone()
                if row and int(row["count"] or 0) > 0:
                    return
                self._import_seed_locked(connection)

    def _load_seed_items(self) -> list[dict[str, Any]]:
        if not self.seed_file.exists():
            return []
        try:
            data = json.loads(self.seed_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [item for item in data if isinstance(item, dict)]

    def _load_dimensions(self) -> dict[str, dict[str, Any]]:
        if not self.dimensions_file.exists():
            return {}
        try:
            data = json.loads(self.dimensions_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {
            str(item.get("id") or ""): item
            for item in data
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }

    def _import_seed_locked(self, connection: sqlite3.Connection) -> None:
        seed_items = self._load_seed_items()
        dimensions = self._load_dimensions()
        now = now_text()
        inserted = 0
        for item in seed_items:
            prompt = normalize_prompt(str(item.get("prompt") or ""))
            image_url = str(item.get("imageUrl") or "").strip()
            if not image_url or not is_seed_prompt_usable(prompt):
                continue
            seed_id = str(item.get("id") or "").strip() or str(inserted + 1)
            item_id = f"seed-{seed_id}"
            title = str(item.get("title") or "").strip() or f"画廊项 {seed_id}"
            metadata = {
                "seed_id": seed_id,
                "post_number": item.get("postNumber"),
                "username": item.get("username"),
                "image_index": item.get("imageIndex"),
                "download_path": item.get("downloadPath"),
                "post_url": item.get("postUrl"),
            }
            connection.execute(
                """
                INSERT OR IGNORE INTO gallery_items (
                    id, status, visibility, source, prompt, prompt_preview, title,
                    tags_json, sort_order, is_pinned, submitted_at, reviewed_at,
                    reviewed_by, created_at, updated_at, published_at, metadata_json
                )
                VALUES (?, 'published', 1, 'seed', ?, ?, ?, '[]', ?, 0, ?, ?, 'seed-import', ?, ?, ?, ?)
                """,
                (
                    item_id,
                    prompt,
                    build_prompt_preview(prompt),
                    title,
                    inserted,
                    now,
                    now,
                    now,
                    now,
                    now,
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            dimension = dimensions.get(seed_id, {})
            asset_id = f"{item_id}-cover"
            connection.execute(
                """
                INSERT OR IGNORE INTO gallery_assets (
                    id, item_id, kind, url, mime_type, width, height, created_at, sort_order
                )
                VALUES (?, ?, 'image', ?, ?, ?, ?, ?, 0)
                """,
                (
                    asset_id,
                    item_id,
                    image_url,
                    self._mime_from_url(image_url),
                    self._optional_int(dimension.get("width")),
                    self._optional_int(dimension.get("height")),
                    now,
                ),
            )
            inserted += 1

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        numeric = int(value or 0)
        return numeric if numeric > 0 else None

    @staticmethod
    def _mime_from_url(url: str) -> str | None:
        lowered = str(url or "").split("?", 1)[0].lower()
        if lowered.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        if lowered.endswith(".webp"):
            return "image/webp"
        if lowered.endswith(".gif"):
            return "image/gif"
        if lowered.endswith(".avif"):
            return "image/avif"
        if lowered.endswith(".png"):
            return "image/png"
        if lowered.startswith("data:image/"):
            return lowered.split(";", 1)[0].replace("data:", "")
        return None

    def _rows_to_items(
            self,
            connection: sqlite3.Connection,
            rows: list[sqlite3.Row],
            *,
            asset_url_mode: str = "full",
    ) -> list[dict[str, Any]]:
        if not rows:
            return []
        ids = [str(row["id"]) for row in rows]
        placeholders = ",".join("?" for _ in ids)
        asset_rows = connection.execute(
            f"""
            SELECT
                id,
                item_id,
                kind,
                CASE
                    WHEN ? = 'asset_api' AND lower(substr(url, 1, 96)) LIKE 'data:image/%;base64,%' THEN NULL
                    ELSE url
                END AS url,
                CASE
                    WHEN ? = 'asset_api' AND lower(substr(url, 1, 96)) LIKE 'data:image/%;base64,%' THEN 1
                    ELSE 0
                END AS has_legacy_data_image,
                file_id,
                mime_type,
                width,
                height,
                size_bytes,
                created_at,
                sort_order
            FROM gallery_assets
            WHERE item_id IN ({placeholders})
            ORDER BY item_id, sort_order ASC
            """,
            [asset_url_mode, asset_url_mode, *ids],
        ).fetchall()
        assets_by_item: dict[str, list[dict[str, Any]]] = {}
        for row in asset_rows:
            asset = {
                "asset_id": str(row["id"]),
                "kind": str(row["kind"]),
                "url": self._asset_url_from_row(row, mode=asset_url_mode),
                "file_id": row["file_id"],
                "mime_type": row["mime_type"],
                "width": row["width"],
                "height": row["height"],
                "size_bytes": row["size_bytes"],
                "created_at": row["created_at"],
            }
            assets_by_item.setdefault(str(row["item_id"]), []).append(asset)
        return [self._row_to_item(row, assets_by_item.get(str(row["id"]), [])) for row in rows]

    def _asset_url_from_row(self, row: sqlite3.Row, *, mode: str) -> str:
        url = str(row["url"] or "")
        if mode == "asset_api" and int(row["has_legacy_data_image"] or 0):
            return f"/api/gallery/assets/{str(row['id'])}"
        return url

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        normalized_id = str(asset_id or "").strip()
        if not normalized_id:
            return None
        with self.store.connect() as connection:
            row = connection.execute(
                """
                SELECT id, kind, url, mime_type, width, height, size_bytes, created_at
                FROM gallery_assets
                WHERE id = ?
                """,
                (normalized_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "asset_id": str(row["id"]),
            "kind": str(row["kind"]),
            "url": str(row["url"]),
            "mime_type": row["mime_type"],
            "width": row["width"],
            "height": row["height"],
            "size_bytes": row["size_bytes"],
            "created_at": row["created_at"],
        }

    def get_asset_image_response(self, asset_id: str) -> tuple[bytes, str] | None:
        asset = self.get_asset(asset_id)
        if asset is None:
            return None
        url = str(asset.get("url") or "")
        if not is_base64_data_image_url(url):
            return None
        header, _, raw_data = url.partition(",")
        if not raw_data:
            return None
        mime_type = str(asset.get("mime_type") or "").strip()
        if not mime_type:
            mime_type = header.split(";", 1)[0].replace("data:", "") or "image/png"
        try:
            return b64decode(raw_data, validate=True), mime_type
        except (BinasciiError, ValueError):
            return None

    def _row_to_item(self, row: sqlite3.Row, assets: list[dict[str, Any]]) -> dict[str, Any]:
        metadata = self._decode_json(row["metadata_json"], {})
        tags = self._decode_json(row["tags_json"], [])
        cover_asset_id = assets[0]["asset_id"] if assets else None
        return {
            "id": str(row["id"]),
            "status": str(row["status"]),
            "visibility": bool(row["visibility"]),
            "source": str(row["source"]),
            "prompt": str(row["prompt"]),
            "prompt_preview": str(row["prompt_preview"]),
            "title": row["title"],
            "tags": tags if isinstance(tags, list) else [],
            "assets": assets,
            "cover_asset_id": cover_asset_id,
            "sort_order": int(row["sort_order"] or 0),
            "is_pinned": bool(row["is_pinned"]),
            "submitted_by_owner_id": row["submitted_by_owner_id"],
            "submitted_at": row["submitted_at"],
            "reviewed_at": row["reviewed_at"],
            "reviewed_by": row["reviewed_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "published_at": row["published_at"],
            "last_clicked_at": row["last_clicked_at"],
            "last_used_at": row["last_used_at"],
            "click_count": int(row["click_count"] or 0),
            "use_count": int(row["use_count"] or 0),
            "metadata": metadata if isinstance(metadata, dict) else {},
        }

    @staticmethod
    def _decode_json(value: Any, default: Any) -> Any:
        try:
            return json.loads(str(value or ""))
        except json.JSONDecodeError:
            return default

    def list_public_items(self, *, limit: int = 120) -> list[dict[str, Any]]:
        self.ensure_seed_imported()
        with self.store.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM gallery_items
                WHERE status = 'published' AND visibility = 1
                ORDER BY is_pinned DESC, sort_order ASC, published_at DESC, created_at DESC
                LIMIT ?
                """,
                (max(1, min(500, int(limit or 120))),),
            ).fetchall()
            return self._rows_to_items(connection, rows, asset_url_mode="asset_api")

    def list_admin_items(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        self.ensure_seed_imported()
        normalized_status = str(status or "").strip()
        with self.store.connect() as connection:
            if normalized_status and normalized_status in ADMIN_STATUSES:
                rows = connection.execute(
                    """
                    SELECT * FROM gallery_items
                    WHERE status = ?
                    ORDER BY is_pinned DESC, sort_order ASC, updated_at DESC
                    LIMIT ?
                    """,
                    (normalized_status, max(1, min(500, int(limit or 200)))),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM gallery_items
                    WHERE status != 'deleted'
                    ORDER BY
                        CASE status WHEN 'pending' THEN 0 WHEN 'published' THEN 1 WHEN 'hidden' THEN 2 ELSE 3 END,
                        is_pinned DESC,
                        sort_order ASC,
                        updated_at DESC
                    LIMIT ?
                    """,
                    (max(1, min(500, int(limit or 200))),),
                ).fetchall()
            return self._rows_to_items(connection, rows, asset_url_mode="asset_api")

    def submit_item(self, *, auth_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = normalize_prompt(str(payload.get("prompt") or ""))
        if not prompt:
            raise ValueError("prompt is required")
        assets = self._normalize_assets(payload.get("assets"), payload=payload)
        if not assets:
            raise ValueError("at least one image asset is required")
        now = now_text()
        item_id = f"gal_{uuid4().hex}"
        owner_id = owner_id_from_token(auth_token)
        with self._lock:
            with self.store.connect() as connection:
                self._ensure_schema(connection)
                connection.execute(
                    """
                    INSERT INTO gallery_items (
                        id, status, visibility, source, prompt, prompt_preview, title,
                        tags_json, sort_order, is_pinned, submitted_by_owner_id,
                        submitted_at, created_at, updated_at, metadata_json
                    )
                    VALUES (?, 'pending', 0, 'user_submission', ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        prompt,
                        build_prompt_preview(prompt),
                        self._optional_text(payload.get("title")),
                        json.dumps(self._normalize_tags(payload.get("tags")), ensure_ascii=False),
                        owner_id,
                        now,
                        now,
                        now,
                        json.dumps(self._submission_metadata(payload), ensure_ascii=False),
                    ),
                )
                self._replace_assets(connection, item_id, assets, now)
                rows = connection.execute("SELECT * FROM gallery_items WHERE id = ?", (item_id,)).fetchall()
                return self._rows_to_items(connection, rows)[0]

    def _submission_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_conversation_id": self._optional_text(payload.get("source_conversation_id")),
            "source_turn_id": self._optional_text(payload.get("source_turn_id")),
            "source_image_id": self._optional_text(payload.get("source_image_id")),
        }

    def _normalize_assets(self, raw_assets: Any, *, payload: dict[str, Any]) -> list[dict[str, Any]]:
        assets = raw_assets if isinstance(raw_assets, list) else []
        if not assets:
            url = self._optional_text(payload.get("image_url"))
            if url:
                assets = [{"url": url, "mime_type": payload.get("mime_type")}]
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(assets):
            if not isinstance(item, dict):
                continue
            url = self._optional_text(item.get("url") or item.get("imageUrl"))
            if not url:
                continue
            width = self._optional_int(item.get("width"))
            height = self._optional_int(item.get("height"))
            normalized.append(
                {
                    "id": self._optional_text(item.get("asset_id") or item.get("id")) or f"asset_{uuid4().hex}",
                    "kind": self._optional_text(item.get("kind")) or "image",
                    "url": url,
                    "file_id": self._optional_text(item.get("file_id") or item.get("fileId")),
                    "mime_type": self._optional_text(item.get("mime_type") or item.get("mimeType")) or self._mime_from_url(url),
                    "width": width,
                    "height": height,
                    "size_bytes": self._optional_int(item.get("size_bytes") or item.get("sizeBytes")),
                    "sort_order": index,
                }
            )
        return normalized

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _normalize_tags(value: Any) -> list[str]:
        if isinstance(value, str):
            raw_tags = re.split(r"[,，\s]+", value)
        elif isinstance(value, list):
            raw_tags = [str(item or "") for item in value]
        else:
            raw_tags = []
        result: list[str] = []
        for tag in raw_tags:
            normalized = tag.strip().lower()
            if normalized and normalized not in result:
                result.append(normalized[:32])
        return result[:12]

    def _replace_assets(
            self,
            connection: sqlite3.Connection,
            item_id: str,
            assets: list[dict[str, Any]],
            created_at: str,
    ) -> None:
        connection.execute("DELETE FROM gallery_assets WHERE item_id = ?", (item_id,))
        for index, asset in enumerate(assets):
            connection.execute(
                """
                INSERT INTO gallery_assets (
                    id, item_id, kind, url, file_id, mime_type, width, height, size_bytes, created_at, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(asset["id"]),
                    item_id,
                    str(asset.get("kind") or "image"),
                    str(asset["url"]),
                    asset.get("file_id"),
                    asset.get("mime_type"),
                    asset.get("width"),
                    asset.get("height"),
                    asset.get("size_bytes"),
                    created_at,
                    int(asset.get("sort_order") if asset.get("sort_order") is not None else index),
                ),
            )

    def record_event(self, item_id: str, event_type: str) -> dict[str, Any] | None:
        normalized_id = str(item_id or "").strip()
        normalized_event = str(event_type or "").strip()
        if not normalized_id or normalized_event not in {"click", "use"}:
            raise ValueError("event must be click or use")
        field = "click_count" if normalized_event == "click" else "use_count"
        time_field = "last_clicked_at" if normalized_event == "click" else "last_used_at"
        now = now_text()
        with self._lock:
            with self.store.connect() as connection:
                self._ensure_schema(connection)
                cursor = connection.execute(
                    f"""
                    UPDATE gallery_items
                    SET {field} = {field} + 1, {time_field} = ?, updated_at = ?
                    WHERE id = ? AND status = 'published' AND visibility = 1
                    """,
                    (now, now, normalized_id),
                )
                if cursor.rowcount <= 0:
                    return None
                rows = connection.execute("SELECT * FROM gallery_items WHERE id = ?", (normalized_id,)).fetchall()
                items = self._rows_to_items(connection, rows)
                return items[0] if items else None

    def admin_update_item(self, item_id: str, payload: dict[str, Any], *, reviewed_by: str = "admin") -> dict[str, Any]:
        normalized_id = str(item_id or "").strip()
        if not normalized_id:
            raise ValueError("gallery item id is required")
        now = now_text()
        with self._lock:
            with self.store.connect() as connection:
                self._ensure_schema(connection)
                existing = connection.execute(
                    "SELECT * FROM gallery_items WHERE id = ? AND status != 'deleted'",
                    (normalized_id,),
                ).fetchone()
                if existing is None:
                    raise KeyError(normalized_id)
                updates: dict[str, Any] = {"updated_at": now}
                action = str(payload.get("action") or "").strip()
                if action == "approve":
                    updates.update(
                        {
                            "status": "published",
                            "visibility": 1,
                            "reviewed_at": now,
                            "reviewed_by": reviewed_by,
                            "published_at": existing["published_at"] or now,
                        }
                    )
                elif action == "reject":
                    updates.update(
                        {
                            "status": "rejected",
                            "visibility": 0,
                            "reviewed_at": now,
                            "reviewed_by": reviewed_by,
                        }
                    )
                elif action == "hide":
                    updates.update({"status": "hidden", "visibility": 0})
                elif action == "publish":
                    updates.update(
                        {
                            "status": "published",
                            "visibility": 1,
                            "published_at": existing["published_at"] or now,
                        }
                    )
                if "status" in payload:
                    status = str(payload.get("status") or "").strip()
                    if status not in ADMIN_STATUSES:
                        raise ValueError("invalid gallery status")
                    updates["status"] = status
                    if status == "published":
                        updates["published_at"] = existing["published_at"] or now
                    if status in {"hidden", "rejected"}:
                        updates["visibility"] = 0
                if "visibility" in payload:
                    updates["visibility"] = 1 if bool(payload.get("visibility")) else 0
                if "prompt" in payload:
                    prompt = normalize_prompt(str(payload.get("prompt") or ""))
                    if not prompt:
                        raise ValueError("prompt is required")
                    updates["prompt"] = prompt
                    updates["prompt_preview"] = build_prompt_preview(prompt)
                if "title" in payload:
                    updates["title"] = self._optional_text(payload.get("title"))
                if "tags" in payload:
                    updates["tags_json"] = json.dumps(self._normalize_tags(payload.get("tags")), ensure_ascii=False)
                if "sort_order" in payload:
                    updates["sort_order"] = int(payload.get("sort_order") or 0)
                if "is_pinned" in payload:
                    updates["is_pinned"] = 1 if bool(payload.get("is_pinned")) else 0
                assignments = ", ".join(f"{key} = ?" for key in updates)
                connection.execute(
                    f"UPDATE gallery_items SET {assignments} WHERE id = ?",
                    [*updates.values(), normalized_id],
                )
                if "assets" in payload or "image_url" in payload:
                    assets = self._normalize_assets(payload.get("assets"), payload=payload)
                    if assets:
                        self._replace_assets(connection, normalized_id, assets, now)
                rows = connection.execute("SELECT * FROM gallery_items WHERE id = ?", (normalized_id,)).fetchall()
                return self._rows_to_items(connection, rows)[0]

    def admin_delete_item(self, item_id: str) -> dict[str, Any]:
        normalized_id = str(item_id or "").strip()
        if not normalized_id:
            raise ValueError("gallery item id is required")
        now = now_text()
        with self._lock:
            with self.store.connect() as connection:
                self._ensure_schema(connection)
                cursor = connection.execute(
                    """
                    UPDATE gallery_items
                    SET status = 'deleted', visibility = 0, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, normalized_id),
                )
                return {"removed": max(0, int(cursor.rowcount or 0))}

    def get_status(self) -> dict[str, int]:
        self.ensure_seed_imported()
        with self.store.connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM gallery_items GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["count"] or 0) for row in rows}


gallery_service = GalleryService()
