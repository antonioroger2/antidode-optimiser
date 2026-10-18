"""End-to-end verification through the internal Flask API."""
import numpy as np
import pytest

from optimise.app import app


@pytest.fixture(scope="module")
def client():
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(scope="module")
def india(client):
    r = client.post("/api/optimize_stockrooms", json={"country": "India", "num_stockrooms": 8})
    assert r.status_code == 200, r.json
    return r.json


def test_countries(client):
    r = client.get("/api/countries")
    data = r.json
    assert r.status_code == 200 and len(data) > 100
    ind = next(c for c in data if c["ISO_3_CODE"] == "IND")
    assert ind["population_provisional"] is False


def test_india_certified_optimal(india):
    o = india["optimality"]
    assert o["proven_optimal"] is True
    assert o["gap"] <= 1e-6
    assert o["lower_bound"] <= india["objective_course_hours_per_year"] * (1 + 1e-9)
    assert india["objective_course_hours_per_year"] <= o["heuristic"]["objective_course_hours"] * (1 + 1e-9)
    assert len(india["selected_stockroom_hubs"]) == 8


def test_india_demand_and_population_are_real(india):
    a = india["demand_anchor"]
    assert a["gbd2019_deaths"] == 51100
    assert a["population_source"] == ["census_ind_2011_areal"]
    pops = [h["assigned_population"] for h in india["selected_stockroom_hubs"]]
    assert 1.15e9 < sum(pops) < 1.25e9                       # real people, not 2.3e11
    courses = sum(d["annual_courses"] for d in india["district_assignments"])
    assert courses == pytest.approx(india["annual_courses_total"], rel=1e-6)


def test_inventory_meets_service_level(india):
    for h in india["selected_stockroom_hubs"]:
        for it in h["vial_inventory"]:
            assert it["cycle_service_level"] >= 0.99 - 1e-9
            assert it["total_vials_allocated"] >= it["cycle_demand"] - 1e-9


def test_no_invented_products(india, client):
    names = {p["brand_name"] for p in india["product_portfolio"]}
    assert not any("Experimental" in n for n in names)


def test_scenarios(client, india):
    hub = india["selected_stockroom_hubs"][0]["district_id"]
    r = client.post("/api/simulate_scenario", json={"country": "India", "num_stockrooms": 8,
                                                     "scenario_type": "custom", "disabled_hub_district": hub})
    s = r.json
    assert r.status_code == 200
    assert hub not in [h["district_id"] for h in s["selected_stockroom_hubs"]]
    assert s["impact_vs_baseline"]["delta_mean_resupply_hours_per_course"] >= -1e-9   # removing an option cannot help
    cap = int(0.5 * india["total_national_vials_allocated"])
    r = client.post("/api/optimize_stockrooms", json={"country": "India", "num_stockrooms": 8, "total_vial_cap": cap})
    s = r.json
    assert s["total_national_vials_allocated"] <= cap
    assert s["rationing"]["expected_vials_served"] <= s["rationing"]["expected_vials_served_unconstrained"]
    r = client.post("/api/optimize_stockrooms", json={"country": "India", "num_stockrooms": 8, "surge_factor": 2.0})
    assert r.json["annual_courses_total"] == pytest.approx(2 * india["annual_courses_total"], rel=1e-6)


def test_more_hubs_never_worse(client):
    r = client.post("/api/p_sweep", json={"country": "Sri Lanka", "p_values": [1, 2, 3, 4]})
    curve = r.json["curve"]
    vals = [c["mean_resupply_hours_per_course"] for c in curve]
    assert all(b <= a + 1e-9 for a, b in zip(vals, vals[1:]))
    assert all(c["proven_optimal"] for c in curve)


def test_species_endpoints(client, india):
    did = india["district_assignments"][0]["district_id"]
    r = client.get("/api/species_by_district", query_string={"country": "India", "district": did})
    assert r.status_code == 200 and r.json["mode"] == "district"
    r = client.get("/api/species_by_country?country=India")
    assert r.json["total_species"] > 20


def test_patient_and_export(client, india):
    d = india["district_assignments"][10]["district_id"]
    r = client.post("/api/patient_emergency", json={"country": "India", "district": d, "species": "Daboia russelii",
                                                    "num_stockrooms": 8})
    assert r.status_code == 200 and r.json["nearest_stockrooms"][0]["stock_confirmed"]
    r = client.post("/api/export_solution", json=india)
    assert r.status_code == 200 and b"MODEL CERTIFICATE" in r.data


def test_provisional_country_flagged(client):
    prov = [c for c in client.get("/api/countries").json
            if c["population_provisional"] and (c["gbd2019_deaths"] or 0) > 10]
    if not prov:
        pytest.skip("no provisional country with burden left (all have WorldPop)")
    r = client.post("/api/optimize_stockrooms", json={"country": prov[0]["ISO_3_CODE"], "num_stockrooms": 3})
    assert r.status_code == 200
    assert r.json["population_provisional"] is True and r.json["warnings"]


def test_unknown_country(client):
    assert client.post("/api/optimize_stockrooms", json={"country": "Atlantis"}).status_code == 404


def test_capacity_allocation(client, india):
    target = india["total_national_vials_allocated"]
    cap = int(max(h["total_vials_to_store"] for h in india["selected_stockroom_hubs"]) * 0.8)
    supply = int(0.7 * target)
    r = client.post("/api/capacity_allocation", json={"country": "India", "num_stockrooms": 8,
                                                      "hub_capacity_vials": cap, "national_supply_vials": supply,
                                                      "floor_courses": 1})
    assert r.status_code == 200, r.json
    A = r.json["allocation"]
    assert A["summary"]["vials_allocated"] <= supply
    for h in A["hubs"]:
        assert h["allocated_vials"] <= cap
        assert h["allocated_vials"] >= min(h["floor_vials"], h["target_vials"])   # dormant reserve kept
    assert 0 < A["summary"]["network_fill_rate"] < 1
    # unconstrained run reproduces the base solution
    r = client.post("/api/capacity_allocation", json={"country": "India", "num_stockrooms": 8})
    assert r.json["allocation"]["summary"]["vials_allocated"] == pytest.approx(target, rel=1e-3)


def test_true_outage_keeps_other_hubs(client, india):
    hub = india["selected_stockroom_hubs"][2]["district_id"]
    r = client.post("/api/capacity_allocation", json={"country": "India", "num_stockrooms": 8,
                                                      "disabled_hub_district": hub, "hub_capacity_pct": 100})
    got = {h["district_id"] for h in r.json["selected_stockroom_hubs"]}
    base = {h["district_id"] for h in india["selected_stockroom_hubs"]}
    assert got == base - {hub}                                     # no replacement site
    assert r.json["allocation"]["summary"]["network_fill_rate"] < 1.0


def test_resilience_n_minus_1(client):
    r = client.post("/api/resilience", json={"country": "Sri Lanka", "num_stockrooms": 3})
    d = r.json
    assert r.status_code == 200, d
    assert len(d["rows"]) == 3
    assert d["required_capacity_pct"] is None or d["required_capacity_pct"] >= 100
    for row in d["rows"]:
        assert 0 < row["fill_rate_at_capacity"] <= 1


def test_surge_stresses_fixed_build(client):
    """Capacity/supply '100 %' = built for normal demand, so a 1.5x surge must lower the fill rate."""
    body = {"country": "India", "num_stockrooms": 8, "hub_capacity_pct": 100, "supply_pct": 100}
    base = client.post("/api/capacity_allocation", json=body).json["allocation"]["summary"]
    surge = client.post("/api/capacity_allocation", json={**body, "surge_factor": 1.5}).json["allocation"]["summary"]
    assert base["network_fill_rate"] == pytest.approx(1.0, abs=1e-6)
    assert surge["network_fill_rate"] < 0.99
    assert surge["vials_allocated"] == pytest.approx(base["vials_allocated"], rel=1e-3)   # same cold rooms
