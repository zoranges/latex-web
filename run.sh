#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "创建虚拟环境 …"
    python3 -m venv .venv
    .venv/bin/pip install -q --upgrade pip
    .venv/bin/pip install -q -r requirements.txt
fi

PORT="${PORT:-8090}"
HOST="${HOST:-0.0.0.0}"

echo "LaTeX Web 启动: http://${HOST}:${PORT}"
exec .venv/bin/uvicorn app.main:app --app-dir "$(pwd)" --host "$HOST" --port "$PORT"