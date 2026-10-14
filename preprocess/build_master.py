#!/usr/bin/env python3
"""
================================================================================
PREPROCESS: MASTER DATASET COMPILER & OPTIMIZATION EXPORTER
================================================================================
Merges planar GIS intersections, demographic exposure models, clinical lethality
indices, and WHO antivenom manufacturer catalogs into the master dataset.
Produces exactly all 31 clinical & geospatial attributes across 197,660 records.
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
    print("STARTING GLOBAL MASTER DATASET GENERATION (31 COLUMNS)")
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

    # 2. Load Antivenom Manufacturers Catalog
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
                'Antivenom_Name': row['Antivenom_Name'] if pd.notna(row['Antivenom_Name']) and str(row['Antivenom_Name']).strip() != '' else 'No specific licensed antivenom listed in WHO catalog',
                'Manufacturer_Name': row['Manufacturer_Name'] if pd.notna(row['Manufacturer_Name']) and str(row['Manufacturer_Name']).strip() != '' else 'None',
                'Specificity': row['Specificity'] if pd.notna(row['Specificity']) and str(row['Specificity']).strip() != '' else 'Not specified'
            }

    # 3. Load ADM2 Global boundary metadata for district area
    adm2_file = os.path.join(RAW_DIR, 'who_detailed_boundary_adm2_global_districts_cities.csv')
    print(f"[*] Loading ADM2 boundary metadata: {adm2_file}")
    df_adm2 = pd.read_csv(adm2_file)
    adm2_area_lookup = {}
    for _, row in df_adm2.iterrows():
        key = (str(row['ADM2_NAME']).strip().upper(), str(row['ISO_3_CODE']).strip().upper())
        adm2_area_lookup[key] = row.get('Shape__Area', np.nan)

    # 4. Load India exact GIS overlap
    ind_overlap_file = os.path.join(PROCESSED_DIR, 'WHO_EXACT_GIS_INDIA_DISTRICT_SNAKE_OVERLAP.csv')
    print(f"[*] Loading India exact GIS overlap: {ind_overlap_file}")
    df_ind = pd.read_csv(ind_overlap_file)

    # 5. Load Global GIS overlap
    glob_overlap_file = os.path.join(PROCESSED_DIR, 'WHO_EXACT_GIS_GLOBAL_DISTRICT_SNAKE_OVERLAP.csv')
    print(f"[*] Loading Global GIS overlap: {glob_overlap_file}")
    df_glob = pd.read_csv(glob_overlap_file)

    # Exclude India from global because we use exact polygon overlap for India
    df_glob_non_ind = df_glob[df_glob['ISO_3_CODE'] != 'IND'].copy()
    print(f"  -> Global non-India records: {len(df_glob_non_ind):,}")
    print(f"  -> India exact overlap records: {len(df_ind):,}")

    records = []
    obj_id = 1

    # Process India records first
    for _, row in df_ind.iterrows():
        sci = row['SCIENTIFIC_NAME']
        sp_meta = species_lookup.get(sci, {})
        av_meta = av_lookup.get(sci, {})

        overlap_pct = row.get('SPECIES_DISTRICT_OVERLAP_PCT', 100.0)
        inter_area = row.get('INTERSECTION_AREA_SQ_DEG', np.nan)
        dist_area = row.get('DISTRICT_TOTAL_AREA_SQ_DEG', np.nan)
        std_vials = sp_meta.get('Standard_Antivenom_Vials_Required', 10)

        records.append({
            'OBJECTID': obj_id,
            'DISTRICT_NAME': row['DISTRICT_NAME'],
            'STATE_NAME': row['STATE_NAME'],
            'COUNTRY_NAME': row['COUNTRY_NAME'],
            'ISO_3_CODE': row['ISO_3_CODE'],
            'SCIENTIFIC_NAME': sci,
            'COMMON_NAME': row['COMMON_NAME'],
            'FAMILY': row['FAMILY'],
            'MEDICAL_IMPORTANCE_CATEGORY': row['MEDICAL_IMPORTANCE_CATEGORY'],
            'CODE_SSN': row['CODE_SSN'],
            'SPECIES_DISTRICT_OVERLAP_PCT': overlap_pct,
            'INTERSECTION_AREA_SQ_DEG': inter_area,
            'DISTRICT_TOTAL_AREA_SQ_DEG': dist_area,
            'ANTIVENOM_EFFICACY_STATUS': row.get('ANTIVENOM_EFFICACY_STATUS', sp_meta.get('Global_Antivenom_Coverage_Status', 'Standard Coverage')),
            'RECOMMENDED_ANTIVENOM_NAME': row.get('RECOMMENDED_ANTIVENOM_NAME', av_meta.get('Antivenom_Name', 'Polyvalent Anti-Snake Venom Serum (ASVS) I.P.')),
            'CENTER_LON': row['CENTER_LON'],
            'CENTER_LAT': row['CENTER_LAT'],
            'humanPopRange': sp_meta.get('humanPopRange', 0),
            'Vulnerable_Population': sp_meta.get('Vulnerable_Population', 0),
            'Annual_Estimated_Bites_Global': sp_meta.get('Annual_Estimated_Bites_Global', 0),
            'Annual_Estimated_Envenomations_Global': sp_meta.get('Annual_Estimated_Envenomations_Global', 0),
            'Annual_Estimated_Deaths_Global': sp_meta.get('Annual_Estimated_Deaths_Global', 0.0),
            'Annual_Estimated_Deaths_India': sp_meta.get('Annual_Estimated_Deaths_India', 0.0),
            'Share_of_Global_Snakebite_Deaths_Pct': sp_meta.get('Share_of_Global_Snakebite_Deaths_Pct', 0.0),
            'Untreated_Case_Fatality_Rate_Pct': sp_meta.get('Untreated_Case_Fatality_Rate_Pct', 10.0),
            'Treated_Case_Fatality_Rate_Pct': sp_meta.get('Treated_Case_Fatality_Rate_Pct', 2.0),
            'Standard_Antivenom_Vials_Required': std_vials,
            'Global_Antivenom_Coverage_Status': sp_meta.get('Global_Antivenom_Coverage_Status', 'Unknown'),
            'WHO_MAP_PDF_URL': sp_meta.get('WHO_MAP_PDF_URL', ''),
            'WHO_PHOTO_URL': sp_meta.get('WHO_PHOTO_URL', ''),
            'WHO_REPTILE_DB_URL': sp_meta.get('WHO_REPTILE_DB_URL', '')
        })
        obj_id += 1

    # Process Global non-India records
    for _, row in df_glob_non_ind.iterrows():
        sci = row['SCIENTIFIC_NAME']
        sp_meta = species_lookup.get(sci, {})
        av_meta = av_lookup.get(sci, {})

        d_name = str(row['DISTRICT_NAME']).strip()
        iso3 = str(row['ISO_3_CODE']).strip().upper()
        dist_area = adm2_area_lookup.get((d_name.upper(), iso3), np.nan)
        inter_area = dist_area

        rec_av = av_meta.get('Antivenom_Name', 'No specific licensed antivenom listed in WHO catalog')
        spec_status = av_meta.get('Specificity', 'Not specified')
        if spec_status != 'Not specified':
            eff_status = spec_status
        else:
            eff_status = sp_meta.get('Global_Antivenom_Coverage_Status', 'Standard Care')

        std_vials = sp_meta.get('Standard_Antivenom_Vials_Required', 10)

        records.append({
            'OBJECTID': obj_id,
            'DISTRICT_NAME': d_name,
            'STATE_NAME': row['STATE_NAME'],
            'COUNTRY_NAME': row['COUNTRY_NAME'],
            'ISO_3_CODE': iso3,
            'SCIENTIFIC_NAME': sci,
            'COMMON_NAME': row['COMMON_NAME'],
            'FAMILY': row['FAMILY'],
            'MEDICAL_IMPORTANCE_CATEGORY': row['MEDICAL_IMPORTANCE_CATEGORY'],
            'CODE_SSN': row['CODE_SSN'],
            'SPECIES_DISTRICT_OVERLAP_PCT': 100.0,
            'INTERSECTION_AREA_SQ_DEG': inter_area,
            'DISTRICT_TOTAL_AREA_SQ_DEG': dist_area,
            'ANTIVENOM_EFFICACY_STATUS': eff_status,
            'RECOMMENDED_ANTIVENOM_NAME': rec_av,
            'CENTER_LON': row['CENTER_LON'],
            'CENTER_LAT': row['CENTER_LAT'],
            'humanPopRange': sp_meta.get('humanPopRange', 0),
            'Vulnerable_Population': sp_meta.get('Vulnerable_Population', 0),
            'Annual_Estimated_Bites_Global': sp_meta.get('Annual_Estimated_Bites_Global', 0),
            'Annual_Estimated_Envenomations_Global': sp_meta.get('Annual_Estimated_Envenomations_Global', 0),
            'Annual_Estimated_Deaths_Global': sp_meta.get('Annual_Estimated_Deaths_Global', 0.0),
            'Annual_Estimated_Deaths_India': sp_meta.get('Annual_Estimated_Deaths_India', 0.0),
            'Share_of_Global_Snakebite_Deaths_Pct': sp_meta.get('Share_of_Global_Snakebite_Deaths_Pct', 0.0),
            'Untreated_Case_Fatality_Rate_Pct': sp_meta.get('Untreated_Case_Fatality_Rate_Pct', 10.0),
            'Treated_Case_Fatality_Rate_Pct': sp_meta.get('Treated_Case_Fatality_Rate_Pct', 2.0),
            'Standard_Antivenom_Vials_Required': std_vials,
            'Global_Antivenom_Coverage_Status': sp_meta.get('Global_Antivenom_Coverage_Status', 'Unknown'),
            'WHO_MAP_PDF_URL': sp_meta.get('WHO_MAP_PDF_URL', ''),
            'WHO_PHOTO_URL': sp_meta.get('WHO_PHOTO_URL', ''),
            'WHO_REPTILE_DB_URL': sp_meta.get('WHO_REPTILE_DB_URL', '')
        })
        obj_id += 1

    df_master = pd.DataFrame(records)

    # Save compressed for Git
    print(f"[*] Writing compressed master dataset to {output_gz_path}...")
    with gzip.open(output_gz_path, 'wt', encoding='utf-8') as f_gz:
        df_master.to_csv(f_gz, index=False)

    print(f"[SUCCESS] Generated master dataset ({len(df_master):,} rows, {len(df_master.columns)} columns) in {time.time() - start_time:.2f}s")
    print(f"  -> Compressed Size: {os.path.getsize(output_gz_path)/(1024*1024):.2f} MB")
    return output_gz_path


if __name__ == '__main__':
    build_optimization_master()
