from __future__ import annotations
import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
import base64
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


TEST_ROOT = Path(tempfile.mkdtemp(prefix="chatgpt2api-tests-config-"))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")
os.environ.setdefault("CHATGPT2API_ADMIN_AUTH_KEY", "test-admin-key")
os.environ.setdefault("CHATGPT2API_USER_KEYS_FILE", str(TEST_ROOT / "bootstrap-user-keys.json"))
sys.modules.setdefault("pybase64", base64)

from services import api  # noqa: E402
from services.image_service import ImageGenerationError  # noqa: E402
from services.uploaded_image_service import uploaded_image_service  # noqa: E402
from services.user_key_service import UserKeyService  # noqa: E402


class FakeThread:
    def join(self, timeout: float | None = None) -> None:
        return None


class FakeAccountService:
    DONATION_CATEGORY = "捐赠"

    def __init__(self, items: list[dict] | None = None):
        self.items = items or [{"quota": 9, "status": "正常"}]

    def list_limited_tokens(self) -> list[str]:
        return []

    def list_accounts(self) -> list[dict]:
        return list(self.items)

    def list_tokens(self) -> list[str]:
        return [str(item.get("access_token") or "").strip() for item in self.items if str(item.get("access_token") or "").strip()]

    def add_account_items(self, items: list[dict], category: str = "普通") -> dict:
        added_tokens = [str(item.get("access_token") or "").strip() for item in items if str(item.get("access_token") or "").strip()]
        return {
            "items": list(self.items),
            "added": len(added_tokens),
            "updated": 0,
            "skipped": 0,
            "added_tokens": added_tokens,
            "category": category,
        }

    def add_accounts(self, tokens: list[str], category: str = "普通") -> dict:
        added_tokens = [str(token or "").strip() for token in tokens if str(token or "").strip()]
        return {
            "items": list(self.items),
            "added": len(added_tokens),
            "updated": 0,
            "skipped": 0,
            "added_tokens": added_tokens,
            "category": category,
        }

    def refresh_accounts(self, access_tokens: list[str]) -> dict:
        refreshed_items = []
        for token in access_tokens:
            normalized = str(token or "").strip()
            if not normalized:
                continue
            refreshed_items.append(
                {
                    "access_token": normalized,
                    "type": "Free" if "free" in normalized.lower() else "Plus",
                    "status": "正常",
                    "quota": 9,
                }
            )
        return {
            "items": refreshed_items,
            "refreshed": len(refreshed_items),
            "errors": [],
        }


class FakeBackendService:
    response = {
        "created": 123,
        "data": [{"b64_json": "ZmFrZQ==", "mime_type": "image/png"}],
    }
    error: Exception | None = None
    last_call: dict[str, object] | None = None

    def __init__(self, account_service: FakeAccountService):
        self.account_service = account_service

    def generate_with_pool(
        self,
        prompt: str,
        model: str,
        n: int,
        input_images: list[dict[str, str]] | None = None,
        queue_request_id: str | None = None,
        size: str | None = None,
    ) -> dict:
        del queue_request_id
        self.__class__.last_call = {
            "prompt": prompt,
            "model": model,
            "n": n,
            "input_images": [dict(item) for item in list(input_images or [])],
            "size": size,
        }
        if self.error is not None:
            raise self.error
        return {
            "created": self.response["created"],
            "data": [dict(item) for item in self.response["data"]],
        }


class UserKeyPricingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="chatgpt2api-tests-"))
        self.user_keys_file = self.temp_dir / "user_keys.json"
        self.redeem_codes_file = self.temp_dir / "redeem_codes.json"
        self.upload_store_file = self.temp_dir / "uploaded_images.json"
        self.upload_files_dir = self.temp_dir / "uploaded_images"
        api.user_key_service.store_file = self.user_keys_file
        api.user_key_service._user_keys = []
        api.redeem_code_service.store_file = self.redeem_codes_file
        api.redeem_code_service._items = []
        uploaded_image_service.store_file = self.upload_store_file
        uploaded_image_service.files_dir = self.upload_files_dir
        uploaded_image_service._items = []
        with api.RESPONSES_STORE_LOCK:
            api.RESPONSES_STORE.clear()
        api.clear_image_request_timestamps()
        if self.user_keys_file.exists():
            self.user_keys_file.unlink()
        FakeBackendService.error = None
        FakeBackendService.last_call = None
        FakeBackendService.response = {
            "created": 123,
            "data": [{"b64_json": "ZmFrZQ==", "mime_type": "image/png"}],
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def make_client(self, account_items: list[dict] | None = None) -> TestClient:
        patchers = [
            patch.object(api, "account_service", FakeAccountService(account_items)),
            patch.object(api, "BackendService", FakeBackendService),
            patch.object(api, "start_limited_account_watcher", side_effect=lambda stop_event: FakeThread()),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        return TestClient(api.create_app())

    def collect_sse_events(self, content: str) -> list[tuple[str | None, object]]:
        events: list[tuple[str | None, object]] = []
        current_event: str | None = None
        current_data_lines: list[str] = []

        for line in content.splitlines():
            if line == "":
                if current_event is not None or current_data_lines:
                    payload_text = "\n".join(current_data_lines)
                    payload = payload_text if payload_text == "[DONE]" else json.loads(payload_text)
                    events.append((current_event, payload))
                current_event = None
                current_data_lines = []
                continue
            if line.startswith("event:"):
                current_event = line[6:].strip()
                continue
            if line.startswith("data:"):
                current_data_lines.append(line[5:].strip())

        if current_event is not None or current_data_lines:
            payload_text = "\n".join(current_data_lines)
            payload = payload_text if payload_text == "[DONE]" else json.loads(payload_text)
            events.append((current_event, payload))

        return events

    def test_legacy_user_key_uses_default_pricing(self) -> None:
        legacy_file = self.temp_dir / "legacy-user-keys.json"
        legacy_file.write_text(
            json.dumps(
                [
                    {
                        "key": "legacy-key",
                        "quota": 12,
                        "status": "启用",
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        service = UserKeyService(legacy_file)

        item = service.get_user_key("legacy-key")
        self.assertIsNotNone(item)
        self.assertEqual(item["pricing"], {"gpt-image-1": 0, "gpt-image-2": 2})
        self.assertEqual(service.list_public_user_keys()[0]["pricing"], {"gpt-image-1": 0, "gpt-image-2": 2})

    def test_user_key_session_quota_and_billing_use_custom_pricing(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=30,
            prefix="uk",
            pricing={"gpt-image-1": 2, "gpt-image-2": 7},
        )
        user_key = created["created_items"][0]["key"]

        with self.make_client() as client:
            session_response = client.get("/auth/session", headers={"Authorization": f"Bearer {user_key}"})
            self.assertEqual(session_response.status_code, 200)
            self.assertEqual(
                session_response.json()["pricing"],
                {"gpt-image-1": 2, "gpt-image-2": 7},
            )

            quota_response = client.get("/api/quota", headers={"Authorization": f"Bearer {user_key}"})
            self.assertEqual(quota_response.status_code, 200)
            self.assertEqual(quota_response.json()["remaining_quota"], 30)
            self.assertEqual(
                quota_response.json()["pricing"],
                {"gpt-image-1": 2, "gpt-image-2": 7},
            )

            image_response = client.post(
                "/v1/images/generations",
                headers={"Authorization": f"Bearer {user_key}"},
                json={"prompt": "a test image", "model": "gpt-image-2", "n": 2},
            )
            self.assertEqual(image_response.status_code, 200)
            body = image_response.json()
            self.assertEqual(body["billing"]["requested_model"], "gpt-image-2")
            self.assertEqual(body["billing"]["unit_cost"], 7)
            self.assertEqual(body["billing"]["charged_quota"], 14)
            self.assertEqual(body["billing"]["remaining_quota"], 16)

        current_item = api.user_key_service.get_user_key(user_key)
        self.assertIsNotNone(current_item)
        self.assertEqual(current_item["quota"], 16)
        self.assertIsNotNone(current_item["last_used_at"])

    def test_image_generation_refunds_quota_when_upstream_fails(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=15,
            prefix="uk",
            pricing={"gpt-image-1": 3, "gpt-image-2": 6},
        )
        user_key = created["created_items"][0]["key"]
        FakeBackendService.error = ImageGenerationError("upstream failed")

        with self.make_client() as client:
            response = client.post(
                "/v1/images/generations",
                headers={"Authorization": f"Bearer {user_key}"},
                json={"prompt": "a failed image", "model": "gpt-image-2", "n": 2},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"]["error"], "upstream failed")
        current_item = api.user_key_service.get_user_key(user_key)
        self.assertIsNotNone(current_item)
        self.assertEqual(current_item["quota"], 15)

    def test_quota_is_not_deducted_before_backend_returns_success(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=18,
            prefix="uk",
            pricing={"gpt-image-1": 0, "gpt-image-2": 6},
        )
        user_key = created["created_items"][0]["key"]
        context = api.resolve_auth_context(f"Bearer {user_key}")
        self.assertIsNotNone(context)
        seen_quota: list[int] = []

        class InspectBackendService:
            def generate_with_pool(self, prompt: str, model: str, n: int, input_images=None, queue_request_id=None, size=None) -> dict:
                del prompt, model, n, input_images, queue_request_id, size
                current_item = api.user_key_service.get_user_key(user_key)
                assert current_item is not None
                seen_quota.append(int(current_item["quota"]))
                return {
                    "created": 123,
                    "data": [{"b64_json": "ZmFrZQ==", "mime_type": "image/png"}],
                }

        async def fake_run_in_threadpool(func, *args):
            return func(*args)

        with patch.object(api, "run_in_threadpool", side_effect=fake_run_in_threadpool):
            result, billing_payload = asyncio.run(
                api.generate_image_payload(
                    service=InspectBackendService(),
                    context=context,
                    authorization=f"Bearer {user_key}",
                    prompt="draw a cat",
                    model="gpt-image-2",
                    n=1,
                )
            )

        self.assertEqual(seen_quota, [18])
        self.assertEqual(result["billing"]["charged_quota"], 6)
        assert billing_payload is not None
        self.assertEqual(billing_payload["remaining_quota"], 12)

    def test_purchase_quota_uses_ldc_balance(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=10,
            prefix="uk",
        )
        user_key = created["created_items"][0]["key"]
        api.user_key_service.update_user_key(user_key, {"ldc_balance": 40})

        with self.make_client() as client:
            response = client.post(
                "/api/quota/purchase",
                headers={"Authorization": f"Bearer {user_key}"},
                json={"package_count": 2},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["purchased_quota"], 40)
        self.assertEqual(response.json()["spent_ldc"], 40)
        self.assertEqual(response.json()["remaining_quota"], 50)
        self.assertEqual(response.json()["ldc_balance"], 0)
        current_item = api.user_key_service.get_user_key(user_key)
        self.assertIsNotNone(current_item)
        assert current_item is not None
        self.assertEqual(current_item["quota"], 50)
        self.assertEqual(current_item["ldc_balance"], 0)

    def test_redeem_code_adds_20_quota_to_current_user_key(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=5,
            prefix="uk",
        )
        user_key = created["created_items"][0]["key"]

        with self.make_client() as client:
            create_response = client.post(
                "/api/redeem-codes",
                headers={"Authorization": f"Bearer {api.config.admin_auth_key}"},
                json={"count": 1, "target_quota": 20, "prefix": "RDM", "label": "test-batch"},
            )
            self.assertEqual(create_response.status_code, 200)
            code = create_response.json()["created_items"][0]["code"]

            redeem_response = client.post(
                "/api/redeem-codes/redeem",
                headers={"Authorization": f"Bearer {user_key}"},
                json={"code": code},
            )
            second_redeem_response = client.post(
                "/api/redeem-codes/redeem",
                headers={"Authorization": f"Bearer {user_key}"},
                json={"code": code},
            )

        self.assertEqual(redeem_response.status_code, 200)
        self.assertEqual(redeem_response.json()["previous_quota"], 5)
        self.assertEqual(redeem_response.json()["added_quota"], 20)
        self.assertEqual(redeem_response.json()["remaining_quota"], 25)
        self.assertEqual(second_redeem_response.status_code, 404)
        current_item = api.user_key_service.get_user_key(user_key)
        self.assertIsNotNone(current_item)
        assert current_item is not None
        self.assertEqual(current_item["quota"], 25)
        redeemed_item = api.redeem_code_service.list_public_codes()[0]
        self.assertEqual(redeemed_item["status"], "已使用")
        self.assertEqual(redeemed_item["usedByKey"], user_key)

    def test_redeem_code_adds_100_quota_to_current_user_key(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=5,
            prefix="uk",
        )
        user_key = created["created_items"][0]["key"]

        with self.make_client() as client:
            create_response = client.post(
                "/api/redeem-codes",
                headers={"Authorization": f"Bearer {api.config.admin_auth_key}"},
                json={"count": 1, "target_quota": 100, "prefix": "RDM", "label": "test-batch"},
            )
            self.assertEqual(create_response.status_code, 200)
            code = create_response.json()["created_items"][0]["code"]

            redeem_response = client.post(
                "/api/redeem-codes/redeem",
                headers={"Authorization": f"Bearer {user_key}"},
                json={"code": code},
            )

        self.assertEqual(redeem_response.status_code, 200)
        self.assertEqual(redeem_response.json()["previous_quota"], 5)
        self.assertEqual(redeem_response.json()["added_quota"], 100)
        self.assertEqual(redeem_response.json()["remaining_quota"], 105)
        current_item = api.user_key_service.get_user_key(user_key)
        self.assertIsNotNone(current_item)
        assert current_item is not None
        self.assertEqual(current_item["quota"], 105)

    def test_redeem_code_create_rejects_unsupported_quota(self) -> None:
        with self.make_client() as client:
            create_response = client.post(
                "/api/redeem-codes",
                headers={"Authorization": f"Bearer {api.config.admin_auth_key}"},
                json={"count": 1, "target_quota": 80, "prefix": "RDM", "label": "test-batch"},
            )

        self.assertEqual(create_response.status_code, 400)

    def test_redeem_code_create_accepts_legacy_target_quota_alias(self) -> None:
        with self.make_client() as client:
            create_response = client.post(
                "/api/redeem-codes",
                headers={"Authorization": f"Bearer {api.config.admin_auth_key}"},
                json={"count": 1, "targetQuota": 20, "prefix": "RDM", "label": "legacy-body"},
            )

        self.assertEqual(create_response.status_code, 200)
        self.assertEqual(create_response.json()["created_items"][0]["targetQuota"], 20)

    def test_redeem_code_create_accepts_count_200(self) -> None:
        with self.make_client() as client:
            create_response = client.post(
                "/api/redeem-codes",
                headers={"Authorization": f"Bearer {api.config.admin_auth_key}"},
                json={"count": 200, "target_quota": 20, "prefix": "RDM", "label": "count-200"},
            )

        self.assertEqual(create_response.status_code, 200)
        self.assertEqual(len(create_response.json()["created_items"]), 200)

    def test_donation_rewards_ldc_only_for_free_accounts(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=10,
            prefix="uk",
        )
        user_key = created["created_items"][0]["key"]

        with self.make_client() as client:
            response = client.post(
                "/api/donations/accounts",
                headers={"Authorization": f"Bearer {user_key}"},
                json={
                    "tokens": [],
                    "accounts": [
                        {"access_token": "free-token-1"},
                        {"access_token": "plus-token-1"},
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rewarded_accounts"], 1)
        self.assertEqual(response.json()["rewarded_ldc"], 20)
        self.assertEqual(response.json()["remaining_quota"], 10)
        self.assertEqual(response.json()["ldc_balance"], 20)
        current_item = api.user_key_service.get_user_key(user_key)
        self.assertIsNotNone(current_item)
        assert current_item is not None
        self.assertEqual(current_item["ldc_balance"], 20)

    def test_process_upload_stream_and_recent_uploaded_images(self) -> None:
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
        )
        client_conversation_id = "conv-upload-1"

        with self.make_client() as client:
            upload_response = client.post(
                "/backend-api/files/process_upload_stream",
                headers={"Authorization": f"Bearer {api.config.auth_key}"},
                data={"client_conversation_id": client_conversation_id},
                files={"file": ("pixel.png", png_bytes, "image/png")},
            )
            self.assertEqual(upload_response.status_code, 200)
            uploaded = upload_response.json()
            self.assertTrue(str(uploaded["file_id"]).startswith("upload_"))
            self.assertEqual(uploaded["mime_type"], "image/png")
            self.assertEqual(uploaded["client_conversation_id"], client_conversation_id)

            list_response = client.get(
                f"/backend-api/my/recent/uploaded_images?limit=25&images_app_only=false&client_conversation_id={client_conversation_id}",
                headers={"Authorization": f"Bearer {api.config.auth_key}"},
            )
            self.assertEqual(list_response.status_code, 200)
            items = list_response.json()["items"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["file_id"], uploaded["file_id"])

    def test_responses_accepts_uploaded_image_file_id(self) -> None:
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
        )
        client_conversation_id = "conv-response-1"

        with self.make_client() as client:
            upload_response = client.post(
                "/backend-api/files/process_upload_stream",
                headers={"Authorization": f"Bearer {api.config.auth_key}"},
                data={"client_conversation_id": client_conversation_id},
                files={"file": ("pixel.png", png_bytes, "image/png")},
            )
            self.assertEqual(upload_response.status_code, 200)
            file_id = upload_response.json()["file_id"]

            response = client.post(
                "/v1/responses",
                headers={"Authorization": f"Bearer {api.config.auth_key}"},
                json={
                    "model": "gpt-5",
                    "input": [
                        {"type": "input_text", "text": "repeat ABC123"},
                        {"type": "input_image", "file_id": file_id},
                    ],
                    "tools": [{"type": "image_generation", "model": "gpt-image-2"}],
                    "n": 1,
                    "metadata": {"client_conversation_id": client_conversation_id},
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(FakeBackendService.last_call)
        self.assertEqual(FakeBackendService.last_call["prompt"], "repeat ABC123")
        self.assertEqual(
            FakeBackendService.last_call["input_images"],
            [{
                "type": "input_image",
                "file_id": file_id,
                "owner_auth_token": api.config.auth_key,
                "client_conversation_id": client_conversation_id,
            }],
        )

    def test_responses_rejects_uploaded_image_file_id_from_other_conversation(self) -> None:
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
        )

        with self.make_client() as client:
            upload_response = client.post(
                "/backend-api/files/process_upload_stream",
                headers={"Authorization": f"Bearer {api.config.auth_key}"},
                data={"client_conversation_id": "conv-a"},
                files={"file": ("pixel.png", png_bytes, "image/png")},
            )
            self.assertEqual(upload_response.status_code, 200)
            file_id = upload_response.json()["file_id"]

            response = client.post(
                "/v1/responses",
                headers={"Authorization": f"Bearer {api.config.auth_key}"},
                json={
                    "model": "gpt-5",
                    "input": [
                        {"type": "input_text", "text": "repeat ABC123"},
                        {"type": "input_image", "file_id": file_id},
                    ],
                    "tools": [{"type": "image_generation", "model": "gpt-image-2"}],
                    "n": 1,
                    "metadata": {"client_conversation_id": "conv-b"},
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn("input image file_id was not found", response.text)

    def test_responses_rejects_uploaded_image_file_id_from_other_owner(self) -> None:
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
        )
        created = api.user_key_service.create_user_keys(count=1, quota=10, prefix="uk")
        user_key = created["created_items"][0]["key"]

        with self.make_client() as client:
            upload_response = client.post(
                "/backend-api/files/process_upload_stream",
                headers={"Authorization": f"Bearer {api.config.auth_key}"},
                data={"client_conversation_id": "conv-a"},
                files={"file": ("pixel.png", png_bytes, "image/png")},
            )
            self.assertEqual(upload_response.status_code, 200)
            file_id = upload_response.json()["file_id"]

            response = client.post(
                "/v1/responses",
                headers={"Authorization": f"Bearer {user_key}"},
                json={
                    "model": "gpt-5",
                    "input": [
                        {"type": "input_text", "text": "repeat ABC123"},
                        {"type": "input_image", "file_id": file_id},
                    ],
                    "tools": [{"type": "image_generation", "model": "gpt-image-2"}],
                    "n": 1,
                    "metadata": {"client_conversation_id": "conv-a"},
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn("input image file_id was not found", response.text)

    def test_responses_rejects_consumed_uploaded_image_file_id_for_new_conversation(self) -> None:
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
        )

        with self.make_client() as client:
            upload_response = client.post(
                "/backend-api/files/process_upload_stream",
                headers={"Authorization": f"Bearer {api.config.auth_key}"},
                data={"client_conversation_id": "conv-a"},
                files={"file": ("pixel.png", png_bytes, "image/png")},
            )
            self.assertEqual(upload_response.status_code, 200)
            file_id = upload_response.json()["file_id"]

            first_response = client.post(
                "/v1/responses",
                headers={"Authorization": f"Bearer {api.config.auth_key}"},
                json={
                    "model": "gpt-5",
                    "input": [
                        {"type": "input_text", "text": "repeat ABC123"},
                        {"type": "input_image", "file_id": file_id},
                    ],
                    "tools": [{"type": "image_generation", "model": "gpt-image-2"}],
                    "n": 1,
                    "metadata": {"client_conversation_id": "conv-a"},
                },
            )
            self.assertEqual(first_response.status_code, 200)

            second_response = client.post(
                "/v1/responses",
                headers={"Authorization": f"Bearer {api.config.auth_key}"},
                json={
                    "model": "gpt-5",
                    "input": [
                        {"type": "input_text", "text": "repeat AGAIN"},
                        {"type": "input_image", "file_id": file_id},
                    ],
                    "tools": [{"type": "image_generation", "model": "gpt-image-2"}],
                    "n": 1,
                    "metadata": {"client_conversation_id": "conv-b"},
                },
            )

        self.assertEqual(second_response.status_code, 404)
        self.assertIn("input image file_id was not found", second_response.text)

    def test_image_generation_rejects_more_than_two_images(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=30,
            prefix="uk",
        )
        user_key = created["created_items"][0]["key"]

        with self.make_client() as client:
            response = client.post(
                "/v1/images/generations",
                headers={"Authorization": f"Bearer {user_key}"},
                json={"prompt": "a test image", "model": "gpt-image-2", "n": 3},
            )

        self.assertEqual(response.status_code, 422)

    def test_models_endpoint_only_exposes_gpt_image_2(self) -> None:
        with self.make_client() as client:
            response = client.get("/v1/models", headers={"Authorization": f"Bearer {api.config.auth_key}"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["data"]],
            ["gpt-image-2"],
        )

    def test_image_generation_rejects_gpt_image_1(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=10,
            prefix="uk",
        )
        user_key = created["created_items"][0]["key"]

        with self.make_client() as client:
            response = client.post(
                "/v1/images/generations",
                headers={"Authorization": f"Bearer {user_key}"},
                json={"prompt": "a test image", "model": "gpt-image-1", "n": 1},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("unsupported image model", response.json()["detail"]["error"])

    def test_responses_without_tool_model_default_to_gpt_image_2(self) -> None:
        with self.make_client() as client:
            response = client.post(
                "/v1/responses",
                headers={"Authorization": f"Bearer {api.config.auth_key}"},
                json={
                    "model": "gpt-5.4",
                    "input": [{"type": "input_text", "text": "draw a test image"}],
                    "tools": [{"type": "image_generation"}],
                    "n": 1,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(FakeBackendService.last_call)
        assert FakeBackendService.last_call is not None
        self.assertEqual(FakeBackendService.last_call["model"], "gpt-image-2")

    def test_image_queue_status_reports_current_request(self) -> None:
        auth_key = api.config.auth_key
        api.image_queue_service.create_ticket(auth_key, "req-1", "draw a cat")
        api.image_queue_service.wait_for_turn("req-1")
        api.image_queue_service.mark_status("req-1", "running")

        with self.make_client() as client:
            response = client.get(
                "/api/image-queue/me?request_id=req-1",
                headers={"Authorization": f"Bearer {auth_key}"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user"], {"waiting": 0, "running": 1})
        self.assertEqual(body["request"]["status"], "running")
        self.assertEqual(body["request"]["request_id"], "req-1")

    def test_register_image_queue_request_enforces_per_user_limit(self) -> None:
        auth_key = "queued-user-key"
        for index in range(api.image_queue_service.PER_USER_WAIT_LIMIT):
            api.image_queue_service.create_ticket(auth_key, f"req-{index}")

        with self.assertRaises(api.HTTPException) as raised:
            asyncio.run(api.register_image_queue_request(auth_key, "overflow", "draw overflow"))

        self.assertEqual(raised.exception.status_code, 429)
        self.assertIn("max_waiting", raised.exception.detail["error"])

    def test_admin_can_create_and_update_user_key_pricing(self) -> None:
        with self.make_client() as client:
            create_response = client.post(
                "/api/user-keys",
                headers={"Authorization": f"Bearer {api.config.admin_auth_key}"},
                json={
                    "count": 1,
                    "quota": 18,
                    "prefix": "uk",
                    "pricing": {"gpt-image-1": 5, "gpt-image-2": 11},
                },
            )
            self.assertEqual(create_response.status_code, 200)
            created_item = create_response.json()["created_items"][0]
            self.assertEqual(created_item["pricing"], {"gpt-image-1": 5, "gpt-image-2": 11})

            update_response = client.post(
                "/api/user-keys/update",
                headers={"Authorization": f"Bearer {api.config.admin_auth_key}"},
                json={
                    "key": created_item["key"],
                    "pricing": {"gpt-image-1": 6, "gpt-image-2": 9},
                },
            )
            self.assertEqual(update_response.status_code, 200)
            self.assertEqual(
                update_response.json()["item"]["pricing"],
                {"gpt-image-1": 6, "gpt-image-2": 9},
            )

    def test_response_api_uses_requested_image_model_and_can_be_read_back(self) -> None:
        result = {
            "created": 123,
            "data": [{"b64_json": "ZmFrZQ==", "mime_type": "image/png"}],
        }
        billing_payload = {
            "requested_model": "gpt-image-2",
            "unit_cost": 8,
            "charged_quota": 8,
            "remaining_quota": 4,
        }
        payload = api.build_responses_payload(
            response_id="resp_test_1",
            response_model="gpt-5",
            image_result=result,
            billing=billing_payload,
        )
        api.response_store_set(payload["id"], payload)
        stored = api.response_store_get(payload["id"])

        self.assertEqual(payload["object"], "response")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["model"], "gpt-5")
        self.assertEqual(payload["billing"]["requested_model"], "gpt-image-2")
        self.assertEqual(payload["billing"]["unit_cost"], 8)
        self.assertEqual(payload["billing"]["charged_quota"], 8)
        self.assertEqual(payload["billing"]["remaining_quota"], 4)
        self.assertIsNone(payload["error"])
        self.assertIsNone(payload["incomplete_details"])
        self.assertEqual(payload["output"][0]["type"], "image_generation_call")
        self.assertEqual(payload["output"][0]["status"], "completed")
        self.assertEqual(payload["output"][0]["result"], "ZmFrZQ==")
        self.assertEqual(len(payload["output"]), 1)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["id"], payload["id"])
        self.assertEqual(stored["output"][0]["result"], "ZmFrZQ==")
        self.assertEqual(stored["model"], "gpt-5")

    def test_extract_responses_input_accepts_text_with_single_input_image(self) -> None:
        input_payload = [
            {"type": "input_text", "text": "edit this image"},
            {"type": "input_image", "image_url": "https://example.com/source.png"},
        ]

        prompt = api.extract_responses_prompt(input_payload)
        image_inputs = api.extract_image_inputs_from_responses_input(input_payload)

        self.assertEqual(prompt, "edit this image")
        self.assertEqual(
            image_inputs,
            [{"type": "input_image", "image_url": "https://example.com/source.png"}],
        )

    def test_extract_responses_input_accepts_data_url_image(self) -> None:
        input_payload = {
            "type": "message",
            "content": [
                {"type": "input_text", "text": "edit this image"},
                {"type": "input_image", "image_url": "data:image/png;base64,ZmFrZQ=="},
            ],
        }

        image_inputs = api.extract_image_inputs_from_responses_input(input_payload)

        self.assertEqual(
            image_inputs,
            [{"type": "input_image", "image_url": "data:image/png;base64,ZmFrZQ=="}],
        )

    def test_extract_responses_input_rejects_non_image_data_url(self) -> None:
        with self.assertRaises(api.HTTPException) as raised:
            api.extract_image_inputs_from_responses_input(
                [{"type": "input_image", "image_url": "data:text/plain;base64,ZmFrZQ=="}]
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(
            raised.exception.detail["error"],
            "responses input_image data URL must use an image mime type",
        )

    def test_extract_responses_input_accepts_file_id(self) -> None:
        self.assertEqual(
            api.extract_image_inputs_from_responses_input(
                [{"type": "input_image", "file_id": "file_123"}]
            ),
            [{"type": "input_image", "file_id": "file_123"}],
        )

    def test_validate_responses_input_images_rejects_multiple_input_images_for_now(self) -> None:
        with self.assertRaises(api.HTTPException) as raised:
            api.validate_responses_input_images(
                [
                    {"type": "input_text", "text": "edit both"},
                    {"type": "input_image", "image_url": "https://example.com/1.png"},
                    {"type": "input_image", "image_url": "https://example.com/2.png"},
                ]
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(
            raised.exception.detail["error"],
            "responses input_image currently supports at most one image",
        )

    def test_validate_responses_input_images_accepts_single_input_image(self) -> None:
        image_inputs = api.validate_responses_input_images(
            [
                {"type": "input_text", "text": "edit this image"},
                {"type": "input_image", "image_url": "https://example.com/source.png"},
            ]
        )

        self.assertEqual(
            image_inputs,
            [{"type": "input_image", "image_url": "https://example.com/source.png"}],
        )

    def test_generate_image_payload_passes_input_image_to_backend_generation(self) -> None:
        service = FakeBackendService(FakeAccountService())

        async def fake_run_in_threadpool(func, *args):
            return func(*args)

        with patch.object(api, "run_in_threadpool", side_effect=fake_run_in_threadpool):
            result, billing_payload = asyncio.run(
                api.generate_image_payload(
                    service=service,
                    context=api.AuthContext(role="user", auth_type="auth_key"),
                    authorization=f"Bearer {api.config.auth_key}",
                    prompt="edit this image",
                    model="gpt-image-2",
                    n=1,
                    input_images=[{"type": "input_image", "image_url": "https://example.com/source.png"}],
                )
            )

        self.assertEqual(result["data"][0]["b64_json"], "ZmFrZQ==")
        self.assertIsNone(billing_payload)
        self.assertIsNotNone(FakeBackendService.last_call)
        assert FakeBackendService.last_call is not None
        self.assertEqual(
            FakeBackendService.last_call["input_images"],
            [{"type": "input_image", "image_url": "https://example.com/source.png"}],
        )

    def test_generate_image_payload_with_input_image_applies_user_key_billing(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=10,
            prefix="uk",
            pricing={"gpt-image-1": 2, "gpt-image-2": 6},
        )
        user_key = created["created_items"][0]["key"]
        context = api.resolve_auth_context(f"Bearer {user_key}")
        self.assertIsNotNone(context)
        service = FakeBackendService(FakeAccountService())

        async def fake_run_in_threadpool(func, *args):
            return func(*args)

        with patch.object(api, "run_in_threadpool", side_effect=fake_run_in_threadpool):
            result, billing_payload = asyncio.run(
                api.generate_image_payload(
                    service=service,
                    context=context,
                    authorization=f"Bearer {user_key}",
                    prompt="edit this image",
                    model="gpt-image-2",
                    n=1,
                    input_images=[{"type": "input_image", "image_url": "https://example.com/source.png"}],
                )
            )

        self.assertIsNotNone(billing_payload)
        assert billing_payload is not None
        self.assertEqual(billing_payload["requested_model"], "gpt-image-2")
        self.assertEqual(billing_payload["unit_cost"], 6)
        self.assertEqual(billing_payload["charged_quota"], 6)
        self.assertEqual(billing_payload["remaining_quota"], 4)
        self.assertEqual(result["billing"]["charged_quota"], 6)
        current_item = api.user_key_service.get_user_key(user_key)
        self.assertIsNotNone(current_item)
        self.assertEqual(current_item["quota"], 4)
        self.assertEqual(
            FakeBackendService.last_call["input_images"],
            [{"type": "input_image", "image_url": "https://example.com/source.png"}],
        )

    def test_generate_image_payload_with_input_image_refunds_user_key_on_failure(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=15,
            prefix="uk",
            pricing={"gpt-image-1": 3, "gpt-image-2": 6},
        )
        user_key = created["created_items"][0]["key"]
        context = api.resolve_auth_context(f"Bearer {user_key}")
        self.assertIsNotNone(context)
        service = FakeBackendService(FakeAccountService())
        FakeBackendService.error = ImageGenerationError("upstream failed")

        async def fake_run_in_threadpool(func, *args):
            return func(*args)

        with patch.object(api, "run_in_threadpool", side_effect=fake_run_in_threadpool):
            with self.assertRaises(api.HTTPException) as raised:
                asyncio.run(
                    api.generate_image_payload(
                        service=service,
                        context=context,
                        authorization=f"Bearer {user_key}",
                        prompt="edit this image",
                        model="gpt-image-2",
                        n=2,
                        input_images=[{"type": "input_image", "image_url": "https://example.com/source.png"}],
                    )
                )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.detail["error"], "upstream failed")
        current_item = api.user_key_service.get_user_key(user_key)
        self.assertIsNotNone(current_item)
        self.assertEqual(current_item["quota"], 15)

    def test_responses_alias_supports_multiple_images(self) -> None:
        result = {
            "created": 123,
            "data": [
                {"b64_json": "Zmlyc3Q=", "mime_type": "image/png"},
                {"b64_json": "c2Vjb25k", "mime_type": "image/webp"},
            ],
        }
        billing_payload = {
            "requested_model": "gpt-image-1",
            "unit_cost": 4,
            "charged_quota": 8,
            "remaining_quota": 4,
        }
        payload = api.build_responses_payload(
            response_id="resp_test_2",
            response_model="gpt-5",
            image_result=result,
            billing=billing_payload,
        )

        self.assertEqual(payload["model"], "gpt-5")
        self.assertEqual(payload["billing"]["charged_quota"], 8)
        self.assertEqual(payload["billing"]["remaining_quota"], 4)
        self.assertEqual(len(payload["output"]), 2)
        self.assertEqual(payload["output"][0]["type"], "image_generation_call")
        self.assertEqual(payload["output"][0]["result"], "Zmlyc3Q=")
        self.assertEqual(payload["output"][1]["type"], "image_generation_call")
        self.assertEqual(payload["output"][1]["result"], "c2Vjb25k")
        self.assertEqual(payload["output"][1]["status"], "completed")

    def test_response_stream_emits_completed_event_and_done_marker(self) -> None:
        payload = api.build_responses_payload(
            response_id="resp_stream_test",
            response_model="gpt-5",
            image_result={
                "created": 123,
                "data": [{"b64_json": "ZmFrZQ==", "mime_type": "image/png"}],
            },
            billing={
                "requested_model": "gpt-image-2",
                "unit_cost": 8,
                "charged_quota": 8,
                "remaining_quota": 4,
            },
        )
        stream_content = b"".join(api.iter_responses_stream(payload)).decode("utf-8")
        events = self.collect_sse_events(stream_content)

        self.assertGreaterEqual(len(events), 5)
        self.assertEqual(events[0][0], "response.created")
        self.assertEqual(events[0][1]["type"], "response.created")
        self.assertEqual(events[0][1]["response"]["status"], "in_progress")

        image_completed_events = [payload for event, payload in events if event == "response.image_generation_call.completed"]
        self.assertEqual(len(image_completed_events), 1)
        self.assertEqual(image_completed_events[0]["item_id"], payload["output"][0]["id"])

        output_item_done_events = [payload for event, payload in events if event == "response.output_item.done"]
        self.assertEqual(len(output_item_done_events), 1)
        self.assertEqual(output_item_done_events[0]["item"]["type"], "image_generation_call")
        self.assertEqual(output_item_done_events[0]["item"]["result"], "ZmFrZQ==")

        completed_events = [payload for event, payload in events if event == "response.completed"]
        self.assertEqual(len(completed_events), 1)
        completed_payload = completed_events[0]
        self.assertEqual(completed_payload["type"], "response.completed")
        self.assertEqual(completed_payload["response"]["status"], "completed")
        self.assertEqual(completed_payload["response"]["model"], "gpt-5")
        self.assertEqual(completed_payload["response"]["billing"]["charged_quota"], 8)
        self.assertEqual(completed_payload["response"]["output"][0]["result"], "ZmFrZQ==")

        self.assertEqual(events[-1], (None, "[DONE]"))

    def test_response_stream_with_input_image_result_still_emits_completed_and_done_marker(self) -> None:
        payload = api.build_responses_payload(
            response_id="resp_stream_input_image",
            response_model="gpt-5",
            image_result={
                "created": 123,
                "data": [{"b64_json": "ZmFrZQ==", "mime_type": "image/png"}],
            },
            billing={
                "requested_model": "gpt-image-1",
                "unit_cost": 3,
                "charged_quota": 3,
                "remaining_quota": 6,
            },
            metadata={"input_image": "true"},
        )
        stream_content = b"".join(api.iter_responses_stream(payload)).decode("utf-8")
        events = self.collect_sse_events(stream_content)

        completed_events = [payload for event, payload in events if event == "response.completed"]
        self.assertEqual(len(completed_events), 1)
        self.assertEqual(completed_events[0]["response"]["billing"]["charged_quota"], 3)
        self.assertEqual(completed_events[0]["response"]["metadata"]["input_image"], "true")
        self.assertEqual(events[-1], (None, "[DONE]"))

    def test_image_generation_stream_emits_completed_and_done_marker(self) -> None:
        payload = api.build_images_response_payload(
            {
                "created": 123,
                "data": [{"b64_json": "ZmFrZQ==", "mime_type": "image/png"}],
            },
            billing={
                "requested_model": "gpt-image-2",
                "unit_cost": 8,
                "charged_quota": 8,
                "remaining_quota": 4,
            },
        )
        stream_content = b"".join(
            api.iter_images_stream(
                payload,
                output_format="png",
                background="transparent",
                quality="high",
                size="1024x1024",
                partial_images=0,
            )
        ).decode("utf-8")
        events = self.collect_sse_events(stream_content)

        self.assertEqual(events[0][0], "image_generation.completed")
        self.assertEqual(events[0][1]["type"], "image_generation.completed")
        self.assertEqual(events[0][1]["b64_json"], "ZmFrZQ==")
        self.assertEqual(events[0][1]["output_format"], "png")
        self.assertEqual(events[0][1]["background"], "transparent")
        self.assertEqual(events[0][1]["quality"], "high")
        self.assertEqual(events[0][1]["size"], "1024x1024")
        self.assertEqual(events[-1], (None, "[DONE]"))

    def test_admin_login_role_and_accounts_access(self) -> None:
        with self.make_client() as client:
            login_response = client.post(
                "/auth/login",
                headers={"Authorization": f"Bearer {api.config.admin_auth_key}"},
                json={},
            )
            self.assertEqual(login_response.status_code, 200)
            self.assertEqual(login_response.json()["role"], "admin")
            self.assertEqual(login_response.json()["auth_type"], "admin_auth_key")

            accounts_response = client.get(
                "/api/accounts",
                headers={"Authorization": f"Bearer {api.config.admin_auth_key}"},
            )
            self.assertEqual(accounts_response.status_code, 200)
            self.assertIn("items", accounts_response.json())

    def test_static_pages_support_head_requests(self) -> None:
        web_dist_dir = self.temp_dir / "web_dist"
        web_dist_dir.mkdir(parents=True, exist_ok=True)
        (web_dist_dir / "login.html").write_text("<html><body>login</body></html>", encoding="utf-8")

        with patch.object(api, "WEB_DIST_DIR", web_dist_dir):
            with self.make_client() as client:
                response = client.head("/login")

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
