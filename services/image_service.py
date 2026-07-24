from __future__ import annotations

import base64
import binascii
import hashlib
import json
import random
import re
import time
import uuid
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.parse import unquote_to_bytes

from curl_cffi.requests import Session

from services.account_service import account_service
from services.chat_image.account_plan import decode_jwt_payload
from services.config import config
from services import proof_of_work
from services.proxy_service import proxy_service
from services.uploaded_image_service import uploaded_image_service
from services.image_size import upstream_image_size


BASE_URL = "https://chatgpt.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_MODEL = "gpt-4o"
GPT_IMAGE_2_UPSTREAM_MODEL = "gpt-image-2"
GPT_IMAGE_2_REASONING_EFFORT = None
PUBLIC_GPT_IMAGE_2_MODELS = {"gpt-image-2", "gpt-image-2-2K", "gpt-image-2-4K"}
CODEX_RESPONSES_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_RESPONSES_MODEL = "gpt-5.4-mini"
CODEX_RESPONSES_USER_AGENT = "codex-tui/0.118.0 (Mac OS 26.3.1; arm64) iTerm.app/3.6.9 (codex-tui; 0.118.0)"
MAX_POW_ATTEMPTS = 500000
UPSTREAM_IMAGE_RESULT_TIMEOUT_SECONDS = 90
UPSTREAM_CONVERSATION_TIMEOUT_SECONDS = 120
TRANSIENT_HTTP_STATUS_CODES = (408, 429, 500, 502, 503, 504, 520, 522, 524)
SUPPORTED_INPUT_IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/avif": ".avif",
}
TRANSIENT_UPSTREAM_STATUS_CODES = frozenset((*TRANSIENT_HTTP_STATUS_CODES, 422))
MAX_UPSTREAM_INPUT_IMAGE_SIDE = 1536
MAX_UPSTREAM_INPUT_IMAGE_BYTES = 4 * 1024 * 1024
PROXY_CONNECT_RETRY_DELAYS = (0.25, 0.75, 1.5)

_CORES = [16, 24, 32]
_SCREENS = [3000, 4000, 6000]
_NAV_KEYS = [
    "webdriver−false",
    "vendor−Google Inc.",
    "cookieEnabled−true",
    "pdfViewerEnabled−true",
    "hardwareConcurrency−32",
    "language−zh-CN",
    "mimeTypes−[object MimeTypeArray]",
    "userAgentData−[object NavigatorUAData]",
]
_WIN_KEYS = [
    "innerWidth",
    "innerHeight",
    "devicePixelRatio",
    "screen",
    "chrome",
    "location",
    "history",
    "navigator",
]


class ImageGenerationError(Exception):
    pass


@dataclass
class GeneratedImage:
    b64_json: str
    revised_prompt: str
    url: str = ""
    mime_type: str = "image/png"


@dataclass
class UploadedInputImage:
    file_id: str
    file_name: str
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None


def _is_transient_stream_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return (
        "http/2 stream" in text
        or "internal_error" in text
        or "curl: (92)" in text
        or "stream was not closed cleanly" in text
        or "connection was reset" in text
        or "recv failure" in text
    )


def _is_proxy_connect_error(message: str) -> bool:
    text = str(message or "").lower()
    return (
        "curl: (7)" in text
        or "failed to connect" in text
        or "could not connect to server" in text
        or "connection refused" in text
    )


def _build_fp(access_token: str) -> dict:
    account = account_service.get_account(access_token) or {}
    fp = {}
    raw_fp = account.get("fp")
    if isinstance(raw_fp, dict):
        fp.update({str(k).lower(): v for k, v in raw_fp.items()})
    for key in (
        "user-agent",
        "impersonate",
        "oai-device-id",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
    ):
        if key in account:
            fp[key] = account[key]
    if "user-agent" not in fp:
        fp["user-agent"] = USER_AGENT
    if "impersonate" not in fp:
        fp["impersonate"] = "edge101"
    if "oai-device-id" not in fp:
        fp["oai-device-id"] = str(uuid.uuid4())
    return fp


def _new_session(access_token: str) -> tuple[Session, dict]:
    fp = _build_fp(access_token)
    session = Session(
        impersonate=fp.get("impersonate") or "edge101",
        verify=config.tls_verify,
        proxy=proxy_service.get_enabled_proxy_url(),
    )
    session.headers.update(
        {
            "user-agent": fp.get("user-agent") or USER_AGENT,
            "accept-language": "en-US,en;q=0.9",
            "origin": BASE_URL,
            "referer": BASE_URL + "/",
            "accept": "*/*",
            "sec-ch-ua": fp.get("sec-ch-ua") or '"Microsoft Edge";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": fp.get("sec-ch-ua-mobile") or "?0",
            "sec-ch-ua-platform": fp.get("sec-ch-ua-platform") or '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "oai-device-id": fp.get("oai-device-id"),
        }
    )
    return session, fp


def _retry(fn, retries: int = 4, delay: float = 2.0, retry_on_status: tuple[int, ...] = ()) -> object:
    last_error = None
    last_response = None
    max_attempts = max(1, retries)
    attempt = 0
    proxy_retry_index = 0
    while attempt < max_attempts:
        try:
            response = fn()
        except Exception as exc:
            last_error = exc
            if proxy_retry_index < len(PROXY_CONNECT_RETRY_DELAYS) and _is_proxy_connect_error(str(exc)):
                time.sleep(PROXY_CONNECT_RETRY_DELAYS[proxy_retry_index])
                proxy_retry_index += 1
                max_attempts += 1
                continue
            time.sleep(delay)
            attempt += 1
            continue
        if retry_on_status and getattr(response, "status_code", 0) in retry_on_status:
            last_response = response
            time.sleep(delay * (attempt + 1))
            attempt += 1
            continue
        return response
    if last_response is not None:
        return last_response
    if last_error is not None:
        raise last_error
    raise ImageGenerationError("request failed")


def _pow_config(user_agent: str) -> list:
    return proof_of_work.get_config(user_agent)


def _generate_requirements_answer(seed: str, difficulty: str, config: list) -> tuple[str, bool]:
    diff_len = len(difficulty)
    seed_bytes = seed.encode()
    prefix1 = (json.dumps(config[:3], separators=(",", ":"), ensure_ascii=False)[:-1] + ",").encode()
    prefix2 = ("," + json.dumps(config[4:9], separators=(",", ":"), ensure_ascii=False)[1:-1] + ",").encode()
    prefix3 = ("," + json.dumps(config[10:], separators=(",", ":"), ensure_ascii=False)[1:]).encode()
    target = bytes.fromhex(difficulty)
    for attempt in range(MAX_POW_ATTEMPTS):
        left = str(attempt).encode()
        right = str(attempt >> 1).encode()
        encoded = base64.b64encode(prefix1 + left + prefix2 + right + prefix3)
        digest = hashlib.sha3_512(seed_bytes + encoded).digest()
        if digest[:diff_len] <= target:
            return encoded.decode(), True
    fallback = "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + base64.b64encode(f'"{seed}"'.encode()).decode()
    return fallback, False


def _get_requirements_token(config: list) -> str:
    seed = format(random.random())
    answer, _ = _generate_requirements_answer(seed, "0fffff", config)
    return "gAAAAAC" + answer


def _generate_proof_token(seed: str, difficulty: str, user_agent: str, proof_config: Optional[list] = None) -> str:
    answer, _ = proof_of_work.get_answer_token(seed, difficulty, proof_config or _pow_config(user_agent))
    return answer


def _bootstrap(session: Session, fp: dict) -> str:
    response = _retry(lambda: session.get(BASE_URL + "/", timeout=30))
    try:
        proof_of_work.get_data_build_from_html(response.text)
    except Exception:
        pass
    device_id = response.cookies.get("oai-did")
    if device_id:
        return device_id
    for cookie in session.cookies.jar if hasattr(session.cookies, "jar") else []:
        name = getattr(cookie, "name", getattr(cookie, "key", ""))
        if name == "oai-did":
            return cookie.value
    return str(fp.get("oai-device-id") or uuid.uuid4())


def _chat_requirements(session: Session, access_token: str, device_id: str) -> tuple[str, Optional[dict]]:
    config = _pow_config(USER_AGENT)
    response = _retry(
        lambda: session.post(
            BASE_URL + "/backend-api/sentinel/chat-requirements",
            headers={
                "Authorization": f"Bearer {access_token}",
                "oai-device-id": device_id,
                "content-type": "application/json",
            },
            json={"p": _get_requirements_token(config)},
            timeout=30,
        ),
        retries=4,
        retry_on_status=TRANSIENT_HTTP_STATUS_CODES,
    )
    if not response.ok:
        raise ImageGenerationError(response.text[:400] or f"chat-requirements failed: {response.status_code}")
    payload = response.json()
    return payload["token"], payload.get("proofofwork") or {}


def is_token_invalid_error(message: str) -> bool:
    text = str(message or "").lower()
    return (
        "token_invalidated" in text
        or "token_revoked" in text
        or "authentication token has been invalidated" in text
        or "invalidated oauth token" in text
        or "token_expired" in text
        or "authentication token is expired" in text
        or "invalid access token" in text
        or "unauthorized" in text
        or bool(re.search(r"\b401\b", text))
    )


def _iter_nested_error_values(value: object):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _iter_nested_error_values(nested)
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_nested_error_values(item)
        return
    yield value


def _extract_upstream_status_codes(message: str) -> set[int]:
    text = str(message or "").strip()
    if not text:
        return set()

    codes: set[int] = set()
    for match in re.finditer(r"\b(408|422|429|500|502|503|504|520|522|524)\b", text):
        try:
            codes.add(int(match.group(1)))
        except Exception:
            continue

    try:
        payload = json.loads(text)
    except Exception:
        return codes

    for value in _iter_nested_error_values(payload):
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            numeric = int(value)
            if numeric in TRANSIENT_UPSTREAM_STATUS_CODES:
                codes.add(numeric)
            continue
        nested_text = str(value or "").strip()
        if not nested_text:
            continue
        for match in re.finditer(r"\b(408|422|429|500|502|503|504|520|522|524)\b", nested_text):
            try:
                codes.add(int(match.group(1)))
            except Exception:
                continue
    return codes


def is_transient_image_error(message: str) -> bool:
    text = str(message or "").lower()
    return (
        bool(_extract_upstream_status_codes(text) & TRANSIENT_UPSTREAM_STATUS_CODES)
        or
        _is_transient_stream_error(Exception(text))
        or "download image failed" in text
        or "failed to get download url" in text
        or "no image returned from upstream" in text
        or "timed out" in text
        or "timeout" in text
        or "gateway timeout" in text
        or _is_proxy_connect_error(text)
        or "cloudflare" in text
        or "rate limit" in text
        or "too many requests" in text
        or "temporarily unavailable" in text
        or "upstream_error" in text
        or "overloaded_error" in text
    )


def _extract_sse_error_text(value: object) -> str:
    if isinstance(value, dict):
        for key in ("message", "detail", "error", "text", "description"):
            nested = _extract_sse_error_text(value.get(key))
            if nested:
                return nested
        return ""
    if isinstance(value, list):
        for item in value:
            nested = _extract_sse_error_text(item)
            if nested:
                return nested
        return ""
    return str(value or "").strip()


def _send_conversation(
    session: Session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token: Optional[str],
    parent_message_id: str,
    prompt: str,
    model: str,
    reasoning_effort: Optional[str] = None,
    input_images: list[dict[str, str]] | None = None,
    route: str = "legacy",
    size: str | None = None,
):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "text/event-stream",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "content-type": "application/json",
        "oai-device-id": device_id,
        "oai-language": "zh-CN",
        "oai-client-build-number": "5955942",
        "oai-client-version": "prod-be885abbfcfe7b1f511e88b3003d9ee44757fbad",
        "origin": BASE_URL,
        "referer": BASE_URL + "/",
        "openai-sentinel-chat-requirements-token": chat_token,
    }
    if proof_token:
        headers["openai-sentinel-proof-token"] = proof_token
    conversation_message = _build_conversation_message(
        session,
        access_token,
        device_id,
        prompt,
        input_images=input_images,
    )
    request_body = {
        "action": "next",
        "messages": [conversation_message],
        "parent_message_id": parent_message_id,
        "model": model,
        "history_and_training_disabled": False,
        "timezone_offset_min": -480,
        "timezone": "America/Los_Angeles",
        "conversation_mode": {"kind": "primary_assistant"},
        "conversation_origin": None,
        "force_paragen": False,
        "force_paragen_model_slug": "",
        "force_rate_limit": False,
        "force_use_sse": True,
        "paragen_cot_summary_display_override": "allow",
        "paragen_stream_type_override": None,
        "reset_rate_limits": False,
        "suggestions": [],
        "supported_encodings": [],
        "system_hints": ["picture_v2"],
        "variant_purpose": "comparison_implicit",
        "websocket_request_id": str(uuid.uuid4()),
        "client_contextual_info": {
            "is_dark_mode": False,
            "time_since_loaded": random.randint(50, 500),
            "page_height": random.randint(500, 1000),
            "page_width": random.randint(1000, 2000),
            "pixel_ratio": 1.2,
            "screen_height": random.randint(800, 1200),
            "screen_width": random.randint(1200, 2200),
        },
    }
    if reasoning_effort:
        request_body["reasoning"] = {"effort": reasoning_effort}
    requested_size = upstream_image_size(size)
    if requested_size:
        request_body["image_generation_options"] = {"size": requested_size}
    endpoint_path = "/backend-api/conversation"
    if route in {"images", "images_edit"}:
        endpoint_path = "/backend-api/f/conversation"
        request_body["client_prepare_state"] = "none"
        request_body["supported_encodings"] = ["v1"]

    response = _retry(
        lambda: session.post(
            BASE_URL + endpoint_path,
            headers=headers,
            json=request_body,
            stream=True,
            timeout=UPSTREAM_CONVERSATION_TIMEOUT_SECONDS,
        ),
        retries=3,
        retry_on_status=TRANSIENT_HTTP_STATUS_CODES,
    )
    if not response.ok:
        label = "f conversation" if endpoint_path.endswith("/f/conversation") else "conversation"
        raise ImageGenerationError(response.text[:400] or f"{label} failed: {response.status_code}")
    return response


def _parse_sse(response) -> dict:
    file_ids: list[str] = []
    conversation_id = ""
    text_parts: list[str] = []
    terminal_error = ""
    stream_complete = False
    for raw_line in response.iter_lines():
        if not raw_line:
            continue
        if isinstance(raw_line, bytes):
            raw_line = raw_line.decode("utf-8", errors="replace")
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload in ("", "[DONE]"):
            break
        for prefix, stored_prefix in (("file-service://", ""), ("sediment://", "sed:")):
            start = 0
            while True:
                index = payload.find(prefix, start)
                if index < 0:
                    break
                start = index + len(prefix)
                tail = payload[start:]
                file_id = []
                for char in tail:
                    if char.isalnum() or char in "_-":
                        file_id.append(char)
                    else:
                        break
                if file_id:
                    value = stored_prefix + "".join(file_id)
                    if value not in file_ids:
                        file_ids.append(value)
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if not terminal_error:
            terminal_error = _extract_sse_error_text(obj.get("error"))
        if not terminal_error and str(obj.get("type") or "").strip().lower() in {"error", "conversation_error"}:
            terminal_error = _extract_sse_error_text(obj)
        conversation_id = str(obj.get("conversation_id") or conversation_id)
        event_type = str(obj.get("type") or "").strip()
        if event_type in {"resume_conversation_token", "message_marker", "message_stream_complete"}:
            conversation_id = str(obj.get("conversation_id") or conversation_id)
        if event_type == "message_stream_complete":
            stream_complete = True
        data = obj.get("v")
        if isinstance(data, dict):
            conversation_id = str(data.get("conversation_id") or conversation_id)
        message = obj.get("message") or {}
        content = message.get("content") or {}
        if content.get("content_type") == "text":
            parts = content.get("parts") or []
            if parts:
                text_parts.append(str(parts[0]))
        if file_ids and conversation_id and stream_complete:
            break
        if file_ids and conversation_id:
            break
    return {
        "conversation_id": conversation_id,
        "file_ids": file_ids,
        "text": "".join(text_parts),
        "error": terminal_error,
    }


def _extract_image_ids(mapping: dict) -> list[str]:
    file_ids: list[str] = []
    for node in mapping.values():
        message = (node or {}).get("message") or {}
        author = message.get("author") or {}
        metadata = message.get("metadata") or {}
        content = message.get("content") or {}
        if author.get("role") != "tool":
            continue
        if metadata.get("async_task_type") != "image_gen":
            continue
        if content.get("content_type") != "multimodal_text":
            continue
        for part in content.get("parts") or []:
            if isinstance(part, dict):
                pointer = str(part.get("asset_pointer") or "")
                if pointer.startswith("file-service://"):
                    file_id = pointer.removeprefix("file-service://")
                    if file_id not in file_ids:
                        file_ids.append(file_id)
                elif pointer.startswith("sediment://"):
                    file_id = "sed:" + pointer.removeprefix("sediment://")
                    if file_id not in file_ids:
                        file_ids.append(file_id)
    return file_ids


def _poll_image_ids(session: Session, access_token: str, device_id: str, conversation_id: str) -> list[str]:
    started = time.time()
    while time.time() - started < UPSTREAM_IMAGE_RESULT_TIMEOUT_SECONDS:
        response = _retry(
            lambda: session.get(
                f"{BASE_URL}/backend-api/conversation/{conversation_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "oai-device-id": device_id,
                    "accept": "*/*",
                },
                timeout=30,
            ),
            retries=2,
            retry_on_status=TRANSIENT_HTTP_STATUS_CODES,
        )
        if response.status_code != 200:
            time.sleep(3)
            continue
        try:
            payload = response.json()
        except Exception:
            time.sleep(3)
            continue
        file_ids = _extract_image_ids(payload.get("mapping") or {})
        if file_ids:
            return file_ids
        time.sleep(3)
    return []


def _fetch_download_url(session: Session, access_token: str, device_id: str, conversation_id: str, file_id: str) -> str:
    is_sediment = file_id.startswith("sed:")
    raw_id = file_id[4:] if is_sediment else file_id
    if is_sediment:
        endpoint = f"{BASE_URL}/backend-api/conversation/{conversation_id}/attachment/{raw_id}/download"
    else:
        endpoint = f"{BASE_URL}/backend-api/files/{raw_id}/download"
    response = _retry(
        lambda: session.get(
            endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "oai-device-id": device_id,
            },
            timeout=30,
        ),
        retries=3,
        retry_on_status=TRANSIENT_HTTP_STATUS_CODES,
    )
    if not response.ok:
        print(
            "[image-download] url lookup failed "
            f"file_id={_safe_download_file_id(file_id)} status={response.status_code} "
            f"content_type={_safe_content_type(response.headers.get('content-type'))}"
        )
        return ""
    download_url = str((response.json() or {}).get("download_url") or "")
    if not download_url:
        print(
            "[image-download] url lookup empty "
            f"file_id={_safe_download_file_id(file_id)} status={response.status_code} "
            f"content_type={_safe_content_type(response.headers.get('content-type'))}"
        )
    return download_url


def _download_as_base64(session: Session, download_url: str) -> str:
    response = session.get(download_url, timeout=60)
    if not response.ok or not response.content:
        raise ImageGenerationError("download image failed")
    return base64.b64encode(response.content).decode("ascii")


def _detect_image_mime_type(image_bytes: bytes, response_content_type: str | None = None) -> str:
    content_type = str(response_content_type or "").split(";", 1)[0].strip().lower()
    if content_type.startswith("image/"):
        return content_type
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    if image_bytes.startswith(b"BM"):
        return "image/bmp"
    if image_bytes[4:12] == b"ftypavif":
        return "image/avif"
    return "image/png"


def _safe_content_type(value: str | None) -> str:
    content_type = str(value or "").split(";", 1)[0].strip().lower()
    return content_type[:64] or "unknown"


def _safe_download_url_label(download_url: str) -> str:
    parsed = urlparse(str(download_url or ""))
    if not parsed.scheme or not parsed.netloc:
        return "relative-or-invalid"
    return f"{parsed.scheme}://{parsed.netloc}"


def _safe_download_file_id(file_id: str) -> str:
    normalized = str(file_id or "").strip()
    if len(normalized) <= 16:
        return normalized or "unknown"
    return f"{normalized[:6]}...{normalized[-6:]}"


def _normalize_input_image_mime_type(image_bytes: bytes, response_content_type: str | None = None) -> str:
    mime_type = _detect_image_mime_type(image_bytes, response_content_type)
    if mime_type not in SUPPORTED_INPUT_IMAGE_EXTENSIONS:
        raise ImageGenerationError(f"unsupported input image mime type: {mime_type}")
    return mime_type


def _decode_data_url_input_image(image_url: str) -> tuple[bytes, str]:
    try:
        header, payload = str(image_url or "").split(",", 1)
    except ValueError as exc:
        raise ImageGenerationError("invalid input image data URL") from exc
    meta = header[5:]
    mime_hint = meta.split(";", 1)[0].strip().lower()
    try:
        if ";base64" in meta.lower():
            image_bytes = base64.b64decode(payload, validate=True)
        else:
            image_bytes = unquote_to_bytes(payload)
    except (ValueError, binascii.Error) as exc:
        raise ImageGenerationError("invalid input image data URL") from exc
    if not image_bytes:
        raise ImageGenerationError("input image is empty")
    mime_type = _normalize_input_image_mime_type(image_bytes, mime_hint or None)
    return image_bytes, mime_type


def _download_input_image(session: Session, image_url: str) -> tuple[bytes, str]:
    normalized_url = str(image_url or "").strip()
    if not normalized_url:
        raise ImageGenerationError("input image_url is required")
    if normalized_url.lower().startswith("data:"):
        return _decode_data_url_input_image(normalized_url)
    response = _retry(
        lambda: session.get(
            normalized_url,
            headers={"accept": "image/*,*/*;q=0.8"},
            timeout=60,
        ),
        retries=3,
        retry_on_status=TRANSIENT_HTTP_STATUS_CODES,
    )
    if not response.ok or not response.content:
        raise ImageGenerationError("failed to fetch input image")
    mime_type = _normalize_input_image_mime_type(response.content, response.headers.get("content-type"))
    return response.content, mime_type


def _detect_input_image_dimensions(image_bytes: bytes) -> tuple[int | None, int | None]:
    try:
        from PIL import Image
    except Exception:
        return None, None
    try:
        image = Image.open(BytesIO(image_bytes))
        return int(image.width), int(image.height)
    except Exception:
        return None, None


def _prepare_input_image_for_upstream(image_bytes: bytes, mime_type: str) -> tuple[bytes, str]:
    if len(image_bytes) <= MAX_UPSTREAM_INPUT_IMAGE_BYTES:
        width, height = _detect_input_image_dimensions(image_bytes)
        if not width or not height or max(width, height) <= MAX_UPSTREAM_INPUT_IMAGE_SIDE:
            return image_bytes, mime_type
    try:
        from PIL import Image
    except Exception:
        return image_bytes, mime_type
    try:
        image = Image.open(BytesIO(image_bytes))
        image.load()
    except Exception:
        return image_bytes, mime_type

    has_alpha = image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in getattr(image, "info", {})
    )
    width, height = int(image.width), int(image.height)
    if max(width, height) > MAX_UPSTREAM_INPUT_IMAGE_SIDE:
        scale = MAX_UPSTREAM_INPUT_IMAGE_SIDE / max(width, height)
        next_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
        image = image.resize(next_size, resampling)

    output = BytesIO()
    try:
        if has_alpha:
            if image.mode not in {"RGBA", "LA"}:
                image = image.convert("RGBA")
            image.save(output, format="PNG", optimize=True)
            next_bytes = output.getvalue()
            next_mime_type = "image/png"
        else:
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.save(output, format="JPEG", quality=88, optimize=True, progressive=True)
            next_bytes = output.getvalue()
            next_mime_type = "image/jpeg"
    except Exception:
        return image_bytes, mime_type
    if next_bytes and len(next_bytes) < len(image_bytes):
        print(
            f"[image-upstream] input image optimized "
            f"from={len(image_bytes)} to={len(next_bytes)} mime={mime_type}->{next_mime_type}"
        )
        return next_bytes, next_mime_type
    return image_bytes, mime_type


def _normalize_input_image_ref(input_image: dict[str, str] | str) -> dict[str, str]:
    if isinstance(input_image, str):
        return {"image_url": str(input_image or "").strip()}
    return dict(input_image or {})


def _token_label(access_token: str) -> str:
    return hashlib.sha1(str(access_token or "").encode("utf-8")).hexdigest()[:10]


def _load_input_image_bytes(session: Session, input_image: dict[str, str] | str) -> tuple[bytes, str]:
    normalized_input_image = _normalize_input_image_ref(input_image)
    file_id = str(normalized_input_image.get("file_id") or "").strip()
    if file_id:
        owner_auth_token = str(normalized_input_image.get("owner_auth_token") or "")
        client_conversation_id = str(normalized_input_image.get("client_conversation_id") or "")
        stored = uploaded_image_service.read_bytes(
            file_id,
            owner_auth_token,
            client_conversation_id,
        )
        if stored is None:
            raise ImageGenerationError("input image file_id was not found")
        consumed = uploaded_image_service.consume_upload(file_id, owner_auth_token, client_conversation_id)
        if consumed is None:
            raise ImageGenerationError("input image file_id was not found")
        image_bytes, item = stored
        mime_type = _normalize_input_image_mime_type(image_bytes, str(item.get("mime_type") or ""))
        return _prepare_input_image_for_upstream(image_bytes, mime_type)
    image_bytes, mime_type = _download_input_image(session, str(normalized_input_image.get("image_url") or "").strip())
    return _prepare_input_image_for_upstream(image_bytes, mime_type)


def _build_uploaded_input_image(
    session: Session,
    access_token: str,
    device_id: str,
    input_image: dict[str, str] | str,
) -> UploadedInputImage:
    image_bytes, mime_type = _load_input_image_bytes(session, input_image)
    width, height = _detect_input_image_dimensions(image_bytes)
    file_ext = SUPPORTED_INPUT_IMAGE_EXTENSIONS.get(mime_type, ".png")
    file_name = f"input-{uuid.uuid4().hex}{file_ext}"
    request_headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "application/json",
        "content-type": "application/json",
        "oai-device-id": device_id,
    }
    create_response = _retry(
        lambda: session.post(
            BASE_URL + "/backend-api/files",
            headers=request_headers,
            json={
                "file_name": file_name,
                "file_size": len(image_bytes),
                "use_case": "multimodal",
                "mime_type": mime_type,
            },
            timeout=60,
        ),
        retries=3,
        retry_on_status=TRANSIENT_HTTP_STATUS_CODES,
    )
    if not create_response.ok:
        raise ImageGenerationError(
            create_response.text[:400] or f"input image upload init failed: {create_response.status_code}"
        )
    try:
        create_payload = create_response.json() or {}
    except Exception as exc:
        raise ImageGenerationError("input image upload init returned invalid JSON") from exc
    file_id = str(create_payload.get("file_id") or create_payload.get("id") or "").strip()
    upload_url = str(create_payload.get("upload_url") or "").strip()
    if not file_id or not upload_url:
        raise ImageGenerationError("input image upload init missing file_id or upload_url")
    upload_response = _retry(
        lambda: session.put(
            upload_url,
            data=image_bytes,
            headers={
                "content-type": mime_type,
                "x-ms-blob-type": "BlockBlob",
            },
            timeout=120,
        ),
        retries=3,
        retry_on_status=TRANSIENT_HTTP_STATUS_CODES,
    )
    if upload_response.status_code not in (200, 201):
        raise ImageGenerationError(
            upload_response.text[:400] or f"input image upload failed: {upload_response.status_code}"
        )
    uploaded_response = _retry(
        lambda: session.post(
            f"{BASE_URL}/backend-api/files/{file_id}/uploaded",
            headers=request_headers,
            json={},
            timeout=60,
        ),
        retries=3,
        retry_on_status=TRANSIENT_HTTP_STATUS_CODES,
    )
    if not uploaded_response.ok:
        raise ImageGenerationError(
            uploaded_response.text[:400] or f"input image uploaded confirm failed: {uploaded_response.status_code}"
        )
    return UploadedInputImage(
        file_id=file_id,
        file_name=file_name,
        mime_type=mime_type,
        size_bytes=len(image_bytes),
        width=width,
        height=height,
    )


def _build_conversation_message(
    session: Session,
    access_token: str,
    device_id: str,
    prompt: str,
    input_images: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    normalized_input_images = list(input_images or [])
    if not normalized_input_images:
        return {
            "id": str(uuid.uuid4()),
            "author": {"role": "user"},
            "content": {"content_type": "text", "parts": [prompt]},
            "metadata": {"attachments": []},
        }

    parts: list[object] = [prompt]
    attachments: list[dict[str, object]] = []
    for image in normalized_input_images:
        uploaded = _build_uploaded_input_image(
            session,
            access_token,
            device_id,
            image,
        )
        image_part: dict[str, object] = {
            "content_type": "image_asset_pointer",
            "asset_pointer": f"file-service://{uploaded.file_id}",
            "size_bytes": uploaded.size_bytes,
            "mime_type": uploaded.mime_type,
        }
        if uploaded.width is not None:
            image_part["width"] = uploaded.width
        if uploaded.height is not None:
            image_part["height"] = uploaded.height
        parts.append(image_part)

        attachment: dict[str, object] = {
            "id": uploaded.file_id,
            "name": uploaded.file_name,
            "mimeType": uploaded.mime_type,
            "size": uploaded.size_bytes,
        }
        if uploaded.width is not None:
            attachment["width"] = uploaded.width
        if uploaded.height is not None:
            attachment["height"] = uploaded.height
        attachments.append(attachment)

    return {
        "id": str(uuid.uuid4()),
        "author": {"role": "user"},
        "content": {"content_type": "multimodal_text", "parts": parts},
        "metadata": {
            "attachments": attachments,
            "system_hints": ["picture_v2"],
            "serialization_metadata": {"custom_symbol_offsets": []},
        },
    }


def _download_headers_for_url(download_url: str, access_token: str | None, device_id: str | None) -> dict[str, str]:
    parsed = urlparse(str(download_url or ""))
    if parsed.netloc != "chatgpt.com":
        return {}
    headers = {
        "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "sec-fetch-dest": "image",
        "sec-fetch-mode": "no-cors",
        "sec-fetch-site": "same-origin",
    }
    normalized_token = str(access_token or "").strip()
    normalized_device_id = str(device_id or "").strip()
    if normalized_token:
        headers["Authorization"] = f"Bearer {normalized_token}"
    if normalized_device_id:
        headers["oai-device-id"] = normalized_device_id
    return headers


def _download_image_payload(
    session: Session,
    download_url: str,
    *,
    access_token: str | None = None,
    device_id: str | None = None,
) -> tuple[str, str]:
    last_error: Exception | None = None
    headers = _download_headers_for_url(download_url, access_token, device_id)
    for _ in range(3):
        try:
            response = _retry(
                lambda: session.get(
                    download_url,
                    headers=headers or None,
                    timeout=UPSTREAM_IMAGE_RESULT_TIMEOUT_SECONDS,
                ),
                retries=2,
                retry_on_status=TRANSIENT_HTTP_STATUS_CODES,
            )
        except Exception as exc:
            last_error = exc
            time.sleep(1.0)
            continue
        if response.ok and response.content:
            image_bytes = response.content
            mime_type = _detect_image_mime_type(image_bytes, response.headers.get("content-type"))
            return base64.b64encode(image_bytes).decode("ascii"), mime_type
        content_type = _safe_content_type(response.headers.get("content-type"))
        content_length = len(response.content or b"")
        print(
            "[image-download] payload failed "
            f"url={_safe_download_url_label(download_url)} status={response.status_code} "
            f"content_type={content_type} bytes={content_length}"
        )
        last_error = ImageGenerationError(
            f"download image failed: HTTP {response.status_code} content_type={content_type} bytes={content_length}"
        )
        time.sleep(1.0)
    raise ImageGenerationError(str(last_error or "download image failed"))


def _download_generated_images(
    session: Session,
    access_token: str,
    device_id: str,
    conversation_id: str,
    file_ids: list[str],
    revised_prompt: str,
) -> list[GeneratedImage]:
    images: list[GeneratedImage] = []
    for file_id in file_ids:
        normalized_file_id = str(file_id or "").strip()
        if not normalized_file_id:
            continue
        download_url = _fetch_download_url(
            session,
            access_token,
            device_id,
            conversation_id,
            normalized_file_id,
        )
        if not download_url:
            raise ImageGenerationError(f"failed to get download url for file: {normalized_file_id}")
        image_b64, mime_type = _download_image_payload(
            session,
            download_url,
            access_token=access_token,
            device_id=device_id,
        )
        images.append(
            GeneratedImage(
                b64_json=image_b64,
                revised_prompt=revised_prompt,
                url=download_url,
                mime_type=mime_type,
            )
        )
    if not images:
        raise ImageGenerationError("no downloadable image returned from upstream")
    return images


def _first_string(value: dict[str, Any] | None, *keys: str) -> str:
    if not isinstance(value, dict):
        return ""
    for key in keys:
        item = value.get(key)
        if item is not None and str(item).strip():
            return str(item).strip()
    return ""


def _resolve_chatgpt_account_id(access_token: str) -> str:
    account = account_service.get_account(access_token) or {}
    account_id = _first_string(account, "account_id", "chatgpt_account_id")
    if account_id:
        return account_id

    auth_data = account.get("auth_data")
    if isinstance(auth_data, dict):
        account_id = _first_string(auth_data, "account_id", "chatgpt_account_id")
        if account_id:
            return account_id
        nested_auth = auth_data.get("https://api.openai.com/auth")
        if isinstance(nested_auth, dict):
            account_id = _first_string(nested_auth, "account_id", "chatgpt_account_id")
            if account_id:
                return account_id

    token_payload = decode_jwt_payload(access_token)
    nested_auth = token_payload.get("https://api.openai.com/auth")
    if isinstance(nested_auth, dict):
        return _first_string(nested_auth, "account_id", "chatgpt_account_id")
    return ""


def _normalize_responses_image_tool_model(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized in PUBLIC_GPT_IMAGE_2_MODELS:
        return GPT_IMAGE_2_UPSTREAM_MODEL
    return GPT_IMAGE_2_UPSTREAM_MODEL


def _encode_image_data_url(image_bytes: bytes, mime_type: str) -> str:
    normalized_mime = str(mime_type or "").strip() or "image/png"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{normalized_mime};base64,{encoded}"


def _build_responses_request_content(
    session: Session,
    prompt: str,
    input_images: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    content = [{"type": "input_text", "text": str(prompt or "").strip()}]
    for input_image in input_images or []:
        image_bytes, mime_type = _load_input_image_bytes(session, input_image)
        content.append(
            {
                "type": "input_image",
                "image_url": _encode_image_data_url(image_bytes, mime_type),
            }
        )
    return content


def _parse_responses_sse(response, prompt: str) -> list[GeneratedImage]:
    data_lines: list[str] = []
    final_images: list[GeneratedImage] = []
    partial_images: dict[str, str] = {}
    seen: set[str] = set()

    def emit_image(b64_json: str, output_format: str = "png") -> None:
        normalized_b64 = str(b64_json or "").strip()
        if not normalized_b64:
            return
        digest = hashlib.sha256(normalized_b64.encode("utf-8")).hexdigest()
        if digest in seen:
            return
        seen.add(digest)
        normalized_format = str(output_format or "").strip().lower()
        mime_type = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
        }.get(normalized_format, "image/png")
        final_images.append(
            GeneratedImage(
                b64_json=normalized_b64,
                revised_prompt=prompt,
                url=f"data:{mime_type};base64,{normalized_b64}",
                mime_type=mime_type,
            )
        )

    def process_frame(frame: str) -> None:
        frame = str(frame or "").strip()
        if not frame or frame == "[DONE]":
            return
        try:
            payload = json.loads(frame)
        except Exception:
            return
        event_type = str(payload.get("type") or "")
        if event_type == "error":
            error_payload = payload.get("error")
            message = _extract_sse_error_text(error_payload) or "responses stream returned an error"
            raise ImageGenerationError(message)
        if event_type == "response.image_generation_call.partial_image":
            item_id = str(payload.get("item_id") or "").strip()
            partial = str(payload.get("partial_image_b64") or "").strip()
            if item_id and partial:
                partial_images[item_id] = partial
            return
        if event_type == "response.output_item.done":
            item = payload.get("item")
            if isinstance(item, dict) and item.get("type") == "image_generation_call":
                emit_image(str(item.get("result") or ""), str(item.get("output_format") or "png"))
            return
        if event_type == "response.completed":
            response_payload = payload.get("response")
            if not isinstance(response_payload, dict):
                return
            output = response_payload.get("output")
            if not isinstance(output, list):
                return
            for item in output:
                if isinstance(item, dict) and item.get("type") == "image_generation_call":
                    emit_image(str(item.get("result") or ""), str(item.get("output_format") or "png"))

    for raw_line in response.iter_lines():
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="ignore")
        else:
            line = str(raw_line or "")
        if line == "":
            process_frame("\n".join(data_lines))
            data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    process_frame("\n".join(data_lines))

    if not final_images:
        for b64_json in partial_images.values():
            emit_image(b64_json, "png")
    if not final_images:
        raise ImageGenerationError("no images generated")
    return final_images


def _send_responses_request(
    session: Session,
    access_token: str,
    account_id: str,
    prompt: str,
    model: str,
    input_images: list[dict[str, str]] | None,
    size: str | None = None,
):
    content = _build_responses_request_content(session, prompt, input_images)
    tool = {
        "type": "image_generation",
        "model": _normalize_responses_image_tool_model(model),
        "action": "edit" if input_images else "generate",
        "output_format": "png",
    }
    requested_size = upstream_image_size(size)
    if requested_size:
        tool["size"] = requested_size
    body = {
        "model": CODEX_RESPONSES_MODEL,
        "input": [{"role": "user", "content": content}],
        "tools": [tool],
        "tool_choice": {"type": "image_generation"},
        "instructions": "You generate and edit images for the user.",
        "stream": True,
        "store": False,
        "parallel_tool_calls": True,
        "include": ["reasoning.encrypted_content"],
    }
    try:
        response = _retry(
            lambda: session.post(
                CODEX_RESPONSES_BASE_URL + "/responses",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Chatgpt-Account-Id": account_id,
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "User-Agent": CODEX_RESPONSES_USER_AGENT,
                    "Originator": "codex-tui",
                    "Session_id": str(uuid.uuid4()),
                    "Connection": "Keep-Alive",
                },
                json=body,
                stream=True,
                timeout=UPSTREAM_CONVERSATION_TIMEOUT_SECONDS + 30,
            ),
            retries=3,
            retry_on_status=TRANSIENT_HTTP_STATUS_CODES,
        )
    except Exception as exc:
        if _is_transient_stream_error(exc) or is_transient_image_error(str(exc)):
            raise ImageGenerationError(str(exc)) from exc
        raise
    if not response.ok:
        raise ImageGenerationError(response.text[:400] or f"responses failed: {response.status_code}")
    return response


def generate_image_result_via_responses(
    access_token: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    n: int = 1,
    input_images: list[dict[str, str]] | None = None,
    size: str | None = None,
) -> dict:
    access_token = str(access_token or "").strip()
    if not prompt:
        raise ImageGenerationError("prompt is required")
    if not access_token:
        raise ImageGenerationError("token is required")
    if n < 1:
        raise ImageGenerationError("n must be >= 1")
    account_id = _resolve_chatgpt_account_id(access_token)
    if not account_id:
        raise ImageGenerationError("chatgpt account id is required")

    session, _fp = _new_session(access_token)
    try:
        print(
            f"[image-upstream] start token={_token_label(access_token)} "
            f"route=responses text_model={CODEX_RESPONSES_MODEL} image_model={model} n={n} size={size or 'auto'}"
        )
        results: list[GeneratedImage] = []
        for _ in range(n):
            response = _send_responses_request(
                session,
                access_token,
                account_id,
                prompt,
                model,
                input_images,
                size=size,
            )
            results.extend(_parse_responses_sse(response, prompt))
        print(f"[image-upstream] success token={_token_label(access_token)} route=responses images={len(results)}")
        return {
            "created": time.time_ns() // 1_000_000_000,
            "data": [
                {
                    "b64_json": item.b64_json,
                    "revised_prompt": item.revised_prompt,
                    "mime_type": item.mime_type,
                }
                for item in results
            ],
        }
    except Exception as exc:
        print(f"[image-upstream] fail token={_token_label(access_token)} route=responses error={exc}")
        raise
    finally:
        session.close()


def _resolve_upstream_target(access_token: str, requested_model: str) -> tuple[str, Optional[str]]:
    requested_model = str(requested_model or "").strip() or GPT_IMAGE_2_UPSTREAM_MODEL

    if requested_model in PUBLIC_GPT_IMAGE_2_MODELS:
        return GPT_IMAGE_2_UPSTREAM_MODEL, GPT_IMAGE_2_REASONING_EFFORT
    return str(requested_model or DEFAULT_MODEL).strip() or DEFAULT_MODEL, None


def generate_image_result(
    access_token: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    n: int = 1,
    input_images: list[dict[str, str]] | None = None,
    route: str = "legacy",
    size: str | None = None,
) -> dict:
    normalized_route = str(route or "legacy").strip().lower()
    if normalized_route == "responses":
        return generate_image_result_via_responses(
            access_token,
            prompt,
            model=model,
            n=n,
            input_images=input_images,
            size=size,
        )
    access_token = str(access_token or "").strip()
    if not prompt:
        raise ImageGenerationError("prompt is required")
    if not access_token:
        raise ImageGenerationError("token is required")
    if n < 1:
        raise ImageGenerationError("n must be >= 1")

    session, fp = _new_session(access_token)
    try:
        upstream_model, reasoning_effort = _resolve_upstream_target(access_token, model)
        print(
            f"[image-upstream] start token={_token_label(access_token)} "
            f"route={normalized_route} requested_model={model} upstream_model={upstream_model} "
            f"reasoning_effort={reasoning_effort or 'none'} n={n} size={size or 'auto'}"
        )
        results: list[GeneratedImage] = []
        copied_text = ""
        for _ in range(n):
            last_stream_error: Exception | None = None
            for stream_attempt in range(3):
                device_id = _bootstrap(session, fp)
                chat_token, pow_info = _chat_requirements(session, access_token, device_id)
                proof_token = None
                if pow_info.get("required"):
                    proof_token = _generate_proof_token(
                        seed=str(pow_info["seed"]),
                        difficulty=str(pow_info["difficulty"]),
                        user_agent=USER_AGENT,
                        proof_config=_pow_config(USER_AGENT),
                    )
                parent_message_id = str(uuid.uuid4())
                response = _send_conversation(
                    session,
                    access_token,
                    device_id,
                    chat_token,
                    proof_token,
                    parent_message_id,
                    prompt,
                    upstream_model,
                    reasoning_effort,
                    input_images=input_images,
                    route=normalized_route,
                    size=size,
                )
                try:
                    parsed = _parse_sse(response)
                except Exception as exc:
                    last_stream_error = exc
                    if stream_attempt < 2 and _is_transient_stream_error(exc):
                        print(
                            f"[image-upstream] retry token={_token_label(access_token)} "
                            f"stage=parse_sse attempt={stream_attempt + 1} error={exc}"
                        )
                        continue
                    raise ImageGenerationError(str(exc)) from exc

                actual_conversation_id = parsed.get("conversation_id") or ""
                file_ids = parsed.get("file_ids") or []
                response_text = str(parsed.get("text") or "").strip()
                if response_text and not copied_text:
                    copied_text = response_text
                terminal_error = str(parsed.get("error") or "").strip()
                if terminal_error and not file_ids:
                    raise ImageGenerationError(terminal_error)
                if actual_conversation_id and not file_ids:
                    file_ids = _poll_image_ids(session, access_token, device_id, actual_conversation_id)
                if not file_ids:
                    if response_text:
                        raise ImageGenerationError(response_text)
                    raise ImageGenerationError("no image returned from upstream")
                print(
                    f"[image-upstream] attachments token={_token_label(access_token)} "
                    f"conversation_id={actual_conversation_id or 'none'} count={len(file_ids)}"
                )
                try:
                    downloaded_images = _download_generated_images(
                        session=session,
                        access_token=access_token,
                        device_id=device_id,
                        conversation_id=actual_conversation_id,
                        file_ids=file_ids,
                        revised_prompt=prompt,
                    )
                except ImageGenerationError:
                    raise
                results.extend(downloaded_images)
                break
            else:
                if last_stream_error is not None:
                    raise ImageGenerationError(str(last_stream_error))
                raise ImageGenerationError("image stream failed")
        print(f"[image-upstream] success token={_token_label(access_token)} images={len(results)}")
        response_payload = {
            "created": time.time_ns() // 1_000_000_000,
            "data": [
                {
                    "b64_json": item.b64_json,
                    "revised_prompt": item.revised_prompt,
                    "mime_type": item.mime_type,
                }
                for item in results
            ],
        }
        if copied_text:
            response_payload["copied_text"] = copied_text
        return response_payload
    except Exception as exc:
        print(f"[image-upstream] fail token={_token_label(access_token)} error={exc}")
        raise
    finally:
        session.close()
