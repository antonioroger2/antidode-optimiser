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
    from .solver import calculate_danger_score, evaluate_emergency_dispatch, solve_p_median
except ImportError:
    from db import get_db_connection
    from solver import calculate_danger_score, evaluate_emergency_dispatch, solve_p_median

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


@app.route('/api/species_by_district', methods=['GET'])
def get_species_by_district():
    country = request.args.get('country', 'India')
    district = request.args.get('district', '')

    conn = get_db_connection()
    cursor = conn.cursor()
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
        'country': country,
        'district': district,
        'total_species': len(rows),
        'species': rows
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


@app.route('/api/optimize_stockrooms', methods=['POST'])
def optimize_stockrooms():
    data = request.json or {}
    country = data.get('country', 'India')
    k_hubs = int(data.get('num_stockrooms', 5))
    max_travel_hours = float(data.get('max_travel_time', 2.0))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTRICT_NAME, STATE_NAME, CENTER_LAT, CENTER_LON,
               SUM(Vulnerable_Population) as total_vuln_pop,
               SUM(Standard_Antivenom_Vials_Required) as total_demand_weight,
               COUNT(DISTINCT SCIENTIFIC_NAME) as species_count
        FROM records
        WHERE COUNTRY_NAME = ?
        GROUP BY DISTRICT_NAME, STATE_NAME, CENTER_LAT, CENTER_LON
    """, (country,))
    districts = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if len(districts) == 0:
        return jsonify({'error': f'No district data for {country}'}), 404

    solution = solve_p_median(districts, k_hubs=k_hubs, max_travel_hours=max_travel_hours)
    solution['country'] = country
    return jsonify(solution)


def run_server():
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Antidote Optimizer Web UI on http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == '__main__':
    run_server()
