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
echo " Running Antidote Optimizer Test Suites"
echo "=========================================================="

echo "[1/2] Preprocessing & Dataset Schema Integrity Tests..."
"${PYTHON}" tests/test_preprocessing.py

echo "[2/2] Operations Research & Flask API Tests..."
"${PYTHON}" tests/test_optimization.py

echo "=========================================================="
echo "[SUCCESS] All tests passed cleanly!"
echo "=========================================================="
