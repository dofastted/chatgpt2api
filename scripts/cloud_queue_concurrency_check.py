from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import statistics
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


MODEL_DISTRIBUTION = (
    ("gpt-image-2", "responses", 5),
    ("gpt-image-2", "images", 5),
    ("gpt-image-2-2K", "responses", 3),
    ("gpt-image-2-2K", "images", 3),
    ("gpt-image-2-4K", "responses", 2),
    ("gpt-image-2-4K", "images", 2),
)
EXPECTED_UNIT_COST = {
    "gpt-image-2": 2,
    "gpt-image-2-2K": 2,
    "gpt-image-2-4K": 8,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a 20-request mixed queue check against chatgpt2api.")
    parser.add_argument("--base-url", default="https://img.fkcodex.com")
    parser.add_argument("--key-a", default=os.getenv("CLOUD_QUEUE_KEY_A"), help="First user key, receives 10 requests")
    parser.add_argument("--key-b", default=os.getenv("CLOUD_QUEUE_KEY_B"), help="Second user key, receives 10 requests")
    parser.add_argument("--save-dir", default=".llmdoc-tmp/cloud-queue-checks")
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args()
    if not str(args.key_a or "").strip() or not str(args.key_b or "").strip():
        raise SystemExit("missing --key-a/--key-b or CLOUD_QUEUE_KEY_A/CLOUD_QUEUE_KEY_B")
    return args


def request_json(
    method: str,
    url: str,
    *,
    auth_key: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8") if body is not None else None
    merged_headers = {
        "Authorization": f"Bearer {auth_key}",
        "Content-Type": "application/json",
        "User-Agent": "curl/8.5.0",
        **(headers or {}),
    }
    request = Request(url, data=data, headers=merged_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return int(getattr(response, "status", 200)), json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {"error": raw.decode("utf-8", errors="replace")}
        return int(exc.code), payload
    except URLError as exc:
        return 0, {"error": f"request failed: {exc}"}


def build_requests(key_a: str, key_b: str) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    sequence = 0
    for model, protocol, count in MODEL_DISTRIBUTION:
        for _ in range(count):
            sequence += 1
            auth_key = key_a if sequence % 2 == 1 else key_b
            requests.append(
                {
                    "index": sequence,
                    "model": model,
                    "protocol": protocol,
                    "auth_key": auth_key,
                    "request_id": f"cloud-q-{sequence:02d}-{uuid.uuid4().hex[:10]}",
                    "prompt": f"queue validation image {sequence:02d}, simple blue square, model {model}",
                }
            )
    return requests


def run_generation(base_url: str, item: dict[str, Any], timeout: int) -> dict[str, Any]:
    started_at = time.time()
    headers = {"X-Image-Queue-Request-Id": item["request_id"]}
    if item["protocol"] == "responses":
        body = {
            "model": "gpt-5",
            "input": [{"type": "input_text", "text": item["prompt"]}],
            "tools": [{"type": "image_generation", "model": item["model"]}],
            "n": 1,
            "stream": False,
        }
        path = "/v1/responses"
    else:
        body = {
            "prompt": item["prompt"],
            "model": item["model"],
            "n": 1,
            "response_format": "b64_json",
            "stream": False,
        }
        path = "/v1/images/generations"
    status, payload = request_json(
        "POST",
        f"{base_url.rstrip('/')}{path}",
        auth_key=item["auth_key"],
        body=body,
        headers=headers,
        timeout=timeout,
    )
    elapsed = time.time() - started_at
    billing = payload.get("billing") if isinstance(payload, dict) else None
    if not isinstance(billing, dict) and item["protocol"] == "responses":
        billing = payload.get("billing") if isinstance(payload, dict) else None
    return {
        **{key: value for key, value in item.items() if key != "auth_key"},
        "http_status": status,
        "elapsed_seconds": round(elapsed, 2),
        "billing": billing if isinstance(billing, dict) else None,
        "expected_unit_cost": EXPECTED_UNIT_COST[item["model"]],
        "error": extract_error(payload) if status != 200 else None,
    }


def extract_error(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return str(payload)
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return str(detail.get("error") or detail)
    if detail:
        return str(detail)
    return str(payload.get("error") or payload.get("message") or "") or None


def poll_queue(
    base_url: str,
    requests: list[dict[str, Any]],
    done: threading.Event,
    poll_interval: float,
    timeout: int,
    snapshots: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if snapshots is None:
        snapshots = []
    started_at = time.time()
    while not done.is_set() and time.time() - started_at < timeout:
        for item in requests:
            query = urlencode({"request_id": item["request_id"]})
            try:
                status, payload = request_json(
                    "GET",
                    f"{base_url.rstrip('/')}/api/image-queue/me?{query}",
                    auth_key=item["auth_key"],
                    timeout=30,
                )
            except Exception as exc:
                status, payload = 0, {"error": str(exc)}
            snapshots.append(
                {
                    "at_seconds": round(time.time() - started_at, 2),
                    "request_id": item["request_id"],
                    "protocol": item["protocol"],
                    "model": item["model"],
                    "http_status": status,
                    "user": payload.get("user") if isinstance(payload, dict) else None,
                    "global": payload.get("global") if isinstance(payload, dict) else None,
                    "request": payload.get("request") if isinstance(payload, dict) else None,
                }
            )
        time.sleep(max(0.2, poll_interval))
    return snapshots


def summarize(results: list[dict[str, Any]], queue_snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed_values = [float(item["elapsed_seconds"]) for item in results]
    successful = [item for item in results if item["http_status"] == 200]
    failed = [item for item in results if item["http_status"] != 200]
    max_global_waiting = max(
        [int((item.get("global") or {}).get("waiting") or 0) for item in queue_snapshots] or [0]
    )
    max_global_running = max(
        [int((item.get("global") or {}).get("running") or 0) for item in queue_snapshots] or [0]
    )
    max_user_waiting = max(
        [int((item.get("user") or {}).get("waiting") or 0) for item in queue_snapshots] or [0]
    )
    billing_by_model: dict[str, dict[str, int]] = {}
    unit_cost_mismatches: list[dict[str, Any]] = []
    for item in successful:
        model = str(item["model"])
        billing = item.get("billing") or {}
        unit_cost = int(billing.get("unit_cost") or 0) if isinstance(billing, dict) else 0
        charged = int(billing.get("charged_quota") or 0) if isinstance(billing, dict) else 0
        bucket = billing_by_model.setdefault(model, {"count": 0, "charged_quota": 0})
        bucket["count"] += 1
        bucket["charged_quota"] += charged
        if unit_cost != int(item["expected_unit_cost"]):
            unit_cost_mismatches.append(
                {
                    "request_id": item["request_id"],
                    "model": model,
                    "expected": item["expected_unit_cost"],
                    "actual": unit_cost,
                }
            )
    final_queue = queue_snapshots[-1] if queue_snapshots else None
    return {
        "total": len(results),
        "success": len(successful),
        "failed": len(failed),
        "avg_elapsed_seconds": round(statistics.mean(elapsed_values), 2) if elapsed_values else 0,
        "p95_elapsed_seconds": round(statistics.quantiles(elapsed_values, n=20)[18], 2)
        if len(elapsed_values) >= 20
        else (round(max(elapsed_values), 2) if elapsed_values else 0),
        "billing_by_model": billing_by_model,
        "unit_cost_mismatches": unit_cost_mismatches,
        "max_global_waiting": max_global_waiting,
        "max_global_running": max_global_running,
        "max_user_waiting": max_user_waiting,
        "final_queue": final_queue,
        "failures": failed,
    }


def main() -> int:
    args = parse_args()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    save_root = Path(args.save_dir) / run_id
    save_root.mkdir(parents=True, exist_ok=True)
    requests = build_requests(args.key_a, args.key_b)
    done = threading.Event()
    queue_result: list[dict[str, Any]] = []
    poller = threading.Thread(
        target=lambda: poll_queue(args.base_url, requests, done, args.poll_interval, args.timeout, queue_result),
        daemon=True,
    )
    poller.start()
    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        futures = [executor.submit(run_generation, args.base_url, item, args.timeout) for item in requests]
        results = [future.result() for future in as_completed(futures)]
    done.set()
    poller.join(timeout=10)
    results.sort(key=lambda item: int(item["index"]))
    report = {
        "base_url": args.base_url,
        "run_id": run_id,
        "distribution": MODEL_DISTRIBUTION,
        "summary": summarize(results, queue_result),
        "results": results,
        "queue_snapshots": queue_result,
    }
    report_path = save_root / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "summary": report["summary"]}, ensure_ascii=False))
    return 0 if not report["summary"]["unit_cost_mismatches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
