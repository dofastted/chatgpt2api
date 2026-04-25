from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from threading import Condition
from time import time
from typing import Any
from uuid import uuid4


@dataclass
class ImageQueueTicket:
    request_id: str
    auth_token: str
    title: str = ""
    status: str = "waiting"
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None


class ImageQueueService:
    PER_USER_WAIT_LIMIT = 10
    GLOBAL_WAIT_LIMIT = 2000
    GLOBAL_START_LIMIT = 60
    GLOBAL_START_WINDOW_SECONDS = 60.0
    RECENT_TTL_SECONDS = 600

    def __init__(self) -> None:
        self._condition = Condition()
        self._waiting_order: deque[str] = deque()
        self._start_timestamps: deque[float] = deque()
        self._tickets: dict[str, ImageQueueTicket] = {}
        self._recent: dict[str, ImageQueueTicket] = {}
        self._user_waiting: dict[str, int] = {}
        self._user_running: dict[str, int] = {}
        self._global_running = 0

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _new_request_id(cls) -> str:
        return f"iq_{uuid4().hex}"

    @staticmethod
    def _now_text(timestamp: float | None) -> str | None:
        if timestamp is None:
            return None
        return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")

    def _cleanup_recent_locked(self) -> None:
        now_value = time()
        expired = [
            request_id
            for request_id, ticket in self._recent.items()
            if ticket.finished_at is not None and now_value - ticket.finished_at > self.RECENT_TTL_SECONDS
        ]
        for request_id in expired:
            self._recent.pop(request_id, None)

    def _cleanup_start_timestamps_locked(self, now_value: float | None = None) -> None:
        current_time = time() if now_value is None else now_value
        cutoff = current_time - float(self.GLOBAL_START_WINDOW_SECONDS)
        while self._start_timestamps and self._start_timestamps[0] <= cutoff:
            self._start_timestamps.popleft()

    def _global_start_wait_seconds_locked(self, now_value: float | None = None) -> float:
        current_time = time() if now_value is None else now_value
        self._cleanup_start_timestamps_locked(current_time)
        if len(self._start_timestamps) < int(self.GLOBAL_START_LIMIT):
            return 0.0
        earliest = self._start_timestamps[0]
        return max(0.0, earliest + float(self.GLOBAL_START_WINDOW_SECONDS) - current_time)

    def _decrement_user_waiting_locked(self, auth_token: str) -> None:
        current = max(0, int(self._user_waiting.get(auth_token) or 0) - 1)
        if current:
            self._user_waiting[auth_token] = current
        else:
            self._user_waiting.pop(auth_token, None)

    def _decrement_user_running_locked(self, auth_token: str) -> None:
        current = max(0, int(self._user_running.get(auth_token) or 0) - 1)
        if current:
            self._user_running[auth_token] = current
        else:
            self._user_running.pop(auth_token, None)

    def create_ticket(self, auth_token: str, request_id: str | None = None, title: str | None = None) -> ImageQueueTicket:
        normalized_auth_token = self._clean_text(auth_token) or "__anonymous__"
        normalized_request_id = self._clean_text(request_id) or self._new_request_id()
        with self._condition:
            self._cleanup_recent_locked()
            if len(self._waiting_order) >= self.GLOBAL_WAIT_LIMIT:
                raise RuntimeError(f"global image queue is full, max_waiting={self.GLOBAL_WAIT_LIMIT}")
            user_waiting = int(self._user_waiting.get(normalized_auth_token) or 0)
            if user_waiting >= self.PER_USER_WAIT_LIMIT:
                raise ValueError(f"user image queue is full, max_waiting={self.PER_USER_WAIT_LIMIT}")
            existing = self._tickets.get(normalized_request_id)
            if existing is not None:
                return ImageQueueTicket(**existing.__dict__)
            ticket = ImageQueueTicket(
                request_id=normalized_request_id,
                auth_token=normalized_auth_token,
                title=self._clean_text(title),
            )
            self._tickets[ticket.request_id] = ticket
            self._waiting_order.append(ticket.request_id)
            self._user_waiting[normalized_auth_token] = user_waiting + 1
            self._condition.notify_all()
            return ImageQueueTicket(**ticket.__dict__)

    def wait_for_turn(self, request_id: str) -> ImageQueueTicket:
        normalized_request_id = self._clean_text(request_id)
        with self._condition:
            while True:
                ticket = self._tickets.get(normalized_request_id)
                if ticket is None:
                    raise RuntimeError("image queue ticket was not found")
                if self._waiting_order and self._waiting_order[0] == normalized_request_id:
                    wait_seconds = self._global_start_wait_seconds_locked()
                    if wait_seconds > 0:
                        self._condition.wait(timeout=min(wait_seconds, 1.0))
                        continue
                    self._waiting_order.popleft()
                    self._decrement_user_waiting_locked(ticket.auth_token)
                    ticket.status = "assigning_account"
                    ticket.started_at = time()
                    ticket.updated_at = ticket.started_at
                    self._start_timestamps.append(ticket.started_at)
                    self._user_running[ticket.auth_token] = int(self._user_running.get(ticket.auth_token) or 0) + 1
                    self._global_running += 1
                    self._condition.notify_all()
                    return ImageQueueTicket(**ticket.__dict__)
                self._condition.wait(timeout=1.0)

    def mark_assigning_account(self, request_id: str) -> None:
        self.mark_status(request_id, "assigning_account")

    def mark_status(self, request_id: str, status: str, error: str | None = None) -> None:
        normalized_request_id = self._clean_text(request_id)
        with self._condition:
            ticket = self._tickets.get(normalized_request_id)
            if ticket is None:
                return
            ticket.status = self._clean_text(status) or ticket.status
            ticket.updated_at = time()
            if error:
                ticket.error = self._clean_text(error)
            self._condition.notify_all()

    def finish_ticket(self, request_id: str, error: str | None = None) -> None:
        normalized_request_id = self._clean_text(request_id)
        with self._condition:
            ticket = self._tickets.pop(normalized_request_id, None)
            if ticket is None:
                return
            if ticket.status == "waiting":
                try:
                    self._waiting_order.remove(normalized_request_id)
                except ValueError:
                    pass
                self._decrement_user_waiting_locked(ticket.auth_token)
            else:
                self._decrement_user_running_locked(ticket.auth_token)
                self._global_running = max(0, self._global_running - 1)
            ticket.status = "failed" if error else "finished"
            ticket.error = self._clean_text(error) or None
            ticket.finished_at = time()
            ticket.updated_at = ticket.finished_at
            self._recent[normalized_request_id] = ticket
            self._cleanup_recent_locked()
            self._condition.notify_all()

    def clear(self) -> None:
        with self._condition:
            self._waiting_order.clear()
            self._start_timestamps.clear()
            self._tickets.clear()
            self._recent.clear()
            self._user_waiting.clear()
            self._user_running.clear()
            self._global_running = 0
            self._condition.notify_all()

    def snapshot(self, auth_token: str, request_id: str | None = None) -> dict[str, object]:
        normalized_auth_token = self._clean_text(auth_token) or "__anonymous__"
        normalized_request_id = self._clean_text(request_id)
        with self._condition:
            now_value = time()
            self._cleanup_recent_locked()
            self._cleanup_start_timestamps_locked(now_value)
            start_wait_seconds = self._global_start_wait_seconds_locked(now_value)
            waiting_positions = {item_id: index + 1 for index, item_id in enumerate(self._waiting_order)}
            active_items = [
                ticket
                for ticket in self._tickets.values()
                if ticket.auth_token == normalized_auth_token
            ]
            recent_items = [
                ticket
                for ticket in self._recent.values()
                if ticket.auth_token == normalized_auth_token
            ]
            items = sorted(
                active_items + recent_items,
                key=lambda ticket: (ticket.finished_at is not None, ticket.created_at),
            )
            request_ticket = None
            if normalized_request_id:
                request_ticket = self._tickets.get(normalized_request_id) or self._recent.get(normalized_request_id)
            return {
                "limits": {
                    "per_user_waiting": self.PER_USER_WAIT_LIMIT,
                    "global_waiting": self.GLOBAL_WAIT_LIMIT,
                    "global_starts_per_window": self.GLOBAL_START_LIMIT,
                    "global_start_window_seconds": self.GLOBAL_START_WINDOW_SECONDS,
                },
                "user": {
                    "waiting": int(self._user_waiting.get(normalized_auth_token) or 0),
                    "running": int(self._user_running.get(normalized_auth_token) or 0),
                },
                "global": {
                    "waiting": len(self._waiting_order),
                    "running": self._global_running,
                    "starts_in_window": len(self._start_timestamps),
                    "start_wait_seconds": round(start_wait_seconds, 3),
                },
                "request": self._serialize_ticket(request_ticket, waiting_positions),
                "items": [self._serialize_ticket(ticket, waiting_positions) for ticket in items],
            }

    def _serialize_ticket(
        self,
        ticket: ImageQueueTicket | None,
        waiting_positions: dict[str, int],
    ) -> dict[str, object] | None:
        if ticket is None:
            return None
        position = waiting_positions.get(ticket.request_id)
        return {
            "request_id": ticket.request_id,
            "title": ticket.title,
            "status": ticket.status,
            "position": position,
            "ahead": max(0, int(position or 0) - 1) if position is not None else None,
            "created_at": self._now_text(ticket.created_at),
            "started_at": self._now_text(ticket.started_at),
            "finished_at": self._now_text(ticket.finished_at),
            "error": ticket.error,
        }


image_queue_service = ImageQueueService()
