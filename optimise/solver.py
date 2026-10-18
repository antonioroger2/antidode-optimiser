#!/usr/bin/env python3
"""
Country-level antivenom location–inventory optimisation (orchestrator).

Pipeline for one country c:
  1. demand.country_demand      expected courses / yr per district and product class
  2. location.solve_location    exact lexicographic MCLP → p-median MILP (HiGHS), certified
  3. inventory.base_stock       exact compound-Poisson (R,S) levels per hub × product
  4. inventory.ration           optimal allocation if a national vial cap binds

Hubs are resupply/storage nodes. Travel time hub → district is a *resupply* time.
Patient time-to-antivenom depends on which health facilities hold stock and is
outside this model (needs a facility registry).
"""
from __future__ import annotations

import copy
import os
import time
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import yaml

try:
    from .demand import country_demand, load_tables
    from .inventory import base_stock, course_distribution, ration, expected_served
    from .location import solve_location, haversine_km
except ImportError:  # executed as a script from optimise/
    from demand import country_demand, load_tables  # type: ignore
    from inventory import base_stock, course_distribution, ration, expected_served  # type: ignore
    from location import solve_location, haversine_km  # type: ignore

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(REPO, "configs", "model.yaml")

OVERRIDE_MAP = {
    # request key           -> (config section, key)
    "envenomings_per_death": ("demand", "envenomings_per_death"),
    "p_antivenom_indicated": ("demand", "p_antivenom_indicated"),
    "category2_weight": ("demand", "category2_weight"),
    "initial_dose_vials": ("course", "initial_dose_vials"),
    "repeat_dose_probability": ("course", "repeat_dose_probability"),
    "avg_speed_kmh": ("network", "avg_speed_kmh"),
    "circuity": ("network", "circuity"),
    "max_resupply_hours": ("network", "max_resupply_hours"),
    "n_hubs": ("network", "n_hubs"),
    "time_limit_s": ("network", "time_limit_s"),
    "service_level": ("inventory", "cycle_service_level"),
    "review_period_months": ("inventory", "review_period_months"),
    "lead_time_months": ("inventory", "lead_time_months"),
}


def load_config(overrides: Optional[Dict[str, Any]] = None) -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for k, v in (overrides or {}).items():
        if k in OVERRIDE_MAP and v is not None and v != "":
            sec, key = OVERRIDE_MAP[k]
            cfg[sec][key] = v
        elif k == "max_resupply_hours" and v is None:
            cfg["network"]["max_resupply_hours"] = None
    return cfg


def _resolve_district(cd, name_or_id: Optional[str]) -> Optional[int]:
    if not name_or_id:
        return None
    d = cd.districts
    hit = np.flatnonzero((d.district_id == name_or_id).to_numpy() |
                         (d.adm2.str.upper() == str(name_or_id).upper()).to_numpy())
    if hit.size == 0:
        raise KeyError(f"hub district '{name_or_id}' not found in {cd.iso3}")
    return int(hit[0])


def optimise_country(iso3: str, overrides: Optional[Dict[str, Any]] = None, *,
                     surge_factor: float = 1.0, disabled_hub: Optional[str] = None,
                     vial_cap: Optional[int] = None, hub_capacity_courses: Optional[float] = None,
                     include_districts: bool = True) -> Dict[str, Any]:
    t0 = time.time()
    cfg = load_config(overrides)
    net, inv, crs = cfg["network"], cfg["inventory"], cfg["course"]
    cd = country_demand(iso3, cfg)
    d = cd.districts
    if surge_factor <= 0:
        raise ValueError("surge_factor must be > 0")
    lam_k = cd.product_courses.to_numpy(float) * surge_factor           # (n, K) courses / yr
    w = lam_k.sum(axis=1)
    if w.sum() <= 0:
        raise ValueError(f"{iso3}: no treatable antivenom demand ({'; '.join(cd.warnings)})")
    p = min(int(net["n_hubs"]), len(d))
    disabled = _resolve_district(cd, disabled_hub)
    T = net.get("max_resupply_hours")
    T = None if T in (None, 0, "none") else float(T)
    T_rep = T if T is not None else float(net.get("report_resupply_hours", 8.0))
    loc = solve_location(d.lat.to_numpy(), d.lon.to_numpy(), w, p,
                         circuity=float(net["circuity"]), speed_kmh=float(net["avg_speed_kmh"]),
                         max_hours=T, disabled=[disabled] if disabled is not None else None,
                         capacity=hub_capacity_courses,
                         time_limit=float(net["time_limit_s"]), mip_rel_gap=float(net["mip_rel_gap"]))

    # ---------------- inventory
    tau = (float(inv["review_period_months"]) + float(inv["lead_time_months"])) / 12.0
    lead_share = float(inv["lead_time_months"]) / (float(inv["review_period_months"]) + float(inv["lead_time_months"]))
    alpha = float(inv["cycle_service_level"])
    v, pi = course_distribution(int(crs["initial_dose_vials"]), float(crs["repeat_dose_probability"]))
    vol = float(inv["vial_volume_l"])
    assign = np.asarray(loc["assignment"])
    hours = np.asarray(loc["travel_hours"])
    km = hours * float(net["avg_speed_kmh"])
    items, hubs_out = [], []
    sp_by_prod: Dict[str, List[str]] = {}
    for s, pr in cd.species_product.items():
        sp_by_prod.setdefault(pr, []).append(s)
    for rank, h in enumerate(loc["hubs"]):
        idx = np.flatnonzero(assign == h)
        hub_items = []
        for k, prod in enumerate(cd.products):
            lam = float(lam_k[idx, k].sum())
            bs = base_stock(lam * tau, v, pi, alpha, lead_share)
            it = {"hub_rank": rank, "product": prod, "annual_courses": lam, **bs}
            items.append(it)
            hub_items.append(it)
        hubs_out.append((rank, h, idx, hub_items))

    rationing = None
    if vial_cap is not None:
        total_target = sum(it["S"] for it in items)
        if vial_cap < total_target:
            r = ration(items, int(vial_cap))
            for it, a in zip(items, r["allocation"]):
                it["S_target"] = it["S"]
                it["S"] = int(a)
                it["fill_rate_rationed"] = expected_served(it["pmf"], it["S"]) / it["mean_demand"] if it["mean_demand"] > 0 else 1.0
            unconstrained = sum(expected_served(it["pmf"], it["S_target"]) for it in items)
            rationing = {"cap_vials": int(vial_cap), "target_vials": int(total_target),
                         "expected_vials_served": r["expected_served"],
                         "expected_vials_served_unconstrained": unconstrained,
                         "expected_vials_short_per_cycle": unconstrained - r["expected_served"],
                         "method": "greedy marginal allocation (exact for separable concave objective)"}

    # ---------------- assemble output (keys kept compatible with the UI)
    hubs_json = []
    prod_hubs: Dict[str, List[int]] = {}
    for rank, h, idx, hub_items in hubs_out:
        inv_rows = []
        for it in hub_items:
            if it["annual_courses"] <= 0 and it["S"] == 0:
                continue
            inv_rows.append({
                "brand_name": it["product"].split(" | ")[0],
                "product_id": it["product"],
                "manufacturer": it["product"].split(" | ")[1] if " | " in it["product"] else None,
                "target_species": sorted(sp_by_prod.get(it["product"], [])),
                "target_species_count": len(sp_by_prod.get(it["product"], [])),
                "annual_courses": round(it["annual_courses"], 2),
                "cycle_demand": round(it["mean_demand"], 1),
                "safety_stock_buffer": round(it["safety_stock"], 1),
                "total_vials_allocated": int(it["S"]),
                "order_up_to_target": int(it.get("S_target", it["S"])),
                "cycle_service_level": round(it["cycle_service_level"], 5),
                "fill_rate": round(it.get("fill_rate_rationed", it["fill_rate"]), 5),
                "expected_on_hand": round(it["expected_on_hand"], 1),
                "refrigeration_liters": round(it["S"] * vol, 2),
            })
            if it["S"] > 0:
                prod_hubs.setdefault(it["product"], []).append(rank)
        tot = int(sum(r["total_vials_allocated"] for r in inv_rows))
        hd = d.iloc[h]
        hubs_json.append({
            "hub_id": rank + 1, "district_id": hd.district_id,
            "district_name": hd.adm2, "state_name": hd.adm1,
            "lat": float(hd.lat), "lon": float(hd.lon),
            "assigned_districts_count": int(idx.size),
            "assigned_population": int(round(float(d.pop_total.iloc[idx].sum()))),
            "assigned_exposed_population": int(round(float(d.exposure_in_range.iloc[idx].fillna(0).sum()))),
            "annual_courses_served": round(float(w[idx].sum()), 2),
            "total_vials_to_store": tot,
            "total_refrigeration_liters": round(tot * vol, 2),
            "vial_inventory": inv_rows,
            "assigned_district_names": d.adm2.iloc[idx].tolist(),
        })

    dist_rows = []
    if include_districts:
        hub_rank_of = {h: r for r, h in enumerate(loc["hubs"])}
        lat_h = np.array([hj["lat"] for hj in hubs_json]); lon_h = np.array([hj["lon"] for hj in hubs_json])
        for i in range(len(d)):
            row = d.iloc[i]
            src = []
            for k, prod in enumerate(cd.products):
                if lam_k[i, k] <= 0 or prod not in prod_hubs:
                    continue
                cands = prod_hubs[prod]
                dk = haversine_km(row.lat, row.lon, lat_h[cands], lon_h[cands]) * float(net["circuity"])
                b = int(np.argmin(dk))
                src.append({"antivenom_product": prod.split(" | ")[0], "supplied_by_hub": hubs_json[cands[b]]["district_name"],
                            "hub_id": cands[b] + 1, "distance_km": round(float(dk[b]), 1),
                            "travel_time_min": int(round(float(dk[b]) / float(net["avg_speed_kmh"]) * 60)),
                            "is_primary_hub": cands[b] == hub_rank_of[assign[i]]})
            dist_rows.append({
                "district_id": row.district_id, "district": row.adm2, "state": row.adm1,
                "lat": float(row.lat), "lon": float(row.lon),
                "assigned_hub": d.adm2.iloc[assign[i]], "assigned_hub_id": hub_rank_of[assign[i]] + 1,
                "distance_km": round(float(km[i]), 1), "travel_time_min": int(round(hours[i] * 60)),
                "within_resupply_standard": bool(hours[i] <= T_rep + 1e-9),
                "annual_courses": round(float(w[i]), 3),
                "courses_no_antivenom": round(float(d.courses_no_antivenom.iloc[i]) * surge_factor, 3),
                "population": float(d.pop_total.iloc[i]), "exposed_population": float(d.exposure_in_range.iloc[i] or 0),
                "product_sourcing": src,
            })

    wsum = w.sum()
    total_vials = int(sum(h["total_vials_to_store"] for h in hubs_json))
    maxw = max(1e-12, float(w.max()))
    return {
        "country": cd.country, "iso3": cd.iso3,
        "k_stockrooms": p,
        "total_districts_optimized": int(len(d)),
        "demand_anchor": cd.anchor,
        "surge_factor_applied": surge_factor,
        "annual_courses_total": round(float(wsum), 2),
        "annual_courses_no_effective_antivenom": round(float(d.courses_no_antivenom.sum()) * surge_factor, 2),
        "no_antivenom_species": cd.no_antivenom_species,
        "product_portfolio": [{"product_id": pr, "brand_name": pr.split(" | ")[0], "species": sorted(sp_by_prod.get(pr, []))}
                              for pr in cd.products],
        "objective_course_hours_per_year": loc["objective_course_hours"],
        "mean_resupply_hours_per_course": loc["objective_course_hours"] / wsum,
        "max_travel_time_minutes": round(float(hours[w > 0].max() * 60), 1),
        "avg_travel_time_minutes": round(float(np.average(hours, weights=w) * 60), 1),
        "resupply_standard_hours": T_rep,
        "resupply_standard_in_objective": T is not None,
        "pct_courses_within_resupply_standard": round(100 * float(w[hours <= T_rep + 1e-9].sum() / wsum), 2),
        "optimality": {k: loc[k] for k in ("status", "proven_optimal", "lower_bound",
                                            "gap", "objective_recomputed", "n_demand", "n_candidates",
                                            "solve_seconds", "stage1", "heuristic", "lagrangian")},
        "total_national_vials_allocated": total_vials,
        "total_national_cold_chain_liters": round(total_vials * vol, 2),
        "inventory_policy": {"type": "(R,S) periodic review, compound-Poisson demand (exact)",
                             "review_months": inv["review_period_months"], "lead_months": inv["lead_time_months"],
                             "cycle_service_level": alpha,
                             "course_vials": {"values": v.tolist(), "probs": pi.tolist()}},
        "rationing": rationing,
        "disabled_hub": disabled_hub,
        "parameters": {k: cfg[sec][key] for k, (sec, key) in OVERRIDE_MAP.items()},
        "population_provisional": cd.provisional_population,
        "warnings": cd.warnings,
        "selected_stockroom_hubs": hubs_json,
        "district_assignments": dist_rows,
        "continuous_heatmap_data": [[float(a), float(b), round(float(c) / maxw, 4)]
                                    for a, b, c in zip(d.lat, d.lon, w) if c > 0],
        "runtime_seconds": round(time.time() - t0, 3),
    }


def p_sweep(iso3: str, p_values: List[int], overrides=None) -> List[Dict]:
    out = []
    for p in p_values:
        o = dict(overrides or {}); o["n_hubs"] = int(p)
        s = optimise_country(iso3, o, include_districts=False)
        out.append({"n_hubs": p, "mean_resupply_hours_per_course": s["mean_resupply_hours_per_course"],
                    "pct_courses_within_resupply_standard": s["pct_courses_within_resupply_standard"],
                    "total_vials": s["total_national_vials_allocated"],
                    "proven_optimal": s["optimality"]["proven_optimal"], "gap": s["optimality"]["gap"]})
    return out


def sensitivity(iso3: str, overrides=None) -> Dict:
    """One-at-a-time low/high scenarios from configs (scenarios block)."""
    cfg = load_config(overrides)
    base = optimise_country(iso3, overrides, include_districts=False)
    base_hubs = {h["district_id"] for h in base["selected_stockroom_hubs"]}
    rows = []
    for param, levels in cfg["scenarios"].items():
        for lvl in ("low", "high"):
            o = dict(overrides or {}); o[param] = levels[lvl]
            s = optimise_country(iso3, o, include_districts=False)
            hubs = {h["district_id"] for h in s["selected_stockroom_hubs"]}
            rows.append({"parameter": param, "level": lvl, "value": levels[lvl],
                         "total_vials": s["total_national_vials_allocated"],
                         "annual_courses": s["annual_courses_total"],
                         "mean_resupply_hours_per_course": s["mean_resupply_hours_per_course"],
                         "hub_overlap_with_base": len(hubs & base_hubs) / max(1, len(base_hubs)),
                         "proven_optimal": s["optimality"]["proven_optimal"]})
    return {"base": {"total_vials": base["total_national_vials_allocated"],
                     "annual_courses": base["annual_courses_total"],
                     "mean_resupply_hours_per_course": base["mean_resupply_hours_per_course"],
                     "hubs": sorted(base_hubs)}, "scenarios": rows}


def evaluate_emergency_dispatch(solution: Dict, lat: float, lon: float, product_hint: Optional[str] = None,
                                hours_since_bite: float = 0.0) -> Dict:
    """Nearest hubs (from a solved network) that hold stock of the needed product.
    Travel time here is road time from the district centroid to the hub; it is a
    logistics indicator, not clinical guidance."""
    circ = solution["parameters"]["circuity"]; spd = solution["parameters"]["avg_speed_kmh"]
    rows = []
    for h in solution["selected_stockroom_hubs"]:
        stocked = [r for r in h["vial_inventory"] if r["total_vials_allocated"] > 0 and
                   (product_hint is None or r["product_id"] == product_hint or r["brand_name"] == product_hint)]
        km = float(haversine_km(lat, lon, h["lat"], h["lon"])) * circ
        rows.append({"hub_name": h["district_name"], "state_name": h["state_name"], "lat": h["lat"], "lon": h["lon"],
                     "road_distance_km": round(km, 1), "travel_time_minutes": int(round(km / spd * 60)),
                     "stock_confirmed": bool(stocked),
                     "available_products": [r["brand_name"] for r in stocked],
                     "vials_on_hand_target": int(sum(r["total_vials_allocated"] for r in stocked))})
    rows.sort(key=lambda r: (not r["stock_confirmed"], r["road_distance_km"]))
    return {"nearest_stockrooms": rows[:5], "hours_since_bite": hours_since_bite,
            "note": "Hub resupply distances; patient care should be sought at the nearest facility holding antivenom."}