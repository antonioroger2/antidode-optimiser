# WHO ArcGIS Data Acquisition Dictionary & Endpoints

This document specifies the official World Health Organization (WHO) ArcGIS REST API endpoints and payload schemas used to acquire raw epidemiological and geographic distribution data.

---

### Layer 1: Snake Species Habitation Polygons
* **Endpoint URL:** `https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/SNBPROD_Views/FeatureServer/1/query`
* **Format:** GeoJSON MultiPolygons (`outSR=4326`)
* **Local Destination:** `data/spatial/who_snake_species_habitation_polygons.geojson`
* **Key Attributes:**
  - `OBJECTID`: Unique polygon identifier
  - `Scientific_Name`: Binomial species name
  - `code_ssn`: WHO species sequence identifier
  - `code_cat`: Category rating (Category 1 = Highest medical importance, Category 2 = Secondary)
  - `geometry`: EPSG:4326 MultiPolygon geometry

---

### Layer 2: Snake Species Master Clinical Layer
* **Endpoint URL:** `https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/SNBPROD_Views/FeatureServer/2/query`
* **Format:** GeoJSON (`outSR=4326`)
* **Local Destination:** `data/spatial/who_snake_species_master_spatial.geojson`
* **Key Attributes:**
  - `Scientific_Name`: Binomial Latin name
  - `PrimaryCommonName`: Standard English vernacular name
  - `Family_Name`: Taxonomic family (`Elapidae`, `Viperidae`, `Colubridae`)
  - `Impacted_Population`: WorldPop population residing within species polygon range
  - `Pop_percentage`: Percentage of country population exposed
  - `Map_pdf`: Official WHO range distribution PDF map
  - `Photo_1_url`: Verified clinical specimen photo URL

---

### Layer 3: India ADM2 District Boundaries
* **Endpoint URL:** `https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/Detailed_Boundary_ADM2/FeatureServer/0/query`
* **Filter:** `ISO_3_CODE = 'IND'`
* **Local Destination:** `data/spatial/who_india_adm2_district_polygons.geojson`
* **Key Attributes:**
  - `ADM2_NAME`: District name (e.g., Nicobar, Pune, Wayanad)
  - `ADM1_NAME`: State/Province name (e.g., Kerala, Maharashtra)
  - `CENTER_LON`, `CENTER_LAT`: Geodetic centroid coordinates
  - `Shape__Area`: Planar polygon area in square degrees

---

### Layer 4: Global ADM0 Country Boundaries
* **Endpoint URL:** `https://services.arcgis.com/5T5nSi527N4F7luB/arcgis/rest/services/Detailed_Boundary_ADM0/FeatureServer/0/query`
* **Local Destination:** `data/raw/who_detailed_boundary_adm0_countries.json`
* **Key Attributes:**
  - `ISO_2_CODE`, `ISO_3_CODE`: International standard country codes
  - `ADM0_NAME`: Official country name
  - `WHO_REGION`: WHO regional office identifier (`SEARO`, `AFRO`, `AMRO`, `EURO`, `EMRO`, `WPRO`)
