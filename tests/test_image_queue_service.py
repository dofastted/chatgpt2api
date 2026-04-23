from __future__ import annotations

import unittest

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
        self.assertEqual(snapshot["user"], {"waiting": 1, "running": 1})

    def test_per_user_waiting_limit_rejects_extra_request(self) -> None:
        for index in range(self.service.PER_USER_WAIT_LIMIT):
            self.service.create_ticket("user-1", f"req-{index}")

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
        self.assertEqual(running_snapshot["user"], {"waiting": 0, "running": 1})
        self.assertEqual(running_snapshot["request"]["status"], "running")

        self.service.finish_ticket("req-1")
        finished_snapshot = self.service.snapshot("user-1", request_id="req-1")
        self.assertEqual(finished_snapshot["user"], {"waiting": 0, "running": 0})
        self.assertEqual(finished_snapshot["request"]["status"], "finished")


if __name__ == "__main__":
    unittest.main()
