from __future__ import annotations

import re


IMAGE_SIZE_AUTO = "auto"
IMAGE_SIZE_MIN = 16
IMAGE_SIZE_MAX = 4096


def _round_down_to_multiple(value: int, multiple: int = 16) -> int:
    return max(IMAGE_SIZE_MIN, (max(IMAGE_SIZE_MIN, int(value)) // multiple) * multiple)


def normalize_image_size(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized or normalized == IMAGE_SIZE_AUTO:
        return IMAGE_SIZE_AUTO
    match = re.fullmatch(r"(\d{2,5})\s*x\s*(\d{2,5})", normalized)
    if match is None:
        raise ValueError("image size must be auto or WIDTHxHEIGHT")
    width = _round_down_to_multiple(int(match.group(1)))
    height = _round_down_to_multiple(int(match.group(2)))
    if width > IMAGE_SIZE_MAX or height > IMAGE_SIZE_MAX:
        raise ValueError(f"image size must be <= {IMAGE_SIZE_MAX}x{IMAGE_SIZE_MAX}")
    return f"{width}x{height}"


def upstream_image_size(value: str | None) -> str | None:
    normalized = normalize_image_size(value)
    if normalized == IMAGE_SIZE_AUTO:
        return None
    return normalized
