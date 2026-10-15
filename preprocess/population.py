#!/usr/bin/env python3
"""
District population and exposure base, per country, from the best available source.

Output: data/processed/district_population.csv
  district_id, iso3, pop_source, pop_year, pop_total, pop_rural, agri_workers,
  exposure_base, exposure_in_range, provisional

Sources (order in configs/model.yaml -> population.order):

1. worldpop   WorldPop 2020 1 km UN-adjusted raster, data/external/worldpop/<iso3>.tif,
              and ADM2 polygons data/spatial/adm2/<ISO3>.geojson (or the India file).
              pop_total  = Σ cells in district
              pop_rural  = Σ cells with density < urban-centre threshold (1,500 /km²,
                           Degree of Urbanisation, UN Statistical Commission 2020)
              exposure_in_range = Σ rural cells inside ⋃ medically-important ranges (exact)
2. census_ind Census of India 2011 district tables (640 districts) + DataMeet 2011
              district boundaries, areally interpolated (equal-area CRS) onto the
              WHO ADM2 polygons. rural = Population × Rural_HH / HH;
              agri_workers = Cultivators + Agricultural labourers.
              exposure_in_range = exposure_base × omega_i^any  (uniform within district)
3. geonames   PROVISIONAL: GeoNames settlements ≥ 500 people (PyPI geonamescache),
              assigned to the nearest WHO ADM2 centroid of the same country.
              Systematically undercounts villages, i.e. the rural population that
              carries most snakebite burden. Flagged `provisional = True`.

Only *relative* exposure within a country is used downstream: the country total
burden comes from GBD deaths, so a constant scaling error cancels out.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED = os.path.join(REPO, "data", "processed")
EXTERNAL = os.path.join(REPO, "data", "external")
SPATIAL = os.path.join(REPO, "data", "spatial")

try:
    from .presence import district_id, _polygon_layers, load_ranges
except ImportError:  # run as script
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from presence import district_id, _polygon_layers, load_ranges  # type: ignore

EA_CRS = "EPSG:6933"


# ----------------------------------------------------------------------------- census (India)
def census_india(range_any: pd.Series) -> Optional[pd.DataFrame]:
    shp = os.path.join(EXTERNAL, "2011_Dist.shp")
    csv = os.path.join(EXTERNAL, "india-districts-census-2011.csv")
    poly = _polygon_layers().get("IND")
    if not (os.path.exists(shp) and os.path.exists(csv) and poly):
        return None
    import geopandas as gpd
    c = pd.read_csv(csv).copy()
    c["rural_pop"] = c.Population * c.Rural_Households / c.Households
    c["agri_workers"] = c.Cultivator_Workers + c.Agricultural_Workers
    src = gpd.read_file(shp)
    src["censuscode"] = src.censuscode.astype(int)
    src = src.merge(c[["District code", "Population", "rural_pop", "agri_workers"]],
                    left_on="censuscode", right_on="District code", how="inner")
    if len(src) != 640:
        raise ValueError(f"Census join produced {len(src)} of 640 districts")
    src = src.to_crs(EA_CRS)
    src["geometry"] = src.geometry.buffer(0)
    src["src_area"] = src.geometry.area

    tgt = gpd.read_file(poly)
    tgt["district_id"] = [district_id("IND", a, b) for a, b in zip(tgt.ADM1_NAME, tgt.ADM2_NAME)]
    tgt = tgt.to_crs(EA_CRS)
    tgt["geometry"] = tgt.geometry.buffer(0)

    inter = gpd.overlay(src[["censuscode", "Population", "rural_pop", "agri_workers", "src_area", "geometry"]],
                        tgt[["district_id", "geometry"]], how="intersection", keep_geom_type=True)
    w = inter.geometry.area / inter.src_area
    out = pd.DataFrame({"district_id": inter.district_id})
    for col in ("Population", "rural_pop", "agri_workers"):
        out[col] = inter[col] * w
    out = out.groupby("district_id", as_index=False).sum()
    out = tgt[["district_id"]].merge(out, on="district_id", how="left").fillna(0.0)
    res = pd.DataFrame({
        "district_id": out.district_id,
        "iso3": "IND",
        "pop_source": "census_ind_2011_areal",
        "pop_year": 2011,
        "pop_total": out.Population,
        "pop_rural": out.rural_pop,
        "agri_workers": out.agri_workers,
        "provisional": False,
    })
    res["range_any_frac"] = res.district_id.map(range_any).fillna(0.0)
    return res


# ----------------------------------------------------------------------------- WorldPop
def worldpop(iso3: str, ranges, urban_threshold: float, range_species=None) -> Optional[pd.DataFrame]:
    tif = os.path.join(EXTERNAL, "worldpop", f"{iso3.lower()}.tif")
    poly = _polygon_layers().get(iso3)
    if not (os.path.exists(tif) and poly):
        return None
    import rasterio
    from rasterio.mask import mask
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union
    with open(poly, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    rng = unary_union([ranges[s]["all"] for s in (range_species or ranges)])
    rows = []
    with rasterio.open(tif) as ds:
        # cell area (km²) varies with latitude for geographic rasters
        res_x, res_y = abs(ds.transform.a), abs(ds.transform.e)
        for ft in feats:
            p = ft["properties"]
            g = shape(ft["geometry"]).buffer(0)
            did = district_id(iso3, p["ADM1_NAME"], p["ADM2_NAME"])
            try:
                arr, tr = mask(ds, [mapping(g)], crop=True, filled=True, nodata=0)
            except ValueError:  # polygon outside raster
                rows.append((did, 0.0, 0.0, 0.0))
                continue
            a = np.where(np.isfinite(arr[0]) & (arr[0] > 0), arr[0], 0.0)
            nrow = a.shape[0]
            lats = tr.f + tr.e * (np.arange(nrow) + 0.5)
            cell_km2 = (111.32 * res_x * np.cos(np.radians(lats))) * (110.57 * res_y)
            dens = a / cell_km2[:, None]
            rural = np.where(dens < urban_threshold, a, 0.0)
            gi = g.intersection(rng)
            in_rng = 0.0
            if not gi.is_empty:
                from rasterio.features import geometry_mask
                inside = ~geometry_mask([mapping(gi)], out_shape=a.shape, transform=tr, all_touched=False)
                in_rng = float(rural[inside].sum())
            rows.append((did, float(a.sum()), float(rural.sum()), in_rng))
    df = pd.DataFrame(rows, columns=["district_id", "pop_total", "pop_rural", "exposure_in_range"])
    df["iso3"] = iso3
    df["pop_source"] = "worldpop_2020_1km"
    df["pop_year"] = 2020
    df["agri_workers"] = np.nan
    df["provisional"] = False
    return df


# ----------------------------------------------------------------------------- GeoNames (interim)
def geonames(districts: pd.DataFrame) -> pd.DataFrame:
    import geonamescache
    path = os.path.join(os.path.dirname(geonamescache.__file__), "data", "cities500.json")
    with open(path, encoding="utf-8") as f:
        cities = pd.DataFrame(json.load(f).values())
    cc = pd.read_csv(os.path.join(REPO, "data", "raw", "who_detailed_boundary_adm0_countries.csv"),
                     usecols=["ISO_2_CODE", "ISO_3_CODE"]).dropna()
    iso2to3 = dict(zip(cc.ISO_2_CODE, cc.ISO_3_CODE))
    cities["iso3"] = cities.countrycode.map(iso2to3)
    cities = cities.dropna(subset=["iso3"])
    cities = cities[cities.population > 0]
    from scipy.spatial import cKDTree

    def xyz(lat, lon):
        la, lo = np.radians(lat), np.radians(lon)
        return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])

    parts = []
    for iso3, dd in districts.groupby("iso3"):
        cs = cities[cities.iso3 == iso3]
        tot = np.zeros(len(dd))
        rur = np.zeros(len(dd))
        if len(cs):
            _, idx = cKDTree(xyz(dd.lat.values, dd.lon.values)).query(xyz(cs.latitude.values, cs.longitude.values))
            np.add.at(tot, idx, cs.population.values)
            small = cs.population.values < 50_000
            np.add.at(rur, idx[small], cs.population.values[small])
        parts.append(pd.DataFrame({"district_id": dd.district_id.values, "iso3": iso3,
                                   "pop_total": tot, "pop_rural": rur}))
    df = pd.concat(parts, ignore_index=True)
    df["pop_source"] = "geonames_cities500_PROVISIONAL"
    df["pop_year"] = np.nan
    df["agri_workers"] = np.nan
    df["provisional"] = True
    return df


# ----------------------------------------------------------------------------- orchestration
def build(cfg: dict, out_dir: str = PROCESSED) -> pd.DataFrame:
    districts = pd.read_csv(os.path.join(PROCESSED, "districts.csv"))
    range_any = districts.set_index("district_id").range_any_frac
    order = cfg["population"]["order"]
    thr = float(cfg["population"]["urban_centre_density_per_km2"])
    done = {}
    ranges = None
    for iso3 in sorted(districts.iso3.unique()):
        for src in order:
            df = None
            if src == "worldpop":
                if os.path.exists(os.path.join(EXTERNAL, "worldpop", f"{iso3.lower()}.tif")):
                    ranges = ranges or load_ranges()
                    df = worldpop(iso3, ranges, thr)
            elif src == "census_ind" and iso3 == "IND":
                df = census_india(range_any)
            if df is not None:
                done[iso3] = df
                break
    rest = districts[~districts.iso3.isin(done)]
    parts = list(done.values())
    if "geonames" in order and len(rest):
        parts.append(geonames(rest))
    pop = pd.concat(parts, ignore_index=True)
    pop = pop.drop(columns=["range_any_frac"], errors="ignore").merge(
        districts[["district_id", "range_any_frac"]], on="district_id", how="left")

    # exposure base (configs: rural_in_range; India override agricultural workers)
    base_default = cfg["demand"]["exposure_base"]
    base_ind = cfg["demand"].get("india_exposure_base", base_default)
    pop["exposure_base"] = np.where(
        (pop.iso3 == "IND") & (base_ind == "agricultural_workers_in_range") & pop.agri_workers.notna(),
        "agricultural_workers_in_range", "rural_in_range")
    if "exposure_in_range" not in pop:
        pop["exposure_in_range"] = np.nan
    base_val = np.where(pop.exposure_base == "agricultural_workers_in_range", pop.agri_workers, pop.pop_rural)
    pop["exposure_in_range"] = np.where(pop.exposure_in_range.notna() & (pop.pop_source.str.startswith("worldpop")),
                                        pop.exposure_in_range, base_val * pop.range_any_frac.fillna(0.0))
    if pop.district_id.duplicated().any():
        raise AssertionError("duplicate district population rows")
    os.makedirs(out_dir, exist_ok=True)
    pop.to_csv(os.path.join(out_dir, "district_population.csv"), index=False)
    return pop


if __name__ == "__main__":
    import yaml
    with open(os.path.join(REPO, "configs", "model.yaml")) as f:
        cfg = yaml.safe_load(f)
    p = build(cfg)
    print(p.groupby(["pop_source"]).agg(n=("district_id", "size"), pop=("pop_total", "sum")))
