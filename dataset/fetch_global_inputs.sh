#!/bin/bash
# =============================================================================
# Fetch the free inputs that remove the PROVISIONAL population flag worldwide.
#   1. WHO ADM2 district polygons per country (WHO ArcGIS, paged)  -> data/spatial/adm2/<ISO3>.geojson
#   2. WorldPop 2020 1 km UN-adjusted population per country      -> data/external/worldpop/<iso3>.tif
# Then rebuild:  ./scripts/run_pipeline.sh
# Usage:  ./dataset/fetch_global_inputs.sh            (all countries in the presence table)
#         ./dataset/fetch_global_inputs.sh NGA BGD    (selected ISO3 codes)
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p data/spatial/adm2 data/external/worldpop

if [ $# -gt 0 ]; then
  CODES="$*"
else
  CODES=$(python3 -c "import pandas as pd; print(' '.join(sorted(pd.read_csv('data/processed/district_species.csv').district_id.str[:3].unique())))")
fi

ADM2="https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/Detailed_Boundary_ADM2/FeatureServer/0/query"
for ISO in $CODES; do
  LOW=$(echo "$ISO" | tr '[:upper:]' '[:lower:]')
  OUT="data/spatial/adm2/${ISO}.geojson"
  if [ ! -s "$OUT" ]; then
    echo "[ADM2] $ISO"
    python3 - "$ISO" "$OUT" "$ADM2" <<'PY'
import json, sys, requests
iso, out, url = sys.argv[1], sys.argv[2], sys.argv[3]
feats, offset = [], 0
while True:
    r = requests.get(url, params={"where": f"ISO_3_CODE='{iso}'", "outFields": "ADM2_NAME,ADM1_NAME,ISO_3_CODE",
                                  "outSR": 4326, "f": "geojson", "resultOffset": offset, "resultRecordCount": 200},
                     timeout=120)
    r.raise_for_status()
    js = r.json()
    batch = js.get("features", [])
    feats += batch
    if not batch or not js.get("properties", {}).get("exceededTransferLimit", len(batch) == 200):
        break
    offset += len(batch)
json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w"))
print(f"  {len(feats)} polygons")
PY
  fi
  TIF="data/external/worldpop/${LOW}.tif"
  if [ ! -s "$TIF" ]; then
    echo "[WorldPop] $ISO"
    curl -fsSL -o "$TIF" "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km_UNadj/2020/${ISO}/${LOW}_ppp_2020_1km_Aggregated_UNadj.tif" \
      || { echo "  WorldPop file not found for $ISO (skipped)"; rm -f "$TIF"; }
  fi
done
echo "Done. Now run ./scripts/run_pipeline.sh"
