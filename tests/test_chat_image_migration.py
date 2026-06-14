from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from services import api
from services.backend_service import BackendService
from services.chat_image.account_import import normalize_account_carrier
from services.chat_image.gateway import ImageGateway
from services.chat_image.route_selector import select_image_route
from services.image_service import ImageGenerationError, is_token_invalid_error


class FakeRouteAccountService:
    def __init__(self, account_type: str) -> None:
        self.account_type = account_type
        self.prefer_input_image_values: list[bool] = []

    def next_token(self, excluded_tokens: set[str] | None = None, *, prefer_input_image: bool = False) -> str:
        del excluded_tokens
        self.prefer_input_image_values.append(prefer_input_image)
        return "token-1"

    def get_account(self, access_token: str) -> dict | None:
        return {"access_token": access_token, "quota": 5, "status": "正常", "type": self.account_type}

    def fetch_remote_info(self, access_token: str) -> dict:
        return self.get_account(access_token) or {}

    def update_account(self, access_token: str, updates: dict) -> dict:
        return {**(self.get_account(access_token) or {}), **updates}

    def mark_image_result(self, access_token: str, success: bool) -> dict:
        return {**(self.get_account(access_token) or {}), "success": success}


class RecordingGateway:
    def __init__(self, fail_routes: set[str] | None = None, route_errors: dict[str, str] | None = None) -> None:
        self.routes: list[str] = []
        self.fail_routes = fail_routes or set()
        self.route_errors = route_errors or {}

    def generate_image(
        self,
        access_token: str,
        prompt: str,
        model: str,
        n: int,
        *,
        input_images: list[dict[str, str]] | None = None,
        route: str = "legacy",
        size: str | None = None,
    ) -> dict:
        del access_token, prompt, model, n, input_images, size
        self.routes.append(route)
        if route in self.route_errors:
            raise ImageGenerationError(self.route_errors[route])
        if route in self.fail_routes:
            raise ImageGenerationError("responses failed: 429")
        return {"created": 1, "data": [{"b64_json": "ok"}]}


def patched_backend_config(**overrides: object) -> SimpleNamespace:
    values = {
        "image_route_policy": "plan_type",
        "image_generation_max_account_attempts": 4,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ChatImageMigrationTests(unittest.TestCase):
    def test_single_account_carrier_normalizes_plan_and_sanitizes_auth_data(self) -> None:
        accounts = normalize_account_carrier(
            json.dumps(
                {
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "id_token": "id-1",
                    "email": "user@example.com",
                    "plan_type": "team",
                    "extra": {"note": "ok", "refresh_token": "hidden"},
                }
            )
        )

        self.assertEqual(len(accounts), 1)
        account = accounts[0]
        self.assertEqual(account["access_token"], "access-1")
        self.assertEqual(account["refresh_token"], "refresh-1")
        self.assertEqual(account["type"], "Team")
        self.assertEqual(account["auth_source"], "single_json")
        self.assertNotIn("refresh_token", account["auth_data"])

    def test_account_carrier_preserves_runtime_snapshot_fields(self) -> None:
        accounts = normalize_account_carrier(
            {
                "accounts": [
                    {
                        "access_token": "access-1",
                        "category": "捐赠",
                        "status": "正常",
                        "type": "Plus",
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
            }
        )

        self.assertEqual(len(accounts), 1)
        account = accounts[0]
        self.assertEqual(account["category"], "捐赠")
        self.assertEqual(account["status"], "正常")
        self.assertEqual(account["quota"], 7)
        self.assertFalse(account["needs_refresh"])
        self.assertEqual(account["limits_progress"][0]["remaining"], 7)

    def test_token_expired_error_is_invalid_token(self) -> None:
        self.assertTrue(
            is_token_invalid_error(
                '{"code":"token_expired","message":"Provided authentication token is expired."}'
            )
        )

    def test_sub2api_accounts_carrier_extracts_credentials_and_dedupes(self) -> None:
        accounts = normalize_account_carrier(
            {
                "accounts": [
                    {
                        "name": "one",
                        "platform": "openai",
                        "credentials": {
                            "access_token": "access-1",
                            "refresh_token": "refresh-1",
                            "email": "user@example.com",
                            "plan_type": "pro",
                            "model_mapping": {"x": "y"},
                        },
                        "proxy_key": "proxy-a",
                        "concurrency": 10,
                        "priority": 1,
                    },
                    {
                        "credentials": {
                            "access_token": "access-1",
                            "plan_type": "free",
                        },
                    },
                ]
            }
        )

        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["type"], "Pro")
        self.assertEqual(accounts[0]["auth_source"], "sub2api_accounts")
        self.assertEqual(accounts[0]["proxy_key"], "proxy-a")
        self.assertEqual(accounts[0]["model_mapping"], {"x": "y"})

    def test_external_nested_account_payload_preserves_session_fingerprint(self) -> None:
        accounts = normalize_account_carrier(
            {
                "data": {
                    "items": [
                        {
                            "auth": {
                                "authorization": "Bearer " + "x" * 48,
                                "refreshToken": "refresh-2",
                            },
                            "session": {
                                "oaiDeviceId": "device-2",
                                "oaiSessionId": "session-2",
                                "userAgent": "agent-2",
                            },
                        }
                    ]
                }
            }
        )

        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["access_token"], "x" * 48)
        self.assertEqual(accounts[0]["refresh_token"], "refresh-2")
        self.assertEqual(accounts[0]["oai-device-id"], "device-2")
        self.assertEqual(accounts[0]["oai-session-id"], "session-2")
        self.assertEqual(accounts[0]["user-agent"], "agent-2")

    def test_route_selector_uses_images_for_text_only_and_responses_for_paid_input_images(self) -> None:
        self.assertEqual(select_image_route(account={"type": "Free"}), "images")
        self.assertEqual(select_image_route(account={"type": "Free"}, has_input_image=True), "images_edit")
        self.assertEqual(select_image_route(account={"type": "Plus"}), "images")
        self.assertEqual(select_image_route(account={"type": "Team"}, has_input_image=True), "responses")

    def test_route_selector_policy_overrides_are_available_for_tests(self) -> None:
        self.assertEqual(select_image_route(account={"type": "Plus"}, policy="force_images"), "images")
        self.assertEqual(
            select_image_route(account={"type": "Free"}, has_input_image=True, policy="force_responses"),
            "responses",
        )
        self.assertEqual(select_image_route(account={"type": "Plus"}, policy="legacy"), "legacy")

    def test_backend_service_passes_plan_route_to_gateway(self) -> None:
        cases = [
            ("Free", None, "images"),
            ("Free", [{"image_url": "data:image/png;base64,aW1n"}], "images_edit"),
            ("Plus", None, "images"),
            ("Pro", None, "images"),
            ("Team", [{"image_url": "data:image/png;base64,aW1n"}], "responses"),
        ]

        for account_type, input_images, expected_route in cases:
            service = BackendService(FakeRouteAccountService(account_type))
            gateway = RecordingGateway()
            service.image_gateway = gateway
            with patch("services.backend_service.config", patched_backend_config()):
                service.generate_with_pool("draw", "gpt-image-2", 1, input_images=input_images)
            self.assertEqual(gateway.routes, [expected_route])

    def test_backend_service_prefers_input_image_account_history_for_input_image_requests(self) -> None:
        account_service = FakeRouteAccountService("Team")
        service = BackendService(account_service)
        service.image_gateway = RecordingGateway()

        with patch("services.backend_service.config", patched_backend_config()):
            service.generate_with_pool(
                "draw",
                "gpt-image-2",
                1,
                input_images=[{"image_url": "data:image/png;base64,aW1n"}],
            )

        self.assertEqual(account_service.prefer_input_image_values, [True])

    def test_backend_service_falls_back_to_images_when_responses_policy_is_rate_limited(self) -> None:
        service = BackendService(FakeRouteAccountService("Team"))
        gateway = RecordingGateway(fail_routes={"responses"})
        service.image_gateway = gateway

        with patch("services.backend_service.config", patched_backend_config(image_route_policy="force_responses")):
            payload = service.generate_with_pool("draw", "gpt-image-2", 1)

        self.assertEqual(payload["data"][0]["b64_json"], "ok")
        self.assertEqual(gateway.routes, ["responses", "images"])

    def test_backend_service_does_not_fallback_to_images_edit_for_paid_input_images(self) -> None:
        self.assertIsNone(
            BackendService._fallback_route_for(
                "responses",
                [{"image_url": "data:image/png;base64,aW1n"}],
            )
        )
        self.assertEqual(BackendService._fallback_route_for("responses", None), "images")

    def test_backend_service_treats_responses_input_image_400_as_next_account_retry(self) -> None:
        self.assertTrue(
            BackendService._is_responses_input_image_rejection(
                ImageGenerationError("responses failed: 400"),
                [{"file_id": "upload-1"}],
            )
        )
        self.assertFalse(
            BackendService._is_responses_input_image_rejection(
                ImageGenerationError("responses failed: 400"),
                None,
            )
        )

    def test_image_gateway_forwards_route_to_executor(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_executor(
            access_token: str,
            prompt: str,
            model: str,
            n: int,
            input_images: list[dict[str, str]] | None,
            route: str,
            size: str | None = None,
        ) -> dict:
            calls.append({"route": route, "input_images": input_images, "size": size})
            return {"created": 1, "data": [{"b64_json": "ok"}]}

        gateway = ImageGateway(fake_executor)
        gateway.generate_image(
            "token",
            "draw",
            "gpt-image-2",
            1,
            input_images=[{"image_url": "data:image/png;base64,aW1n"}],
            route="responses",
        )

        self.assertEqual(
            calls,
            [{"route": "responses", "input_images": [{"image_url": "data:image/png;base64,aW1n"}], "size": None}],
        )

    def test_singular_response_endpoint_is_not_registered(self) -> None:
        client = TestClient(api.create_app())

        response = client.post(
            "/v1/response",
            headers={"Authorization": "Bearer test-auth-key"},
            json={"model": "gpt-5", "input": "draw", "tools": [{"type": "image_generation"}]},
        )

        self.assertIn(response.status_code, {404, 405})


if __name__ == "__main__":
    unittest.main()
