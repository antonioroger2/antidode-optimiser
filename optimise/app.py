#!/usr/bin/env python3
"""
Flask REST backend and web dashboard for the antivenom location–inventory model.

Endpoints
  GET  /api/countries                 countries with districts, species, burden anchor, population source
  GET  /api/districts?country=        WHO ADM2 districts of a country
  GET  /api/species_by_district       species present in a district (or whole country) + assigned product
  POST /api/optimize_stockrooms       solve one country (exact MILP + inventory)
  POST /api/simulate_scenario         stress test vs. baseline (surge / hub outage / vial cap)
  POST /api/p_sweep                   objective vs. number of hubs (trade-off curve)
  POST /api/sensitivity               one-at-a-time low/high scenarios
  POST /api/patient_emergency         nearest hubs stocking the product for a species
  POST /api/export_solution           CSV export
"""
from __future__ import annotations

import csv
import io
import json
import os
import threading
from typing import Any, Dict

import numpy as np
from flask import Flask, Response, jsonify, render_template, request

try:
    from .demand import load_tables, country_demand
    from .solver import (evaluate_emergency_dispatch, load_config, optimise_country, p_sweep,
                         sensitivity)
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from optimise.demand import load_tables, country_demand  # type: ignore
    from optimise.solver import (evaluate_emergency_dispatch, load_config, optimise_country,  # type: ignore
                                 p_sweep, sensitivity)

template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
app = Flask(__name__, template_folder=template_dir)

_CACHE: Dict[str, Any] = {}
_LOCK = threading.Lock()


def _iso3(country: str) -> str:
    t = load_tables()
    d = t["districts"]
    c = (country or "India").strip()
    if len(c) == 3 and c.upper() in set(d.iso3):
        return c.upper()
    hit = d[d.country.str.upper() == c.upper()]
    if hit.empty:
        raise KeyError(f"Unknown country '{country}'")
    return str(hit.iso3.iloc[0])


def _clean(o):
    """JSON-safe conversion (numpy types, NaN → None)."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not np.isfinite(f) else f
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _params_from_request(data: dict) -> Dict[str, Any]:
    ov = {}
    if "num_stockrooms" in data:
        ov["n_hubs"] = int(data["num_stockrooms"])
    for k in ("n_hubs", "service_level", "avg_speed_kmh", "circuity", "envenomings_per_death",
              "p_antivenom_indicated", "category2_weight", "initial_dose_vials", "repeat_dose_probability",
              "review_period_months", "lead_time_months", "time_limit_s"):
        if data.get(k) not in (None, ""):
            ov[k] = float(data[k]) if k not in ("n_hubs", "initial_dose_vials") else int(data[k])
    if "max_resupply_hours" in data:
        v = data["max_resupply_hours"]
        ov["max_resupply_hours"] = None if v in (None, "", 0, "0", "none") else float(v)
    return ov


def _solve(iso3: str, ov: dict, surge: float = 1.0, disabled=None, cap=None, include=True):
    key = json.dumps([iso3, ov, surge, disabled, cap, include], sort_keys=True, default=str)
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    sol = _clean(optimise_country(iso3, ov, surge_factor=surge, disabled_hub=disabled,
                                  vial_cap=cap, include_districts=include))
    with _LOCK:
        if len(_CACHE) > 64:
            _CACHE.clear()
        _CACHE[key] = sol
    return sol


def _err(e: Exception, code=400):
    return jsonify({"error": f"{type(e).__name__}: {e}"}), code


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/countries", methods=["GET"])
def get_countries():
    t = load_tables()
    d, pres, pop = t["districts"], t["pres"], t["pop"]
    sp = pres.groupby("iso3").scientific_name.nunique()
    ps = pop.groupby("iso3").agg(src=("pop_source", "first"), prov=("provisional", "max"))
    out = []
    for (iso3, name), g in d.groupby(["iso3", "country"]):
        if iso3 not in sp.index:
            continue
        out.append({"COUNTRY_NAME": name, "ISO_3_CODE": iso3, "district_count": int(len(g)),
                    "species_count": int(sp.get(iso3, 0)),
                    "gbd2019_deaths": t["deaths"].get(iso3),
                    "population_source": ps.src.get(iso3), "population_provisional": bool(ps.prov.get(iso3, True))})
    out.sort(key=lambda r: r["COUNTRY_NAME"])
    return jsonify(_clean(out))


@app.route("/api/districts", methods=["GET"])
def get_districts():
    try:
        iso3 = _iso3(request.args.get("country", "India"))
    except KeyError as e:
        return _err(e, 404)
    d = load_tables()["districts"]
    g = d[d.iso3 == iso3].sort_values("adm2")
    return jsonify(_clean([{"DISTRICT_NAME": r.adm2, "STATE_NAME": r.adm1, "district_id": r.district_id,
                            "CENTER_LAT": r.lat, "CENTER_LON": r.lon} for r in g.itertuples()]))


@app.route("/api/species_by_country", methods=["GET"])
@app.route("/api/species_by_district", methods=["GET"])
def get_species_by_district():
    try:
        iso3 = _iso3(request.args.get("country", "India"))
    except KeyError as e:
        return _err(e, 404)
    district = (request.args.get("district") or "").strip()
    t = load_tables()
    cfg = load_config()
    try:
        cd = country_demand(iso3, cfg)
        sp2p, noav = cd.species_product, set(cd.no_antivenom_species)
    except Exception:
        cd, sp2p, noav = None, {}, set()
    pres = t["pres"][t["pres"].iso3 == iso3].merge(t["species"], on="scientific_name", how="left")
    dist = t["districts"][t["districts"].iso3 == iso3]

    def sp_row(r, extra=None):
        prod = sp2p.get(r.scientific_name)
        row = {"SCIENTIFIC_NAME": r.scientific_name, "COMMON_NAME": r.common_name if isinstance(r.common_name, str) else None,
               "FAMILY": r.family if isinstance(r.family, str) else None,
               "MEDICAL_IMPORTANCE_CATEGORY": "Category 1 (Highest medical importance)" if r.category == 1
               else "Category 2 (Secondary medical importance)",
               "RECOMMENDED_ANTIVENOM_NAME": prod.split(" | ")[0] if prod else
               ("No procurable antivenom listed by WHO" if r.scientific_name in noav else "—"),
               "ANTIVENOM_PRODUCT_ID": prod, "HAS_ANTIVENOM": prod is not None,
               "WHO_MAP_PDF_URL": r.map_pdf_url, "WHO_PHOTO_URL": r.photo_url, "WHO_REPTILE_DB_URL": r.reptile_db_url}
        row.update(extra or {})
        return row

    if district and district not in ("__ALL__", "ALL", "all"):
        hit = dist[(dist.district_id == district) | (dist.adm2 == district)]
        if hit.empty:
            return _err(KeyError(f"district '{district}' not found"), 404)
        did = hit.district_id.iloc[0]
        rows = pres[pres.district_id == did]
        lam = None
        if cd is not None:
            dd = cd.districts.set_index("district_id")
            lam = float(dd.lambda_total.get(did, 0.0))
        out = [sp_row(r, {"SPECIES_DISTRICT_OVERLAP_PCT": round(100 * r.overlap_frac, 2), "PRESENCE_METHOD": r.method})
               for r in rows.itertuples()]
        out.sort(key=lambda x: (x["MEDICAL_IMPORTANCE_CATEGORY"], -x["SPECIES_DISTRICT_OVERLAP_PCT"]))
        return jsonify(_clean({"mode": "district", "country": hit.country.iloc[0], "district": hit.adm2.iloc[0],
                               "district_id": did, "total_species": len(out),
                               "expected_courses_per_year": lam, "species": out}))
    n_d = len(dist)
    grp = pres.groupby("scientific_name").agg(n=("district_id", "nunique"), cat=("category", "min"),
                                              ov=("overlap_frac", "mean")).reset_index()
    meta = t["species"].set_index("scientific_name")
    out = []
    for r in grp.itertuples():
        m = meta.loc[r.scientific_name] if r.scientific_name in meta.index else None

        class R:  # adapter
            pass
        o = R()
        o.scientific_name, o.category = r.scientific_name, r.cat
        for k in ("common_name", "family", "map_pdf_url", "photo_url", "reptile_db_url"):
            setattr(o, k, None if m is None else m[k])
        out.append(sp_row(o, {"district_presence_count": int(r.n),
                              "country_coverage_pct": round(100 * r.n / max(1, n_d), 1),
                              "SPECIES_DISTRICT_OVERLAP_PCT": round(100 * r.ov, 1)}))
    out.sort(key=lambda x: (x["MEDICAL_IMPORTANCE_CATEGORY"], -x["district_presence_count"]))
    return jsonify(_clean({"mode": "country", "country": dist.country.iloc[0], "district": "__ALL__",
                           "total_districts": n_d, "total_species": len(out), "species": out}))


@app.route("/api/optimize_stockrooms", methods=["POST"])
def optimize_stockrooms():
    data = request.json or {}
    try:
        iso3 = _iso3(data.get("country", "India"))
        ov = _params_from_request(data)
        surge = float(data.get("surge_factor") or 1.0)
        cap = int(data["total_vial_cap"]) if data.get("total_vial_cap") else None
        disabled = data.get("disabled_hub_district") or None
        sol = _solve(iso3, ov, surge, disabled, cap)
    except KeyError as e:
        return _err(e, 404)
    except Exception as e:
        return _err(e, 400)
    sol = dict(sol)
    sol["scenario"] = data.get("scenario", "baseline")
    return jsonify(sol)


@app.route("/api/simulate_scenario", methods=["POST"])
def simulate_scenario():
    data = request.json or {}
    try:
        iso3 = _iso3(data.get("country", "India"))
        ov = _params_from_request(data)
        st = data.get("scenario_type", "monsoon_surge")
        surge = float(data.get("surge_factor") or (2.5 if st == "monsoon_surge" else 1.0))
        disabled = data.get("disabled_hub_district") if st in ("hub_outage", "custom") else None
        cap = int(data["total_vial_cap"]) if data.get("total_vial_cap") else None
        base = _solve(iso3, ov)
        if st == "hub_outage" and not disabled:
            disabled = base["selected_stockroom_hubs"][0]["district_id"]
        stressed = _solve(iso3, ov, surge, disabled, cap)
    except KeyError as e:
        return _err(e, 404)
    except Exception as e:
        return _err(e, 400)
    impact = {
        "delta_mean_resupply_hours_per_course": stressed["mean_resupply_hours_per_course"] - base["mean_resupply_hours_per_course"],
        "delta_pct_within_standard": (None if base["pct_courses_within_resupply_standard"] is None else
                                      stressed["pct_courses_within_resupply_standard"] - base["pct_courses_within_resupply_standard"]),
        "delta_total_vials": stressed["total_national_vials_allocated"] - base["total_national_vials_allocated"],
        "hubs_changed": sorted({h["district_name"] for h in stressed["selected_stockroom_hubs"]} ^
                               {h["district_name"] for h in base["selected_stockroom_hubs"]}),
        "rationing": stressed.get("rationing"),
    }
    out = dict(stressed)
    out.update({"scenario": st, "impact_vs_baseline": impact})
    return jsonify(_clean(out))


@app.route("/api/p_sweep", methods=["POST"])
def api_p_sweep():
    data = request.json or {}
    try:
        iso3 = _iso3(data.get("country", "India"))
        ps = [int(x) for x in data.get("p_values", [2, 4, 6, 8, 10, 12, 16, 20])]
        return jsonify(_clean({"country": iso3, "curve": p_sweep(iso3, ps, _params_from_request(data))}))
    except Exception as e:
        return _err(e)


@app.route("/api/sensitivity", methods=["POST"])
def api_sensitivity():
    data = request.json or {}
    try:
        iso3 = _iso3(data.get("country", "India"))
        return jsonify(_clean({"country": iso3, **sensitivity(iso3, _params_from_request(data))}))
    except Exception as e:
        return _err(e)


@app.route("/api/patient_emergency", methods=["POST"])
def patient_emergency():
    data = request.json or {}
    try:
        iso3 = _iso3(data.get("country", "India"))
        sol = _solve(iso3, _params_from_request(data))
        t = load_tables()
        dist = t["districts"][t["districts"].iso3 == iso3]
        hit = dist[(dist.district_id == data.get("district")) | (dist.adm2 == data.get("district"))]
        if hit.empty:
            return _err(KeyError("district not found"), 404)
        lat, lon = float(hit.lat.iloc[0]), float(hit.lon.iloc[0])
        species = data.get("species")
        prod = None
        for p in sol["product_portfolio"]:
            if species in p["species"]:
                prod = p["product_id"]
        res = evaluate_emergency_dispatch(sol, lat, lon, prod, float(data.get("hours_since_bite") or 0))
    except Exception as e:
        return _err(e)
    res.update({"country": sol["country"], "district": hit.adm2.iloc[0], "species": species,
                "recommended_antivenom": prod.split(" | ")[0] if prod else "No procurable antivenom listed by WHO for this species",
                "patient_location": {"lat": lat, "lon": lon}})
    return jsonify(_clean(res))


@app.route("/api/export_solution", methods=["POST"])
def export_solution():
    data = request.json or {}
    hubs = data.get("selected_stockroom_hubs", [])
    assignments = data.get("district_assignments", [])
    country = data.get("country", "Global")
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["=== MODEL CERTIFICATE ==="])
    opt = data.get("optimality", {})
    w.writerow(["proven_optimal", opt.get("proven_optimal"), "gap", opt.get("gap"), "lower_bound", opt.get("lower_bound"),
                "objective_course_hours_per_year", data.get("objective_course_hours_per_year")])
    w.writerow(["population_provisional", data.get("population_provisional"), "warnings", " | ".join(data.get("warnings", []))])
    w.writerow([])
    w.writerow(["=== SELECTED STOCKROOM HUBS ==="])
    w.writerow(["Hub ID", "District", "State", "Latitude", "Longitude", "Assigned Districts", "Population",
                "Exposed Population", "Courses/yr", "Total Vials", "Cold Chain Liters"])
    for h in hubs:
        w.writerow([h.get("hub_id"), h.get("district_name"), h.get("state_name"), h.get("lat"), h.get("lon"),
                    h.get("assigned_districts_count"), h.get("assigned_population"), h.get("assigned_exposed_population"),
                    h.get("annual_courses_served"), h.get("total_vials_to_store"), h.get("total_refrigeration_liters")])
    w.writerow([])
    w.writerow(["=== VIAL ORDER-UP-TO LEVELS PER HUB AND PRODUCT ==="])
    w.writerow(["Hub ID", "Hub District", "Product", "Manufacturer", "Courses/yr", "Mean demand (R+L)",
                "Safety stock", "Order-up-to S", "Cycle service level", "Fill rate", "Cold storage L", "Species covered"])
    for h in hubs:
        for it in h.get("vial_inventory", []):
            w.writerow([h.get("hub_id"), h.get("district_name"), it.get("brand_name"), it.get("manufacturer"),
                        it.get("annual_courses"), it.get("cycle_demand"), it.get("safety_stock_buffer"),
                        it.get("total_vials_allocated"), it.get("cycle_service_level"), it.get("fill_rate"),
                        it.get("refrigeration_liters"), "; ".join(it.get("target_species", []))])
    w.writerow([])
    w.writerow(["=== DISTRICT ASSIGNMENT ==="])
    w.writerow(["District", "State", "Assigned Hub", "Distance (km)", "Resupply time (min)",
                "Within resupply standard", "Expected courses/yr", "Courses with no effective antivenom"])
    for d in assignments:
        w.writerow([d.get("district"), d.get("state"), d.get("assigned_hub"), d.get("distance_km"), d.get("travel_time_min"),
                    d.get("within_resupply_standard"), d.get("annual_courses"), d.get("courses_no_antivenom")])
    fn = f"antivenom_optimization_{str(country).lower().replace(' ', '_')}.csv"
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment;filename={fn}"})


def run_server():
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Antivenom Optimiser Web UI on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_server()
