#!/usr/bin/env python3
"""
================================================================================
TESTS: OPERATIONS RESEARCH SOLVER & FLASK ENDPOINTS
================================================================================
"""

import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from optimise.app import app
from optimise.solver import haversine_distance, calculate_danger_score, solve_p_median


class TestOptimizationAndAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.testing = True
        cls.client = app.test_client()

    def test_haversine_distance(self):
        """Verify distance between New Delhi and Mumbai is ~1148 km."""
        delhi = (28.6139, 77.2090)
        mumbai = (19.0760, 72.8777)
        dist = haversine_distance(delhi[0], delhi[1], mumbai[0], mumbai[1])
        self.assertAlmostEqual(dist, 1148.0, delta=50.0)

    def test_danger_score(self):
        """Verify danger score calculates in range [1, 100]."""
        sample_row = {
            'Untreated_Case_Fatality_Rate_Pct': 20.0,
            'MEDICAL_IMPORTANCE_CATEGORY': 'Category 1 (Highest medical importance)',
            'Annual_Estimated_Deaths_Global': 10000,
            'SPECIES_DISTRICT_OVERLAP_PCT': 80.0
        }
        score = calculate_danger_score(sample_row)
        self.assertTrue(1.0 <= score <= 100.0)

    def test_p_median_solver(self):
        """Verify p-Median solver selects requested number of hubs."""
        mock_districts = [
            {'DISTRICT_NAME': 'D1', 'STATE_NAME': 'S1', 'CENTER_LAT': 10.0, 'CENTER_LON': 20.0, 'total_vuln_pop': 5000},
            {'DISTRICT_NAME': 'D2', 'STATE_NAME': 'S1', 'CENTER_LAT': 10.5, 'CENTER_LON': 20.5, 'total_vuln_pop': 10000},
            {'DISTRICT_NAME': 'D3', 'STATE_NAME': 'S1', 'CENTER_LAT': 12.0, 'CENTER_LON': 22.0, 'total_vuln_pop': 2000},
            {'DISTRICT_NAME': 'D4', 'STATE_NAME': 'S1', 'CENTER_LAT': 15.0, 'CENTER_LON': 25.0, 'total_vuln_pop': 8000},
        ]
        res = solve_p_median(mock_districts, k_hubs=2, max_travel_hours=2.0)
        self.assertEqual(len(res['selected_stockroom_hubs']), 2)
        self.assertEqual(len(res['district_assignments']), 4)

    def test_api_index(self):
        """Verify web application UI route."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'GOAD', res.data)

    def test_api_countries(self):
        """Verify /api/countries returns non-empty array."""
        res = self.client.get('/api/countries')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

    def test_api_districts(self):
        """Verify /api/districts for India."""
        res = self.client.get('/api/districts?country=India')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

    def test_api_optimize_stockrooms(self):
        """Verify stockroom location optimization endpoint."""
        payload = {'country': 'India', 'num_stockrooms': 3, 'max_travel_time': 2.0}
        res = self.client.post('/api/optimize_stockrooms', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(len(data['selected_stockroom_hubs']), 3)

    def test_api_species_by_country(self):
        """Verify /api/species_by_country returns nationwide species and district hotspots."""
        res = self.client.get('/api/species_by_country?country=India')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data.get('mode'), 'country')
        self.assertGreater(data.get('total_species', 0), 20)
        self.assertGreater(data.get('total_districts', 0), 500)
        self.assertIn('districts_summary', data)
        self.assertIn('country_center', data)

    def test_parse_therapeutic_brands(self):
        """Verify brand parsing identifies multi-brand interchangeable options."""
        from optimise.solver import parse_therapeutic_brands
        raw = "CroFab (Crotalidae Polyvalent Immune Fab (Ovine)); Anavip®"
        brands = parse_therapeutic_brands(raw)
        self.assertEqual(len(brands), 2)
        self.assertIn("Anavip®", brands)

    def test_multi_brand_combination_allocation(self):
        """Verify that when 2 interchangeable brands exist, a combination blend of both is allocated."""
        from optimise.solver import calculate_node_vial_allocation
        mock_districts = [{
            'DISTRICT_NAME': 'Test County',
            'population': 100000,
            'species': [{
                'scientific_name': 'Crotalus atrox',
                'common_name': 'Western Diamondback Rattlesnake',
                'category': 'Category 1',
                'overlap_pct': 100.0,
                'antivenom_name': 'CroFab; Anavip®',
                'vials_required': 10,
                'untreated_cfr': 15.0,
                'deaths': 50.0,
                'district_presence_count': 10
            }]
        }]
        res = calculate_node_vial_allocation(mock_districts, service_level=0.99, replenishment_months=3)
        self.assertGreater(len(res['vial_inventory']), 1)
        # Check that both brands are allocated and marked as combination
        brand_names = [item['brand_name'] for item in res['vial_inventory']]
        self.assertIn('CroFab', brand_names)
        self.assertIn('Anavip®', brand_names)
        for item in res['vial_inventory']:
            self.assertTrue(item['is_combination'])
            self.assertEqual(item['combination_blend_pct'], 50.0)
            self.assertGreater(item['total_vials_allocated'], 0)
            self.assertGreater(item['emergency_reserve'], 0)

    def test_api_simulate_scenario(self):
        """Verify scenario simulation endpoint."""
        payload = {'country': 'India', 'scenario_type': 'monsoon_surge', 'num_stockrooms': 3}
        res = self.client.post('/api/simulate_scenario', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data.get('scenario'), 'monsoon_surge')
        self.assertGreater(data.get('total_national_vials_allocated', 0), 1000)

    def test_api_export_solution(self):
        """Verify export solution endpoint returns CSV."""
        opt_res = self.client.post('/api/optimize_stockrooms', json={'country': 'India', 'num_stockrooms': 2})
        sol_data = opt_res.get_json()
        exp_res = self.client.post('/api/export_solution', json=sol_data)
        self.assertEqual(exp_res.status_code, 200)
        self.assertIn('text/csv', exp_res.content_type)
        self.assertIn(b'SELECTED COLD-CHAIN STOCKROOM HUBS', exp_res.data)


if __name__ == '__main__':
    unittest.main()

