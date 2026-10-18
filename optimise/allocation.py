#!/usr/bin/env python3
"""
Post-location stock allocation with hub operating capacity.

Hubs H are fixed by the location model. Each hub h has a cold-storage capacity
Cap_h (vials) and the country has a national supply V (vials). Stock must be placed
where risk is highest while every low-demand ("dormant") catchment keeps at least a
minimum emergency reserve.

Stage A – capacitated demand routing (LP, HiGHS)
    min  Σ_i Σ_h w_i t_ih f_ih  +  B Σ_i w_i u_i
    s.t. Σ_h f_ih + u_i = 1                         ∀ i      (all demand routed or reported)
         Σ_i w_i τ v̄ f_ih ≤ Ĉ_h                     ∀ h      (mean cycle vials fit the hub)
         f, u ≥ 0
  w_i: courses/yr, t_ih: resupply hours, τ = (R+L) in years, v̄ = mean vials/course.
  Ĉ_h starts at Cap_h and is reduced by the safety stock of the resulting
  order-up-to level until S_h ≤ Cap_h (fixed point, ≤ 8 iterations).
  Overflow from a full hub is re-routed to the next-best hub (f may split a district).

Stage B – risk-prioritised stock (exact greedy)
    max  Σ_{h,k} E[min(X_hk, S_hk)]
    s.t. Σ_k S_hk ≤ Cap_h  ∀ h ;  Σ_{h,k} S_hk ≤ V ;  F_hk ≤ S_hk ≤ S*_hk
  X_hk is compound-Poisson demand over R+L, S*_hk the unconstrained order-up-to level
  and F_hk = min(S*_hk, floor_courses · v_max) the dormant-catchment reserve.
  The objective is separable concave and the constraints form a laminar family
  (hub caps nested in the national cap), so taking marginal units in decreasing
  order of g·P(X > s) is optimal. High-risk hubs win marginal vials because their
  P(X > s) stays large for longer, which is exactly "vials closer to high risk".
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

try:
    from .demand import country_demand
    from .inventory import base_stock, course_distribution, expected_served
    from .location import travel_hours
except ImportError:  # pragma: no cover
    from demand import country_demand  # type: ignore
    from inventory import base_stock, course_distribution, expected_served  # type: ignore
    from location import travel_hours  # type: ignore


def _route(w, T, cap_eff, tau_vbar):
    n, H = T.shape
    big = 10.0 * max(1.0, float(T.max()))
    nf = n * H
    c = np.r_[(w[:, None] * T).ravel(), big * w]
    # equality: Σ_h f_ih + u_i = 1
    rows = np.r_[np.repeat(np.arange(n), H), np.arange(n)]
    cols = np.r_[np.arange(nf), nf + np.arange(n)]
    A_eq = coo_matrix((np.ones(nf + n), (rows, cols)), shape=(n, nf + n)).tocsr()
    # capacity: Σ_i w_i τ v̄ f_ih ≤ Ĉ_h
    hi = np.tile(np.arange(H), n)
    A_ub = coo_matrix((np.repeat(w, H) * tau_vbar, (hi, np.arange(nf))), shape=(H, nf + n)).tocsr()
    res = linprog(c, A_ub=A_ub, b_ub=cap_eff, A_eq=A_eq, b_eq=np.ones(n), bounds=(0, None), method="highs")
    if res.status != 0:
        raise RuntimeError(f"routing LP failed: {res.message}")
    return res.x[:nf].reshape(n, H), res.x[nf:]


def allocate(iso3: str, cfg: dict, hub_district_ids, *, hub_capacity_vials=None,
             national_supply_vials: Optional[float] = None, floor_courses: int = 1,
             surge_factor: float = 1.0, cd=None, reserve_pct_national: float = 0.0) -> Dict:
    inv, crs, net = cfg["inventory"], cfg["course"], cfg["network"]
    cd = cd if cd is not None else country_demand(iso3, cfg)
    d = cd.districts
    lam = cd.product_courses.to_numpy(float) * surge_factor           # n × K
    w_all = lam.sum(axis=1)
    idx = {k: i for i, k in enumerate(d.district_id)}
    hubs = [idx[h] for h in hub_district_ids]
    H, K = len(hubs), lam.shape[1]
    dem = np.flatnonzero(w_all > 0)
    w = w_all[dem]
    T = travel_hours(d.lat.to_numpy()[dem], d.lon.to_numpy()[dem], d.lat.to_numpy()[hubs], d.lon.to_numpy()[hubs],
                     float(net["circuity"]), float(net["avg_speed_kmh"]))
    tau = (float(inv["review_period_months"]) + float(inv["lead_time_months"])) / 12.0
    lead_share = float(inv["lead_time_months"]) / (float(inv["review_period_months"]) + float(inv["lead_time_months"]))
    alpha = float(inv["cycle_service_level"])
    v, pi = course_distribution(int(crs["initial_dose_vials"]), float(crs["repeat_dose_probability"]))
    vbar, vmax = float((v * pi).sum()), int(v.max())

    if hub_capacity_vials is None:
        cap = np.full(H, np.inf)
    elif np.isscalar(hub_capacity_vials):
        cap = np.full(H, float(hub_capacity_vials))
    else:
        cap = np.asarray(hub_capacity_vials, float)
    V = np.inf if national_supply_vials in (None, 0) else float(national_supply_vials)

    # ---------------- Stage A: route demand under capacity (fixed point on safety stock)
    cap_eff = np.where(np.isfinite(cap), cap, 1e18)
    nearest = np.argmin(T, axis=1)
    # If the whole network is too small for even the mean demand, nobody is dropped:
    # routing capacities are scaled up uniformly (every hub equally overloaded) and the
    # shortage shows up as a lower fill rate in stage B, where the true capacity binds.
    mean_need = float(w.sum()) * tau * vbar
    overloaded = bool(np.all(np.isfinite(cap)) and cap.sum() < mean_need)
    if overloaded:
        cap_eff = cap * (mean_need / max(cap.sum(), 1e-9)) * (1 + 1e-9)
    for it in range(1 if overloaded else 8):
        f, u = _route(w, T, cap_eff, tau * vbar)
        Lam = f.T @ lam[dem]                                            # H × K courses/yr
        items = [[base_stock(Lam[h, k] * tau, v, pi, alpha, lead_share) for k in range(K)] for h in range(H)]
        S_h = np.array([sum(it["S"] for it in row) for row in items], float)
        over = S_h - cap
        if np.all(over <= 1e-9):
            break
        cap_eff = np.where(over > 0, np.maximum(0.0, cap_eff - over), cap_eff)
    routing_iters = it + 1

    # ---------------- Stage B: floors + laminar greedy
    floors = np.zeros((H, K), int)
    targets = np.zeros((H, K), int)
    for h in range(H):
        for k in range(K):
            if Lam[h, k] > 0:
                targets[h, k] = items[h][k]["S"]
                floors[h, k] = min(targets[h, k], floor_courses * vmax)
    # National reserve rule: a pool of reserve_pct of total need, shared equally by the hubs,
    # never above a hub's own optimal level (stock beyond that would only expire).
    if reserve_pct_national > 0:
        per_hub = reserve_pct_national / 100.0 * targets.sum() / H
        g0 = int(v.min())
        for h in range(H):
            tot = targets[h].sum()
            if tot <= 0:
                continue
            want = min(per_hub, tot)
            for k in range(K):
                share = int(np.floor(want * targets[h, k] / tot / g0)) * g0
                floors[h, k] = max(floors[h, k], min(targets[h, k], share))
    alloc = floors.copy()
    floor_feasible = bool(np.all(floors.sum(1) <= cap + 1e-9) and floors.sum() <= V + 1e-9)
    if not floor_feasible:  # scale floors down to whole courses that fit (report it)
        for h in range(H):
            while alloc[h].sum() > cap[h] and alloc[h].max() > 0:
                alloc[h, int(np.argmax(alloc[h]))] -= vmax if alloc[h].max() >= vmax else alloc[h].max()
    gains = []
    for h in range(H):
        for k in range(K):
            g, pmf = items[h][k]["pmf"]
            surv = 1.0 - np.cumsum(pmf)
            for unit in range(alloc[h, k] // g, targets[h, k] // g):
                gains.append((g * surv[unit] if unit < len(surv) else 0.0, h, k, g))
    gains.sort(key=lambda x: -x[0])
    room = cap - alloc.sum(1)
    budget = V - alloc.sum()
    for gain, h, k, g in gains:
        if budget < g:
            break
        if room[h] >= g:
            alloc[h, k] += g
            room[h] -= g
            budget -= g

    # ---------------- report
    hub_rows = []
    for hpos, hi in enumerate(hubs):
        served = sum(expected_served(items[hpos][k]["pmf"], alloc[hpos, k]) for k in range(K))
        mean = sum(items[hpos][k]["mean_demand"] for k in range(K))
        unconstrained = sum(expected_served(items[hpos][k]["pmf"], targets[hpos, k]) for k in range(K))
        own = f[nearest == hpos, hpos].sum() if (nearest == hpos).any() else 0.0
        n_near = int((nearest == hpos).sum())
        hub_rows.append({
            "hub_id": hpos + 1, "district_id": d.district_id.iat[hi], "district_name": d.adm2.iat[hi],
            "state_name": d.adm1.iat[hi], "capacity_vials": None if not np.isfinite(cap[hpos]) else int(cap[hpos]),
            "target_vials": int(targets[hpos].sum()), "allocated_vials": int(alloc[hpos].sum()),
            "floor_vials": int(floors[hpos].sum()),
            "utilisation_pct": None if not np.isfinite(cap[hpos]) else round(100 * alloc[hpos].sum() / max(cap[hpos], 1), 1),
            "annual_courses_routed": round(float(Lam[hpos].sum()), 2),
            "fill_rate": round(served / mean, 4) if mean > 0 else 1.0,
            "expected_vials_short_per_cycle": round(unconstrained - served, 1),
            "nearest_districts": n_near,
            "nearest_demand_kept_pct": round(100 * own / n_near, 1) if n_near else None,
            "products": [{"product": cd.products[k].split(" | ")[0], "target": int(targets[hpos, k]),
                          "allocated": int(alloc[hpos, k]), "floor": int(floors[hpos, k])} for k in range(K)
                         if targets[hpos, k] > 0],
        })
    rerouted = float((w * (1 - f[np.arange(len(dem)), nearest] - u)).sum())
    split = [{"district": d.adm2.iat[dem[i]], "state": d.adm1.iat[dem[i]],
              "courses": round(float(w[i]), 2),
              "served_by": {d.adm2.iat[hubs[h]]: round(float(f[i, h]), 3) for h in np.flatnonzero(f[i] > 1e-6)}}
             for i in np.flatnonzero(f[np.arange(len(dem)), nearest] < 1 - 1e-6)][:200]
    total_mean = sum(items[h][k]["mean_demand"] for h in range(H) for k in range(K)) \
        + float((w * u).sum()) * tau * vbar                     # unrouted demand counts as unmet
    total_served = sum(expected_served(items[h][k]["pmf"], alloc[h, k]) for h in range(H) for k in range(K))
    return {
        "iso3": cd.iso3, "country": cd.country,
        "parameters": {"hub_capacity_vials": None if hub_capacity_vials is None else
                       (list(map(int, cap)) if not np.isscalar(hub_capacity_vials) else hub_capacity_vials),
                       "national_supply_vials": None if not np.isfinite(V) else int(V),
                       "floor_courses": floor_courses, "reserve_pct_national": reserve_pct_national,
                       "surge_factor": surge_factor,
                       "course_vials_max": vmax, "cycle_service_level": alpha},
        "summary": {
            "vials_target_unconstrained": int(targets.sum()),
            "vials_allocated": int(alloc.sum()),
            "network_fill_rate": round(total_served / total_mean, 4) if total_mean > 0 else 1.0,
            "expected_vials_short_per_cycle": round(total_mean - total_served, 1),
            "courses_rerouted_per_year": round(rerouted, 2),
            "pct_courses_rerouted": round(100 * rerouted / w.sum(), 2),
            "courses_unrouted_per_year": round(float((w * u).sum()), 2),
            "floors_feasible": floor_feasible,
            "network_overloaded": overloaded,
            "hubs_at_capacity": int(sum(1 for r in hub_rows if r["utilisation_pct"] is not None and r["utilisation_pct"] >= 99.5)),
            "routing_iterations": routing_iters,
        },
        "hubs": hub_rows,
        "rerouted_districts": split,
        "method": "capacitated routing LP (HiGHS) + laminar greedy (exact for separable concave objective)",
    }


def n_minus_1(iso3: str, cfg: dict, hub_district_ids, designed_vials, *, capacity_pct: float = 100.0,
              target_fill: float = 0.99, surge_factor: float = 1.0, floor_courses: int = 1,
              max_pct: float = 300.0, tol_pct: float = 1.0, reserve_pct_national: float = 0.0) -> Dict:
    """Single-hub-failure analysis with the other hubs kept where they are.

    For every hub h: remove it, give each remaining hub capacity_pct % of its designed stock,
    report the network fill rate, and find (bisection) the smallest uniform capacity % at
    which the remaining hubs still reach `target_fill`.
    """
    cd = country_demand(iso3, cfg)
    designed = dict(zip(hub_district_ids, designed_vials))

    def fill(out, pct):
        rem = [i for i in hub_district_ids if i != out]
        r = allocate(iso3, cfg, rem, hub_capacity_vials=[pct / 100.0 * designed[i] for i in rem],
                     floor_courses=floor_courses, surge_factor=surge_factor, cd=cd,
                     reserve_pct_national=reserve_pct_national)
        return r["summary"]["network_fill_rate"], r["summary"]["pct_courses_rerouted"]

    rows = []
    for out in hub_district_ids:
        f_now, rer = fill(out, capacity_pct)
        lo, hi = 0.0, max_pct
        if fill(out, hi)[0] < target_fill:
            need = None
        else:
            while hi - lo > tol_pct:
                mid = (lo + hi) / 2
                if fill(out, mid)[0] >= target_fill:
                    hi = mid
                else:
                    lo = mid
            need = round(hi, 1)
        i = list(cd.districts.district_id).index(out)
        rows.append({"failed_hub": cd.districts.adm2.iat[i], "state": cd.districts.adm1.iat[i], "district_id": out,
                     "fill_rate_at_capacity": round(f_now, 4), "pct_courses_rerouted": rer,
                     "capacity_pct_needed": need})
    needs = [r["capacity_pct_needed"] for r in rows if r["capacity_pct_needed"] is not None]
    worst = min(rows, key=lambda r: r["fill_rate_at_capacity"]) if rows else None
    return {"target_fill": target_fill, "capacity_pct_tested": capacity_pct,
            "required_capacity_pct": max(needs) if len(needs) == len(rows) else None,
            "worst_case_hub": worst["failed_hub"] if worst else None,
            "worst_case_fill_rate": worst["fill_rate_at_capacity"] if worst else None,
            "rows": sorted(rows, key=lambda r: r["fill_rate_at_capacity"])}