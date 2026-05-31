from __future__ import annotations

import json
from typing import Any

from services.chat_image.account_plan import clean_text, derive_plan_type


SECRET_KEYS = {
    "access_token",
    "access-token",
    "accesstoken",
    "chatgpt_access_token",
    "chatgpt-access-token",
    "chatgptaccesstoken",
    "refresh_token",
    "refresh-token",
    "refreshtoken",
    "id_token",
    "id-token",
    "idtoken",
    "token",
    "authorization",
}

ACCESS_TOKEN_KEYS = {
    "access_token",
    "access-token",
    "accesstoken",
    "accessToken",
    "chatgpt_access_token",
    "chatgpt-access-token",
    "chatgptAccessToken",
    "chatgptaccesstoken",
}
FALLBACK_TOKEN_KEYS = {"token", "authorization"}
REFRESH_TOKEN_KEYS = {"refresh_token", "refresh-token", "refreshToken", "refreshtoken"}
ID_TOKEN_KEYS = {"id_token", "id-token", "idToken", "idtoken"}
EXTERNAL_ACCOUNT_TEXT_FIELDS = {
    "email": ("email",),
    "account_id": ("account_id", "account-id", "accountId"),
    "user_id": ("user_id", "user-id", "userId"),
    "proxy_key": ("proxy_key", "proxy-key", "proxyKey"),
    "user-agent": ("user-agent", "user_agent", "userAgent"),
    "impersonate": ("impersonate",),
    "oai-device-id": ("oai-device-id", "oai_device_id", "oaiDeviceId"),
    "oai-session-id": ("oai-session-id", "oai_session_id", "oaiSessionId"),
    "sec-ch-ua": ("sec-ch-ua", "sec_ch_ua", "secChUa"),
    "sec-ch-ua-mobile": ("sec-ch-ua-mobile", "sec_ch_ua_mobile", "secChUaMobile"),
    "sec-ch-ua-platform": ("sec-ch-ua-platform", "sec_ch_ua_platform", "secChUaPlatform"),
}


def normalize_key(value: Any) -> str:
    text = clean_text(value).lower()
    return "".join(char for char in text if char.isalnum())


def _looks_like_access_token(value: str) -> bool:
    token = clean_text(value)
    if not token:
        return False
    if token.startswith("Bearer "):
        token = token[len("Bearer "):].strip()
    if token.startswith("eyJ") and len(token.split(".")) >= 3:
        return True
    return len(token) >= 40


def _strip_bearer(value: str) -> str:
    token = clean_text(value)
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_first_text(sources: list[dict[str, Any]], keys: set[str] | tuple[str, ...]) -> str:
    wanted = {normalize_key(key) for key in keys}
    for source in sources:
        for key, item in source.items():
            if normalize_key(key) in wanted:
                text = clean_text(item)
                if text:
                    return text
    return ""


def _read_access_token(sources: list[dict[str, Any]]) -> str:
    token = _read_first_text(sources, ACCESS_TOKEN_KEYS)
    if token:
        return _strip_bearer(token)
    fallback = _read_first_text(sources, FALLBACK_TOKEN_KEYS)
    if fallback and _looks_like_access_token(fallback):
        return _strip_bearer(fallback)
    return ""


def _has_account_marker(value: dict[str, Any]) -> bool:
    sources = [
        value,
        _as_dict(value.get("credentials")),
        _as_dict(value.get("auth")),
        _as_dict(value.get("metadata")),
        _as_dict(value.get("session")),
    ]
    return bool(_read_access_token(sources))


def _collect_raw_accounts(value: Any, collected: list[dict[str, Any]]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_raw_accounts(item, collected)
        return
    if not isinstance(value, dict):
        return
    if _has_account_marker(value):
        collected.append(value)
    for item in value.values():
        _collect_raw_accounts(item, collected)


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
            if normalize_key(key) in {normalize_key(secret_key) for secret_key in SECRET_KEYS}:
                continue
            result[str(key)] = sanitize_metadata(item)
        return result
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    return value


def _iter_raw_accounts(carrier: dict[str, Any] | list[Any]) -> tuple[list[dict[str, Any]], str]:
    if isinstance(carrier, list):
        items: list[dict[str, Any]] = []
        _collect_raw_accounts(carrier, items)
        return items, "array"
    accounts = carrier.get("accounts")
    if isinstance(accounts, list):
        items: list[dict[str, Any]] = []
        _collect_raw_accounts(accounts, items)
        return items, "sub2api_accounts"
    items: list[dict[str, Any]] = []
    _collect_raw_accounts(carrier, items)
    return items or [carrier], "single_json"


def _normalize_one(raw_item: dict[str, Any], auth_source: str) -> dict[str, Any] | None:
    credentials = _as_dict(raw_item.get("credentials"))
    auth_data = _as_dict(raw_item.get("auth"))
    metadata = _as_dict(raw_item.get("metadata"))
    session_data = _as_dict(raw_item.get("session"))
    sources = [raw_item, credentials, auth_data, metadata, session_data]

    access_token = _read_access_token(sources)
    if not access_token:
        return None

    refresh_token = _read_first_text(sources, REFRESH_TOKEN_KEYS)
    id_token = _read_first_text(sources, ID_TOKEN_KEYS)
    explicit_plan = (
        raw_item.get("plan_type")
        or raw_item.get("type")
        or credentials.get("plan_type")
        or credentials.get("type")
        or auth_data.get("plan_type")
        or auth_data.get("type")
        or metadata.get("plan_type")
        or metadata.get("type")
    )
    plan_type, plan_type_raw = derive_plan_type(
        explicit=explicit_plan,
        id_token=id_token,
        access_token=access_token,
    )

    normalized: dict[str, Any] = {
        "access_token": access_token,
        "email": _read_first_text(sources, EXTERNAL_ACCOUNT_TEXT_FIELDS["email"]) or None,
        "account_id": _read_first_text(sources, EXTERNAL_ACCOUNT_TEXT_FIELDS["account_id"]) or None,
        "user_id": _read_first_text(sources, EXTERNAL_ACCOUNT_TEXT_FIELDS["user_id"]) or None,
        "plan_type_raw": plan_type_raw or clean_text(explicit_plan) or None,
        "type": plan_type,
        "proxy_key": _read_first_text(sources, EXTERNAL_ACCOUNT_TEXT_FIELDS["proxy_key"]) or None,
        "priority": raw_item.get("priority"),
        "concurrency": raw_item.get("concurrency"),
        "model_mapping": credentials.get("model_mapping") or raw_item.get("model_mapping") or {},
        "expires_at": raw_item.get("expires_at") or credentials.get("expires_at") or raw_item.get("expired"),
        "auth_source": auth_source,
        "auth_data": sanitize_metadata(raw_item.get("extra") if isinstance(raw_item.get("extra"), dict) else raw_item),
        "needs_refresh": True,
    }
    for target_key, source_keys in EXTERNAL_ACCOUNT_TEXT_FIELDS.items():
        if target_key in normalized:
            continue
        text = _read_first_text(sources, source_keys)
        if text:
            normalized[target_key] = text
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
