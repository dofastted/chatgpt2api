from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from services.account_service import AccountService


class AccountServiceImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="chatgpt2api-account-import-"))
        self.store_file = self.temp_dir / "accounts.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def make_service(self, items: list[dict] | None = None) -> AccountService:
        if items is not None:
            self.store_file.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        elif self.store_file.exists():
            self.store_file.unlink()
        return AccountService(self.store_file)

    def test_bare_json_import_marks_account_for_refresh_and_makes_it_selectable(self) -> None:
        service = self.make_service()

        result = service.add_account_items(
            [
                {
                    "access_token": " token-1 ",
                    "refresh_token": "refresh-1",
                    "email": "user@example.com",
                }
            ]
        )

        self.assertEqual(result["added"], 1)
        self.assertEqual(result["updated"], 0)
        account = service.get_account("token-1")
        self.assertIsNotNone(account)
        self.assertEqual(account["status"], "正常")
        self.assertEqual(account["quota"], 0)
        self.assertTrue(account["needs_refresh"])
        self.assertEqual(service.next_token(), "token-1")

        saved = json.loads(self.store_file.read_text(encoding="utf-8"))
        self.assertTrue(saved[0]["needs_refresh"])

    def test_reimport_resets_abnormal_runtime_state_when_source_json_has_only_token_data(self) -> None:
        service = self.make_service(
            [
                {
                    "access_token": "token-1",
                    "category": "普通",
                    "type": "Free",
                    "status": "异常",
                    "quota": 0,
                    "limits_progress": [],
                    "restore_at": None,
                }
            ]
        )

        result = service.add_account_items(
            [
                {
                    "access_token": "token-1",
                    "refresh_token": "refresh-1",
                }
            ]
        )

        self.assertEqual(result["added"], 0)
        self.assertEqual(result["updated"], 1)
        account = service.get_account("token-1")
        self.assertIsNotNone(account)
        self.assertEqual(account["status"], "正常")
        self.assertEqual(account["quota"], 0)
        self.assertTrue(account["needs_refresh"])
        self.assertEqual(service.next_token(), "token-1")

    def test_reimport_keeps_manual_disabled_state(self) -> None:
        service = self.make_service(
            [
                {
                    "access_token": "token-1",
                    "category": "普通",
                    "type": "Free",
                    "status": "禁用",
                    "quota": 0,
                    "limits_progress": [],
                }
            ]
        )

        service.add_account_items([{"access_token": "token-1", "refresh_token": "refresh-1"}])

        account = service.get_account("token-1")
        self.assertIsNotNone(account)
        self.assertEqual(account["status"], "禁用")
        self.assertTrue(account["needs_refresh"])
        with self.assertRaises(RuntimeError):
            service.next_token()

    def test_full_account_snapshot_import_preserves_known_runtime_fields(self) -> None:
        service = self.make_service()

        service.add_account_items(
            [
                {
                    "access_token": "token-1",
                    "category": "捐赠",
                    "type": "Plus",
                    "status": "正常",
                    "quota": 7,
                    "limits_progress": [
                        {
                            "feature_name": "image_gen",
                            "remaining": 7,
                            "reset_after": "2026-04-23T10:00:00+00:00",
                        }
                    ],
                    "restore_at": "2026-04-23T10:00:00+00:00",
                    "needs_refresh": False,
                }
            ]
        )

        account = service.get_account("token-1")
        self.assertIsNotNone(account)
        self.assertEqual(account["category"], "捐赠")
        self.assertEqual(account["type"], "Plus")
        self.assertEqual(account["quota"], 7)
        self.assertFalse(account["needs_refresh"])

    def test_failed_account_enters_cooldown_for_three_minutes(self) -> None:
        service = self.make_service(
            [
                {
                    "access_token": "token-1",
                    "category": "普通",
                    "type": "Plus",
                    "status": "正常",
                    "quota": 5,
                    "needs_refresh": False,
                }
            ]
        )

        account = service.mark_request_failure("token-1")
        self.assertIsNotNone(account)
        assert account is not None
        self.assertIsNotNone(account["cooldown_until"])
        with self.assertRaises(RuntimeError):
            service.next_token()

        updated = service.update_account("token-1", {"cooldown_until": "2000-01-01 00:00:00"})
        self.assertIsNotNone(updated)
        self.assertEqual(service.next_token(), "token-1")

    def test_single_account_slot_limit_is_two(self) -> None:
        service = self.make_service(
            [
                {
                    "access_token": "token-1",
                    "category": "普通",
                    "type": "Plus",
                    "status": "正常",
                    "quota": 5,
                    "needs_refresh": False,
                }
            ]
        )

        self.assertEqual(service.try_acquire_token_slot(), "token-1")
        self.assertEqual(service.try_acquire_token_slot(), "token-1")
        self.assertIsNone(service.try_acquire_token_slot())

        service.release_token_slot("token-1")
        self.assertEqual(service.try_acquire_token_slot(), "token-1")

    def test_list_refreshable_tokens_includes_limited_and_expired_cooldown(self) -> None:
        service = self.make_service(
            [
                {
                    "access_token": "limited-token",
                    "category": "普通",
                    "type": "Plus",
                    "status": "限流",
                    "quota": 0,
                    "needs_refresh": False,
                },
                {
                    "access_token": "cooldown-token",
                    "category": "普通",
                    "type": "Plus",
                    "status": "正常",
                    "quota": 3,
                    "cooldown_until": "2099-01-01 00:00:00",
                    "needs_refresh": False,
                },
            ]
        )
        service._accounts[1]["cooldown_until"] = "2000-01-01 00:00:00"

        self.assertEqual(
            service.list_refreshable_tokens(),
            ["limited-token", "cooldown-token"],
        )


if __name__ == "__main__":
    unittest.main()
