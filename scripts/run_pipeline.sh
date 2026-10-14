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
echo " Executing Data Preprocessing & Optimization Build Pipeline"
echo "=========================================================="
"${PYTHON}" preprocess/build_master.py
