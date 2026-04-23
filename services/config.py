from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = BASE_DIR / "config.json"


@dataclass(frozen=True)
class AppSettings:
    auth_key: str
    admin_auth_key: str
    host: str
    port: int
    accounts_file: Path
    user_keys_file: Path
    redeem_codes_file: Path
    tls_verify: bool


def _parse_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError("config 'tls-verify' must be a boolean")


def _load_settings() -> AppSettings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_config: dict[str, object] = {}

    if CONFIG_FILE.exists():
        text = CONFIG_FILE.read_text(encoding="utf-8").strip()
        if text:
            loaded = json.loads(text)
            if not isinstance(loaded, dict):
                raise ValueError("config.json must be a JSON object")
            raw_config = loaded

    auth_key = str(os.getenv("CHATGPT2API_AUTH_KEY") or raw_config.get("auth-key") or "").strip()
    if not auth_key:
        raise ValueError(
            "config.json must contain a non-empty 'auth-key' or CHATGPT2API_AUTH_KEY must be set"
        )
    admin_auth_key = str(
        os.getenv("CHATGPT2API_ADMIN_AUTH_KEY") or raw_config.get("admin-auth-key") or auth_key
    ).strip()
    if not admin_auth_key:
        raise ValueError(
            "config.json must contain a non-empty 'admin-auth-key' or CHATGPT2API_ADMIN_AUTH_KEY must be set"
        )

    tls_verify = _parse_bool(
        os.getenv("CHATGPT2API_TLS_VERIFY", raw_config.get("tls-verify")),
        default=True,
    )

    return AppSettings(
        auth_key=auth_key,
        admin_auth_key=admin_auth_key,
        host="0.0.0.0",
        port=8000,
        accounts_file=DATA_DIR / "accounts.json",
        user_keys_file=Path(
            str(os.getenv("CHATGPT2API_USER_KEYS_FILE") or raw_config.get("user-keys-file") or DATA_DIR / "user_keys.json")
        ),
        redeem_codes_file=Path(
            str(
                os.getenv("CHATGPT2API_REDEEM_CODES_FILE")
                or raw_config.get("redeem-codes-file")
                or DATA_DIR / "redeem_codes.json"
            )
        ),
        tls_verify=tls_verify,
    )


config = _load_settings()
