from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
from pathlib import Path
from threading import Lock
from threading import Event, Thread
from time import time
from typing import Any
from uuid import uuid4
from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from services.account_service import account_service
from services.config import config
from services.backend_service import BackendService
from services.image_service import ImageGenerationError
from services.user_key_service import user_key_service
from services.version import get_app_version


BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIST_DIR = BASE_DIR / "web_dist"
WEB_OUT_DIR = BASE_DIR / "web" / "out"
DONATION_REWARD_QUOTA = 50
DEFAULT_USER_KEY_PRICING = dict(user_key_service.DEFAULT_PRICING)
SUPPORTED_IMAGE_MODELS = tuple(user_key_service.SUPPORTED_MODELS)
MAX_IMAGES_PER_REQUEST = 2
IMAGE_REQUEST_COOLDOWN_SECONDS = 10
MAX_QUEUED_IMAGE_REQUESTS = 100
DEFAULT_RESPONSES_MODEL = "gpt-5"
RESPONSES_STORE: dict[str, dict[str, object]] = {}
RESPONSES_STORE_LOCK = Lock()
IMAGE_REQUEST_SCHEDULER: dict[str, dict[str, float | int]] = {}
IMAGE_REQUEST_SCHEDULER_LOCK = Lock()
IMAGE_REQUEST_SLEEP = asyncio.sleep


class UserKeyPricingRequest(BaseModel):
    gpt_image_1: int = Field(default=1, ge=0, alias="gpt-image-1")
    gpt_image_2: int = Field(default=4, ge=0, alias="gpt-image-2")

    model_config = {"populate_by_name": True}

    def to_pricing_dict(self) -> dict[str, int]:
        return {
            "gpt-image-1": int(self.gpt_image_1),
            "gpt-image-2": int(self.gpt_image_2),
        }


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str = "gpt-image-1"
    n: int = Field(default=1, ge=1, le=MAX_IMAGES_PER_REQUEST)
    response_format: str = "b64_json"
    output_format: str | None = None
    background: str | None = None
    quality: str | None = None
    size: str | None = None
    partial_images: int = Field(default=0, ge=0, le=3)
    output_compression: int | None = None
    stream: bool = False
    history_disabled: bool = True


class ResponsesToolRequest(BaseModel):
    type: str
    model: str | None = None
    size: str | None = None
    quality: str | None = None
    format: str | None = None
    compression: int | None = None
    background: str | None = None
    action: str | None = None
    partial_images: int | None = None


class ResponsesCreateRequest(BaseModel):
    model: str = "gpt-5"
    input: Any
    n: int = Field(default=1, ge=1, le=MAX_IMAGES_PER_REQUEST)
    tools: list[ResponsesToolRequest] = Field(default_factory=list)
    tool_choice: dict[str, Any] | str | None = None
    previous_response_id: str | None = None
    stream: bool = False
    metadata: dict[str, str] | None = None

class AccountCreateRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)
    accounts: list[dict[str, Any]] = Field(default_factory=list)


class AccountDeleteRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)


class AccountRefreshRequest(BaseModel):
    access_tokens: list[str] = Field(default_factory=list)


class AccountUpdateRequest(BaseModel):
    access_token: str = Field(default="")
    category: str | None = None
    type: str | None = None
    status: str | None = None
    quota: int | None = None


class UserKeyCreateRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=100)
    quota: int = Field(default=0, ge=0)
    prefix: str | None = None
    label_prefix: str | None = None
    status: str | None = None
    pricing: UserKeyPricingRequest | None = None


class UserKeyDeleteRequest(BaseModel):
    keys: list[str] = Field(default_factory=list)


class UserKeyUpdateRequest(BaseModel):
    key: str = Field(default="")
    label: str | None = None
    quota: int | None = None
    status: str | None = None
    pricing: UserKeyPricingRequest | None = None


@dataclass(frozen=True)
class AuthContext:
    role: str
    auth_type: str
    remaining_quota: int | None = None
    user_key_id: str | None = None
    user_key_label: str | None = None
    pricing: dict[str, int] | None = None


def resolve_auth_context(authorization: str | None) -> AuthContext | None:
    auth_key = extract_bearer_token(authorization)
    if not auth_key:
        return None
    if auth_key == str(config.admin_auth_key or "").strip():
        return AuthContext(role="admin", auth_type="admin_auth_key")
    if auth_key == str(config.auth_key or "").strip():
        return AuthContext(role="user", auth_type="auth_key")

    user_key = user_key_service.get_user_key(auth_key)
    if user_key is None or user_key.get("status") != user_key_service.ENABLED_STATUS:
        return None
    return AuthContext(
        role="user",
        auth_type="user_key",
        remaining_quota=max(0, int(user_key.get("quota") or 0)),
        user_key_id=str(user_key.get("id") or "") or None,
        user_key_label=str(user_key.get("label") or "") or None,
        pricing=user_key_service.normalize_pricing(user_key.get("pricing")),
    )


def resolve_auth_role(authorization: str | None) -> str | None:
    context = resolve_auth_context(authorization)
    if context is None:
        return None
    return context.role


def build_auth_session_payload(app_version: str, context: AuthContext) -> dict[str, object]:
    return {
        "ok": True,
        "version": app_version,
        "role": context.role,
        "auth_type": context.auth_type,
        "remaining_quota": context.remaining_quota,
        "user_key_id": context.user_key_id,
        "user_key_label": context.user_key_label,
        "pricing": context.pricing,
    }


def resolve_user_key_pricing(pricing: dict[str, int] | None) -> dict[str, int]:
    return user_key_service.normalize_pricing(pricing or DEFAULT_USER_KEY_PRICING)


def build_quota_payload(context: AuthContext, available_quota: int) -> dict[str, object]:
    return {
        "available_quota": available_quota,
        "auth_type": context.auth_type,
        "remaining_quota": available_quota if context.auth_type == "user_key" else None,
        "pricing": resolve_user_key_pricing(context.pricing) if context.auth_type == "user_key" else None,
    }


def build_billing_payload(
        requested_model: str,
        unit_cost: int,
        charged_quota: int,
        remaining_quota: int,
) -> dict[str, object]:
    return {
        "requested_model": requested_model,
        "unit_cost": unit_cost,
        "charged_quota": charged_quota,
        "remaining_quota": remaining_quota,
    }


def normalize_requested_image_model(model: str) -> str:
    normalized_model = str(model or "").strip() or "gpt-image-1"
    if normalized_model not in SUPPORTED_IMAGE_MODELS:
        raise HTTPException(status_code=400, detail={"error": f"unsupported image model: {normalized_model}"})
    return normalized_model


def clear_image_request_timestamps() -> None:
    with IMAGE_REQUEST_SCHEDULER_LOCK:
        IMAGE_REQUEST_SCHEDULER.clear()


def release_image_request_waiter(auth_token: str) -> None:
    normalized_token = str(auth_token or "").strip()
    if not normalized_token:
        return
    with IMAGE_REQUEST_SCHEDULER_LOCK:
        state = IMAGE_REQUEST_SCHEDULER.get(normalized_token)
        if state is None:
            return
        waiting = max(0, int(state.get("waiting") or 0) - 1)
        state["waiting"] = waiting
        if waiting == 0 and float(state.get("next_available_at") or 0.0) <= float(time()):
            IMAGE_REQUEST_SCHEDULER.pop(normalized_token, None)


async def wait_for_image_request_turn(auth_token: str, now_value: float | None = None) -> None:
    normalized_token = str(auth_token or "").strip()
    if not normalized_token:
        return
    current_time = float(time() if now_value is None else now_value)
    wait_seconds = 0.0
    is_waiting = False
    with IMAGE_REQUEST_SCHEDULER_LOCK:
        state = IMAGE_REQUEST_SCHEDULER.setdefault(
            normalized_token,
            {"next_available_at": 0.0, "waiting": 0},
        )
        scheduled_start = max(current_time, float(state.get("next_available_at") or 0.0))
        wait_seconds = max(0.0, scheduled_start - current_time)
        if wait_seconds > 0:
            waiting = int(state.get("waiting") or 0)
            if waiting >= MAX_QUEUED_IMAGE_REQUESTS:
                raise HTTPException(
                    status_code=429,
                    detail={"error": f"image queue is full, max_waiting={MAX_QUEUED_IMAGE_REQUESTS}"},
                )
            state["waiting"] = waiting + 1
            is_waiting = True
        state["next_available_at"] = scheduled_start + IMAGE_REQUEST_COOLDOWN_SECONDS
    if wait_seconds <= 0:
        return
    try:
        await IMAGE_REQUEST_SLEEP(wait_seconds)
    finally:
        if is_waiting:
            release_image_request_waiter(normalized_token)


async def generate_image_payload(
        *,
        service: BackendService,
        context: AuthContext,
        authorization: str | None,
        prompt: str,
        model: str,
        n: int,
        input_images: list[dict[str, str]] | None = None,
) -> tuple[dict[str, object], dict[str, object] | None]:
    reserved_user_key = ""
    request_cost = 0
    unit_cost = 0
    remaining_quota_after_charge = max(0, int(context.remaining_quota or 0))
    if context.auth_type == "user_key":
        reserved_user_key = extract_bearer_token(authorization)
        pricing = resolve_user_key_pricing(context.pricing)
        unit_cost = max(0, int(pricing.get(model) or 0))
        request_cost = max(1, int(n or 1)) * unit_cost
        reserved = user_key_service.consume_quota(reserved_user_key, request_cost)
        if reserved is None:
            raise HTTPException(
                status_code=403,
                detail={"error": f"quota is insufficient for this request, required={request_cost}"},
            )
        remaining_quota_after_charge = max(0, int(reserved.get("quota") or 0))
    try:
        result = await run_in_threadpool(
            service.generate_with_pool,
            prompt,
            model,
            n,
            input_images,
        )
        billing_payload = None
        if reserved_user_key:
            used_item = user_key_service.mark_used(reserved_user_key)
            if used_item is not None:
                remaining_quota_after_charge = max(0, int(used_item.get("quota") or 0))
            billing_payload = build_billing_payload(
                requested_model=model,
                unit_cost=unit_cost,
                charged_quota=request_cost,
                remaining_quota=remaining_quota_after_charge,
            )
            result = {
                **result,
                "billing": billing_payload,
            }
        return result, billing_payload
    except ImageGenerationError as exc:
        if reserved_user_key:
            user_key_service.refund_quota(reserved_user_key, request_cost)
        raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
    except HTTPException:
        if reserved_user_key:
            user_key_service.refund_quota(reserved_user_key, request_cost)
        raise
    except Exception:
        if reserved_user_key:
            user_key_service.refund_quota(reserved_user_key, request_cost)
        raise


def response_store_set(response_id: str, payload: dict[str, object]) -> None:
    with RESPONSES_STORE_LOCK:
        RESPONSES_STORE[response_id] = dict(payload)


def response_store_get(response_id: str) -> dict[str, object] | None:
    with RESPONSES_STORE_LOCK:
        payload = RESPONSES_STORE.get(response_id)
    if payload is None:
        return None
    return dict(payload)


def get_image_generation_tool(tools: list[ResponsesToolRequest]) -> ResponsesToolRequest | None:
    for tool in tools:
        if str(tool.type or "").strip() == "image_generation":
            return tool
    return None


def has_image_generation_tool(tools: list[ResponsesToolRequest]) -> bool:
    return get_image_generation_tool(tools) is not None


def validate_responses_tool_choice(tool_choice: dict[str, Any] | str | None) -> None:
    if tool_choice in (None, "auto", "required"):
        return
    if isinstance(tool_choice, dict) and str(tool_choice.get("type") or "").strip() == "image_generation":
        return
    raise HTTPException(status_code=400, detail={"error": "only image_generation tool_choice is supported"})


def resolve_requested_response_image_model(body: ResponsesCreateRequest) -> str:
    image_tool = get_image_generation_tool(body.tools)
    tool_model = str(image_tool.model or "").strip() if image_tool is not None else ""
    if tool_model:
        return normalize_requested_image_model(tool_model)
    requested_model = str(body.model or "").strip()
    if requested_model in SUPPORTED_IMAGE_MODELS:
        return normalize_requested_image_model(requested_model)
    return "gpt-image-1"


def _normalize_response_input_image_url(item: dict[str, Any]) -> str:
    image_url = item.get("image_url")
    if isinstance(image_url, dict):
        image_url = image_url.get("url")
    normalized = str(image_url or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail={"error": "responses input_image must include image_url"})
    lowered = normalized.lower()
    if lowered.startswith("data:"):
        if not lowered.startswith("data:image/"):
            raise HTTPException(
                status_code=400,
                detail={"error": "responses input_image data URL must use an image mime type"},
            )
        return normalized
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return normalized
    raise HTTPException(
        status_code=400,
        detail={"error": "responses input_image only supports http(s) URL or data:image/* URL"},
    )


def extract_image_inputs_from_responses_input(value: Any) -> list[dict[str, str]]:
    if isinstance(value, list):
        images: list[dict[str, str]] = []
        for item in value:
            images.extend(extract_image_inputs_from_responses_input(item))
        return images
    if isinstance(value, dict):
        item_type = str(value.get("type") or "").strip()
        if item_type == "input_image":
            if value.get("file_id") is not None:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "responses input_image file_id is not supported yet"},
                )
            return [{"type": "input_image", "image_url": _normalize_response_input_image_url(value)}]
        if item_type in {"image", "image_generation_call"}:
            raise HTTPException(
                status_code=400,
                detail={"error": "responses image output replay and multi-turn image edit are not supported yet"},
            )
        if "content" in value:
            return extract_image_inputs_from_responses_input(value.get("content"))
    return []


def validate_responses_input_images(input_value: Any) -> list[dict[str, str]]:
    input_images = extract_image_inputs_from_responses_input(input_value)
    if len(input_images) > 1:
        raise HTTPException(
            status_code=400,
            detail={"error": "responses input_image currently supports at most one image"},
        )
    return input_images


def extract_text_segments_from_responses_input(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        segments: list[str] = []
        for item in value:
            segments.extend(extract_text_segments_from_responses_input(item))
        return segments
    if isinstance(value, dict):
        item_type = str(value.get("type") or "").strip()
        if item_type == "input_image":
            return []
        if item_type in {"image", "image_generation_call"}:
            raise HTTPException(
                status_code=400,
                detail={"error": "responses image output replay and multi-turn image edit are not supported yet"},
            )
        if item_type in {"input_text", "output_text", "text"}:
            return extract_text_segments_from_responses_input(value.get("text"))
        if "content" in value:
            return extract_text_segments_from_responses_input(value.get("content"))
        if "text" in value:
            return extract_text_segments_from_responses_input(value.get("text"))
    return []


def extract_responses_prompt(input_value: Any) -> str:
    segments = extract_text_segments_from_responses_input(input_value)
    prompt = "\n".join(segment for segment in segments if segment).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail={"error": "responses input must include text content"})
    return prompt


def normalize_output_format(output_format: str | None, mime_type: str | None) -> str:
    requested = str(output_format or "").strip().lower()
    if requested in {"png", "jpeg", "webp"}:
        return requested
    normalized_mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime == "image/jpeg":
        return "jpeg"
    if normalized_mime == "image/webp":
        return "webp"
    return "png"


def build_images_response_payload(
        image_result: dict[str, object],
        billing: dict[str, object] | None,
) -> dict[str, object]:
    payload = {
        "created": int(image_result.get("created") or time()),
        "data": [
            {
                "b64_json": str((item or {}).get("b64_json") or "").strip(),
                **(
                    {"revised_prompt": (item or {}).get("revised_prompt")}
                    if (item or {}).get("revised_prompt") is not None
                    else {}
                ),
            }
            for item in list(image_result.get("data") or [])
            if str((item or {}).get("b64_json") or "").strip()
        ],
    }
    if billing is not None:
        payload["billing"] = billing
    return payload


def build_responses_payload(
        response_id: str,
        response_model: str,
        image_result: dict[str, object],
        billing: dict[str, object] | None,
        *,
        metadata: dict[str, str] | None = None,
        previous_response_id: str | None = None,
) -> dict[str, object]:
    created_at = int(time())
    output_items: list[dict[str, object]] = []
    for item in list(image_result.get("data") or []):
        result = str((item or {}).get("b64_json") or "").strip()
        if not result:
            continue
        output_items.append(
            {
                "id": f"ig_{uuid4().hex}",
                "type": "image_generation_call",
                "status": "completed",
                "result": result,
            }
        )
    payload = {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "model": str(response_model or "").strip() or DEFAULT_RESPONSES_MODEL,
        "output": output_items,
        "parallel_tool_calls": False,
        "previous_response_id": str(previous_response_id or "").strip() or None,
        "metadata": metadata or {},
        "text": {"format": {"type": "text"}},
        "usage": None,
    }
    if billing is not None:
        payload["billing"] = billing
    return payload


def clone_json_value(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def build_responses_stream_snapshot(payload: dict[str, object], status: str) -> dict[str, object]:
    snapshot = clone_json_value(payload)
    snapshot["status"] = status
    if status != "completed":
        snapshot["output"] = []
        snapshot["billing"] = None
    return snapshot


def format_sse_event(event_type: str | None, payload: Any) -> bytes:
    lines: list[str] = []
    if event_type:
        lines.append(f"event: {event_type}")
    if isinstance(payload, str) and payload == "[DONE]":
        lines.append("data: [DONE]")
    else:
        for line in json.dumps(payload, ensure_ascii=False, separators=(",", ":")).splitlines():
            lines.append(f"data: {line}")
    lines.append("")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def iter_responses_stream(payload: dict[str, object]):
    sequence_number = 0

    def emit(event_type: str, **extra: Any):
        nonlocal sequence_number
        event_payload = {
            "type": event_type,
            "sequence_number": sequence_number,
            **extra,
        }
        sequence_number += 1
        return format_sse_event(event_type, event_payload)

    response_id = str(payload.get("id") or "").strip()
    created_snapshot = build_responses_stream_snapshot(payload, "in_progress")
    yield emit("response.created", response=created_snapshot)
    yield emit("response.in_progress", response=created_snapshot)

    for output_index, item in enumerate(list(payload.get("output") or [])):
        output_item = clone_json_value(item)
        added_item = clone_json_value(item)
        if str(added_item.get("status") or "").strip() == "completed":
            added_item["status"] = "in_progress"
        if str(added_item.get("type") or "").strip() == "image_generation_call":
            added_item["result"] = ""

        yield emit("response.output_item.added", output_index=output_index, item=added_item)
        if str(output_item.get("type") or "").strip() == "image_generation_call":
            item_id = str(output_item.get("id") or "")
            yield emit("response.image_generation_call.in_progress", output_index=output_index, item_id=item_id)
            yield emit("response.image_generation_call.generating", output_index=output_index, item_id=item_id)
            yield emit("response.image_generation_call.completed", output_index=output_index, item_id=item_id)

        yield emit("response.output_item.done", output_index=output_index, item=output_item)

    yield emit("response.completed", response=clone_json_value(payload))
    yield format_sse_event(None, "[DONE]")


def iter_images_stream(
        payload: dict[str, object],
        *,
        output_format: str | None,
        background: str | None,
        quality: str | None,
        size: str | None,
        partial_images: int = 0,
):
    created_at = int(payload.get("created") or time())
    data_items = list(payload.get("data") or [])
    for image_index, item in enumerate(data_items):
        image_b64 = str((item or {}).get("b64_json") or "").strip()
        if not image_b64:
            continue
        item_output_format = normalize_output_format(output_format, (item or {}).get("mime_type"))
        partial_count = max(0, int(partial_images or 0))
        if partial_count > 0:
            yield format_sse_event(
                None,
                {
                    "type": "image_generation.partial_image",
                    "b64_json": image_b64,
                    "created_at": created_at,
                    "background": str(background or "auto"),
                    "output_format": item_output_format,
                    "quality": str(quality or "auto"),
                    "size": str(size or "auto"),
                    "partial_image_index": image_index,
                },
            )
        completed_event: dict[str, object] = {
            "type": "image_generation.completed",
            "b64_json": image_b64,
            "created_at": created_at,
            "background": str(background or "auto"),
            "output_format": item_output_format,
            "quality": str(quality or "auto"),
            "size": str(size or "auto"),
        }
        if payload.get("usage") is not None:
            completed_event["usage"] = payload.get("usage")
        yield format_sse_event(None, completed_event)
    yield format_sse_event(None, "[DONE]")


def build_model_item(model_id: str) -> dict[str, object]:
    return {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "chatgpt2api",
    }


def extract_bearer_token(authorization: str | None) -> str:
    scheme, _, value = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return ""
    return value.strip()


def require_auth_key(authorization: str | None) -> AuthContext:
    context = resolve_auth_context(authorization)
    if context is None:
        raise HTTPException(status_code=401, detail={"error": "authorization is invalid"})
    return context


def require_admin_auth_key(authorization: str | None) -> AuthContext:
    context = require_auth_key(authorization)
    if context.role != "admin":
        raise HTTPException(status_code=403, detail={"error": "admin authorization is required"})
    return context


def start_limited_account_watcher(stop_event: Event) -> Thread:
    def worker() -> None:
        while not stop_event.is_set():
            try:
                limited_tokens = account_service.list_limited_tokens()
                if limited_tokens:
                    print(f"[account-limited-watcher] checking {len(limited_tokens)} limited accounts")
                    account_service.refresh_accounts(limited_tokens)
            except Exception as exc:
                print(f"[account-limited-watcher] fail {exc}")
            stop_event.wait(300)

    thread = Thread(target=worker, name="limited-account-watcher", daemon=True)
    thread.start()
    return thread


def resolve_web_asset(requested_path: str) -> Path | None:
    clean_path = requested_path.strip("/")
    for base_dir in (WEB_DIST_DIR, WEB_OUT_DIR):
        if not base_dir.exists():
            continue
        if not clean_path:
            candidates = [base_dir / "index.html"]
        else:
            relative_path = Path(clean_path)
            candidates = [
                base_dir / relative_path,
                base_dir / relative_path / "index.html",
                base_dir / f"{clean_path}.html",
            ]

        for candidate in candidates:
            try:
                candidate.relative_to(base_dir)
            except ValueError:
                continue
            if candidate.is_file():
                return candidate

    return None


def create_app() -> FastAPI:
    service = BackendService(account_service)
    app_version = get_app_version()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop_event = Event()
        thread = start_limited_account_watcher(stop_event)
        try:
            yield
        finally:
            stop_event.set()
            thread.join(timeout=1)

    app = FastAPI(title="chatgpt2api", version=app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    router = APIRouter()

    @router.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [
                build_model_item("gpt-image-1"),
                build_model_item("gpt-image-2"),
            ],
        }

    @router.post("/auth/login")
    async def login(authorization: str | None = Header(default=None)):
        context = require_auth_key(authorization)
        return build_auth_session_payload(app_version, context)

    @router.get("/auth/session")
    async def get_auth_session(authorization: str | None = Header(default=None)):
        context = require_auth_key(authorization)
        return build_auth_session_payload(app_version, context)

    @router.post("/v1/response")
    @router.post("/v1/responses")
    async def create_response(
            body: ResponsesCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        context = require_auth_key(authorization)
        if body.previous_response_id:
            raise HTTPException(
                status_code=400,
                detail={"error": "responses previous_response_id is not supported for image generation yet"},
            )
        if not has_image_generation_tool(body.tools):
            raise HTTPException(
                status_code=400,
                detail={"error": "responses request must include an image_generation tool"},
            )
        validate_responses_tool_choice(body.tool_choice)
        input_images = validate_responses_input_images(body.input)
        prompt = extract_responses_prompt(body.input)
        await wait_for_image_request_turn(extract_bearer_token(authorization))

        response_model = str(body.model or "").strip() or DEFAULT_RESPONSES_MODEL
        if response_model in SUPPORTED_IMAGE_MODELS:
            response_model = DEFAULT_RESPONSES_MODEL
        requested_model = resolve_requested_response_image_model(body)
        image_result, billing_payload = await generate_image_payload(
            service=service,
            context=context,
            authorization=authorization,
            prompt=prompt,
            model=requested_model,
            n=body.n,
            input_images=input_images,
        )
        response_id = f"resp_{uuid4().hex}"
        payload = build_responses_payload(
            response_id=response_id,
            response_model=response_model,
            image_result=image_result,
            billing=billing_payload,
            metadata=body.metadata,
            previous_response_id=body.previous_response_id,
        )
        response_store_set(response_id, payload)
        if body.stream:
            return StreamingResponse(
                iter_responses_stream(payload),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        return payload

    @router.get("/v1/response/{response_id}")
    @router.get("/v1/responses/{response_id}")
    async def get_response(response_id: str, authorization: str | None = Header(default=None)):
        require_auth_key(authorization)
        payload = response_store_get(str(response_id or "").strip())
        if payload is None:
            raise HTTPException(status_code=404, detail={"error": "response not found"})
        return payload

    @router.get("/version")
    async def get_version():
        return {"version": app_version}

    @router.get("/api/accounts")
    async def get_accounts(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return {"items": account_service.list_accounts()}

    @router.get("/api/user-keys")
    async def get_user_keys(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return {"items": user_key_service.list_public_user_keys()}

    @router.post("/api/accounts")
    async def create_accounts(
            body: AccountCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        imported_accounts = [dict(item) for item in body.accounts if isinstance(item, dict)]
        tokens = [str(token or "").strip() for token in body.tokens if str(token or "").strip()]
        if not imported_accounts and not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens is required"})
        if imported_accounts:
            result = account_service.add_account_items(imported_accounts)
            refresh_targets = [
                str(item.get("access_token") or "").strip()
                for item in imported_accounts
                if str(item.get("access_token") or "").strip()
            ]
        else:
            result = account_service.add_accounts(tokens)
            refresh_targets = tokens
        refresh_result = account_service.refresh_accounts(refresh_targets)
        return {
            **result,
            "refreshed": refresh_result.get("refreshed", 0),
            "errors": refresh_result.get("errors", []),
            "items": refresh_result.get("items", result.get("items", [])),
        }

    @router.post("/api/donations/accounts")
    async def create_donation_accounts(
            body: AccountCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        context = require_auth_key(authorization)
        imported_accounts = [dict(item) for item in body.accounts if isinstance(item, dict)]
        tokens = [str(token or "").strip() for token in body.tokens if str(token or "").strip()]
        if not imported_accounts and not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens is required"})
        if imported_accounts:
            result = account_service.add_account_items(imported_accounts, category=account_service.DONATION_CATEGORY)
            refresh_targets = [
                str(item.get("access_token") or "").strip()
                for item in imported_accounts
                if str(item.get("access_token") or "").strip()
            ]
        else:
            result = account_service.add_accounts(tokens, category=account_service.DONATION_CATEGORY)
            refresh_targets = tokens
        refresh_result = account_service.refresh_accounts(refresh_targets)
        added_tokens = {
            str(token or "").strip()
            for token in result.get("added_tokens", [])
            if str(token or "").strip()
        }
        failed_tokens = {
            str(item.get("access_token") or "").strip()
            for item in refresh_result.get("errors", [])
            if str(item.get("access_token") or "").strip()
        }
        rewarded_accounts = len(added_tokens - failed_tokens)
        rewarded_quota = rewarded_accounts * DONATION_REWARD_QUOTA
        remaining_quota = None
        if context.auth_type == "user_key" and rewarded_quota > 0:
            rewarded_user_key = user_key_service.grant_quota(extract_bearer_token(authorization), rewarded_quota)
            remaining_quota = max(0, int(rewarded_user_key.get("quota") or 0)) if rewarded_user_key else None
        return {
            **result,
            "refreshed": refresh_result.get("refreshed", 0),
            "errors": refresh_result.get("errors", []),
            "items": refresh_result.get("items", result.get("items", [])),
            "rewarded_accounts": rewarded_accounts,
            "rewarded_quota": rewarded_quota,
            "remaining_quota": remaining_quota,
        }

    @router.post("/api/user-keys")
    async def create_user_keys(
            body: UserKeyCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        return user_key_service.create_user_keys(
            count=body.count,
            quota=body.quota,
            prefix=body.prefix,
            label_prefix=body.label_prefix,
            status=body.status,
            pricing=body.pricing.to_pricing_dict() if body.pricing is not None else None,
        )

    @router.delete("/api/accounts")
    async def delete_accounts(
            body: AccountDeleteRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        tokens = [str(token or "").strip() for token in body.tokens if str(token or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens is required"})
        return account_service.delete_accounts(tokens)

    @router.delete("/api/user-keys")
    async def delete_user_keys(
            body: UserKeyDeleteRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        keys = [str(key or "").strip() for key in body.keys if str(key or "").strip()]
        if not keys:
            raise HTTPException(status_code=400, detail={"error": "keys is required"})
        return user_key_service.delete_user_keys(keys)

    @router.get("/api/quota")
    async def get_quota_summary(authorization: str | None = Header(default=None)):
        context = require_auth_key(authorization)
        if context.auth_type == "user_key":
            return build_quota_payload(context, max(0, int(context.remaining_quota or 0)))
        accounts = account_service.list_accounts()
        available_quota = sum(
            max(0, int(account.get("quota") or 0))
            for account in accounts
            if account.get("status") != "禁用"
        )
        return build_quota_payload(context, available_quota)

    @router.post("/api/accounts/refresh")
    async def refresh_accounts(
            body: AccountRefreshRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        access_tokens = [str(token or "").strip() for token in body.access_tokens if str(token or "").strip()]
        if not access_tokens:
            access_tokens = account_service.list_tokens()
        if not access_tokens:
            raise HTTPException(status_code=400, detail={"error": "access_tokens is required"})
        return account_service.refresh_accounts(access_tokens)

    @router.post("/api/accounts/update")
    async def update_account(
            body: AccountUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        access_token = str(body.access_token or "").strip()
        if not access_token:
            raise HTTPException(status_code=400, detail={"error": "access_token is required"})

        updates = {
            key: value
            for key, value in {
                "category": body.category,
                "type": body.type,
                "status": body.status,
                "quota": body.quota,
            }.items()
            if value is not None
        }
        if not updates:
            raise HTTPException(status_code=400, detail={"error": "no updates provided"})

        account = account_service.update_account(access_token, updates)
        if account is None:
            raise HTTPException(status_code=404, detail={"error": "account not found"})
        return {"item": account, "items": account_service.list_accounts()}

    @router.post("/api/user-keys/update")
    async def update_user_key(
            body: UserKeyUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        key = str(body.key or "").strip()
        if not key:
            raise HTTPException(status_code=400, detail={"error": "key is required"})

        updates = {
            update_key: value
            for update_key, value in {
                "label": body.label,
                "quota": body.quota,
                "status": body.status,
                "pricing": body.pricing.to_pricing_dict() if body.pricing is not None else None,
            }.items()
            if value is not None
        }
        if not updates:
            raise HTTPException(status_code=400, detail={"error": "no updates provided"})

        user_key = user_key_service.update_user_key(key, updates)
        if user_key is None:
            raise HTTPException(status_code=404, detail={"error": "user key not found"})
        return {"item": user_key, "items": user_key_service.list_public_user_keys()}

    @router.post("/v1/images/generations")
    async def generate_images(
            body: ImageGenerationRequest,
            authorization: str | None = Header(default=None),
    ):
        context = require_auth_key(authorization)
        requested_model = normalize_requested_image_model(body.model)
        await wait_for_image_request_turn(extract_bearer_token(authorization))
        result, billing_payload = await generate_image_payload(
            service=service,
            context=context,
            authorization=authorization,
            prompt=body.prompt,
            model=requested_model,
            n=body.n,
        )
        payload = build_images_response_payload(result, billing_payload)
        if body.stream:
            return StreamingResponse(
                iter_images_stream(
                    payload,
                    output_format=body.output_format or body.response_format,
                    background=body.background,
                    quality=body.quality,
                    size=body.size,
                    partial_images=body.partial_images,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        return payload

    app.include_router(router)

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_web(full_path: str):
        asset = resolve_web_asset(full_path)
        if asset is not None:
            return FileResponse(asset)

        fallback = resolve_web_asset("")
        if fallback is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(fallback)

    return app
