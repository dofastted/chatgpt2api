from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Iterator

from services.config import config


class SQLiteStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = Lock()
        self._initialized = False
        self.initialize()

    @staticmethod
    def now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            with self.connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS json_documents (
                        name TEXT PRIMARY KEY,
                        data TEXT NOT NULL,
                        imported_from TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS response_records (
                        response_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS image_conversations (
                        owner_id TEXT NOT NULL,
                        conversation_id TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (owner_id, conversation_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_image_conversations_owner_updated
                        ON image_conversations(owner_id, updated_at DESC);
                    CREATE TABLE IF NOT EXISTS app_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        level TEXT NOT NULL,
                        component TEXT NOT NULL,
                        message TEXT NOT NULL,
                        context TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_app_logs_created_at
                        ON app_logs(created_at DESC);
                    CREATE TABLE IF NOT EXISTS data_management_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS backup_records (
                        id TEXT PRIMARY KEY,
                        path TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        error TEXT,
                        s3_uploaded INTEGER NOT NULL DEFAULT 0,
                        s3_error TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_backup_records_created_at
                        ON backup_records(created_at DESC);
                    CREATE TABLE IF NOT EXISTS image_request_records (
                        request_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        auth_type TEXT NOT NULL,
                        user_key_id TEXT,
                        user_key_label TEXT,
                        auth_token_hash TEXT,
                        endpoint TEXT NOT NULL,
                        protocol TEXT NOT NULL,
                        model TEXT,
                        size TEXT,
                        n INTEGER NOT NULL DEFAULT 1,
                        stream INTEGER NOT NULL DEFAULT 0,
                        has_input_image INTEGER NOT NULL DEFAULT 0,
                        input_image_count INTEGER NOT NULL DEFAULT 0,
                        client_conversation_id TEXT,
                        response_id TEXT,
                        prompt_preview TEXT,
                        prompt_hash TEXT,
                        status TEXT NOT NULL,
                        accepted_at TEXT NOT NULL,
                        queued_at TEXT,
                        started_at TEXT,
                        running_at TEXT,
                        finished_at TEXT,
                        updated_at TEXT NOT NULL,
                        queue_wait_ms INTEGER,
                        assigning_ms INTEGER,
                        running_ms INTEGER,
                        total_ms INTEGER,
                        requested_count INTEGER,
                        succeeded_count INTEGER,
                        failed_count INTEGER,
                        unit_cost INTEGER,
                        charged_quota INTEGER,
                        remaining_quota INTEGER,
                        http_status INTEGER,
                        error_type TEXT,
                        error_message TEXT,
                        upstream_error TEXT,
                        account_token_hash TEXT,
                        account_type TEXT,
                        route TEXT,
                        attempt_count INTEGER,
                        fallback_used INTEGER NOT NULL DEFAULT 0,
                        metadata_json TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_image_request_records_created_at
                        ON image_request_records(created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_image_request_records_owner_created
                        ON image_request_records(owner_id, created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_image_request_records_status_created
                        ON image_request_records(status, created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_image_request_records_model_created
                        ON image_request_records(model, created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_image_request_records_endpoint_created
                        ON image_request_records(endpoint, created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_image_request_records_auth_type_created
                        ON image_request_records(auth_type, created_at DESC);
                    """
                )
            self._initialized = True

    def load_document(self, name: str, default: Any, import_file: Path | None = None) -> Any:
        with self._lock:
            with self.connect() as connection:
                row = connection.execute(
                    "SELECT data FROM json_documents WHERE name = ?",
                    (name,),
                ).fetchone()
                if row is not None:
                    try:
                        return json.loads(str(row["data"]))
                    except json.JSONDecodeError:
                        return default

                data = default
                imported_from = None
                if import_file is not None and import_file.exists():
                    try:
                        loaded = json.loads(import_file.read_text(encoding="utf-8"))
                        data = loaded
                        imported_from = str(import_file)
                    except (OSError, json.JSONDecodeError):
                        data = default
                now = self.now_text()
                connection.execute(
                    """
                    INSERT INTO json_documents (name, data, imported_from, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (name, json.dumps(data, ensure_ascii=False), imported_from, now, now),
                )
                return data

    def save_document(self, name: str, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        now = self.now_text()
        with self._lock:
            with self.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO json_documents (name, data, imported_from, created_at, updated_at)
                    VALUES (?, ?, NULL, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
                    """,
                    (name, payload, now, now),
                )

    def get_response(self, response_id: str) -> dict[str, object] | None:
        normalized_id = str(response_id or "").strip()
        if not normalized_id:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM response_records WHERE response_id = ?",
                (normalized_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload"]))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def set_response(self, response_id: str, payload: dict[str, object]) -> None:
        normalized_id = str(response_id or "").strip()
        if not normalized_id:
            return
        now = self.now_text()
        with self._lock:
            with self.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO response_records (response_id, payload, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(response_id) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = excluded.updated_at
                    """,
                    (normalized_id, json.dumps(payload, ensure_ascii=False), now, now),
                )

    def get_status(self) -> dict[str, Any]:
        with self.connect() as connection:
            tables = {}
            for table in (
                "json_documents",
                "response_records",
                "image_conversations",
                "app_logs",
                "backup_records",
                "image_request_records",
            ):
                row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
                tables[table] = int(row["count"] or 0) if row else 0
        return {
            "sqlite_path": str(self.db_path),
            "exists": self.db_path.exists(),
            "size_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
            "tables": tables,
        }


sqlite_store = SQLiteStore(config.sqlite_path)
