#!/usr/bin/env bash
# ReleaseGraph platform + Acme Shop demo (Ctrl+C stops all child processes).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3

trap 'kill 0 2>/dev/null || true' EXIT INT TERM

echo "ReleaseGraph UI   → http://127.0.0.1:5173"
echo "ReleaseGraph API  → http://127.0.0.1:8000"
echo "Acme Shop         → http://127.0.0.1:8082"
echo ""

cd "$ROOT"
"$PY" demo/ecommerce/run_all.py &
"$PY" -m uvicorn releasegraph.main:app --reload --host 127.0.0.1 --port 8000 &
cd "$ROOT/web"
npm run dev -- --host 127.0.0.1 --port 5173 &
wait
