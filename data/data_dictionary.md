# Data dictionary

Coordinate reference systems: download and display in **EPSG:4326** (lon/lat); analysis in **EPSG:32636** (UTM zone 36N, metres).

Polygons (campuses, parks, hospitals, shop areas) are stored as **centroids**.

## `data/raw/cankaya_boundary.geojson`

Çankaya district polygon from Nominatim / OSMnx.

## `data/raw/cankaya_pois.geojson`

All Overpass POIs with exclusive `category` and `group`.

| Column | Description |
| --- | --- |
| amenity, leisure, highway, railway, shop | Original OSM tags |
| name | OSM name (often missing) |
| category | cafe, restaurant, university, school, hospital, park, shop, bus_stop, metro, other |
| group | target_business, demand, transit, network, other |
| geometry | Point, EPSG:32636 |

Priority when tags overlap: metro / bus stop → café → restaurant → university → school → hospital → park → shop.

## Layer files

| File | OSM filter |
| --- | --- |
| `cankaya_cafes.geojson` | amenity=cafe |
| `cankaya_restaurants.geojson` | amenity=restaurant or fast_food |
| `cankaya_universities.geojson` | amenity=university |
| `cankaya_schools.geojson` | amenity=school |
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
| cafes_500m | Cafés within 500 m | Saturation |
| restaurants_500m | Nearby restaurants | Positive (complementary) |
| bus_stops_400m | Transit access | Positive |
| metro_distance | Distance to nearest metro (m) | Negative as distance grows |
| universities_1000m | Universities nearby | Positive |
| schools_750m | Schools nearby | Context-dependent |
| parks_500m | Parks nearby | Positive |
| shops_500m | Retail activity | Positive |
| hospitals_1000m | Hospitals/clinics within 1000 m | Context |
| road_intersections | Intersections inside the cell | Pedestrian activity proxy |
| poi_diversity | Count of nearby amenity types | Positive |
| population | Areal-weighted mahalle pop_total | Positive |
| population_density | people / km² | Positive |
| pop_15_34 | Empty until mahalle age data exists | — |
| mahalle_name | Dominant overlapping mahalle | — |
| population_source | `tuik_areal_weight_total_only` | — |
