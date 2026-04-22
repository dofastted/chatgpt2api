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
from typing import Optional
from urllib.parse import unquote_to_bytes

from curl_cffi.requests import Session

from services.account_service import account_service
from services.config import config
from services import proof_of_work


BASE_URL = "https://chatgpt.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_MODEL = "gpt-4o"
GPT_IMAGE_2_UPSTREAM_MODEL = "gpt-image-2"
GPT_IMAGE_2_REASONING_EFFORT = None
MAX_POW_ATTEMPTS = 500000
SUPPORTED_INPUT_IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/avif": ".avif",
}

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


@dataclass
class TextRenderMetrics:
    foreground_area_ratio: float
    foreground_width_ratio: float
    foreground_height_ratio: float
    top_margin_ratio: float
    bottom_margin_ratio: float
    vertical_imbalance_ratio: float
    extra_component_ratio: float


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


_TEXT_RENDER_HINT_PATTERN = re.compile(
    r"\b("
    r"letters?|typography|font|text|word|words|uppercase|lowercase|sans-serif|serif"
    r")\b|字母|文字|字体|排版|黑底白字",
    re.IGNORECASE,
)


def _refine_prompt_for_text_rendering(prompt: str) -> str:
    normalized_prompt = str(prompt or "").strip()
    if not normalized_prompt:
        return normalized_prompt
    if not _TEXT_RENDER_HINT_PATTERN.search(normalized_prompt):
        return normalized_prompt
    refinement = (
        " Render the text with crisp hard edges and clean spacing. "
        "Keep one centered line only, with wide empty black margins. "
        "The letters should occupy about 55% to 65% of the canvas width and about 18% to 24% "
        "of the canvas height. "
        "No blur, glow, bloom, shadow, smear, ghosting, extra marks, or stray shapes."
    )
    return normalized_prompt + refinement


def _measure_text_render_metrics(image_bytes: bytes) -> Optional[TextRenderMetrics]:
    try:
        from io import BytesIO
        from PIL import Image
    except Exception:
        return None

    try:
        image = Image.open(BytesIO(image_bytes)).convert("L")
    except Exception:
        return None

    width, height = image.size
    pixels = image.load()
    foreground_x: list[int] = []
    foreground_y: list[int] = []
    for y in range(height):
        for x in range(width):
            if pixels[x, y] > 30:
                foreground_x.append(x)
                foreground_y.append(y)
    if not foreground_x or not foreground_y:
        return None

    left = min(foreground_x)
    right = max(foreground_x)
    top = min(foreground_y)
    bottom = max(foreground_y)
    foreground_area_ratio = len(foreground_x) / max(width * height, 1)
    foreground_width_ratio = (right - left + 1) / max(width, 1)
    foreground_height_ratio = (bottom - top + 1) / max(height, 1)
    top_margin_ratio = top / max(height, 1)
    bottom_margin_ratio = (height - 1 - bottom) / max(height, 1)
    vertical_imbalance_ratio = abs(top_margin_ratio - bottom_margin_ratio)

    binary_threshold = 60
    component_sizes: list[int] = []
    visited: set[tuple[int, int]] = set()
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            if pixels[x, y] <= binary_threshold or (x, y) in visited:
                continue
            stack = [(x, y)]
            visited.add((x, y))
            size = 0
            while stack:
                current_x, current_y = stack.pop()
                size += 1
                for next_x, next_y in (
                    (current_x + 1, current_y),
                    (current_x - 1, current_y),
                    (current_x, current_y + 1),
                    (current_x, current_y - 1),
                ):
                    if next_x < left or next_x > right or next_y < top or next_y > bottom:
                        continue
                    if pixels[next_x, next_y] <= binary_threshold or (next_x, next_y) in visited:
                        continue
                    visited.add((next_x, next_y))
                    stack.append((next_x, next_y))
            component_sizes.append(size)
    component_sizes.sort(reverse=True)
    total_component_pixels = sum(component_sizes)
    extra_component_ratio = 0.0
    if total_component_pixels > 0 and len(component_sizes) > 4:
        extra_component_ratio = sum(component_sizes[4:]) / total_component_pixels

    return TextRenderMetrics(
        foreground_area_ratio=foreground_area_ratio,
        foreground_width_ratio=foreground_width_ratio,
        foreground_height_ratio=foreground_height_ratio,
        top_margin_ratio=top_margin_ratio,
        bottom_margin_ratio=bottom_margin_ratio,
        vertical_imbalance_ratio=vertical_imbalance_ratio,
        extra_component_ratio=extra_component_ratio,
    )


def _needs_text_render_retry(prompt: str, image_bytes: bytes) -> bool:
    if not _TEXT_RENDER_HINT_PATTERN.search(str(prompt or "").strip()):
        return False
    metrics = _measure_text_render_metrics(image_bytes)
    if metrics is None:
        return False
    return (
        metrics.foreground_area_ratio > 0.11
        or metrics.foreground_width_ratio > 0.75
        or metrics.foreground_height_ratio > 0.28
        or metrics.vertical_imbalance_ratio > 0.08
        or metrics.extra_component_ratio > 0.004
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
    for attempt in range(retries):
        try:
            response = fn()
        except Exception as exc:
            last_error = exc
            time.sleep(delay)
            continue
        if retry_on_status and getattr(response, "status_code", 0) in retry_on_status:
            last_response = response
            time.sleep(delay * (attempt + 1))
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
    )


def is_low_quality_image_error(message: str) -> bool:
    return "low quality text render" in str(message or "").lower()


def is_transient_image_error(message: str) -> bool:
    text = str(message or "").lower()
    return (
        _is_transient_stream_error(Exception(text))
        or "download image failed" in text
        or "failed to get download url" in text
        or "no image returned from upstream" in text
        or "timed out" in text
        or "timeout" in text
    )


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

    response = _retry(
        lambda: session.post(
            BASE_URL + "/backend-api/conversation",
            headers=headers,
            json=request_body,
            stream=True,
            timeout=180,
        ),
        retries=3,
    )
    if not response.ok:
        raise ImageGenerationError(response.text[:400] or f"conversation failed: {response.status_code}")
    return response


def _parse_sse(response) -> dict:
    file_ids: list[str] = []
    conversation_id = ""
    text_parts: list[str] = []
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
        conversation_id = str(obj.get("conversation_id") or conversation_id)
        if obj.get("type") in {"resume_conversation_token", "message_marker", "message_stream_complete"}:
            conversation_id = str(obj.get("conversation_id") or conversation_id)
        data = obj.get("v")
        if isinstance(data, dict):
            conversation_id = str(data.get("conversation_id") or conversation_id)
        message = obj.get("message") or {}
        content = message.get("content") or {}
        if content.get("content_type") == "text":
            parts = content.get("parts") or []
            if parts:
                text_parts.append(str(parts[0]))
    return {"conversation_id": conversation_id, "file_ids": file_ids, "text": "".join(text_parts)}


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
    while time.time() - started < 180:
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
            retry_on_status=(429, 502, 503, 504),
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
        retry_on_status=(429, 500, 502, 503, 504),
    )
    if not response.ok:
        return ""
    return str((response.json() or {}).get("download_url") or "")


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
        retry_on_status=(429, 500, 502, 503, 504),
    )
    if not response.ok or not response.content:
        raise ImageGenerationError("failed to fetch input image")
    mime_type = _normalize_input_image_mime_type(response.content, response.headers.get("content-type"))
    return response.content, mime_type


def _detect_input_image_dimensions(image_bytes: bytes) -> tuple[int | None, int | None]:
    try:
        from io import BytesIO
        from PIL import Image
    except Exception:
        return None, None
    try:
        image = Image.open(BytesIO(image_bytes))
        return int(image.width), int(image.height)
    except Exception:
        return None, None


def _build_uploaded_input_image(
    session: Session,
    access_token: str,
    device_id: str,
    image_url: str,
) -> UploadedInputImage:
    image_bytes, mime_type = _download_input_image(session, image_url)
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
            },
            timeout=60,
        ),
        retries=3,
        retry_on_status=(429, 500, 502, 503, 504),
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
        retry_on_status=(429, 500, 502, 503, 504),
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
        retry_on_status=(429, 500, 502, 503, 504),
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
            str((image or {}).get("image_url") or "").strip(),
        )
        image_part: dict[str, object] = {
            "content_type": "image_asset_pointer",
            "asset_pointer": f"file-service://{uploaded.file_id}",
            "size_bytes": uploaded.size_bytes,
        }
        attachment: dict[str, object] = {
            "id": uploaded.file_id,
            "name": uploaded.file_name,
            "mimeType": uploaded.mime_type,
            "size": uploaded.size_bytes,
        }
        if uploaded.width is not None:
            image_part["width"] = uploaded.width
            attachment["width"] = uploaded.width
        if uploaded.height is not None:
            image_part["height"] = uploaded.height
            attachment["height"] = uploaded.height
        parts.append(image_part)
        attachments.append(attachment)

    return {
        "id": str(uuid.uuid4()),
        "author": {"role": "user"},
        "content": {"content_type": "multimodal_text", "parts": parts},
        "metadata": {"attachments": attachments},
    }


def _download_image_payload(session: Session, download_url: str) -> tuple[str, str]:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = _retry(
                lambda: session.get(download_url, timeout=60),
                retries=2,
                retry_on_status=(429, 500, 502, 503, 504),
            )
        except Exception as exc:
            last_error = exc
            time.sleep(1.0)
            continue
        if response.ok and response.content:
            image_bytes = response.content
            mime_type = _detect_image_mime_type(image_bytes, response.headers.get("content-type"))
            return base64.b64encode(image_bytes).decode("ascii"), mime_type
        last_error = ImageGenerationError("download image failed")
        time.sleep(1.0)
    raise ImageGenerationError(str(last_error or "download image failed"))


def _download_generated_images(
    session: Session,
    access_token: str,
    device_id: str,
    conversation_id: str,
    file_ids: list[str],
    prompt: str,
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
        image_b64, mime_type = _download_image_payload(session, download_url)
        if _needs_text_render_retry(prompt, base64.b64decode(image_b64)):
            raise ImageGenerationError(f"low quality text render for file: {normalized_file_id}")
        images.append(
            GeneratedImage(
                b64_json=image_b64,
                revised_prompt=prompt,
                url=download_url,
                mime_type=mime_type,
            )
        )
    if not images:
        raise ImageGenerationError("no downloadable image returned from upstream")
    return images


def _resolve_upstream_target(access_token: str, requested_model: str) -> tuple[str, Optional[str]]:
    requested_model = str(requested_model or "").strip() or "gpt-image-1"

    if requested_model == "gpt-image-1":
        return "auto", None
    if requested_model == "gpt-image-2":
        return GPT_IMAGE_2_UPSTREAM_MODEL, GPT_IMAGE_2_REASONING_EFFORT
    return str(requested_model or DEFAULT_MODEL).strip() or DEFAULT_MODEL, None


def generate_image_result(
    access_token: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    n: int = 1,
    input_images: list[dict[str, str]] | None = None,
) -> dict:
    prompt = _refine_prompt_for_text_rendering(prompt)
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
            f"[image-upstream] start token={access_token[:12]}... "
            f"requested_model={model} upstream_model={upstream_model} reasoning_effort={reasoning_effort or 'none'} n={n}"
        )
        results: list[GeneratedImage] = []
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
                )
                try:
                    parsed = _parse_sse(response)
                except Exception as exc:
                    last_stream_error = exc
                    if stream_attempt < 2 and _is_transient_stream_error(exc):
                        print(
                            f"[image-upstream] retry token={access_token[:12]}... "
                            f"stage=parse_sse attempt={stream_attempt + 1} error={exc}"
                        )
                        continue
                    raise ImageGenerationError(str(exc)) from exc

                actual_conversation_id = parsed.get("conversation_id") or ""
                file_ids = parsed.get("file_ids") or []
                response_text = str(parsed.get("text") or "").strip()
                if actual_conversation_id and not file_ids:
                    file_ids = _poll_image_ids(session, access_token, device_id, actual_conversation_id)
                if not file_ids:
                    if response_text:
                        raise ImageGenerationError(response_text)
                    raise ImageGenerationError("no image returned from upstream")
                print(
                    f"[image-upstream] attachments token={access_token[:12]}... "
                    f"conversation_id={actual_conversation_id or 'none'} count={len(file_ids)} file_ids={file_ids}"
                )
                try:
                    downloaded_images = _download_generated_images(
                        session=session,
                        access_token=access_token,
                        device_id=device_id,
                        conversation_id=actual_conversation_id,
                        file_ids=file_ids,
                        prompt=prompt,
                    )
                except ImageGenerationError as exc:
                    if stream_attempt < 2 and "low quality text render" in str(exc):
                        print(
                            f"[image-upstream] retry token={access_token[:12]}... "
                            f"stage=text_render attempt={stream_attempt + 1} error={exc}"
                        )
                        continue
                    raise
                results.extend(downloaded_images)
                break
            else:
                if last_stream_error is not None:
                    raise ImageGenerationError(str(last_stream_error))
                raise ImageGenerationError("image stream failed")
        print(f"[image-upstream] success token={access_token[:12]}... images={len(results)}")
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
        print(f"[image-upstream] fail token={access_token[:12]}... error={exc}")
        raise
    finally:
        session.close()
