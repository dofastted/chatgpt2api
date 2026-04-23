from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from services.config import DATA_DIR


SUPPORTED_IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/avif": ".avif",
}


def detect_image_mime_type(image_bytes: bytes, response_content_type: str | None = None) -> str:
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


def normalize_uploaded_image_mime_type(image_bytes: bytes, response_content_type: str | None = None) -> str:
    mime_type = detect_image_mime_type(image_bytes, response_content_type)
    if mime_type not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(f"unsupported input image mime type: {mime_type}")
    return mime_type


def detect_image_dimensions(image_bytes: bytes) -> tuple[int | None, int | None]:
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


class UploadedImageService:
    def __init__(self, store_file: Path, files_dir: Path):
        self.store_file = store_file
        self.files_dir = files_dir
        self._lock = Lock()
        self._items = self._load_items()

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def build_owner_id(auth_token: str) -> str:
        normalized_token = str(auth_token or "").strip()
        if not normalized_token:
            return ""
        return hashlib.sha1(normalized_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _normalize_item(self, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        file_id = self._clean_text(item.get("file_id") or item.get("id"))
        owner_id = self._clean_text(item.get("owner_id"))
        stored_name = self._clean_text(item.get("stored_name"))
        mime_type = self._clean_text(item.get("mime_type"))
        if not file_id or not owner_id or not stored_name or not mime_type:
            return None
        size_bytes = max(0, int(item.get("size_bytes") or 0))
        width = item.get("width")
        height = item.get("height")
        return {
            "id": file_id,
            "file_id": file_id,
            "owner_id": owner_id,
            "file_name": self._clean_text(item.get("file_name")) or stored_name,
            "stored_name": stored_name,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "width": int(width) if width is not None else None,
            "height": int(height) if height is not None else None,
            "created_at": self._clean_text(item.get("created_at")) or None,
            "images_app_only": bool(item.get("images_app_only")),
        }

    def _load_items(self) -> list[dict[str, Any]]:
        if not self.store_file.exists():
            return []
        try:
            data = json.loads(self.store_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [normalized for item in data if (normalized := self._normalize_item(item)) is not None]

    def _save_items(self) -> None:
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        self.store_file.write_text(
            json.dumps(self._items, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _build_public_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(item.get("file_id") or ""),
            "file_id": str(item.get("file_id") or ""),
            "name": str(item.get("file_name") or ""),
            "mime_type": str(item.get("mime_type") or ""),
            "size_bytes": max(0, int(item.get("size_bytes") or 0)),
            "width": item.get("width"),
            "height": item.get("height"),
            "created_at": str(item.get("created_at") or "") or None,
            "images_app_only": bool(item.get("images_app_only")),
            "download_url": f"/backend-api/files/{item.get('file_id')}/content",
        }

    def save_upload(
        self,
        *,
        auth_token: str,
        file_name: str,
        content_type: str | None,
        image_bytes: bytes,
        images_app_only: bool = False,
    ) -> dict[str, Any]:
        owner_id = self.build_owner_id(auth_token)
        if not owner_id:
            raise ValueError("auth token is required")
        if not image_bytes:
            raise ValueError("image is empty")
        mime_type = normalize_uploaded_image_mime_type(image_bytes, content_type)
        width, height = detect_image_dimensions(image_bytes)
        file_ext = SUPPORTED_IMAGE_EXTENSIONS.get(mime_type, ".png")
        file_id = f"upload_{uuid.uuid4().hex}"
        stored_name = f"{file_id}{file_ext}"
        stored_path = self.files_dir / stored_name
        self.files_dir.mkdir(parents=True, exist_ok=True)
        stored_path.write_bytes(image_bytes)
        item = self._normalize_item(
            {
                "file_id": file_id,
                "owner_id": owner_id,
                "file_name": self._clean_text(file_name) or stored_name,
                "stored_name": stored_name,
                "mime_type": mime_type,
                "size_bytes": len(image_bytes),
                "width": width,
                "height": height,
                "created_at": self._now_text(),
                "images_app_only": images_app_only,
            }
        )
        if item is None:
            raise ValueError("failed to build uploaded image metadata")
        with self._lock:
            self._items.insert(0, item)
            self._save_items()
        return self._build_public_item(item)

    def list_items(self, auth_token: str, *, limit: int = 25, images_app_only: bool = False) -> list[dict[str, Any]]:
        owner_id = self.build_owner_id(auth_token)
        if not owner_id:
            return []
        normalized_limit = max(1, min(100, int(limit or 25)))
        with self._lock:
            filtered = [
                dict(item)
                for item in self._items
                if str(item.get("owner_id") or "") == owner_id
                and (not images_app_only or bool(item.get("images_app_only")))
            ]
        return [self._build_public_item(item) for item in filtered[:normalized_limit]]

    def get_item(self, file_id: str, auth_token: str | None = None) -> dict[str, Any] | None:
        normalized_file_id = self._clean_text(file_id)
        owner_id = self.build_owner_id(auth_token or "") if auth_token is not None else ""
        with self._lock:
            for item in self._items:
                if str(item.get("file_id") or "") != normalized_file_id:
                    continue
                if auth_token is not None and str(item.get("owner_id") or "") != owner_id:
                    return None
                return dict(item)
        return None

    def read_bytes(self, file_id: str, auth_token: str | None = None) -> tuple[bytes, dict[str, Any]] | None:
        item = self.get_item(file_id, auth_token)
        if item is None:
            return None
        stored_name = self._clean_text(item.get("stored_name"))
        if not stored_name:
            return None
        path = self.files_dir / stored_name
        if not path.exists():
            return None
        return path.read_bytes(), item


uploaded_image_service = UploadedImageService(
    store_file=DATA_DIR / "uploaded_images.json",
    files_dir=DATA_DIR / "uploaded_images",
)
