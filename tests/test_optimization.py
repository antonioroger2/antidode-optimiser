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


if __name__ == '__main__':
    unittest.main()
