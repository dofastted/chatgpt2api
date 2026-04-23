from __future__ import annotations

import asyncio
import base64
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TEST_ROOT = Path(tempfile.mkdtemp(prefix="chatgpt2api-tests-config-"))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")
os.environ.setdefault("CHATGPT2API_ADMIN_AUTH_KEY", "test-admin-key")
os.environ.setdefault("CHATGPT2API_USER_KEYS_FILE", str(TEST_ROOT / "bootstrap-user-keys.json"))
sys.modules.setdefault("pybase64", base64)

from services import api  # noqa: E402
from services.image_service import ImageGenerationError  # noqa: E402
from services.user_key_service import UserKeyService  # noqa: E402


class FakeBackendService:
    def generate_with_pool(
        self,
        prompt: str,
        model: str,
        n: int,
        input_images: list[dict[str, str]] | None = None,
    ) -> dict:
        del prompt, n, input_images
        return {
            "created": 123,
            "data": [{"b64_json": model, "mime_type": "image/png"}],
        }


class ApiImageModelRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="chatgpt2api-api-rules-"))
        self.user_keys_file = self.temp_dir / "user_keys.json"
        api.user_key_service.store_file = self.user_keys_file
        api.user_key_service._user_keys = []

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_user_key_pricing_now_uses_image_2_cost_two(self) -> None:
        legacy_file = self.temp_dir / "legacy-user-keys.json"
        legacy_file.write_text(
            '[{"key":"legacy-key","quota":12,"status":"启用"}]',
            encoding="utf-8",
        )

        service = UserKeyService(legacy_file)

        item = service.get_user_key("legacy-key")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item["pricing"], {"gpt-image-1": 0, "gpt-image-2": 2})

    def test_normalize_requested_image_model_only_allows_image_2(self) -> None:
        self.assertEqual(api.normalize_requested_image_model("gpt-image-2"), "gpt-image-2")
        with self.assertRaises(api.HTTPException) as raised:
            api.normalize_requested_image_model("gpt-image-1")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("unsupported image model", raised.exception.detail["error"])

    def test_responses_request_defaults_to_image_2_when_tool_model_missing(self) -> None:
        request = api.ResponsesCreateRequest(
            model="gpt-5.4",
            input=[{"type": "input_text", "text": "draw a cat"}],
            tools=[api.ResponsesToolRequest(type="image_generation")],
            n=1,
        )

        self.assertEqual(api.resolve_requested_response_image_model(request), "gpt-image-2")

    def test_generate_image_payload_uses_image_2_billing_by_default(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=10,
            prefix="uk",
        )
        user_key = created["created_items"][0]["key"]
        context = api.resolve_auth_context(f"Bearer {user_key}")
        self.assertIsNotNone(context)
        service = FakeBackendService()

        async def fake_run_in_threadpool(func, *args):
            return func(*args)

        with patch.object(api, "run_in_threadpool", side_effect=fake_run_in_threadpool):
            result, billing_payload = asyncio.run(
                api.generate_image_payload(
                    service=service,
                    context=context,
                    authorization=f"Bearer {user_key}",
                    prompt="draw a cat",
                    model="gpt-image-2",
                    n=1,
                )
            )

        self.assertIsNotNone(billing_payload)
        assert billing_payload is not None
        self.assertEqual(billing_payload["requested_model"], "gpt-image-2")
        self.assertEqual(billing_payload["unit_cost"], 2)
        self.assertEqual(billing_payload["charged_quota"], 2)
        self.assertEqual(billing_payload["remaining_quota"], 8)
        self.assertEqual(result["data"][0]["b64_json"], "gpt-image-2")

    def test_build_image_payloads_preserve_copied_text(self) -> None:
        image_result = {
            "created": 123,
            "copied_text": "copied from chrome",
            "data": [{"b64_json": "ZmFrZQ==", "mime_type": "image/png"}],
        }

        legacy_payload = api.build_images_response_payload(image_result, billing=None)
        responses_payload = api.build_responses_payload(
            response_id="resp_test_copy_text",
            response_model="gpt-5.4",
            image_result=image_result,
            billing=None,
        )

        self.assertEqual(legacy_payload["copied_text"], "copied from chrome")
        self.assertEqual(responses_payload["copied_text"], "copied from chrome")

    def test_generate_image_payload_refunds_image_2_quota_when_backend_fails(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=12,
            prefix="uk",
        )
        user_key = created["created_items"][0]["key"]
        context = api.resolve_auth_context(f"Bearer {user_key}")
        self.assertIsNotNone(context)

        class FailingBackendService:
            def generate_with_pool(self, prompt: str, model: str, n: int, input_images=None) -> dict:
                del prompt, model, n, input_images
                raise ImageGenerationError("conversation failed: 524")

        async def fake_run_in_threadpool(func, *args):
            return func(*args)

        with patch.object(api, "run_in_threadpool", side_effect=fake_run_in_threadpool):
            with self.assertRaises(api.HTTPException) as raised:
                asyncio.run(
                    api.generate_image_payload(
                        service=FailingBackendService(),
                        context=context,
                        authorization=f"Bearer {user_key}",
                        prompt="draw a cat",
                        model="gpt-image-2",
                        n=1,
                    )
                )

        self.assertEqual(raised.exception.status_code, 502)
        current_item = api.user_key_service.get_user_key(user_key)
        self.assertIsNotNone(current_item)
        assert current_item is not None
        self.assertEqual(current_item["quota"], 12)


if __name__ == "__main__":
    unittest.main()
