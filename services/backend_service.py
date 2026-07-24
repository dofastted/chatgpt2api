from __future__ import annotations

import hashlib

from fastapi import HTTPException

from services.account_service import AccountService
from services.image_service import (
    ImageGenerationError,
    generate_image_result,
    is_transient_image_error,
    is_token_invalid_error,
)
from services.image_queue_service import image_queue_service
from services.image_request_log_service import image_request_log_service
from services.config import config
from services.chat_image.gateway import ImageGateway
from services.chat_image.route_selector import select_image_route


class BackendService:
    def __init__(self, account_service: AccountService):
        self.account_service = account_service
        self.image_gateway = ImageGateway(
            lambda access_token, prompt, model, n, input_images, route, size=None: generate_image_result(
                access_token,
                prompt,
                model,
                n,
                input_images=input_images,
                route=route,
                size=size,
            )
        )

    @staticmethod
    def _token_label(access_token: str) -> str:
        return hashlib.sha1(str(access_token or "").encode("utf-8")).hexdigest()[:10]

    def _account_pool_error_detail(self) -> dict:
        summary = None
        if hasattr(self.account_service, "pool_summary"):
            summary = self.account_service.pool_summary()
        return {
            "error": "No available account slots found",
            "reason": "account_pool_unavailable",
            "message": "账号池没有可调度账号，请刷新账号、检查额度或等待冷却结束",
            **({"summary": summary} if summary is not None else {}),
        }

    @staticmethod
    def _is_account_ready_for_image(account: dict | None) -> bool:
        if not isinstance(account, dict):
            return False
        if account.get("status") in {"禁用", "异常"}:
            return False
        return int(account.get("quota") or 0) > 0

    @staticmethod
    def _fallback_route_for(route: str, input_images: list[dict[str, str]] | None) -> str | None:
        normalized_route = str(route or "").strip().lower()
        if normalized_route != "responses":
            return None
        if input_images:
            return None
        # Legacy "images" conversation route is broken upstream (always times out
        # with "no image returned"); falling back to it only wastes the poll
        # timeout. Disable fallback so a responses failure rotates accounts fast.
        return None

    @staticmethod
    def _is_responses_input_image_rejection(exc: ImageGenerationError, input_images: list[dict[str, str]] | None) -> bool:
        return bool(input_images) and "responses failed: 400" in str(exc).lower()

    def _mark_image_result(
        self,
        access_token: str,
        *,
        success: bool,
        input_image: bool,
        error: str | None = None,
    ) -> dict | None:
        try:
            return self.account_service.mark_image_result(
                access_token,
                success=success,
                input_image=input_image,
                error=error,
            )
        except TypeError:
            return self.account_service.mark_image_result(access_token, success=success)

    def resolve_request_token(
        self,
        excluded_tokens: set[str] | None = None,
        *,
        prefer_input_image: bool = False,
    ) -> str:
        if hasattr(self.account_service, "acquire_token_slot"):
            try:
                token = self.account_service.acquire_token_slot(
                    excluded_tokens=excluded_tokens,
                    prefer_input_image=prefer_input_image,
                    timeout_seconds=config.image_generation_timeout_seconds,
                )
            except TypeError:
                token = self.account_service.acquire_token_slot(excluded_tokens=excluded_tokens)
            if token:
                return token
            raise HTTPException(status_code=503, detail=self._account_pool_error_detail())
        if hasattr(self.account_service, "try_acquire_token_slot"):
            try:
                token = self.account_service.try_acquire_token_slot(
                    excluded_tokens=excluded_tokens,
                    prefer_input_image=prefer_input_image,
                )
            except TypeError:
                token = self.account_service.try_acquire_token_slot(excluded_tokens=excluded_tokens)
            if token:
                return token
            raise HTTPException(status_code=503, detail=self._account_pool_error_detail())
        try:
            try:
                return self.account_service.next_token(
                    excluded_tokens=excluded_tokens,
                    prefer_input_image=prefer_input_image,
                )
            except TypeError:
                return self.account_service.next_token(excluded_tokens=excluded_tokens)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc

    def generate_with_pool(
        self,
        prompt: str,
        model: str,
        n: int,
        input_images: list[dict[str, str]] | None = None,
        queue_request_id: str | None = None,
        size: str | None = None,
    ):
        attempted_tokens: set[str] = set()
        account_attempt_count = 0
        max_account_attempts = max(1, int(config.image_generation_max_account_attempts or 4))
        last_error: Exception | None = None

        while True:
            if account_attempt_count >= max_account_attempts:
                message = (
                    f"image generation failed after {max_account_attempts} account attempts"
                    + (f": {last_error}" if last_error else "")
                )
                raise ImageGenerationError(message)
            if queue_request_id:
                image_queue_service.mark_assigning_account(queue_request_id)
            try:
                request_token = self.resolve_request_token(
                    excluded_tokens=attempted_tokens,
                    prefer_input_image=bool(input_images),
                )
            except HTTPException:
                if last_error is not None and is_transient_image_error(str(last_error)):
                    raise ImageGenerationError(
                        f"image generation failed after {account_attempt_count} account attempts: {last_error}"
                    ) from last_error
                raise

            attempted_tokens.add(request_token)
            account_attempt_count += 1
            try:
                account = self.account_service.get_account(request_token)
                if not self._is_account_ready_for_image(account):
                    print(
                        f"[image-generate] skip token={self._token_label(request_token)} "
                        f"quota={account.get('quota') if account else 'unknown'} "
                        f"status={account.get('status') if account else 'unknown'}"
                    )
                    continue

                if queue_request_id:
                    image_queue_service.mark_status(queue_request_id, "running")
                route = select_image_route(
                    account=account,
                    has_input_image=bool(input_images),
                    policy=config.image_route_policy,
                )
                route_candidates = [route]
                fallback_route = self._fallback_route_for(route, input_images)
                if fallback_route:
                    route_candidates.append(fallback_route)
                last_route_error: ImageGenerationError | None = None
                for attempt_index, candidate_route in enumerate(route_candidates, start=1):
                    if queue_request_id:
                        image_request_log_service.mark_running(
                            queue_request_id,
                            account_token=request_token,
                            account_type=str((account or {}).get("type") or ""),
                            route=candidate_route,
                            attempt_count=account_attempt_count,
                            fallback_used=attempt_index > 1,
                        )
                    print(
                        f"[image-generate] start pooled token={self._token_label(request_token)} "
                        f"model={model} n={n} size={size or 'auto'} route={candidate_route}"
                    )
                    try:
                        result = self.image_gateway.generate_image(
                            request_token,
                            prompt,
                            model,
                            n,
                            input_images=input_images,
                            route=candidate_route,
                            size=size,
                        )
                        break
                    except ImageGenerationError as exc:
                        last_route_error = exc
                        if (
                            candidate_route == route
                            and fallback_route
                            and is_transient_image_error(str(exc))
                        ):
                            print(
                                f"[image-generate] fallback route token={self._token_label(request_token)} "
                                f"from={candidate_route} to={fallback_route} error={exc}"
                            )
                            continue
                        raise
                else:
                    assert last_route_error is not None
                    raise last_route_error
                account = self._mark_image_result(
                    request_token,
                    success=True,
                    input_image=bool(input_images),
                )
                print(
                    f"[image-generate] success pooled token={self._token_label(request_token)} "
                    f"quota={account.get('quota') if account else 'unknown'} status={account.get('status') if account else 'unknown'}"
                )
                return result
            except ImageGenerationError as exc:
                account = self._mark_image_result(
                    request_token,
                    success=False,
                    input_image=bool(input_images),
                    error=str(exc),
                )
                print(
                    f"[image-generate] fail pooled token={self._token_label(request_token)} "
                    f"error={exc} quota={account.get('quota') if account else 'unknown'} status={account.get('status') if account else 'unknown'}"
                )
                if is_token_invalid_error(str(exc)):
                    last_error = exc
                    if hasattr(self.account_service, "disable_account"):
                        self.account_service.disable_account(
                            request_token,
                            reason="credential_invalid",
                            error="账号凭据已失效",
                        )
                    else:
                        self.account_service.update_account(
                            request_token,
                            {"status": "禁用", "quota": 0, "needs_refresh": False},
                        )
                    print(f"[image-generate] disable invalid token={self._token_label(request_token)}")
                    continue
                if self._is_responses_input_image_rejection(exc, input_images):
                    last_error = exc
                    print(f"[image-generate] skip responses input image rejection token={self._token_label(request_token)}")
                    continue
                if is_transient_image_error(str(exc)):
                    last_error = exc
                    print(f"[image-generate] skip transient failure token={self._token_label(request_token)}")
                    continue
                raise
            finally:
                if hasattr(self.account_service, "release_token_slot"):
                    self.account_service.release_token_slot(request_token)
