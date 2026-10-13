#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=========================================================="
echo " Starting Antidote & Antivenom Logistics Optimizer Web UI"
echo "=========================================================="

PORT="${PORT:-8080}"
echo "[*] Launching server on http://127.0.0.1:${PORT}"
exec python3 optimise/app.py
