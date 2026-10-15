#!/usr/bin/env python3
"""Solve every country with a GBD burden anchor and write data/processed/world_results.csv."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from optimise.demand import load_tables
from optimise.solver import optimise_country

rows = []
t = load_tables()
countries = sorted(set(t["pres"].iso3) & set(t["deaths"]))
p_default = int(sys.argv[1]) if len(sys.argv) > 1 else 0
for iso3 in countries:
    n = int((t["districts"].iso3 == iso3).sum())
    p = p_default or max(1, min(20, round(n ** 0.5 / 2)))   # rule of thumb; use /api/p_sweep to choose
    t0 = time.time()
    try:
        s = optimise_country(iso3, {"n_hubs": min(p, n)}, include_districts=False)
        o = s["optimality"]
        rows.append({"iso3": iso3, "country": s["country"], "districts": n, "hubs": s["k_stockrooms"],
                     "gbd_deaths": s["demand_anchor"]["gbd2019_deaths"], "courses_per_year": s["annual_courses_total"],
                     "courses_no_effective_antivenom": s["annual_courses_no_effective_antivenom"],
                     "vials_stocked": s["total_national_vials_allocated"],
                     "mean_resupply_h": round(s["mean_resupply_hours_per_course"], 3),
                     "pct_within_8h": s["pct_courses_within_resupply_standard"],
                     "proven_optimal": o["proven_optimal"], "gap": o["gap"], "status": o["status"],
                     "heuristic_excess_pct": round(100 * (o["heuristic"]["objective_course_hours"] / s["objective_course_hours_per_year"] - 1), 4),
                     "population_provisional": s["population_provisional"], "seconds": round(time.time() - t0, 2),
                     "portfolio": " ; ".join(x["brand_name"] for x in s["product_portfolio"])})
    except Exception as e:
        rows.append({"iso3": iso3, "districts": n, "status": f"ERROR {type(e).__name__}: {e}"})
    print(rows[-1].get("iso3"), rows[-1].get("status"), rows[-1].get("seconds"), flush=True)
df = pd.DataFrame(rows)
df.to_csv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "processed", "world_results.csv"), index=False)
print(df.proven_optimal.value_counts(dropna=False))
