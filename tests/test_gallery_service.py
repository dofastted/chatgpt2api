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

    def test_import_seed_when_user_submission_already_exists(self) -> None:
        submitted = self.service.submit_item(
            auth_token="plain-user-key",
            payload={
                "prompt": "生成一张海边日落照片",
                "image_url": "data:image/png;base64,ZmFrZQ==",
                "mime_type": "image/png",
            },
        )

        items = self.service.list_public_items()

        self.assertEqual([item["id"] for item in items], ["seed-2"])
        with self.store.connect() as connection:
            submitted_row = connection.execute(
                "SELECT status FROM gallery_items WHERE id = ?",
                (submitted["id"],),
            ).fetchone()
            seed_count = connection.execute(
                "SELECT COUNT(*) AS count FROM gallery_items WHERE source = 'seed'",
            ).fetchone()
        self.assertIsNotNone(submitted_row)
        self.assertEqual(submitted_row["status"], "pending")
        self.assertEqual(seed_count["count"], 1)

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

    def test_admin_approval_appends_submission_to_public_gallery(self) -> None:
        before_items = self.service.list_public_items()
        item = self.service.submit_item(
            auth_token="plain-user-key",
            payload={
                "prompt": "生成一张海边日落照片",
                "image_url": "data:image/png;base64,ZmFrZQ==",
                "mime_type": "image/png",
            },
        )

        self.service.admin_update_item(item["id"], {"action": "approve"})
        after_items = self.service.list_public_items()

        self.assertEqual(len(after_items), len(before_items) + 1)
        self.assertIn("seed-2", {entry["id"] for entry in after_items})
        self.assertIn(item["id"], {entry["id"] for entry in after_items})
        approved_item = next(entry for entry in after_items if entry["id"] == item["id"])
        self.assertEqual(approved_item["prompt"], "生成一张海边日落照片")
        self.assertEqual(len(approved_item["assets"]), 1)

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
            headers={"Authorization": f"Bearer {api.config.auth_key}"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["id"], "seed-7")

    def test_user_submission_and_admin_review_boundaries(self) -> None:
        submit_response = self.client.post(
            "/api/gallery/submissions",
            headers={"Authorization": f"Bearer {api.config.auth_key}"},
            json={
                "prompt": "生成一张夜晚城市霓虹插画",
                "image_url": "data:image/png;base64,ZmFrZQ==",
            },
        )
        self.assertEqual(submit_response.status_code, 200)
        item_id = submit_response.json()["item"]["id"]

        user_admin_response = self.client.get(
            "/api/admin/gallery",
            headers={"Authorization": f"Bearer {api.config.auth_key}"},
        )
        self.assertEqual(user_admin_response.status_code, 403)

        admin_response = self.client.patch(
            f"/api/admin/gallery/{item_id}",
            headers={"Authorization": f"Bearer {api.config.admin_auth_key}"},
            json={"action": "approve", "is_pinned": True, "sort_order": -10},
        )
        self.assertEqual(admin_response.status_code, 200)
        item = admin_response.json()["item"]
        self.assertEqual(item["status"], "published")
        self.assertTrue(item["is_pinned"])

    def test_gallery_lists_strip_base64_assets_but_asset_endpoint_serves_image(self) -> None:
        submit_response = self.client.post(
            "/api/gallery/submissions",
            headers={"Authorization": f"Bearer {api.config.auth_key}"},
            json={
                "prompt": "生成一张适合画廊展示的花园照片",
                "image_url": "data:image/png;base64,ZmFrZQ==",
                "mime_type": "image/png",
            },
        )
        self.assertEqual(submit_response.status_code, 200)
        item_id = submit_response.json()["item"]["id"]

        admin_response = self.client.patch(
            f"/api/admin/gallery/{item_id}",
            headers={"Authorization": f"Bearer {api.config.admin_auth_key}"},
            json={"action": "approve"},
        )
        self.assertEqual(admin_response.status_code, 200)

        list_response = self.client.get(
            "/api/gallery/public",
            headers={"Authorization": f"Bearer {api.config.auth_key}"},
        )
        self.assertEqual(list_response.status_code, 200)
        list_item = next(item for item in list_response.json()["items"] if item["id"] == item_id)
        asset_url = list_item["assets"][0]["url"]
        self.assertTrue(asset_url.startswith("/api/gallery/assets/"))
        self.assertNotIn("data:image", json.dumps(list_response.json()))

        asset_response = self.client.get(asset_url)
        self.assertEqual(asset_response.status_code, 200)
        self.assertEqual(asset_response.headers["content-type"], "image/png")
        self.assertEqual(asset_response.content, b"fake")

        admin_list_response = self.client.get(
            "/api/admin/gallery",
            headers={"Authorization": f"Bearer {api.config.admin_auth_key}"},
        )
        self.assertEqual(admin_list_response.status_code, 200)
        admin_list_item = next(item for item in admin_list_response.json()["items"] if item["id"] == item_id)
        self.assertEqual(admin_list_item["assets"][0]["url"], asset_url)
        self.assertNotIn("data:image", json.dumps(admin_list_response.json()))

    def test_gallery_asset_endpoint_rejects_non_base64_data_images(self) -> None:
        item = self.gallery_service.submit_item(
            auth_token="plain-user-key",
            payload={
                "prompt": "生成一张适合画廊展示的手绘插画",
                "image_url": "data:image/svg+xml,<svg></svg>",
                "mime_type": "image/svg+xml",
            },
        )
        asset_id = item["assets"][0]["asset_id"]

        asset_response = self.client.get(f"/api/gallery/assets/{asset_id}")
        self.assertEqual(asset_response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
