# Data dictionary

Coordinate reference systems: download and display in **EPSG:4326** (lon/lat); analysis in **EPSG:32636** (UTM zone 36N, metres).

Polygons (campuses, parks, hospitals, shop areas) are stored as **centroids**.

## `data/raw/cankaya_boundary.geojson`

Çankaya district polygon from Nominatim / OSMnx.

## `data/raw/cankaya_pois.geojson`

All Overpass POIs with exclusive `category` and `group`.

| Column | Description |
| --- | --- |
| amenity, leisure, highway, railway, shop | Original OSM tags; office and isced:level are also retained |
| name | OSM name (often missing) |
| category | cafe, restaurant, university, school, kindergarten, government, office, hospital, park, shop, bus_stop, metro, other |
| group | target_business, demand, transit, network, other |
| geometry | Point, EPSG:32636 |

Priority when tags overlap: metro / bus stop → café → restaurant → university → school → kindergarten → government → office → hospital → park → shop.

## Layer files

| File | OSM filter |
| --- | --- |
| `cankaya_cafes.geojson` | amenity=cafe |
| `cankaya_restaurants.geojson` | amenity=restaurant or fast_food |
| `cankaya_universities.geojson` | amenity=university |
| `cankaya_schools.geojson` | amenity=school; ISCED tags retained |
| `cankaya_offices.geojson` | office=* excluding government and higher-priority categories |
| `cankaya_government.geojson` | office=government |
| `cankaya_kindergartens.geojson` | amenity=kindergarten |
| `cankaya_hospitals.geojson` | amenity=hospital or clinic |
| `cankaya_parks.geojson` | leisure=park |
| `cankaya_shops.geojson` | shop=* (and not claimed by a higher-priority tag) |
| `cankaya_bus_stops.geojson` | highway=bus_stop |
| `cankaya_metro.geojson` | railway=station or subway_entrance |
| `cankaya_road_intersections.geojson` | OSMnx drive graph nodes with street_count ≥ 3 |
| `cankaya_walk_edges.parquet` | OSMnx walk graph edges (pedestrian ways) |
| `cankaya_mahalle.geojson` | OSM admin_level=8 mahalle polygons clipped to Çankaya |

## TÜİK input (you provide)

`data/raw/tuik/cankaya_mahalle_nufus.csv` (or `.xlsx`)

| Column | Required |
| --- | --- |
| mahalle_name | yes |
| pop_total | yes |
| pop_15_34 | no (not in the 2025 mahalle extract) |

Population is allocated as `pop_total × (cell∩mahalle area / mahalle area)`.

## Cell features (`data/processed/cankaya_grid_features.parquet`)

| Variable | Description | Expected effect |
| --- | --- | --- |
| cafes_500m | Cafés within 500 m | RF target; not a suitability pillar |
| cafes_cell | Distinct mapped cafés inside the centre 300 m cell | Competition context |
| cafes_9_cells | Distinct mapped cafés in the centre plus 8 surrounding cells | Competition context |
| cafes_25_cells | Distinct mapped cafés in the 5×5 block | Competition context |
| competition_level | Number of user-defined thresholds crossed (0–3): ≥2 / ≥6 / ≥13 | Warning layer and negative MCDA competition component |
| covered_cells_9, covered_cells_25 | Cells inside Çankaya included in the 3×3 and 5×5 blocks | Boundary coverage warning |
| restaurants_500m | Restaurants/fast food within 500 m | Negative saturation component |
| bus_stops_400m | Transit access | Positive |
| metro_distance | Distance to nearest metro (m) | Negative as distance grows |
| universities_1000m | Universities nearby | Positive |
| schools_750m | Explicit ISCED 2/3 schools nearby; legacy dataset contains generic schools | Positive demand |
| parks_500m | Parks nearby | Positive |
| shops_500m | Retail activity | Positive |
| offices_500m, government_500m, kindergartens_500m | New demand generators within 500 m; absent from committed legacy data | Positive demand |
| school_level_unknown_count | District-wide number of schools without ISCED level; absent in legacy data | Coverage disclosure |
| hospitals_1000m | Hospitals/clinics within 1000 m | Context |
| road_intersections | Intersections inside the cell | Pedestrian activity proxy |
| poi_diversity | Count of nearby amenity types, including cafés in stored data | Not used in MCDA; RF recomputes without cafés |
| population | Areal-weighted mahalle pop_total | Positive |
| population_density | people / km² | Positive |
| pop_15_34 | Empty until mahalle age data exists | — |
| mahalle_name | Dominant overlapping mahalle | — |
| street_name | Nearest named OSM walk way within 250 m (label only) | — |
| population_source | `tuik_areal_weight_total_only` | — |

The grid competition columns are added when the feature matrix is rebuilt with raw café coordinates. They are absent from the currently committed Parquet; the app can compute them from downloaded café GeoJSON instead. `cafes_500m` alone cannot reconstruct these counts.

## Suitability pillars (`src/scoring.py`)

Default weights: demand 45%, access 25%, population 20%; restaurant saturation penalty 3%, café competition penalty 7%. User scenario preferences, not fitted to profit.

| Column | Description |
| --- | --- |
| demand_score | 0–1 mix: university .30, shops .25, ISCED 2/3 schools .15, parks .10, offices .10, government .05, kindergartens .05; available subweights are renormalized |
| demand_missing_features | Missing demand layers; missing does not mean zero mapped venues |
| accessibility_score | 0–1 mix: bus stops .45, inverse metro distance .35, intersections .20 |
| population_score | Min–max population density, or population if density is absent |
| saturation_score | Min–max restaurants_500m; constant zero = 0, constant positive = 1, missing = NaN |
| competition_score | competition_level / 3; missing = NaN |
| positive_contribution | 100 × weighted positive pillars / their weight total |
| saturation_penalty | 100 × saturation weight × saturation_score |
| competition_penalty | 100 × competition weight × competition_score |
| score_provisional | True if an enabled penalty cannot be computed |
| suitability_score | Positive contribution minus penalties; clipped to 0–100 and rounded to one decimal |
| cafe_similarity_score | 0–100 held-out RF probability, recomputed by the app; stored legacy values use the former model and must not be treated as current validation |

Positive pillars are rescaled across the district before UI filtering. Restaurant saturation is also scaled before filtering. Missing penalties are omitted from the numeric score and flagged as provisional. Popularity is disabled and has no effect. Missing ISCED columns exclude all schools from the refreshed secondary-school count; this differs from the disclosed generic-school legacy dataset.
