#!/usr/bin/env python3
"""
================================================================================
OPTIMISE: FLASK REST BACKEND & INTERACTIVE WEB DASHBOARD
================================================================================
Provides REST API endpoints and web interface for:
  1. District-level venomous species profiling & Composite Danger ranking
  2. Patient emergency clinical triage & nearest stockroom dispatch
  3. Operations Research p-Median facility location MIP stockroom optimization
================================================================================
"""

import os
from typing import Any, Dict, List
from flask import Flask, jsonify, render_template, request

# Support running directly or as a module
try:
    from .db import get_db_connection
    from .solver import (
        calculate_danger_score,
        evaluate_emergency_dispatch,
        solve_p_median,
        calculate_district_hazard_gradient,
        calculate_node_vial_allocation,
        parse_therapeutic_brands
    )
except ImportError:
    from db import get_db_connection
    from solver import (
        calculate_danger_score,
        evaluate_emergency_dispatch,
        solve_p_median,
        calculate_district_hazard_gradient,
        calculate_node_vial_allocation,
        parse_therapeutic_brands
    )

template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
app = Flask(__name__, template_folder=template_dir)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/countries', methods=['GET'])
def get_countries():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNTRY_NAME, ISO_3_CODE, COUNT(DISTINCT DISTRICT_NAME) as district_count,
               COUNT(DISTINCT SCIENTIFIC_NAME) as species_count
        FROM records
        GROUP BY COUNTRY_NAME, ISO_3_CODE
        ORDER BY COUNTRY_NAME ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/districts', methods=['GET'])
def get_districts():
    country = request.args.get('country', 'India')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT DISTRICT_NAME, STATE_NAME, CENTER_LON, CENTER_LAT
        FROM records
        WHERE COUNTRY_NAME = ?
        ORDER BY DISTRICT_NAME ASC
    """, (country,))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/species_by_country', methods=['GET'])
@app.route('/api/species_by_district', methods=['GET'])
def get_species_by_district():
    country = request.args.get('country', 'India')
    district = (request.args.get('district') or '').strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. District-Specific Mode
    if district and district not in ['__ALL__', 'ALL', 'all', 'Whole Country']:
        cursor.execute("""
            SELECT *
            FROM records
            WHERE COUNTRY_NAME = ? AND DISTRICT_NAME = ?
        """, (country, district))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        for r in rows:
            r['DANGER_SCORE'] = calculate_danger_score(r)

        rows.sort(key=lambda x: x['DANGER_SCORE'], reverse=True)
        for idx, r in enumerate(rows):
            r['DANGER_RANK'] = idx + 1

        return jsonify({
            'mode': 'district',
            'country': country,
            'district': district,
            'total_species': len(rows),
            'species': rows
        })

    # 2. Whole Country Overview Mode
    cursor.execute("""
        SELECT COUNT(DISTINCT DISTRICT_NAME) FROM records WHERE COUNTRY_NAME = ?
    """, (country,))
    total_districts_in_country = cursor.fetchone()[0] or 1

    cursor.execute("""
        SELECT 
            SCIENTIFIC_NAME,
            COMMON_NAME,
            FAMILY,
            MEDICAL_IMPORTANCE_CATEGORY,
            CODE_SSN,
            ANTIVENOM_EFFICACY_STATUS,
            RECOMMENDED_ANTIVENOM_NAME,
            Untreated_Case_Fatality_Rate_Pct,
            Treated_Case_Fatality_Rate_Pct,
            Standard_Antivenom_Vials_Required,
            Annual_Estimated_Deaths_Global,
            Annual_Estimated_Deaths_India,
            Global_Antivenom_Coverage_Status,
            WHO_MAP_PDF_URL,
            WHO_PHOTO_URL,
            WHO_REPTILE_DB_URL,
            COUNT(DISTINCT DISTRICT_NAME) as district_presence_count,
            ROUND(AVG(SPECIES_DISTRICT_OVERLAP_PCT), 1) as avg_overlap_pct,
            ROUND(MAX(SPECIES_DISTRICT_OVERLAP_PCT), 1) as max_overlap_pct
        FROM records
        WHERE COUNTRY_NAME = ?
        GROUP BY SCIENTIFIC_NAME
    """, (country,))
    species_rows = [dict(r) for r in cursor.fetchall()]

    for r in species_rows:
        r['country_coverage_pct'] = round((r['district_presence_count'] / total_districts_in_country) * 100.0, 1)
        r['SPECIES_DISTRICT_OVERLAP_PCT'] = r['avg_overlap_pct']
        r['DANGER_SCORE'] = calculate_danger_score(r)

    species_rows.sort(key=lambda x: x['DANGER_SCORE'], reverse=True)
    for idx, r in enumerate(species_rows):
        r['DANGER_RANK'] = idx + 1

    cursor.execute("""
        SELECT 
            DISTRICT_NAME,
            STATE_NAME,
            CENTER_LAT,
            CENTER_LON,
            COUNT(DISTINCT SCIENTIFIC_NAME) as species_count,
            SUM(CASE WHEN MEDICAL_IMPORTANCE_CATEGORY LIKE '%Highest%' THEN 1 ELSE 0 END) as cat1_species_count
        FROM records
        WHERE COUNTRY_NAME = ?
        GROUP BY DISTRICT_NAME, STATE_NAME, CENTER_LAT, CENTER_LON
        ORDER BY species_count DESC
    """, (country,))
    districts_summary = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if districts_summary:
        avg_lat = sum(float(d['CENTER_LAT']) for d in districts_summary) / len(districts_summary)
        avg_lon = sum(float(d['CENTER_LON']) for d in districts_summary) / len(districts_summary)
    else:
        avg_lat, avg_lon = 20.5937, 78.9629

    return jsonify({
        'mode': 'country',
        'country': country,
        'district': '__ALL__',
        'total_districts': total_districts_in_country,
        'total_species': len(species_rows),
        'country_center': {'lat': avg_lat, 'lon': avg_lon},
        'species': species_rows,
        'districts_summary': districts_summary
    })



@app.route('/api/patient_emergency', methods=['POST'])
def patient_emergency():
    data = request.json or {}
    country = data.get('country', 'India')
    district = data.get('district', '')
    species_name = data.get('species', '')
    hours_since_bite = float(data.get('hours_since_bite', 0.5))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM records
        WHERE COUNTRY_NAME = ? AND DISTRICT_NAME = ? AND SCIENTIFIC_NAME = ?
        LIMIT 1
    """, (country, district, species_name))
    spec_row = cursor.fetchone()

    if not spec_row:
        cursor.execute("SELECT * FROM records WHERE SCIENTIFIC_NAME = ? LIMIT 1", (species_name,))
        spec_row = cursor.fetchone()

    if not spec_row:
        conn.close()
        return jsonify({'error': f'Species {species_name} not found'}), 404

    spec_dict = dict(spec_row)

    cursor.execute("""
        SELECT CENTER_LAT, CENTER_LON FROM records
        WHERE COUNTRY_NAME = ? AND DISTRICT_NAME = ? LIMIT 1
    """, (country, district))
    p_coord = cursor.fetchone()
    p_lat = float(p_coord['CENTER_LAT']) if p_coord else 20.0
    p_lon = float(p_coord['CENTER_LON']) if p_coord else 78.0

    cursor.execute("""
        SELECT DISTINCT DISTRICT_NAME, STATE_NAME, CENTER_LAT, CENTER_LON
        FROM records
        WHERE COUNTRY_NAME = ?
    """, (country,))
    all_districts = [dict(r) for r in cursor.fetchall()]
    conn.close()

    result = evaluate_emergency_dispatch(
        patient_coords=(p_lat, p_lon),
        species_info=spec_dict,
        hours_since_bite=hours_since_bite,
        all_districts=all_districts
    )
    result['district'] = district
    result['country'] = country
    return jsonify(result)


def get_enriched_districts_for_country(country: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT SCIENTIFIC_NAME, COUNT(DISTINCT DISTRICT_NAME) as presence_cnt
        FROM records
        WHERE COUNTRY_NAME = ?
        GROUP BY SCIENTIFIC_NAME
    """, (country,))
    presence_map = dict(cursor.fetchall())

    cursor.execute("""
        SELECT DISTRICT_NAME, STATE_NAME, CENTER_LAT, CENTER_LON, Vulnerable_Population,
               SCIENTIFIC_NAME, COMMON_NAME, FAMILY, MEDICAL_IMPORTANCE_CATEGORY,
               SPECIES_DISTRICT_OVERLAP_PCT, RECOMMENDED_ANTIVENOM_NAME,
               ANTIVENOM_EFFICACY_STATUS, Standard_Antivenom_Vials_Required,
               Untreated_Case_Fatality_Rate_Pct, Treated_Case_Fatality_Rate_Pct,
               Annual_Estimated_Deaths_Global, Annual_Estimated_Deaths_India
        FROM records
        WHERE COUNTRY_NAME = ?
    """, (country,))
    rows = cursor.fetchall()
    conn.close()

    districts_map: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d_name = r['DISTRICT_NAME']
        if d_name not in districts_map:
            districts_map[d_name] = {
                'DISTRICT_NAME': d_name,
                'STATE_NAME': r['STATE_NAME'],
                'CENTER_LAT': float(r['CENTER_LAT']),
                'CENTER_LON': float(r['CENTER_LON']),
                'population': int(r['Vulnerable_Population'] or 0),
                'total_vuln_pop': int(r['Vulnerable_Population'] or 0),
                'species': []
            }
        sci = r['SCIENTIFIC_NAME']
        deaths_val = float(r['Annual_Estimated_Deaths_India'] or r['Annual_Estimated_Deaths_Global'] or 0.0)
        districts_map[d_name]['species'].append({
            'scientific_name': sci,
            'common_name': r['COMMON_NAME'],
            'family': r['FAMILY'],
            'category': r['MEDICAL_IMPORTANCE_CATEGORY'],
            'overlap_pct': float(r['SPECIES_DISTRICT_OVERLAP_PCT'] or 100.0),
            'antivenom_name': r['RECOMMENDED_ANTIVENOM_NAME'],
            'efficacy_status': r['ANTIVENOM_EFFICACY_STATUS'],
            'vials_required': int(r['Standard_Antivenom_Vials_Required'] or 10),
            'untreated_cfr': float(r['Untreated_Case_Fatality_Rate_Pct'] or 10.0),
            'treated_cfr': float(r['Treated_Case_Fatality_Rate_Pct'] or 1.5),
            'deaths': deaths_val,
            'district_presence_count': presence_map.get(sci, 1)
        })

    return list(districts_map.values())


@app.route('/api/optimize_stockrooms', methods=['POST'])
def optimize_stockrooms():
    data = request.json or {}
    country = data.get('country', 'India')
    k_hubs = int(data.get('num_stockrooms', 5))
    max_travel_hours = float(data.get('max_travel_time', 2.0))
    hazard_weight = float(data.get('hazard_weight', 1.0))
    service_level = float(data.get('service_level', 0.99))
    scenario = data.get('scenario', 'baseline')
    surge_factor = float(data.get('surge_factor', 2.5 if scenario == 'monsoon_surge' else 1.0))
    disabled_hub = data.get('disabled_hub_district') or data.get('offline_hub')
    vial_cap = int(data['total_vial_cap']) if data.get('total_vial_cap') else None

    districts = get_enriched_districts_for_country(country)
    if len(districts) == 0:
        return jsonify({'error': f'No district data for {country}'}), 404

    solution = solve_p_median(
        districts=districts,
        k_hubs=k_hubs,
        max_travel_hours=max_travel_hours,
        hazard_weight=hazard_weight,
        service_level=service_level,
        surge_factor=surge_factor,
        disabled_hub_district=disabled_hub,
        total_vial_cap=vial_cap
    )
    solution['country'] = country
    solution['scenario'] = scenario
    return jsonify(solution)


@app.route('/api/simulate_scenario', methods=['POST'])
def simulate_scenario():
    data = request.json or {}
    country = data.get('country', 'India')
    scenario_type = data.get('scenario_type', 'monsoon_surge')
    k_hubs = int(data.get('num_stockrooms', 6))
    max_travel_hours = float(data.get('max_travel_time', 2.0))
    hazard_weight = float(data.get('hazard_weight', 1.0))
    service_level = float(data.get('service_level', 0.99))

    surge_factor = 2.5 if scenario_type == 'monsoon_surge' else 1.0
    disabled_hub = data.get('disabled_hub_district') if scenario_type == 'hub_outage' else None
    vial_cap = int(data.get('total_vial_cap', 5000)) if scenario_type == 'supply_constrained' else None

    districts = get_enriched_districts_for_country(country)
    if len(districts) == 0:
        return jsonify({'error': f'No district data for {country}'}), 404

    solution = solve_p_median(
        districts=districts,
        k_hubs=k_hubs,
        max_travel_hours=max_travel_hours,
        hazard_weight=hazard_weight,
        service_level=service_level,
        surge_factor=surge_factor,
        disabled_hub_district=disabled_hub,
        total_vial_cap=vial_cap
    )
    solution['country'] = country
    solution['scenario'] = scenario_type
    return jsonify(solution)


@app.route('/api/export_solution', methods=['POST'])
def export_solution():
    import io
    import csv
    from flask import Response

    data = request.json or {}
    hubs = data.get('selected_stockroom_hubs', [])
    assignments = data.get('district_assignments', [])
    country = data.get('country', 'Global')

    output = io.StringIO()
    writer = csv.writer(output)

    # 1. Hub Summary Section
    writer.writerow(["=== SELECTED COLD-CHAIN STOCKROOM HUBS ==="])
    writer.writerow([
        "Hub ID", "District Name", "State", "Latitude", "Longitude",
        "Assigned Districts Count", "Catchment Population",
        "Total Vials Allocated", "Cold Chain Liters Required"
    ])
    for h in hubs:
        writer.writerow([
            h.get('hub_id'), h.get('district_name'), h.get('state_name'),
            h.get('lat'), h.get('lon'), h.get('assigned_districts_count'),
            h.get('assigned_population'), h.get('total_vials_to_store'),
            h.get('total_refrigeration_liters')
        ])

    writer.writerow([])
    # 2. Detailed Itemized Vial Manifest per Hub
    writer.writerow(["=== ITEMIZED MULTI-BRAND VIAL ALLOCATION PER HUB ==="])
    writer.writerow([
        "Hub ID", "Hub District", "Brand / Formulation Name", "Combination Blend %",
        "Interchangeable Brands", "Cycle Demand", "Safety Stock Buffer",
        "Emergency Reserve", "Total Vials Allocated", "Cold Storage Liters",
        "Target Species Count"
    ])
    for h in hubs:
        for item in h.get('vial_inventory', []):
            writer.writerow([
                h.get('hub_id'), h.get('district_name'), item.get('brand_name'),
                f"{item.get('combination_blend_pct', 100)}%",
                "; ".join(item.get('interchangeable_brands', [])) or "None",
                item.get('cycle_demand'), item.get('safety_stock_buffer'),
                item.get('emergency_reserve'), item.get('total_vials_allocated'),
                item.get('refrigeration_liters'), item.get('target_species_count')
            ])

    writer.writerow([])
    # 3. District Assignment & Golden Hour Status
    writer.writerow(["=== DISTRICT ASSIGNMENT & TRANSIT TIME ==="])
    writer.writerow([
        "District Name", "State", "Assigned Hub", "Distance (km)",
        "Transit Time (min)", "Within Golden Hour (<=2h)", "Continuous Hazard Gradient"
    ])
    for d in assignments:
        writer.writerow([
            d.get('district'), d.get('state'), d.get('assigned_hub'),
            d.get('distance_km'), d.get('travel_time_min'),
            "YES" if d.get('within_golden_hour') else "NO (CRITICAL DELAY)",
            d.get('hazard_gradient')
        ])

    filename = f"antivenom_optimization_{country.lower().replace(' ', '_')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )


def run_server():
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Antidote Optimizer Web UI on http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == '__main__':
    run_server()
