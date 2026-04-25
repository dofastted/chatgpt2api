from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import base64
import json
from pathlib import Path
from threading import Lock
from threading import Event, Thread
from time import time
from typing import Any
from uuid import uuid4
from fastapi import APIRouter, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from services.account_service import account_service
from services.config import config
from services.backend_service import BackendService
from services.chat_image.account_import import normalize_account_carrier
from services.image_service import ImageGenerationError
from services.image_size import normalize_image_size
from services.image_queue_service import image_queue_service
from services.proxy_service import proxy_service
from services.redeem_code_service import redeem_code_service
from services.uploaded_image_service import uploaded_image_service
from services.user_key_service import user_key_service
from services.version import get_app_version


BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIST_DIR = BASE_DIR / "web_dist"
WEB_OUT_DIR = BASE_DIR / "web" / "out"
FREE_DONATION_REWARD_LDC = 20
PURCHASE_QUOTA_PER_ORDER = 20
PURCHASE_LDC_COST_PER_ORDER = 20
DEFAULT_USER_KEY_PRICING = dict(user_key_service.DEFAULT_PRICING)
ALL_IMAGE_MODELS = tuple(user_key_service.SUPPORTED_MODELS)
ENABLED_IMAGE_MODELS = ("gpt-image-2",)
MAX_IMAGES_PER_REQUEST = 2
DEFAULT_IMAGE_MODEL = ENABLED_IMAGE_MODELS[0]
DEFAULT_RESPONSES_MODEL = "gpt-5"
MAX_INPUT_IMAGE_BYTES = 8 * 1024 * 1024
RESPONSES_STORE: dict[str, dict[str, object]] = {}
RESPONSES_STORE_LOCK = Lock()


class UserKeyPricingRequest(BaseModel):
    gpt_image_1: int = Field(default=0, ge=0, alias="gpt-image-1")
    gpt_image_2: int = Field(default=2, ge=0, alias="gpt-image-2")

    model_config = {"populate_by_name": True}

    def to_pricing_dict(self) -> dict[str, int]:
        return {
            "gpt-image-1": int(self.gpt_image_1),
            "gpt-image-2": int(self.gpt_image_2),
        }


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str = DEFAULT_IMAGE_MODEL
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
    metadata: dict[str, Any] | None = None

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


class ProxyUpsertRequest(BaseModel):
    id: str | None = None
    name: str | None = None
    protocol: str
    host: str
    port: int = Field(..., ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    enabled: bool = True


class ProxyDeleteRequest(BaseModel):
    id: str = Field(default="")


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
    ldc_balance: int | None = None
    status: str | None = None
    pricing: UserKeyPricingRequest | None = None


class QuotaPurchaseRequest(BaseModel):
    package_count: int = Field(default=1, ge=1, le=100)


class RedeemCodeCreateRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=500)
    target_quota: int = Field(default=0, ge=0, alias="targetQuota")
    prefix: str | None = None
    label: str | None = None

    model_config = {"populate_by_name": True}


class RedeemCodeDeleteRequest(BaseModel):
    codes: list[str] = Field(default_factory=list)


class RedeemCodeRedeemRequest(BaseModel):
    code: str = Field(default="")


@dataclass(frozen=True)
class AuthContext:
    role: str
    auth_type: str
    remaining_quota: int | None = None
    ldc_balance: int | None = None
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
        ldc_balance=max(0, int(user_key.get("ldc_balance") or 0)),
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
        "ldc_balance": context.ldc_balance,
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
        "ldc_balance": context.ldc_balance if context.auth_type == "user_key" else None,
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
    normalized_model = str(model or "").strip() or DEFAULT_IMAGE_MODEL
    if normalized_model not in ENABLED_IMAGE_MODELS:
        enabled = ", ".join(ENABLED_IMAGE_MODELS)
        raise HTTPException(
            status_code=400,
            detail={"error": f"unsupported image model: {normalized_model}. enabled models: {enabled}"},
        )
    return normalized_model


def clear_image_request_timestamps() -> None:
    image_queue_service.clear()


def resolve_queue_request_id(header_value: str | None) -> str:
    normalized_header = str(header_value or "").strip()
    return normalized_header or f"iq_{uuid4().hex}"


def build_queue_title(prompt: str) -> str:
    trimmed = str(prompt or "").strip()
    if len(trimmed) <= 40:
        return trimmed
    return f"{trimmed[:40]}..."


async def register_image_queue_request(auth_token: str, request_id: str, title: str) -> None:
    try:
        await run_in_threadpool(image_queue_service.create_ticket, auth_token, request_id, title)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail={"error": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc


async def wait_for_image_request_turn(request_id: str) -> None:
    await run_in_threadpool(image_queue_service.wait_for_turn, request_id)


def build_queue_background_task(request_id: str) -> BackgroundTask:
    return BackgroundTask(image_queue_service.finish_ticket, request_id)


def fail_queue_request(request_id: str, error: str | None = None) -> None:
    image_queue_service.finish_ticket(request_id, error=error)


async def generate_image_payload(
        *,
        service: BackendService,
        context: AuthContext,
        authorization: str | None,
        prompt: str,
        model: str,
        n: int,
        input_images: list[dict[str, str]] | None = None,
        queue_request_id: str | None = None,
        size: str | None = None,
) -> tuple[dict[str, object], dict[str, object] | None]:
    settled_user_key = ""
    request_cost = 0
    unit_cost = 0
    remaining_quota_after_charge = max(0, int(context.remaining_quota or 0))
    if context.auth_type == "user_key":
        settled_user_key = extract_bearer_token(authorization)
        pricing = resolve_user_key_pricing(context.pricing)
        unit_cost = max(0, int(pricing.get(model) or 0))
        request_cost = max(1, int(n or 1)) * unit_cost
        if remaining_quota_after_charge < request_cost:
            raise HTTPException(
                status_code=403,
                detail={"error": f"quota is insufficient for this request, required={request_cost}"},
            )
    try:
        result = await run_in_threadpool(
            service.generate_with_pool,
            prompt,
            model,
            n,
            input_images,
            queue_request_id,
            size,
        )
        billing_payload = None
        if settled_user_key:
            charged_item = user_key_service.consume_quota(settled_user_key, request_cost)
            if charged_item is not None:
                remaining_quota_after_charge = max(0, int(charged_item.get("quota") or 0))
            latest_item = user_key_service.mark_used(settled_user_key)
            used_item = latest_item or charged_item
            if used_item is not None:
                remaining_quota_after_charge = max(0, int(used_item.get("quota") or 0))
            billing_payload = build_billing_payload(
                requested_model=model,
                unit_cost=unit_cost,
                charged_quota=request_cost if charged_item is not None else 0,
                remaining_quota=remaining_quota_after_charge,
            )
            result = {
                **result,
                "billing": billing_payload,
            }
        return result, billing_payload
    except ImageGenerationError as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
    except HTTPException:
        raise
    except Exception:
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
    if requested_model in ENABLED_IMAGE_MODELS:
        return normalize_requested_image_model(requested_model)
    return DEFAULT_IMAGE_MODEL


def resolve_requested_response_image_size(body: ResponsesCreateRequest) -> str:
    image_tool = get_image_generation_tool(body.tools)
    raw_size = image_tool.size if image_tool is not None else None
    try:
        return normalize_image_size(raw_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


def resolve_requested_image_size(value: str | None) -> str:
    try:
        return normalize_image_size(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


def summarize_input_images(input_images: list[dict[str, str]] | None) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for item in input_images or []:
        file_id = str(item.get("file_id") or "").strip()
        image_url = str(item.get("image_url") or "").strip()
        if file_id:
            summaries.append({"type": "file_id", "file_id": file_id})
        elif image_url.startswith("data:"):
            summaries.append({"type": "data_url", "image_url": image_url[:64]})
        elif image_url:
            summaries.append({"type": "image_url", "image_url": image_url})
    return summaries


def build_previous_response_context(previous_response_id: str | None) -> tuple[dict[str, object] | None, str]:
    normalized_id = str(previous_response_id or "").strip()
    if not normalized_id:
        return None, "none"
    previous_payload = response_store_get(normalized_id)
    if previous_payload is None:
        raise HTTPException(status_code=404, detail={"error": "previous_response_id was not found"})
    history = previous_payload.get("_history")
    if not isinstance(history, list):
        return previous_payload, "text_history"
    lines: list[str] = []
    for item in history[-6:]:
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or "").strip()
        size = str(item.get("size") or "").strip() or "auto"
        copied_text = str(item.get("copied_text") or "").strip()
        if prompt:
            lines.append(f"- prompt: {prompt}; size: {size}")
        if copied_text:
            lines.append(f"  copied_text: {copied_text[:500]}")
    if not lines:
        return previous_payload, "text_history"
    return previous_payload, "text_history"


def merge_prompt_with_previous_context(prompt: str, previous_payload: dict[str, object] | None) -> str:
    if not previous_payload:
        return prompt
    history = previous_payload.get("_history")
    if not isinstance(history, list):
        return prompt
    lines: list[str] = []
    for item in history[-6:]:
        if not isinstance(item, dict):
            continue
        previous_prompt = str(item.get("prompt") or "").strip()
        previous_size = str(item.get("size") or "").strip() or "auto"
        if previous_prompt:
            lines.append(f"上一轮提示词: {previous_prompt} (size={previous_size})")
        previous_text = str(item.get("copied_text") or "").strip()
        if previous_text:
            lines.append(f"上一轮可复制文本: {previous_text[:500]}")
    if not lines:
        return prompt
    return "历史上下文:\n" + "\n".join(lines) + "\n\n当前请求:\n" + prompt


def build_response_history_entry(
        *,
        response_id: str,
        prompt: str,
        size: str,
        input_images: list[dict[str, str]] | None,
        image_result: dict[str, object],
) -> dict[str, object]:
    return {
        "response_id": response_id,
        "prompt": prompt,
        "size": size,
        "input_images": summarize_input_images(input_images),
        "output_count": len(list(image_result.get("data") or [])),
        "copied_text": str(image_result.get("copied_text") or "").strip() or None,
    }


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
            file_id = str(value.get("file_id") or "").strip()
            if file_id:
                return [{"type": "input_image", "file_id": file_id}]
            return [{"type": "input_image", "image_url": _normalize_response_input_image_url(value)}]
        if item_type in {"image", "image_generation_call"}:
            return []
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


def validate_uploaded_file_inputs(
        input_images: list[dict[str, str]],
        *,
        auth_token: str,
        client_conversation_id: str,
) -> list[dict[str, str]]:
    normalized_conversation_id = str(client_conversation_id or "").strip()
    validated: list[dict[str, str]] = []
    for item in input_images:
        file_id = str(item.get("file_id") or "").strip()
        if not file_id:
            validated.append(dict(item))
            continue
        if not normalized_conversation_id:
            raise HTTPException(
                status_code=400,
                detail={"error": "responses file_id input requires metadata.client_conversation_id"},
            )
        stored = uploaded_image_service.get_item(
            file_id,
            auth_token,
            normalized_conversation_id,
        )
        if stored is None:
            raise HTTPException(status_code=404, detail={"error": "input image file_id was not found"})
        consumed_by = str(stored.get("consumed_by_client_conversation_id") or "").strip()
        if consumed_by and consumed_by != normalized_conversation_id:
            raise HTTPException(status_code=409, detail={"error": "input image file_id was already consumed"})
        validated.append(dict(item))
    return validated


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
            return []
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
    copied_text = str(image_result.get("copied_text") or "").strip()
    if copied_text:
        payload["copied_text"] = copied_text
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
    copied_text = str(image_result.get("copied_text") or "").strip()
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
    if copied_text:
        payload["copied_text"] = copied_text
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
                "image_generation.partial_image",
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
        yield format_sse_event("image_generation.completed", completed_event)
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


def require_user_key_auth_context(authorization: str | None) -> AuthContext:
    context = require_auth_key(authorization)
    if context.auth_type != "user_key":
        raise HTTPException(status_code=403, detail={"error": "user key authorization is required"})
    return context


def normalize_account_request_items(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not accounts:
        return []
    try:
        return normalize_account_carrier({"accounts": accounts})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


def start_limited_account_watcher(stop_event: Event) -> Thread:
    def worker() -> None:
        while not stop_event.is_set():
            try:
                if hasattr(account_service, "list_refreshable_tokens"):
                    refreshable_tokens = account_service.list_refreshable_tokens()
                else:
                    refreshable_tokens = account_service.list_limited_tokens()
                if refreshable_tokens:
                    print(f"[account-limited-watcher] checking {len(refreshable_tokens)} recoverable accounts")
                    account_service.refresh_accounts(refreshable_tokens)
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

    @router.get("/api/image-queue/me")
    async def get_my_image_queue(
            authorization: str | None = Header(default=None),
            request_id: str | None = Query(default=None),
    ):
        require_auth_key(authorization)
        auth_token = extract_bearer_token(authorization)
        return image_queue_service.snapshot(auth_token, request_id=request_id)

    @router.api_route("/v1/responses", methods=["GET", "HEAD"])
    async def check_responses_endpoint(authorization: str | None = Header(default=None)):
        require_auth_key(authorization)
        auth_token = extract_bearer_token(authorization)
        queue_snapshot = image_queue_service.snapshot(auth_token)
        return {
            "object": "list",
            "data": [],
            "status": "ok",
            "endpoint": "/v1/responses",
            "queue": {
                "user": queue_snapshot.get("user", {}),
                "global": queue_snapshot.get("global", {}),
            },
        }

    @router.post("/v1/responses")
    async def create_response(
            body: ResponsesCreateRequest,
            authorization: str | None = Header(default=None),
            image_queue_request_id: str | None = Header(default=None, alias="X-Image-Queue-Request-Id"),
    ):
        context = require_auth_key(authorization)
        if not has_image_generation_tool(body.tools):
            raise HTTPException(
                status_code=400,
                detail={"error": "responses request must include an image_generation tool"},
            )
        validate_responses_tool_choice(body.tool_choice)
        input_images = validate_responses_input_images(body.input)
        request_auth_token = extract_bearer_token(authorization)
        metadata = body.metadata if isinstance(body.metadata, dict) else {}
        client_conversation_id = str(metadata.get("client_conversation_id") or "").strip()
        input_images = validate_uploaded_file_inputs(
            input_images,
            auth_token=request_auth_token,
            client_conversation_id=client_conversation_id,
        )
        input_images = [
            {
                **item,
                **({"owner_auth_token": request_auth_token} if str(item.get("file_id") or "").strip() else {}),
                **({"client_conversation_id": client_conversation_id} if str(item.get("file_id") or "").strip() else {}),
            }
            for item in input_images
        ]
        prompt = extract_responses_prompt(body.input)
        requested_size = resolve_requested_response_image_size(body)
        previous_payload, context_mode = build_previous_response_context(body.previous_response_id)
        generation_prompt = merge_prompt_with_previous_context(prompt, previous_payload)
        queue_request_id = resolve_queue_request_id(image_queue_request_id)
        await register_image_queue_request(request_auth_token, queue_request_id, build_queue_title(prompt))
        try:
            await wait_for_image_request_turn(queue_request_id)
        except Exception as exc:
            fail_queue_request(queue_request_id, str(exc))
            raise

        response_model = str(body.model or "").strip() or DEFAULT_RESPONSES_MODEL
        if response_model in ALL_IMAGE_MODELS:
            response_model = DEFAULT_RESPONSES_MODEL
        requested_model = resolve_requested_response_image_model(body)
        try:
            image_result, billing_payload = await generate_image_payload(
                service=service,
                context=context,
                authorization=authorization,
                prompt=generation_prompt,
                model=requested_model,
                n=body.n,
                input_images=input_images,
                queue_request_id=queue_request_id,
                size=requested_size,
            )
        except Exception as exc:
            fail_queue_request(queue_request_id, str(exc))
            raise
        response_id = f"resp_{uuid4().hex}"
        payload = build_responses_payload(
            response_id=response_id,
            response_model=response_model,
            image_result=image_result,
            billing=billing_payload,
            metadata={
                **(body.metadata or {}),
                "size": requested_size,
                "context_mode": context_mode,
            },
            previous_response_id=body.previous_response_id,
        )
        previous_history = []
        if isinstance(previous_payload, dict) and isinstance(previous_payload.get("_history"), list):
            previous_history = list(previous_payload.get("_history") or [])
        stored_payload = {
            **payload,
            "_history": [
                *previous_history,
                build_response_history_entry(
                    response_id=response_id,
                    prompt=prompt,
                    size=requested_size,
                    input_images=input_images,
                    image_result=image_result,
                ),
            ],
        }
        response_store_set(response_id, stored_payload)
        if body.stream:
            return StreamingResponse(
                iter_responses_stream(payload),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
                background=build_queue_background_task(queue_request_id),
            )
        return JSONResponse(payload, background=build_queue_background_task(queue_request_id))

    @router.post("/backend-api/files/process_upload_stream")
    async def process_upload_stream(
            file: UploadFile = File(...),
            client_conversation_id: str = Form(...),
            authorization: str | None = Header(default=None),
    ):
        require_auth_key(authorization)
        auth_token = extract_bearer_token(authorization)
        image_bytes = await file.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail={"error": "image file is required"})
        if len(image_bytes) > MAX_INPUT_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail={"error": "image file must be <= 8 MB"})
        try:
            item = uploaded_image_service.save_upload(
                auth_token=auth_token,
                client_conversation_id=client_conversation_id,
                file_name=str(file.filename or "").strip() or "upload.png",
                content_type=file.content_type,
                image_bytes=image_bytes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return item

    @router.get("/backend-api/my/recent/uploaded_images")
    async def list_uploaded_images(
            authorization: str | None = Header(default=None),
            limit: int = Query(default=25, ge=1, le=100),
            images_app_only: bool = Query(default=False),
            client_conversation_id: str | None = Query(default=None),
    ):
        require_auth_key(authorization)
        auth_token = extract_bearer_token(authorization)
        return {
            "items": uploaded_image_service.list_items(
                auth_token,
                limit=limit,
                images_app_only=images_app_only,
                client_conversation_id=client_conversation_id,
            )
        }

    @router.get("/backend-api/files/{file_id}/content")
    async def get_uploaded_image_content(file_id: str, authorization: str | None = Header(default=None)):
        require_auth_key(authorization)
        auth_token = extract_bearer_token(authorization)
        stored = uploaded_image_service.read_bytes(file_id, auth_token)
        if stored is None:
            raise HTTPException(status_code=404, detail={"error": "uploaded image not found"})
        _, item = stored
        file_path = uploaded_image_service.files_dir / str(item.get("stored_name") or "")
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail={"error": "uploaded image not found"})
        return FileResponse(
            file_path,
            media_type=str(item.get("mime_type") or "image/png"),
            filename=str(item.get("file_name") or file_path.name),
        )

    @router.get("/v1/responses/{response_id}")
    async def get_response(response_id: str, authorization: str | None = Header(default=None)):
        require_auth_key(authorization)
        payload = response_store_get(str(response_id or "").strip())
        if payload is None:
            raise HTTPException(status_code=404, detail={"error": "response not found"})
        return {key: value for key, value in payload.items() if not str(key).startswith("_")}

    @router.get("/version")
    async def get_version():
        return {"version": app_version}

    @router.get("/api/accounts")
    async def get_accounts(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return {"items": account_service.list_accounts()}

    @router.get("/api/proxies")
    async def get_proxies(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return {
            "items": proxy_service.list_public_items(),
            "active_proxy_url": proxy_service.get_enabled_proxy_url(),
        }

    @router.get("/api/user-keys")
    async def get_user_keys(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return {"items": user_key_service.list_public_user_keys()}

    @router.get("/api/redeem-codes")
    async def get_redeem_codes(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return {"items": redeem_code_service.list_public_codes()}

    @router.post("/api/accounts")
    async def create_accounts(
            body: AccountCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        imported_accounts = normalize_account_request_items([dict(item) for item in body.accounts if isinstance(item, dict)])
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

    @router.post("/api/proxies")
    async def upsert_proxy(
            body: ProxyUpsertRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        try:
            item = proxy_service.upsert_proxy(body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {
            "item": item,
            "items": proxy_service.list_public_items(),
            "active_proxy_url": proxy_service.get_enabled_proxy_url(),
        }

    @router.post("/api/donations/accounts")
    async def create_donation_accounts(
            body: AccountCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        context = require_auth_key(authorization)
        imported_accounts = normalize_account_request_items([dict(item) for item in body.accounts if isinstance(item, dict)])
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
        rewarded_accounts = len(
            {
                str(item.get("access_token") or "").strip()
                for item in refresh_result.get("items", [])
                if str(item.get("access_token") or "").strip() in added_tokens
                and str(item.get("access_token") or "").strip() not in failed_tokens
                and str(item.get("type") or "").strip() == "Free"
            }
        )
        rewarded_ldc = rewarded_accounts * FREE_DONATION_REWARD_LDC
        remaining_quota = context.remaining_quota
        ldc_balance = context.ldc_balance
        if context.auth_type == "user_key" and rewarded_ldc > 0:
            rewarded_user_key = user_key_service.grant_ldc(extract_bearer_token(authorization), rewarded_ldc)
            if rewarded_user_key is not None:
                remaining_quota = max(0, int(rewarded_user_key.get("quota") or 0))
                ldc_balance = max(0, int(rewarded_user_key.get("ldc_balance") or 0))
        return {
            **result,
            "refreshed": refresh_result.get("refreshed", 0),
            "errors": refresh_result.get("errors", []),
            "items": refresh_result.get("items", result.get("items", [])),
            "rewarded_accounts": rewarded_accounts,
            "rewarded_ldc": rewarded_ldc,
            "remaining_quota": remaining_quota,
            "ldc_balance": ldc_balance,
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

    @router.post("/api/redeem-codes")
    async def create_redeem_codes(
            body: RedeemCodeCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        if body.target_quota not in {20, 100}:
            raise HTTPException(status_code=400, detail={"error": "redeem code quota must be 20 or 100"})
        return redeem_code_service.create_codes(
            count=body.count,
            target_quota=body.target_quota,
            prefix=body.prefix,
            label=body.label,
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

    @router.delete("/api/proxies")
    async def delete_proxy(
            body: ProxyDeleteRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        proxy_id = str(body.id or "").strip()
        if not proxy_id:
            raise HTTPException(status_code=400, detail={"error": "id is required"})
        result = proxy_service.delete_proxy(proxy_id)
        return {
            **result,
            "active_proxy_url": proxy_service.get_enabled_proxy_url(),
        }

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

    @router.delete("/api/redeem-codes")
    async def delete_redeem_codes(
            body: RedeemCodeDeleteRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        codes = [str(code or "").strip() for code in body.codes if str(code or "").strip()]
        if not codes:
            raise HTTPException(status_code=400, detail={"error": "codes is required"})
        return redeem_code_service.delete_codes(codes)

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

    @router.post("/api/quota/purchase")
    async def purchase_quota(
            body: QuotaPurchaseRequest,
            authorization: str | None = Header(default=None),
    ):
        context = require_user_key_auth_context(authorization)
        auth_token = extract_bearer_token(authorization)
        package_count = max(1, int(body.package_count or 1))
        spent_ldc = package_count * PURCHASE_LDC_COST_PER_ORDER
        purchased_quota = package_count * PURCHASE_QUOTA_PER_ORDER
        spent_item = user_key_service.spend_ldc(auth_token, spent_ldc)
        if spent_item is None:
            raise HTTPException(
                status_code=403,
                detail={"error": f"ldc balance is insufficient for this purchase, required={spent_ldc}"},
            )
        updated_item = user_key_service.grant_quota(auth_token, purchased_quota)
        remaining_quota = max(0, int(updated_item.get("quota") or 0)) if updated_item else max(0, int(context.remaining_quota or 0))
        ldc_balance = max(0, int(updated_item.get("ldc_balance") or 0)) if updated_item else max(0, int(spent_item.get("ldc_balance") or 0))
        return {
            "purchased_quota": purchased_quota,
            "spent_ldc": spent_ldc,
            "remaining_quota": remaining_quota,
            "ldc_balance": ldc_balance,
        }

    @router.post("/api/redeem-codes/redeem")
    async def redeem_code(
            body: RedeemCodeRedeemRequest,
            authorization: str | None = Header(default=None),
    ):
        context = require_user_key_auth_context(authorization)
        auth_token = extract_bearer_token(authorization)
        code = str(body.code or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail={"error": "code is required"})
        redeemed_item = redeem_code_service.redeem_code(code, auth_token)
        if redeemed_item is None:
            raise HTTPException(status_code=404, detail={"error": "redeem code not found or already used"})
        added_quota = max(0, int(redeemed_item.get("target_quota") or 0))
        updated_user_key = user_key_service.grant_quota(auth_token, added_quota)
        if updated_user_key is None:
            raise HTTPException(status_code=404, detail={"error": "user key not found"})
        return {
            "item": redeemed_item,
            "added_quota": added_quota,
            "remaining_quota": max(0, int(updated_user_key.get("quota") or 0)),
            "ldc_balance": max(0, int(updated_user_key.get("ldc_balance") or 0)),
            "previous_quota": max(0, int(context.remaining_quota or 0)),
        }

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
                "ldc_balance": body.ldc_balance,
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
            image_queue_request_id: str | None = Header(default=None, alias="X-Image-Queue-Request-Id"),
    ):
        context = require_auth_key(authorization)
        requested_model = normalize_requested_image_model(body.model)
        requested_size = resolve_requested_image_size(body.size)
        request_auth_token = extract_bearer_token(authorization)
        queue_request_id = resolve_queue_request_id(image_queue_request_id)
        await register_image_queue_request(request_auth_token, queue_request_id, build_queue_title(body.prompt))
        try:
            await wait_for_image_request_turn(queue_request_id)
        except Exception as exc:
            fail_queue_request(queue_request_id, str(exc))
            raise
        try:
            result, billing_payload = await generate_image_payload(
                service=service,
                context=context,
                authorization=authorization,
                prompt=body.prompt,
                model=requested_model,
                n=body.n,
                queue_request_id=queue_request_id,
                size=requested_size,
            )
        except Exception as exc:
            fail_queue_request(queue_request_id, str(exc))
            raise
        payload = build_images_response_payload(result, billing_payload)
        if body.stream:
            return StreamingResponse(
                iter_images_stream(
                    payload,
                    output_format=body.output_format or body.response_format,
                    background=body.background,
                    quality=body.quality,
                    size=requested_size,
                    partial_images=body.partial_images,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
                background=build_queue_background_task(queue_request_id),
            )
        return JSONResponse(payload, background=build_queue_background_task(queue_request_id))

    @router.post("/v1/images/edits")
    async def edit_images(
            prompt: str = Form(...),
            image: UploadFile = File(...),
            model: str = Form(default=DEFAULT_IMAGE_MODEL),
            n: int = Form(default=1),
            response_format: str = Form(default="b64_json"),
            size: str | None = Form(default=None),
            stream: bool = Form(default=False),
            authorization: str | None = Header(default=None),
            image_queue_request_id: str | None = Header(default=None, alias="X-Image-Queue-Request-Id"),
    ):
        context = require_auth_key(authorization)
        requested_model = normalize_requested_image_model(model)
        requested_size = resolve_requested_image_size(size)
        normalized_n = max(1, min(MAX_IMAGES_PER_REQUEST, int(n or 1)))
        image_bytes = await image.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail={"error": "image file is required"})
        if len(image_bytes) > MAX_INPUT_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail={"error": "image file must be <= 8 MB"})
        content_type = str(image.content_type or "image/png").split(";", 1)[0].strip().lower() or "image/png"
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail={"error": "image file must use an image mime type"})
        input_images = [
            {
                "type": "input_image",
                "image_url": f"data:{content_type};base64,{base64.b64encode(image_bytes).decode('ascii')}",
            }
        ]
        request_auth_token = extract_bearer_token(authorization)
        queue_request_id = resolve_queue_request_id(image_queue_request_id)
        await register_image_queue_request(request_auth_token, queue_request_id, build_queue_title(prompt))
        try:
            await wait_for_image_request_turn(queue_request_id)
        except Exception as exc:
            fail_queue_request(queue_request_id, str(exc))
            raise
        try:
            result, billing_payload = await generate_image_payload(
                service=service,
                context=context,
                authorization=authorization,
                prompt=prompt,
                model=requested_model,
                n=normalized_n,
                input_images=input_images,
                queue_request_id=queue_request_id,
                size=requested_size,
            )
        except Exception as exc:
            fail_queue_request(queue_request_id, str(exc))
            raise
        payload = build_images_response_payload(result, billing_payload)
        if stream:
            return StreamingResponse(
                iter_images_stream(
                    payload,
                    output_format=response_format,
                    background=None,
                    quality=None,
                    size=requested_size,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
                background=build_queue_background_task(queue_request_id),
            )
        return JSONResponse(payload, background=build_queue_background_task(queue_request_id))

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
