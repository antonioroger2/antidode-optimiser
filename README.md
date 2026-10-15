# Antidote & Antivenom Logistics Optimizer (GOAD)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Flask 3.0](https://img.shields.io/badge/flask-3.0+-green.svg)](https://flask.palletsprojects.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)]()
[![Data: WHO / WorldPop / IHME](https://img.shields.io/badge/data-WHO%20%7C%20WorldPop%20%7C%20IHME-blueviolet.svg)](https://www.who.int/teams/control-of-neglected-tropical-diseases/snakebite-envenoming)
[![Operations Research: MIP](https://img.shields.io/badge/Operations%20Research-p--Median%20MIP-orange.svg)]()

A unified spatial-epidemiological framework, reproducible data processing pipeline, and interactive Operations Research web application. Integrates **World Health Organization (WHO) GIS vector habitation polygons**, **41,053 global administrative districts & cities**, **WorldPop gridded demographic exposure layers**, **peer-reviewed clinical lethality benchmarks**, and **WHO antivenom manufacturer catalogs** into a high-fidelity master optimization dataset and real-time clinical dispatch platform.

---


## ⚙️ Model (2026 rebuild) — read this first

* **Demand**: GBD-2019 snakebite deaths per country × envenomings-per-death (WHO-derived) × share needing antivenom, distributed to WHO ADM2 districts by rural (India: agricultural-worker) population living inside WHO species ranges. Every parameter is in `configs/model.yaml` with its status (observed / calibrated / assumption) and low–base–high scenarios.
* **Products**: only WHO-catalogued antivenoms; per-country portfolio chosen by an exact ILP; species with no procurable product are reported, not stocked.
* **Location**: exact p-median on course-hours (optionally coverage-first MCLP), solved with Lagrangian bounds + exact candidate elimination + HiGHS MILP. Each solution carries a lower bound, a gap and a `proven_optimal` flag.
* **Inventory**: (R,S) order-up-to levels from the exact compound-Poisson distribution; optimal rationing under a national vial cap.
* **Population**: India uses Census 2011 (real). Other countries are **provisional** (GeoNames settlements) until you run `./dataset/fetch_global_inputs.sh && ./scripts/run_pipeline.sh` (WorldPop 2020 + WHO ADM2 polygons).
* Full audit and the list of applied fixes: `docs/MODEL_AUDIT.md`. Worldwide batch: `python3 scripts/run_world.py`.

## 🏛️ Modular Repository Architecture

The codebase is organized into clean, dedicated modules following production standards:

```
antidode-optimiser/
├── dataset/                  # Data acquisition & extraction scripts
│   ├── fetch_who_data.sh     # Shell script to curl official WHO ArcGIS FeatureServers
│   ├── fetch_who_data.py     # Python client for dataset acquisition
│   └── DATA_DICTIONARY.md    # API endpoints & field definitions
│
├── preprocess/               # ETL, planar GIS spatial intersections & epidemiology
│   ├── gis_intersection.py   # Shapely polygon-polygon intersection engine
│   ├── epidemiology.py       # Clinical case fatality rates & attribution logic
│   └── build_master.py       # Pipeline orchestrator to compile the master dataset
│
├── data/                     # Clean, structured data repository (git-friendly)
│   ├── raw/                  # Official reference CSVs and country/district boundaries
│   ├── spatial/              # WHO GeoJSON vector habitation & district boundaries
│   └── processed/            # Master tables, overlap records, and compressed master CSV.gz
│
├── optimise/                 # Operations Research solver & interactive Web Dashboard
│   ├── app.py                # Flask REST API backend
│   ├── solver.py             # p-Median MIP solver, Haversine matrices, & clinical triage
│   ├── db.py                 # SQLite database connector & on-demand auto-initializer
│   └── templates/
│       └── index.html        # Interactive Leaflet GIS web UI with dark mode
│
├── tests/                    # Automated testing suite
│   ├── test_preprocessing.py # Geometry, column schema & CFR validation tests
│   └── test_optimization.py  # Mathematical solver & Flask API endpoint tests
│
├── scripts/                  # Operational execution & runner scripts
│   ├── run_app.sh            # Launch interactive web dashboard
│   ├── run_tests.sh          # Run complete test suites
│   └── run_pipeline.sh       # Recompile master optimization dataset
│
├── docs/                     # Comprehensive scientific documentation
│   └── DATASET_DOCUMENTATION.md # Detailed data dictionary and methodologies
│
├── .gitignore                # Pushes safely without massive >100MB binaries
├── .gitattributes            # Line endings & binary rules
├── requirements.txt          # Python dependency specifications
├── pyproject.toml            # PEP 517/621 packaging metadata
└── LICENSE                   # MIT License
```

---

## 📌 Problem & Motivation

Snakebite envenoming causes over **100,000 fatalities** and **400,000 permanent disabilities** annually, predominantly in rural South Asia, Sub-Saharan Africa, and Latin America.

Traditional supply chain formulations suffer from **Centroid Collapse**: allocating cold-chain antivenom warehouses based on geographic population centroids places stock in central urban metropolises, far from remote rural perimeters where severe envenomations occur.

This framework solves this by coupling:
1. **Exact Planar GIS Habitat Intersections** ($Area_{\text{overlap}} \text{ and } \%$) with administrative boundaries.
2. **Clinical Severity & Golden Hour Constraints** ($T_{\max} \le 120\text{ min}$) to ensure antivenom reaches patients before irreversible neuro/hemotoxicity occurs.
3. **Multi-Species Mismatch Penalties** accounting for species-specific antivenom neutralization profiles (monovalent vs. polyvalent).
4. **Operations Research p-Median MIP Facility Location** to optimally position cold-chain distribution stockrooms.

---

## 🚀 Quickstart & Usage

### 1. Installation
```bash
git clone https://github.com/your-org/antidode-optimiser.git
cd antidode-optimiser

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Launch the Interactive Web Dashboard
```bash
./scripts/run_app.sh
```
Open your browser to: **`http://127.0.0.1:8080`**

> **Note on Database Initialization:**
> `optimise/db.py` automatically checks for `snakebite_optimizer.db`. If absent (e.g. on a fresh git clone), it will decompress and load `data/processed/GLOBAL_SNAKE_ANTIVENOM_DISTRICT_OPTIMIZATION_MASTER.csv.gz` (5.9 MB) in ~2 seconds and build composite indices.

### 3. Run Test Suites
```bash
./scripts/run_tests.sh
```

### 4. Re-fetch Raw Data & Run Preprocessing Pipeline
```bash
# Download raw layers from WHO ArcGIS REST API
./dataset/fetch_who_data.sh

# Recompile the master optimization dataset
./scripts/run_pipeline.sh
```

---

## 🌐 Web Application Features

1. **District-Level Hazard & Species Profiling**:
   - Filter by country and administrative district.
   - Live Leaflet map displaying district boundary centroids, venomous species lists, and Composite Danger Scores ($0 - 100$).
   - Clinical specimen photographs, taxonomic families, untreated vs. treated Case Fatality Rates (CFR).

2. **Emergency Clinical Dispatch & Golden Hour Triage**:
   - Input patient location, identified species, and elapsed bite time.
   - Calculates road travel times with regional tortuosity factors ($1.45 \times \text{Haversine}$).
   - Assigns triage urgency category:
     * 🟢 **SAFE WINDOW**: Elapsed + Travel $\le 2.0\text{h}$
     * 🟡 **URGENT WINDOW**: $2.0\text{h} < \text{Total} \le 4.0\text{h}$
     * 🔴 **CRITICAL WINDOW**: $\text{Total} > 4.0\text{h}$ (resuscitation/ICU alert)
   - Recommends specific antivenom vial quantities and manufacturer formulations.

3. **Operations Research Stockroom Location Optimizer**:
   - Solves the capacitated $p$-Median Facility Location problem.
   - Calculates population-weighted distance and percentage of at-risk rural population reachable within the Golden Hour ($T_{\max} \le 2\text{ hours}$).

---

## 📐 Operations Research (OR) Formulation

### A. Geodesic Haversine Distance Matrix
For candidate hub $j (\phi_j, \lambda_j)$ and district demand node $i (\phi_i, \lambda_i)$:

$$\Delta \phi = \text{radians}(\text{lat}_i - \text{lat}_j), \quad \Delta \lambda = \text{radians}(\text{lon}_i - \text{lon}_j)$$

$$a = \sin^2\left(\frac{\Delta \phi}{2}\right) + \cos(\phi_j) \cos(\phi_i) \sin^2\left(\frac{\Delta \lambda}{2}\right)$$

$$d_{ij} = 2 R \cdot \arcsin\left(\sqrt{a}\right) \quad (R = 6,371.0 \text{ km})$$

### B. Capacitated p-Median Formulation with Golden Hour Ceiling
$$\min_{\mathbf{y}, \mathbf{x}} \sum_{j \in \mathcal{J}} f_j y_j + \sum_{i \in \mathcal{I}} \sum_{j \in \mathcal{J}} c_{ij} d_{ij} \text{Demand}_i x_{ij} + \sum_{i \in \mathcal{I}} \lambda_i \text{StockoutRisk}_i$$

**Subject to:**
$$\sum_{j \in \mathcal{J}} y_j = p \quad \text{(Select exactly } p \text{ cold-chain hubs)}$$

$$\sum_{j \in \mathcal{J}} x_{ij} = 1 \quad \forall i \in \mathcal{I} \quad \text{(Every district assigned)}$$

$$d_{ij} x_{ij} \le v_{\text{avg}} \cdot T_{\max} \quad (T_{\max} \le 2.0\text{ hours}) \quad \forall i, j \quad \text{(Survival window ceiling)}$$

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).
