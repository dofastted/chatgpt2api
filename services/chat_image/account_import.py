from __future__ import annotations

import json
from typing import Any

from services.chat_image.account_plan import clean_text, derive_plan_type


SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "authorization",
}


def parse_account_carrier(value: str | bytes | dict[str, Any] | list[Any]) -> dict[str, Any] | list[Any]:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("account JSON is empty")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("account JSON is malformed") from exc
        if not isinstance(parsed, (dict, list)):
            raise ValueError("account JSON must be an object or array")
        return parsed
    if isinstance(value, (dict, list)):
        return value
    raise ValueError("account carrier must be JSON text, object, or array")


def sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if clean_text(key).lower() in SECRET_KEYS:
                continue
            result[str(key)] = sanitize_metadata(item)
        return result
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    return value


def _iter_raw_accounts(carrier: dict[str, Any] | list[Any]) -> tuple[list[dict[str, Any]], str]:
    if isinstance(carrier, list):
        return [item for item in carrier if isinstance(item, dict)], "array"
    accounts = carrier.get("accounts")
    if isinstance(accounts, list):
        return [item for item in accounts if isinstance(item, dict)], "sub2api_accounts"
    return [carrier], "single_json"


def _normalize_one(raw_item: dict[str, Any], auth_source: str) -> dict[str, Any] | None:
    credentials = raw_item.get("credentials")
    if not isinstance(credentials, dict):
        credentials = {}

    access_token = clean_text(raw_item.get("access_token") or credentials.get("access_token"))
    if not access_token:
        return None

    refresh_token = clean_text(raw_item.get("refresh_token") or credentials.get("refresh_token"))
    id_token = clean_text(raw_item.get("id_token") or credentials.get("id_token"))
    explicit_plan = (
        raw_item.get("plan_type")
        or raw_item.get("type")
        or credentials.get("plan_type")
        or credentials.get("type")
    )
    plan_type, plan_type_raw = derive_plan_type(
        explicit=explicit_plan,
        id_token=id_token,
        access_token=access_token,
    )

    normalized: dict[str, Any] = {
        "access_token": access_token,
        "email": clean_text(raw_item.get("email") or credentials.get("email")) or None,
        "account_id": clean_text(raw_item.get("account_id") or credentials.get("account_id")) or None,
        "user_id": clean_text(raw_item.get("user_id") or credentials.get("user_id")) or None,
        "plan_type_raw": plan_type_raw or clean_text(explicit_plan) or None,
        "type": plan_type,
        "proxy_key": clean_text(raw_item.get("proxy_key") or credentials.get("proxy_key")) or None,
        "priority": raw_item.get("priority"),
        "concurrency": raw_item.get("concurrency"),
        "model_mapping": credentials.get("model_mapping") or raw_item.get("model_mapping") or {},
        "expires_at": raw_item.get("expires_at") or credentials.get("expires_at") or raw_item.get("expired"),
        "auth_source": auth_source,
        "auth_data": sanitize_metadata(raw_item.get("extra") if isinstance(raw_item.get("extra"), dict) else raw_item),
        "needs_refresh": True,
    }
    if refresh_token:
        normalized["refresh_token"] = refresh_token
    if id_token:
        normalized["id_token"] = id_token
    return {key: value for key, value in normalized.items() if value is not None}


def normalize_account_carrier(value: str | bytes | dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    carrier = parse_account_carrier(value)
    raw_accounts, auth_source = _iter_raw_accounts(carrier)
    if not raw_accounts:
        raise ValueError("account JSON contains no accounts")

    result: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    for raw_item in raw_accounts:
        normalized = _normalize_one(raw_item, auth_source)
        if normalized is None:
            continue
        access_token = clean_text(normalized.get("access_token"))
        if access_token in seen_tokens:
            continue
        seen_tokens.add(access_token)
        result.append(normalized)

    if not result:
        raise ValueError("account JSON contains no usable access_token")
    return result

