from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from services import api
from services.gallery_service import GalleryService, is_seed_prompt_usable
from services.sqlite_store import SQLiteStore


class FakeThread:
    def join(self, timeout: float | None = None) -> None:
        return None


class GalleryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="chatgpt2api-gallery-tests-"))
        self.store = SQLiteStore(self.temp_dir / "gallery.sqlite3")
        self.seed_file = self.temp_dir / "gallery-ui-seed.json"
        self.dimensions_file = self.temp_dir / "gallery-image-dimensions.json"
        self.seed_file.write_text(
            json.dumps(
                [
                    {
                        "id": 1,
                        "postNumber": 1,
                        "username": "bad",
                        "imageIndex": 1,
                        "title": "bad",
                        "imageUrl": "https://example.com/bad.png",
                        "prompt": "未提供",
                    },
                    {
                        "id": 2,
                        "postNumber": 2,
                        "username": "good",
                        "imageIndex": 1,
                        "title": "good",
                        "imageUrl": "https://example.com/good.png",
                        "prompt": "生成一张成都的宣传海报",
                    },
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.dimensions_file.write_text(
            json.dumps([{"id": 2, "width": 640, "height": 800, "aspectRatio": 0.8}]),
            encoding="utf-8",
        )
        self.service = GalleryService(
            self.store,
            seed_file=self.seed_file,
            dimensions_file=self.dimensions_file,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_seed_prompt_filter_keeps_short_generation_intent(self) -> None:
        self.assertFalse(is_seed_prompt_usable("未提供"))
        self.assertFalse(is_seed_prompt_usable("哈哈我也试了一下"))
        self.assertTrue(is_seed_prompt_usable("生成一张成都的宣传海报"))

    def test_import_seed_filters_placeholder_prompts(self) -> None:
        items = self.service.list_public_items()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "seed-2")
        self.assertEqual(items[0]["prompt"], "生成一张成都的宣传海报")
        self.assertEqual(items[0]["assets"][0]["width"], 640)

    def test_submission_stores_owner_hash_and_admin_can_publish(self) -> None:
        item = self.service.submit_item(
            auth_token="plain-user-key",
            payload={
                "prompt": "生成一张海边日落照片",
                "image_url": "data:image/png;base64,ZmFrZQ==",
                "mime_type": "image/png",
            },
        )

        self.assertEqual(item["status"], "pending")
        self.assertNotEqual(item["submitted_by_owner_id"], "plain-user-key")
        self.assertEqual(len(str(item["submitted_by_owner_id"])), 64)

        published = self.service.admin_update_item(item["id"], {"action": "approve"})
        self.assertEqual(published["status"], "published")
        self.assertTrue(published["visibility"])

    def test_public_event_only_updates_visible_published_items(self) -> None:
        item = self.service.submit_item(
            auth_token="plain-user-key",
            payload={
                "prompt": "生成一张海边日落照片",
                "image_url": "data:image/png;base64,ZmFrZQ==",
                "mime_type": "image/png",
            },
        )

        self.assertIsNone(self.service.record_event(item["id"], "click"))

        published = self.service.admin_update_item(item["id"], {"action": "approve"})
        clicked = self.service.record_event(published["id"], "click")
        self.assertIsNotNone(clicked)
        self.assertEqual(clicked["click_count"], 1)

        self.service.admin_update_item(item["id"], {"action": "hide"})
        self.assertIsNone(self.service.record_event(item["id"], "use"))


class GalleryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="chatgpt2api-gallery-api-tests-"))
        self.store = SQLiteStore(self.temp_dir / "gallery-api.sqlite3")
        self.seed_file = self.temp_dir / "gallery-ui-seed.json"
        self.dimensions_file = self.temp_dir / "gallery-image-dimensions.json"
        self.seed_file.write_text(
            json.dumps(
                [
                    {
                        "id": 7,
                        "postNumber": 7,
                        "username": "seed",
                        "imageIndex": 1,
                        "title": "seed",
                        "imageUrl": "https://example.com/seed.png",
                        "prompt": "生成一张适合画廊展示的建筑海报",
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.dimensions_file.write_text("[]", encoding="utf-8")
        self.gallery_service = GalleryService(
            self.store,
            seed_file=self.seed_file,
            dimensions_file=self.dimensions_file,
        )
        patchers = [
            patch.object(api, "gallery_service", self.gallery_service),
            patch.object(api, "start_limited_account_watcher", side_effect=lambda stop_event: FakeThread()),
            patch.object(api, "start_backup_scheduler", side_effect=lambda stop_event: FakeThread()),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(api.create_app())

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_public_gallery_requires_auth_and_imports_seed(self) -> None:
        unauthorized = self.client.get("/api/gallery/public")
        self.assertEqual(unauthorized.status_code, 401)

        response = self.client.get(
            "/api/gallery/public",
            headers={"Authorization": "Bearer test-auth-key"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["id"], "seed-7")

    def test_user_submission_and_admin_review_boundaries(self) -> None:
        submit_response = self.client.post(
            "/api/gallery/submissions",
            headers={"Authorization": "Bearer test-auth-key"},
            json={
                "prompt": "生成一张夜晚城市霓虹插画",
                "image_url": "data:image/png;base64,ZmFrZQ==",
            },
        )
        self.assertEqual(submit_response.status_code, 200)
        item_id = submit_response.json()["item"]["id"]

        user_admin_response = self.client.get(
            "/api/admin/gallery",
            headers={"Authorization": "Bearer test-auth-key"},
        )
        self.assertEqual(user_admin_response.status_code, 403)

        admin_response = self.client.patch(
            f"/api/admin/gallery/{item_id}",
            headers={"Authorization": "Bearer test-admin-key"},
            json={"action": "approve", "is_pinned": True, "sort_order": -10},
        )
        self.assertEqual(admin_response.status_code, 200)
        item = admin_response.json()["item"]
        self.assertEqual(item["status"], "published")
        self.assertTrue(item["is_pinned"])


if __name__ == "__main__":
    unittest.main()
