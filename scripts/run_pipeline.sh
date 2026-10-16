#!/bin/bash
# Rebuild every processed input from data/raw, data/spatial and data/external.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=${PYTHON:-python3}
$PY preprocess/presence.py      # districts.csv, district_species.csv, species.csv
$PY preprocess/antivenom.py     # antivenom_products.csv
$PY preprocess/population.py    # district_population.csv (WorldPop > Census IND > GeoNames provisional)
