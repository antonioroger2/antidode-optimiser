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
    r = client.post("/api/optimize_stockrooms", json={"country": "NGA", "num_stockrooms": 5})
    assert r.status_code == 200
    assert r.json["population_provisional"] is True and r.json["warnings"]


def test_unknown_country(client):
    assert client.post("/api/optimize_stockrooms", json={"country": "Atlantis"}).status_code == 404
