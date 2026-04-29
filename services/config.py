from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("CHATGPT2API_DATA_DIR") or BASE_DIR / "data")
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
    proxies_file: Path
    sqlite_path: Path
    backup_dir: Path
    backup_max_bytes: int
    backup_interval_minutes: int
    tls_verify: bool
    image_engine: str
    image_route_policy: str
    image_dev_port: int
    image_enable_free_images_fallback: bool
    image_enable_responses_primary: bool
    image_log_requests: bool
    image_queue_per_user_active_limit: int
    image_queue_per_user_wait_limit: int
    image_queue_global_wait_limit: int
    image_queue_global_start_limit: int
    image_queue_global_start_window_seconds: int
    image_generation_timeout_seconds: int


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


def _parse_int(value: object, *, default: int, name: str) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"config '{name}' must be an integer") from exc


def _parse_choice(value: object, *, default: str, choices: set[str], name: str) -> str:
    normalized = str(value or default).strip().lower()
    if normalized not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"config '{name}' must be one of: {allowed}")
    return normalized


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
    image_engine = _parse_choice(
        os.getenv("IMAGE_ENGINE", raw_config.get("image-engine")),
        default="chat_image",
        choices={"legacy", "chat_image"},
        name="image-engine",
    )
    image_route_policy = _parse_choice(
        os.getenv("IMAGE_ROUTE_POLICY", raw_config.get("image-route-policy")),
        default="plan_type",
        choices={"plan_type", "force_responses", "force_images", "legacy"},
        name="image-route-policy",
    )

    return AppSettings(
        auth_key=auth_key,
        admin_auth_key=admin_auth_key,
        host="0.0.0.0",
        port=_parse_int(
            os.getenv("CHATGPT2API_PORT", raw_config.get("port")),
            default=8000,
            name="port",
        ),
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
        proxies_file=Path(
            str(
                os.getenv("CHATGPT2API_PROXIES_FILE")
                or raw_config.get("proxies-file")
                or DATA_DIR / "proxies.json"
            )
        ),
        sqlite_path=Path(
            str(
                os.getenv("CHATGPT2API_SQLITE_PATH")
                or raw_config.get("sqlite-path")
                or DATA_DIR / "chatgpt2api.sqlite3"
            )
        ),
        backup_dir=Path(
            str(
                os.getenv("CHATGPT2API_BACKUP_DIR")
                or raw_config.get("backup-dir")
                or DATA_DIR / "backups"
            )
        ),
        backup_max_bytes=_parse_int(
            os.getenv("CHATGPT2API_BACKUP_MAX_BYTES", raw_config.get("backup-max-bytes")),
            default=500 * 1024 * 1024,
            name="backup-max-bytes",
        ),
        backup_interval_minutes=_parse_int(
            os.getenv("CHATGPT2API_BACKUP_INTERVAL_MINUTES", raw_config.get("backup-interval-minutes")),
            default=0,
            name="backup-interval-minutes",
        ),
        tls_verify=tls_verify,
        image_engine=image_engine,
        image_route_policy=image_route_policy,
        image_dev_port=_parse_int(
            os.getenv("IMAGE_DEV_PORT", raw_config.get("image-dev-port")),
            default=18201,
            name="image-dev-port",
        ),
        image_enable_free_images_fallback=_parse_bool(
            os.getenv("IMAGE_ENABLE_FREE_IMAGES_FALLBACK", raw_config.get("image-enable-free-images-fallback")),
            default=True,
        ),
        image_enable_responses_primary=_parse_bool(
            os.getenv("IMAGE_ENABLE_RESPONSES_PRIMARY", raw_config.get("image-enable-responses-primary")),
            default=True,
        ),
        image_log_requests=_parse_bool(
            os.getenv("IMAGE_LOG_REQUESTS", raw_config.get("image-log-requests")),
            default=False,
        ),
        image_queue_per_user_active_limit=_parse_int(
            os.getenv("IMAGE_QUEUE_PER_USER_ACTIVE_LIMIT", raw_config.get("image-queue-per-user-active-limit")),
            default=10,
            name="image-queue-per-user-active-limit",
        ),
        image_queue_per_user_wait_limit=_parse_int(
            os.getenv("IMAGE_QUEUE_PER_USER_WAIT_LIMIT", raw_config.get("image-queue-per-user-wait-limit")),
            default=10,
            name="image-queue-per-user-wait-limit",
        ),
        image_queue_global_wait_limit=_parse_int(
            os.getenv("IMAGE_QUEUE_GLOBAL_WAIT_LIMIT", raw_config.get("image-queue-global-wait-limit")),
            default=2000,
            name="image-queue-global-wait-limit",
        ),
        image_queue_global_start_limit=_parse_int(
            os.getenv("IMAGE_QUEUE_GLOBAL_START_LIMIT", raw_config.get("image-queue-global-start-limit")),
            default=60,
            name="image-queue-global-start-limit",
        ),
        image_queue_global_start_window_seconds=_parse_int(
            os.getenv(
                "IMAGE_QUEUE_GLOBAL_START_WINDOW_SECONDS",
                raw_config.get("image-queue-global-start-window-seconds"),
            ),
            default=60,
            name="image-queue-global-start-window-seconds",
        ),
        image_generation_timeout_seconds=_parse_int(
            os.getenv(
                "IMAGE_GENERATION_TIMEOUT_SECONDS",
                raw_config.get("image-generation-timeout-seconds"),
            ),
            default=900,
            name="image-generation-timeout-seconds",
        ),
    )


config = _load_settings()
