#!/usr/bin/env python3
"""
Antivenom product catalogue from the WHO Snakebite Information & Data Platform
(SNBPROD_Views table 6, `antivenom_and_manufacturers_v`) and per-country
product–portfolio selection.

Output: data/processed/antivenom_products.csv  (one row per product–species link)

Each link carries
  * specificity      – WHO field (immunizing species / paraspecific claim / evidence / legacy)
  * registered_iso3  – countries where the product is licensed or has marketing approval,
                       parsed from the WHO comment text plus the manufacturer country
  * procurable       – False for experimental / investigational / not-yet-registered products

Portfolio selection (per country) is an uncapacitated facility-location ILP:

    max  Σ_s Σ_p  D_s · q_sp · a_sp  −  ε Σ_p z_p
    s.t. Σ_p a_sp ≤ 1          ∀ s           (each species is treated with ≤ 1 product)
         a_sp ≤ z_p            ∀ s,p         (only stocked products can be used)
         z_p ∈ {0,1},  0 ≤ a_sp ≤ 1

D_s = expected antivenom courses for species s in the country, q_sp = clinical
suitability weight (specificity × registration factor, configs/model.yaml).
Quality is maximised first; ε only breaks ties towards fewer SKUs. Species with
no procurable product are reported as "no effective antivenom" – they are never
assigned an invented product.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "data", "raw")
PROCESSED = os.path.join(REPO, "data", "processed")

ALIASES = {
    "USA": "USA", "UNITED STATES OF AMERICA": "USA", "THE UNITED STATES OF AMERICA": "USA",
    "UAE": "ARE", "IVORY COAST": "CIV", "COTE D'IVOIRE": "CIV", "CÔTE D'IVOIRE": "CIV",
    "IRAN": "IRN", "I.R.IRAN": "IRN", "RUSSIA": "RUS", "VIETNAM": "VNM", "VENEZUELA": "VEN",
    "BOLIVIA": "BOL", "TANZANIA": "TZA", "REPUBLIC OF CONGO": "COG", "REPUBLIC OF KOREA": "KOR",
    "CHINA (TAIWAN PROVINCE)": "TWN", "SULTANATE OF OMAN": "OMN", "OMAN": "OMN", "QATAR": "QAT",
    "UNITED KINGDOM": "GBR", "MARTINIQUE": "MTQ", "TURKEY": "TUR", "SYRIA": "SYR", "LAOS": "LAO",
}
NON_PROCURABLE = re.compile(r"experimental|investigational|not yet registered|clinical evaluation", re.I)


def _country_lookup() -> Dict[str, str]:
    a0 = pd.read_csv(os.path.join(RAW, "who_detailed_boundary_adm0_countries.csv"))
    names = {}
    for col in ("ADM0_NAME", "ADM0_VIZ_NAME"):
        for n, iso in zip(a0[col], a0.ISO_3_CODE):
            if isinstance(n, str) and isinstance(iso, str):
                names[n.strip().upper()] = iso.strip().upper()
    names.update(ALIASES)
    return names


def parse_countries(text: str, lookup: Dict[str, str]) -> List[str]:
    if not isinstance(text, str):
        return []
    t = text.upper()
    found = []
    # longest names first so "Republic of Congo" is not matched as "Congo" twice
    for name in sorted(lookup, key=len, reverse=True):
        pat = r"(?<![A-Z])" + re.escape(name) + r"(?![A-Z])"
        if re.search(pat, t):
            found.append(lookup[name])
            t = re.sub(pat, " ", t)
    return sorted(set(found))


def build_catalogue(out_dir: str = PROCESSED) -> pd.DataFrame:
    a = pd.read_csv(os.path.join(RAW, "who_snb_antivenom_manufacturers.csv"))
    a = a.replace("<Null>", np.nan)
    a = a[~a.Antivenom_Name.fillna("").str.contains("No specific antivenom", case=False)]
    a = a.dropna(subset=["Antivenom_Name"])
    lookup = _country_lookup()
    rows = []
    for r in a.itertuples():
        reg = set(parse_countries(r.Antivenom_Comments, lookup))
        mc = lookup.get(str(r.Manufacturer_Country).strip().upper()) if isinstance(r.Manufacturer_Country, str) else None
        if mc:
            reg.add(mc)
        status = f"{r.Status or ''} {r.Antivenom_Comments or ''}"
        rows.append({
            "product_id": f"{r.Antivenom_Name.strip()} | {str(r.Manufacturer_Name).strip()}",
            "product_name": r.Antivenom_Name.strip(),
            "manufacturer": r.Manufacturer_Name,
            "manufacturer_country": r.Manufacturer_Country,
            "scientific_name": r.Scientific_Name.strip(),
            "specificity": r.Specificity if isinstance(r.Specificity, str) else "Unspecified",
            "who_status": r.Status,
            "registered_iso3": ";".join(sorted(reg)),
            "procurable": not bool(NON_PROCURABLE.search(status)),
        })
    df = pd.DataFrame(rows).drop_duplicates(["product_id", "scientific_name"])
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(os.path.join(out_dir, "antivenom_products.csv"), index=False)
    return df


def choose_portfolio(iso3: str, species_courses: Dict[str, float], catalogue: pd.DataFrame,
                     cfg: dict) -> dict:
    """Solve the portfolio ILP for one country.

    Returns {'assignment': {species: product_id}, 'products': [...],
             'no_antivenom': [species...], 'quality': {species: q}}.
    """
    spec_w = cfg["specificity_weight"]
    nreg = float(cfg["not_registered_factor"])
    eps = float(cfg["sku_penalty"])
    species = [s for s, d in species_courses.items() if d > 0]
    cat = catalogue[catalogue.scientific_name.isin(species) & catalogue.procurable]
    links = []
    for r in cat.itertuples():
        q = float(spec_w.get(r.specificity, 0.0))
        if q <= 0:
            continue
        if iso3 not in str(r.registered_iso3).split(";"):
            q *= nreg
        links.append((r.scientific_name, r.product_id, q))
    covered = {s for s, _, _ in links}
    no_av = sorted(set(species) - covered)
    if not links:
        return {"assignment": {}, "products": [], "no_antivenom": no_av, "quality": {}}

    prods = sorted({p for _, p, _ in links})
    pidx = {p: i for i, p in enumerate(prods)}
    sp_list = sorted(covered)
    sidx = {s: i for i, s in enumerate(sp_list)}
    L, P, S = len(links), len(prods), len(sp_list)
    # variables: a_l (L) then z_p (P);  milp minimises
    c = np.zeros(L + P)
    scale = max(species_courses[s] for s in sp_list)
    for l, (s, p, q) in enumerate(links):
        c[l] = -(species_courses[s] / scale) * q
    c[L:] = eps
    A1 = lil_matrix((S, L + P))            # Σ_p a_sp ≤ 1
    A2 = lil_matrix((L, L + P))            # a_sp − z_p ≤ 0
    for l, (s, p, q) in enumerate(links):
        A1[sidx[s], l] = 1
        A2[l, l] = 1
        A2[l, L + pidx[p]] = -1
    cons = [LinearConstraint(A1.tocsr(), -np.inf, 1), LinearConstraint(A2.tocsr(), -np.inf, 0)]
    integ = np.r_[np.zeros(L), np.ones(P)]
    res = milp(c, constraints=cons, integrality=integ, bounds=Bounds(0, 1),
               options={"time_limit": 30, "mip_rel_gap": 0})
    if not res.success:
        raise RuntimeError(f"portfolio ILP failed for {iso3}: {res.message}")
    x = res.x
    assign, quality = {}, {}
    for l, (s, p, q) in enumerate(links):
        if x[l] > 0.5:
            assign[s] = p
            quality[s] = q
    used = sorted({assign[s] for s in assign})
    return {"assignment": assign, "products": used, "no_antivenom": no_av, "quality": quality}


if __name__ == "__main__":
    df = build_catalogue()
    print(df.shape, df.product_id.nunique(), "products,", df.scientific_name.nunique(), "species")
