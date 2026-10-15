"""Exactness tests for the location model: compare against exhaustive enumeration."""
import itertools

import numpy as np
import pytest

from optimise.location import brute_force, heuristic, solve_location, travel_hours


def _instance(rng, n):
    lat = rng.uniform(5, 25, n)
    lon = rng.uniform(70, 90, n)
    w = rng.exponential(1.0, n) * (rng.random(n) > 0.15)
    if w.sum() == 0:
        w[0] = 1.0
    return lat, lon, w


@pytest.mark.parametrize("seed", range(30))
def test_matches_brute_force(seed):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(8, 15))
    p = int(rng.integers(1, 5))
    lat, lon, w = _instance(rng, n)
    T = None if seed % 2 == 0 else float(rng.uniform(2, 15))
    dis = [int(rng.integers(0, n))] if seed % 3 == 0 else None
    r = solve_location(lat, lon, w, p, circuity=1.35, speed_kmh=40, max_hours=T, disabled=dis)
    b = brute_force(lat, lon, w, p, circuity=1.35, speed_kmh=40, max_hours=T, disabled=dis)
    assert r["proven_optimal"]
    assert r["objective_course_hours"] == pytest.approx(b["objective"], rel=1e-7, abs=1e-9)
    if T is not None:
        assert r["coverage_share"] * w.sum() == pytest.approx(b["coverage"], abs=1e-9)
    if dis:
        assert dis[0] not in r["hubs"]
    assert len(r["hubs"]) == p


def test_lower_bound_never_exceeds_optimum():
    rng = np.random.default_rng(99)
    for _ in range(15):
        lat, lon, w = _instance(rng, 12)
        r = solve_location(lat, lon, w, 3, circuity=1.3, speed_kmh=50)
        assert r["lower_bound"] <= r["objective_course_hours"] * (1 + 1e-9)


def test_assignment_is_nearest_open_hub():
    rng = np.random.default_rng(5)
    lat, lon, w = _instance(rng, 40)
    r = solve_location(lat, lon, w, 4, circuity=1.35, speed_kmh=40)
    Th = travel_hours(lat, lon, lat[r["hubs"]], lon[r["hubs"]], 1.35, 40)
    assert np.allclose(np.asarray(r["travel_hours"]), Th.min(axis=1))


def test_capacity_respected():
    rng = np.random.default_rng(7)
    lat, lon, w = _instance(rng, 14)
    cap = 0.45 * w.sum()
    r = solve_location(lat, lon, w, 3, circuity=1.35, speed_kmh=40, capacity=cap)
    load = {h: 0.0 for h in r["hubs"]}
    for i, h in enumerate(r["assignment"]):
        load[h] += w[i]
    assert max(load.values()) <= cap + 1e-6


def test_capacitated_matches_enumeration_small():
    rng = np.random.default_rng(11)
    lat, lon, w = _instance(rng, 7)
    p, cap = 2, 0.6 * w.sum()
    D = travel_hours(lat, lon, lat, lon, 1.35, 40)
    best = np.inf
    for S in itertools.combinations(range(7), p):
        for a in itertools.product(S, repeat=7):  # exhaustive single-sourcing assignment
            loads = {h: 0.0 for h in S}
            for i, h in enumerate(a):
                loads[h] += w[i]
            if max(loads.values()) <= cap + 1e-12:
                best = min(best, sum(w[i] * D[i, a[i]] for i in range(7)))
    r = solve_location(lat, lon, w, p, circuity=1.35, speed_kmh=40, capacity=cap)
    assert r["objective_course_hours"] == pytest.approx(best, rel=1e-7)


def test_heuristic_never_beats_exact():
    rng = np.random.default_rng(3)
    for _ in range(10):
        lat, lon, w = _instance(rng, 30)
        r = solve_location(lat, lon, w, 3, circuity=1.35, speed_kmh=40)
        assert r["heuristic"]["objective_course_hours"] >= r["objective_course_hours"] * (1 - 1e-9)


def test_invalid_inputs():
    lat, lon, w = np.zeros(3), np.zeros(3), np.zeros(3)
    with pytest.raises(ValueError):
        solve_location(lat, lon, w, 1, circuity=1.3, speed_kmh=40)
    with pytest.raises(ValueError):
        solve_location(lat, lon, np.ones(3), 5, circuity=1.3, speed_kmh=40)
