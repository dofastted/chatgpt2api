from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread

from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from services.account_service import account_service
from services.config import config
from services.backend_service import BackendService
from services.image_service import ImageGenerationError
from services.user_key_service import user_key_service
from services.version import get_app_version


BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIST_DIR = BASE_DIR / "web_dist"


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str = "gpt-4o"
    n: int = Field(default=1, ge=1, le=4)
    response_format: str = "b64_json"
    history_disabled: bool = True


class AccountCreateRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)


class AccountDeleteRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)


class AccountRefreshRequest(BaseModel):
    access_tokens: list[str] = Field(default_factory=list)


class AccountUpdateRequest(BaseModel):
    access_token: str = Field(default="")
    type: str | None = None
    status: str | None = None
    quota: int | None = None


@dataclass(frozen=True)
class AuthContext:
    role: str
    auth_type: str
    remaining_quota: int | None = None
    user_key_id: str | None = None
    user_key_label: str | None = None


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
    }


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
    if not WEB_DIST_DIR.exists():
        return None

    clean_path = requested_path.strip("/")
    if not clean_path:
        candidates = [WEB_DIST_DIR / "index.html"]
    else:
        relative_path = Path(clean_path)
        candidates = [
            WEB_DIST_DIR / relative_path,
            WEB_DIST_DIR / relative_path / "index.html",
            WEB_DIST_DIR / f"{clean_path}.html",
        ]

    for candidate in candidates:
        try:
            candidate.relative_to(WEB_DIST_DIR)
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

    @router.get("/version")
    async def get_version():
        return {"version": app_version}

    @router.get("/api/accounts")
    async def get_accounts(authorization: str | None = Header(default=None)):
        require_admin_auth_key(authorization)
        return {"items": account_service.list_accounts()}

    @router.post("/api/accounts")
    async def create_accounts(
            body: AccountCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_auth_key(authorization)
        tokens = [str(token or "").strip() for token in body.tokens if str(token or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens is required"})
        result = account_service.add_accounts(tokens)
        refresh_result = account_service.refresh_accounts(tokens)
        return {
            **result,
            "refreshed": refresh_result.get("refreshed", 0),
            "errors": refresh_result.get("errors", []),
            "items": refresh_result.get("items", result.get("items", [])),
        }

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

    @router.get("/api/quota")
    async def get_quota_summary(authorization: str | None = Header(default=None)):
        context = require_auth_key(authorization)
        if context.auth_type == "user_key":
            return {
                "available_quota": max(0, int(context.remaining_quota or 0)),
                "auth_type": context.auth_type,
                "remaining_quota": max(0, int(context.remaining_quota or 0)),
            }
        accounts = account_service.list_accounts()
        available_quota = sum(
            max(0, int(account.get("quota") or 0))
            for account in accounts
            if account.get("status") != "禁用"
        )
        return {"available_quota": available_quota, "auth_type": context.auth_type, "remaining_quota": None}

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

    @router.post("/v1/images/generations")
    async def generate_images(
            body: ImageGenerationRequest,
            authorization: str | None = Header(default=None),
    ):
        require_auth_key(authorization)
        try:
            return await run_in_threadpool(
                service.generate_with_pool,
                body.prompt,
                body.model,
                body.n,
            )
        except ImageGenerationError as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

    app.include_router(router)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_web(full_path: str):
        asset = resolve_web_asset(full_path)
        if asset is not None:
            return FileResponse(asset)

        fallback = resolve_web_asset("")
        if fallback is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(fallback)

    return app
