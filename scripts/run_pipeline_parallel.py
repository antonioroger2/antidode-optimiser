#!/usr/bin/env python3
"""Parallel version of scripts/run_pipeline.sh (same outputs, one process per CPU core).

Usage:  python scripts/run_pipeline_parallel.py [n_workers]
"""
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "preprocess"))

import pandas as pd
import yaml

import presence as P
import population as POP

_RANGES = None
_TO_EA = None


def _init():
    global _RANGES, _TO_EA
    _RANGES = P.load_ranges()
    _TO_EA = P._equal_area()


def _overlap(job):
    iso3, path = job
    try:
        return iso3, P.polygon_overlap(iso3, path, _RANGES, _TO_EA), None
    except Exception as e:  # keep going; country falls back to centroid presence
        return iso3, None, f"{type(e).__name__}: {e}"


def _worldpop(job):
    iso3, thr = job
    try:
        return iso3, POP.worldpop(iso3, _RANGES, thr), None
    except Exception as e:
        return iso3, None, f"{type(e).__name__}: {e}"


def main(workers):
    t0 = time.time()
    with open(os.path.join(REPO, "configs", "model.yaml")) as f:
        cfg = yaml.safe_load(f)

    # ---------------- presence
    species = P.load_species_master()
    ranges = P.load_ranges()
    unknown = set(ranges) - set(species.scientific_name)
    if unknown:
        species = pd.concat([species, pd.DataFrame({"scientific_name": sorted(unknown)})], ignore_index=True)
    districts = P.load_districts()
    poly = {k: v for k, v in P._polygon_layers().items() if os.path.getsize(v) > 1000}
    pres_all, drows_all, failed = [], [], []
    # largest files first so the long jobs start early
    jobs = sorted(poly.items(), key=lambda kv: -os.path.getsize(kv[1]))
    with ProcessPoolExecutor(workers, initializer=_init) as ex:
        futs = [ex.submit(_overlap, j) for j in jobs]
        for i, fu in enumerate(as_completed(futs), 1):
            iso3, res, err = fu.result()
            if err:
                failed.append(iso3)
                print(f"[presence {i}/{len(jobs)}] {iso3} FAILED ({err}) -> centroid fallback", flush=True)
                continue
            p, d = res
            pres_all += p
            drows_all += d
            print(f"[presence {i}/{len(jobs)}] {iso3}: {len(d)} districts  ({time.time()-t0:.0f}s)", flush=True)
    done = {r["district_id"][:3] for r in drows_all}
    rest = districts[~districts.iso3.isin(done)]
    p, d = P.centroid_presence(rest, ranges)
    pres_all += p
    drows_all += d
    pres = pd.DataFrame(pres_all).drop_duplicates(["district_id", "scientific_name"])
    drows = pd.DataFrame(drows_all).drop_duplicates("district_id")
    drows = drows[drows.district_id.isin(districts.district_id)]          # polygon names not in WHO table
    pres = pres[pres.district_id.isin(districts.district_id)]
    districts = districts.merge(drows, on="district_id", how="left")
    districts["presence_method"] = districts.presence_method.fillna("none")
    districts["range_any_frac"] = districts.range_any_frac.fillna(0.0)
    os.makedirs(P.PROCESSED, exist_ok=True)
    species.to_csv(os.path.join(P.PROCESSED, "species.csv"), index=False)
    districts.to_csv(os.path.join(P.PROCESSED, "districts.csv"), index=False)
    pres.to_csv(os.path.join(P.PROCESSED, "district_species.csv"), index=False)
    print(f"[presence] done in {time.time()-t0:.0f}s, polygon failures: {failed}", flush=True)

    # ---------------- antivenom catalogue
    import antivenom
    antivenom.build_catalogue()

    # ---------------- population
    thr = float(cfg["population"]["urban_centre_density_per_km2"])
    have_tif = {f[:3].upper() for f in os.listdir(os.path.join(POP.EXTERNAL, "worldpop"))
                if f.endswith(".tif") and os.path.getsize(os.path.join(POP.EXTERNAL, "worldpop", f)) > 1000} \
        if os.path.isdir(os.path.join(POP.EXTERNAL, "worldpop")) else set()
    jobs = [(iso, thr) for iso in sorted(have_tif & set(poly)) if iso != "IND"]
    parts, wp_fail = [], []
    with ProcessPoolExecutor(workers, initializer=_init) as ex:
        futs = [ex.submit(_worldpop, j) for j in jobs]
        for i, fu in enumerate(as_completed(futs), 1):
            iso3, df, err = fu.result()
            if err or df is None:
                wp_fail.append(iso3)
                print(f"[worldpop {i}/{len(jobs)}] {iso3} FAILED ({err})", flush=True)
                continue
            parts.append(df)
            print(f"[worldpop {i}/{len(jobs)}] {iso3}  ({time.time()-t0:.0f}s)", flush=True)
    range_any = districts.set_index("district_id").range_any_frac
    ind = POP.census_india(range_any)
    if ind is not None:
        parts.append(ind)
    covered = set(pd.concat(parts).district_id) if parts else set()
    rest = districts[~districts.district_id.isin(covered)]
    if len(rest):
        parts.append(POP.geonames(rest))
    pop = pd.concat(parts, ignore_index=True)
    pop = pop[pop.district_id.isin(districts.district_id)].drop_duplicates("district_id")
    pop = pop.drop(columns=["range_any_frac"], errors="ignore").merge(
        districts[["district_id", "range_any_frac"]], on="district_id", how="left")
    base_ind = cfg["demand"].get("india_exposure_base")
    import numpy as np
    pop["exposure_base"] = np.where((pop.iso3 == "IND") & (base_ind == "agricultural_workers_in_range")
                                    & pop.agri_workers.notna(), "agricultural_workers_in_range", "rural_in_range")
    if "exposure_in_range" not in pop:
        pop["exposure_in_range"] = np.nan
    base_val = np.where(pop.exposure_base == "agricultural_workers_in_range", pop.agri_workers, pop.pop_rural)
    pop["exposure_in_range"] = np.where(pop.pop_source.str.startswith("worldpop") & pop.exposure_in_range.notna(),
                                        pop.exposure_in_range, base_val * pop.range_any_frac.fillna(0.0))
    pop.to_csv(os.path.join(POP.PROCESSED, "district_population.csv"), index=False)
    print(pop.groupby("pop_source").iso3.nunique())
    print(f"[done] {time.time()-t0:.0f}s  worldpop failures: {wp_fail}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else (os.cpu_count() or 4))
