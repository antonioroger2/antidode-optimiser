# Antivenom Optimiser — End-to-End Model Audit

Audit date: 2026-10-15 · Scope: `dataset/`, `preprocess/`, `optimise/`, `data/`, `docs/`, `OPERATIONAL_RESEARCH_CONTEXT.md` · Focus: India (811 districts), because that is the only country with real polygon intersection.

Everything numeric below was produced by running the repository's own code (`get_enriched_districts_for_country('India')` → `solve_p_median(k_hubs=8)` with UI defaults) on the shipped `GLOBAL_SNAKE_ANTIVENOM_DISTRICT_OPTIMIZATION_MASTER.csv.gz`.

---

## 0. Verdict in one paragraph

The species-presence layer (WHO range polygons ∩ WHO ADM2 districts) is genuine WHO-derived data and the GIS step is sound. Almost everything downstream of it is either a constructed estimate with no reproducible source or a proxy, and two bugs dominate the output: (1) the "district population" fed to the solver is not a district population at all — it is a species-level global number, identical (321,817,535) for 703 of 811 districts; (2) district vial demand ignores population entirely — each species' national death estimate is split equally across every district in its range. The "golden hour" parameter does not enter the optimisation; it is only reported afterwards. The solver is a greedy + capped interchange heuristic, not a MIP, and has no capacity constraint. **Current hub locations and vial numbers are mathematically produced but not epidemiologically meaningful.** The pipeline is fixable, and the fix is mostly about replacing the demand model, not adding model complexity.

---

## 1. Data lineage

```text
WHO ArcGIS FeatureServer  SNBPROD_Views
 ├─ layer 1  master_features_layer_v ──► who_snake_species_habitation_polygons.geojson   (range polygons, code_cat)      [WHO, real]
 ├─ layer 2  background_features_v   ──► who_snake_species_master_spatial.geojson         (373 species; Impacted_Population,
 │                                                                                         Pop_percentage, URLs)        [WHO, real]
 ├─ table 6  antivenom_and_manufacturers_v ─► data/raw/who_snb_antivenom_manufacturers.csv [WHO, real — NOT fetched by any script]
WHO ArcGIS  Detailed_Boundary_ADM2 (IND) ──► who_india_adm2_district_polygons.geojson     [WHO, real]
WHO ArcGIS  Detailed_Boundary_ADM0       ──► who_detailed_boundary_adm0_countries.json    [WHO, real, unused]
OWID / IHME GBD 2019                     ──► deaths-from-snakebite-envenoming.csv          [India 2019 = 51,100 deaths; real, national only]
??? (no script, no source)               ──► STATE_WISE_MORTALITY.csv                      [unsourced, unused]
??? (no script in repo)                  ──► DEATHS-SPECIES_WISE.csv  = layer 2 attributes
                                              + 10 constructed columns (Vulnerable_Population, Annual_Estimated_*,
                                                CFR treated/untreated, Standard_Antivenom_Vials_Required, coverage status)
                                                                                                  │
preprocess/gis_intersection.py  (district ∩ species polygon, planar deg²; hard-coded antivenom rules)
          ──► WHO_EXACT_GIS_INDIA_DISTRICT_SNAKE_OVERLAP.csv (5,361 district-species rows)
??? (no script in repo)          ──► WHO_EXACT_GIS_GLOBAL_DISTRICT_SNAKE_OVERLAP.csv
                                                                                                  │
preprocess/build_master.py  (join species attributes by Scientific_Name onto every district row)
          ──► GLOBAL_SNAKE_ANTIVENOM_DISTRICT_OPTIMIZATION_MASTER.csv.gz (197,830 rows × 31 cols)
                                                                                                  │
optimise/db.py ──► SQLite `records`
optimise/app.py :: get_enriched_districts_for_country()  → district dicts {population, species[]}
optimise/solver.py :: solve_p_median() → hubs, assignment, calculate_node_vial_allocation() → vials
optimise/templates/index.html  (Leaflet map, KPIs, "Golden Hour Coverage", manifests, CSV export)
```

Reproducibility gaps: `DEATHS-SPECIES_WISE.csv` enrichment and the global overlap file have no generating code in this repo (docs point to `../OR/reproduce_full_pipeline_from_scratch.py`, outside the project). `preprocess/epidemiology.py` returns early because the columns already exist, and its own rules (CFR 15/25/12/4 %, vials 10/8/4) do not match the values in the CSV (CFR 35/75/50/18/…, vials 4/10/12/15). So the shipped numbers cannot be regenerated from the repo.

---

## 2. Ground truth vs derived vs assumed

| Quantity | Status | Evidence |
|---|---|---|
| Species range polygons, species list, WHO Category 1/2 | **Ground truth (WHO expert-consensus presence)** | WHO says range maps are "indicative and not absolute". They encode *possible occurrence*, not abundance. |
| District polygons, names, centroids | **Ground truth (WHO GIS)** | 813 India ADM2 units; 811 survive (Lakshadweep, Diu have no overlap ≥ 0.05 %). |
| `SPECIES_DISTRICT_OVERLAP_PCT` | **Derived, valid** | Area share of district inside range polygon. It is a presence-extent measure, not density. |
| `Impacted_Population` (= `humanPopRange`) | **Ground truth (WHO/WorldPop 2020), but global per species** | Daboia russelii: 1,693,793,208 = everyone inside its whole 6-country range. Not per district. |
| `Pop_percentage` | Ground truth, **misdescribed in docs** | 0.2117 for Daboia = share of *world* population (1.69 B / ~8 B), not "% of country population". |
| National snakebite deaths, India | **Ground truth (modelled)** | GBD 2019 via OWID: 51,100. MDS (Suraweera 2020) ≈ 1.2 M deaths 2000–2019, ~94 % rural. |
| `Vulnerable_Population` | **Assumption** | Exactly `humanPopRange × c` with c ∈ {0.002, 0.08, 0.09, 0.18, 0.28} by region. Attributed to Longbottom 2018 in docs, but it is a constant multiplier. |
| `Annual_Estimated_Deaths_India` per species | **Constructed allocation** | Sums to 51,023 ≈ GBD's 51,100 → national total split across species by weights. Species shares cited as MDS; verbal autopsy rarely identifies species reliably, and I could not verify those shares. B. sindanus and E. carinatus both get exactly 2,034.8 — looks like an allocation artefact. |
| `Annual_Estimated_Bites/Envenomations/Deaths_Global` | **Constructed** | Global deaths sum to 63,359 vs WHO's 81,000–138,000 → internally inconsistent with the WHO figure cited. |
| `Untreated/Treated_Case_Fatality_Rate_Pct` | **Assumption (genus-level literature values)** | 13 distinct values only; e.g. all *Bungarus* = 75 %. No per-row citation. |
| `Standard_Antivenom_Vials_Required` | **Assumption** | Only 4/10/12/15. Echis = 4 vials is not the Indian protocol (initial dose is not species-specific in India's polyvalent regimen). Repeat doses ignored. |
| `ANTIVENOM_EFFICACY_STATUS`, `RECOMMENDED_ANTIVENOM_NAME` (India) | **Hard-coded rules** in `gis_intersection.py` | Overrides the WHO antivenom table. Creates products that don't exist as Indian SKUs ("Experimental Monovalent Pit Viper Antivenom"). |
| Global non-India overlap = 100 %, intersection area = district area | **Fabricated defaults** | `build_master.py` sets these; labelled "EXACT_GIS". |
| Tortuosity 1.45, 45 km/h, 2 h "golden hour", 0.08 L/vial, 3-month cycle, z-table | **Assumptions** | Reasonable placeholders, none sourced. "Golden hour ≤ 2 h" is not a WHO-defined snakebite standard. |
| `STATE_WISE_MORTALITY.csv` | **Unsourced, unused** | "Envenomation rate" 2.5–8.9/100 k gives 67 k envenomings nationally ≈ the death count, i.e. an implied CFR near 100 % — not plausible. |
| `CITY_SNAKE_POPULATION.csv` | Ground truth (species–country checklist) | Despite the name, there are **no counts** — it lists which species occur in which country. |

### 2.1 Your direct question: is there a number for "species r per district" or "snakes per q people"?

**No. Neither WHO nor any national source in India gives snake abundance or density per district, and there is no validated "snakes per human" ratio.**

What WHO actually provides:
1. **Presence**: range polygons (yes/no, expert-drawn, coarse).
2. **`Impacted_Population`**: the number of people living *inside the whole range* of a species, worldwide. This is the "critical number" you are thinking of. It is a per-species global exposure count, not per district, and not a bite rate.
3. **Antivenom products** per species (table 6), with specificity and WHO assessment status.

What WHO does **not** provide: abundance, density, district or state incidence, envenoming counts, or antivenom demand. The underlying science (Longbottom et al., Lancet 2018) maps *vulnerability* on a 5 × 5 km grid: population within range × travel time to care × antivenom availability × HAQ index. That is exposure plus health-system access, not incidence.

You *can* legitimately compute a district analogue of `Impacted_Population`: run a zonal sum of a WorldPop raster over (district ∩ species range). That gives "people in district i living within range of species r" — a valid **exposure** variable. It is still not demand.

### 2.2 Should higher species richness or density mean higher priority?

**No, not directly.** Bite incidence is driven by human–snake *encounter*: rural agricultural labour (paddy, sugarcane), housing type, sleeping on the floor (kraits), monsoon season, footwear, and night-time activity. Across most of India the Big Four are present nearly everywhere in the plains, so presence barely discriminates between districts. Richness discriminates mainly in the Northeast, where the extra species are mostly Category-2 pit vipers with low mortality.

Empirical check on your model: the 9 states that NAP-SE (MoHFW 2024) says account for about 70 % of deaths hold 45 % of India's districts. They receive 51 % of the model's vial demand, and only 40 of the top-100 "hazard" districts. The top hazard districts are Assam and North Bengal (Koch Bihar, Lakhimpur, Dibrugarh…), driven by species count (corr(Γ, #species) = 0.58). **The model's risk surface disagrees with observed mortality.**

Species should enter the model in only two places:
- **Which product** is needed (product–species compatibility).
- **Optionally, dose per course** (e.g. viper coagulopathy with repeat doses vs. elapid neurotoxicity), sourced from the Indian Standard Treatment Guidelines.

The **amount** of demand should come from incidence data (deaths, cases, ASV consumption) scaled by rural population.

---

## 3. Variable inventory (from code)

### 3.1 Input / observed data
| Code name | Notation | Unit | Source | Status | Resolution | Used in |
|---|---|---|---|---|---|---|
| `DISTRICT_NAME`, `STATE_NAME` | i | — | WHO ADM2 `ADM2_VIZ_NAME`, `ADM1_NAME` | observed | district | dict key (name only) |
| `CENTER_LAT/LON` | (φᵢ, λᵢ) | deg | WHO ADM2 | observed | district | d_ij |
| `SCIENTIFIC_NAME`, `CODE_SSN`, `FAMILY` | s | — | WHO layer 1/2 | observed | species | grouping |
| `MEDICAL_IMPORTANCE_CATEGORY` | I(cat1) | binary | WHO `code_cat` per polygon | observed | species-polygon | Γ, danger score |
| `humanPopRange` | — | persons | WHO `Impacted_Population` | observed | species, global | not in solver |

### 3.2 Derived indicators
| Code name | Notation | Unit | Derivation | Status | Used in |
|---|---|---|---|---|---|
| `SPECIES_DISTRICT_OVERLAP_PCT` | ω_is·100 | % | planar intersection / district area | derived | Γ, demand |
| `INTERSECTION_AREA_SQ_DEG`, `DISTRICT_TOTAL_AREA_SQ_DEG` | — | deg² | Shapely | derived | not used |
| `district_presence_count` | n_s | districts | `COUNT(DISTINCT DISTRICT_NAME)` per species (app.py) | derived | demand denominator |
| `dist_matrix` | d_ij | km | Haversine | derived | objective |
| travel time | T_ij = 1.45·d_ij/45 | h | — | derived | reporting only |
| `hazard_gradient` | Γ_i | "points" (0–~550) | Σ_s ω_is(0.40·CFRᵤ + 35·I(cat1) + 0.25·min(100, 20·log₁₀D_s)) | derived | weight Ω_i, heatmap |
| `DANGER_SCORE` | — | 0–100 | 0.40·CFR + 25·cat + 0.20·(25·log D) + 0.15·overlap | derived | UI ranking only |

### 3.3 Assumptions / calibration constants
| Code name | Value | Where | Status |
|---|---|---|---|
| `population` (district) | = `Vulnerable_Population` of the **first species row** of that district | app.py `get_enriched_districts_for_country` | **bug** |
| `Vulnerable_Population` | humanPopRange × {0.002…0.28} | CSV | assumed |
| `Annual_Estimated_Deaths_India/Global` | per species | CSV | constructed |
| `Untreated_/Treated_Case_Fatality_Rate_Pct` | 2.5–98 % | CSV | assumed |
| `Standard_Antivenom_Vials_Required` | v_s ∈ {4,10,12,15} | CSV | assumed |
| `TORTUOSITY`, `AVG_SPEED_KMH` | 1.45, 45 | solver.py | assumed |
| weight exponents | β = 0.5, Γ/50 | solver.py L335 (L312 version with 0.65, Γ/25 is dead code) | assumed |
| defaults via `or` | pop 50,000; deaths 25; presence 50; CFR 15; vials 10; overlap 100 | solver.py L138, L166–171 | **silent imputation** |
| `SERVICE_LEVEL_Z` | snapped to nearest of 6 levels | solver.py L101 | approx |
| reserve | max(6, ⌈m·2·v_max⌉), m = 0.5 if multi-brand | L232 | assumed |
| refrigeration | 0.08 L/vial | L235 | assumed |
| `surge_factor` | 2.5 for "monsoon" | app.py | assumed |

### 3.4 Decision variables (as implemented)
| Variable | Meaning | Type | Determined by |
|---|---|---|---|
| `chosen_indices` | open hubs H ⊂ I, \|H\| = k | combinatorial set (≈ y_j) | greedy + interchange heuristic |
| `assignment` | nearest open hub per district (≈ x_ij) | derived from H | argmin distance — **not a free decision** |
| `total_vials_allocated` per hub × product | stock S_jb | integer | **closed-form formula after location**, not optimised |

There is no Δ_ij, no capacity variable, no z_jp, no w_ijᵖ in code — those exist only in `OPERATIONAL_RESEARCH_CONTEXT.md`.

### 3.5 Objective components (actual)
Only one: Σᵢ Ωᵢ · min_{j∈H} d_ij, with Ωᵢ = Pᵢ^0.5 · (1 + Γᵢ/50)^γ.

### 3.6 Constraint parameters
`k_hubs` (cardinality), `disabled_hub_district` (excluded candidate). That is all. `max_travel_hours` and `total_vial_cap` act after the solve.

### 3.7 UI-only / post-hoc values (do not influence location)
`max_travel_hours` → `within_golden_hour`, `pct_covered_in_golden_hour`; `stockout_risk_pct` (= 1 − service level, a tautology); `assigned_population`, `total_population_at_risk` (shows 229,886,461,694 "people at risk" for India); `refrigeration_liters`; `DANGER_SCORE`; heatmap intensity; `product_sourcing` (nearest hub stocking product — post-hoc); triage windows in `evaluate_emergency_dispatch`.

---

## 4. What is actually optimised

### 4.1 Location (solver.py `solve_p_median`)

$$
\min_{H\subseteq I,\;|H|=k,\;j_{\text{off}}\notin H}\;\; \sum_{i\in I} \Omega_i \min_{j\in H} d_{ij},
\qquad \Omega_i = P_i^{0.5}\left(1+\tfrac{\Gamma_i}{50}\right)^{\gamma}
$$

This is an uncapacitated p-median, solved heuristically: a 1-median seed, then greedy add, then first-improvement 1-swap capped at 10 passes. Units of Ω are √persons × dimensionless, so the objective is in "√person-km" with no physical meaning. Not MIP, not capacitated, no latency term.

Checks run:
- Running the interchange to convergence lowers the objective by **1.52 %** and changes 6 of 8 hubs. The code comment "guarantee optimal hub placement" is false.
- `max_travel_hours = 1` and `= 4` give **identical hubs**.
- `hazard_weight` 0 → 1 → 3 changes most hubs, but cannot be validated because Γ has no empirical anchor.

### 4.2 Assignment
xᵢⱼ = 1 for the nearest open hub. It is fully determined by H.

### 4.3 Vial allocation (`calculate_node_vial_allocation`), per hub j and product b

$$
\text{env}_{is} = \psi \cdot \frac{D_s^{\text{India}}}{n_s}\cdot\frac{100}{\max(2,\text{CFR}^u_s)}\cdot\max(0.05,\omega_{is}),\qquad
\Lambda_{jb} = \sum_{i\in C_j}\sum_{s:\,b\in B(s)} \frac{v_s}{|B(s)|}\,\text{env}_{is}
$$
$$
CS = \lceil \Lambda L\rceil,\quad SS = \lceil z\sqrt{\max(1,\;CS\cdot\max(1, v_{\max}/2))}\rceil,\quad ER = \max(6,\lceil m\cdot 2v_{\max}\rceil),\quad S_{jb}= CS+SS+ER
$$

with L = 3/12. **Population does not appear.** Demand depends on how many species overlap the district and on national per-species death shares divided by range size.

Results for India, k = 8: 273,529 vials stocked; 4.8 % of "population" within 2 h; mean 451 min; worst 56 h. Example district annual demand: Kolkata 1,552 vials vs Bardhaman 1,574 vs Chennai 1,301. Urban and high-burden rural districts come out the same.

---

## 5. Flaws, ranked

Severity: **C** = invalidates results · **H** = materially distorts · **M** = weakens defensibility · **L** = hygiene.

| # | Sev | Where | Flaw | Why it matters | Fix |
|---|---|---|---|---|---|
| 1 | C | app.py `get_enriched_districts_for_country` | `population` = `Vulnerable_Population` of the first species row. 703/811 districts get 321,817,535 (B. caeruleus' global value); Himalayan districts get 1.8 M. | Ωᵢ is driven by row order, not people. The UI shows hubs serving 25–49 *billion* people. | Join real district population (Census 2011 + projection, or WorldPop zonal sum over the ADM2 polygons you already have). Use rural population. |
| 2 | C | solver.py L190 | Demand = national species deaths ÷ #districts in range — equal split, no population, no rurality. | Vial numbers have no relationship to where bites happen. | Replace with the incidence-based demand in §7.2. |
| 3 | C | solver.py L386–390, L522 | Golden-hour limit is not in the objective or constraints; only reported. Hubs (k ≈ 8) are warehouses, yet "golden hour" measures warehouse→district-centroid time. Covering every district centroid within 2 h would need about **335** hubs (greedy set cover). | A warehouse network cannot meet a patient-treatment time target. The KPI conflates resupply time with time-to-antivenom. | Separate the echelons: a hub→facility resupply time constraint (hours to a day), and patient→nearest ASV-stocking PHC/CHC access as its own metric. |
| 4 | C | `DEATHS-SPECIES_WISE.csv` | 10 enrichment columns with no generating code; species death shares constructed to sum to the GBD national total; global deaths inconsistent with WHO; `epidemiology.py` does not reproduce them. | Core demand inputs are unverifiable. Examiners will ask for the source of every number. | Delete the per-species death allocation. Anchor demand to national/state totals with cited sources; keep species for product mapping only. |
| 5 | C | gis_intersection.py L118–129, solver.py L179 | Efficacy and products are hard-coded, overriding the WHO antivenom table. Non-existent SKUs ("Experimental Monovalent Pit Viper Antivenom") receive stock (e.g. 4,790 vials at Namakkal). The unneutralised flag looks for "Deficit"/"Unneutralized", which the India strings never contain → always empty. | Stocks products that can't be procured, and hides species with no effective antivenom. | Map species→product from table 6 filtered to products licensed in India. Species with no product → report "no effective antivenom", exclude from vial demand. |
| 6 | H | solver.py L48–71 | Γ adds a CFR (%), a category bonus (points) and a log-death score across all species → dimensionally mixed and monotone in species richness. Its doc formula differs from the code. It is also used both in location weights and (via the same species list) in demand → double counting of species risk. | Pulls hubs to the species-rich Northeast against the observed burden (§2.2). | Drop Γ from location weights. Weight by expected ASV courses λᵢ. Keep species only for product mix. |
| 7 | H | master data | 170 duplicate (district, species) rows in 79 districts — multipart range polygons not dissolved. | Double-counts demand and Γ. | `unary_union` per species before intersection, or `groupby(district, species)` summing overlap (capped at 100). |
| 8 | H | solver.py L227–253 | σ = √(CS·v/2) is ad hoc (compound-Poisson σ with fixed course size v is √(CS·v)); ER is stacked on top of SS (double buffer); review period and lead time are conflated (L = 3 months); `stockout_risk_pct` just restates the input. | Safety stock is underestimated for the main product and overstated for rare SKUs. The service level is asserted, not achieved. | Base-stock on courses: S = v·F⁻¹_Poisson(Λ_c(R+L))(α), computed exactly. Report the achieved fill rate. |
| 9 | H | solver.py L190 | envenomings = deaths / CFR_untreated assumes every death was untreated → lower bound. Implied ≈ 114,000 envenomings/yr nationally, while NAP-SE quotes an estimated 3–4 million bites/yr. | Demand scale is likely off by a large factor. | Calibrate to case data (IHIP/CBHI ~3 lakh reported cases/yr, with an under-reporting factor) and validate against state ASV procurement/consumption. |
| 10 | H | README, UI, docs | "MIP", "capacitated", "optimal", "Multi-Product Optimal Allocation". | Overclaims. An examiner will check and find a heuristic. | Solve the p-median exactly as a MILP (PuLP/OR-Tools + HiGHS), or report the heuristic's gap to the LP bound. Rename the UI labels. |
| 11 | M | solver.py L138, L166–171 | `x or default` turns legitimate zeros into defaults (0 deaths → 25; 0 population → 50,000). | Silent fabrication. | Use explicit `is None` / NaN checks; fail loudly on missing inputs. |
| 12 | M | solver.py L440–456 | The "knapsack rationing" is proportional scaling with an ER floor; it can exceed the cap; no priority. | Doesn't match the documentation; not a decision model. | A small LP: maximise expected courses served subject to the cap. |
| 13 | M | build_master.py | Non-India rows: overlap = 100 %, intersection = district area, labelled EXACT_GIS; no code for the global overlap file. | Global output is not comparable to India. | Restrict the project scope to India, or run the same intersection globally. |
| 14 | M | solver.py | Haversine × 1.45 at 45 km/h, centroid to centroid. | Large error in hilly or riverine districts (NE, Himalaya, Sundarbans). | OSRM / OpenRouteService travel-time matrix (811² is easy). |
| 15 | M | docs | `Vulnerable_Population` attributed to Longbottom but is a constant multiplier; `Pop_percentage` misdescribed; row count 197,660 vs actual 197,830; Γ and ER formulas differ between doc and code. | Documentation does not describe the implementation. | Regenerate the docs from the code after the fixes. |
| 16 | L | gis_intersection.py | Areas in planar deg². | The overlap *ratio* within a district is fine; absolute areas are meaningless. | Reproject to an equal-area CRS (e.g. EPSG:6933 or an Albers projection for India) if areas are reported. |
| 17 | L | identifiers | Districts keyed by name only (WHO spellings like `AURANGAABAD`, `HAMIIRPUR`); municipal corporations as separate ADM2 units (Navi Mumbai, Aurangabad Corp). | Won't join to Census/LGD/IHIP; fragile. | Key on `(ADM1, ADM2)` and build a crosswalk to LGD district codes. |
| 18 | L | `STATE_WISE_MORTALITY.csv` | Unsourced, unused, implausible. | It will be taken as data if anyone finds it. | Remove it, or source it. |

---

## 6. Is the current output scientifically defensible?

| Output | Defensible? | Reason |
|---|---|---|
| Species presence per district (map, species lists) | **Yes**, as "possible occurrence per WHO range maps" | Real WHO data, correct intersection (after deduplication). |
| Antivenom product per species | **Partly** | The WHO table is real, but the India rules are hard-coded and invent SKUs. |
| Danger score / hazard heatmap | **No** | Arbitrary weights; anti-correlated with the observed state burden. |
| Hub locations | **No** | Weights dominated by the population bug and species richness. |
| Vial quantities | **No** | No population term; constructed death shares; ad-hoc buffers. |
| Golden-hour coverage | **No** | Not optimised; measures the wrong leg of the supply chain. |
| Scenario deltas (surge ×2.5, outage) | **Mechanically correct, substantively empty** | A linear scaling of an invalid baseline. |

---

## 7. Corrected formulation (minimum that withstands review)

### 7.1 Sets
- I: districts (LGD-coded).
- J ⊆ I: candidate hub sites (district HQ hospitals or existing state drug warehouses).
- P: antivenom products licensed in India (in practice, polyvalent ASV, with any others only if table 6 lists them as registered in India).
- S: species, with S_p ⊆ S neutralised by product p (from WHO table 6).

### 7.2 Demand (the core fix)

For district i and season/month m:

$$
\lambda_{i} \;=\; \underbrace{R_i}_{\text{rural pop}} \cdot \underbrace{\rho_{\text{state}(i)}}_{\text{ASV-treated envenomings per person-yr}} \cdot \underbrace{e_i}_{\text{exposure adj.}}
\qquad\text{(courses/yr)},
\qquad
\lambda_{ip} = \lambda_i \cdot \pi_{ip},\;\; \text{vials}_{ip} = \lambda_{ip}\, \bar v_p
$$

- **R_i**: rural population, Census or WorldPop zonal sum. Observed.
- **ρ_state**: calibrated from data, in order of preference:
  1. State ASV consumption (RTI or NHM procurement records), directly in vials.
  2. IHIP/IDSP reported cases × an under-reporting factor (scenario range).
  3. MDS/GBD state deaths ÷ an effective CFR (scenario range).
- **e_i**: optional exposure adjustment (agricultural workforce share, or the share of the population within Big-Four range). Default 1. Its effect should be shown through sensitivity analysis, not assumed.
- **π_ip**: share of envenomings in i needing product p. ≈ 1 for polyvalent wherever Big Four are present. Species without an effective product go to a separate "no antivenom" metric.
- **v̄_p**: mean vials per treated case, including repeat doses, from the MoHFW Standard Treatment Guidelines or hospital audits. Use a range (low/base/high), not a single constant.
- **Seasonality**: monthly factors (monsoon peak) from IHIP monthly counts, if obtainable.

Every parameter is either observed or an explicit scenario parameter. Nothing is a hidden constant.

### 7.3 Location (exact MILP)

Decision variables: y_j ∈ {0,1}; x_ij ∈ [0,1] (single-sourcing integrality holds at optimum for an uncapacitated p-median; make it binary if capacities are added); u_i ≥ 0 (uncovered demand).

$$
\min \sum_{i}\sum_{j} \lambda_i\, t_{ij}\, x_{ij} \;+\; M\sum_i \lambda_i u_i
$$
$$
\sum_j x_{ij} + u_i = 1\;\;\forall i,\qquad x_{ij}\le y_j,\qquad \sum_j y_j = k,\qquad x_{ij}=0 \text{ if } t_{ij} > T^{\text{resupply}},
$$
$$
\sum_i \lambda_i \bar v\, x_{ij} \le \text{Cap}_j\, y_j \;\;(\text{if cold-chain capacities known}),\qquad y_{j_{\text{off}}}=0 .
$$

- t_ij: road travel time (OSRM).
- T^resupply: a logistics standard (e.g. same-day or 24 h), **not** the clinical golden hour.
- Objective units: course-hours (expected treatment courses × resupply hours), which is interpretable.
- Equivalent alternative if the policy goal is coverage: a maximal covering location problem (MCLP), maximising Σλᵢzᵢ subject to Σyⱼ = k.

### 7.4 Inventory per hub and product (exact, no normal approximation)

Courses during review period R plus lead time L follow N_jp ~ Poisson(Λ_jp(R+L)), with Λ_jp = Σᵢ λ_ip x_ij.

$$
S_{jp} = \bar v_p \cdot \min\{s : F_{\text{Poisson}(\Lambda_{jp}(R+L))}(s) \ge \alpha\}
$$

Report the achieved cycle service level and the expected shortage (vials) from the actual distribution. Add a negative-binomial variant if monthly counts are overdispersed.

### 7.5 Patient-access metric (separate, not in the hub model)

A_i = share of district population within T* hours of a facility that stocks ASV (PHC/CHC/DH, from the National Health Facility Registry or the PMGSY road network). This is where a clinical time threshold belongs, labelled as an assumption.

### 7.6 Uncertainty
Run low/base/high scenarios on ρ, v̄ and the under-reporting factor; report the stability of hub sets (how often each hub is chosen) and the vial ranges. With these inputs, this is more defensible than a single point estimate.

---

## 8. Implementation plan (priority order)

| Phase | Task | Files | Exit criterion |
|---|---|---|---|
| 1 | Fix the population bug: attach a real district population (WorldPop 2020 zonal sum over `who_india_adm2_district_polygons.geojson`; rural share from Census 2011) | new `preprocess/district_population.py`, app.py | India total ≈ 1.4 B; no district shares a value by accident |
| 1 | Deduplicate district–species rows; dissolve multipart ranges | gis_intersection.py | 0 duplicates |
| 1 | Remove `or`-defaults; raise on missing values | solver.py | tests fail loudly on missing inputs |
| 2 | New demand module (§7.2) with explicit parameter file `configs/demand.yaml` (each value with source/citation and low/base/high) | new `preprocess/demand.py` | λᵢ table with provenance column |
| 2 | Species→product from WHO table 6 (fetch it in `fetch_who_data.py`); delete invented SKUs | gis_intersection.py, build_master.py | every stocked SKU appears in the WHO table as licensed in India |
| 3 | Exact p-median / MCLP MILP (PuLP + HiGHS or OR-Tools) with OSRM times and resupply constraint; keep the heuristic only as a warm start, and report the gap | solver.py | optimal (or bounded-gap) solution, objective in course-hours |
| 3 | Poisson base-stock (§7.4) | solver.py | achieved service level reported |
| 4 | Validation: compare λ by state against MDS/GBD state deaths and IHIP cases; hold out a state; sensitivity tornado on ρ, v̄, k | notebooks/ | correlation and error reported; stable hub sets |
| 4 | Strip Γ/danger score from the optimisation (keep as descriptive UI only, renamed "species presence index"); fix UI labels and KPIs | index.html | no "optimal/MIP/golden hour" claim that the code doesn't support |
| 5 | Regenerate docs from code; one reproducible `run_pipeline.sh` that rebuilds every processed file | docs/, scripts/ | fresh clone → identical master file |

Phase 1–2 are essential. Without them no downstream result is interpretable. Phase 3 is what makes it an OR project. Phase 4 is what makes it defensible.

---

## 9. Data you need (and where it lives)

| Need | Source | Resolution | Note |
|---|---|---|---|
| District population, rural share | Census 2011 (PCA tables); WorldPop 2020 1 km rasters (zonal sum) | district / 1 km | WorldPop is consistent with WHO's own `Impacted_Population` |
| District codes | MoPR Local Government Directory (LGD) | district | crosswalk WHO ADM2 names → LGD |
| Snakebite cases & deaths | IHIP / IDSP (MoHFW, NCDC) — case-based reporting; snakebite was made notifiable nationally in 2024, with several states earlier | district, monthly | heavily under-reported (NAP-SE: only ~7 % of deaths officially reported) — use for spatial *pattern*, not level |
| Mortality level | Million Death Study (Suraweera et al., eLife 2020); GBD 2019 | state / national | anchor for totals |
| Burden distribution | NAP-SE 2024 (NCDC) | state | ~70 % of deaths in 9 states |
| ASV consumption / procurement | State medical services corporations (e.g. TNMSC, KMSCL, BMSICL) tenders; RTI; NHM Free Drugs Initiative | state / facility | the best direct measure of vials demand |
| Vials per treated case | MoHFW Standard Treatment Guidelines for snakebite; published Indian hospital audits | protocol | use a range |
| Species–product compatibility | WHO table 6 (`antivenom_and_manufacturers_v`) | species | already in `data/raw`, not fetched by script |
| Health facilities | National Health Facility Registry; HMIS facility lists | point | for the patient-access metric |
| Road travel times | OSRM / OpenRouteService on OpenStreetMap | network | replace Haversine × 1.45 |
| Vulnerability (optional covariate) | Longbottom et al., Lancet 2018, 5 km grids | 5 km | exposure + access, not incidence |

---

## 10. What the results can legitimately claim

**Can claim now:** where WHO range maps indicate medically important species may occur, per district; which WHO-listed antivenom products cover them; and a working decision-support tool architecture for location–inventory analysis.

**Cannot claim now:** where antivenom demand is; how many vials any hub needs; that hubs are optimal; that any population is within a clinically meaningful treatment time.

**Can claim after Phases 1–4:** "Under stated demand scenarios calibrated to [source], an exact p-median/MCLP places k resupply hubs minimising expected course-weighted resupply time; base-stock levels achieve service level α under Poisson demand; results are robust/sensitive to …". This is still a planning model, not a stocking order. Before anyone treats it as a real recommendation, it needs validation against state ASV consumption records and review by clinicians and state drug-logistics staff.

---

### Sources
- WHO Snakebite Information and Data Platform — overview: https://www.who.int/teams/control-of-neglected-tropical-diseases/snakebite-envenoming/snakebite-information-and-data-platform/overview
- WHO SNBPROD_Views FeatureServer (layers 0–2, tables 3–6): https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/SNBPROD_Views/FeatureServer
- Longbottom et al., Lancet 2018, vulnerability mapping (IHME summary): https://healthdata.org/research-article/vulnerability-snakebite-envenoming-global-mapping-hotspots
- National Action Plan for Prevention and Control of Snakebite Envenoming (NAP-SE), NCDC/MoHFW 2024: https://ncdc.mohfw.gov.in/wp-content/uploads/2024/07/NATIONAL-ACTION-PLAN-FOR-PREVENTION-AND-CONTROL-OF-SNAKEBITE-ENVENOMING-NAPSE.pdf
- Suraweera et al., eLife 2020, Trends in snakebite deaths in India 2000–2019: https://elifesciences.org/articles/54076
- Yale Environment Review summary of Suraweera et al.: https://environment-review.yale.edu/node/5118

---

# 11. Applied fixes (2026-10-15)

| # | Finding | Fix (file) | Verified by |
|---|---|---|---|
| 1 | District population = species-level global constant | Real population per district: Census of India 2011 areally interpolated onto WHO ADM2 (equal-area CRS, 99.5 % of 1.211 B conserved); WorldPop 2020 1 km backend for every country; GeoNames settlements as an explicitly **provisional** fallback (`preprocess/population.py`) | `test_india_census_interpolation_conserves_population`, `test_india_demand_and_population_are_real` |
| 2 | Demand ignored population | λ_i = D_c^GBD · ρ · p_AV · x_i / Σx, x_i = rural (India: agricultural workers) population inside ≥1 WHO range (`optimise/demand.py`) | `test_demand_conservation` (Σλ = national total exactly) |
| 3 | Golden hour not in the model; wrong supply-chain leg | Renamed to a hub→district **resupply** standard. Default objective = p-median on course-hours; optional lexicographic MCLP→p-median uses T as an objective, with a certified gap | `test_matches_brute_force` (coverage + cost, 30 instances) |
| 4 | Unsourced per-species deaths/CFR/doses | Removed from the optimisation. Burden anchored to GBD-2019 country deaths; ρ, p_AV, dose and repeat probability are explicit, sourced or labelled assumptions with low/base/high scenarios (`configs/model.yaml`) | `/api/sensitivity` |
| 5 | Invented products, broken "unneutralised" flag | Products come only from the WHO antivenom table; registration per country parsed from WHO comments; portfolio chosen by an exact ILP (max clinical suitability, then min SKUs); species with no procurable product reported as "no effective antivenom" and not stocked (`preprocess/antivenom.py`) | `test_catalogue_products_are_real_who_products`, `test_no_invented_products` |
| 6 | Hazard gradient Γ (dimensionally mixed, species-richness driven) | Removed from optimisation and UI; species only affect the product mix (κ_cat weights) | — |
| 7 | 170 duplicate district–species rows | Ranges dissolved per species before intersection; global presence rebuilt reproducibly (centroid-in-range where no polygons) | `test_presence_no_duplicates` |
| 8 | Ad-hoc safety stock, stacked reserve, tautological stock-out risk | (R,S) policy with exact compound-Poisson demand (Poisson splitting); S = smallest level with P(X ≤ S) ≥ α; fill rate and expected shortage computed from the distribution | `test_quantile_vs_monte_carlo`, `test_pmf_moments` |
| 9 | Demand lower bound via untreated CFR | Replaced by WHO-derived envenomings-per-death ratio (13 / 20.5 / 35.5) | scenario tests |
| 10 | "MIP/optimal/capacitated" claims for a heuristic | Exact: MCLP (HiGHS) → Lagrangian relaxation (subgradient) with exact candidate elimination → HiGHS MILP on remaining candidates; optional capacity with single-sourcing. Reports lower bound and gap | brute force + capacitated exhaustive enumeration tests |
| 11 | `or`-defaults turning 0 into 25 deaths etc. | No silent imputation anywhere; missing inputs raise | — |
| 12 | Proportional "rationing" | Optimal allocation for the separable concave problem max Σ E[min(X,S)] s.t. Σ S ≤ C (greedy marginal = exact) | `test_rationing_is_optimal_and_within_cap` |
| 13 | Global overlap = 100 %, no generator code | `preprocess/presence.py` regenerates everything; exact polygon overlap for every country whose ADM2 polygons are present | rebuild agreed with old pairs on 99.6 % |
| 15 | Doc/code mismatch | This section + README updated from the code | — |
| 17 | Districts keyed by name only | `district_id = ISO3|ADM1|ADM2` (unique, tested) | `test_every_presence_row_has_a_district_and_species` |
| 18 | Unsourced STATE_WISE_MORTALITY.csv | No longer read by any code | — |

Old modules (`gis_intersection.py`, `build_master.py`, `epidemiology.py`, `db.py`) are replaced by stubs that raise on import.

**Limitations that remain:** one global ρ (implies one CFR everywhere); p_AV and vials-per-course are planning assumptions; within-district exposure is assumed uniform where only census totals exist; travel time is great-circle × circuity (plug in an OSRM matrix when available); hubs are resupply nodes, not treatment points; every country except India uses provisional GeoNames population until `dataset/fetch_global_inputs.sh` is run.
