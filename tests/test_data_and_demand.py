"""Data integrity and demand-model invariants."""
import os

import numpy as np
import pandas as pd
import pytest

from optimise.demand import country_demand, load_tables
from optimise.solver import load_config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(REPO, "data", "processed")


@pytest.fixture(scope="module")
def t():
    return load_tables()


def test_presence_no_duplicates(t):
    assert not t["pres"].duplicated(["district_id", "scientific_name"]).any()
    assert t["pres"].overlap_frac.between(0, 1).all()
    assert set(t["pres"].category.unique()) <= {1, 2}


def test_every_presence_row_has_a_district_and_species(t):
    assert set(t["pres"].district_id) <= set(t["districts"].district_id)
    assert set(t["pres"].scientific_name) <= set(t["species"].scientific_name)


def test_population_covers_all_districts(t):
    assert set(t["pop"].district_id) == set(t["districts"].district_id)
    assert (t["pop"].pop_total >= 0).all()


def test_india_census_interpolation_conserves_population(t):
    ind = t["pop"][t["pop"].iso3 == "IND"]
    assert (ind.pop_source == "census_ind_2011_areal").all()
    census_total = pd.read_csv(os.path.join(REPO, "data", "external", "india-districts-census-2011.csv")).Population.sum()
    # WHO and Census boundaries differ slightly at the borders; ≥ 99 % must be conserved
    assert 0.99 <= ind.pop_total.sum() / census_total <= 1.001


def test_catalogue_products_are_real_who_products(t):
    raw = pd.read_csv(os.path.join(REPO, "data", "raw", "who_snb_antivenom_manufacturers.csv"))
    assert set(t["catalogue"].product_name) <= set(raw.Antivenom_Name.str.strip())
    assert not t["catalogue"].product_name.str.contains("No specific", case=False).any()


@pytest.mark.parametrize("iso3", ["IND", "NGA", "BRA", "LKA", "AUS"])
def test_demand_conservation(iso3):
    cfg = load_config()
    cd = country_demand(iso3, cfg)
    d = cd.districts
    expected = cd.anchor["gbd2019_deaths"] * cfg["demand"]["envenomings_per_death"] * cfg["demand"]["p_antivenom_indicated"]
    assert d.lambda_total.sum() == pytest.approx(expected, rel=1e-9)
    assert (d.lambda_treatable + d.courses_no_antivenom).sum() == pytest.approx(expected, rel=1e-9)
    assert (d.lambda_total >= 0).all()
    # every stocked product exists in the WHO catalogue and is procurable
    cat = load_tables()["catalogue"]
    for prod in cd.products:
        assert prod in set(cat[cat.procurable].product_id)


def test_demand_scales_linearly_with_rho():
    cfg = load_config()
    a = country_demand("IND", cfg).districts.lambda_total.to_numpy()
    cfg["demand"]["envenomings_per_death"] *= 2
    b = country_demand("IND", cfg).districts.lambda_total.to_numpy()
    assert np.allclose(b, 2 * a)


def test_unknown_country_raises():
    with pytest.raises(KeyError):
        country_demand("XXX", load_config())
