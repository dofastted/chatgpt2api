#!/usr/bin/env python3
"""Deterministic frontend benchmark metrics for autoresearch.

The workload is the exported Next.js app after `npm run build`.  It measures
what a browser must receive for the main user-facing routes without calling any
live API or external network.
"""

from __future__ import annotations

import gzip
import html.parser
import json
import re
import sys
from pathlib import Path

ROUTES = ("/image", "/gallery", "/login", "/accounts")
PRIMARY_ROUTE = "/image"
EXPECTED_IMAGE_COPY = (
    "今天你想创造什么?",
    "画图",
    "画廊",
    "新建",
    "配置",
)


class VisibleTextParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "template", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


def html_file_for_route(out_dir: Path, route: str) -> Path:
    if route == "/":
        return out_dir / "index.html"
    return out_dir / f"{route.strip('/')}.html"


def normalize_asset_path(out_dir: Path, asset_path: str) -> Path:
    cleaned = asset_path.split("?", 1)[0]
    if cleaned.startswith(".next/"):
        cleaned = "_next/" + cleaned[len(".next/") :]
    cleaned = cleaned.lstrip("/")
    return out_dir / cleaned


def gzip_len(data: bytes) -> int:
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def read_route_stats(root: Path) -> dict[str, dict[str, object]]:
    stats_path = root / "web" / ".next" / "diagnostics" / "route-bundle-stats.json"
    if not stats_path.exists():
        raise FileNotFoundError(f"missing Next route bundle stats: {stats_path}")
    data = json.loads(stats_path.read_text(encoding="utf-8"))
    return {item["route"]: item for item in data}


def collect_html_assets(html: str) -> set[str]:
    assets: set[str] = set()
    for match in re.finditer(r'<link[^>]+href="([^"]+)"[^>]*>', html):
        tag = match.group(0)
        if 'rel="stylesheet"' in tag or 'as="font"' in tag:
            assets.add(match.group(1))
    for match in re.finditer(r'<script[^>]+src="([^"]+)"', html):
        assets.add(match.group(1))
    return assets


def visible_text(html: str) -> str:
    parser = VisibleTextParser()
    parser.feed(html)
    return " ".join(parser.parts)


def route_payload(root: Path, route: str, stats: dict[str, dict[str, object]]) -> dict[str, float]:
    out_dir = root / "web" / "out"
    html_path = html_file_for_route(out_dir, route)
    if not html_path.exists():
        raise FileNotFoundError(f"missing exported route html: {html_path}")

    html_bytes = html_path.read_bytes()
    route_stat = stats.get(route)
    if route_stat is None:
        raise KeyError(f"missing route bundle stats for {route}")

    asset_paths = set(collect_html_assets(html_bytes.decode("utf-8", errors="replace")))
    for chunk_path in route_stat.get("firstLoadChunkPaths", []):
        if not isinstance(chunk_path, str):
            continue
        asset_paths.add(chunk_path)

    asset_files = [normalize_asset_path(out_dir, asset) for asset in asset_paths]
    missing = [str(path) for path in asset_files if not path.exists()]
    if missing:
        raise FileNotFoundError("missing route assets: " + ", ".join(sorted(missing)))

    asset_bytes = sum(path.stat().st_size for path in asset_files)
    asset_gzip_bytes = sum(gzip_len(path.read_bytes()) for path in asset_files)
    html_gzip_bytes = gzip_len(html_bytes)
    return {
        "payload_kb": (asset_gzip_bytes + html_gzip_bytes) / 1024,
        "html_kb": len(html_bytes) / 1024,
        "html_gzip_kb": html_gzip_bytes / 1024,
        "asset_raw_kb": asset_bytes / 1024,
        "asset_gzip_kb": asset_gzip_bytes / 1024,
        "js_uncompressed_kb": float(route_stat["firstLoadUncompressedJsBytes"]) / 1024,
        "asset_count": float(len(asset_files)),
    }


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    stats = read_route_stats(root)
    route_metrics = {route: route_payload(root, route, stats) for route in ROUTES}

    image_html = html_file_for_route(root / "web" / "out", PRIMARY_ROUTE).read_text(
        encoding="utf-8",
        errors="replace",
    )
    text = visible_text(image_html)
    compact_text = "".join(text.split())
    copy_hits = sum(1 for item in EXPECTED_IMAGE_COPY if item in text)

    primary = route_metrics[PRIMARY_ROUTE]["payload_kb"]
    print(f"METRIC image_route_payload_kb={primary:.3f}")
    print(f"METRIC image_route_js_uncompressed_kb={route_metrics[PRIMARY_ROUTE]['js_uncompressed_kb']:.3f}")
    print(f"METRIC image_route_html_kb={route_metrics[PRIMARY_ROUTE]['html_kb']:.3f}")
    print(f"METRIC image_route_asset_count={route_metrics[PRIMARY_ROUTE]['asset_count']:.0f}")
    print(f"METRIC gallery_route_payload_kb={route_metrics['/gallery']['payload_kb']:.3f}")
    print(f"METRIC login_route_payload_kb={route_metrics['/login']['payload_kb']:.3f}")
    print(f"METRIC accounts_route_payload_kb={route_metrics['/accounts']['payload_kb']:.3f}")
    print(f"METRIC image_page_visible_text_chars={len(compact_text)}")
    print(f"METRIC image_page_key_copy_score={copy_hits / len(EXPECTED_IMAGE_COPY):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
