# A Multi-Commodity Capacitated Facility Location and Stochastic Inventory Blending Model for Time-Critical SNAKE - Antivenom Logistics

---

## Abstract
Snakebite envenomation is designated by the World Health Organization (WHO) as a high-priority Neglected Tropical Disease (NTD), accounting for over 58,000 fatalities annually in South Asia alone. The clinical efficacy of antivenom therapy is critically governed by the **"Golden Hour"** window ($\le 2.0$ hours), beyond which tissue necrosis, coagulopathy, and neurotoxic respiratory paralysis induce irreversible physiological trauma or death. Designing an optimal antivenom supply chain involves two coupled Operations Research (OR) challenges: (i) an integer programming **Capacitated $p$-Median Facility Location Problem (C-PFLP)** subject to continuous envenomation hazard gradients and transit latency penalties, and (ii) a **Stochastic Multi-Product Inventory Allocation and Blending Model** that determines the exact vial stocking levels across interchangeable therapeutic formulations while accounting for Poisson demand uncertainty, risk-pooled safety stocks, and cold-chain volume limits. Furthermore, to overcome the fatal limitations of monolithic single-hub assignment, we formulate a **Decoupled Multi-Commodity Network Flow** model where high-velocity broad-spectrum polyvalents are sourced from primary local nodes, while rare monovalent formulations are independently fulfilled by specialized tertiary reserves. This document details the mathematical formulations, decision variables, objective functions, constraints, and algorithmic solution methods underpinning the decision support framework.

**Index Terms—** Operations Research, Facility Location, $p$-Median, Integer Programming, Multi-Product Inventory Control, Blending Problem, Stochastic Poisson Processes, Risk Pooling, Humanitarian Logistics, Cold Chain Optimization.

---

## I. Introduction and Problem Context

Envenomation logistics exhibits unique structural complexities that distinguish it from standard commercial supply chain networks:
1. **Extreme Asymmetric Mortality Risk:** Unlike commercial stockouts that result in marginal lost sales, an antivenom stockout or transit delay yields a binary survival transition. The untreated Case Fatality Rate (CFR) for neurotoxic elapid (*Bungarus caeruleus*, *Naja naja*) or hemotoxic viperid (*Daboia russelii*, *Echis carinatus*) envenomations ranges from $35\%$ to $75\%$, dropping to below $3.5\text{--}6.0\%$ when standard therapeutic dosages ($10\text{--}20$ vials) are administered within the first $120$ minutes.
2. **Geographic Inequity & Epidemiological Heterogeneity:** Snakebite incidence does not correlate linearly with general population density. High-density urban centers frequently exhibit low snakebite morbidity, whereas agrarian and tribal districts endure severe envenomation pressure ($\Gamma_i \gg 100$). Naive centroid-based facility location clusters distribution stockrooms inside metropolitan areas, leaving peripheral agrarian populations outside the Golden Hour envelope.
3. **Multi-Brand Interchangeability & Formulation Blending:** Commercial antivenoms are manufactured across different therapeutic brands and production batches (e.g., equine $F(ab')_2$ fragments from Serum Institute of India, Bharat Serums, Premium Serums, and VINS Bioproducts). Multiple commercial brands often neutralize the identical target snake species. The inventory model must optimize procurement and stockroom storage across interchangeable products via blending ratios, avoiding single-source vulnerabilities while maintaining clinical efficacy.
4. **Cold Chain Constraints:** Antivenom vials (liquid formulations) require continuous refrigeration between $2^\circ\text{C}$ and $8^\circ\text{C}$ ($0.08\text{ liters/vial}$ including packaging and spacing). Unconstrained inventory accumulation violates regional cold-storage refrigeration capacities.

---

## II. Nomenclature and Mathematical Indices

### Sets and Indices
* $\mathcal{I} = \{1, 2, \dots, n\}$: Set of demand points (districts, administrative units).
* $\mathcal{J} = \{1, 2, \dots, m\}$: Set of candidate central distribution stockroom nodes ($\mathcal{J} \subseteq \mathcal{I}$).
* $\mathcal{S} = \{1, 2, \dots, K\}$: Set of venomous snake species identified in the national territory.
* $\mathcal{S}_i \subseteq \mathcal{S}$: Subset of venomous species geographically endemic to demand district $i$.
* $\mathcal{P}$: Set of distinct antivenom formulations/products available in the supply chain (e.g., Polyvalent ASVS I.P., Monovalent Pit Viper ASV, King Cobra Monovalent).
* $\mathcal{B}_p$: Set of commercial brands/manufacturers manufacturing formulation $p \in \mathcal{P}$.
* $\mathcal{P}_s \subseteq \mathcal{P}$: Subset of antivenom formulations clinically indicated and effective against species $s \in \mathcal{S}$.

### Empirical System Parameters
* $P_i$: Vulnerable population census of demand district $i \in \mathcal{I}$.
* $(\text{Lat}_i, \text{Lon}_i)$: Geographic centroid coordinates of district $i$.
* $d_{ij}$: Geodesic distance (in kilometers) between hub candidate $j \in \mathcal{J}$ and district $i \in \mathcal{I}$, calculated via the Haversine metric.
* $\tau$: Highway tortuosity factor ($\tau = 1.45$), accounting for road curvature and infrastructure detours relative to geodesic vectors.
* $v$: Mean emergency ambulance dispatch speed under rural highway conditions ($v = 45.0\text{ km/h}$).
* $T_{ij} = \frac{\tau \cdot d_{ij}}{v}$: Expected transit travel time (in hours) between hub $j$ and district $i$.
* $T_{\max}$: Clinical "Golden Hour" travel latency ceiling ($T_{\max} = 2.0\text{ hours}$).
* $k$: Total number of central distribution stockroom hubs to open ($k \in \mathbb{Z}^+$).
* $\text{CFR}_s^{\text{untreated}}$: Untreated Case Fatality Rate (percentage, $0\text{--}100$) for envenomation from species $s$.
* $\text{CFR}_s^{\text{treated}}$: Treated Case Fatality Rate with timely antivenom administration.
* $\mu_s$: Standard clinical vial dosage required per bite episode for species $s$ ($\mu_s \in \{10, 20\}$ vials).
* $\omega_{is}$: Spatial overlap coefficient ($0 \le \omega_{is} \le 1$) of species $s$ within district $i$.
* $\Gamma_i$: Continuous numerical hazard gradient of district $i$.
* $\Omega_i$: Gravitational demand weight of district $i$.
* $\lambda_{j,b}$: Mean annual Poisson arrival demand rate for brand $b$ at hub $j$ (vials/year).
* $L$: Order replenishment lead time (expressed in years, e.g., $L = 0.25$ for a 3-month cycle).
* $\sigma_L$: Standard deviation of replenishment lead time.
* $1 - \alpha$: Target non-stockout service level (e.g., $0.99$).
* $Z_{1-\alpha}$: Standard normal inverse cumulative distribution value ($\Phi^{-1}(1-\alpha)$).
* $\psi$: Envenomation surge/epidemic multiplier ($\psi \ge 1.0$).
* $v_{\text{vial}}$: Unit cold-storage volumetric displacement ($v_{\text{vial}} = 0.08\text{ liters/vial}$).
* $C_j^{\text{cold}}$: Maximum cold storage capacity of hub $j$ (in liters).
* $V^{\text{national}}$: Exogenous national antivenom vial rationing ceiling under acute supply shortages.

---

## III. Optimization Model 1: Continuous-Hazard Weighted Capacitated $p$-Median Facility Location

### A. Formulation Rationale
Standard facility location models minimize population-weighted distance $\sum_i P_i d_{ij}$. However, in envenomation epidemiology, population alone is an inadequate proxy for mortality exposure. High-density metropolitan districts often exhibit low snakebite incidence, whereas rural agricultural districts experience lethal envenomations from Category 1 medically important species. 

To bridge this gap, we define a continuous numerical hazard gradient $\Gamma_i$ for each district:
$$\Gamma_i = \sum_{s \in \mathcal{S}_i} \left[ \text{CFR}_s^{\text{untreated}} \cdot \omega_{is} \cdot \left(\frac{\mu_s}{10}\right) \cdot \mathbb{I}(s \in \text{Category 1}) \right]$$
where $\mathbb{I}(\cdot)$ is an indicator function assigning priority to WHO Category 1 species (e.g., *Bungarus caeruleus*, *Naja naja*, *Daboia russelii*, *Echis carinatus*).

The effective gravitational demand attraction weight $\Omega_i$ is formulated as a non-linear interaction between baseline census population and continuous hazard severity:
$$\Omega_i = P_i^{\beta} \cdot \left(1 + \frac{\Gamma_i}{50.0}\right)^{\gamma}$$
where $\beta = 0.50$ balances scale sensitivity, and $\gamma \ge 1.0$ governs the gravitational pull of high-CFR clusters.

### B. Mathematical Program (Integer Linear Program with Latency Penalty)

#### Decision Variables:
* $y_j \in \{0, 1\} \quad \forall j \in \mathcal{J}$: Equals $1$ if candidate facility $j$ is selected as an operational central distribution hub; $0$ otherwise.
* $x_{ij} \in \{0, 1\} \quad \forall i \in \mathcal{I}, j \in \mathcal{J}$: Equals $1$ if demand district $i$ is assigned to hub $j$ as its primary response stockroom; $0$ otherwise.
* $\Delta_{ij} \ge 0 \quad \forall i \in \mathcal{I}, j \in \mathcal{J}$: Continuous excess latency variable representing transit time exceeding the Golden Hour threshold.

#### Objective Function:
$$\min_{x, y, \Delta} \quad Z_1 = \sum_{i \in \mathcal{I}} \sum_{j \in \mathcal{J}} \Omega_i \cdot d_{ij} \cdot x_{ij} + M \sum_{i \in \mathcal{I}} \sum_{j \in \mathcal{J}} \Omega_i \cdot \Delta_{ij}$$

where $M \gg 0$ is a non-linear penalty parameter that heavily penalizes assignments extending beyond the clinical survival window.

#### Constraints:
1. **Cardinality of Central Hubs:** Exactly $k$ facilities must be activated across the national territory:
   $$\sum_{j \in \mathcal{J}} y_j = k$$

2. **Single Primary Hub Assignment:** Each demand district must be assigned to exactly one primary distribution hub:
   $$\sum_{j \in \mathcal{J}} x_{ij} = 1 \quad \forall i \in \mathcal{I}$$

3. **Facility Activation Prerequisite:** Demand can only be allocated to an established hub:
   $$x_{ij} \le y_j \quad \forall i \in \mathcal{I}, \forall j \in \mathcal{J}$$

4. **Golden Hour Excess Latency Definition:**
   $$\Delta_{ij} \ge \left(T_{ij} - T_{\max}\right) \cdot x_{ij} \quad \forall i \in \mathcal{I}, \forall j \in \mathcal{J}$$
   $$\Delta_{ij} \ge 0 \quad \forall i \in \mathcal{I}, \forall j \in \mathcal{J}$$

5. **Exclusion of Disrupted Facilities (Resilience Constraint):**
   If a hub $j_{\text{failed}}$ suffers an operational outage (e.g., flood, infrastructure failure):
   $$y_{j_{\text{failed}}} = 0$$

6. **Integrity and Non-negativity Constraints:**
   $$y_j \in \{0, 1\} \quad \forall j \in \mathcal{J}$$
   $$x_{ij} \in \{0, 1\} \quad \forall i \in \mathcal{I}, \forall j \in \mathcal{J}$$

---

## IV. Optimization Model 2: Multi-Product & Multi-Brand Stochastic Inventory Blending

Once the optimal set of hubs $\mathcal{J}^* = \{j \mid y_j^* = 1\}$ and their respective catchment district partitions $\mathcal{C}_j = \{i \mid x_{ij}^* = 1\}$ are determined, the inventory stocking model calculates the itemized vial manifest required at each hub node.

### A. Therapeutic Brand Blending and Substitution Model
In healthcare supply chains, reliance on a single commercial manufacturer creates critical vulnerability. When multiple registered brands $b \in \mathcal{B}_p$ provide equivalent neutralization against target envenomations, the demand is blended across available brands.

Let $\theta_{p, b}$ denote the allocation proportion assigned to brand $b$ for formulation $p$, satisfying:
$$\sum_{b \in \mathcal{B}_p} \theta_{p, b} = 1.0, \quad \theta_{p, b} \ge 0 \quad \forall b \in \mathcal{B}_p$$
In the baseline operational model, an equi-proportionate dual-sourcing rule is adopted:
$$\theta_{p, b} = \frac{1}{|\mathcal{B}_p|} \quad \forall b \in \mathcal{B}_p$$
This ensures diversified risk pooling across active pharmaceutical suppliers.

### B. Expected Annual Demand Calculation
For a hub $j$ and brand $b$ corresponding to formulation $p$, expected annual demand $\Lambda_{j, b}$ is computed by aggregating envenomation incidence over all districts in its catchment:
$$\Lambda_{j, b} = \psi \sum_{i \in \mathcal{C}_j} \sum_{s \in \mathcal{S}_i \cap \mathcal{S}(p)} \theta_{p, b} \cdot \left(\frac{P_i}{100,000}\right) \cdot \lambda_s^{\text{base}} \cdot \mu_s \cdot \omega_{is}$$
where:
* $\mathcal{S}(p)$ is the set of species neutralized by formulation $p$.
* $\lambda_s^{\text{base}}$ is the empirical envenomation incidence per 100,000 population.
* $\psi$ is the surge multiplier parameter.

### C. Tripartite Inventory Decomposition: Cycle Stock, Safety Stock, and Clinical Reserve
The total inventory $I_{j, b}$ maintained at hub $j$ for brand $b$ is decomposed into three orthogonal components:
$$I_{j, b} = CS_{j, b} + SS_{j, b} + ER_{j, b}$$

#### 1. Cycle Stock ($CS_{j, b}$):
Represents inventory consumed between deterministic periodic replenishment cycles:
$$CS_{j, b} = \left\lceil \Lambda_{j, b} \cdot L \right\rceil$$
where $L$ is the replenishment order cycle expressed in years ($L = \frac{T_{\text{months}}}{12}$).

#### 2. Stochastic Risk-Pooled Safety Stock ($SS_{j, b}$):
Envenomation arrivals follow a non-homogeneous Poisson process. Under stochastic replenishment lead times with mean $L$ and variance $\sigma_L^2$, the variance of lead-time demand $\sigma_{\text{LTD}}^2$ is given by the standard compound renewal identity:
$$\sigma_{\text{LTD}}^2 = \mathbb{E}[L] \cdot \operatorname{Var}(D) + (\mathbb{E}[D])^2 \cdot \operatorname{Var}(L) = L \cdot \Lambda_{j, b} + \Lambda_{j, b}^2 \cdot \sigma_L^2$$
Assuming deterministic replenishment delivery ($\sigma_L = 0$), the Poisson variance reduces to $\sigma_{\text{LTD}} = \sqrt{L \cdot \Lambda_{j, b}}$.

To guarantee a non-stockout service level probability of at least $1 - \alpha$:
$$\mathbb{P}\left(\text{Demand in Lead Time} \le CS_{j, b} + SS_{j, b}\right) \ge 1 - \alpha$$
The required safety stock buffer is:
$$SS_{j, b} = \left\lceil Z_{1-\alpha} \cdot \sqrt{L \cdot \Lambda_{j, b}} \right\rceil$$

#### 3. Emergency Clinical Reserve ($ER_{j, b}$):
Because envenomation patients present as acute medical crises requiring immediate full multi-vial courses, inventory must never drop below a hard clinical treatment threshold:
$$ER_{j, b} = \max\left( R_{\min}, \quad 2 \cdot \max_{s \in \mathcal{S}(p)} \mu_s \right)$$
where $R_{\min} \in \{20, 30\}$ vials guarantees full initial treatment capacity for at least two concurrent catastrophic admissions.

### D. Cold-Chain Volumetric Constraints
Each vial requires dedicated refrigerated storage space. The total cold-chain capacity required at hub $j$ must satisfy:
$$V_j = v_{\text{vial}} \sum_{p \in \mathcal{P}} \sum_{b \in \mathcal{B}_p} I_{j, b} \le C_j^{\text{cold}}$$

---

## V. Decoupled Multi-Commodity Network Flow Model

### A. The Structural Fallacy of Single-Commodity Assignment
In classical facility location formulations, a single commodity is assumed. A demand district $i$ is assigned entirely to a single hub $j^*$. In antivenom logistics, this assumption leads to severe operational failure:
* **Empirical Reality:** $>95\%$ of all snakebite envenomations in South Asia are caused by the "Big Four" species (*B. caeruleus*, *N. naja*, *D. russelii*, *E. carinatus*), which are fully neutralized by standard **Polyvalent Anti-Snake Venom Serum (ASVS) I.P.**
* Only a tiny fraction ($<5\%$) of envenomations are caused by specialized or orphan species (e.g., King Cobra *Ophiophagus hannah* or Montane Pit Vipers *Trimeresurus* spp.), requiring specialized monovalent antivenoms.
* If a primary local stockroom (e.g., Hub #8 Surat, Gujarat) stocks Polyvalent ASVS but lacks King Cobra Monovalent, a naive single-commodity model assigns Gujarat to a distant Himalayan or national center (e.g., Hub #1 Leh, Ladakh, 2,343 km away) simply to cover the orphan species. This forces thousands of emergency Big Four patients to endure a 52-hour transit delay.

### B. Decoupled Multi-Commodity Mathematical Formulation
To resolve this distortion, we decouple the geographic assignment of demand district $i$ across individual antivenom commodities $p \in \mathcal{P}$.

#### Additional Decision Variables:
* $w_{ij}^p \in \{0, 1\} \quad \forall i \in \mathcal{I}, j \in \mathcal{J}, p \in \mathcal{P}$: Equals $1$ if district $i$ sources antivenom formulation $p$ from hub $j$; $0$ otherwise.
* $z_{jp} \in \{0, 1\} \quad \forall j \in \mathcal{J}, p \in \mathcal{P}$: Equals $1$ if hub $j$ is authorized and equipped to stock product formulation $p$.

#### Decoupled Routing Program:
$$\min_{w} \quad Z_{\text{transport}} = \sum_{p \in \mathcal{P}} \sum_{i \in \mathcal{I}} \sum_{j \in \mathcal{J}} \Phi_{i, p} \cdot d_{ij} \cdot w_{ij}^p$$

where $\Phi_{i, p}$ is the expected annual envenomation demand for specific formulation $p$ originating in district $i$:
$$\Phi_{i, p} = \psi \sum_{s \in \mathcal{S}_i \cap \mathcal{S}(p)} \left(\frac{P_i}{100,000}\right) \cdot \lambda_s^{\text{base}} \cdot \mu_s \cdot \omega_{is}$$

#### Constraints:
1. **Product Demand Fulfillment:** Every district requiring formulation $p$ must be supplied:
   $$\sum_{j \in \mathcal{J}} w_{ij}^p = 1 \quad \forall i \in \mathcal{I}, \forall p \in \mathcal{P} \text{ such that } \Phi_{i, p} > 0$$

2. **Stock Availability Linking:** District $i$ can source product $p$ from hub $j$ only if hub $j$ is operational and stocks product $p$:
   $$w_{ij}^p \le z_{jp} \le y_j \quad \forall i \in \mathcal{I}, \forall j \in \mathcal{J}, \forall p \in \mathcal{P}$$

3. **Independent Nearest-Stocking Sourcing Rule:**
   For each required product $p$, district $i$ is routed to the closest operational hub that maintains positive inventory of formulation $p$:
   $$w_{ij}^p = 1 \iff j = \arg\min_{\ell \in \mathcal{J} : z_{\ell p} = 1} d_{i\ell}$$

#### Managerial Consequence:
Under this decoupled model:
* Devbhumi Dwarka (Gujarat) sources $100\%$ of its high-velocity Polyvalent ASVS from **Hub #8 (Surat, Gujarat)** with road transit within the operational window.
* In the rare event of a specialized envenomation requiring an orphan monovalent not stored at Surat, that specialized SKU alone is dispatched from the nearest specialized tertiary node, without compromising the local cold-chain delivery of polyvalent vials.

---

## VI. Disruption Robustness, Outage Simulation, and Vial Rationing

### A. Single-Node Outage Re-Optimization (Resilience Analysis)
To assess network vulnerability under catastrophic node failure (e.g., regional power failure destroying cold-chain integrity or transport infrastructure shutdown), the model executes an outage simulation:
1. Fix $y_{j_{\text{failed}}} = 0$ for a designated hub $j_{\text{failed}} \in \mathcal{J}^*$.
2. Re-solve the $p$-median optimization over the remaining candidate set $\mathcal{J} \setminus \{j_{\text{failed}}\}$ with $k - 1$ or $k$ active hubs.
3. Quantify the degradation metrics:
   $$\Delta \bar{T} = \bar{T}_{\text{post-outage}} - \bar{T}_{\text{baseline}}$$
   $$\Delta \text{Coverage} = \text{Pop}_{\text{GoldenHour}}^{\text{baseline}} - \text{Pop}_{\text{GoldenHour}}^{\text{post-outage}}$$

### B. National Supply Cap Knapsack Rationing
During national supply shortages or manufacturing delays, total inventory across all hubs is constrained by an exogenous ceiling $V^{\text{national}}$:
$$\sum_{j \in \mathcal{J}^*} \sum_{p \in \mathcal{P}} \sum_{b \in \mathcal{B}_p} I_{j, b} \le V^{\text{national}}$$

When unconstrained demand exceeds $V^{\text{national}}$, inventory is rationed via a **Priority-Preserving Knapsack Allocation Algorithm**:
1. **Preserve Clinical Reserves:** Emergency reserves $ER_{j, b}$ are protected as non-negotiable hard constraints to prevent complete clinical stockouts.
2. **Proportional Safety Stock Compression:** The remaining available vial budget $(V^{\text{national}} - \sum ER)$ is allocated proportionally to cycle stock and safety stock:
   $$\rho = \frac{V^{\text{national}} - \sum_{j, b} ER_{j, b}}{\sum_{j, b} (CS_{j, b} + SS_{j, b})}$$
   $$I_{j, b}^{\text{rationed}} = ER_{j, b} + \max\left(0, \left\lfloor \rho \cdot (CS_{j, b} + SS_{j, b}) \right\rfloor\right)$$

---

## VII. Computational Solution Algorithm

The mixed-integer $p$-median problem with latency penalties is known to be $\mathcal{NP}$-hard. To deliver interactive sub-second responses within the web-based decision support system across national datasets ($n > 750$ districts), we implement a hybrid heuristic algorithm combining **Greedy Forward Selection** with **1-Interchange Local Search (2-Opt Vertex Substitution)**:

```
Algorithm 1: Continuous-Hazard Capacitated p-Median Solver
Input: Demand set I, Candidate set J, k, max_travel_hours, hazard_weight
Output: Selected hubs J*, District assignments x*

1:  Compute Haversine distance matrix D = [d_ij] for all i, j in I
2:  Compute Continuous Hazard Gradient Gamma_i for each district i in I
3:  Compute Gravitational Demand Weights:
        Omega_i = (Pop_i)^0.50 * (1 + Gamma_i / 50.0)^hazard_weight
4:  // Step 1: 1-Median Seed Selection
5:  Seed hub j_1 = argmin_{j in J} sum_{i in I} (Omega_i * d_ij)
6:  J* = {j_1}
7:  // Step 2: Forward Greedy p-Median Expansion
8:  while |J*| < k do:
9:      j_best = null; best_cost = infinity
10:     for each candidate c in J \ J* do:
11:         trial_set = J* U {c}
12:         cost = sum_{i in I} [ Omega_i * min_{j in trial_set} (d_ij) ]
13:         if cost < best_cost then:
14:             best_cost = cost; j_best = c
15:     J* = J* U {j_best}
16: end while
17: // Step 3: 1-Interchange Local Search Refinement (2-Opt)
18: improved = true; iterations = 0
19: while improved and iterations < 10 do:
20:     improved = false; iterations = iterations + 1
21:     for each active hub h in J* do:
22:         for each non-active candidate c in J \ J* do:
23:             trial_set = (J* \ {h}) U {c}
24:             trial_cost = sum_{i in I} [ Omega_i * min_{j in trial_set} (d_ij) ]
25:             if trial_cost < current_best_cost - epsilon then:
26:                 J* = trial_set; current_best_cost = trial_cost
27:                 improved = true; break
28:         if improved then break
29: end while
30: // Step 4: Geodesic Physical District Assignment
31: for each district i in I do:
32:     x*_{i, j} = 1 for j = argmin_{j in J*} (d_ij); 0 otherwise
33: // Step 5: Multi-Brand Blending & Inventory Manifest
34: for each active hub j in J* do:
35:     Compute Cycle Stock CS, Safety Stock SS, Reserve ER via Poisson Model
36:     Compute Decoupled Sourcing Matrix w*_{ij}^p for all products p
37: return J*, x*, w*, InventoryManifest
```

---

## VIII. Decision Support System (DSS) Implementation Architecture

The mathematical formulations are operationalized within a full-stack Decision Support System:
* **Backend Mathematical Engine:** Python 3 / NumPy / SciPy running on high-performance vector operations.
* **Geospatial & Statistical Layer:** SQLite database containing 41,053 districts globally, cross-referenced with WHO snake envenomation species distributions, published untreated/treated Case Fatality Rates, and clinical dosing guidelines.
* **Interactive Frontend UI:** Single-page dashboard built with Vanilla JavaScript, Leaflet.js GIS mapping, Leaflet.heat kernel density surfaces, and Chart.js analytics.
* **Operational Capabilities Provided to Decision Makers:**
  1. Real-time parameterized re-optimization across varying hub counts ($k \in [3, 16]$).
  2. Dynamic Golden Hour travel ceiling adjustments ($T_{\max} \in [1.0, 4.0\text{ hours}]$).
  3. Interactive single-district species vulnerability lookup (e.g., Devbhumi Dwarka threat matrix).
  4. Real-time simulated hub outage disruption stress-testing.
  5. Multi-product cold-chain inventory manifest exports formatted for healthcare procurement ministries.

---

## IX. Conclusion and Managerial Implications

The integration of **Continuous Hazard Attraction** within integer facility location models resolves the critical distortion of standard centroid clustering, ensuring that emergency antivenom stockrooms are physically anchored near high-lethality agricultural communities. Furthermore, formalizing **Decoupled Multi-Commodity Routing** eliminates the catastrophic penalty of single-commodity assignment, enabling healthcare supply chains to maintain local, life-saving delivery of broad-spectrum polyvalent antivenoms while centralizing specialized orphan formulations at regional tertiary centers. This technical framework demonstrates how rigorous Operations Research methodologies directly mitigate preventable human mortality in humanitarian public health supply chains.