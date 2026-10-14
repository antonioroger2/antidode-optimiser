#!/bin/bash
set -euo pipefail

# Always navigate to repo root
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# Detect python binary
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif [ -f "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
else
    PYTHON="python3"
fi

echo "=========================================================="
echo " Starting Antidote & Antivenom Logistics Optimizer Web UI"
echo "=========================================================="

PORT="${PORT:-8080}"
echo "[*] Launching server on http://127.0.0.1:${PORT}"
exec "${PYTHON}" optimise/app.py
