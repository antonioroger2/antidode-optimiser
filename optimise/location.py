#!/usr/bin/env python3
"""
Exact hub-location model with an optimality certificate.

Data (one country):
  I  demand districts with w_i > 0  (expected antivenom courses / yr)
  J  candidate hub districts (all districts of the country minus disabled ones)
  t_ij = circuity · greatcircle(i, j) / speed                         [hours]
  a_ij = 1[t_ij ≤ T]                                                  (resupply standard T)

Lexicographic objective: (1) maximise demand served within T, then
(2) minimise course-weighted resupply time.

Stage 1 – maximal covering location problem (MCLP), solved exactly with HiGHS
  Cov* = max Σ_i w_i z_i   s.t.  z_i ≤ Σ_j a_ij y_j,  Σ_j y_j = p,  y ∈ {0,1}, 0 ≤ z ≤ 1

Stage 2 – p-median under the optimal coverage
  (P)  min  Σ_ij w_i t_ij x_ij
       s.t. Σ_j x_ij = 1  ∀i ;   x_ij ≤ y_j ;   Σ_j y_j = p ;
            Σ_ij w_i a_ij x_ij ≥ Cov*  ;   x, y ∈ {0,1}

Certificate (no capacity):
  1. Upper bound: greedy + Teitz–Bart vertex substitution (lexicographic), started
     from the stage-1 solution so it is feasible for (P).
  2. Lower bound: Lagrangian relaxation of the assignment rows (λ_i) and of the
     coverage row (μ ≥ 0),
        L(λ, μ) = Σ_i λ_i + μ Cov* + Σ_{p smallest} ρ_j,
        ρ_j = Σ_i min(0, w_i t_ij − λ_i − μ w_i a_ij),
     maximised by subgradient optimisation (Held–Wolfe–Crowder; Beasley 1993).
  3. Exact candidate elimination: forcing y_j = 1 gives the bound
        L_j = L − ρ_(p) + ρ_j    (ρ_(p): p-th smallest ρ)
     If L_j > UB, no solution containing hub j can beat the incumbent ⇒ y_j = 0.
  4. The remaining (small) MILP is solved to proven optimality by HiGHS.
     If UB − LB ≤ tolerance already after step 2, the incumbent is proven optimal.
  With a capacity constraint the Lagrangian test is skipped and the full MILP
  (single-sourcing, binary x) is solved instead.

Units: objective = course-hours per year.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

import numpy as np
from scipy.sparse import coo_matrix

R_EARTH = 6371.0088
TOL = 1e-9


# ----------------------------------------------------------------------------- geometry
def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dl = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R_EARTH * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def travel_hours(lat_a, lon_a, lat_b, lon_b, circuity, speed_kmh):
    return haversine_km(np.asarray(lat_a)[:, None], np.asarray(lon_a)[:, None],
                        np.asarray(lat_b)[None, :], np.asarray(lon_b)[None, :]) * circuity / speed_kmh


# ----------------------------------------------------------------------------- HiGHS wrapper
def _highs_milp(c, A, rlo, rhi, lo, hi, integ, time_limit, gap, x0=None):
    import highspy
    A = A.tocsc()
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", float(max(1.0, time_limit)))
    h.setOptionValue("mip_rel_gap", float(gap))
    h.setOptionValue("mip_abs_gap", 1e-12)
    h.setOptionValue("random_seed", 0)
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = int(A.shape[1]), int(A.shape[0])
    lp.col_cost_ = np.asarray(c, float)
    lp.col_lower_, lp.col_upper_ = np.asarray(lo, float), np.asarray(hi, float)
    lp.row_lower_, lp.row_upper_ = np.asarray(rlo, float), np.asarray(rhi, float)
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = A.indptr.astype(np.int32)
    lp.a_matrix_.index_ = A.indices.astype(np.int32)
    lp.a_matrix_.value_ = A.data.astype(float)
    lp.integrality_ = [highspy.HighsVarType.kInteger if v else highspy.HighsVarType.kContinuous for v in integ]
    h.passModel(lp)
    if x0 is not None:
        sol = highspy.HighsSolution()
        sol.col_value = list(map(float, x0))
        sol.value_valid = True
        h.setSolution(sol)
    h.run()
    info = h.getInfo()
    status = h.modelStatusToString(h.getModelStatus())
    has_sol = info.primal_solution_status == 2
    x = np.array(h.getSolution().col_value) if has_sol else None
    return {"x": x, "obj": info.objective_function_value if has_sol else None,
            "dual_bound": info.mip_dual_bound, "gap": info.mip_gap, "status": status}


# ----------------------------------------------------------------------------- evaluation & heuristic
def _evaluate(Tm, w, S, Tmax):
    t = Tm[:, S].min(axis=1)
    cov = float(w @ (t <= Tmax + TOL)) if Tmax is not None else 0.0
    return cov, float(w @ t)


def _lex_better(a, b, tol=1e-12):
    return a[0] > b[0] + tol or (abs(a[0] - b[0]) <= tol and a[1] < b[1] - tol)


def heuristic(Tm: np.ndarray, w: np.ndarray, p: int, Tmax: Optional[float],
              init: Optional[List[int]] = None, min_cov: Optional[float] = None, max_passes: int = 100):
    """Greedy (unless `init`) + best-improvement Teitz–Bart vertex substitution on the
    lexicographic objective (max coverage, then min cost). If `min_cov` is given, moves
    must keep coverage ≥ min_cov (used for stage 2). Returns (open list, (cov, cost))."""
    n, m = Tm.shape
    covm = (Tm <= Tmax + TOL) if Tmax is not None else None
    if init is None:
        best_t = np.full(n, 1e9)
        open_ = []
        for _ in range(p):
            newt = np.minimum(best_t[:, None], Tm)
            cost = w @ newt
            cov = w @ (newt <= Tmax + TOL) if Tmax is not None else np.zeros(m)
            cost[open_] = np.inf
            cov[open_] = -np.inf
            j = int(np.lexsort((cost, -cov))[0])
            open_.append(j)
            best_t = np.minimum(best_t, Tm[:, j])
    else:
        open_ = list(init)
    cur = _evaluate(Tm, w, open_, Tmax)
    for _ in range(max_passes):
        sub = Tm[:, open_]
        order = np.argsort(sub, axis=1)
        d1 = np.take_along_axis(sub, order[:, :1], 1)[:, 0]
        d2 = np.take_along_axis(sub, order[:, 1:2], 1)[:, 0] if p > 1 else np.full(n, 1e9)
        nearest = order[:, 0]
        best_move, best_val = None, cur
        for hpos in range(p):
            t_wo = np.where(nearest == hpos, d2, d1)
            newt = np.minimum(t_wo[:, None], Tm)
            cost = w @ newt
            cov = w @ (newt <= Tmax + TOL) if Tmax is not None else np.zeros(m)
            cost[open_] = np.inf
            cov[open_] = -np.inf
            if min_cov is not None:
                cost[cov < min_cov - TOL] = np.inf
                key_cov = np.where(cov >= min_cov - TOL, min_cov, cov)   # coverage is a constraint here
                j = int(np.argmin(cost))
                cand_val = (float(key_cov[j]), float(cost[j]))
                better = np.isfinite(cost[j]) and cand_val[1] < best_val[1] - 1e-12
                if better:
                    best_val, best_move = (cur[0], cand_val[1]), (hpos, j)
            else:
                j = int(np.lexsort((cost, -cov))[0])
                if _lex_better((cov[j], cost[j]), best_val):
                    best_val, best_move = (float(cov[j]), float(cost[j])), (hpos, j)
        if best_move is None:
            break
        open_[best_move[0]] = best_move[1]
        cur = _evaluate(Tm, w, open_, Tmax)
    return open_, cur


# ----------------------------------------------------------------------------- Lagrangian
def lagrangian_bound(C: np.ndarray, Acov: Optional[np.ndarray], p: int, cov_star: Optional[float],
                     ub: float, lam0: np.ndarray, iters: int = 3000, Tm=None, w=None, Tmax=None,
                     keep: Optional[List[int]] = None):
    """Subgradient optimisation of L(λ, μ). Returns best bound, alive candidate mask,
    improved incumbent (if any primal heuristic beat `ub`), and diagnostics."""
    n, m = C.shape
    lam = lam0.astype(float).copy()
    mu = 0.0
    best_L, theta, stall = -np.inf, 2.0, 0
    alive = np.ones(m, dtype=bool)
    best_primal = None
    for it in range(iters):
        Cp = C - lam[:, None]
        if Acov is not None:
            Cp = Cp - mu * Acov
        neg = np.minimum(Cp, 0.0)
        rho = neg.sum(axis=0)
        S = np.argpartition(rho, p - 1)[:p]
        rho_p = float(np.max(rho[S]))
        L = float(lam.sum() + (mu * cov_star if Acov is not None else 0.0) + rho[S].sum())
        # exact elimination: forcing j open costs at least L - rho_p + rho_j
        Lj = L - rho_p + rho
        alive &= ~(Lj > ub + 1e-10 * max(1.0, abs(ub)))
        if keep is not None:
            alive[keep] = True
        if L > best_L + 1e-12:
            best_L, stall = L, 0
        else:
            stall += 1
            if stall >= 25:
                theta *= 0.5
                stall = 0
        # primal heuristic: evaluate the Lagrangian hub set
        if Tm is not None and it % 20 == 0:
            cov_s, cost_s = _evaluate(Tm, w, list(S), Tmax)
            feasible = cov_star is None or cov_s >= cov_star - TOL
            if feasible and cost_s < ub - 1e-12:
                ub, best_primal = cost_s, list(map(int, S))
        if (ub - best_L) <= 1e-9 * max(1.0, abs(ub)) or theta < 1e-5:
            break
        X = (Cp[:, S] < 0)
        g = 1.0 - X.sum(axis=1)
        gnorm = float(g @ g)
        gmu = 0.0
        if Acov is not None:
            gmu = float(cov_star - (Acov[:, S] * X).sum())
            if mu <= 0 and gmu < 0:
                gmu = 0.0
            gnorm += gmu * gmu
        if gnorm <= 1e-18:
            break  # λ optimal for the relaxation and its solution is feasible
        step = theta * (ub - L) / gnorm
        lam += step * g
        if Acov is not None:
            mu = max(0.0, mu + step * gmu)
    return {"lower_bound": best_L, "alive": alive, "ub": ub, "primal": best_primal,
            "iterations": it + 1, "mu": mu}


# ----------------------------------------------------------------------------- MILP blocks
def _mclp(Tm, Wn, p, T, time_limit, gap, y_init):
    n, m = Tm.shape
    cover = Tm <= T + TOL
    ri, cj = np.nonzero(cover)
    A = coo_matrix((np.r_[-np.ones(len(ri)), np.ones(n), np.ones(m)],
                    (np.r_[ri, np.arange(n), np.full(m, n)],
                     np.r_[cj, m + np.arange(n), np.arange(m)])), shape=(n + 1, m + n))
    y0 = np.zeros(m); y0[y_init] = 1
    z0 = cover[:, y_init].any(axis=1).astype(float)
    r = _highs_milp(np.r_[np.zeros(m), -Wn], A, np.r_[np.full(n, -np.inf), p], np.r_[np.zeros(n), p],
                    np.zeros(m + n), np.ones(m + n), np.r_[np.ones(m), np.zeros(n)], time_limit, gap,
                    np.r_[y0, z0])
    if r["x"] is None:
        raise RuntimeError(f"coverage stage failed: {r['status']}")
    y = list(np.flatnonzero(r["x"][:m] > 0.5))
    return {"cov": -r["obj"], "upper_bound": -r["dual_bound"], "gap": r["gap"], "status": r["status"], "y": y}


def _pmedian_milp(Tm, Wn, p, T, cov_star, cols, time_limit, gap, incumbent, capacity_n=None):
    """Dense p-median over candidate columns `cols` (all demand rows)."""
    n = Tm.shape[0]
    m = len(cols)
    Tc = Tm[:, cols]
    xi = np.repeat(np.arange(n), m)
    xj = np.tile(np.arange(m), n)
    nX = n * m
    N = nX + m
    rows, cc, vals, rlo, rhi = [], [], [], [], []
    rows.append(xi); cc.append(np.arange(nX)); vals.append(np.ones(nX)); rlo.append(np.ones(n)); rhi.append(np.ones(n))
    r = n
    rows += [r + np.arange(nX), r + np.arange(nX)]; cc += [np.arange(nX), nX + xj]
    vals += [np.ones(nX), -np.ones(nX)]; rlo.append(np.full(nX, -np.inf)); rhi.append(np.zeros(nX)); r += nX
    rows.append(np.full(m, r)); cc.append(nX + np.arange(m)); vals.append(np.ones(m)); rlo.append([p]); rhi.append([p]); r += 1
    if cov_star is not None:
        a = (Wn[:, None] * (Tc <= T + TOL)).ravel()
        rows.append(np.full(nX, r)); cc.append(np.arange(nX)); vals.append(a)
        rlo.append([cov_star - 1e-9]); rhi.append([np.inf]); r += 1
    integ = np.r_[np.zeros(nX), np.ones(m)]
    if capacity_n is not None:
        rows += [r + xj, r + np.arange(m)]; cc += [np.arange(nX), nX + np.arange(m)]
        vals += [np.repeat(Wn, m), -capacity_n * np.ones(m)]; rlo.append(np.full(m, -np.inf)); rhi.append(np.zeros(m)); r += m
        integ = np.ones(N)
    A = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cc))), shape=(r, N))
    c = np.r_[(Wn[:, None] * Tc).ravel(), np.zeros(m)]
    x0 = None
    if incumbent is not None and capacity_n is None:
        loc = [cols.index(j) for j in incumbent]
        y0 = np.zeros(m); y0[loc] = 1
        near = np.array(loc)[np.argmin(Tc[:, loc], axis=1)]
        xs = np.zeros((n, m)); xs[np.arange(n), near] = 1
        x0 = np.r_[xs.ravel(), y0]
    res = _highs_milp(c, A, np.concatenate([np.asarray(v, float) for v in rlo]),
                      np.concatenate([np.asarray(v, float) for v in rhi]),
                      np.zeros(N), np.ones(N), integ, time_limit, gap, x0)
    if res["x"] is None:
        raise RuntimeError(f"p-median MILP failed: {res['status']}")
    y = [cols[k] for k in np.flatnonzero(res["x"][nX:] > 0.5)]
    xa = None
    if capacity_n is not None:
        X = res["x"][:nX].reshape(n, m)
        xa = np.array(cols)[np.argmax(X, axis=1)]
    return {"y": y, "obj": res["obj"], "dual_bound": res["dual_bound"], "gap": res["gap"],
            "status": res["status"], "assign_cols": xa}


# ----------------------------------------------------------------------------- driver
def solve_location(lat, lon, w, p: int, *, circuity: float, speed_kmh: float,
                   max_hours: Optional[float] = None, candidate_mask=None,
                   disabled: Optional[List[int]] = None, capacity: Optional[float] = None,
                   time_limit: float = 120.0, mip_rel_gap: float = 0.0,
                   lagrange_iters: int = 3000, max_dense_vars: int = 1_500_000, **_ignored) -> Dict:
    t0 = time.time()
    lat, lon, w = np.asarray(lat, float), np.asarray(lon, float), np.asarray(w, float)
    n_all = len(w)
    cand = np.arange(n_all) if candidate_mask is None else np.flatnonzero(candidate_mask)
    if disabled:
        cand = np.setdiff1d(cand, np.asarray(disabled, int))
    m = len(cand)
    if p < 1:
        raise ValueError("p must be ≥ 1")
    if m < p:
        raise ValueError(f"only {m} candidate hubs for p={p}")
    dem = np.flatnonzero(w > 0)
    if dem.size == 0:
        raise ValueError("no positive demand")
    W = w[dem]
    scale = W.sum()
    Wn = W / scale
    Tm = travel_hours(lat[dem], lon[dem], lat[cand], lon[cand], circuity, speed_kmh)
    T = max_hours
    n = len(dem)
    log = {}

    # 1) heuristic (lexicographic) – also reported as the "heuristic-only" benchmark
    th = time.time()
    h_open, h_val = heuristic(Tm, Wn, p, T)
    log["heuristic"] = {"hubs": cand[h_open].tolist(), "coverage_share": h_val[0] if T is not None else None,
                        "objective_course_hours": h_val[1] * scale, "seconds": round(time.time() - th, 3)}

    # 2) stage 1: exact MCLP
    cov_star, stage1 = None, None
    if T is not None:
        s1 = _mclp(Tm, Wn, p, T, time_limit * 0.3, mip_rel_gap, h_open)
        cov_star = s1["cov"]
        stage1 = {k: s1[k] for k in ("cov", "upper_bound", "gap", "status")}
        stage1["coverage_share"] = stage1.pop("cov")
        # incumbent feasible for stage 2: start interchange from the better-covering set
        start = h_open if h_val[0] >= cov_star - TOL else s1["y"]
        inc, inc_val = heuristic(Tm, Wn, p, T, init=list(start), min_cov=cov_star)
    else:
        inc, inc_val = h_open, h_val
    ub = inc_val[1]

    # 3) Lagrangian bound + exact elimination (uncapacitated only)
    lag = None
    cols = list(range(m))
    if capacity is None:
        C = Wn[:, None] * Tm
        Acov = (Wn[:, None] * (Tm <= T + TOL)) if T is not None else None
        lam0 = C[np.arange(n), np.array(inc)[np.argmin(Tm[:, inc], axis=1)]]
        lag = lagrangian_bound(C, Acov, p, cov_star, ub, lam0, iters=lagrange_iters,
                               Tm=Tm, w=Wn, Tmax=T, keep=list(inc))
        if lag["primal"] is not None and lag["ub"] < ub:
            inc, ub = lag["primal"], lag["ub"]
        cols = sorted(set(np.flatnonzero(lag["alive"]).tolist()) | set(inc))
        log["lagrangian"] = {"lower_bound": lag["lower_bound"] * scale, "iterations": lag["iterations"],
                             "candidates_remaining": len(cols), "candidates_total": m,
                             "gap_after_lagrangian": (ub - lag["lower_bound"]) / max(ub, 1e-15)}

    # 4) exact MILP on the remaining candidates (skip if the Lagrangian already closed the gap)
    closed = lag is not None and (ub - lag["lower_bound"]) <= 1e-9 * max(1.0, ub)
    hubs_local, lb, status, gap, assign_cols = inc, (lag["lower_bound"] if lag else None), "lagrangian_gap_closed", 0.0, None
    if not closed:
        if n * len(cols) > max_dense_vars:
            status = f"MILP skipped (n×m'={n * len(cols)} > {max_dense_vars}); certified gap from Lagrangian bound"
            gap = (ub - lb) / max(ub, 1e-15) if lb is not None else None
        else:
            remaining = max(5.0, time_limit - (time.time() - t0))
            capn = None if capacity is None else capacity / scale
            r = _pmedian_milp(Tm, Wn, p, T, cov_star, cols, remaining, mip_rel_gap,
                              inc if set(inc) <= set(cols) else None, capn)
            hubs_local, status = r["y"], r["status"]
            milp_lb = r["dual_bound"]
            lb = max(lb, milp_lb) if lb is not None else milp_lb
            ub = r["obj"]
            gap = max(0.0, (ub - lb) / max(ub, 1e-15))
            assign_cols = r["assign_cols"]
    hubs = cand[np.array(hubs_local)]

    # 5) assignment of ALL districts (incl. zero demand) to nearest open hub
    Th = travel_hours(lat, lon, lat[hubs], lon[hubs], circuity, speed_kmh)
    near = np.argmin(Th, axis=1)
    assign = hubs[near]
    t_assign = Th[np.arange(n_all), near]
    if assign_cols is not None:  # capacitated: MILP assignment for demand rows
        assign[dem] = cand[assign_cols]
        t_assign[dem] = Tm[np.arange(n), assign_cols]
    recomputed = float(np.sum(w * t_assign))
    covered = None if T is None else float(np.sum(w[t_assign <= T + TOL]) / w.sum())
    proven = gap is not None and gap <= max(mip_rel_gap, 1e-6) and \
        (stage1 is None or (stage1["gap"] or 0.0) <= max(mip_rel_gap, 1e-6))
    return {
        "hubs": hubs.tolist(),
        "assignment": assign.tolist(),
        "travel_hours": t_assign.tolist(),
        "objective_course_hours": recomputed,
        "objective_recomputed": recomputed,
        "lower_bound": None if lb is None else lb * scale,
        "gap": gap,
        "status": status,
        "proven_optimal": bool(proven),
        "coverage_share": covered,
        "stage1": stage1,
        "heuristic": log["heuristic"],
        "lagrangian": log.get("lagrangian"),
        "n_demand": int(n),
        "n_candidates": int(m),
        "solve_seconds": round(time.time() - t0, 3),
    }


def brute_force(lat, lon, w, p, *, circuity, speed_kmh, max_hours=None, disabled=None):
    """Exhaustive enumeration (tests only). Lexicographic: max coverage, then min course-hours."""
    from itertools import combinations
    n = len(w)
    cand = [j for j in range(n) if not disabled or j not in disabled]
    D = travel_hours(lat, lon, lat, lon, circuity, speed_kmh)
    best = None
    for S in combinations(cand, p):
        t = D[:, list(S)].min(axis=1)
        cov = 0.0 if max_hours is None else float(np.sum(w[t <= max_hours + 1e-9]))
        cost = float(np.sum(w * t))
        key = (-round(cov, 12), cost)
        if best is None or key < best[0]:
            best = (key, S)
    return {"hubs": list(best[1]), "coverage": -best[0][0], "objective": best[0][1]}
