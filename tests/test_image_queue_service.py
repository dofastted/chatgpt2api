from __future__ import annotations

import unittest
from unittest.mock import patch

from services.image_queue_service import ImageQueueService


class ImageQueueServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ImageQueueService()

    def test_wait_for_turn_uses_fifo_position(self) -> None:
        first = self.service.create_ticket("user-1", "req-1", "first")
        second = self.service.create_ticket("user-1", "req-2", "second")

        self.assertEqual(first.request_id, "req-1")
        self.assertEqual(second.request_id, "req-2")
        snapshot = self.service.snapshot("user-1", request_id="req-2")
        self.assertEqual(snapshot["request"]["position"], 2)
        self.assertEqual(snapshot["request"]["ahead"], 1)

        running = self.service.wait_for_turn("req-1")
        self.assertEqual(running.status, "assigning_account")
        snapshot = self.service.snapshot("user-1", request_id="req-2")
        self.assertEqual(snapshot["request"]["position"], 1)
        self.assertEqual(snapshot["user"], {"waiting": 1, "running": 1, "active": 2})

    def test_per_user_waiting_limit_rejects_extra_request(self) -> None:
        self.service.PER_USER_ACTIVE_LIMIT = self.service.PER_USER_WAIT_LIMIT + 1
        for index in range(self.service.PER_USER_WAIT_LIMIT):
            self.service.create_ticket("user-1", f"req-{index}")

        with self.assertRaises(ValueError):
            self.service.create_ticket("user-1", "overflow")

    def test_per_user_active_limit_counts_waiting_and_running(self) -> None:
        self.service.PER_USER_ACTIVE_LIMIT = 2
        self.service.PER_USER_WAIT_LIMIT = 10
        self.service.create_ticket("user-1", "req-1")
        self.service.wait_for_turn("req-1")
        self.service.create_ticket("user-1", "req-2")

        with self.assertRaises(ValueError):
            self.service.create_ticket("user-1", "overflow")

    def test_global_waiting_limit_rejects_extra_request(self) -> None:
        self.service.GLOBAL_WAIT_LIMIT = 2
        self.service.create_ticket("user-1", "req-1")
        self.service.create_ticket("user-2", "req-2")

        with self.assertRaises(RuntimeError):
            self.service.create_ticket("user-3", "req-3")

    def test_finish_ticket_releases_running_count(self) -> None:
        self.service.create_ticket("user-1", "req-1")
        self.service.wait_for_turn("req-1")
        self.service.mark_status("req-1", "running")

        running_snapshot = self.service.snapshot("user-1", request_id="req-1")
        self.assertEqual(running_snapshot["user"], {"waiting": 0, "running": 1, "active": 1})
        self.assertEqual(running_snapshot["request"]["status"], "running")

        self.service.finish_ticket("req-1")
        finished_snapshot = self.service.snapshot("user-1", request_id="req-1")
        self.assertEqual(finished_snapshot["user"], {"waiting": 0, "running": 0, "active": 0})
        self.assertEqual(finished_snapshot["request"]["status"], "finished")

    def test_finish_stale_tickets_releases_running_count(self) -> None:
        with patch("services.image_queue_service.time", side_effect=[100.0, 100.0, 100.0]):
            self.service.create_ticket("user-1", "req-1")
            self.service.wait_for_turn("req-1")
        self.service.mark_status("req-1", "running")

        with patch("services.image_queue_service.time", return_value=401.0):
            stale_ids = self.service.finish_stale_tickets(max_age_seconds=300, error="timed out")

        self.assertEqual(stale_ids, ["req-1"])
        with patch("services.image_queue_service.time", return_value=402.0):
            snapshot = self.service.snapshot("user-1", request_id="req-1")
        self.assertEqual(snapshot["user"], {"waiting": 0, "running": 0, "active": 0})
        self.assertEqual(snapshot["request"]["status"], "failed")
        self.assertEqual(snapshot["request"]["error"], "timed out")

    def test_global_start_limit_keeps_extra_requests_waiting(self) -> None:
        self.service.GLOBAL_START_LIMIT = 1
        self.service.GLOBAL_START_WINDOW_SECONDS = 60.0
        self.service.create_ticket("user-1", "req-1")
        self.service.create_ticket("user-2", "req-2")

        with patch("services.image_queue_service.time", side_effect=[100.0, 100.0, 100.0, 100.0, 100.0]):
            self.service.wait_for_turn("req-1")
            snapshot = self.service.snapshot("user-2", request_id="req-2")

        self.assertEqual(snapshot["request"]["status"], "waiting")
        self.assertEqual(snapshot["request"]["position"], 1)
        self.assertEqual(snapshot["global"]["starts_in_window"], 1)
        self.assertGreater(snapshot["global"]["start_wait_seconds"], 0)

    def test_snapshot_expires_old_start_timestamps_before_reporting_stats(self) -> None:
        self.service.GLOBAL_START_LIMIT = 1
        self.service.GLOBAL_START_WINDOW_SECONDS = 60.0
        self.service._start_timestamps.append(100.0)

        with patch("services.image_queue_service.time", return_value=161.0):
            snapshot = self.service.snapshot("user-1")

        self.assertEqual(snapshot["global"]["starts_in_window"], 0)
        self.assertEqual(snapshot["global"]["start_wait_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
