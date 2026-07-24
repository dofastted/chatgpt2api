from __future__ import annotations

import asyncio
import base64
import binascii
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
from pathlib import Path
from threading import Lock
from threading import Event
from time import time
from typing import Any
from uuid import uuid4
from fastapi import APIRouter, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from services.account_service import account_service
from services.config import DATA_DIR, config
from services.data_management_service import data_management_service, start_backup_scheduler
from services.backend_service import BackendService
from services.chat_image.account_import import normalize_account_carrier
from services.gallery_service import gallery_service
from services.image_service import ImageGenerationError
from services.image_size import normalize_image_size
from services.image_queue_service import image_queue_service
from services.image_request_log_service import image_request_log_service, token_owner_id
from services.proxy_service import proxy_service
from services.redeem_code_service import redeem_code_service
from services.sqlite_store import sqlite_store
from services.uploaded_image_service import (
    MIN_INPUT_IMAGE_SIDE,
    detect_image_dimensions,
    normalize_uploaded_image_mime_type,
    uploaded_image_service,
)
from services.user_key_service import user_key_service
from services.version import get_app_version


BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIST_DIR = BASE_DIR / "web_dist"
WEB_OUT_DIR = BASE_DIR / "web" / "out"
GENERATED_IMAGE_DIR = DATA_DIR / "generated_images"
FREE_DONATION_REWARD_LDC = 20
PURCHASE_QUOTA_PER_ORDER = 20
PURCHASE_LDC_COST_PER_ORDER = 20
DEFAULT_USER_KEY_PRICING = dict(user_key_service.DEFAULT_PRICING)
ENABLED_IMAGE_MODELS = ("gpt-image-2", "gpt-image-2-2K", "gpt-image-2-4K")
MAX_IMAGES_PER_REQUEST = 10
IMAGE_BATCH_CONCURRENCY = 3
DEFAULT_IMAGE_MODEL = ENABLED_IMAGE_MODELS[0]
DEFAULT_RESPONSES_MODEL = "gpt-5"
MAX_INPUT_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_GENERATION_TIMEOUT_SECONDS = max(60, int(config.image_generation_timeout_seconds or 900))
RESPONSES_STORE: dict[str, dict[str, object]] = {}
RESPONSES_STORE_LOCK = Lock()


class UserKeyPricingRequest(BaseModel):
    gpt_image_2: int = Field(default=2, ge=0, alias="gpt-image-2")
    gpt_image_2_2k: int = Field(default=2, ge=0, alias="gpt-image-2-2K")
    gpt_image_2_4k: int = Field(default=8, ge=0, alias="gpt-image-2-4K")

    model_config = {"populate_by_name": True}

    def to_pricing_dict(self) -> dict[str, int]:
        return {
            "gpt-image-2": int(self.gpt_image_2),
            "gpt-image-2-2K": int(self.gpt_image_2_2k),
            "gpt-image-2-4K": int(self.gpt_image_2_4k),
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
    payload: Any | None = None
    account_json: Any | None = Field(default=None, alias="accountJson")
    category: str | None = None

    model_config = {"populate_by_name": True}


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


class DataManagementSettingsRequest(BaseModel):
    backup_enabled: bool | None = None
    backup_interval_minutes: int | None = Field(default=None, ge=0)
    backup_max_bytes: int | None = Field(default=None, ge=1)
    save_image_conversations: bool | None = None
    save_logs: bool | None = None
    s3: dict[str, Any] | None = None


class GalleryAssetRequest(BaseModel):
    asset_id: str | None = None
    id: str | None = None
    kind: str | None = None
    url: str
    file_id: str | None = None
    fileId: str | None = None
    mime_type: str | None = None
    mimeType: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    size_bytes: int | None = Field(default=None, ge=1)
    sizeBytes: int | None = Field(default=None, ge=1)


class GallerySubmissionRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    title: str | None = None
    tags: list[str] | str | None = None
    assets: list[GalleryAssetRequest] = Field(default_factory=list)
    image_url: str | None = None
    mime_type: str | None = None
    source_conversation_id: str | None = None
    source_turn_id: str | None = None
    source_image_id: str | None = None


class GalleryEventRequest(BaseModel):
    event: str = Field(..., min_length=1)


class AdminGalleryUpdateRequest(BaseModel):
    action: str | None = None
    status: str | None = None
    visibility: bool | None = None
    prompt: str | None = None
    title: str | None = None
    tags: list[str] | str | None = None
    assets: list[GalleryAssetRequest] | None = None
    image_url: str | None = None
    mime_type: str | None = None
    sort_order: int | None = None
    is_pinned: bool | None = None


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

    user_key = user_key_service.get_user_key(auth_key)
    if user_key is not None and user_key.get("status") == user_key_service.ENABLED_STATUS:
        return AuthContext(
            role="user",
            auth_type="user_key",
            remaining_quota=max(0, int(user_key.get("quota") or 0)),
            ldc_balance=max(0, int(user_key.get("ldc_balance") or 0)),
            user_key_id=str(user_key.get("id") or "") or None,
            user_key_label=str(user_key.get("label") or "") or None,
            pricing=user_key_service.normalize_pricing(user_key.get("pricing")),
        )
    if auth_key == str(config.auth_key or "").strip():
        return AuthContext(role="user", auth_type="auth_key")
    return None


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
        requested_count: int | None = None,
        succeeded_count: int | None = None,
        failed_count: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "requested_model": requested_model,
        "unit_cost": unit_cost,
        "charged_quota": charged_quota,
        "remaining_quota": remaining_quota,
    }
    if requested_count is not None:
        payload["requested_count"] = max(0, int(requested_count))
    if succeeded_count is not None:
        payload["succeeded_count"] = max(0, int(succeeded_count))
    if failed_count is not None:
        payload["failed_count"] = max(0, int(failed_count))
    return payload


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


def build_request_owner_id(auth_token: str) -> str:
    return token_owner_id(auth_token)


def http_status_from_exception(exc: Exception) -> int | None:
    if isinstance(exc, HTTPException):
        return int(exc.status_code)
    return None


def create_image_request_record(
        *,
        request_id: str,
        context: AuthContext,
        auth_token: str,
        endpoint: str,
        protocol: str,
        model: str,
        size: str | None,
        n: int,
        stream: bool,
        prompt: str,
        has_input_image: bool = False,
        input_image_count: int = 0,
        client_conversation_id: str | None = None,
        response_id: str | None = None,
        metadata: dict[str, Any] | None = None,
) -> None:
    image_request_log_service.create_record(
        request_id=request_id,
        owner_id=build_request_owner_id(auth_token),
        auth_type=context.auth_type,
        auth_token=auth_token,
        user_key_id=context.user_key_id,
        user_key_label=context.user_key_label,
        endpoint=endpoint,
        protocol=protocol,
        model=model,
        size=size,
        n=n,
        stream=stream,
        prompt=prompt,
        has_input_image=has_input_image,
        input_image_count=input_image_count,
        client_conversation_id=client_conversation_id,
        response_id=response_id,
        requested_count=n,
        metadata=metadata,
    )


async def register_image_queue_request(auth_token: str, request_id: str, title: str) -> None:
    reconcile_stale_image_queue_tickets()
    try:
        await run_in_threadpool(image_queue_service.create_ticket, auth_token, request_id, title)
        image_request_log_service.mark_waiting(request_id)
    except ValueError as exc:
        image_request_log_service.mark_rejected(request_id, reason=str(exc), http_status=429)
        raise HTTPException(status_code=429, detail={"error": str(exc)}) from exc
    except RuntimeError as exc:
        image_request_log_service.mark_rejected(request_id, reason=str(exc), http_status=503)
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc


async def wait_for_image_request_turn(request_id: str) -> None:
    await run_in_threadpool(image_queue_service.wait_for_turn, request_id)
    image_request_log_service.mark_assigning(request_id)


def build_queue_background_task(request_id: str) -> BackgroundTask:
    return BackgroundTask(image_queue_service.finish_ticket, request_id)


def fail_queue_request(request_id: str, error: str | None = None) -> None:
    image_queue_service.finish_ticket(request_id, error=error)


def reconcile_stale_image_queue_tickets() -> list[str]:
    stale_ids = image_queue_service.finish_stale_tickets(
        max_age_seconds=IMAGE_GENERATION_TIMEOUT_SECONDS,
        error=f"image generation timed out after {IMAGE_GENERATION_TIMEOUT_SECONDS}s",
    )
    for request_id in stale_ids:
        record = image_request_log_service.get_record(request_id)
        if not record or str(record.get("status") or "") in {"finished", "failed", "rejected"}:
            continue
        image_request_log_service.mark_failed(
            request_id,
            error=build_image_generation_timeout_error(),
            http_status=504,
        )
    return stale_ids


def reconcile_stale_image_request_records() -> int:
    return image_request_log_service.mark_stale_active_failed(
        max_age_seconds=IMAGE_GENERATION_TIMEOUT_SECONDS,
        reason=generation_error_to_text(build_image_generation_timeout_error()),
    )


def enrich_queue_request_payload_from_record(
        request_payload: dict[str, object],
        record: dict[str, object] | None,
) -> dict[str, object]:
    if not record:
        return request_payload
    next_payload = dict(request_payload)
    for key in (
            "response_id",
            "requested_count",
            "succeeded_count",
            "failed_count",
            "charged_quota",
            "remaining_quota",
            "http_status",
            "queue_wait_ms",
            "running_ms",
            "total_ms",
    ):
        if record.get(key) is not None:
            next_payload[key] = record.get(key)
    return next_payload


def extract_image_result_items(result: dict[str, object], *, request_index: int | None = None) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for item in list(result.get("data") or []):
        if not isinstance(item, dict):
            continue
        b64_json = str(item.get("b64_json") or "").strip()
        if not b64_json:
            continue
        next_item = dict(item)
        next_item["b64_json"] = b64_json
        if request_index is not None:
            next_item["index"] = int(request_index)
        items.append(next_item)
    return items


def extract_generated_text(result: dict[str, object] | None) -> str:
    payload = result or {}
    for key in ("text_content", "copied_text", "output_text"):
        text = str(payload.get(key) or "").strip()
        if text:
            return text
    output_texts: list[str] = []
    for item in list(payload.get("output") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip() == "message":
            for content in list(item.get("content") or []):
                if isinstance(content, dict) and str(content.get("type") or "").strip() == "output_text":
                    text = str(content.get("text") or "").strip()
                    if text:
                        output_texts.append(text)
    return "\n".join(output_texts).strip()


def generation_error_to_text(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            return str(detail.get("error") or detail.get("message") or detail).strip()
        return str(detail).strip()
    return str(exc).strip() or exc.__class__.__name__


def build_image_generation_timeout_error() -> HTTPException:
    return HTTPException(
        status_code=504,
        detail={"error": f"image generation timed out after {IMAGE_GENERATION_TIMEOUT_SECONDS}s"},
    )


def build_image_generation_cancelled_error() -> HTTPException:
    return HTTPException(
        status_code=499,
        detail={"error": "image generation stream was cancelled before completion"},
    )


async def await_image_generation_payload(awaitable):
    try:
        return await asyncio.wait_for(awaitable, timeout=IMAGE_GENERATION_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise build_image_generation_timeout_error() from exc


@dataclass
class ImageBatchSlotResult:
    index: int
    result: dict[str, object] | None = None
    error: Exception | None = None


async def generate_single_image_slot(
        *,
        service: BackendService,
        prompt: str,
        model: str,
        request_index: int,
        input_images: list[dict[str, str]] | None,
        queue_request_id: str | None,
        size: str | None,
) -> ImageBatchSlotResult:
    try:
        current_result = await run_in_threadpool(
            service.generate_with_pool,
            prompt,
            model,
            1,
            input_images,
            queue_request_id,
            size,
        )
        return ImageBatchSlotResult(index=request_index, result=current_result)
    except (ImageGenerationError, HTTPException) as exc:
        return ImageBatchSlotResult(index=request_index, error=exc)


async def generate_image_slots_with_limit(
        *,
        service: BackendService,
        prompt: str,
        model: str,
        requested_count: int,
        input_images: list[dict[str, str]] | None,
        queue_request_id: str | None,
        size: str | None,
) -> list[ImageBatchSlotResult]:
    semaphore = asyncio.Semaphore(max(1, min(IMAGE_BATCH_CONCURRENCY, requested_count)))

    async def run_slot(request_index: int) -> ImageBatchSlotResult:
        async with semaphore:
            return await generate_single_image_slot(
                service=service,
                prompt=prompt,
                model=model,
                request_index=request_index,
                input_images=input_images,
                queue_request_id=queue_request_id,
                size=size,
            )

    return await asyncio.gather(*(run_slot(request_index) for request_index in range(requested_count)))


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
    requested_count = max(1, int(n or 1))
    unit_cost = 0
    remaining_quota_after_charge = max(0, int(context.remaining_quota or 0))
    if context.auth_type == "user_key":
        settled_user_key = extract_bearer_token(authorization)
        pricing = resolve_user_key_pricing(context.pricing)
        unit_cost = max(0, int(pricing.get(model) or 0))
        request_cost = requested_count * unit_cost
        if remaining_quota_after_charge < request_cost:
            raise HTTPException(
                status_code=403,
                detail={"error": f"quota is insufficient for this request, required={request_cost}"},
            )
    try:
        result: dict[str, object]
        partial_errors: list[dict[str, object]] = []
        if requested_count == 1:
            result = await run_in_threadpool(
                service.generate_with_pool,
                prompt,
                model,
                1,
                input_images,
                queue_request_id,
                size,
            )
            success_items = extract_image_result_items(result, request_index=0)[:1]
            generated_text = extract_generated_text(result)
            if not success_items and not generated_text:
                raise ImageGenerationError("image generation returned no image data")
            result = {
                **result,
                "data": success_items,
            }
            if generated_text:
                result["text_content"] = generated_text
                result["copied_text"] = str(result.get("copied_text") or generated_text).strip()
        else:
            created = int(time())
            success_items: list[dict[str, object]] = []
            copied_text = ""
            text_content = ""
            first_error: Exception | None = None
            slot_results = await generate_image_slots_with_limit(
                service=service,
                prompt=prompt,
                model=model,
                requested_count=requested_count,
                input_images=input_images,
                queue_request_id=queue_request_id,
                size=size,
            )
            for slot_result in sorted(slot_results, key=lambda item: item.index):
                request_index = slot_result.index
                if slot_result.error is not None:
                    if first_error is None:
                        first_error = slot_result.error
                    partial_errors.append(
                        {
                            "index": request_index,
                            "error": generation_error_to_text(slot_result.error),
                        }
                    )
                    continue
                current_result = slot_result.result or {}
                try:
                    current_items = extract_image_result_items(current_result, request_index=request_index)[:1]
                    current_text = extract_generated_text(current_result)
                    if not current_items and not current_text:
                        raise ImageGenerationError("image generation returned no image data")
                    success_items.extend(current_items)
                    if not copied_text:
                        copied_text = str(current_result.get("copied_text") or "").strip()
                    if not text_content and current_text:
                        text_content = current_text
                    if current_text and not current_items:
                        partial_errors.append(
                            {
                                "index": request_index,
                                "error": "image generation returned text instead of image",
                            }
                        )
                    created = int(current_result.get("created") or created)
                except ImageGenerationError as exc:
                    if first_error is None:
                        first_error = exc
                    partial_errors.append(
                        {
                            "index": request_index,
                            "error": generation_error_to_text(exc),
                        }
                    )
                    continue
            if not success_items and not text_content:
                if isinstance(first_error, HTTPException):
                    raise first_error
                if isinstance(first_error, ImageGenerationError):
                    raise first_error
                raise ImageGenerationError("image generation failed")
            result = {
                "created": created,
                "data": success_items,
            }
            if copied_text:
                result["copied_text"] = copied_text
            if text_content:
                result["text_content"] = text_content
                if not copied_text:
                    result["copied_text"] = text_content
            if partial_errors:
                result["partial_errors"] = partial_errors
        succeeded_count = len(success_items)
        failed_count = max(0, requested_count - succeeded_count)
        charged_quota = succeeded_count * unit_cost
        billing_payload = None
        if settled_user_key:
            charged_item = user_key_service.consume_quota(settled_user_key, charged_quota)
            if charged_item is not None:
                remaining_quota_after_charge = max(0, int(charged_item.get("quota") or 0))
            latest_item = user_key_service.mark_used(settled_user_key)
            used_item = latest_item or charged_item
            if used_item is not None:
                remaining_quota_after_charge = max(0, int(used_item.get("quota") or 0))
            billing_payload = build_billing_payload(
                requested_model=model,
                unit_cost=unit_cost,
                charged_quota=charged_quota if charged_item is not None else 0,
                remaining_quota=remaining_quota_after_charge,
                requested_count=requested_count,
                succeeded_count=succeeded_count,
                failed_count=failed_count,
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
    sqlite_store.set_response(response_id, dict(payload))


def response_store_get(response_id: str) -> dict[str, object] | None:
    with RESPONSES_STORE_LOCK:
        memory_payload = RESPONSES_STORE.get(response_id)
    if memory_payload is not None:
        return dict(memory_payload)
    payload = sqlite_store.get_response(response_id)
    return dict(payload) if payload is not None else None


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


def image_mime_type_to_extension(mime_type: str | None) -> str:
    normalized = str(mime_type or "").split(";", 1)[0].strip().lower()
    if normalized == "image/jpeg":
        return ".jpg"
    if normalized == "image/webp":
        return ".webp"
    if normalized == "image/gif":
        return ".gif"
    if normalized == "image/bmp":
        return ".bmp"
    if normalized == "image/avif":
        return ".avif"
    return ".png"


def save_generated_image_url(image_b64: str, mime_type: str | None, base_url: str | None) -> str:
    normalized_base_url = str(base_url or "").strip().rstrip("/")
    if not normalized_base_url:
        return f"data:{str(mime_type or 'image/png').strip() or 'image/png'};base64,{image_b64}"
    GENERATED_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    extension = image_mime_type_to_extension(mime_type)
    image_id = f"img_{uuid4().hex}{extension}"
    try:
        image_bytes = base64.b64decode(image_b64, validate=False)
    except binascii.Error as exc:
        raise HTTPException(status_code=502, detail={"error": "generated image base64 is invalid"}) from exc
    (GENERATED_IMAGE_DIR / image_id).write_bytes(image_bytes)
    return f"{normalized_base_url}/v1/images/generated/{image_id}"


def resolve_generated_image_base_url(request: Request | None = None) -> str | None:
    configured_base_url = str(config.public_base_url or "").strip().rstrip("/")
    if configured_base_url:
        return configured_base_url
    if request is None:
        return None
    request_base_url = str(request.base_url or "").strip().rstrip("/")
    return request_base_url or None


def build_images_response_payload(
        image_result: dict[str, object],
        billing: dict[str, object] | None,
        response_format: str | None = None,
        base_url: str | None = None,
) -> dict[str, object]:
    requested_response_format = str(response_format or "b64_json").strip().lower()
    wants_url = requested_response_format == "url"
    data_items: list[dict[str, object]] = []
    for item in list(image_result.get("data") or []):
        if not isinstance(item, dict):
            continue
        image_b64 = str(item.get("b64_json") or "").strip()
        if not image_b64:
            continue
        response_item: dict[str, object] = {}
        if wants_url:
            mime_type = str(item.get("mime_type") or "image/png").strip() or "image/png"
            response_item["url"] = save_generated_image_url(image_b64, mime_type, base_url)
        else:
            response_item["b64_json"] = image_b64
        if item.get("revised_prompt") is not None:
            response_item["revised_prompt"] = item.get("revised_prompt")
        if item.get("index") is not None:
            response_item["index"] = int(item.get("index"))
        data_items.append(response_item)
    payload = {
        "created": int(image_result.get("created") or time()),
        "data": data_items,
    }
    copied_text = str(image_result.get("copied_text") or "").strip()
    if copied_text:
        payload["copied_text"] = copied_text
    text_content = str(image_result.get("text_content") or "").strip()
    if text_content:
        payload["text_content"] = text_content
    partial_errors = list(image_result.get("partial_errors") or [])
    if partial_errors:
        payload["partial_errors"] = partial_errors
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
                **(
                    {"index": int((item or {}).get("index"))}
                    if (item or {}).get("index") is not None
                    else {}
                ),
            }
        )
    copied_text = str(image_result.get("copied_text") or "").strip()
    text_content = str(image_result.get("text_content") or "").strip()
    if text_content:
        output_items.append(
            {
                "id": f"msg_{uuid4().hex}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": text_content,
                        "annotations": [],
                    }
                ],
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
    if copied_text:
        payload["copied_text"] = copied_text
    if text_content:
        payload["text_content"] = text_content
        payload["output_text"] = text_content
    partial_errors = list(image_result.get("partial_errors") or [])
    if partial_errors:
        payload["partial_errors"] = partial_errors
    if billing is not None:
        payload["billing"] = billing
    return payload


def build_responses_health_payload(
        *,
        response_model: str,
        auth_type: str,
) -> dict[str, object]:
    created_at = int(time())
    message_id = f"msg_{uuid4().hex}"
    return {
        "id": f"resp_{uuid4().hex}",
        "object": "response",
        "created_at": created_at,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "model": str(response_model or "").strip() or DEFAULT_RESPONSES_MODEL,
        "output": [
            {
                "id": message_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "ok",
                        "annotations": [],
                    }
                ],
            }
        ],
        "output_text": "ok",
        "parallel_tool_calls": False,
        "previous_response_id": None,
        "metadata": {
            "auth_type": auth_type,
            "health_check": True,
        },
        "text": {"format": {"type": "text"}},
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
    }


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


def iter_responses_stream(payload: dict[str, object], *, include_start: bool = True):
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
    if include_start:
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
            request_index = (
                int(output_item.get("index"))
                if output_item.get("index") is not None
                else output_index
            )
            yield emit("response.image_generation_call.in_progress", output_index=output_index, item_id=item_id)
            yield emit("response.image_generation_call.generating", output_index=output_index, item_id=item_id)
            yield emit(
                "response.image_generation_call.completed",
                output_index=output_index,
                index=request_index,
                item_id=item_id,
                result=str(output_item.get("result") or ""),
                item=clone_json_value(output_item),
            )

        output_item_done_extra: dict[str, object] = {
            "output_index": output_index,
            "item": output_item,
        }
        if output_item.get("index") is not None:
            output_item_done_extra["index"] = int(output_item.get("index"))
        yield emit("response.output_item.done", **output_item_done_extra)

    yield emit("response.completed", response=clone_json_value(payload))
    yield format_sse_event(None, "[DONE]")


async def iter_live_responses_generation_stream(
        *,
        build_payload,
        queue_request_id: str,
        response_id: str,
        response_model: str,
):
    sequence_number = 0
    started_at = int(time())
    pending_payload = {
        "id": response_id,
        "object": "response",
        "created_at": started_at,
        "status": "in_progress",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "model": response_model,
        "output": [],
        "parallel_tool_calls": False,
        "previous_response_id": None,
        "metadata": {},
        "text": {"format": {"type": "text"}},
        "usage": None,
    }

    def emit(event_type: str, **extra: Any) -> bytes:
        nonlocal sequence_number
        event_payload = {
            "type": event_type,
            "sequence_number": sequence_number,
            **extra,
        }
        sequence_number += 1
        return format_sse_event(event_type, event_payload)

    yield emit("response.created", response=clone_json_value(pending_payload))
    yield emit("response.in_progress", response=clone_json_value(pending_payload))

    task = asyncio.create_task(build_payload())
    completed = False
    try:
        deadline = time() + IMAGE_GENERATION_TIMEOUT_SECONDS
        while not task.done():
            remaining_seconds = deadline - time()
            if remaining_seconds <= 0:
                task.cancel()
                raise build_image_generation_timeout_error()
            await asyncio.sleep(min(10, max(0.1, remaining_seconds)))
            if not task.done():
                yield emit("response.in_progress", response=clone_json_value(pending_payload), heartbeat=True)
        payload = await task
        for chunk in iter_responses_stream(payload, include_start=False):
            yield chunk
        image_request_log_service.mark_finished(queue_request_id, billing=payload.get("billing"), result=payload)
        image_queue_service.finish_ticket(queue_request_id)
        completed = True
    except asyncio.CancelledError as exc:
        cancelled_error = build_image_generation_cancelled_error()
        message = generation_error_to_text(cancelled_error)
        fail_queue_request(queue_request_id, message)
        image_request_log_service.mark_failed(
            queue_request_id,
            error=cancelled_error,
            http_status=499,
        )
        raise exc
    except Exception as exc:
        fail_queue_request(queue_request_id, str(exc))
        image_request_log_service.mark_failed(
            queue_request_id,
            error=exc,
            http_status=http_status_from_exception(exc),
        )
        failed_payload = {
            **pending_payload,
            "status": "failed",
            "error": {
                "message": generation_error_to_text(exc),
                "type": exc.__class__.__name__,
            },
        }
        yield emit("response.failed", response=failed_payload)
        yield format_sse_event(None, "[DONE]")
        return
    finally:
        if not completed and not task.done():
            task.cancel()


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
        request_index = int((item or {}).get("index")) if (item or {}).get("index") is not None else image_index
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
                    "index": request_index,
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
            "index": request_index,
        }
        if payload.get("usage") is not None:
            completed_event["usage"] = payload.get("usage")
        yield format_sse_event("image_generation.completed", completed_event)
    yield format_sse_event(None, "[DONE]")


def iter_images_stream_with_finish(
        payload: dict[str, object],
        *,
        output_format: str | None,
        background: str | None,
        quality: str | None,
        size: str | None,
        partial_images: int,
        queue_request_id: str,
):
    try:
        yield from iter_images_stream(
            payload,
            output_format=output_format,
            background=background,
            quality=quality,
            size=size,
            partial_images=partial_images,
        )
        image_request_log_service.mark_finished(queue_request_id, billing=payload.get("billing"), result=payload)
    finally:
        image_queue_service.finish_ticket(queue_request_id)


def build_model_item(model_id: str, *, image_tool_model: str | None = None) -> dict[str, object]:
    item: dict[str, object] = {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "openai",
        "endpoint": "/v1/responses",
        "type": "responses",
        "capabilities": {
            "responses": True,
            "streaming": True,
            "tools": True,
            "image_generation": True,
            "input_image": True,
        },
    }
    if image_tool_model:
        item["default_image_tool"] = {
            "type": "image_generation",
            "model": image_tool_model,
        }
    return item


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


def resolve_account_create_payload(body: AccountCreateRequest) -> tuple[list[dict[str, Any]], list[str], str | None]:
    carriers: list[Any] = []
    if body.accounts:
        carriers.append({"accounts": [dict(item) for item in body.accounts if isinstance(item, dict)]})
    for item in (body.payload, body.account_json):
        if item is not None:
            carriers.append(item)

    imported_accounts: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    for carrier in carriers:
        try:
            normalized_accounts = normalize_account_carrier(carrier)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        for account in normalized_accounts:
            access_token = str(account.get("access_token") or "").strip()
            if not access_token or access_token in seen_tokens:
                continue
            seen_tokens.add(access_token)
            imported_accounts.append(account)

    tokens = [str(token or "").strip() for token in body.tokens if str(token or "").strip()]
    category = str(body.category or "").strip() or None
    return imported_accounts, tokens, category


def create_accounts_result(body: AccountCreateRequest, *, category_override: str | None = None) -> dict:
    imported_accounts, tokens, request_category = resolve_account_create_payload(body)
    category = category_override if category_override is not None else request_category
    if not imported_accounts and not tokens:
        raise HTTPException(status_code=400, detail={"error": "tokens or accounts is required"})
    if imported_accounts:
        result = account_service.add_account_items(imported_accounts, category=category)
        refresh_tokens = [str(item.get("access_token") or "").strip() for item in imported_accounts]
    else:
        result = account_service.add_accounts(tokens, category=category)
        refresh_tokens = tokens

    refresh_result = account_service.refresh_accounts(refresh_tokens)
    refreshed_items = refresh_result.get("items", result.get("items", []))
    if hasattr(account_service, "pool_summary"):
        available = int(account_service.pool_summary().get("ready", 0))
    else:
        available = sum(
            1
            for item in refreshed_items
            if item.get("availableForImages")
            or (
                item.get("status") not in {"禁用", "异常"}
                and not bool(item.get("needsRefresh"))
                and int(item.get("quota") or 0) > 0
            )
        )
    return {
        **result,
        "refreshed": refresh_result.get("refreshed", 0),
        "disabled": refresh_result.get("disabled", 0),
        "available": available,
        "errors": refresh_result.get("errors", []),
        "items": refreshed_items,
    }


class DisabledAccountRefreshWatcher:
    def join(self, timeout: float | None = None) -> None:
        del timeout


def start_limited_account_watcher(stop_event: Event) -> DisabledAccountRefreshWatcher:
    del stop_event
    return DisabledAccountRefreshWatcher()


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
        interrupted_count = image_request_log_service.mark_active_failed(
            reason="image generation interrupted by service restart",
            http_status=503,
            error_type="ServiceRestart",
        )
        if interrupted_count:
            print(f"[image-request-log] marked {interrupted_count} active requests as interrupted")
        backup_thread = start_backup_scheduler(stop_event)
        try:
            yield
        finally:
            stop_event.set()
            backup_thread.join(timeout=1)

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
                build_model_item(model, image_tool_model=model)
                for model in ENABLED_IMAGE_MODELS
            ],
        }

    @router.post("/v1/chat/completions")
    async def create_chat_completion_health(body: dict[str, Any], authorization: str | None = Header(default=None)):
        context = require_auth_key(authorization)
        model = str(body.get("model") or DEFAULT_RESPONSES_MODEL).strip() or DEFAULT_RESPONSES_MODEL
        return {
            "id": f"chatcmpl_{uuid4().hex}",
            "object": "chat.completion",
            "created": int(time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "ok",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "metadata": {
                "auth_type": context.auth_type,
                "health_check": True,
            },
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
        reconcile_stale_image_queue_tickets()
        reconcile_stale_image_request_records()
        snapshot = image_queue_service.snapshot(auth_token, request_id=request_id)
        owner_id = build_request_owner_id(auth_token)
        if request_id and snapshot.get("request"):
            record = image_request_log_service.get_record(request_id)
            if record and record.get("owner_id") == owner_id:
                snapshot["request"] = enrich_queue_request_payload_from_record(
                    dict(snapshot["request"] or {}),
                    record,
                )
        elif request_id:
            record = image_request_log_service.get_record(request_id)
            if record and record.get("owner_id") == owner_id:
                record_status = str(record.get("status") or "").strip()
                if record_status in {
                    "accepted",
                    "waiting",
                    "assigning_account",
                    "running",
                    "finished",
                    "failed",
                    "rejected",
                }:
                    request_payload = enrich_queue_request_payload_from_record(
                        {
                            "request_id": request_id,
                            "title": str(record.get("prompt_preview") or "").strip(),
                            "status": record_status,
                            "position": None,
                            "ahead": None,
                            "created_at": record.get("accepted_at") or record.get("created_at"),
                            "started_at": record.get("started_at"),
                            "finished_at": record.get("finished_at"),
                            "error": record.get("error_message"),
                        },
                        record,
                    )
                    snapshot["request"] = request_payload
                    snapshot["items"] = [*list(snapshot.get("items") or []), request_payload]
        return snapshot

    @router.get("/api/image-queue/admin")
    async def get_admin_image_queue(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        reconcile_stale_image_queue_tickets()
        reconcile_stale_image_request_records()
        return image_queue_service.snapshot_all()

    @router.api_route("/v1/responses", methods=["GET", "HEAD"])
    async def check_responses_endpoint(authorization: str | None = Header(default=None)):
        context = require_auth_key(authorization)
        auth_token = extract_bearer_token(authorization)
        reconcile_stale_image_queue_tickets()
        queue_snapshot = image_queue_service.snapshot(auth_token)
        return {
            "object": "list",
            "data": [],
            "status": "ok",
            "endpoint": "/v1/responses",
            "auth_type": context.auth_type,
            "queue": {
                "user": queue_snapshot.get("user", {}),
                "global": queue_snapshot.get("global", {}),
            },
        }

    @router.post("/v1/images/generations")
    async def create_image_generation(
            request: Request,
            body: ImageGenerationRequest,
            authorization: str | None = Header(default=None),
            image_queue_request_id: str | None = Header(default=None, alias="X-Image-Queue-Request-Id"),
    ):
        context = require_auth_key(authorization)
        request_auth_token = extract_bearer_token(authorization)
        requested_model = normalize_requested_image_model(body.model)
        requested_size = resolve_requested_image_size(body.size)
        queue_request_id = resolve_queue_request_id(image_queue_request_id)
        create_image_request_record(
            request_id=queue_request_id,
            context=context,
            auth_token=request_auth_token,
            endpoint="/v1/images/generations",
            protocol="images",
            model=requested_model,
            size=requested_size,
            n=body.n,
            stream=body.stream,
            prompt=body.prompt,
            metadata={"response_format": body.response_format},
        )

        async def build_generation_payload() -> dict[str, object]:
            await register_image_queue_request(request_auth_token, queue_request_id, build_queue_title(body.prompt))
            try:
                await wait_for_image_request_turn(queue_request_id)
            except Exception as exc:
                fail_queue_request(queue_request_id, str(exc))
                raise
            image_result, billing_payload = await generate_image_payload(
                service=service,
                context=context,
                authorization=authorization,
                prompt=body.prompt,
                model=requested_model,
                n=body.n,
                queue_request_id=queue_request_id,
                size=requested_size,
            )
            return build_images_response_payload(
                image_result,
                billing_payload,
                response_format=body.response_format,
                base_url=resolve_generated_image_base_url(request),
            )

        try:
            payload = await await_image_generation_payload(build_generation_payload())
            if not body.stream:
                image_request_log_service.mark_finished(queue_request_id, billing=payload.get("billing"), result=payload)
        except Exception as exc:
            fail_queue_request(queue_request_id, str(exc))
            image_request_log_service.mark_failed(
                queue_request_id,
                error=exc,
                http_status=http_status_from_exception(exc),
            )
            raise
        if body.stream:
            return StreamingResponse(
                iter_images_stream_with_finish(
                    payload,
                    output_format=body.output_format,
                    background=body.background,
                    quality=body.quality,
                    size=requested_size,
                    partial_images=body.partial_images,
                    queue_request_id=queue_request_id,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        return JSONResponse(payload, background=build_queue_background_task(queue_request_id))

    @router.post("/v1/images/edits")
    async def create_image_edit(
            request: Request,
            prompt: str = Form(..., min_length=1),
            image: UploadFile = File(...),
            model: str = Form(default=DEFAULT_IMAGE_MODEL),
            n: int = Form(default=1, ge=1, le=MAX_IMAGES_PER_REQUEST),
            response_format: str = Form(default="b64_json"),
            output_format: str | None = Form(default=None),
            background: str | None = Form(default=None),
            quality: str | None = Form(default=None),
            size: str | None = Form(default=None),
            partial_images: int = Form(default=0, ge=0, le=3),
            stream: bool = Form(default=False),
            authorization: str | None = Header(default=None),
            image_queue_request_id: str | None = Header(default=None, alias="X-Image-Queue-Request-Id"),
    ):
        context = require_auth_key(authorization)
        image_bytes = await image.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail={"error": "image file is required"})
        if len(image_bytes) > MAX_INPUT_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail={"error": "image file must be <= 8 MB"})
        try:
            mime_type = normalize_uploaded_image_mime_type(image_bytes, image.content_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        width, height = detect_image_dimensions(image_bytes)
        if width is not None and width < MIN_INPUT_IMAGE_SIDE:
            raise HTTPException(status_code=400, detail={"error": "image width is too small"})
        if height is not None and height < MIN_INPUT_IMAGE_SIDE:
            raise HTTPException(status_code=400, detail={"error": "image height is too small"})

        request_auth_token = extract_bearer_token(authorization)
        requested_model = normalize_requested_image_model(model)
        requested_size = resolve_requested_image_size(size)
        queue_request_id = resolve_queue_request_id(image_queue_request_id)
        input_images = [
            {
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}",
            }
        ]
        create_image_request_record(
            request_id=queue_request_id,
            context=context,
            auth_token=request_auth_token,
            endpoint="/v1/images/edits",
            protocol="images_edit",
            model=requested_model,
            size=requested_size,
            n=n,
            stream=stream,
            prompt=prompt,
            has_input_image=True,
            input_image_count=1,
            metadata={"response_format": response_format},
        )

        async def build_generation_payload() -> dict[str, object]:
            await register_image_queue_request(request_auth_token, queue_request_id, build_queue_title(prompt))
            try:
                await wait_for_image_request_turn(queue_request_id)
            except Exception as exc:
                fail_queue_request(queue_request_id, str(exc))
                raise
            image_result, billing_payload = await generate_image_payload(
                service=service,
                context=context,
                authorization=authorization,
                prompt=prompt,
                model=requested_model,
                n=n,
                input_images=input_images,
                queue_request_id=queue_request_id,
                size=requested_size,
            )
            return build_images_response_payload(
                image_result,
                billing_payload,
                response_format=response_format,
                base_url=resolve_generated_image_base_url(request),
            )

        try:
            payload = await await_image_generation_payload(build_generation_payload())
            if not stream:
                image_request_log_service.mark_finished(queue_request_id, billing=payload.get("billing"), result=payload)
        except Exception as exc:
            fail_queue_request(queue_request_id, str(exc))
            image_request_log_service.mark_failed(
                queue_request_id,
                error=exc,
                http_status=http_status_from_exception(exc),
            )
            raise
        if stream:
            return StreamingResponse(
                iter_images_stream_with_finish(
                    payload,
                    output_format=output_format,
                    background=background,
                    quality=quality,
                    size=requested_size,
                    partial_images=partial_images,
                    queue_request_id=queue_request_id,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        return JSONResponse(payload, background=build_queue_background_task(queue_request_id))

    @router.post("/v1/responses")
    async def create_response(
            body: ResponsesCreateRequest,
            authorization: str | None = Header(default=None),
            image_queue_request_id: str | None = Header(default=None, alias="X-Image-Queue-Request-Id"),
    ):
        context = require_auth_key(authorization)
        if not has_image_generation_tool(body.tools):
            payload = build_responses_health_payload(
                response_model=body.model,
                auth_type=context.auth_type,
            )
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
        response_model = str(body.model or "").strip() or DEFAULT_RESPONSES_MODEL
        requested_model = resolve_requested_response_image_model(body)
        response_id = f"resp_{uuid4().hex}"
        create_image_request_record(
            request_id=queue_request_id,
            context=context,
            auth_token=request_auth_token,
            endpoint="/v1/responses",
            protocol="responses",
            model=requested_model,
            size=requested_size,
            n=body.n,
            stream=body.stream,
            prompt=prompt,
            has_input_image=bool(input_images),
            input_image_count=len(input_images),
            client_conversation_id=client_conversation_id,
            response_id=response_id,
            metadata={"response_model": response_model},
        )

        async def build_generation_payload() -> dict[str, object]:
            await register_image_queue_request(request_auth_token, queue_request_id, build_queue_title(prompt))
            try:
                await wait_for_image_request_turn(queue_request_id)
            except Exception as exc:
                fail_queue_request(queue_request_id, str(exc))
                raise
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
            return payload

        if body.stream:
            return StreamingResponse(
                iter_live_responses_generation_stream(
                    build_payload=build_generation_payload,
                    queue_request_id=queue_request_id,
                    response_id=response_id,
                    response_model=response_model,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        try:
            payload = await await_image_generation_payload(build_generation_payload())
            if not body.stream:
                image_request_log_service.mark_finished(queue_request_id, billing=payload.get("billing"), result=payload)
        except Exception as exc:
            fail_queue_request(queue_request_id, str(exc))
            image_request_log_service.mark_failed(
                queue_request_id,
                error=exc,
                http_status=http_status_from_exception(exc),
            )
            raise
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

    @router.get("/v1/images/generated/{image_id}")
    async def get_generated_image(image_id: str):
        normalized_id = Path(str(image_id or "").strip()).name
        if not normalized_id or normalized_id != str(image_id or "").strip():
            raise HTTPException(status_code=404, detail={"error": "generated image not found"})
        file_path = GENERATED_IMAGE_DIR / normalized_id
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail={"error": "generated image not found"})
        suffix = file_path.suffix.lower()
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".avif": "image/avif",
        }.get(suffix, "image/png")
        return FileResponse(file_path, media_type=media_type, filename=file_path.name)

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

    @router.post("/api/proxies/test")
    async def test_proxy_connection(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return proxy_service.test_connection()

    @router.get("/api/user-keys")
    async def get_user_keys(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return {"items": user_key_service.list_public_user_keys()}

    @router.get("/api/redeem-codes")
    async def get_redeem_codes(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return {"items": redeem_code_service.list_public_codes()}

    @router.get("/api/gallery/public")
    async def list_public_gallery(
            authorization: str | None = Header(default=None),
            limit: int = Query(default=120, ge=1, le=500),
    ):
        require_auth_key(authorization)
        return {"items": gallery_service.list_public_items(limit=limit)}

    @router.get("/api/gallery/assets/{asset_id}")
    async def get_gallery_asset(asset_id: str):
        image_response = gallery_service.get_asset_image_response(asset_id)
        if image_response is None:
            raise HTTPException(status_code=404, detail={"error": "gallery asset not found"})
        content, media_type = image_response
        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @router.post("/api/gallery/{item_id}/events")
    async def record_gallery_event(
            item_id: str,
            body: GalleryEventRequest,
            authorization: str | None = Header(default=None),
    ):
        require_auth_key(authorization)
        try:
            item = gallery_service.record_event(item_id, body.event)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "gallery item not found"})
        return {"item": item}

    @router.post("/api/gallery/submissions")
    async def submit_gallery_item(
            body: GallerySubmissionRequest,
            authorization: str | None = Header(default=None),
    ):
        require_auth_key(authorization)
        try:
            item = gallery_service.submit_item(
                auth_token=extract_bearer_token(authorization),
                payload=body.model_dump(exclude_none=True),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item}

    @router.get("/api/admin/gallery")
    async def list_admin_gallery(
            authorization: str | None = Header(default=None),
            status: str | None = Query(default=None),
            limit: int = Query(default=200, ge=1, le=500),
    ):
        require_admin_auth_key(authorization)
        return {
            "items": gallery_service.list_admin_items(status=status, limit=limit),
            "status": gallery_service.get_status(),
        }

    @router.patch("/api/admin/gallery/{item_id}")
    async def update_admin_gallery_item(
            item_id: str,
            body: AdminGalleryUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        context = require_admin_auth_key(authorization)
        reviewed_by = context.auth_type
        try:
            item = gallery_service.admin_update_item(
                item_id,
                body.model_dump(exclude_none=True),
                reviewed_by=reviewed_by,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": "gallery item not found"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {
            "item": item,
            "items": gallery_service.list_admin_items(),
            "status": gallery_service.get_status(),
        }

    @router.delete("/api/admin/gallery/{item_id}")
    async def delete_admin_gallery_item(
            item_id: str,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        result = gallery_service.admin_delete_item(item_id)
        return {
            **result,
            "items": gallery_service.list_admin_items(),
            "status": gallery_service.get_status(),
        }

    @router.get("/api/data-management/status")
    async def get_data_management_status(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return data_management_service.get_status()

    @router.get("/api/data-management/settings")
    async def get_data_management_settings(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return data_management_service.get_settings(masked=True)

    @router.put("/api/data-management/settings")
    async def update_data_management_settings(
            body: DataManagementSettingsRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        return data_management_service.update_settings(body.model_dump(exclude_none=True))

    @router.post("/api/data-management/backups")
    async def create_data_backup(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return data_management_service.create_backup(reason="manual")

    @router.get("/api/data-management/backups")
    async def list_data_backups(
            authorization: str | None = Header(default=None),
            limit: int = Query(default=100, ge=1, le=500),
    ):
        require_admin_auth_key(authorization)
        return {"items": data_management_service.list_backups(limit=limit)}

    @router.post("/api/data-management/s3/test")
    async def test_data_management_s3(body: dict[str, Any], authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        try:
            return data_management_service.test_s3(body)
        except Exception as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/data-management/logs")
    async def list_data_management_logs(
            authorization: str | None = Header(default=None),
            limit: int = Query(default=100, ge=1, le=500),
            level: str | None = Query(default=None),
            component: str | None = Query(default=None),
            since: str | None = Query(default=None),
    ):
        require_admin_auth_key(authorization)
        return {
            "items": data_management_service.list_logs(
                limit=limit,
                level=level,
                component=component,
                since=since,
            )
        }

    @router.get("/api/image-requests")
    async def list_image_requests(
            authorization: str | None = Header(default=None),
            request_id: str | None = Query(default=None),
            owner_id: str | None = Query(default=None),
            auth_type: str | None = Query(default=None),
            status: str | None = Query(default=None),
            model: str | None = Query(default=None),
            endpoint: str | None = Query(default=None),
            since: str | None = Query(default=None),
            until: str | None = Query(default=None),
            limit: int = Query(default=100, ge=1, le=500),
            cursor: str | None = Query(default=None),
    ):
        require_admin_auth_key(authorization)
        return image_request_log_service.list_records(
            filters={
                "request_id": request_id,
                "owner_id": owner_id,
                "auth_type": auth_type,
                "status": status,
                "model": model,
                "endpoint": endpoint,
                "since": since,
                "until": until,
            },
            cursor=cursor,
            limit=limit,
        )

    @router.get("/api/image-requests/{request_id}")
    async def get_image_request_record(request_id: str, authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        record = image_request_log_service.get_record(request_id)
        if record is None:
            raise HTTPException(status_code=404, detail={"error": "image request record not found"})
        return record

    @router.get("/api/image-conversations")
    async def list_image_conversations(
        summary: bool = False,
        limit: int = Query(default=100, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        authorization: str | None = Header(default=None),
    ):
        require_auth_key(authorization)
        return {
            "items": data_management_service.list_conversations(
                extract_bearer_token(authorization),
                summary=summary,
                limit=limit,
                offset=offset,
            )
        }

    @router.get("/api/image-conversations/{conversation_id}")
    async def get_image_conversation(conversation_id: str, authorization: str | None = Header(default=None)):
        require_auth_key(authorization)
        item = data_management_service.get_conversation(extract_bearer_token(authorization), conversation_id)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "image conversation not found"})
        return {"item": item}

    @router.post("/api/image-conversations")
    async def save_image_conversation(body: dict[str, Any], authorization: str | None = Header(default=None)):
        require_auth_key(authorization)
        auth_token = extract_bearer_token(authorization)
        try:
            item = data_management_service.upsert_conversation(auth_token, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "items": data_management_service.list_conversations(auth_token, summary=True)}

    @router.delete("/api/image-conversations")
    async def delete_image_conversation(body: dict[str, Any], authorization: str | None = Header(default=None)):
        require_auth_key(authorization)
        conversation_id = str(body.get("id") or body.get("conversation_id") or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=400, detail={"error": "conversation id is required"})
        auth_token = extract_bearer_token(authorization)
        result = data_management_service.delete_conversation(auth_token, conversation_id)
        return {**result, "items": data_management_service.list_conversations(auth_token, summary=True)}

    @router.post("/api/accounts")
    async def create_accounts(
            body: AccountCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        return create_accounts_result(body)

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
        result = create_accounts_result(body, category_override=account_service.DONATION_CATEGORY)
        rewarded_accounts = 0
        rewarded_ldc = 0
        remaining_quota = context.remaining_quota
        ldc_balance = context.ldc_balance
        if context.auth_type == "user_key" and rewarded_ldc > 0:
            rewarded_user_key = user_key_service.grant_ldc(extract_bearer_token(authorization), rewarded_ldc)
            if rewarded_user_key is not None:
                remaining_quota = max(0, int(rewarded_user_key.get("quota") or 0))
                ldc_balance = max(0, int(rewarded_user_key.get("ldc_balance") or 0))
        return {
            **result,
            "items": result.get("items", []),
            "rewarded_accounts": rewarded_accounts,
            "rewarded_ldc": rewarded_ldc,
            "remaining_quota": remaining_quota,
            "ldc_balance": ldc_balance,
        }

    @router.post("/api/external/accounts")
    async def create_external_accounts(
            body: AccountCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        return create_accounts_result(body)

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

    @app.api_route("/{full_path:path}", methods=["POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def serve_missing_non_get(full_path: str):
        del full_path
        raise HTTPException(status_code=404, detail="Not Found")

    return app
