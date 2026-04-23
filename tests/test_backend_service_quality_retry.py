from __future__ import annotations

import unittest
from unittest.mock import patch

from services.backend_service import BackendService
from services.image_service import ImageGenerationError


class FakeAccountService:
    def __init__(self) -> None:
        self.tokens = ["bad-token", "good-token"]
        self.index = 0
        self.removed: list[str] = []
        self.failed: list[str] = []
        self.accounts = {
            "bad-token": {"access_token": "bad-token", "quota": 5, "status": "正常"},
            "good-token": {"access_token": "good-token", "quota": 5, "status": "正常"},
        }

    def next_token(self, excluded_tokens: set[str] | None = None) -> str:
        excluded = excluded_tokens or set()
        for token in self.tokens:
            if token not in excluded and token not in self.removed:
                return token
        raise RuntimeError("no token")

    def get_account(self, access_token: str) -> dict | None:
        item = self.accounts.get(access_token)
        return dict(item) if item is not None else None

    def fetch_remote_info(self, access_token: str) -> dict:
        item = self.accounts.get(access_token) or {"access_token": access_token}
        return {**item, "status": "正常", "quota": 5}

    def update_account(self, access_token: str, updates: dict) -> dict:
        next_item = {
            **(self.accounts.get(access_token) or {"access_token": access_token}),
            **updates,
        }
        self.accounts[access_token] = next_item
        return dict(next_item)

    def mark_image_result(self, access_token: str, success: bool) -> dict:
        next_item = {
            **(self.accounts.get(access_token) or {"access_token": access_token}),
            "quota": 5,
            "status": "正常",
            "success": success,
        }
        self.accounts[access_token] = next_item
        return dict(next_item)

    def remove_token(self, access_token: str) -> None:
        self.removed.append(access_token)

    def mark_request_failure(self, access_token: str) -> dict:
        self.failed.append(access_token)
        return {"access_token": access_token, "quota": 5, "status": "正常"}


class BackendServiceQualityRetryTests(unittest.TestCase):
    def test_generate_with_pool_skips_low_quality_token_and_uses_next_one(self) -> None:
        service = BackendService(FakeAccountService())

        def fake_generate(
            access_token: str,
            prompt: str,
            model: str,
            n: int,
            input_images: list[dict[str, str]] | None = None,
        ) -> dict:
            del prompt, model, n, input_images
            if access_token == "bad-token":
                raise ImageGenerationError("low quality text render for file: file-1")
            return {"created": 1, "data": [{"b64_json": "ok"}]}

        with patch("services.backend_service.generate_image_result", side_effect=fake_generate):
            payload = service.generate_with_pool("draw ABCD", "gpt-image-2", 1)

        self.assertEqual(payload["data"][0]["b64_json"], "ok")

    def test_generate_with_pool_skips_transient_failure_and_uses_next_token(self) -> None:
        service = BackendService(FakeAccountService())

        def fake_generate(
            access_token: str,
            prompt: str,
            model: str,
            n: int,
            input_images: list[dict[str, str]] | None = None,
        ) -> dict:
            del prompt, model, n, input_images
            if access_token == "bad-token":
                raise ImageGenerationError("download image failed")
            return {"created": 1, "data": [{"b64_json": "ok"}]}

        with patch("services.backend_service.generate_image_result", side_effect=fake_generate):
            payload = service.generate_with_pool("draw ABCD", "gpt-image-2", 1)

        self.assertEqual(payload["data"][0]["b64_json"], "ok")

    def test_generate_with_pool_retries_next_token_when_upstream_returns_524(self) -> None:
        service = BackendService(FakeAccountService())

        def fake_generate(
            access_token: str,
            prompt: str,
            model: str,
            n: int,
            input_images: list[dict[str, str]] | None = None,
        ) -> dict:
            del prompt, model, n, input_images
            if access_token == "bad-token":
                raise ImageGenerationError("conversation failed: 524")
            return {"created": 1, "data": [{"b64_json": "ok"}]}

        with patch("services.backend_service.generate_image_result", side_effect=fake_generate):
            payload = service.generate_with_pool("draw ABCD", "gpt-image-2", 1)

        self.assertEqual(payload["data"][0]["b64_json"], "ok")

    def test_generate_with_pool_retries_next_token_when_upstream_returns_json_429(self) -> None:
        service = BackendService(FakeAccountService())

        def fake_generate(
            access_token: str,
            prompt: str,
            model: str,
            n: int,
            input_images: list[dict[str, str]] | None = None,
        ) -> dict:
            del prompt, model, n, input_images
            if access_token == "bad-token":
                raise ImageGenerationError('{"detail":{"message":"rate limited","status_code":429}}')
            return {"created": 1, "data": [{"b64_json": "ok"}]}

        with patch("services.backend_service.generate_image_result", side_effect=fake_generate):
            payload = service.generate_with_pool("draw ABCD", "gpt-image-2", 1)

        self.assertEqual(payload["data"][0]["b64_json"], "ok")


if __name__ == "__main__":
    unittest.main()
