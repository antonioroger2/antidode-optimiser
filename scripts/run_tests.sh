#!/bin/bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
${PYTHON:-python3} -m pytest -q tests
