#!/usr/bin/env python3
"""
================================================================================
PREPROCESS: GIS SPATIAL POLYGON INTERSECTION ENGINE
================================================================================
Performs exact planar polygon-polygon intersections between WHO snake species
habitation ranges and administrative boundaries (India ADM2 / Global ADM2).
Calculates exact overlap area (sq deg) and percentage coverage.
================================================================================
"""

import os
import json
import time
from typing import Dict, List, Any
import pandas as pd
from shapely.geometry import shape

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPATIAL_DIR = os.path.join(REPO_ROOT, 'data', 'spatial')
RAW_DIR = os.path.join(REPO_ROOT, 'data', 'raw')
PROCESSED_DIR = os.path.join(REPO_ROOT, 'data', 'processed')


def compute_india_district_species_overlap(
    habitat_path: str = None,
    district_path: str = None,
    species_master_path: str = None,
    output_path: str = None
) -> pd.DataFrame:
    habitat_path = habitat_path or os.path.join(SPATIAL_DIR, 'who_snake_species_habitation_polygons.geojson')
    district_path = district_path or os.path.join(SPATIAL_DIR, 'who_india_adm2_district_polygons.geojson')
    species_master_path = species_master_path or os.path.join(PROCESSED_DIR, 'DEATHS-SPECIES_WISE.csv')
    output_path = output_path or os.path.join(PROCESSED_DIR, 'WHO_EXACT_GIS_INDIA_DISTRICT_SNAKE_OVERLAP.csv')

    print("[*] Computing Exact Geometric Polygon Overlaps for India Districts...")
    start_time = time.time()

    with open(habitat_path, 'r', encoding='utf-8') as f:
        sp_geo = json.load(f)
    with open(district_path, 'r', encoding='utf-8') as f:
        dist_geo = json.load(f)

    species_master = pd.read_csv(species_master_path)
    species_meta = {}
    for _, row in species_master.iterrows():
        sci = row['Scientific_Name']
        species_meta[sci] = {
            'common_name': row['PrimaryCommonName'] if pd.notna(row['PrimaryCommonName']) else 'Venomous snake',
            'family': row['Family_Name'] if pd.notna(row['Family_Name']) else ('Elapidae' if any(g in str(sci) for g in ['Naja', 'Bungarus', 'Ophiophagus']) else 'Viperidae'),
            'category': row['List_of_Category_name'] if pd.notna(row['List_of_Category_name']) else 'Highest medical importance'
        }

    # Prepare species geometries
    species_polygons = []
    for f in sp_geo['features']:
        props = f['properties']
        sci_name = props.get('Scientific_Name')
        ssn = props.get('code_ssn')
        cat = props.get('code_cat')
        try:
            geom = shape(f['geometry']).buffer(0)
            if not geom.is_empty:
                species_polygons.append({
                    'Scientific_Name': sci_name,
                    'code_ssn': ssn,
                    'code_cat': cat,
                    'geom': geom,
                    'bounds': geom.bounds
                })
        except Exception:
            continue

    print(f"  -> Loaded {len(species_polygons)} valid species habitat geometries.")

    records = []
    obj_id = 1

    for d_feat in dist_geo['features']:
        d_props = d_feat['properties']
        d_name = d_props.get('ADM2_VIZ_NAME') if pd.notna(d_props.get('ADM2_VIZ_NAME')) else d_props.get('ADM2_NAME')
        s_name = d_props.get('ADM1_NAME')
        lon = d_props.get('CENTER_LON')
        lat = d_props.get('CENTER_LAT')

        try:
            d_geom = shape(d_feat['geometry']).buffer(0)
            if d_geom.is_empty:
                continue
            d_area = d_geom.area
            d_bounds = d_geom.bounds
        except Exception:
            continue

        for sp in species_polygons:
            sp_bounds = sp['bounds']
            # Bounding box rejection
            if (d_bounds[2] < sp_bounds[0] or d_bounds[0] > sp_bounds[2] or
                d_bounds[3] < sp_bounds[1] or d_bounds[1] > sp_bounds[3]):
                continue

            sp_geom = sp['geom']
            if d_geom.intersects(sp_geom):
                try:
                    inter_geom = d_geom.intersection(sp_geom)
                    inter_area = inter_geom.area
                    coverage_pct = (inter_area / d_area) * 100.0

                    if coverage_pct >= 0.05:  # Filter out negligible slivers
                        sci_name = sp['Scientific_Name']
                        meta = species_meta.get(sci_name, {})
                        cat_code = sp['code_cat']
                        cat_desc = 'Category 1 (Highest medical importance)' if cat_code == 'CAT001' else 'Category 2 (Secondary medical importance)'

                        # Antivenom Neutralization Protocol
                        if sci_name in ['Daboia russelii', 'Naja naja', 'Bungarus caeruleus', 'Echis carinatus']:
                            av_status = 'Fully Neutralized by Polyvalent ASVS (IP)'
                            av_prod = 'Polyvalent Anti-Snake Venom Serum (ASVS) I.P.'
                        elif sci_name in ['Hypnale hypnale', 'Trimeresurus malabaricus', 'Trimeresurus erythrurus', 'Gloydius himalayanus']:
                            av_status = 'Poor / Incomplete Neutralization (Requires Monovalent / Supportive Care)'
                            av_prod = 'Experimental Monovalent Pit Viper Antivenom / Supportive Care'
                        elif sci_name == 'Ophiophagus hannah':
                            av_status = 'Requires King Cobra Monovalent Antivenom'
                            av_prod = 'King Cobra Monovalent Antivenin'
                        else:
                            av_status = 'Partial Paraspecific Neutralization'
                            av_prod = 'Polyvalent Anti-Snake Venom Serum (ASVS) I.P.'

                        records.append({
                            'OBJECTID': obj_id,
                            'DISTRICT_NAME': d_name,
                            'STATE_NAME': s_name,
                            'COUNTRY_NAME': 'India',
                            'ISO_3_CODE': 'IND',
                            'SCIENTIFIC_NAME': sci_name,
                            'COMMON_NAME': meta.get('common_name', sci_name),
                            'FAMILY': meta.get('family', 'Viperidae'),
                            'MEDICAL_IMPORTANCE_CATEGORY': cat_desc,
                            'CODE_SSN': sp['code_ssn'],
                            'SPECIES_DISTRICT_OVERLAP_PCT': round(min(100.0, coverage_pct), 2),
                            'INTERSECTION_AREA_SQ_DEG': round(inter_area, 6),
                            'DISTRICT_TOTAL_AREA_SQ_DEG': round(d_area, 6),
                            'ANTIVENOM_EFFICACY_STATUS': av_status,
                            'RECOMMENDED_ANTIVENOM_NAME': av_prod,
                            'CENTER_LON': lon,
                            'CENTER_LAT': lat
                        })
                        obj_id += 1
                except Exception:
                    continue

    df_overlap = pd.DataFrame(records)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df_overlap.to_csv(output_path, index=False)
    print(f"[OK] Generated {len(df_overlap):,} overlap records in {time.time() - start_time:.2f}s -> {output_path}")
    return df_overlap


if __name__ == '__main__':
    compute_india_district_species_overlap()
