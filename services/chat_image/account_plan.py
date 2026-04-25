from __future__ import annotations

import base64
import json
from typing import Any


PLAN_TYPE_MAP = {
    "free": "Free",
    "plus": "Plus",
    "pro": "Pro",
    "team": "Team",
    "personal": "Plus",
    "business": "Team",
    "enterprise": "Team",
}


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_plan_type(value: Any) -> str:
    return PLAN_TYPE_MAP.get(clean_text(value).lower(), "Free")


def decode_jwt_payload(token: Any) -> dict[str, Any]:
    parts = clean_text(token).split(".")
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


def search_plan_type(value: Any) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = clean_text(key).lower()
            normalized = PLAN_TYPE_MAP.get(clean_text(item).lower())
            if normalized and any(flag in key_text for flag in ("plan", "type", "subscription", "workspace", "tier")):
                return normalized
        for item in value.values():
            found = search_plan_type(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = search_plan_type(item)
            if found:
                return found
    return PLAN_TYPE_MAP.get(clean_text(value).lower(), "")


def derive_plan_type(*, explicit: Any = None, id_token: Any = None, access_token: Any = None) -> tuple[str, str]:
    explicit_plan = search_plan_type(explicit)
    if explicit_plan:
        return explicit_plan, clean_text(explicit)

    for token in (id_token, access_token):
        payload = decode_jwt_payload(token)
        if not payload:
            continue
        auth_payload = payload.get("https://api.openai.com/auth")
        if isinstance(auth_payload, dict):
            auth_plan = search_plan_type(auth_payload.get("chatgpt_plan_type"))
            if auth_plan:
                return auth_plan, clean_text(auth_payload.get("chatgpt_plan_type"))
        payload_plan = search_plan_type(payload)
        if payload_plan:
            return payload_plan, ""

    return "Free", ""

