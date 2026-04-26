from __future__ import annotations

from typing import Any, Literal

from services.chat_image.account_plan import normalize_plan_type


ImageRoute = Literal["responses", "images", "images_edit", "legacy"]


def select_image_route(
    *,
    account: dict[str, Any] | None,
    has_input_image: bool = False,
    policy: str = "plan_type",
) -> ImageRoute:
    normalized_policy = str(policy or "plan_type").strip().lower()
    if normalized_policy == "legacy":
        return "legacy"
    if normalized_policy == "force_responses":
        return "responses"
    if normalized_policy == "force_images":
        return "images_edit" if has_input_image else "images"

    plan_type = normalize_plan_type((account or {}).get("type") or (account or {}).get("plan_type"))
    if has_input_image:
        return "images_edit" if plan_type == "Free" else "responses"
    return "images"
