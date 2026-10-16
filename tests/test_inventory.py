"""Inventory model: exact compound-Poisson quantiles and optimal rationing."""
import itertools

import numpy as np
import pytest

from optimise.inventory import (base_stock, compound_poisson_pmf, course_distribution, expected_served,
                                ration)


@pytest.mark.parametrize("mu", [0.01, 0.3, 2.0, 15.0, 400.0])
def test_pmf_moments(mu):
    v, pi = course_distribution(10, 0.3)
    g, pmf = compound_poisson_pmf(mu, v, pi)
    x = np.arange(len(pmf)) * g
    assert pmf.sum() == pytest.approx(1.0, abs=1e-12)
    ev = (v * pi).sum()
    ev2 = (v ** 2 * pi).sum()
    assert (pmf * x).sum() == pytest.approx(mu * ev, rel=1e-9)
    var = (pmf * x ** 2).sum() - (pmf * x).sum() ** 2
    assert var == pytest.approx(mu * ev2, rel=1e-6)          # compound Poisson: Var = μ E[V²]


@pytest.mark.parametrize("mu,alpha", [(0.5, 0.95), (3.0, 0.99), (40.0, 0.99), (250.0, 0.999)])
def test_quantile_vs_monte_carlo(mu, alpha):
    rng = np.random.default_rng(0)
    v, pi = course_distribution(10, 0.3)
    r = base_stock(mu, v, pi, alpha, 0.25)
    N = rng.poisson(mu, 400_000)
    X = 10 * (N + rng.binomial(N, 0.3))
    assert r["cycle_service_level"] >= alpha
    assert (X <= r["S"]).mean() >= alpha - 0.002
    assert (X <= r["S"] - 10).mean() < alpha + 0.002          # S is the smallest such level
    assert r["mean_demand"] == pytest.approx(X.mean(), rel=0.01)


def test_zero_demand():
    v, pi = course_distribution(10, 0.3)
    r = base_stock(0.0, v, pi, 0.99, 0.25)
    assert r["S"] == 0 and r["fill_rate"] == 1.0


def test_rationing_is_optimal_and_within_cap():
    v, pi = course_distribution(10, 0.3)
    items = [base_stock(m, v, pi, 0.99, 0.25) for m in (0.4, 1.5, 5.0)]
    for cap in (0, 20, 50, 90, 140):
        r = ration(items, cap)
        assert sum(r["allocation"]) <= cap
        best = max(sum(expected_served(it["pmf"], a) for it, a in zip(items, al))
                   for al in itertools.product(*[range(0, it["S"] + 1, 10) for it in items]) if sum(al) <= cap)
        got = sum(expected_served(it["pmf"], a) for it, a in zip(items, r["allocation"]))
        assert got == pytest.approx(best, abs=1e-9)


def test_laminar_allocation_matches_brute_force():
    """Hub caps nested in a national cap: greedy must equal exhaustive search."""
    import itertools
    v, pi = course_distribution(10, 0.3)
    mus = [(0.6, 2.0), (4.0,)]                     # hub 0 has two products, hub 1 one
    items = [[base_stock(m, v, pi, 0.99, 0.25) for m in hub] for hub in mus]
    caps, V = [60, 70], 100
    best = -1
    grids = [range(0, it["S"] + 1, 10) for hub in items for it in hub]
    flat = [it for hub in items for it in hub]
    for al in itertools.product(*grids):
        if al[0] + al[1] > caps[0] or al[2] > caps[1] or sum(al) > V:
            continue
        best = max(best, sum(expected_served(it["pmf"], a) for it, a in zip(flat, al)))
    # greedy as in optimise.allocation stage B (floors = 0)
    gains = []
    for h, hub in enumerate(items):
        for k, it in enumerate(hub):
            g, pmf = it["pmf"]
            surv = 1 - np.cumsum(pmf)
            gains += [(g * surv[u], h, k, g) for u in range(it["S"] // g)]
    gains.sort(key=lambda x: -x[0])
    alloc = [[0] * len(hub) for hub in items]
    room, budget = list(caps), V
    for gain, h, k, g in gains:
        if budget >= g and room[h] >= g:
            alloc[h][k] += g; room[h] -= g; budget -= g
    got = sum(expected_served(it["pmf"], a) for hub, ah in zip(items, alloc) for it, a in zip(hub, ah))
    assert got == pytest.approx(best, abs=1e-9)
