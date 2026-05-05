from __future__ import annotations

import hashlib
import json
import base64
from datetime import datetime, timedelta
from typing import Any

from services.sqlite_store import sqlite_store


REQUEST_TERMINAL_STATUSES = {"finished", "failed", "rejected"}
REQUEST_ACTIVE_STATUSES = ("accepted", "waiting", "assigning_account", "running")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_time(value: Any) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _duration_ms(start: Any, end: Any) -> int | None:
    start_time = _parse_time(start)
    end_time = _parse_time(end)
    if start_time is None or end_time is None:
        return None
    return max(0, int((end_time - start_time).total_seconds() * 1000))


def hash_text(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def token_owner_id(auth_token: str) -> str:
    return hash_text(auth_token)


def prompt_preview(prompt: str, *, limit: int = 80) -> str:
    text = " ".join(_clean_text(prompt).split())
    return text[:limit]


def encode_cursor(created_at: Any, request_id: Any) -> str:
    payload = json.dumps(
        {"created_at": _clean_text(created_at), "request_id": _clean_text(request_id)},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str] | None:
    text = _clean_text(cursor)
    if not text:
        return None
    try:
        padded = text + ("=" * (-len(text) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    created_at = _clean_text(payload.get("created_at"))
    request_id = _clean_text(payload.get("request_id"))
    if not created_at or not request_id:
        return None
    return created_at, request_id


class ImageRequestLogService:
    def create_record(
        self,
        *,
        request_id: str,
        owner_id: str,
        auth_type: str,
        endpoint: str,
        protocol: str,
        model: str,
        size: str | None,
        n: int,
        stream: bool,
        prompt: str,
        auth_token: str | None = None,
        user_key_id: str | None = None,
        user_key_label: str | None = None,
        has_input_image: bool = False,
        input_image_count: int = 0,
        client_conversation_id: str | None = None,
        response_id: str | None = None,
        requested_count: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now_text()
        record = {
            "request_id": _clean_text(request_id),
            "owner_id": _clean_text(owner_id),
            "auth_type": _clean_text(auth_type),
            "user_key_id": _clean_text(user_key_id) or None,
            "user_key_label": _clean_text(user_key_label) or None,
            "auth_token_hash": hash_text(auth_token),
            "endpoint": _clean_text(endpoint),
            "protocol": _clean_text(protocol),
            "model": _clean_text(model),
            "size": _clean_text(size) or "auto",
            "n": max(1, int(n or 1)),
            "stream": 1 if stream else 0,
            "has_input_image": 1 if has_input_image else 0,
            "input_image_count": max(0, int(input_image_count or 0)),
            "client_conversation_id": _clean_text(client_conversation_id) or None,
            "response_id": _clean_text(response_id) or None,
            "prompt_preview": prompt_preview(prompt),
            "prompt_hash": hash_text(prompt),
            "status": "accepted",
            "accepted_at": now,
            "queued_at": None,
            "started_at": None,
            "running_at": None,
            "finished_at": None,
            "updated_at": now,
            "queue_wait_ms": None,
            "assigning_ms": None,
            "running_ms": None,
            "total_ms": None,
            "requested_count": max(1, int(requested_count if requested_count is not None else n or 1)),
            "succeeded_count": None,
            "failed_count": None,
            "unit_cost": None,
            "charged_quota": None,
            "remaining_quota": None,
            "http_status": None,
            "error_type": None,
            "error_message": None,
            "upstream_error": None,
            "account_token_hash": None,
            "account_type": None,
            "route": None,
            "attempt_count": 0,
            "fallback_used": 0,
            "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
            "created_at": now,
        }
        columns = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        updates = ", ".join(
            f"{key} = excluded.{key}"
            for key in record
            if key not in {"request_id", "created_at"}
        )
        with sqlite_store.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO image_request_records ({columns})
                VALUES ({placeholders})
                ON CONFLICT(request_id) DO UPDATE SET {updates}
                """,
                list(record.values()),
            )
        return self.get_record(record["request_id"]) or record

    def _apply_update(self, request_id: str, updates: dict[str, Any]) -> None:
        normalized_id = _clean_text(request_id)
        if not normalized_id or not updates:
            return
        next_status = _clean_text(updates.get("status"))
        if next_status in REQUEST_ACTIVE_STATUSES:
            current = self.get_record(normalized_id) or {}
            if _clean_text(current.get("status")) in REQUEST_TERMINAL_STATUSES:
                return
        updates["updated_at"] = _now_text()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with sqlite_store.connect() as connection:
            connection.execute(
                f"UPDATE image_request_records SET {assignments} WHERE request_id = ?",
                [*updates.values(), normalized_id],
            )

    def _get_times(self, request_id: str) -> dict[str, Any]:
        record = self.get_record(request_id) or {}
        return {
            "accepted_at": record.get("accepted_at"),
            "queued_at": record.get("queued_at"),
            "started_at": record.get("started_at"),
            "running_at": record.get("running_at"),
            "finished_at": record.get("finished_at"),
        }

    def mark_waiting(self, request_id: str) -> None:
        now = _now_text()
        self._apply_update(request_id, {"status": "waiting", "queued_at": now})

    def mark_assigning(self, request_id: str) -> None:
        now = _now_text()
        times = self._get_times(request_id)
        self._apply_update(
            request_id,
            {
                "status": "assigning_account",
                "started_at": times.get("started_at") or now,
                "queue_wait_ms": _duration_ms(times.get("queued_at") or times.get("accepted_at"), now),
            },
        )

    def mark_running(
        self,
        request_id: str,
        *,
        account_token: str | None = None,
        account_type: str | None = None,
        route: str | None = None,
        attempt_count: int | None = None,
        fallback_used: bool | None = None,
    ) -> None:
        now = _now_text()
        times = self._get_times(request_id)
        updates: dict[str, Any] = {
            "status": "running",
            "running_at": times.get("running_at") or now,
            "assigning_ms": _duration_ms(times.get("started_at"), now),
        }
        if account_token is not None:
            updates["account_token_hash"] = hash_text(account_token)
        if account_type is not None:
            updates["account_type"] = _clean_text(account_type) or None
        if route is not None:
            updates["route"] = _clean_text(route) or None
        if attempt_count is not None:
            updates["attempt_count"] = max(0, int(attempt_count or 0))
        if fallback_used is not None:
            updates["fallback_used"] = 1 if fallback_used else 0
        self._apply_update(request_id, updates)

    def mark_finished(self, request_id: str, *, billing: dict[str, Any] | None = None, result: dict[str, Any] | None = None) -> None:
        now = _now_text()
        times = self._get_times(request_id)
        data_items = list((result or {}).get("data") or [])
        output_items = [
            item
            for item in list((result or {}).get("output") or [])
            if isinstance(item, dict) and item.get("type") == "image_generation_call"
        ]
        billing_payload = billing or {}
        updates = {
            "status": "finished",
            "finished_at": now,
            "queue_wait_ms": _duration_ms(times.get("queued_at") or times.get("accepted_at"), times.get("started_at")),
            "assigning_ms": _duration_ms(times.get("started_at"), times.get("running_at")),
            "running_ms": _duration_ms(times.get("running_at") or times.get("started_at"), now),
            "total_ms": _duration_ms(times.get("accepted_at"), now),
            "succeeded_count": int(billing_payload.get("succeeded_count") or len(data_items) or len(output_items) or 0),
            "failed_count": int(billing_payload.get("failed_count") or 0),
            "unit_cost": int(billing_payload.get("unit_cost") or 0) if billing_payload else None,
            "charged_quota": int(billing_payload.get("charged_quota") or 0) if billing_payload else None,
            "remaining_quota": int(billing_payload.get("remaining_quota") or 0) if billing_payload else None,
            "http_status": 200,
        }
        self._apply_update(request_id, updates)

    def mark_failed(
        self,
        request_id: str,
        *,
        error: Exception | str,
        http_status: int | None = None,
        upstream_error: str | None = None,
    ) -> None:
        current = self.get_record(request_id) or {}
        if current.get("status") == "rejected":
            return
        now = _now_text()
        times = self._get_times(request_id)
        message = _clean_text(error)
        self._apply_update(
            request_id,
            {
                "status": "failed",
                "finished_at": now,
                "running_ms": _duration_ms(times.get("running_at") or times.get("started_at"), now),
                "total_ms": _duration_ms(times.get("accepted_at"), now),
                "http_status": http_status,
                "error_type": error.__class__.__name__ if isinstance(error, Exception) else "Error",
                "error_message": message[:500],
                "upstream_error": _clean_text(upstream_error)[:500] or None,
            },
        )

    def mark_rejected(self, request_id: str, *, reason: str, http_status: int | None = None) -> None:
        now = _now_text()
        times = self._get_times(request_id)
        self._apply_update(
            request_id,
            {
                "status": "rejected",
                "finished_at": now,
                "total_ms": _duration_ms(times.get("accepted_at"), now),
                "http_status": http_status,
                "error_type": "Rejected",
                "error_message": _clean_text(reason)[:500],
            },
        )

    def mark_stale_active_failed(self, *, max_age_seconds: int, reason: str) -> int:
        cutoff = datetime.now() - timedelta(seconds=max(1, int(max_age_seconds or 1)))
        now = _now_text()
        status_placeholders = ", ".join("?" for _ in REQUEST_ACTIVE_STATUSES)
        with sqlite_store.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT request_id, accepted_at, queued_at, started_at, running_at
                FROM image_request_records
                WHERE status IN ({status_placeholders})
                """,
                REQUEST_ACTIVE_STATUSES,
            ).fetchall()
        stale_rows = []
        for row in rows:
            record = dict(row)
            reference_time = (
                _parse_time(record.get("running_at"))
                or _parse_time(record.get("started_at"))
                or _parse_time(record.get("queued_at"))
                or _parse_time(record.get("accepted_at"))
            )
            if reference_time is not None and reference_time <= cutoff:
                stale_rows.append(record)
        for record in stale_rows:
            self._apply_update(
                record["request_id"],
                {
                    "status": "failed",
                    "finished_at": now,
                    "running_ms": _duration_ms(record.get("running_at") or record.get("started_at"), now),
                    "total_ms": _duration_ms(record.get("accepted_at"), now),
                    "http_status": 504,
                    "error_type": "TimeoutError",
                    "error_message": _clean_text(reason)[:500],
                },
            )
        return len(stale_rows)

    def mark_active_failed(
        self,
        *,
        reason: str,
        http_status: int = 503,
        error_type: str = "Interrupted",
    ) -> int:
        now = _now_text()
        status_placeholders = ", ".join("?" for _ in REQUEST_ACTIVE_STATUSES)
        with sqlite_store.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT request_id, accepted_at, started_at, running_at
                FROM image_request_records
                WHERE status IN ({status_placeholders})
                """,
                REQUEST_ACTIVE_STATUSES,
            ).fetchall()
        for row in rows:
            record = dict(row)
            self._apply_update(
                record["request_id"],
                {
                    "status": "failed",
                    "finished_at": now,
                    "running_ms": _duration_ms(record.get("running_at") or record.get("started_at"), now),
                    "total_ms": _duration_ms(record.get("accepted_at"), now),
                    "http_status": int(http_status),
                    "error_type": _clean_text(error_type)[:100],
                    "error_message": _clean_text(reason)[:500],
                },
            )
        return len(rows)

    def get_record(self, request_id: str) -> dict[str, Any] | None:
        normalized_id = _clean_text(request_id)
        if not normalized_id:
            return None
        with sqlite_store.connect() as connection:
            row = connection.execute(
                "SELECT * FROM image_request_records WHERE request_id = ?",
                (normalized_id,),
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def list_records(
        self,
        *,
        filters: dict[str, Any] | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        normalized_limit = max(1, min(500, int(limit or 100)))
        filters = filters or {}
        clauses: list[str] = []
        params: list[Any] = []
        for field in ("request_id", "owner_id", "auth_type", "status", "model", "endpoint"):
            value = _clean_text(filters.get(field))
            if value:
                clauses.append(f"{field} = ?")
                params.append(value)
        if _clean_text(filters.get("since")):
            clauses.append("created_at >= ?")
            params.append(_clean_text(filters.get("since")))
        if _clean_text(filters.get("until")):
            clauses.append("created_at <= ?")
            params.append(_clean_text(filters.get("until")))
        decoded_cursor = decode_cursor(cursor or "")
        if decoded_cursor is not None:
            cursor_created_at, cursor_request_id = decoded_cursor
            clauses.append("(created_at < ? OR (created_at = ? AND request_id < ?))")
            params.extend([cursor_created_at, cursor_created_at, cursor_request_id])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with sqlite_store.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM image_request_records
                {where}
                ORDER BY created_at DESC, request_id DESC
                LIMIT ?
                """,
                [*params, normalized_limit + 1],
            ).fetchall()
        records = [self._row_to_record(row) for row in rows[:normalized_limit]]
        next_cursor = (
            encode_cursor(records[-1]["created_at"], records[-1]["request_id"])
            if len(rows) > normalized_limit and records
            else None
        )
        return {"items": records, "next_cursor": next_cursor}

    def cleanup_old_records(self, *, retention_days: int = 30, max_rows: int = 100000) -> int:
        cutoff = (datetime.now() - timedelta(days=max(1, int(retention_days or 30)))).strftime("%Y-%m-%d %H:%M:%S")
        removed = 0
        with sqlite_store.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM image_request_records WHERE created_at < ?",
                (cutoff,),
            )
            removed += int(cursor.rowcount or 0)
            cursor = connection.execute(
                """
                DELETE FROM image_request_records
                WHERE request_id IN (
                    SELECT request_id
                    FROM image_request_records
                    ORDER BY created_at DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (max(1, int(max_rows or 100000)),),
            )
            removed += int(cursor.rowcount or 0)
        return removed

    @staticmethod
    def _row_to_record(row: Any) -> dict[str, Any]:
        record = dict(row)
        for key in ("stream", "has_input_image", "fallback_used"):
            record[key] = bool(record.get(key))
        try:
            record["metadata"] = json.loads(str(record.get("metadata_json") or "{}"))
        except json.JSONDecodeError:
            record["metadata"] = {}
        record.pop("metadata_json", None)
        return record


image_request_log_service = ImageRequestLogService()
