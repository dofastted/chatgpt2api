from __future__ import annotations

import hashlib

from fastapi import HTTPException

from services.account_service import AccountService
from services.image_service import (
    ImageGenerationError,
    generate_image_result,
    is_low_quality_image_error,
    is_transient_image_error,
    is_token_invalid_error,
)
from services.image_queue_service import image_queue_service
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

    @staticmethod
    def _is_transient_refresh_error(message: str) -> bool:
        normalized = str(message or "").lower()
        return (
            "tls connect error" in normalized
            or "failed to perform, curl:" in normalized
            or "timeout" in normalized
            or "timed out" in normalized
            or "connection was reset" in normalized
            or "recv failure" in normalized
        )

    @staticmethod
    def _is_terminal_refresh_error(message: str) -> bool:
        normalized = str(message or "").lower()
        return (
            "/backend-api/me failed: http 401" in normalized
            or "/backend-api/me failed: http 402" in normalized
        )

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
        return "images"

    @staticmethod
    def _is_responses_input_image_rejection(exc: ImageGenerationError, input_images: list[dict[str, str]] | None) -> bool:
        return bool(input_images) and "responses failed: 400" in str(exc).lower()

    def _refresh_request_token(self, access_token: str) -> dict | None:
        cached_account = self.account_service.get_account(access_token)
        try:
            remote_info = self.account_service.fetch_remote_info(access_token)
        except Exception as exc:
            message = str(exc)
            print(f"[image-generate] refresh token={self._token_label(access_token)} fail {message}")
            if self._is_terminal_refresh_error(message):
                return self.account_service.update_account(
                    access_token,
                    {
                        "status": "异常",
                        "quota": 0,
                        "cooldown_until": None,
                    },
                )
            if self._is_transient_refresh_error(message) and self._is_account_ready_for_image(cached_account):
                print(f"[image-generate] refresh fallback token={self._token_label(access_token)} use cached account state")
                return cached_account
            self.account_service.mark_request_failure(access_token)
            return None
        return self.account_service.update_account(access_token, remote_info)

    def resolve_request_token(self, excluded_tokens: set[str] | None = None) -> str:
        if hasattr(self.account_service, "try_acquire_token_slot"):
            token = self.account_service.try_acquire_token_slot(excluded_tokens=excluded_tokens)
            if token:
                return token
        try:
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

        while True:
            if queue_request_id:
                image_queue_service.mark_assigning_account(queue_request_id)
            try:
                request_token = self.resolve_request_token(excluded_tokens=attempted_tokens)
            except HTTPException:
                raise

            attempted_tokens.add(request_token)
            try:
                refreshed_account = self._refresh_request_token(request_token)
                if not self._is_account_ready_for_image(refreshed_account):
                    print(
                        f"[image-generate] skip token={self._token_label(request_token)} "
                        f"quota={refreshed_account.get('quota') if refreshed_account else 'unknown'} "
                        f"status={refreshed_account.get('status') if refreshed_account else 'unknown'}"
                    )
                    continue

                if queue_request_id:
                    image_queue_service.mark_status(queue_request_id, "running")
                route = select_image_route(
                    account=refreshed_account,
                    has_input_image=bool(input_images),
                    policy=config.image_route_policy,
                )
                route_candidates = [route]
                fallback_route = self._fallback_route_for(route, input_images)
                if fallback_route:
                    route_candidates.append(fallback_route)
                last_route_error: ImageGenerationError | None = None
                for candidate_route in route_candidates:
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
                account = self.account_service.mark_image_result(request_token, success=True)
                print(
                    f"[image-generate] success pooled token={self._token_label(request_token)} "
                    f"quota={account.get('quota') if account else 'unknown'} status={account.get('status') if account else 'unknown'}"
                )
                return result
            except ImageGenerationError as exc:
                account = self.account_service.mark_image_result(request_token, success=False)
                print(
                    f"[image-generate] fail pooled token={self._token_label(request_token)} "
                    f"error={exc} quota={account.get('quota') if account else 'unknown'} status={account.get('status') if account else 'unknown'}"
                )
                if is_token_invalid_error(str(exc)):
                    self.account_service.remove_token(request_token)
                    print(f"[image-generate] remove invalid token={self._token_label(request_token)}")
                    continue
                if is_low_quality_image_error(str(exc)):
                    print(f"[image-generate] skip low quality token={self._token_label(request_token)}")
                    continue
                if self._is_responses_input_image_rejection(exc, input_images):
                    print(f"[image-generate] skip responses input image rejection token={self._token_label(request_token)}")
                    continue
                if is_transient_image_error(str(exc)):
                    print(f"[image-generate] skip transient failure token={self._token_label(request_token)}")
                    continue
                raise
            finally:
                if hasattr(self.account_service, "release_token_slot"):
                    self.account_service.release_token_slot(request_token)
