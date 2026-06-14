#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export NEXT_TELEMETRY_DISABLED=1
export CI=1

npm --prefix "$ROOT_DIR/web" run build
python3 "$ROOT_DIR/scripts/autoresearch_frontend_metrics.py" "$ROOT_DIR"
