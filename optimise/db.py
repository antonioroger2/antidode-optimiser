#!/usr/bin/env python3
"""
================================================================================
OPTIMISE: DATABASE CONNECTOR & AUTOMATIC INITIALIZER
================================================================================
Provides fast SQLite access with automatic on-demand database construction from
the compressed master dataset (data/processed/GLOBAL_SNAKE_ANTIVENOM_DISTRICT_OPTIMIZATION_MASTER.csv.gz).
================================================================================
"""

import os
import gzip
import sqlite3
import time
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'snakebite_optimizer.db')
MASTER_GZ = os.path.join(REPO_ROOT, 'data', 'processed', 'GLOBAL_SNAKE_ANTIVENOM_DISTRICT_OPTIMIZATION_MASTER.csv.gz')
MASTER_CSV = os.path.join(REPO_ROOT, 'data', 'processed', 'GLOBAL_SNAKE_ANTIVENOM_DISTRICT_OPTIMIZATION_MASTER.csv')


def initialize_database(force: bool = False) -> str:
    if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 1000 and not force:
        return DB_PATH

    print(f"[*] Initializing SQLite database from master dataset: {DB_PATH}")
    start_time = time.time()

    if os.path.exists(MASTER_CSV):
        print(f"  -> Loading from uncompressed CSV: {MASTER_CSV}")
        df = pd.read_csv(MASTER_CSV)
    elif os.path.exists(MASTER_GZ):
        print(f"  -> Decompressing and loading from: {MASTER_GZ}")
        with gzip.open(MASTER_GZ, 'rt', encoding='utf-8') as f_gz:
            df = pd.read_csv(f_gz)
    else:
        raise FileNotFoundError(
            f"Master dataset not found at '{MASTER_GZ}' or '{MASTER_CSV}'. "
            "Run 'preprocess/build_master.py' first."
        )

    print(f"  -> Read {len(df):,} records ({len(df.columns)} columns) in {time.time() - start_time:.2f}s")

    conn = sqlite3.connect(DB_PATH)
    df.to_sql('records', conn, if_exists='replace', index=False)

    print("  -> Creating composite querying indexes...")
    cursor = conn.cursor()
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_country_dist ON records (COUNTRY_NAME, DISTRICT_NAME);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_species ON records (SCIENTIFIC_NAME);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_iso3 ON records (ISO_3_CODE);")
    conn.commit()
    conn.close()

    total_time = time.time() - start_time
    print(f"[SUCCESS] Database initialized in {total_time:.2f}s ({os.path.getsize(DB_PATH) / (1024*1024):.1f} MB)")
    return DB_PATH


def get_db_connection() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 1000:
        initialize_database()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


if __name__ == '__main__':
    initialize_database()
