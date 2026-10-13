#!/usr/bin/env python3
"""
================================================================================
DATASET ACQUISITION: WHO ArcGIS REST API Python Extractor
================================================================================
"""

import os
import json
import requests
from typing import Dict, Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPATIAL_DIR = os.path.join(REPO_ROOT, 'data', 'spatial')
RAW_DIR = os.path.join(REPO_ROOT, 'data', 'raw')

ENDPOINTS = [
    {
        'name': 'WHO Snake Species Habitation Polygons',
        'url': 'https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/SNBPROD_Views/FeatureServer/1/query',
        'params': {'where': '1=1', 'outFields': '*', 'outSR': '4326', 'f': 'geojson'},
        'dest': os.path.join(SPATIAL_DIR, 'who_snake_species_habitation_polygons.geojson')
    },
    {
        'name': 'WHO Snake Species Master Spatial Layer',
        'url': 'https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/SNBPROD_Views/FeatureServer/2/query',
        'params': {'where': '1=1', 'outFields': '*', 'outSR': '4326', 'f': 'geojson'},
        'dest': os.path.join(SPATIAL_DIR, 'who_snake_species_master_spatial.geojson')
    },
    {
        'name': 'India ADM2 District Boundaries',
        'url': 'https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/Detailed_Boundary_ADM2/FeatureServer/0/query',
        'params': {
            'where': "ISO_3_CODE = 'IND'",
            'outFields': 'ADM2_NAME,ADM1_NAME,ISO_3_CODE,CENTER_LON,CENTER_LAT,ADM2_VIZ_NAME,ADM1_VIZ_NAME,Shape__Area,Shape__Length',
            'outSR': '4326',
            'f': 'geojson'
        },
        'dest': os.path.join(SPATIAL_DIR, 'who_india_adm2_district_polygons.geojson')
    },
    {
        'name': 'WHO ADM0 Country Boundaries Layer',
        'url': 'https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/Detailed_Boundary_ADM0/FeatureServer/0/query',
        'params': {
            'where': '1=1',
            'outFields': 'OBJECTID,WHO_REGION,ISO_2_CODE,ADM0_NAME,ADM0_CODE,ISO_3_CODE,WHO_CODE,CENTER_LON,CENTER_LAT,Shape__Area',
            'outSR': '4326',
            'f': 'json'
        },
        'dest': os.path.join(RAW_DIR, 'who_detailed_boundary_adm0_countries.json')
    }
]


def download_dataset(entry: Dict[str, Any], force: bool = False) -> None:
    dest = entry['dest']
    if os.path.exists(dest) and os.path.getsize(dest) > 1000 and not force:
        print(f"[CACHE] {entry['name']} already exists ({os.path.getsize(dest)/1024/1024:.2f} MB). Skipping.")
        return

    print(f"[FETCH] Downloading {entry['name']}...")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    resp = requests.get(entry['url'], params=entry['params'], timeout=60)
    resp.raise_for_status()

    with open(dest, 'w', encoding='utf-8') as f:
        f.write(resp.text)
    print(f"[SAVED] {dest} ({os.path.getsize(dest)/1024/1024:.2f} MB)")


def main():
    print("=" * 70)
    print("WHO ARCGIS DATA ACQUISITION PIPELINE")
    print("=" * 70)
    for entry in ENDPOINTS:
        try:
            download_dataset(entry)
        except Exception as e:
            print(f"[ERROR] Failed to fetch {entry['name']}: {e}")
    print("=" * 70)
    print("Data acquisition complete.")


if __name__ == '__main__':
    main()
