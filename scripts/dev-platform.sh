#!/usr/bin/env bash
# Run ReleaseGraph API + Vite UI in one terminal (Ctrl+C stops both).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3

trap 'kill 0 2>/dev/null || true' EXIT INT TERM

echo "API  → http://127.0.0.1:8000"
echo "UI   → http://127.0.0.1:5173  (login admin@acme.demo / admin123!)"
echo "Shop → run separately: python demo/ecommerce/run_all.py → http://127.0.0.1:8082"
echo ""

cd "$ROOT"
"$PY" -m uvicorn releasegraph.main:app --reload --host 127.0.0.1 --port 8000 &
cd "$ROOT/web"
npm run dev -- --host 127.0.0.1 &
wait
