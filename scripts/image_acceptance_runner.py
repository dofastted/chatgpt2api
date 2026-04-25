from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_TEXT_PROMPT = "生成一个清晰的 ABC 三视图展示板，画面里要有 A、B、C 三个角色视图区域，适合后续继续改色。"
DEFAULT_IMAGE_PROMPT = "基于这张已生成的 ABC 三视图，保持同一构图和主体，只把主色改成红色和黑色，仍然输出清晰的视图展示板。"
DEFAULT_SAVE_DIR = ".llmdoc-tmp/image-acceptance"
DEFAULT_RESPONSES_PATH = "/v1/responses"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="chatgpt2api 图片生成逐步验收脚本")
    parser.add_argument(
        "--step",
        required=True,
        choices=(
            "text_generate",
            "upload_generated_text_result",
            "image_generate",
            "summarize",
        ),
    )
    parser.add_argument("--base-url")
    parser.add_argument("--auth-key")
    parser.add_argument("--input-image")
    parser.add_argument("--run-id")
    parser.add_argument("--save-dir", default=DEFAULT_SAVE_DIR)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--text-prompt", default=DEFAULT_TEXT_PROMPT)
    parser.add_argument("--image-prompt", default=DEFAULT_IMAGE_PROMPT)
    parser.add_argument("--client-conversation-id")
    parser.add_argument("--file-id")
    parser.add_argument("--responses-path", default=DEFAULT_RESPONSES_PATH)
    return parser.parse_args()


def ensure_required_runtime_args(args: argparse.Namespace) -> None:
    if args.step == "summarize":
        return
    missing = []
    if not str(args.base_url or "").strip():
        missing.append("--base-url")
    if not str(args.auth_key or "").strip():
        missing.append("--auth-key")
    if missing:
        raise SystemExit(f"missing required args: {', '.join(missing)}")


def make_run_id(args: argparse.Namespace) -> str:
    return str(args.run_id or "").strip() or time.strftime("%Y%m%d-%H%M%S")


def get_run_root(args: argparse.Namespace) -> Path:
    return Path(args.save_dir).expanduser() / make_run_id(args)


def make_client_conversation_id(args: argparse.Namespace) -> str:
    return str(args.client_conversation_id or "").strip() or f"conv-{make_run_id(args)}"


def responses_url(args: argparse.Namespace) -> str:
    path = str(args.responses_path or DEFAULT_RESPONSES_PATH).strip() or DEFAULT_RESPONSES_PATH
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{args.base_url.rstrip('/')}{path}"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def print_key_values(title: str, payload: dict[str, Any]) -> None:
    print(f"[{title}]")
    for key, value in payload.items():
        if value is None:
            continue
        print(f"{key}={value}")


def make_request(
    method: str,
    url: str,
    *,
    auth_key: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> tuple[int, bytes]:
    merged_headers = {
        "Authorization": f"Bearer {auth_key}",
        **(headers or {}),
    }
    request = Request(url, data=body, headers=merged_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(getattr(response, "status", 200)), response.read()
    except HTTPError as exc:
        return int(exc.code), exc.read()
    except URLError as exc:
        raise RuntimeError(f"request failed: {exc}") from exc


def maybe_decode_json(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8"))


def save_base64_image(image_b64: str, save_path: Path) -> None:
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(base64.b64decode(image_b64))


def guess_image_dimensions(image_path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image  # type: ignore

        with Image.open(image_path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return None, None


def run_ocr_if_available(image_path: Path) -> tuple[str | None, str]:
    tesseract = shutil_which("tesseract")
    if not tesseract:
        return None, "未执行 OCR: 未找到 tesseract"
    result = subprocess.run(
        [tesseract, str(image_path), "stdout", "-l", "eng+chi_sim"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None, f"未执行 OCR: tesseract 返回 {result.returncode}: {(result.stderr or '').strip()}"
    return (result.stdout or "").strip(), "OCR 完成"


def shutil_which(binary: str) -> str | None:
    for base in os.environ.get("PATH", "").split(os.pathsep):
        if not base:
            continue
        candidate = Path(base) / binary
        if candidate.exists():
            return str(candidate)
    return None


def poll_queue(
    *,
    base_url: str,
    auth_key: str,
    request_id: str,
    timeout: int,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    started = time.time()
    while time.time() - started < timeout:
        query = urlencode({"request_id": request_id})
        status, raw = make_request(
            "GET",
            f"{base_url.rstrip('/')}/api/image-queue/me?{query}",
            auth_key=auth_key,
            timeout=20,
        )
        payload = maybe_decode_json(raw)
        snapshots.append(
            {
                "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "http_status": status,
                "request": payload.get("request"),
                "user": payload.get("user"),
                "global": payload.get("global"),
            }
        )
        item = payload.get("request") or {}
        if item.get("status") in {"finished", "failed"}:
            return snapshots
        time.sleep(1.5)
    return snapshots


def write_step_result(step_dir: Path, result: dict[str, Any]) -> Path:
    result_path = step_dir / "result.json"
    write_json(result_path, result)
    return result_path


def run_text_generate(args: argparse.Namespace) -> int:
    run_root = get_run_root(args)
    step_dir = run_root / "01_text_generate"
    request_id = f"queue-text-{uuid.uuid4().hex}"
    client_conversation_id = make_client_conversation_id(args)
    started_at = time.time()
    body = {
        "model": "gpt-5",
        "input": [{"type": "input_text", "text": args.text_prompt}],
        "tools": [{"type": "image_generation", "model": "gpt-image-2"}],
        "n": 1,
        "metadata": {"client_conversation_id": client_conversation_id},
    }
    write_json(step_dir / "request.json", body)
    status, raw = make_request(
        "POST",
        responses_url(args),
        auth_key=args.auth_key,
        body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Image-Queue-Request-Id": request_id,
        },
        timeout=args.timeout,
    )
    response_payload = maybe_decode_json(raw)
    write_json(step_dir / "response.json", response_payload)
    queue_snapshots = poll_queue(
        base_url=args.base_url,
        auth_key=args.auth_key,
        request_id=request_id,
        timeout=args.timeout,
    )
    write_json(step_dir / "queue.json", queue_snapshots)
    output = response_payload.get("output") or []
    image_items = [
        item for item in output if item.get("type") == "image_generation_call" and str(item.get("result") or "").strip()
    ]
    image_path = step_dir / "result.png"
    ocr_text = None
    ocr_detail = "未执行 OCR"
    ok = status == 200 and len(image_items) == 1
    if image_items:
        save_base64_image(str(image_items[0]["result"]), image_path)
        ocr_text, ocr_detail = run_ocr_if_available(image_path)
        ok = ok and image_path.exists() and image_path.stat().st_size > 0
    width, height = guess_image_dimensions(image_path) if image_path.exists() else (None, None)
    result = {
        "step": "text_generate",
        "ok": ok,
        "elapsed_seconds": round(time.time() - started_at, 2),
        "base_url": args.base_url,
        "request_id": request_id,
        "http_status": status,
        "prompt": args.text_prompt,
        "client_conversation_id": client_conversation_id,
        "conversation_id": response_payload.get("conversation_id"),
        "billing": response_payload.get("billing"),
        "retry": response_payload.get("retry"),
        "output_count": len(image_items),
        "generated_image_path": str(image_path) if image_path.exists() else None,
        "width": width,
        "height": height,
        "ocr_text": ocr_text,
        "ocr_detail": ocr_detail,
        "queue_last_status": (queue_snapshots[-1].get("request") or {}).get("status") if queue_snapshots else None,
        "files": {
            "request": str(step_dir / "request.json"),
            "response": str(step_dir / "response.json"),
            "queue": str(step_dir / "queue.json"),
            "image": str(image_path) if image_path.exists() else None,
        },
    }
    result_path = write_step_result(step_dir, result)
    print_key_values(
        "text_generate",
        {
            "run_id": make_run_id(args),
            "result_path": str(result_path),
            "request_id": request_id,
            "http_status": status,
            "client_conversation_id": client_conversation_id,
            "conversation_id": result["conversation_id"],
            "output_count": result["output_count"],
            "elapsed_seconds": result["elapsed_seconds"],
            "width": width,
            "height": height,
            "queue_last_status": result["queue_last_status"],
            "ocr_detail": ocr_detail,
            "ok": ok,
        },
    )
    return 0 if ok else 1


def upload_input_image(args: argparse.Namespace, step_dir: Path) -> tuple[int, dict[str, Any], str]:
    input_path = Path(str(args.input_image or "")).expanduser()
    if not input_path.exists():
        raise FileNotFoundError(f"input image not found: {input_path}")
    boundary = f"----chatgpt2api{uuid.uuid4().hex}"
    mime_type = mimetypes.guess_type(str(input_path))[0] or "application/octet-stream"
    client_conversation_id = str(args.client_conversation_id or "").strip() or f"conv-upload-{uuid.uuid4().hex}"
    file_bytes = input_path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="client_conversation_id"\r\n\r\n'
        f"{client_conversation_id}\r\n"
    ).encode("utf-8")
    upstream_conversation_id = str(getattr(args, "upstream_conversation_id", "") or "").strip()
    if upstream_conversation_id:
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="upstream_conversation_id"\r\n\r\n'
            f"{upstream_conversation_id}\r\n"
        ).encode("utf-8")
    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{input_path.name}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    status, raw = make_request(
        "POST",
        f"{args.base_url.rstrip('/')}/backend-api/files/process_upload_stream",
        auth_key=args.auth_key,
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout=args.timeout,
    )
    payload = maybe_decode_json(raw)
    write_json(step_dir / "response.json", payload)
    return status, payload, client_conversation_id


def resolve_upload_source(args: argparse.Namespace) -> tuple[Path, str]:
    if str(args.input_image or "").strip():
        return Path(str(args.input_image)).expanduser(), str(args.client_conversation_id or "").strip()
    text_result_path = get_run_root(args) / "01_text_generate" / "result.json"
    if not text_result_path.exists():
        raise SystemExit("missing text result, run --step text_generate first or pass --input-image")
    text_result = read_json(text_result_path)
    image_path = Path(str(text_result.get("generated_image_path") or "")).expanduser()
    if not image_path.exists():
        raise SystemExit("text_generate result image not found")
    client_conversation_id = str(
        args.client_conversation_id
        or text_result.get("client_conversation_id")
        or text_result.get("conversation_id")
        or ""
    ).strip()
    if not client_conversation_id:
        raise SystemExit("missing conversation id for generated image upload")
    return image_path, client_conversation_id


def run_upload_generated_text_result(args: argparse.Namespace) -> int:
    input_path, client_conversation_id = resolve_upload_source(args)
    upstream_conversation_id = resolve_upstream_conversation_id(args)
    run_root = get_run_root(args)
    step_dir = run_root / "02_upload_generated_text_result"
    started_at = time.time()
    upload_args = argparse.Namespace(**vars(args))
    upload_args.input_image = str(input_path)
    upload_args.client_conversation_id = client_conversation_id
    upload_args.upstream_conversation_id = upstream_conversation_id
    status, payload, client_conversation_id = upload_input_image(upload_args, step_dir)
    file_id = str(payload.get("file_id") or "").strip()
    ok = status == 200 and bool(file_id)
    result = {
        "step": "upload_generated_text_result",
        "ok": ok,
        "elapsed_seconds": round(time.time() - started_at, 2),
        "base_url": args.base_url,
        "http_status": status,
        "input_image": str(input_path),
        "file_id": file_id,
        "client_conversation_id": client_conversation_id,
        "upstream_conversation_id": upstream_conversation_id or None,
        "width": payload.get("width"),
        "height": payload.get("height"),
        "size_bytes": payload.get("size_bytes"),
        "download_url": payload.get("download_url"),
        "files": {
            "response": str(step_dir / "response.json"),
        },
    }
    result_path = write_step_result(step_dir, result)
    print_key_values(
        "upload_generated_text_result",
        {
            "run_id": make_run_id(args),
            "result_path": str(result_path),
            "http_status": status,
            "file_id": file_id,
            "client_conversation_id": client_conversation_id,
            "upstream_conversation_id": upstream_conversation_id or None,
            "elapsed_seconds": result["elapsed_seconds"],
            "width": payload.get("width"),
            "height": payload.get("height"),
            "size_bytes": payload.get("size_bytes"),
            "ok": ok,
        },
    )
    return 0 if ok else 1


def resolve_image_generate_inputs(args: argparse.Namespace) -> tuple[str, str]:
    file_id = str(args.file_id or "").strip()
    client_conversation_id = str(args.client_conversation_id or "").strip()
    if file_id and client_conversation_id:
        return file_id, client_conversation_id
    upload_result_path = get_run_root(args) / "02_upload_generated_text_result" / "result.json"
    if not upload_result_path.exists():
        raise SystemExit("missing upload result, run --step upload_generated_text_result first or pass --file-id and --client-conversation-id")
    upload_result = read_json(upload_result_path)
    resolved_file_id = file_id or str(upload_result.get("file_id") or "").strip()
    resolved_conversation_id = client_conversation_id or str(upload_result.get("client_conversation_id") or "").strip()
    if not resolved_file_id or not resolved_conversation_id:
        raise SystemExit("upload result missing file_id or client_conversation_id")
    return resolved_file_id, resolved_conversation_id


def resolve_upstream_conversation_id(args: argparse.Namespace) -> str:
    text_result_path = get_run_root(args) / "01_text_generate" / "result.json"
    if not text_result_path.exists():
        return ""
    text_result = read_json(text_result_path)
    return str(text_result.get("conversation_id") or "").strip()


def run_image_generate(args: argparse.Namespace) -> int:
    file_id, client_conversation_id = resolve_image_generate_inputs(args)
    upstream_conversation_id = resolve_upstream_conversation_id(args)
    run_root = get_run_root(args)
    step_dir = run_root / "03_image_generate"
    request_id = f"queue-image-{uuid.uuid4().hex}"
    started_at = time.time()
    body = {
        "model": "gpt-5",
        "input": [
            {"type": "input_text", "text": args.image_prompt},
            {"type": "input_image", "file_id": file_id},
        ],
        "tools": [{"type": "image_generation", "model": "gpt-image-2"}],
        "n": 1,
        "metadata": {
            "client_conversation_id": client_conversation_id,
            **({"upstream_conversation_id": upstream_conversation_id} if upstream_conversation_id else {}),
        },
    }
    write_json(step_dir / "request.json", body)
    status, raw = make_request(
        "POST",
        responses_url(args),
        auth_key=args.auth_key,
        body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Image-Queue-Request-Id": request_id,
        },
        timeout=args.timeout,
    )
    response_payload = maybe_decode_json(raw)
    write_json(step_dir / "response.json", response_payload)
    queue_snapshots = poll_queue(
        base_url=args.base_url,
        auth_key=args.auth_key,
        request_id=request_id,
        timeout=args.timeout,
    )
    write_json(step_dir / "queue.json", queue_snapshots)
    output = response_payload.get("output") or []
    image_items = [
        item for item in output if item.get("type") == "image_generation_call" and str(item.get("result") or "").strip()
    ]
    image_path = step_dir / "result.png"
    ocr_text = None
    ocr_detail = "未执行 OCR"
    ok = status == 200 and len(image_items) == 1
    if image_items:
        save_base64_image(str(image_items[0]["result"]), image_path)
        ocr_text, ocr_detail = run_ocr_if_available(image_path)
        ok = ok and image_path.exists() and image_path.stat().st_size > 0
    width, height = guess_image_dimensions(image_path) if image_path.exists() else (None, None)
    result = {
        "step": "image_generate",
        "ok": ok,
        "elapsed_seconds": round(time.time() - started_at, 2),
        "base_url": args.base_url,
        "request_id": request_id,
        "http_status": status,
        "file_id": file_id,
        "client_conversation_id": client_conversation_id,
        "upstream_conversation_id": upstream_conversation_id,
        "prompt": args.image_prompt,
        "conversation_id": response_payload.get("conversation_id"),
        "billing": response_payload.get("billing"),
        "retry": response_payload.get("retry"),
        "output_count": len(image_items),
        "generated_image_path": str(image_path) if image_path.exists() else None,
        "width": width,
        "height": height,
        "ocr_text": ocr_text,
        "ocr_detail": ocr_detail,
        "queue_last_status": (queue_snapshots[-1].get("request") or {}).get("status") if queue_snapshots else None,
        "files": {
            "request": str(step_dir / "request.json"),
            "response": str(step_dir / "response.json"),
            "queue": str(step_dir / "queue.json"),
            "image": str(image_path) if image_path.exists() else None,
        },
    }
    result_path = write_step_result(step_dir, result)
    print_key_values(
        "image_generate",
        {
            "run_id": make_run_id(args),
            "result_path": str(result_path),
            "request_id": request_id,
            "file_id": file_id,
            "client_conversation_id": client_conversation_id,
            "upstream_conversation_id": upstream_conversation_id,
            "http_status": status,
            "conversation_id": result["conversation_id"],
            "output_count": result["output_count"],
            "elapsed_seconds": result["elapsed_seconds"],
            "width": width,
            "height": height,
            "queue_last_status": result["queue_last_status"],
            "ocr_detail": ocr_detail,
            "ok": ok,
        },
    )
    return 0 if ok else 1


def summarize_run(args: argparse.Namespace) -> int:
    run_root = get_run_root(args)
    step_files = [
        run_root / "01_text_generate" / "result.json",
        run_root / "02_upload_generated_text_result" / "result.json",
        run_root / "03_image_generate" / "result.json",
    ]
    items = [read_json(path) for path in step_files if path.exists()]
    if not items:
        raise SystemExit(f"no result files found under {run_root}")
    summary = {
        "run_id": make_run_id(args),
        "run_root": str(run_root),
        "ok": all(bool(item.get("ok")) for item in items),
        "steps": items,
    }
    summary_path = run_root / "summary.json"
    write_json(summary_path, summary)
    print_key_values(
        "summarize",
        {
            "run_id": make_run_id(args),
            "summary_path": str(summary_path),
            "step_count": len(items),
            "ok": summary["ok"],
        },
    )
    for item in items:
        print_key_values(
            f"step:{item.get('step')}",
            {
                "ok": item.get("ok"),
                "http_status": item.get("http_status"),
                "request_id": item.get("request_id"),
                "file_id": item.get("file_id"),
                "client_conversation_id": item.get("client_conversation_id"),
                "conversation_id": item.get("conversation_id"),
                "queue_last_status": item.get("queue_last_status"),
                "result_path": str(run_root / {
                    "text_generate": "01_text_generate/result.json",
                    "upload_generated_text_result": "02_upload_generated_text_result/result.json",
                    "image_generate": "03_image_generate/result.json",
                }.get(str(item.get("step")), "")),
            },
        )
    return 0 if summary["ok"] else 1


def main() -> int:
    args = parse_args()
    ensure_required_runtime_args(args)
    if args.step == "text_generate":
        return run_text_generate(args)
    if args.step == "upload_generated_text_result":
        return run_upload_generated_text_result(args)
    if args.step == "image_generate":
        return run_image_generate(args)
    if args.step == "summarize":
        return summarize_run(args)
    raise SystemExit(f"unsupported step: {args.step}")


if __name__ == "__main__":
    sys.exit(main())
