from __future__ import annotations

import json
import shutil
import tempfile
import unittest
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
