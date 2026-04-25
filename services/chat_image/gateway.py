from __future__ import annotations

from collections.abc import Callable
from typing import Any


LegacyGenerate = Callable[
    [str, str, str, int, list[dict[str, str]] | None, str],
    dict[str, Any],
]


class ImageGateway:
    def __init__(self, legacy_generate: LegacyGenerate):
        self._legacy_generate = legacy_generate

    def generate_image(
        self,
        access_token: str,
        prompt: str,
        model: str,
        n: int,
        *,
        input_images: list[dict[str, str]] | None = None,
        route: str = "legacy",
    ) -> dict[str, Any]:
        return self._legacy_generate(access_token, prompt, model, n, input_images, route)

    def create_response(
        self,
        access_token: str,
        prompt: str,
        model: str,
        n: int,
        *,
        input_images: list[dict[str, str]] | None = None,
        route: str = "legacy",
    ) -> dict[str, Any]:
        return self.generate_image(
            access_token,
            prompt,
            model,
            n,
            input_images=input_images,
            route=route,
        )

    def edit_image(
        self,
        access_token: str,
        prompt: str,
        model: str,
        n: int,
        *,
        input_images: list[dict[str, str]],
        route: str = "legacy",
    ) -> dict[str, Any]:
        return self.generate_image(
            access_token,
            prompt,
            model,
            n,
            input_images=input_images,
            route=route,
        )
