from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.account_service import account_service
from services.image_service import ImageGenerationError, generate_image_result, is_token_invalid_error


OUTPUT_DIR = ROOT_DIR / "data" / "output"


def detect_ext(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return ".webp"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return ".gif"
    return ".png"


def save_image(image_b64: str, index: int) -> Path:
    image_bytes = base64.b64decode(image_b64)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"image_{index}_{int(time.time())}{detect_ext(image_bytes)}"
    path.write_bytes(image_bytes)
    return path


def generate_image_direct(prompt: str, model: str = "gpt-5-3", n: int = 1) -> dict:
    tokens = account_service.list_tokens()
    if not tokens:
        raise ImageGenerationError(f"No tokens found in {account_service.store_file}")

    last_error: Exception | None = None
    for index, token in enumerate(tokens, start=1):
        try:
            print(f"try token {index}/{len(tokens)}")
            return generate_image_result(token, prompt, model, n)
        except ImageGenerationError as exc:
            last_error = exc
            if is_token_invalid_error(str(exc)):
                account_service.remove_token(token)
                print(f"skip invalid token {index}/{len(tokens)}")
                continue
            raise

    if last_error is not None:
        raise last_error
    raise ImageGenerationError("No usable token")


def main() -> int:
    prompt = " ".join(sys.argv[1:]).strip()
    if not prompt:
        prompt = "一只橘猫坐在窗台上，午后阳光，写实摄影"

    print(f"prompt: {prompt}")
    try:
        print("request: direct image_service")
        data = generate_image_direct(prompt)
    except ImageGenerationError as exc:
        print(f"image generation error: {exc}")
        return 1

    items = data.get("data") or []
    if not items:
        print("error: response data is empty")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 1

    saved = []
    for index, item in enumerate(items, start=1):
        image_b64 = str((item or {}).get("b64_json") or "").strip()
        if not image_b64:
            continue
        path = save_image(image_b64, index)
        saved.append(path)
        print(f"saved: {path}")

    if not saved:
        print("error: no b64_json returned")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
