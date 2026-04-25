from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from services import api
from services.chat_image.account_import import normalize_account_carrier
from services.chat_image.route_selector import select_image_route


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
