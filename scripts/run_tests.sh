#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=========================================================="
echo " Running Antidote Optimizer Test Suites"
echo "=========================================================="

echo "[1/2] Preprocessing & Dataset Schema Integrity Tests..."
python3 tests/test_preprocessing.py

echo "[2/2] Operations Research & Flask API Tests..."
python3 tests/test_optimization.py

echo "=========================================================="
echo "[SUCCESS] All tests passed cleanly!"
echo "=========================================================="
