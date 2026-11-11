#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

CONDA_ENV_PY="${KINDLE_TOOLBOX_PYTHON:-$HOME/miniconda3/envs/pdf-toolkit/bin/python}"

if [ -x "$CONDA_ENV_PY" ]; then
    PYTHON_CMD="$CONDA_ENV_PY"
elif [ -x ".venv/bin/python" ]; then
    PYTHON_CMD=".venv/bin/python"
elif [ -x "venv/bin/python" ]; then
    PYTHON_CMD="venv/bin/python"
else
    if command -v conda >/dev/null 2>&1; then
        eval "$(conda shell.bash hook 2>/dev/null || true)"
        conda activate pdf-toolkit 2>/dev/null || true
    fi
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD="python3"
    else
        PYTHON_CMD="python"
    fi
fi

# Ensure ebooklib is installed
"$PYTHON_CMD" -c "import ebooklib" >/dev/null 2>&1 || "$PYTHON_CMD" -m pip install --quiet ebooklib

is_port_in_use() {
    "$PYTHON_CMD" -c "import socket, sys; s = socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1', int(sys.argv[1]))) == 0 else 1)" "$1" 2>/dev/null
}

PORT="${PORT:-8004}"
while is_port_in_use "$PORT"; do
    echo "Port $PORT is in use, trying next..."
    PORT=$((PORT+1))
done

echo "=========================================================="
echo " Kindle Toolbox started successfully"
echo " Python: $PYTHON_CMD"
echo " Web Interface: http://127.0.0.1:$PORT"
echo "=========================================================="

exec "$PYTHON_CMD" -m uvicorn app:app --host 127.0.0.1 --port "$PORT"
