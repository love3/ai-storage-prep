#!/usr/bin/env bash
# KV cache offload simulator -- one-shot demo (Linux + macOS).
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}

echo "== 1) strategy comparison (no deps needed) =="
$PY cli.py --requests 400

echo
echo "== 2) prefetch sweep (overlap hides SSD latency) =="
$PY cli.py --requests 300 --sweep-prefetch | tail -n 9

echo
echo "== 3) FP8 KV cache (smaller blocks) =="
$PY cli.py --requests 400 --kv-bytes 1 | grep -E "block=|avg re-ref|recompute" | head -n 8

echo
echo "To run the API:  pip install -r requirements.txt && uvicorn app:app --reload"
