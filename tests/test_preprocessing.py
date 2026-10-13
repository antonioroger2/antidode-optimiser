#!/usr/bin/env python3
"""
================================================================================
TESTS: DATASET SCHEMA & PREPROCESSING INTEGRITY
================================================================================
"""

import gzip
import os
import unittest
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(REPO_ROOT, 'data', 'processed')
MASTER_GZ = os.path.join(PROCESSED_DIR, 'GLOBAL_SNAKE_ANTIVENOM_DISTRICT_OPTIMIZATION_MASTER.csv.gz')
SPECIES_CSV = os.path.join(PROCESSED_DIR, 'DEATHS-SPECIES_WISE.csv')


class TestPreprocessingIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(MASTER_GZ):
            raise FileNotFoundError(f"Master file {MASTER_GZ} not found.")
        with gzip.open(MASTER_GZ, 'rt', encoding='utf-8') as f:
            cls.df_sample = pd.read_csv(f, nrows=5000)

    def test_master_gz_exists_and_valid(self):
        """Verify compressed master dataset exists and has valid size."""
        sz = os.path.getsize(MASTER_GZ)
        self.assertGreater(sz, 1_000_000, "Compressed master file should exceed 1MB")

    def test_mandatory_columns_present(self):
        """Verify essential geospatial and epidemiological columns."""
        expected = [
            'DISTRICT_NAME', 'STATE_NAME', 'COUNTRY_NAME', 'ISO_3_CODE',
            'SCIENTIFIC_NAME', 'COMMON_NAME', 'CENTER_LAT', 'CENTER_LON',
            'Untreated_Case_Fatality_Rate_Pct', 'Treated_Case_Fatality_Rate_Pct',
            'Standard_Antivenom_Vials_Required'
        ]
        for col in expected:
            self.assertIn(col, self.df_sample.columns)

    def test_coordinates_valid_range(self):
        """Verify latitude is in [-90, 90] and longitude is in [-180, 180]."""
        self.assertTrue((self.df_sample['CENTER_LAT'] >= -90.0).all())
        self.assertTrue((self.df_sample['CENTER_LAT'] <= 90.0).all())
        self.assertTrue((self.df_sample['CENTER_LON'] >= -180.0).all())
        self.assertTrue((self.df_sample['CENTER_LON'] <= 180.0).all())

    def test_case_fatality_rates(self):
        """Verify untreated CFR >= treated CFR."""
        self.assertTrue(
            (self.df_sample['Untreated_Case_Fatality_Rate_Pct'] >= self.df_sample['Treated_Case_Fatality_Rate_Pct']).all()
        )

    def test_species_table_exists(self):
        """Verify species table has at least 300 venomous species."""
        df_sp = pd.read_csv(SPECIES_CSV)
        self.assertGreater(len(df_sp), 300)


if __name__ == '__main__':
    unittest.main()
