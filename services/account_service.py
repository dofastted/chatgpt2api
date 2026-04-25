from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
import hashlib
import json
from pathlib import Path
from threading import Condition, Lock
from typing import Any
from datetime import datetime, timedelta

from curl_cffi.requests import Session

from services.config import config
from services.proxy_service import proxy_service


class AccountService:
    DEFAULT_CATEGORY = "普通"
    DONATION_CATEGORY = "捐赠"
    FAILURE_COOLDOWN_SECONDS = 180
    MAX_INFLIGHT_PER_ACCOUNT = 2

    ACCOUNT_TYPE_MAP = {
        "free": "Free",
        "plus": "Plus",
        "team": "Team",
        "pro": "Pro",
        "personal": "Plus",
        "business": "Team",
        "enterprise": "Team",
    }

    def __init__(self, store_file: Path):
        self.store_file = store_file
        self._lock = Lock()
        self._slot_condition = Condition(self._lock)
        self._index = 0
        self._accounts = self._load_accounts()
        self._inflight_counts: dict[str, int] = {}

    @staticmethod
    def _clean_token(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _token_label(access_token: str) -> str:
        return hashlib.sha1(str(access_token or "").encode("utf-8")).hexdigest()[:10]

    def _clean_tokens(self, tokens: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen = set()
        for token in tokens:
            value = self._clean_token(token)
            if value and value not in seen:
                seen.add(value)
                cleaned.append(value)
        return cleaned

    def _find_account_index(self, access_token: str) -> int:
        for index, item in enumerate(self._accounts):
            if self._clean_token(item.get("access_token")) == access_token:
                return index
        return -1

    @staticmethod
    def _parse_time_text(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S",):
            try:
                parsed = datetime.strptime(text, fmt)
                return parsed.replace(tzinfo=None)
            except ValueError:
                continue
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed.replace(tzinfo=None)
        except ValueError:
            return None

    @classmethod
    def _normalize_future_time_text(cls, value: Any) -> str | None:
        parsed = cls._parse_time_text(value)
        if parsed is None or parsed <= datetime.now():
            return None
        return parsed.strftime("%Y-%m-%d %H:%M:%S")

    @classmethod
    def _build_cooldown_until(cls, seconds: int) -> str | None:
        normalized_seconds = max(0, int(seconds or 0))
        if normalized_seconds <= 0:
            return None
        return (datetime.now() + timedelta(seconds=normalized_seconds)).strftime("%Y-%m-%d %H:%M:%S")

    @classmethod
    def _is_in_cooldown(cls, account: dict[str, Any]) -> bool:
        if not isinstance(account, dict):
            return False
        cooldown_until = cls._parse_time_text(account.get("cooldown_until"))
        return cooldown_until is not None and cooldown_until > datetime.now()

    @staticmethod
    def _is_image_account_available(account: dict) -> bool:
        if not isinstance(account, dict):
            return False
        if account.get("status") in {"禁用", "异常"}:
            return False
        if AccountService._is_in_cooldown(account):
            return False
        if bool(account.get("needs_refresh")):
            return True
        return int(account.get("quota") or 0) > 0

    @classmethod
    def _has_account_capacity(cls, inflight_count: int) -> bool:
        return int(inflight_count or 0) < cls.MAX_INFLIGHT_PER_ACCOUNT

    @staticmethod
    def _has_known_quota_state(item: dict[str, Any]) -> bool:
        if not isinstance(item, dict):
            return False
        if item.get("quota") is not None:
            return True
        limits_progress = item.get("limits_progress")
        if isinstance(limits_progress, list) and len(limits_progress) > 0:
            return True
        if item.get("restore_at") is not None:
            return True
        return False

    @classmethod
    def _is_bare_import_item(cls, item: dict[str, Any]) -> bool:
        if not isinstance(item, dict):
            return False
        if cls._has_known_quota_state(item):
            return False
        for key in ("status", "type", "default_model_slug", "success", "fail", "last_used_at", "needs_refresh"):
            value = item.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                if value.strip():
                    return False
                continue
            return False
        return True

    def _decode_access_token_payload(self, access_token: str) -> dict[str, Any]:
        parts = self._clean_token(access_token).split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload.encode("utf-8"))
            data = json.loads(decoded.decode("utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _normalize_account_type(self, value: Any) -> str | None:
        return self.ACCOUNT_TYPE_MAP.get(self._clean_token(value).lower())

    def _search_account_type(self, value: Any) -> str | None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = self._clean_token(key).lower()
                matched = self._normalize_account_type(item)
                if matched and any(flag in key_text for flag in ("plan", "type", "subscription", "workspace", "tier")):
                    return matched
            for item in value.values():
                matched = self._search_account_type(item)
                if matched:
                    return matched
            return None
        if isinstance(value, list):
            for item in value:
                matched = self._search_account_type(item)
                if matched:
                    return matched
            return None
        return self._normalize_account_type(value)

    def _detect_account_type(self, access_token: str, me_payload: Any, init_payload: Any) -> str:
        token_payload = self._decode_access_token_payload(access_token)

        auth_payload = token_payload.get("https://api.openai.com/auth")
        if isinstance(auth_payload, dict):
            matched = self._normalize_account_type(auth_payload.get("chatgpt_plan_type"))
            if matched:
                return matched

        for payload in (me_payload, init_payload, token_payload):
            matched = self._search_account_type(payload)
            if matched:
                return matched

        return "Free"

    def _normalize_account(self, item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        access_token = self._clean_token(item.get("access_token"))
        if not access_token:
            return None
        normalized = dict(item)
        normalized["access_token"] = access_token
        category = self._clean_token(normalized.get("category")) or self.DEFAULT_CATEGORY
        normalized["category"] = self.DONATION_CATEGORY if category == self.DONATION_CATEGORY else self.DEFAULT_CATEGORY
        normalized["type"] = self._clean_token(normalized.get("type")) or "Free"
        normalized["status"] = self._clean_token(normalized.get("status")) or "正常"
        normalized["quota"] = int(normalized.get("quota") if normalized.get("quota") is not None else 0)
        if normalized["quota"] < 0:
            normalized["quota"] = 0
        normalized["email"] = self._clean_token(normalized.get("email")) or None
        normalized["user_id"] = self._clean_token(normalized.get("user_id")) or None
        limits_progress = normalized.get("limits_progress")
        normalized["limits_progress"] = limits_progress if isinstance(limits_progress, list) else []
        normalized["default_model_slug"] = self._clean_token(normalized.get("default_model_slug")) or None
        normalized["restore_at"] = self._clean_token(normalized.get("restore_at")) or None
        normalized["success"] = int(normalized.get("success") or 0)
        normalized["fail"] = int(normalized.get("fail") or 0)
        normalized["last_used_at"] = normalized.get("last_used_at")
        normalized["cooldown_until"] = self._normalize_future_time_text(normalized.get("cooldown_until"))
        raw_needs_refresh = normalized.get("needs_refresh")
        if raw_needs_refresh is None:
            normalized["needs_refresh"] = (
                normalized["status"] == "正常" and not self._has_known_quota_state(normalized)
            )
        else:
            normalized["needs_refresh"] = bool(raw_needs_refresh)
        return normalized

    @staticmethod
    def _extract_quota_and_restore_at(limits_progress: list[Any]) -> tuple[int, str | None]:
        quota = 0
        restore_at = None
        for item in limits_progress:
            if not isinstance(item, dict) or item.get("feature_name") != "image_gen":
                continue
            quota = int(item.get("remaining") or 0)
            restore_at = str(item.get("reset_after") or "").strip() or None
            break
        return quota, restore_at

    def _load_accounts(self) -> list[dict]:
        if not self.store_file.exists():
            return []
        try:
            data = json.loads(self.store_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [normalized for item in data if (normalized := self._normalize_account(item)) is not None]

    def _save_accounts(self) -> None:
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        self.store_file.write_text(
            json.dumps(self._accounts, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _build_remote_headers(self, access_token: str) -> tuple[dict[str, str], str]:
        account = self.get_account(access_token) or {}
        user_agent = self._clean_token(account.get("user-agent") or account.get("user_agent"))
        impersonate = self._clean_token(account.get("impersonate")) or "edge101"
        headers = {
            "authorization": f"Bearer {access_token}",
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "content-type": "application/json",
            "oai-language": "zh-CN",
            "origin": "https://chatgpt.com",
            "referer": "https://chatgpt.com/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": user_agent
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "sec-ch-ua": self._clean_token(account.get("sec-ch-ua"))
            or '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            "sec-ch-ua-mobile": self._clean_token(account.get("sec-ch-ua-mobile")) or "?0",
            "sec-ch-ua-platform": self._clean_token(account.get("sec-ch-ua-platform")) or '"Windows"',
        }
        device_id = self._clean_token(account.get("oai-device-id") or account.get("oai_device_id"))
        session_id = self._clean_token(account.get("oai-session-id") or account.get("oai_session_id"))
        if device_id:
            headers["oai-device-id"] = device_id
        if session_id:
            headers["oai-session-id"] = session_id
        return headers, impersonate

    def _public_items(self, accounts: list[dict]) -> list[dict]:
        return [
            {
                "id": hashlib.sha1(access_token.encode("utf-8")).hexdigest()[:16],
                "access_token": access_token,
                "category": account.get("category") or self.DEFAULT_CATEGORY,
                "type": account.get("type") or "Free",
                "status": account.get("status") or "正常",
                "quota": account.get("quota") if account.get("quota") is not None else 0,
                "email": account.get("email"),
                "user_id": account.get("user_id"),
                "limits_progress": account.get("limits_progress") or [],
                "default_model_slug": account.get("default_model_slug"),
                "restoreAt": account.get("restore_at"),
                "success": int(account.get("success") or 0),
                "fail": int(account.get("fail") or 0),
                "lastUsedAt": account.get("last_used_at"),
                "cooldownUntil": account.get("cooldown_until"),
                "needsRefresh": bool(account.get("needs_refresh")),
            }
            for account in accounts
            if (access_token := self._clean_token(account.get("access_token")))
        ]

    def list_tokens(self) -> list[str]:
        with self._lock:
            return [token for item in self._accounts if (token := self._clean_token(item.get("access_token")))]

    def _candidate_tokens_locked(self, excluded_tokens: set[str] | None = None) -> list[str]:
        excluded = {self._clean_token(token) for token in (excluded_tokens or set()) if self._clean_token(token)}
        return [
            token
            for item in self._accounts
            if self._is_image_account_available(item)
            and (token := self._clean_token(item.get("access_token")))
            and token not in excluded
            and self._has_account_capacity(int(self._inflight_counts.get(token) or 0))
        ]

    def next_token(self, excluded_tokens: set[str] | None = None) -> str:
        with self._lock:
            tokens = self._candidate_tokens_locked(excluded_tokens=excluded_tokens)
            if not tokens:
                raise RuntimeError(f"No available tokens found in {self.store_file}")
            access_token = tokens[self._index % len(tokens)]
            self._index += 1
            return access_token

    def try_acquire_token_slot(self, excluded_tokens: set[str] | None = None) -> str | None:
        with self._lock:
            tokens = self._candidate_tokens_locked(excluded_tokens=excluded_tokens)
            if not tokens:
                return None
            access_token = tokens[self._index % len(tokens)]
            self._index += 1
            self._inflight_counts[access_token] = int(self._inflight_counts.get(access_token) or 0) + 1
            return access_token

    def release_token_slot(self, access_token: str) -> None:
        normalized_access_token = self._clean_token(access_token)
        if not normalized_access_token:
            return
        with self._lock:
            current = max(0, int(self._inflight_counts.get(normalized_access_token) or 0) - 1)
            if current:
                self._inflight_counts[normalized_access_token] = current
            else:
                self._inflight_counts.pop(normalized_access_token, None)
            self._slot_condition.notify_all()

    def get_account(self, access_token: str) -> dict | None:
        access_token = self._clean_token(access_token)
        if not access_token:
            return None
        with self._lock:
            index = self._find_account_index(access_token)
            if index >= 0:
                return dict(self._accounts[index])
        return None

    def list_accounts(self) -> list[dict]:
        with self._lock:
            return self._public_items(self._accounts)

    def list_limited_tokens(self) -> list[str]:
        with self._lock:
            return [
                token
                for item in self._accounts
                if item.get("status") == "限流"
                and (token := self._clean_token(item.get("access_token")))
            ]

    def list_refreshable_tokens(self) -> list[str]:
        with self._lock:
            refreshable: list[str] = []
            for item in self._accounts:
                token = self._clean_token(item.get("access_token"))
                if not token:
                    continue
                if item.get("status") == "限流":
                    refreshable.append(token)
                    continue
                cooldown_until = self._parse_time_text(item.get("cooldown_until"))
                if cooldown_until is not None and cooldown_until <= datetime.now():
                    refreshable.append(token)
            return refreshable

    def add_accounts(self, tokens: list[str], category: str | None = None) -> dict:
        cleaned_tokens = self._clean_tokens(tokens)
        if not cleaned_tokens:
            return {"added": 0, "updated": 0, "skipped": 0, "added_tokens": [], "items": self.list_accounts()}
        normalized_category = self.DONATION_CATEGORY if self._clean_token(category) == self.DONATION_CATEGORY else self.DEFAULT_CATEGORY

        with self._lock:
            indexed = {self._clean_token(item.get("access_token")): dict(item) for item in self._accounts}
            added = 0
            updated = 0
            skipped = 0
            added_tokens: list[str] = []
            for access_token in cleaned_tokens:
                current = indexed.get(access_token)
                if current is None:
                    added += 1
                    added_tokens.append(access_token)
                    current = {}
                else:
                    skipped += 1
                resolved_status = self._clean_token(current.get("status"))
                if resolved_status != "禁用":
                    resolved_status = "正常"
                account = self._normalize_account(
                    {
                        **current,
                        "access_token": access_token,
                        "category": normalized_category,
                        "type": str(current.get("type") or "Free"),
                        "status": resolved_status,
                        "quota": 0,
                        "limits_progress": [],
                        "restore_at": None,
                        "default_model_slug": None,
                        "needs_refresh": True,
                    }
                )
                if account is not None:
                    if current:
                        updated += 1
                    indexed[access_token] = account
            self._accounts = list(indexed.values())
            self._save_accounts()
            items = self._public_items(self._accounts)
        return {"added": added, "updated": updated, "skipped": skipped, "added_tokens": added_tokens, "items": items}

    def add_account_items(self, accounts: list[dict[str, Any]], category: str | None = None) -> dict:
        if not accounts:
            return {"added": 0, "updated": 0, "skipped": 0, "added_tokens": [], "items": self.list_accounts()}
        normalized_category = self.DONATION_CATEGORY if self._clean_token(category) == self.DONATION_CATEGORY else None

        with self._lock:
            indexed = {self._clean_token(item.get("access_token")): dict(item) for item in self._accounts}
            added = 0
            updated = 0
            skipped = 0
            added_tokens: list[str] = []
            seen_tokens: set[str] = set()
            for raw_item in accounts:
                if not isinstance(raw_item, dict):
                    continue
                access_token = self._clean_token(raw_item.get("access_token"))
                if not access_token or access_token in seen_tokens:
                    if access_token:
                        skipped += 1
                    continue
                seen_tokens.add(access_token)
                current = indexed.get(access_token)
                current_category = self._clean_token(current.get("category")) if current else ""
                resolved_category = normalized_category or self._clean_token(raw_item.get("category")) or current_category
                merged_item = {
                    **(current or {}),
                    **raw_item,
                    "access_token": access_token,
                    "category": resolved_category or self.DEFAULT_CATEGORY,
                }
                if self._is_bare_import_item(raw_item):
                    resolved_status = self._clean_token(current.get("status")) if current else ""
                    merged_item.update(
                        {
                            "quota": 0,
                            "limits_progress": [],
                            "restore_at": None,
                            "default_model_slug": None,
                            "needs_refresh": True,
                            "status": resolved_status if resolved_status == "禁用" else "正常",
                        }
                    )
                elif "needs_refresh" not in merged_item and not self._has_known_quota_state(merged_item):
                    merged_item["needs_refresh"] = True
                account = self._normalize_account(merged_item)
                if account is None:
                    skipped += 1
                    continue
                if current is None:
                    added += 1
                    added_tokens.append(access_token)
                else:
                    updated += 1
                indexed[access_token] = account
            self._accounts = list(indexed.values())
            self._save_accounts()
            items = self._public_items(self._accounts)
        return {"added": added, "updated": updated, "skipped": skipped, "added_tokens": added_tokens, "items": items}

    def delete_accounts(self, tokens: list[str]) -> dict:
        target_set = set(self._clean_tokens(tokens))
        if not target_set:
            return {"removed": 0, "items": self.list_accounts()}
        with self._lock:
            before = len(self._accounts)
            self._accounts = [item for item in self._accounts if self._clean_token(item.get("access_token")) not in target_set]
            removed = before - len(self._accounts)
            if self._accounts:
                self._index %= len(self._accounts)
            else:
                self._index = 0
            for token in target_set:
                self._inflight_counts.pop(token, None)
            if removed:
                self._save_accounts()
                self._slot_condition.notify_all()
            items = self._public_items(self._accounts)
        return {"removed": removed, "items": items}

    def remove_token(self, access_token: str) -> bool:
        return bool(self.delete_accounts([access_token])["removed"])

    def update_account(self, access_token: str, updates: dict) -> dict | None:
        access_token = self._clean_token(access_token)
        if not access_token:
            return None
        with self._lock:
            index = self._find_account_index(access_token)
            if index < 0:
                return None
            account = self._normalize_account({**self._accounts[index], **updates, "access_token": access_token})
            if account is None:
                return None
            self._accounts[index] = account
            self._save_accounts()
            self._slot_condition.notify_all()
            return dict(account)
        return None

    def mark_request_failure(self, access_token: str, cooldown_seconds: int | None = None) -> dict | None:
        access_token = self._clean_token(access_token)
        if not access_token:
            return None
        with self._lock:
            index = self._find_account_index(access_token)
            if index < 0:
                return None
            next_item = dict(self._accounts[index])
            next_item["last_used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            next_item["fail"] = int(next_item.get("fail") or 0) + 1
            next_item["cooldown_until"] = self._build_cooldown_until(
                self.FAILURE_COOLDOWN_SECONDS if cooldown_seconds is None else cooldown_seconds
            )
            account = self._normalize_account(next_item)
            if account is None:
                return None
            self._accounts[index] = account
            self._save_accounts()
            self._slot_condition.notify_all()
            return dict(account)
        return None

    def mark_image_result(self, access_token: str, success: bool) -> dict | None:
        access_token = self._clean_token(access_token)
        if not access_token:
            return None
        with self._lock:
            index = self._find_account_index(access_token)
            if index < 0:
                return None
            next_item = dict(self._accounts[index])
            next_item["last_used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if success:
                next_item["success"] = int(next_item.get("success") or 0) + 1
                next_item["quota"] = max(0, int(next_item.get("quota") or 0) - 1)
                next_item["cooldown_until"] = None
                if next_item["quota"] == 0:
                    next_item["status"] = "限流"
                    next_item["restore_at"] = next_item.get("restore_at") or None
                elif next_item.get("status") == "限流":
                    next_item["status"] = "正常"
            else:
                next_item["fail"] = int(next_item.get("fail") or 0) + 1
                next_item["cooldown_until"] = self._build_cooldown_until(self.FAILURE_COOLDOWN_SECONDS)
            account = self._normalize_account(next_item)
            if account is None:
                return None
            self._accounts[index] = account
            self._save_accounts()
            self._slot_condition.notify_all()
            return dict(account)
        return None

    def fetch_remote_info(self, access_token: str) -> dict[str, Any]:
        access_token = self._clean_token(access_token)
        if not access_token:
            raise ValueError("access_token is required")

        headers, impersonate = self._build_remote_headers(access_token)
        print(f"[account-refresh] start {self._token_label(access_token)}")
        session = Session(
            impersonate=impersonate,
            verify=config.tls_verify,
            proxy=proxy_service.get_enabled_proxy_url(),
        )
        session.headers.update(headers)
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                me_future = executor.submit(
                    session.get,
                    "https://chatgpt.com/backend-api/me",
                    headers={
                        "x-openai-target-path": "/backend-api/me",
                        "x-openai-target-route": "/backend-api/me",
                    },
                    timeout=20,
                )
                init_future = executor.submit(
                    session.post,
                    "https://chatgpt.com/backend-api/conversation/init",
                    json={
                        "gizmo_id": None,
                        "requested_default_model": None,
                        "conversation_id": None,
                        "timezone_offset_min": -480,
                    },
                    timeout=20,
                )

                me_response = me_future.result()
                init_response = init_future.result()

            if me_response.status_code != 200:
                raise RuntimeError(f"/backend-api/me failed: HTTP {me_response.status_code}")
            me_payload = me_response.json()

            if init_response.status_code != 200:
                raise RuntimeError(f"/backend-api/conversation/init failed: HTTP {init_response.status_code}")
            init_payload = init_response.json()

            limits_progress = init_payload.get("limits_progress")
            if not isinstance(limits_progress, list):
                limits_progress = []

            quota, restore_at = self._extract_quota_and_restore_at(limits_progress)
            status = "限流" if quota == 0 else "正常"

            result = {
                "email": me_payload.get("email"),
                "user_id": me_payload.get("id"),
                "type": self._detect_account_type(access_token, me_payload, init_payload),
                "quota": quota,
                "limits_progress": limits_progress,
                "default_model_slug": init_payload.get("default_model_slug"),
                "restore_at": restore_at,
                "status": status,
                "cooldown_until": None,
                "needs_refresh": False,
            }
            print(
                "[account-refresh] ok",
                self._token_label(access_token),
                f"type={result.get('type')}",
                f"quota={result.get('quota')}",
                f"has_restore_at={bool(result.get('restore_at'))}",
            )
            return result
        finally:
            session.close()

    def refresh_accounts(self, access_tokens: list[str]) -> dict[str, Any]:
        cleaned_tokens = self._clean_tokens(access_tokens)
        if not cleaned_tokens:
            return {"refreshed": 0, "errors": [], "items": self.list_accounts()}

        refreshed = 0
        errors: list[dict[str, str]] = []
        max_workers = min(10, len(cleaned_tokens))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(self.fetch_remote_info, access_token): access_token for access_token in cleaned_tokens}
            for future in as_completed(future_map):
                access_token = future_map[future]
                try:
                    remote_info = future.result()
                    if self.update_account(access_token, remote_info) is not None:
                        refreshed += 1
                except Exception as exc:
                    message = str(exc)
                    print(f"[account-refresh] fail {self._token_label(access_token)} {message}")
                    if "/backend-api/me failed: HTTP 401" in message:
                        self.update_account(
                            access_token,
                            {
                                "status": "异常",
                                "quota": 0,
                            },
                        )
                        message = "检测到封号"
                    errors.append({"access_token": access_token, "error": message})

        print(f"[account-refresh] done refreshed={refreshed} errors={len(errors)} workers={max_workers}")
        return {
            "refreshed": refreshed,
            "errors": errors,
            "items": self.list_accounts(),
        }


account_service = AccountService(config.accounts_file)
