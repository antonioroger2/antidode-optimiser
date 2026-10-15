#!/usr/bin/env python3
"""
Expected antivenom demand per district and product class.

For country c with GBD-2019 snakebite deaths D_c:

    E_c   = D_c · ρ                         envenomings / yr      (ρ: envenomings per death)
    C_c   = E_c · p_AV                      antivenom courses / yr
    λ_i   = C_c · x_i / Σ_{i'∈c} x_i'        courses / yr in district i
            x_i = exposure in range (rural population – or agricultural workers for India –
                  living inside ≥1 medically important species range)

Species split inside a district (product mix only, the district total is unchanged):

    s_is  = ω_is κ_cat(s) / Σ_s' ω_is' κ_cat(s')        κ_1 = 1, κ_2 = category2_weight

Product classes come from the per-country portfolio ILP (preprocess/antivenom.py).
Courses for species with no procurable antivenom are reported as `courses_no_antivenom`
and are NOT stocked (no invented products).

Invariants (tested): Σ_i λ_i = C_c exactly; Σ_k λ_ik + λ_i^none = λ_i.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED = os.path.join(REPO, "data", "processed")
RAW = os.path.join(REPO, "data", "raw")


@lru_cache(maxsize=1)
def load_tables():
    t = {
        "districts": pd.read_csv(os.path.join(PROCESSED, "districts.csv")),
        "pres": pd.read_csv(os.path.join(PROCESSED, "district_species.csv")),
        "pop": pd.read_csv(os.path.join(PROCESSED, "district_population.csv")),
        "species": pd.read_csv(os.path.join(PROCESSED, "species.csv")),
        "catalogue": pd.read_csv(os.path.join(PROCESSED, "antivenom_products.csv")),
    }
    d = pd.read_csv(os.path.join(RAW, "deaths-from-snakebite-envenoming.csv"))
    d = d[~d.Code.astype(str).str.startswith("OWID")]
    t["deaths"] = dict(zip(d.Code, d.iloc[:, 3].astype(float)))
    t["pres"]["iso3"] = t["pres"].district_id.str[:3]
    return t


@dataclass
class CountryDemand:
    iso3: str
    country: str
    districts: pd.DataFrame                  # district_id, adm1, adm2, lat, lon, exposure, lambda_total, ...
    product_courses: pd.DataFrame            # district_id x product_class -> courses/yr
    products: List[str]
    species_product: Dict[str, str]
    no_antivenom_species: List[str]
    anchor: dict
    provisional_population: bool
    warnings: List[str] = field(default_factory=list)


def country_demand(iso3: str, cfg: dict) -> CountryDemand:
    try:
        from preprocess.antivenom import choose_portfolio
    except ImportError:
        import sys
        sys.path.insert(0, REPO)
        from preprocess.antivenom import choose_portfolio

    t = load_tables()
    dm = cfg["demand"]
    iso3 = iso3.upper()
    dist = t["districts"][t["districts"].iso3 == iso3].copy()
    if dist.empty:
        raise KeyError(f"No WHO ADM2 districts for {iso3}")
    pop = t["pop"][t["pop"].iso3 == iso3][["district_id", "pop_source", "pop_total", "pop_rural",
                                             "agri_workers", "exposure_base", "exposure_in_range",
                                             "provisional"]]
    dist = dist.merge(pop, on="district_id", how="left")
    if dist.pop_source.isna().any():
        raise ValueError(f"{iso3}: {int(dist.pop_source.isna().sum())} districts without population")
    warnings = []
    deaths = t["deaths"].get(iso3)
    if deaths is None:
        raise KeyError(f"{iso3}: no GBD-2019 death estimate – burden cannot be anchored")
    rho = float(dm["envenomings_per_death"])
    p_av = float(dm["p_antivenom_indicated"])
    courses_total = deaths * rho * p_av

    x = dist.exposure_in_range.fillna(0.0).to_numpy(float)
    if x.sum() <= 0:
        warnings.append("No exposed population inside WHO species ranges; burden left unallocated.")
        dist["lambda_total"] = 0.0
    else:
        dist["lambda_total"] = courses_total * x / x.sum()

    # species split
    pres = t["pres"][t["pres"].iso3 == iso3].copy()
    k2 = float(dm["category2_weight"])
    pres["w"] = pres.overlap_frac * np.where(pres.category == 1, 1.0, k2)
    tot = pres.groupby("district_id").w.transform("sum")
    pres["share"] = np.where(tot > 0, pres.w / tot.replace(0, np.nan), 0.0)
    # districts where all present species have weight 0 (only Cat-2 with k2=0): equal split
    zero = tot <= 0
    if zero.any():
        n = pres[zero].groupby("district_id").scientific_name.transform("size")
        pres.loc[zero, "share"] = 1.0 / n
    lam = dist.set_index("district_id").lambda_total
    pres["courses"] = pres.share * pres.district_id.map(lam).fillna(0.0)
    sp_courses = pres.groupby("scientific_name").courses.sum().to_dict()

    port = choose_portfolio(iso3, sp_courses, t["catalogue"], cfg["product_choice"])
    sp2p = port["assignment"]
    pres["product"] = pres.scientific_name.map(sp2p).fillna("__NO_ANTIVENOM__")
    pc = pres.pivot_table(index="district_id", columns="product", values="courses", aggfunc="sum", fill_value=0.0)
    pc = pc.reindex(dist.district_id).fillna(0.0)
    none = pc.pop("__NO_ANTIVENOM__") if "__NO_ANTIVENOM__" in pc else pd.Series(0.0, index=pc.index)
    dist["courses_no_antivenom"] = none.to_numpy()
    dist["lambda_treatable"] = pc.sum(axis=1).to_numpy()
    # districts with exposure but no species rows can't happen (exposure needs range) – guard
    gap = dist.lambda_total - dist.lambda_treatable - dist.courses_no_antivenom
    if (gap.abs() > 1e-6 * max(1.0, courses_total)).any():
        raise AssertionError(f"{iso3}: demand not conserved in species split")

    anchor = {
        "gbd2019_deaths": deaths,
        "envenomings_per_death": rho,
        "p_antivenom_indicated": p_av,
        "envenomings_per_year": deaths * rho,
        "antivenom_courses_per_year": courses_total,
        "courses_treatable_with_portfolio": float(dist.lambda_treatable.sum()),
        "courses_no_effective_antivenom": float(dist.courses_no_antivenom.sum()),
        "population_source": sorted(dist.pop_source.unique().tolist()),
        "exposure_base": sorted(dist.exposure_base.dropna().unique().tolist()),
    }
    prov = bool(dist.provisional.any())
    if prov:
        warnings.append("PROVISIONAL population (GeoNames settlements): rural exposure is under-counted; "
                        "replace with WorldPop rasters before interpreting district allocations.")
    return CountryDemand(iso3=iso3, country=str(dist.country.iloc[0]), districts=dist.reset_index(drop=True),
                         product_courses=pc.reset_index(drop=True), products=list(pc.columns),
                         species_product=sp2p, no_antivenom_species=port["no_antivenom"],
                         anchor=anchor, provisional_population=prov, warnings=warnings)
