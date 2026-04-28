from __future__ import annotations

import json
import tarfile
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any

from services.config import DATA_DIR, config
from services.sqlite_store import sqlite_store
from services.uploaded_image_service import UploadedImageService


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


class DataManagementService:
    SETTINGS_DOCUMENT_NAME = "data_management_settings"

    def __init__(self) -> None:
        self.backup_dir = config.backup_dir
        self.uploaded_images_dir = DATA_DIR / "uploaded_images"
        self.generated_images_dir = DATA_DIR / "generated_images"

    def _default_settings(self) -> dict[str, Any]:
        return {
            "backup_enabled": bool(config.backup_interval_minutes > 0),
            "backup_interval_minutes": max(0, int(config.backup_interval_minutes or 0)),
            "backup_max_bytes": max(1, int(config.backup_max_bytes or 500 * 1024 * 1024)),
            "save_image_conversations": True,
            "save_logs": True,
            "s3": {
                "enabled": False,
                "endpoint": "",
                "region": "",
                "bucket": "",
                "access_key_id": "",
                "secret_access_key": "",
                "prefix": "",
                "force_path_style": True,
                "use_ssl": True,
            },
        }

    def _normalize_settings(self, payload: Any) -> dict[str, Any]:
        current = self._default_settings()
        if isinstance(payload, dict):
            current.update({key: value for key, value in payload.items() if key != "s3"})
            s3_payload = payload.get("s3")
            if isinstance(s3_payload, dict):
                current["s3"].update(s3_payload)
        current["backup_enabled"] = bool(current.get("backup_enabled"))
        current["backup_interval_minutes"] = max(0, int(current.get("backup_interval_minutes") or 0))
        current["backup_max_bytes"] = max(1, int(current.get("backup_max_bytes") or 1))
        current["save_image_conversations"] = bool(current.get("save_image_conversations"))
        current["save_logs"] = bool(current.get("save_logs"))
        s3 = current["s3"]
        s3["enabled"] = bool(s3.get("enabled"))
        s3["endpoint"] = _clean_text(s3.get("endpoint"))
        s3["region"] = _clean_text(s3.get("region"))
        s3["bucket"] = _clean_text(s3.get("bucket"))
        s3["access_key_id"] = _clean_text(s3.get("access_key_id"))
        s3["secret_access_key"] = _clean_text(s3.get("secret_access_key"))
        s3["prefix"] = _clean_text(s3.get("prefix")).strip("/")
        s3["force_path_style"] = bool(s3.get("force_path_style"))
        s3["use_ssl"] = bool(s3.get("use_ssl", True))
        return current

    def get_settings(self, *, masked: bool = True) -> dict[str, Any]:
        settings = self._normalize_settings(
            sqlite_store.load_document(self.SETTINGS_DOCUMENT_NAME, self._default_settings())
        )
        if masked:
            settings = json.loads(json.dumps(settings, ensure_ascii=False))
            secret = _clean_text(settings.get("s3", {}).get("secret_access_key"))
            if secret:
                settings["s3"]["secret_access_key"] = "********"
        return settings

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_settings(masked=False)
        next_payload = dict(current)
        for key, value in payload.items():
            if key == "s3" and isinstance(value, dict):
                s3 = dict(current.get("s3") or {})
                for s3_key, s3_value in value.items():
                    if s3_key == "secret_access_key" and _clean_text(s3_value) == "********":
                        continue
                    s3[s3_key] = s3_value
                next_payload["s3"] = s3
            elif key in current:
                next_payload[key] = value
        settings = self._normalize_settings(next_payload)
        sqlite_store.save_document(self.SETTINGS_DOCUMENT_NAME, settings)
        self.log("info", "data-management", "settings updated")
        return self.get_settings(masked=True)

    def log(self, level: str, component: str, message: str, context: dict[str, Any] | None = None) -> None:
        try:
            settings = self.get_settings(masked=False)
            if not settings.get("save_logs", True):
                return
            with sqlite_store.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO app_logs (created_at, level, component, message, context)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        _now_text(),
                        _clean_text(level).lower() or "info",
                        _clean_text(component) or "app",
                        _clean_text(message),
                        json.dumps(context or {}, ensure_ascii=False),
                    ),
                )
        except Exception:
            return

    def list_logs(
        self,
        *,
        limit: int = 100,
        level: str | None = None,
        component: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_limit = max(1, min(500, int(limit or 100)))
        filters: list[str] = []
        params: list[Any] = []
        if _clean_text(level):
            filters.append("level = ?")
            params.append(_clean_text(level).lower())
        if _clean_text(component):
            filters.append("component = ?")
            params.append(_clean_text(component))
        if _clean_text(since):
            filters.append("created_at >= ?")
            params.append(_clean_text(since))
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with sqlite_store.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, created_at, level, component, message, context
                FROM app_logs
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                [*params, normalized_limit],
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                context_payload = json.loads(str(row["context"] or "{}"))
            except json.JSONDecodeError:
                context_payload = {}
            items.append(
                {
                    "id": int(row["id"]),
                    "created_at": row["created_at"],
                    "level": row["level"],
                    "component": row["component"],
                    "message": row["message"],
                    "context": context_payload,
                }
            )
        return items

    def get_status(self) -> dict[str, Any]:
        settings = self.get_settings(masked=True)
        backup_records = self.list_backups(limit=20)
        backup_size = self._backup_dir_size()
        return {
            **sqlite_store.get_status(),
            "backup_dir": str(self.backup_dir),
            "backup_size_bytes": backup_size,
            "backup_max_bytes": settings.get("backup_max_bytes"),
            "backup_count": len(backup_records),
            "latest_backup": backup_records[0] if backup_records else None,
            "settings": settings,
        }

    def _backup_dir_size(self) -> int:
        if not self.backup_dir.exists():
            return 0
        return sum(path.stat().st_size for path in self.backup_dir.glob("*") if path.is_file())

    def _copy_sqlite_snapshot(self, destination: Path) -> None:
        with sqlite_store.connect() as source_connection:
            target_connection = None
            try:
                import sqlite3

                target_connection = sqlite3.connect(destination)
                source_connection.backup(target_connection)
                target_connection.commit()
            finally:
                if target_connection is not None:
                    target_connection.close()

    def create_backup(self, *, reason: str = "manual") -> dict[str, Any]:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup_id = f"backup_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        backup_path = self.backup_dir / f"{backup_id}.tar.gz"
        status = "success"
        error = None
        s3_uploaded = False
        s3_error = None
        try:
            with tempfile.TemporaryDirectory() as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                sqlite_copy = temp_dir / "chatgpt2api.sqlite3"
                self._copy_sqlite_snapshot(sqlite_copy)
                with tarfile.open(backup_path, "w:gz") as archive:
                    archive.add(sqlite_copy, arcname="chatgpt2api.sqlite3")
                    for directory, arcname in (
                        (self.uploaded_images_dir, "uploaded_images"),
                        (self.generated_images_dir, "generated_images"),
                    ):
                        if directory.exists():
                            archive.add(directory, arcname=arcname)
            settings = self.get_settings(masked=False)
            if settings.get("s3", {}).get("enabled"):
                try:
                    self.upload_backup_to_s3(backup_path, settings["s3"])
                    s3_uploaded = True
                except Exception as exc:
                    s3_error = str(exc)
                    status = "success"
            self.prune_backups(max_bytes=int(settings.get("backup_max_bytes") or config.backup_max_bytes))
        except Exception as exc:
            status = "failed"
            error = str(exc)
        record = {
            "id": backup_id,
            "path": str(backup_path),
            "size_bytes": backup_path.stat().st_size if backup_path.exists() else 0,
            "status": status,
            "error": error,
            "s3_uploaded": s3_uploaded,
            "s3_error": s3_error,
            "created_at": _now_text(),
            "reason": reason,
        }
        self._insert_backup_record(record)
        self.log("info" if status == "success" else "error", "backup", f"backup {status}", record)
        return record

    def _insert_backup_record(self, record: dict[str, Any]) -> None:
        with sqlite_store.connect() as connection:
            connection.execute(
                """
                INSERT INTO backup_records
                    (id, path, size_bytes, status, error, s3_uploaded, s3_error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["path"],
                    int(record.get("size_bytes") or 0),
                    record["status"],
                    record.get("error"),
                    1 if record.get("s3_uploaded") else 0,
                    record.get("s3_error"),
                    record["created_at"],
                ),
            )

    def list_backups(self, *, limit: int = 100) -> list[dict[str, Any]]:
        normalized_limit = max(1, min(500, int(limit or 100)))
        with sqlite_store.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, path, size_bytes, status, error, s3_uploaded, s3_error, created_at
                FROM backup_records
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (normalized_limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "path": row["path"],
                "size_bytes": int(row["size_bytes"] or 0),
                "status": row["status"],
                "error": row["error"],
                "s3_uploaded": bool(row["s3_uploaded"]),
                "s3_error": row["s3_error"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def prune_backups(self, *, max_bytes: int) -> None:
        if not self.backup_dir.exists():
            return
        files = sorted(
            [path for path in self.backup_dir.glob("*.tar.gz") if path.is_file()],
            key=lambda path: path.stat().st_mtime,
        )
        total = sum(path.stat().st_size for path in files)
        for path in files:
            if total <= max_bytes:
                break
            size = path.stat().st_size
            try:
                path.unlink()
                total -= size
            except OSError:
                continue

    def _build_s3_client(self, s3_config: dict[str, Any]):
        try:
            import boto3
            from botocore.config import Config
        except Exception as exc:
            raise RuntimeError("boto3 is not installed") from exc
        bucket = _clean_text(s3_config.get("bucket"))
        if not bucket:
            raise ValueError("s3 bucket is required")
        endpoint = _clean_text(s3_config.get("endpoint")) or None
        region = _clean_text(s3_config.get("region")) or None
        access_key = _clean_text(s3_config.get("access_key_id")) or None
        secret_key = _clean_text(s3_config.get("secret_access_key")) or None
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            use_ssl=bool(s3_config.get("use_ssl", True)),
            config=Config(s3={"addressing_style": "path" if s3_config.get("force_path_style", True) else "auto"}),
        )

    def test_s3(self, s3_config: dict[str, Any]) -> dict[str, Any]:
        merged = dict(self.get_settings(masked=False).get("s3") or {})
        merged.update(s3_config or {})
        client = self._build_s3_client(merged)
        bucket = _clean_text(merged.get("bucket"))
        client.head_bucket(Bucket=bucket)
        return {"ok": True, "bucket": bucket}

    def upload_backup_to_s3(self, backup_path: Path, s3_config: dict[str, Any]) -> None:
        client = self._build_s3_client(s3_config)
        bucket = _clean_text(s3_config.get("bucket"))
        prefix = _clean_text(s3_config.get("prefix")).strip("/")
        key = f"{prefix}/{backup_path.name}" if prefix else backup_path.name
        client.upload_file(str(backup_path), bucket, key)

    def _build_conversation_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        turns = payload.get("turns")
        if isinstance(turns, list) and turns:
            valid_turns = [turn for turn in turns if isinstance(turn, dict)]
            latest_turn = valid_turns[-1] if valid_turns else {}
            turn_count = len(valid_turns)
        else:
            latest_turn = payload
            turn_count = 1
        conversation_id = _clean_text(payload.get("id"))
        latest_summary = {
            "id": _clean_text(latest_turn.get("id")) or f"{conversation_id or 'conversation'}-turn-1",
            "prompt": _clean_text(latest_turn.get("prompt")),
            "model": _clean_text(latest_turn.get("model")),
            "count": latest_turn.get("count"),
            "size": _clean_text(latest_turn.get("size")),
            "createdAt": _clean_text(latest_turn.get("createdAt")),
            "status": _clean_text(latest_turn.get("status")),
            "error": _clean_text(latest_turn.get("error")),
            "queueRequestId": _clean_text(latest_turn.get("queueRequestId")),
            "requestStartedAt": _clean_text(latest_turn.get("requestStartedAt")),
            "requestFinishedAt": _clean_text(latest_turn.get("requestFinishedAt")),
            "lastError": _clean_text(latest_turn.get("lastError")),
            "responseId": _clean_text(latest_turn.get("responseId")),
            "images": [],
        }
        return {
            "id": conversation_id,
            "clientConversationId": _clean_text(payload.get("clientConversationId") or conversation_id),
            "title": _clean_text(payload.get("title")),
            "createdAt": _clean_text(payload.get("createdAt")),
            "turns": [latest_summary],
            "prompt": latest_summary.get("prompt"),
            "model": latest_summary.get("model"),
            "count": latest_summary.get("count"),
            "size": latest_summary.get("size"),
            "status": latest_summary.get("status"),
            "queueRequestId": latest_summary.get("queueRequestId"),
            "requestStartedAt": latest_summary.get("requestStartedAt"),
            "requestFinishedAt": latest_summary.get("requestFinishedAt"),
            "lastError": latest_summary.get("lastError"),
            "error": latest_summary.get("error"),
            "responseId": latest_summary.get("responseId"),
            "turnCount": turn_count,
            "isSummary": True,
        }

    def list_conversations(self, auth_token: str, *, summary: bool = False) -> list[dict[str, Any]]:
        owner_id = UploadedImageService.build_owner_id(auth_token)
        if not owner_id:
            return []
        with sqlite_store.connect() as connection:
            rows = connection.execute(
                """
                SELECT conversation_id, payload
                FROM image_conversations
                WHERE owner_id = ?
                ORDER BY updated_at DESC
                """,
                (owner_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload"]))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                items.append(self._build_conversation_summary(payload) if summary else payload)
        return items

    def get_conversation(self, auth_token: str, conversation_id: str) -> dict[str, Any] | None:
        owner_id = UploadedImageService.build_owner_id(auth_token)
        normalized_id = _clean_text(conversation_id)
        if not owner_id or not normalized_id:
            return None
        with sqlite_store.connect() as connection:
            row = connection.execute(
                """
                SELECT payload
                FROM image_conversations
                WHERE owner_id = ? AND conversation_id = ?
                """,
                (owner_id, normalized_id),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload"]))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def upsert_conversation(self, auth_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.get_settings(masked=False)
        if not settings.get("save_image_conversations", True):
            raise ValueError("image conversation storage is disabled")
        owner_id = UploadedImageService.build_owner_id(auth_token)
        conversation_id = _clean_text(payload.get("id") or payload.get("conversation_id"))
        if not owner_id or not conversation_id:
            raise ValueError("conversation id is required")
        now = _now_text()
        with sqlite_store.connect() as connection:
            current = connection.execute(
                """
                SELECT created_at FROM image_conversations
                WHERE owner_id = ? AND conversation_id = ?
                """,
                (owner_id, conversation_id),
            ).fetchone()
            created_at = str(current["created_at"]) if current else now
            connection.execute(
                """
                INSERT INTO image_conversations (owner_id, conversation_id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner_id, conversation_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (owner_id, conversation_id, json.dumps(payload, ensure_ascii=False), created_at, now),
            )
        return payload

    def delete_conversation(self, auth_token: str, conversation_id: str) -> dict[str, Any]:
        owner_id = UploadedImageService.build_owner_id(auth_token)
        normalized_id = _clean_text(conversation_id)
        if not owner_id or not normalized_id:
            return {"removed": 0}
        with sqlite_store.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM image_conversations WHERE owner_id = ? AND conversation_id = ?",
                (owner_id, normalized_id),
            )
            return {"removed": int(cursor.rowcount or 0)}


data_management_service = DataManagementService()


def start_backup_scheduler(stop_event: Event) -> Thread:
    def worker() -> None:
        while not stop_event.is_set():
            settings = data_management_service.get_settings(masked=False)
            interval = int(settings.get("backup_interval_minutes") or 0)
            if settings.get("backup_enabled") and interval > 0:
                stop_event.wait(interval * 60)
                if stop_event.is_set():
                    break
                data_management_service.create_backup(reason="scheduled")
            else:
                stop_event.wait(60)

    thread = Thread(target=worker, name="data-backup-scheduler", daemon=True)
    thread.start()
    return thread
