#!/usr/bin/env python3
"""
================================================================================
PREPROCESS: MASTER DATASET COMPILER & OPTIMIZATION EXPORTER
================================================================================
Merges planar GIS intersections, demographic exposure models, clinical lethality
indices, and WHO antivenom manufacturer catalogs into the master dataset.
================================================================================
"""

import os
import gzip
import time
import pandas as pd
import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(REPO_ROOT, 'data', 'raw')
PROCESSED_DIR = os.path.join(REPO_ROOT, 'data', 'processed')


def build_optimization_master(
    output_gz_path: str = None,
    output_csv_path: str = None
) -> str:
    output_gz_path = output_gz_path or os.path.join(PROCESSED_DIR, 'GLOBAL_SNAKE_ANTIVENOM_DISTRICT_OPTIMIZATION_MASTER.csv.gz')
    output_csv_path = output_csv_path or os.path.join(PROCESSED_DIR, 'GLOBAL_SNAKE_ANTIVENOM_DISTRICT_OPTIMIZATION_MASTER.csv')

    print("=" * 75)
    print("STARTING GLOBAL MASTER DATASET GENERATION")
    print("=" * 75)
    start_time = time.time()

    # 1. Load Species Master Table
    species_file = os.path.join(PROCESSED_DIR, 'DEATHS-SPECIES_WISE.csv')
    print(f"[*] Loading species metadata: {species_file}")
    df_species = pd.read_csv(species_file)
    species_lookup = {}
    for _, row in df_species.iterrows():
        sci = row['Scientific_Name']
        species_lookup[sci] = {
            'humanPopRange': row.get('humanPopRange', row.get('Impacted_Population', 0)),
            'Vulnerable_Population': row.get('Vulnerable_Population', 0),
            'Annual_Estimated_Bites_Global': row.get('Annual_Estimated_Bites_Global', 0),
            'Annual_Estimated_Envenomations_Global': row.get('Annual_Estimated_Envenomations_Global', 0),
            'Annual_Estimated_Deaths_Global': row.get('Annual_Estimated_Deaths_Global', 0.0),
            'Annual_Estimated_Deaths_India': row.get('Annual_Estimated_Deaths_India', 0.0),
            'Share_of_Global_Snakebite_Deaths_Pct': row.get('Share_of_Global_Snakebite_Deaths_Pct', 0.0),
            'Untreated_Case_Fatality_Rate_Pct': row.get('Untreated_Case_Fatality_Rate_Pct', 10.0),
            'Treated_Case_Fatality_Rate_Pct': row.get('Treated_Case_Fatality_Rate_Pct', 2.0),
            'Standard_Antivenom_Vials_Required': row.get('Standard_Antivenom_Vials_Required', 10),
            'Global_Antivenom_Coverage_Status': row.get('Global_Antivenom_Coverage_Status', 'Unknown'),
            'WHO_MAP_PDF_URL': row.get('Map_pdf', ''),
            'WHO_PHOTO_URL': row.get('Photo_1_url', ''),
            'WHO_REPTILE_DB_URL': row.get('RepDB', '')
        }

    # 2. Load Antivenom Catalog
    av_file = os.path.join(RAW_DIR, 'who_snb_antivenom_manufacturers.csv')
    print(f"[*] Loading antivenom manufacturer catalog: {av_file}")
    av_lookup = {}
    if os.path.exists(av_file):
        df_av = pd.read_csv(av_file)
        av_grouped = df_av.groupby('Scientific_Name').agg({
            'Antivenom_Name': lambda x: '; '.join(list(dict.fromkeys(x.dropna()))),
            'Manufacturer_Name': lambda x: '; '.join(list(dict.fromkeys(x.dropna()))),
            'Specificity': lambda x: '; '.join(list(dict.fromkeys(x.dropna())))
        }).reset_index()
        for _, row in av_grouped.iterrows():
            sci = row['Scientific_Name']
            av_lookup[sci] = {
                'Antivenom_Name': row['Antivenom_Name'] or 'No specific licensed antivenom listed in WHO catalog',
                'Manufacturer_Name': row['Manufacturer_Name'] or 'None',
                'Specificity': row['Specificity'] or 'Not specified'
            }

    # 3. Load Global Overlap Records
    glob_overlap_file = os.path.join(PROCESSED_DIR, 'WHO_EXACT_GIS_GLOBAL_DISTRICT_SNAKE_OVERLAP.csv')
    print(f"[*] Loading global GIS habitat overlap: {glob_overlap_file}")
    df_global = pd.read_csv(glob_overlap_file)

    print(f"  -> Processing {len(df_global):,} global district-species records...")

    # Enrich rows with species & clinical lookups
    enriched_records = []
    for idx, row in df_global.iterrows():
        sci = row['SCIENTIFIC_NAME']
        s_data = species_lookup.get(sci, {})
        rec = dict(row)
        rec.update({
            'humanPopRange': s_data.get('humanPopRange', 0),
            'Vulnerable_Population': s_data.get('Vulnerable_Population', 0),
            'Annual_Estimated_Bites_Global': s_data.get('Annual_Estimated_Bites_Global', 0),
            'Annual_Estimated_Envenomations_Global': s_data.get('Annual_Estimated_Envenomations_Global', 0),
            'Annual_Estimated_Deaths_Global': s_data.get('Annual_Estimated_Deaths_Global', 0.0),
            'Annual_Estimated_Deaths_India': s_data.get('Annual_Estimated_Deaths_India', 0.0),
            'Share_of_Global_Snakebite_Deaths_Pct': s_data.get('Share_of_Global_Snakebite_Deaths_Pct', 0.0),
            'Untreated_Case_Fatality_Rate_Pct': s_data.get('Untreated_Case_Fatality_Rate_Pct', 10.0),
            'Treated_Case_Fatality_Rate_Pct': s_data.get('Treated_Case_Fatality_Rate_Pct', 2.0),
            'Standard_Antivenom_Vials_Required': s_data.get('Standard_Antivenom_Vials_Required', 10),
            'Global_Antivenom_Coverage_Status': s_data.get('Global_Antivenom_Coverage_Status', 'Unknown'),
            'WHO_MAP_PDF_URL': s_data.get('WHO_MAP_PDF_URL', ''),
            'WHO_PHOTO_URL': s_data.get('WHO_PHOTO_URL', ''),
            'WHO_REPTILE_DB_URL': s_data.get('WHO_REPTILE_DB_URL', '')
        })
        enriched_records.append(rec)

    df_out = pd.DataFrame(enriched_records)

    # Save compressed for Git
    print(f"[*] Writing compressed master dataset to {output_gz_path}...")
    with gzip.open(output_gz_path, 'wt', encoding='utf-8') as f_gz:
        df_out.to_csv(f_gz, index=False)

    print(f"[SUCCESS] Generated master dataset ({len(df_out):,} rows) in {time.time() - start_time:.2f}s")
    print(f"  -> Compressed Size: {os.path.getsize(output_gz_path)/(1024*1024):.2f} MB")
    return output_gz_path


if __name__ == '__main__':
    build_optimization_master()
