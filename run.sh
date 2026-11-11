#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

CONDA_ENV_PY="/home/redo/miniconda3/envs/pdf-toolkit/bin/python"

if [ ! -f "$CONDA_ENV_PY" ]; then
    echo "El entorno conda pdf-toolkit no fue encontrado en $CONDA_ENV_PY"
    echo "Intentando activar via conda..."
    eval "$(/home/redo/miniconda3/bin/conda shell.bash hook 2>/dev/null || true)"
    conda activate pdf-toolkit 2>/dev/null || true
    PYTHON_CMD="python"
else
    PYTHON_CMD="$CONDA_ENV_PY"
fi

# Asegurar presencia de ebooklib
"$PYTHON_CMD" -c "import ebooklib" >/dev/null 2>&1 || "$PYTHON_CMD" -m pip install --quiet ebooklib

is_port_in_use() {
    "$PYTHON_CMD" -c "import socket, sys; s = socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1', int(sys.argv[1]))) == 0 else 1)" "$1" 2>/dev/null
}

PORT="${PORT:-8004}"
while is_port_in_use "$PORT"; do
    echo "Puerto $PORT ocupado, probando siguiente..."
    PORT=$((PORT+1))
done

echo "=========================================================="
echo " Kindle Toolbox iniciado exitosamente con Miniconda"
echo " Interfaz Web: http://127.0.0.1:$PORT"
echo "=========================================================="

exec "$PYTHON_CMD" -m uvicorn app:app --host 127.0.0.1 --port "$PORT"
