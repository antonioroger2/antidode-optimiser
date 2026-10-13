#!/bin/bash
# ==============================================================================
# DATASET ACQUISITION: WHO ARCGIS REST API EXTRACTION SCRIPT
# ==============================================================================
# Downloads official WHO snake species habitation vector polygons, master spatial
# metadata, and administrative boundary layers directly to data/ directory.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SPATIAL_DIR="${REPO_ROOT}/data/spatial"
RAW_DIR="${REPO_ROOT}/data/raw"

mkdir -p "${SPATIAL_DIR}" "${RAW_DIR}"

echo "=========================================================================="
echo " Starting WHO ArcGIS Raw Dataset Acquisition"
echo "=========================================================================="

echo "[1/4] Downloading WHO Snake Species Habitation Polygons (Layer 1)..."
curl -s -S -G "https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/SNBPROD_Views/FeatureServer/1/query" \
  --data-urlencode "where=1=1" \
  --data-urlencode "outFields=*" \
  --data-urlencode "outSR=4326" \
  --data-urlencode "f=geojson" \
  -o "${SPATIAL_DIR}/who_snake_species_habitation_polygons.geojson"
echo "  -> Saved: data/spatial/who_snake_species_habitation_polygons.geojson"

echo "[2/4] Downloading WHO Snake Species Master Spatial Layer (Layer 2)..."
curl -s -S -G "https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/SNBPROD_Views/FeatureServer/2/query" \
  --data-urlencode "where=1=1" \
  --data-urlencode "outFields=*" \
  --data-urlencode "outSR=4326" \
  --data-urlencode "f=geojson" \
  -o "${SPATIAL_DIR}/who_snake_species_master_spatial.geojson"
echo "  -> Saved: data/spatial/who_snake_species_master_spatial.geojson"

echo "[3/4] Downloading India ADM2 District Vector Boundaries..."
curl -s -S -G "https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/Detailed_Boundary_ADM2/FeatureServer/0/query" \
  --data-urlencode "where=ISO_3_CODE = 'IND'" \
  --data-urlencode "outFields=ADM2_NAME,ADM1_NAME,ISO_3_CODE,CENTER_LON,CENTER_LAT,ADM2_VIZ_NAME,ADM1_VIZ_NAME,Shape__Area,Shape__Length" \
  --data-urlencode "outSR=4326" \
  --data-urlencode "f=geojson" \
  -o "${SPATIAL_DIR}/who_india_adm2_district_polygons.geojson"
echo "  -> Saved: data/spatial/who_india_adm2_district_polygons.geojson"

echo "[4/4] Downloading WHO ADM0 Country Boundaries Table..."
curl -s -S -G "https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/Detailed_Boundary_ADM0/FeatureServer/0/query" \
  --data-urlencode "where=1=1" \
  --data-urlencode "outFields=OBJECTID,WHO_REGION,ISO_2_CODE,ADM0_NAME,ADM0_CODE,ISO_3_CODE,WHO_CODE,CENTER_LON,CENTER_LAT,Shape__Area" \
  --data-urlencode "outSR=4326" \
  --data-urlencode "f=json" \
  -o "${RAW_DIR}/who_detailed_boundary_adm0_countries.json"
echo "  -> Saved: data/raw/who_detailed_boundary_adm0_countries.json"

echo "=========================================================================="
echo "[SUCCESS] All raw datasets acquired successfully!"
echo "=========================================================================="
