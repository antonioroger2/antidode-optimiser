#!/usr/bin/env python3
"""
Species presence per district (WHO ADM2) — reproducible rebuild.

Replaces the old `gis_intersection.py` + the missing generator of
WHO_EXACT_GIS_GLOBAL_DISTRICT_SNAKE_OVERLAP.csv.

Outputs (data/processed/):
  districts.csv         one row per WHO ADM2 unit (all countries)
  district_species.csv  one row per (district, species) – no duplicates
  species.csv           species metadata straight from the WHO master layer

Method
------
* Species ranges (WHO SNBPROD layer 1) are dissolved per species (fixes the
  duplicate rows produced by multipart ranges) and kept per WHO category, because
  WHO categories are region-specific (e.g. a species can be Cat-1 in one part of
  its range and Cat-2 elsewhere).
* Where district polygons are available (currently India; any country whose ADM2
  polygons are placed in data/spatial/adm2/<ISO3>.geojson) the overlap is the
  exact area share computed in an equal-area projection (EPSG:6933):
      omega_is = area(district_i ∩ range_s) / area(district_i)
  plus the union share of ALL medically important ranges,
      omega_i^any = area(district_i ∩ ⋃_s range_s) / area(district_i).
* Elsewhere presence is centroid-in-range (omega = 1 if the WHO ADM2 centroid is
  inside the range, else absent) and flagged `method = centroid`.
* Slivers below MIN_OVERLAP are dropped (boundary misalignment between layers).

The WHO range maps encode *expected occurrence* ("indicative and not absolute"),
not abundance. omega is therefore an extent-of-range measure, never a density.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List

import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import Point, shape
from shapely.ops import unary_union

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "data", "raw")
SPATIAL = os.path.join(REPO, "data", "spatial")
PROCESSED = os.path.join(REPO, "data", "processed")

MIN_OVERLAP = 0.001  # 0.1 % of district area

HABITAT = os.path.join(SPATIAL, "who_snake_species_habitation_polygons.geojson")
SPECIES_MASTER = os.path.join(SPATIAL, "who_snake_species_master_spatial.geojson")
ADM2_TABLE = os.path.join(RAW, "who_detailed_boundary_adm2_global_districts_cities.csv")
ADM2_POLY_DIR = os.path.join(SPATIAL, "adm2")
INDIA_POLY = os.path.join(SPATIAL, "who_india_adm2_district_polygons.geojson")


def district_id(iso3: str, adm1: str, adm2: str) -> str:
    return f"{iso3}|{str(adm1).strip().upper()}|{str(adm2).strip().upper()}"


def _equal_area():
    from pyproj import Transformer
    import shapely
    tr = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)

    def _f(xy):
        x, y = tr.transform(xy[:, 0], xy[:, 1])
        return np.column_stack([x, y])
    return lambda geom: shapely.transform(geom, _f)


# ----------------------------------------------------------------------------- species
def load_species_master() -> pd.DataFrame:
    with open(SPECIES_MASTER, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    rows = []
    for ft in feats:
        p = ft["properties"]
        rows.append({
            "scientific_name": p["Scientific_Name"].strip(),
            "code_ssn": p.get("CODE_SSN"),
            "common_name": (p.get("PrimaryCommonName") or "").strip() or None,
            "family": (p.get("Family_Name") or "").strip() or None,
            "who_category_list": (p.get("List_of_Category_name") or "").strip(),
            "impacted_population_global": p.get("Impacted_Population"),
            "range_countries": (p.get("List_of_Countries") or "").strip(),
            "map_pdf_url": p.get("Map_pdf"),
            "photo_url": p.get("Photo_1_url"),
            "reptile_db_url": p.get("RepDB"),
        })
    df = pd.DataFrame(rows).drop_duplicates("scientific_name")
    return df


def load_ranges():
    """Return {species: {'all': geom, 'cat1': geom|None}} dissolved ranges (WGS84)."""
    with open(HABITAT, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    parts: Dict[str, Dict[str, list]] = {}
    for ft in feats:
        p = ft["properties"]
        sp = p["Scientific_Name"].strip()
        g = shape(ft["geometry"]).buffer(0)
        if g.is_empty:
            continue
        d = parts.setdefault(sp, {"all": [], "cat1": []})
        d["all"].append(g)
        if p.get("code_cat") == "CAT001":
            d["cat1"].append(g)
    ranges = {}
    for sp, d in parts.items():
        ranges[sp] = {
            "all": unary_union(d["all"]).buffer(0),
            "cat1": unary_union(d["cat1"]).buffer(0) if d["cat1"] else None,
        }
    return ranges


# ----------------------------------------------------------------------------- districts
def load_districts() -> pd.DataFrame:
    a = pd.read_csv(ADM2_TABLE)
    df = pd.DataFrame({
        "district_id": [district_id(i, s, d) for i, s, d in zip(a.ISO_3_CODE, a.ADM1_NAME, a.ADM2_NAME)],
        "iso3": a.ISO_3_CODE.str.upper(),
        "country": a.ADM0_VIZ_NAME.fillna(a.ADM0_NAME),
        "adm1": a.ADM1_VIZ_NAME.fillna(a.ADM1_NAME),
        "adm2": a.ADM2_VIZ_NAME.fillna(a.ADM2_NAME),
        "who_region": a.WHO_REGION,
        "lat": a.CENTER_LAT.astype(float),
        "lon": a.CENTER_LON.astype(float),
    })
    if df.district_id.duplicated().any():
        raise ValueError("WHO ADM2 district keys are not unique")
    return df


def _polygon_layers() -> Dict[str, str]:
    """ISO3 -> path of an ADM2 polygon GeoJSON (WHO Detailed_Boundary_ADM2 schema)."""
    out = {}
    if os.path.isdir(ADM2_POLY_DIR):
        for fn in os.listdir(ADM2_POLY_DIR):
            if fn.lower().endswith(".geojson"):
                out[fn[:3].upper()] = os.path.join(ADM2_POLY_DIR, fn)
    if "IND" not in out and os.path.exists(INDIA_POLY):
        out["IND"] = INDIA_POLY
    return out


# ----------------------------------------------------------------------------- overlap
def polygon_overlap(iso3: str, path: str, ranges, to_ea) -> (List[dict], List[dict]):
    with open(path, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    sp_names = list(ranges)
    tree = STRtree([ranges[s]["all"] for s in sp_names])
    pres, dist_rows = [], []
    for ft in feats:
        p = ft["properties"]
        did = district_id(iso3, p["ADM1_NAME"], p["ADM2_NAME"])
        g = shape(ft["geometry"]).buffer(0)
        if g.is_empty:
            continue
        g_ea = to_ea(g)
        area = g_ea.area
        hits = []
        for idx in tree.query(g, predicate="intersects"):
            sp = sp_names[idx]
            inter = g.intersection(ranges[sp]["all"])
            if inter.is_empty:
                continue
            frac = to_ea(inter).area / area
            if frac < MIN_OVERLAP:
                continue
            cat1 = False
            if ranges[sp]["cat1"] is not None:
                ci = g.intersection(ranges[sp]["cat1"])
                cat1 = (not ci.is_empty) and to_ea(ci).area / area >= MIN_OVERLAP
            hits.append((sp, inter))
            pres.append({"district_id": did, "scientific_name": sp,
                         "overlap_frac": round(min(1.0, frac), 6),
                         "category": 1 if cat1 else 2, "method": "polygon"})
        any_frac = 0.0
        if hits:
            any_frac = min(1.0, to_ea(unary_union([h[1] for h in hits])).area / area)
        dist_rows.append({"district_id": did, "area_km2": area / 1e6,
                          "range_any_frac": round(any_frac, 6), "presence_method": "polygon"})
    return pres, dist_rows


def centroid_presence(districts: pd.DataFrame, ranges) -> (List[dict], List[dict]):
    sp_names = list(ranges)
    tree = STRtree([ranges[s]["all"] for s in sp_names])
    pts = [Point(lon, lat) for lon, lat in zip(districts.lon, districts.lat)]
    pres = []
    any_flag = np.zeros(len(pts), dtype=bool)
    pi, si = tree.query(pts, predicate="intersects")
    for p_idx, s_idx in zip(pi, si):
        sp = sp_names[s_idx]
        c1 = ranges[sp]["cat1"]
        cat1 = c1 is not None and c1.intersects(pts[p_idx])
        pres.append({"district_id": districts.district_id.iat[p_idx], "scientific_name": sp,
                     "overlap_frac": 1.0, "category": 1 if cat1 else 2, "method": "centroid"})
        any_flag[p_idx] = True
    dist_rows = [{"district_id": d, "area_km2": np.nan, "range_any_frac": float(f),
                  "presence_method": "centroid"} for d, f in zip(districts.district_id, any_flag)]
    return pres, dist_rows


def build(out_dir: str = PROCESSED) -> Dict[str, pd.DataFrame]:
    species = load_species_master()
    ranges = load_ranges()
    unknown = set(ranges) - set(species.scientific_name)
    if unknown:
        # Known WHO data gap (e.g. Bothriechis nubestris has a range layer but no master
        # record). Keep the species with explicit missing metadata instead of guessing it.
        print(f"[presence] WARNING range without WHO master record: {sorted(unknown)}")
        species = pd.concat([species, pd.DataFrame({"scientific_name": sorted(unknown)})],
                            ignore_index=True)
    districts = load_districts()
    to_ea = _equal_area()

    poly = _polygon_layers()
    pres_all, drows_all = [], []
    for iso3, path in poly.items():
        p, d = polygon_overlap(iso3, path, ranges, to_ea)
        pres_all += p
        drows_all += d
        print(f"[presence] {iso3}: polygon overlap, {len(d)} districts, {len(p)} pairs")

    rest = districts[~districts.iso3.isin(poly)]
    p, d = centroid_presence(rest, ranges)
    pres_all += p
    drows_all += d
    print(f"[presence] centroid-in-range for {rest.iso3.nunique()} countries, {len(p)} pairs")

    pres = pd.DataFrame(pres_all)
    drows = pd.DataFrame(drows_all)
    # Polygon districts not present in the WHO ADM2 table (should not happen) -> error
    missing = set(drows.district_id) - set(districts.district_id)
    if missing:
        raise ValueError(f"{len(missing)} polygon districts not in WHO ADM2 table, e.g. {list(missing)[:3]}")
    districts = districts.merge(drows, on="district_id", how="left")
    if pres.duplicated(["district_id", "scientific_name"]).any():
        raise AssertionError("duplicate district-species pairs")

    os.makedirs(out_dir, exist_ok=True)
    species.to_csv(os.path.join(out_dir, "species.csv"), index=False)
    districts.to_csv(os.path.join(out_dir, "districts.csv"), index=False)
    pres.to_csv(os.path.join(out_dir, "district_species.csv"), index=False)
    return {"species": species, "districts": districts, "district_species": pres}


if __name__ == "__main__":
    out = build()
    for k, v in out.items():
        print(k, v.shape)
