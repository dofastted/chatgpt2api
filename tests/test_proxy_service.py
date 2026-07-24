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
