#!/usr/bin/env python3
"""
Hub inventory: periodic-review order-up-to (R, S) policy with compound-Poisson demand,
computed exactly (no normal approximation), and optimal rationing under a vial cap.

Demand over the protection interval τ = R + L (years) at hub h for product class k:

    N  ~ Poisson(μ),  μ = Λ_hk · τ          (treatment courses; Λ in courses / yr)
    X  = Σ_{n=1}^{N} V_n                      (vials),   V ∈ {v_1,…,v_m} w.p. π_1,…,π_m

Poisson splitting: X = Σ_m v_m N_m with independent N_m ~ Poisson(μ π_m), so the pmf of
X is an exact convolution of scaled Poisson pmfs on the lattice g = gcd(v).

Order-up-to level  S* = min{ s : P(X ≤ s) ≥ α }                 (cycle service level α)
Reported: E[X] (cycle stock over R+L), safety stock S* − E[X], fill rate
β = 1 − E[(X − S*)^+]/E[X], expected on-hand ≈ S* − E[D_L] − E[D_R]/2.

Rationing under a national cap C (vials):
    max  Σ_{h,k} E[min(X_hk, S_hk)]    s.t.  Σ S_hk ≤ C,  0 ≤ S_hk ≤ S*_hk
E[min(X, s)] has increments P(X > s), non-increasing in s ⇒ separable concave
resource allocation; taking the C largest increments across all items is optimal
(Gross 1956; Fox 1966). Implemented on the lattice g.
"""
from __future__ import annotations

from math import gcd
from functools import reduce
from typing import Dict, List, Tuple

import numpy as np
from scipy.signal import fftconvolve
from scipy.stats import poisson


def course_distribution(initial_dose: int, repeat_prob: float) -> Tuple[np.ndarray, np.ndarray]:
    d0 = int(initial_dose)
    if d0 <= 0 or not (0 <= repeat_prob <= 1):
        raise ValueError("invalid course parameters")
    v = np.array([d0, 2 * d0])
    pi = np.array([1 - repeat_prob, repeat_prob])
    keep = pi > 0
    return v[keep], pi[keep]


def compound_poisson_pmf(mu: float, v: np.ndarray, pi: np.ndarray, tail: float = 1e-12):
    """pmf of X on lattice g; returns (g, pmf array indexed by X/g)."""
    g = reduce(gcd, [int(x) for x in v])
    pmf = np.array([1.0])
    for vm, pm in zip(v, pi):
        lam = mu * pm
        if lam <= 0:
            continue
        nmax = int(poisson.isf(tail, lam)) + 1
        pk = poisson.pmf(np.arange(nmax + 1), lam)
        step = int(vm) // g
        comp = np.zeros(nmax * step + 1)
        comp[::step] = pk
        pmf = fftconvolve(pmf, comp) if (len(pmf) > 64 and len(comp) > 64) else np.convolve(pmf, comp)
        pmf = np.clip(pmf, 0, None)
    pmf /= pmf.sum()
    return g, pmf


def base_stock(mu_courses: float, v, pi, alpha: float, lead_share: float) -> Dict:
    """lead_share = L / (R + L)."""
    v, pi = np.asarray(v), np.asarray(pi)
    if mu_courses <= 0:
        return {"S": 0, "mean_demand": 0.0, "safety_stock": 0.0, "fill_rate": 1.0,
                "cycle_service_level": 1.0, "expected_on_hand": 0.0, "pmf": (int(v.min()), np.array([1.0]))}
    g, pmf = compound_poisson_pmf(mu_courses, v, pi)
    cdf = np.cumsum(pmf)
    q = int(np.searchsorted(cdf, alpha - 1e-12))
    S = q * g
    x = np.arange(len(pmf)) * g
    mean = float((pmf * x).sum())
    short = float((pmf * np.maximum(x - S, 0)).sum())
    on_hand = S - lead_share * mean - (1 - lead_share) * mean / 2
    return {"S": int(S), "mean_demand": mean, "safety_stock": S - mean,
            "fill_rate": 1 - short / mean, "cycle_service_level": float(cdf[q]),
            "expected_shortage": short, "expected_on_hand": float(max(on_hand, 0.0)),
            "pmf": (g, pmf)}


def ration(items: List[Dict], cap: int) -> Dict:
    """Optimal allocation of `cap` vials across items (each with 'S' and 'pmf').

    Returns allocation list and expected vials served (objective)."""
    gains, owner = [], []
    for idx, it in enumerate(items):
        g, pmf = it["pmf"]
        n_units = it["S"] // g if g else 0
        if n_units <= 0:
            continue
        surv = 1.0 - np.cumsum(pmf)                       # P(X > s) on lattice
        inc = g * surv[:n_units]                          # gain of unit u+1 = g·P(X > u·g)
        gains.append(inc)
        owner.append(np.full(n_units, idx))
    alloc = [0] * len(items)
    if not gains:
        return {"allocation": alloc, "expected_served": 0.0, "cap": cap}
    G = np.concatenate(gains)
    O = np.concatenate(owner)
    # Each unit costs g vials. All items share the course distribution (same g), so ranking
    # by gain is the exact greedy optimum of the separable concave problem.
    unit_cost = np.array([items[o]["pmf"][0] for o in O])
    order = np.argsort(-G / unit_cost, kind="stable")
    budget = cap
    served = 0.0
    for u in order:
        c = unit_cost[u]
        if c <= budget:
            budget -= c
            alloc[O[u]] += int(c)
            served += G[u]
        if budget <= 0:
            break
    return {"allocation": alloc, "expected_served": float(served), "cap": cap, "unused": int(budget)}


def expected_served(pmf_g, S: int) -> float:
    g, pmf = pmf_g
    x = np.arange(len(pmf)) * g
    return float((pmf * np.minimum(x, S)).sum())
