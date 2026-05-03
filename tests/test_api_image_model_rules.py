from __future__ import annotations

import asyncio
import base64
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

TEST_ROOT = Path(tempfile.mkdtemp(prefix="chatgpt2api-tests-config-"))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")
os.environ.setdefault("CHATGPT2API_ADMIN_AUTH_KEY", "test-admin-key")
os.environ.setdefault("CHATGPT2API_USER_KEYS_FILE", str(TEST_ROOT / "bootstrap-user-keys.json"))
sys.modules.setdefault("pybase64", base64)

from services import api  # noqa: E402
from services import image_service  # noqa: E402
from services.image_size import normalize_image_size  # noqa: E402
from services.image_service import ImageGenerationError  # noqa: E402
from services.user_key_service import UserKeyService  # noqa: E402


class FakeBackendService:
    def __init__(self) -> None:
        self.last_call: dict[str, object] = {}

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
        self.last_call = {
            "prompt": prompt,
            "model": model,
            "n": n,
            "input_images": input_images,
            "size": size,
        }
        return {
            "created": 123,
            "data": [{"b64_json": model, "mime_type": "image/png"}],
        }


class FakeThread:
    def join(self, timeout: float | None = None) -> None:
        del timeout


class ApiImageModelRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="chatgpt2api-api-rules-"))
        self.user_keys_file = self.temp_dir / "user_keys.json"
        self.redeem_codes_file = self.temp_dir / "redeem_codes.json"
        api.user_key_service.store_file = self.user_keys_file
        api.user_key_service._user_keys = []
        api.redeem_code_service.store_file = self.redeem_codes_file
        api.redeem_code_service._items = []
        with api.RESPONSES_STORE_LOCK:
            api.RESPONSES_STORE.clear()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_user_key_pricing_uses_4k_cost_eight(self) -> None:
        legacy_file = self.temp_dir / "legacy-user-keys.json"
        legacy_file.write_text(
            '[{"key":"legacy-key","quota":12,"status":"启用"}]',
            encoding="utf-8",
        )

        service = UserKeyService(legacy_file)

        item = service.get_user_key("legacy-key")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(
            item["pricing"],
            {"gpt-image-2": 2, "gpt-image-2-2K": 2, "gpt-image-2-4K": 8},
        )

    def test_normalize_requested_image_model_allows_public_image_2_variants(self) -> None:
        self.assertEqual(api.normalize_requested_image_model("gpt-image-2"), "gpt-image-2")
        self.assertEqual(api.normalize_requested_image_model("gpt-image-2-2K"), "gpt-image-2-2K")
        self.assertEqual(api.normalize_requested_image_model("gpt-image-2-4K"), "gpt-image-2-4K")
        with self.assertRaises(api.HTTPException) as raised:
            api.normalize_requested_image_model("gpt-image-1")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("unsupported image model", raised.exception.detail["error"])

    def test_normalize_image_size_rounds_down_to_multiple_of_sixteen(self) -> None:
        self.assertEqual(normalize_image_size(None), "auto")
        self.assertEqual(normalize_image_size("auto"), "auto")
        self.assertEqual(normalize_image_size("1025x1351"), "1024x1344")
        with self.assertRaises(ValueError):
            normalize_image_size("wide")

    def test_codex_responses_request_places_size_inside_image_tool(self) -> None:
        class Session:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict, dict]] = []

            def post(self, url: str, **kwargs):
                self.calls.append((url, kwargs.get("headers") or {}, kwargs.get("json") or {}))

                class Response:
                    ok = True
                    status_code = 200
                    text = ""

                    def iter_lines(self):
                        return iter([])

                return Response()

        session = Session()
        image_service._send_responses_request(
            session,
            "token-123",
            "account-123",
            "draw",
            "gpt-image-2",
            None,
            size="1537x1025",
        )

        url, headers, body = session.calls[0]
        self.assertEqual(url, "https://chatgpt.com/backend-api/codex/responses")
        self.assertEqual(headers["Chatgpt-Account-Id"], "account-123")
        self.assertEqual(body["tools"][0]["type"], "image_generation")
        self.assertEqual(body["tools"][0]["model"], "gpt-image-2")
        self.assertEqual(body["tools"][0]["action"], "generate")
        self.assertEqual(body["tools"][0]["size"], "1536x1024")
        self.assertEqual(body["tool_choice"], {"type": "image_generation"})
        self.assertNotIn("size", body)

    def test_responses_request_defaults_to_image_2_when_tool_model_missing(self) -> None:
        request = api.ResponsesCreateRequest(
            model="gpt-5.4",
            input=[{"type": "input_text", "text": "draw a cat"}],
            tools=[api.ResponsesToolRequest(type="image_generation")],
            n=1,
        )

        self.assertEqual(api.resolve_requested_response_image_model(request), "gpt-image-2")

    def test_responses_health_endpoint_returns_json_without_generation(self) -> None:
        with patch.object(api, "start_limited_account_watcher", side_effect=lambda stop_event: FakeThread()):
            with TestClient(api.create_app()) as client:
                response = client.get(
                    "/v1/responses",
                    headers={"Authorization": f"Bearer {api.config.auth_key}"},
                )
                head_response = client.head(
                    "/v1/responses",
                    headers={"Authorization": f"Bearer {api.config.auth_key}"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"].split(";", 1)[0], "application/json")
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["endpoint"], "/v1/responses")
        self.assertEqual(payload["data"], [])
        self.assertEqual(payload["auth_type"], "auth_key")
        self.assertEqual(head_response.status_code, 200)

    def test_chat_completions_health_endpoint_accepts_user_key(self) -> None:
        created = api.user_key_service.create_user_keys(count=1, quota=10, prefix="uk")
        user_key = created["created_items"][0]["key"]
        with patch.object(api, "start_limited_account_watcher", side_effect=lambda stop_event: FakeThread()):
            with TestClient(api.create_app()) as client:
                response = client.post(
                    "/v1/chat/completions",
                    headers={"Authorization": f"Bearer {user_key}"},
                    json={"model": "gpt-5", "messages": [{"role": "user", "content": "ping"}]},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["choices"][0]["message"]["content"], "ok")
        self.assertEqual(payload["metadata"]["auth_type"], "user_key")
        self.assertTrue(payload["metadata"]["health_check"])

    def test_responses_post_without_image_tool_returns_health_payload(self) -> None:
        created = api.user_key_service.create_user_keys(count=1, quota=10, prefix="uk")
        user_key = created["created_items"][0]["key"]
        service = FakeBackendService()
        with patch.object(api, "BackendService", return_value=service):
            with patch.object(api, "start_limited_account_watcher", side_effect=lambda stop_event: FakeThread()):
                with TestClient(api.create_app()) as client:
                    response = client.post(
                        "/v1/responses",
                        headers={"Authorization": f"Bearer {user_key}"},
                        json={
                            "model": "gpt-5",
                            "input": "ping",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["output_text"], "ok")
        self.assertEqual(payload["metadata"]["auth_type"], "user_key")
        self.assertTrue(payload["metadata"]["health_check"])
        self.assertEqual(service.last_call, {})

    def test_await_image_generation_payload_returns_504_on_timeout(self) -> None:
        async def slow_payload() -> dict:
            await asyncio.sleep(0.05)
            return {"ok": True}

        with patch.object(api, "IMAGE_GENERATION_TIMEOUT_SECONDS", 0.001):
            with self.assertRaises(api.HTTPException) as raised:
                asyncio.run(api.await_image_generation_payload(slow_payload()))

        self.assertEqual(raised.exception.status_code, 504)
        self.assertIn("timed out", raised.exception.detail["error"])

    def test_user_key_takes_precedence_over_plain_auth_key(self) -> None:
        api.user_key_service.create_user_keys(count=1, quota=10, prefix="uk")
        user_key = api.user_key_service.list_user_keys()[0]["key"]
        with patch.object(api, "config", SimpleNamespace(admin_auth_key="admin-key", auth_key=user_key)):
            context = api.resolve_auth_context(f"Bearer {user_key}")

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.auth_type, "user_key")
        self.assertEqual(context.remaining_quota, 10)

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
                    size="1024x1024",
                )
            )

        self.assertIsNotNone(billing_payload)
        assert billing_payload is not None
        self.assertEqual(billing_payload["requested_model"], "gpt-image-2")
        self.assertEqual(billing_payload["unit_cost"], 2)
        self.assertEqual(billing_payload["charged_quota"], 2)
        self.assertEqual(billing_payload["remaining_quota"], 8)
        self.assertEqual(result["data"][0]["b64_json"], "gpt-image-2")
        self.assertEqual(service.last_call["size"], "1024x1024")

    def test_responses_previous_response_id_adds_history_context_and_size(self) -> None:
        previous_payload = api.build_responses_payload(
            response_id="resp_previous",
            response_model="gpt-5",
            image_result={"created": 123, "data": [{"b64_json": "old"}]},
            billing=None,
            metadata={"size": "1024x1024"},
        )
        api.response_store_set(
            "resp_previous",
            {
                **previous_payload,
                "_history": [
                    {
                        "response_id": "resp_previous",
                        "prompt": "draw first image",
                        "size": "1024x1024",
                        "input_images": [],
                        "output_count": 1,
                    }
                ],
            },
        )
        calls: list[dict[str, object]] = []

        async def fake_generate_image_payload(**kwargs):
            calls.append(dict(kwargs))
            return {
                "created": 123,
                "data": [{"b64_json": "new", "mime_type": "image/png"}],
            }, None

        with patch.object(api, "generate_image_payload", side_effect=fake_generate_image_payload):
            with TestClient(api.create_app()) as client:
                response = client.post(
                    "/v1/responses",
                    headers={"Authorization": f"Bearer {api.config.auth_key}"},
                    json={
                        "model": "gpt-5",
                        "previous_response_id": "resp_previous",
                        "input": [{"type": "input_text", "text": "draw second image"}],
                        "tools": [{"type": "image_generation", "model": "gpt-image-2", "size": "1025x1351"}],
                    },
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["previous_response_id"], "resp_previous")
        self.assertEqual(payload["metadata"]["size"], "1024x1344")
        self.assertEqual(payload["metadata"]["context_mode"], "text_history")
        self.assertIn("历史上下文", calls[0]["prompt"])
        self.assertEqual(calls[0]["size"], "1024x1344")

    def test_responses_previous_response_id_not_found_returns_404(self) -> None:
        with TestClient(api.create_app()) as client:
            response = client.post(
                "/v1/responses",
                headers={"Authorization": f"Bearer {api.config.auth_key}"},
                json={
                    "model": "gpt-5",
                    "previous_response_id": "resp_missing",
                    "input": [{"type": "input_text", "text": "draw"}],
                    "tools": [{"type": "image_generation", "model": "gpt-image-2"}],
                },
            )
        self.assertEqual(response.status_code, 404)

    def test_responses_input_replay_ignores_previous_image_output_item(self) -> None:
        calls: list[dict[str, object]] = []

        async def fake_generate_image_payload(**kwargs):
            calls.append(dict(kwargs))
            return {
                "created": 123,
                "data": [{"b64_json": "new", "mime_type": "image/png"}],
            }, None

        with patch.object(api, "generate_image_payload", side_effect=fake_generate_image_payload):
            with TestClient(api.create_app()) as client:
                response = client.post(
                    "/v1/responses",
                    headers={"Authorization": f"Bearer {api.config.auth_key}"},
                    json={
                        "model": "gpt-5",
                        "metadata": {"client_conversation_id": "conv-1", "turn": 2},
                        "input": [
                            {"type": "image_generation_call", "result": "old-image"},
                            {"type": "input_text", "text": "continue image"},
                        ],
                        "tools": [{"type": "image_generation", "model": "gpt-image-2"}],
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls[0]["prompt"], "continue image")

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

    def test_build_responses_payload_returns_text_when_image_is_missing(self) -> None:
        image_result = {
            "created": 123,
            "text_content": "cannot generate that image",
            "copied_text": "cannot generate that image",
            "data": [],
        }

        payload = api.build_responses_payload(
            response_id="resp_text_only",
            response_model="gpt-5.4",
            image_result=image_result,
            billing=None,
        )

        self.assertEqual(payload["text_content"], "cannot generate that image")
        self.assertEqual(payload["output_text"], "cannot generate that image")
        self.assertEqual(payload["output"][0]["type"], "message")
        self.assertEqual(payload["output"][0]["content"][0]["text"], "cannot generate that image")

    def test_generate_image_payload_returns_text_without_charging_when_image_is_missing(self) -> None:
        created = api.user_key_service.create_user_keys(
            count=1,
            quota=12,
            prefix="uk",
        )
        user_key = created["created_items"][0]["key"]
        context = api.resolve_auth_context(f"Bearer {user_key}")
        self.assertIsNotNone(context)
        assert context is not None

        class TextOnlyBackendService:
            def generate_with_pool(self, prompt: str, model: str, n: int, input_images=None, queue_request_id=None, size=None) -> dict:
                del prompt, model, n, input_images, queue_request_id, size
                return {
                    "created": 123,
                    "copied_text": "cannot generate that image",
                    "data": [],
                }

        async def fake_run_in_threadpool(func, *args):
            return func(*args)

        with patch.object(api, "run_in_threadpool", side_effect=fake_run_in_threadpool):
            result, billing = asyncio.run(
                api.generate_image_payload(
                    service=TextOnlyBackendService(),
                    context=context,
                    authorization=f"Bearer {user_key}",
                    prompt="draw a restricted image",
                    model="gpt-image-2",
                    n=1,
                )
            )

        self.assertEqual(result["data"], [])
        self.assertEqual(result["text_content"], "cannot generate that image")
        self.assertEqual(result["copied_text"], "cannot generate that image")
        self.assertIsNotNone(billing)
        assert billing is not None
        self.assertEqual(billing["charged_quota"], 0)
        self.assertEqual(billing["succeeded_count"], 0)
        self.assertEqual(billing["failed_count"], 1)
        current_item = api.user_key_service.get_user_key(user_key)
        self.assertIsNotNone(current_item)
        assert current_item is not None
        self.assertEqual(current_item["quota"], 12)

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
            def generate_with_pool(self, prompt: str, model: str, n: int, input_images=None, queue_request_id=None, size=None) -> dict:
                del prompt, model, n, input_images, queue_request_id, size
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
