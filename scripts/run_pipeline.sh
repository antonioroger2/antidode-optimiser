#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=========================================================="
echo " Executing Data Preprocessing & Optimization Build Pipeline"
echo "=========================================================="
python3 preprocess/build_master.py
