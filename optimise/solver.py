#!/usr/bin/env python3
"""
================================================================================
OPTIMISE: OPERATIONS RESEARCH MATHEMATICAL SOLVER & TRIAGE ENGINE
================================================================================
Contains:
  1. Geodesic Haversine matrix calculations with regional tortuosity factors
  2. Clinical risk & Composite Danger Score algorithm
  3. Patient Emergency Antivenom Dispatch & Golden Hour triage evaluator
  4. Capacitated p-Median Facility Location Stockroom Optimizer
================================================================================
"""

import math
from typing import Any, Dict, List, Tuple
import numpy as np


# Haversine distance in kilometers
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


# Calculate Composite Danger Score (0 - 100)
def calculate_danger_score(row: Dict[str, Any]) -> float:
    cfr = float(row.get('Untreated_Case_Fatality_Rate_Pct') or 10.0)
    is_cat1 = 1.0 if 'Highest' in str(row.get('MEDICAL_IMPORTANCE_CATEGORY', '')) else 0.2
    deaths = float(row.get('Annual_Estimated_Deaths_Global') or 0.0)
    overlap = float(row.get('SPECIES_DISTRICT_OVERLAP_PCT') or 100.0)

    cfr_score = min(100.0, cfr) * 0.40
    cat_score = (is_cat1 * 100.0) * 0.25
    death_score = min(100.0, math.log10(max(1.0, deaths)) * 25.0) * 0.20
    overlap_score = min(100.0, overlap) * 0.15

    total = cfr_score + cat_score + death_score + overlap_score
    return round(min(100.0, max(1.0, total)), 1)


# Evaluate patient emergency clinical triage & dispatch
def evaluate_emergency_dispatch(
    patient_coords: Tuple[float, float],
    species_info: Dict[str, Any],
    hours_since_bite: float,
    all_districts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    p_lat, p_lon = patient_coords
    TORTUOSITY = 1.45
    AVG_SPEED_KMH = 45.0

    destinations = []
    for d in all_districts:
        d_lat = float(d['CENTER_LAT'])
        d_lon = float(d['CENTER_LON'])
        dist_km = haversine_distance(p_lat, p_lon, d_lat, d_lon)
        road_km = dist_km * TORTUOSITY
        travel_hours = road_km / AVG_SPEED_KMH
        destinations.append({
            'hub_name': f"{d['DISTRICT_NAME']} Medical Center ({d['STATE_NAME']})",
            'lat': d_lat,
            'lon': d_lon,
            'straight_distance_km': round(dist_km, 1),
            'road_distance_km': round(road_km, 1),
            'travel_time_hours': round(travel_hours, 2),
            'travel_time_minutes': int(round(travel_hours * 60))
        })

    destinations.sort(key=lambda x: x['straight_distance_km'])
    nearest_hubs = destinations[:5]

    primary_travel = nearest_hubs[0]['travel_time_hours'] if nearest_hubs else 0.0
    total_delay = hours_since_bite + primary_travel

    if total_delay <= 2.0:
        triage_status = 'SAFE_WINDOW'
        triage_msg = 'Within the optimal Golden Hour (<= 2h). Administer antivenom immediately on arrival.'
        triage_badge = 'emerald'
    elif total_delay <= 4.0:
        triage_status = 'URGENT_WINDOW'
        triage_msg = 'Urgent Window (2h - 4h). Elevated risk of systemic neuro/hemotoxicity. Prepare ICU / ventilation.'
        triage_badge = 'amber'
    else:
        triage_status = 'CRITICAL_WINDOW'
        triage_msg = 'Critical Delay (> 4h). High risk of acute renal failure / respiratory arrest. Emergency resuscitation required.'
        triage_badge = 'rose'

    danger_score = calculate_danger_score(species_info)

    return {
        'species': species_info['SCIENTIFIC_NAME'],
        'common_name': species_info['COMMON_NAME'],
        'family': species_info['FAMILY'],
        'category': species_info['MEDICAL_IMPORTANCE_CATEGORY'],
        'danger_score': danger_score,
        'untreated_cfr': species_info['Untreated_Case_Fatality_Rate_Pct'],
        'treated_cfr': species_info['Treated_Case_Fatality_Rate_Pct'],
        'recommended_antivenom': species_info['RECOMMENDED_ANTIVENOM_NAME'],
        'efficacy_status': species_info['ANTIVENOM_EFFICACY_STATUS'],
        'initial_vials_required': int(species_info.get('Standard_Antivenom_Vials_Required', 10)),
        'patient_location': {'lat': p_lat, 'lon': p_lon},
        'hours_since_bite': hours_since_bite,
        'total_delay_hours': round(total_delay, 2),
        'triage_status': triage_status,
        'triage_message': triage_msg,
        'triage_badge': triage_badge,
        'nearest_stockrooms': nearest_hubs,
        'photo_url': species_info.get('WHO_PHOTO_URL', ''),
        'map_url': species_info.get('WHO_MAP_PDF_URL', '')
    }


# Solve p-Median Stockroom Allocation
def solve_p_median(
    districts: List[Dict[str, Any]],
    k_hubs: int = 5,
    max_travel_hours: float = 2.0
) -> Dict[str, Any]:
    if not districts:
        raise ValueError("No districts provided to solve_p_median")

    n = len(districts)
    k_hubs = min(k_hubs, n)

    coords = np.array([[float(d['CENTER_LAT']), float(d['CENTER_LON'])] for d in districts])
    weights = np.array([max(100.0, float(d.get('total_vuln_pop') or 1000.0)) for d in districts])

    # Haversine Distance Matrix
    dist_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            d_km = haversine_distance(coords[i, 0], coords[i, 1], coords[j, 0], coords[j, 1])
            dist_matrix[i, j] = d_km
            dist_matrix[j, i] = d_km

    # 1-median base seed
    total_weighted_d = np.sum(dist_matrix * weights[np.newaxis, :], axis=1)
    chosen_indices = [int(np.argmin(total_weighted_d))]

    # Greedy forward selection
    while len(chosen_indices) < k_hubs:
        best_cand = None
        best_cost = float('inf')
        for cand in range(n):
            if cand in chosen_indices:
                continue
            test_hubs = chosen_indices + [cand]
            sub_dists = dist_matrix[test_hubs, :]
            min_dists = np.min(sub_dists, axis=0)
            cost = float(np.sum(min_dists * weights))
            if cost < best_cost:
                best_cost = cost
                best_cand = cand
        if best_cand is not None:
            chosen_indices.append(best_cand)
        else:
            break

    sub_dists = dist_matrix[chosen_indices, :]
    assignment = [int(x) for x in np.argmin(sub_dists, axis=0)]
    assigned_distances = [float(x) for x in np.min(sub_dists, axis=0)]

    TORTUOSITY = 1.45
    AVG_SPEED_KMH = 45.0
    assigned_travel_hours = [(d * TORTUOSITY) / AVG_SPEED_KMH for d in assigned_distances]

    hubs_data = []
    for h_rank, h_idx in enumerate(chosen_indices):
        hub_dist = districts[h_idx]
        assigned_d_indices = [i for i, a in enumerate(assignment) if a == h_rank]
        assigned_pop = int(sum(weights[i] for i in assigned_d_indices))
        assigned_vials = int(len(assigned_d_indices) * 150)

        hubs_data.append({
            'hub_id': h_rank + 1,
            'district_name': hub_dist['DISTRICT_NAME'],
            'state_name': hub_dist['STATE_NAME'],
            'lat': float(hub_dist['CENTER_LAT']),
            'lon': float(hub_dist['CENTER_LON']),
            'assigned_districts_count': int(len(assigned_d_indices)),
            'assigned_population': assigned_pop,
            'recommended_safety_stock_vials': assigned_vials
        })

    avg_travel_time_min = float(np.average([t * 60 for t in assigned_travel_hours], weights=weights))
    pop_in_golden = sum(weights[i] for i, t in enumerate(assigned_travel_hours) if t <= max_travel_hours)
    pct_within_golden_hour = float((pop_in_golden / np.sum(weights)) * 100.0)
    max_travel_time_min = float(max(t * 60 for t in assigned_travel_hours))

    return {
        'k_stockrooms': k_hubs,
        'total_districts_optimized': n,
        'total_population_at_risk': int(np.sum(weights)),
        'avg_travel_time_minutes': round(avg_travel_time_min, 1),
        'max_travel_time_minutes': round(max_travel_time_min, 1),
        'pct_covered_in_golden_hour': round(pct_within_golden_hour, 1),
        'selected_stockroom_hubs': hubs_data,
        'district_assignments': [
            {
                'district': districts[i]['DISTRICT_NAME'],
                'state': districts[i]['STATE_NAME'],
                'lat': float(districts[i]['CENTER_LAT']),
                'lon': float(districts[i]['CENTER_LON']),
                'assigned_hub': hubs_data[assignment[i]]['district_name'],
                'distance_km': round(assigned_distances[i] * TORTUOSITY, 1),
                'travel_time_min': int(round(assigned_travel_hours[i] * 60)),
                'within_golden_hour': bool(assigned_travel_hours[i] <= max_travel_hours)
            }
            for i in range(n)
        ]
    }
