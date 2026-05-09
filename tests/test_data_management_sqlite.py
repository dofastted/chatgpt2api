from __future__ import annotations

import json
import importlib.util
import os
import sqlite3
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from services import api
from services.account_service import AccountService
from services import data_management_service as data_management_module
from services.data_management_service import DataManagementService, data_management_service
from services.sqlite_store import SQLiteStore, sqlite_store
from services.uploaded_image_service import UploadedImageService


def load_pricing_update_script():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "update_user_key_pricing.py"
    spec = importlib.util.spec_from_file_location("update_user_key_pricing", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeThread:
    def join(self, timeout: float | None = None) -> None:
        return None


class SQLiteDataManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="chatgpt2api-sqlite-tests-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_json_import_uses_sqlite_document_as_primary_store(self) -> None:
        store_file = self.temp_dir / "accounts.json"
        store_file.write_text(
            json.dumps(
                [
                    {
                        "access_token": "token-from-json",
                        "status": "正常",
                        "quota": 3,
                    }
                ]
            ),
            encoding="utf-8",
        )

        service = AccountService(store_file)

        self.assertEqual(service.next_token(), "token-from-json")
        store_file.write_text("[]", encoding="utf-8")
        second_service = AccountService(store_file)
        self.assertEqual(second_service.next_token(), "token-from-json")

    def test_response_store_reads_sqlite_after_memory_clear(self) -> None:
        api.response_store_set("resp_sqlite_test", {"id": "resp_sqlite_test", "ok": True})
        with api.RESPONSES_STORE_LOCK:
            api.RESPONSES_STORE.clear()

        self.assertEqual(api.response_store_get("resp_sqlite_test"), {"id": "resp_sqlite_test", "ok": True})

    def test_backup_prune_removes_oldest_files_over_limit(self) -> None:
        old_backup_dir = data_management_service.backup_dir
        data_management_service.backup_dir = self.temp_dir / "backups"
        data_management_service.backup_dir.mkdir(parents=True, exist_ok=True)
        old_file = data_management_service.backup_dir / "old.tar.gz"
        new_file = data_management_service.backup_dir / "new.tar.gz"
        old_file.write_bytes(b"a" * 10)
        new_file.write_bytes(b"b" * 10)
        os.utime(old_file, (1, 1))
        os.utime(new_file, (2, 2))
        try:
            data_management_service.prune_backups(max_bytes=10)
            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())
        finally:
            data_management_service.backup_dir = old_backup_dir

    def test_data_management_admin_routes_require_admin_key(self) -> None:
        patchers = [
            patch.object(api, "start_limited_account_watcher", side_effect=lambda stop_event: FakeThread()),
            patch.object(api, "start_backup_scheduler", side_effect=lambda stop_event: FakeThread()),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        client = TestClient(api.create_app())

        user_response = client.get(
            "/api/data-management/status",
            headers={"Authorization": "Bearer test-auth-key"},
        )
        self.assertEqual(user_response.status_code, 403)

        admin_response = client.get(
            "/api/data-management/status",
            headers={"Authorization": "Bearer test-admin-key"},
        )
        self.assertEqual(admin_response.status_code, 200)
        self.assertEqual(admin_response.json()["sqlite_path"], str(sqlite_store.db_path))

    def test_image_conversation_summary_reads_summary_payload_without_full_payload(self) -> None:
        auth_token = "summary-test-key"
        owner_id = UploadedImageService.build_owner_id(auth_token)
        temp_store = SQLiteStore(self.temp_dir / "summary.sqlite3")
        sqlite_patcher = patch.object(data_management_module, "sqlite_store", temp_store)
        sqlite_patcher.start()
        self.addCleanup(sqlite_patcher.stop)
        service = DataManagementService()
        conversation_id = "conv_summary_test"
        summary_payload = {
            "id": conversation_id,
            "clientConversationId": conversation_id,
            "title": "轻量摘要",
            "createdAt": "2026-05-09 00:00:00",
            "turns": [],
            "turnCount": 0,
            "isSummary": True,
        }
        with temp_store.connect() as connection:
            connection.execute(
                """
                INSERT INTO image_conversations (
                    owner_id, conversation_id, payload, summary_payload, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, '2026-05-09 00:00:00', '2026-05-09 00:00:00')
                ON CONFLICT(owner_id, conversation_id) DO UPDATE SET
                    payload = excluded.payload,
                    summary_payload = excluded.summary_payload,
                    updated_at = excluded.updated_at
                """,
                (
                    owner_id,
                    conversation_id,
                    "{not-json",
                    json.dumps(summary_payload, ensure_ascii=False),
                ),
            )

        self.assertEqual(service.list_conversations(auth_token, summary=True), [summary_payload])
        self.assertEqual(service.list_conversations(auth_token, summary=False), [])

    def test_pricing_update_script_overwrites_sqlite_and_json(self) -> None:
        script = load_pricing_update_script()
        db_path = self.temp_dir / "chatgpt2api.sqlite3"
        json_path = self.temp_dir / "user_keys.json"
        old_items = [{"key": "uk_test", "quota": 30, "pricing": {"gpt-image-2-4K": 2}}]
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                """
                CREATE TABLE json_documents (
                    name TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    imported_from TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO json_documents (name, data, imported_from, created_at, updated_at)
                VALUES (?, ?, NULL, 'now', 'now')
                """,
                ("user_keys:/app/data/user_keys.json", json.dumps(old_items),),
            )
        json_path.write_text(json.dumps(old_items), encoding="utf-8")

        sqlite_documents, sqlite_changed = script.update_sqlite(db_path, dry_run=False)
        json_exists, json_changed = script.update_json(json_path, dry_run=False)

        self.assertEqual(sqlite_documents, 1)
        self.assertEqual(sqlite_changed, 1)
        self.assertTrue(json_exists)
        self.assertEqual(json_changed, 1)
        with sqlite3.connect(db_path) as connection:
            row = connection.execute("SELECT data FROM json_documents").fetchone()
        sqlite_items = json.loads(row[0])
        json_items = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(sqlite_items[0]["pricing"], script.DEFAULT_PRICING)
        self.assertEqual(json_items[0]["pricing"], script.DEFAULT_PRICING)


if __name__ == "__main__":
    unittest.main()
