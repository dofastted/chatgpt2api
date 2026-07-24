from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from services.proxy_service import ProxyService


class ProxyServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="chatgpt2api-proxy-service-"))
        self.store_file = self.temp_dir / "proxies.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def make_service(self, items: list[dict] | None = None) -> ProxyService:
        if items is not None:
            self.store_file.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        elif self.store_file.exists():
            self.store_file.unlink()
        return ProxyService(self.store_file)

    def test_get_enabled_proxy_url_defaults_to_windows_local_proxy(self) -> None:
        service = self.make_service()

        self.assertEqual(service.get_enabled_proxy_url(), ProxyService.DEFAULT_PROXY_URL)

    def test_get_enabled_proxy_url_uses_vps_deployment_profile(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CHATGPT2API_DEFAULT_PROXY_URL": "",
                "CHATGPT2API_DEPLOYMENT_PROFILE": "vps",
            },
        ):
            service = self.make_service()
            self.assertEqual(service.get_enabled_proxy_url(), "http://172.20.0.1:3208")

    def test_connection_masks_proxy_credentials(self) -> None:
        service = self.make_service(
            [
                {
                    "id": "proxy-1",
                    "name": "authenticated proxy",
                    "protocol": "http",
                    "host": "proxy.example.com",
                    "port": 8080,
                    "username": "secret-user",
                    "password": "secret-password",
                    "enabled": True,
                }
            ]
        )
        session = MagicMock()
        session.get.return_value.status_code = 403

        with patch("services.proxy_service.Session", return_value=session):
            result = service.test_connection()

        self.assertTrue(result["reachable"])
        self.assertEqual(result["status_code"], 403)
        self.assertEqual(result["source"], "configured")
        self.assertEqual(result["proxy_url"], "http://***:***@proxy.example.com:8080")
        self.assertNotIn("secret-user", result["proxy_url"])
        self.assertNotIn("secret-password", result["proxy_url"])
        session.close.assert_called_once_with()

    def test_public_proxy_payloads_never_expose_credentials(self) -> None:
        service = self.make_service(
            [
                {
                    "id": "proxy-1",
                    "name": "authenticated proxy",
                    "protocol": "http",
                    "host": "proxy.example.com",
                    "port": 8080,
                    "username": "secret-user",
                    "password": "secret-password",
                    "enabled": True,
                }
            ]
        )

        item = service.list_public_items()[0]
        serialized = json.dumps(item)

        self.assertIsNone(item["username"])
        self.assertIsNone(item["password"])
        self.assertTrue(item["has_auth"])
        self.assertEqual(item["url"], "http://***:***@proxy.example.com:8080")
        self.assertEqual(
            service.get_public_enabled_proxy_url(),
            "http://***:***@proxy.example.com:8080",
        )
        self.assertNotIn("secret-user", serialized)
        self.assertNotIn("secret-password", serialized)

    def test_upsert_preserves_credentials_when_public_client_omits_them(self) -> None:
        service = self.make_service(
            [
                {
                    "id": "proxy-1",
                    "name": "authenticated proxy",
                    "protocol": "http",
                    "host": "proxy.example.com",
                    "port": 8080,
                    "username": "secret-user",
                    "password": "secret-password",
                    "enabled": True,
                }
            ]
        )

        result = service.upsert_proxy(
            {
                "id": "proxy-1",
                "name": "renamed proxy",
                "protocol": "http",
                "host": "proxy.example.com",
                "port": 8080,
                "enabled": True,
            }
        )

        self.assertEqual(
            service.get_enabled_proxy_url(),
            "http://secret-user:secret-password@proxy.example.com:8080",
        )
        self.assertEqual(result["name"], "renamed proxy")
        self.assertIsNone(result["username"])
        self.assertIsNone(result["password"])
        self.assertTrue(result["has_auth"])

    def test_get_enabled_proxy_url_prefers_enabled_proxy(self) -> None:
        service = self.make_service(
            [
                {
                    "id": "proxy-1",
                    "name": "local proxy",
                    "protocol": "http",
                    "host": "proxy.example.com",
                    "port": 8080,
                    "enabled": True,
                }
            ]
        )

        self.assertEqual(service.get_enabled_proxy_url(), "http://proxy.example.com:8080")


if __name__ == "__main__":
    unittest.main()
