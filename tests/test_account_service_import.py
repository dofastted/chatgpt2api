from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
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

    def test_bare_json_import_marks_account_for_manual_refresh_and_keeps_it_unavailable(self) -> None:
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
        public_item = result["items"][0]
        self.assertEqual(public_item["quota"], 0)
        self.assertFalse(public_item["quotaKnown"])
        self.assertTrue(public_item["needsRefresh"])
        with self.assertRaises(RuntimeError):
            service.next_token()

        saved = json.loads(self.store_file.read_text(encoding="utf-8"))
        self.assertTrue(saved[0]["needs_refresh"])

    def test_create_accounts_result_imports_five_cpa_accounts_and_disables_only_401(self) -> None:
        from services.api import AccountCreateRequest, create_accounts_result

        service = self.make_service()
        accounts = [
            {
                "access_token": f"access-{index}",
                "refresh_token": f"refresh-{index}",
                "id_token": f"id-{index}",
                "email": f"user{index}@example.com",
                "plan_type": "plus",
            }
            for index in range(1, 6)
        ]

        def fetch_remote_info(access_token: str) -> dict:
            if access_token == "access-4":
                raise RuntimeError("/backend-api/me failed: HTTP 401")
            index = access_token.rsplit("-", 1)[-1]
            return {
                "email": f"user{index}@example.com",
                "type": "Plus",
                "status": "正常",
                "quota": 120,
                "needs_refresh": False,
            }

        with (
            patch("services.api.account_service", service),
            patch.object(service, "fetch_remote_info", side_effect=fetch_remote_info),
        ):
            result = create_accounts_result(AccountCreateRequest(accounts=accounts))

        self.assertEqual(result["added"], 5)
        self.assertEqual(result["refreshed"], 4)
        self.assertEqual(result["disabled"], 1)
        self.assertEqual(result["available"], 4)
        self.assertEqual(len(result["errors"]), 1)
        self.assertTrue(result["errors"][0]["disabled"])
        self.assertEqual(service.get_account("access-4")["status"], "禁用")
        self.assertEqual(service.get_account("access-4")["disabled_reason"], "credential_invalid")
        self.assertEqual(service.pool_summary()["ready"], 4)

    def test_refresh_network_failure_records_error_without_disabling_account(self) -> None:
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

        with patch.object(service, "fetch_remote_info", side_effect=RuntimeError("proxy connect failed: HTTP 503")):
            result = service.refresh_accounts(["token-1"])

        account = service.get_account("token-1")
        self.assertEqual(result["refreshed"], 0)
        self.assertEqual(result["disabled"], 0)
        self.assertFalse(result["errors"][0]["disabled"])
        self.assertEqual(account["status"], "正常")
        self.assertEqual(account["quota"], 5)
        self.assertIn("proxy connect failed", account["last_error"])
        self.assertEqual(service.next_token(), "token-1")

    def test_successful_refresh_restores_previously_disabled_account(self) -> None:
        service = self.make_service(
            [
                {
                    "access_token": "token-1",
                    "category": "普通",
                    "type": "Plus",
                    "status": "禁用",
                    "quota": 0,
                    "needs_refresh": False,
                    "disabled_reason": "credential_invalid",
                    "last_error": "账号凭据已失效",
                }
            ]
        )

        with patch.object(
            service,
            "fetch_remote_info",
            return_value={
                "type": "Plus",
                "status": "正常",
                "quota": 120,
                "needs_refresh": False,
                "disabled_reason": None,
                "last_error": None,
                "last_error_at": None,
            },
        ):
            result = service.refresh_accounts(["token-1"])

        account = service.get_account("token-1")
        self.assertEqual(result["refreshed"], 1)
        self.assertEqual(account["status"], "正常")
        self.assertEqual(account["quota"], 120)
        self.assertIsNone(account["disabled_reason"])
        self.assertIsNone(account["last_error"])
        self.assertEqual(service.next_token(), "token-1")

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
        with self.assertRaises(RuntimeError):
            service.next_token()

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
        public_item = service.list_accounts()[0]
        self.assertEqual(public_item["quota"], 7)
        self.assertTrue(public_item["quotaKnown"])

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

    def test_single_account_slot_limit_is_one(self) -> None:
        service = self.make_service(
            [
                {
                    "access_token": "token-1",
                    "category": "普通",
                    "type": "Plus",
                    "status": "正常",
                    "quota": 5,
                    "needs_refresh": False,
                },
                {
                    "access_token": "token-2",
                    "category": "普通",
                    "type": "Plus",
                    "status": "正常",
                    "quota": 5,
                    "needs_refresh": False,
                },
            ]
        )

        first_token = service.try_acquire_token_slot()
        second_token = service.try_acquire_token_slot()
        self.assertEqual({first_token, second_token}, {"token-1", "token-2"})
        self.assertIsNone(service.try_acquire_token_slot())
        self.assertIsNone(service.acquire_token_slot(timeout_seconds=0))

        assert first_token is not None
        service.release_token_slot(first_token)
        self.assertEqual(service.try_acquire_token_slot(), first_token)

    def test_input_image_token_slot_prefers_recent_successful_accounts(self) -> None:
        service = self.make_service(
            [
                {
                    "access_token": "token-1",
                    "category": "普通",
                    "type": "Plus",
                    "status": "正常",
                    "quota": 5,
                    "input_image_success": 0,
                    "input_image_fail": 2,
                    "needs_refresh": False,
                },
                {
                    "access_token": "token-2",
                    "category": "普通",
                    "type": "Plus",
                    "status": "正常",
                    "quota": 5,
                    "input_image_success": 3,
                    "input_image_fail": 0,
                    "last_input_image_success_at": "2026-04-26 10:00:00",
                    "needs_refresh": False,
                },
            ]
        )

        self.assertEqual(service.try_acquire_token_slot(prefer_input_image=True), "token-2")

    def test_mark_image_result_tracks_input_image_stats(self) -> None:
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

        success = service.mark_image_result("token-1", success=True, input_image=True)
        self.assertIsNotNone(success)
        assert success is not None
        self.assertEqual(success["input_image_success"], 1)
        self.assertEqual(success["input_image_fail"], 0)
        self.assertIsNotNone(success["last_input_image_used_at"])
        self.assertIsNotNone(success["last_input_image_success_at"])

        failed = service.mark_image_result("token-1", success=False, input_image=True)
        self.assertIsNotNone(failed)
        assert failed is not None
        self.assertEqual(failed["input_image_success"], 1)
        self.assertEqual(failed["input_image_fail"], 1)

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
