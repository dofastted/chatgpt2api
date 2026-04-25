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


class FakeRouteAccountService:
    def __init__(self, account_type: str) -> None:
        self.account_type = account_type

    def next_token(self, excluded_tokens: set[str] | None = None) -> str:
        del excluded_tokens
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
    def __init__(self) -> None:
        self.routes: list[str] = []

    def generate_image(
        self,
        access_token: str,
        prompt: str,
        model: str,
        n: int,
        *,
        input_images: list[dict[str, str]] | None = None,
        route: str = "legacy",
    ) -> dict:
        del access_token, prompt, model, n, input_images
        self.routes.append(route)
        return {"created": 1, "data": [{"b64_json": "ok"}]}


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

    def test_route_selector_uses_images_for_free_and_responses_for_paid(self) -> None:
        self.assertEqual(select_image_route(account={"type": "Free"}), "images")
        self.assertEqual(select_image_route(account={"type": "Free"}, has_input_image=True), "images_edit")
        self.assertEqual(select_image_route(account={"type": "Plus"}), "responses")
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
            ("Plus", None, "responses"),
            ("Pro", None, "responses"),
            ("Team", [{"image_url": "data:image/png;base64,aW1n"}], "responses"),
        ]

        for account_type, input_images, expected_route in cases:
            service = BackendService(FakeRouteAccountService(account_type))
            gateway = RecordingGateway()
            service.image_gateway = gateway
            with patch("services.backend_service.config", SimpleNamespace(image_route_policy="plan_type")):
                service.generate_with_pool("draw", "gpt-image-2", 1, input_images=input_images)
            self.assertEqual(gateway.routes, [expected_route])

    def test_image_gateway_forwards_route_to_executor(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_executor(
            access_token: str,
            prompt: str,
            model: str,
            n: int,
            input_images: list[dict[str, str]] | None,
            route: str,
        ) -> dict:
            calls.append({"route": route, "input_images": input_images})
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

        self.assertEqual(calls, [{"route": "responses", "input_images": [{"image_url": "data:image/png;base64,aW1n"}]}])

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
