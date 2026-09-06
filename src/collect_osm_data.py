"""Download Çankaya OSM backbone: businesses, demand generators, transport."""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import geopandas as gpd
import osmnx as ox
import pandas as pd

from src import METRIC_CRS, PLACE_NAME, WGS84_CRS

warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"

# Overpass tags: target venues, demand generators, transit stops.
OSM_TAGS = {
    "amenity": [
        "cafe",
        "restaurant",
        "fast_food",
        "university",
        "school",
        "hospital",
        "clinic",
    ],
    "leisure": ["park"],
    "highway": ["bus_stop"],
    "railway": ["station", "subway_entrance"],
    "shop": True,
}

KEEP_COLUMNS = [
    "amenity",
    "leisure",
    "highway",
    "railway",
    "shop",
    "name",
    "category",
    "group",
    "geometry",
]

LAYER_FILES = {
    "cafes": "cankaya_cafes.geojson",
    "restaurants": "cankaya_restaurants.geojson",
    "universities": "cankaya_universities.geojson",
    "schools": "cankaya_schools.geojson",
    "hospitals": "cankaya_hospitals.geojson",
    "parks": "cankaya_parks.geojson",
    "shops": "cankaya_shops.geojson",
    "bus_stops": "cankaya_bus_stops.geojson",
    "metro": "cankaya_metro.geojson",
}

CATEGORY_TO_LAYER = {
    "cafe": "cafes",
    "restaurant": "restaurants",
    "university": "universities",
    "school": "schools",
    "hospital": "hospitals",
    "park": "parks",
    "shop": "shops",
    "bus_stop": "bus_stops",
    "metro": "metro",
}


def _ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "processed").mkdir(parents=True, exist_ok=True)


def _norm_tag(gdf: gpd.GeoDataFrame, column: str) -> pd.Series:
    if column not in gdf.columns:
        return pd.Series("", index=gdf.index, dtype="object")
    return gdf[column].fillna("").astype(str).str.strip().str.lower()


def classify_pois(pois: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Assign exclusive category/group. Later masks override earlier ones."""
    out = pois.copy()
    amenity = _norm_tag(out, "amenity")
    leisure = _norm_tag(out, "leisure")
    highway = _norm_tag(out, "highway")
    railway = _norm_tag(out, "railway")
    shop = _norm_tag(out, "shop")

    category = pd.Series("other", index=out.index)
    category = category.mask(shop.ne("") & shop.ne("nan") & shop.ne("none"), "shop")
    category = category.mask(leisure.eq("park"), "park")
    category = category.mask(amenity.isin(["hospital", "clinic"]), "hospital")
    category = category.mask(amenity.eq("school"), "school")
    category = category.mask(amenity.eq("university"), "university")
    category = category.mask(amenity.isin(["restaurant", "fast_food"]), "restaurant")
    category = category.mask(amenity.eq("cafe"), "cafe")
    category = category.mask(highway.eq("bus_stop"), "bus_stop")
    category = category.mask(railway.isin(["station", "subway_entrance"]), "metro")

    group = category.map(
        {
            "cafe": "target_business",
            "restaurant": "target_business",
            "university": "demand",
            "school": "demand",
            "hospital": "demand",
            "park": "demand",
            "shop": "demand",
            "bus_stop": "transit",
            "metro": "transit",
        }
    ).fillna("other")

    out["category"] = category
    out["group"] = group
    return out


def fetch_boundary(place: str = PLACE_NAME) -> gpd.GeoDataFrame:
    boundary = ox.geocode_to_gdf(place)
    if boundary.crs is None:
        boundary = boundary.set_crs(WGS84_CRS)
    return boundary.to_crs(METRIC_CRS)


def fetch_pois(place: str = PLACE_NAME) -> gpd.GeoDataFrame:
    pois = ox.features_from_place(place, tags=OSM_TAGS)
    if pois.empty:
        raise RuntimeError(f"No OSM features returned for {place}")
    if pois.crs is None:
        pois = pois.set_crs(WGS84_CRS)
    pois = pois.to_crs(METRIC_CRS)
    pois = pois[~pois.geometry.is_empty & pois.geometry.notna()].copy()
    pois["geometry"] = pois.geometry.centroid
    pois = classify_pois(pois)
    existing = [col for col in KEEP_COLUMNS if col in pois.columns]
    return pois[existing].copy()


def flatten_tag_columns(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """OSMnx sometimes stores tags as lists; flatten for GeoJSON/Parquet."""
    out = gdf.copy()
    for col in out.columns:
        if col == "geometry":
            continue
        sample = out[col].dropna()
        if sample.empty:
            continue
        if sample.map(lambda v: isinstance(v, (list, tuple))).any():
            out[col] = out[col].map(
                lambda v: ";".join(str(x) for x in v) if isinstance(v, (list, tuple)) else v
            )
    return out


def save_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flatten_tag_columns(gdf).to_file(path, driver="GeoJSON")


def save_layer_subsets(pois: gpd.GeoDataFrame) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for category, filename in LAYER_FILES.items():
        key = next(k for k, v in CATEGORY_TO_LAYER.items() if v == category)
        subset = pois.loc[pois["category"] == key].copy()
        path = RAW_DIR / filename
        save_geojson(subset, path)
        paths[category] = path
        print(f"  {category}: {len(subset)} -> {path.name}")
    return paths


def _clip_to_boundary(gdf: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    gdf = gdf.to_crs(boundary.crs)
    union = boundary.union_all() if hasattr(boundary, "union_all") else boundary.unary_union
    return gdf[gdf.intersects(union)].copy()


def fetch_road_intersections(place: str, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    graph = ox.graph_from_place(place, network_type="drive", simplify=True)
    nodes, _edges = ox.graph_to_gdfs(graph)
    nodes = nodes.to_crs(METRIC_CRS)
    if "street_count" in nodes.columns:
        nodes = nodes.loc[nodes["street_count"] >= 3].copy()
    nodes = _clip_to_boundary(nodes, boundary)
    keep = [c for c in ["street_count", "highway", "geometry"] if c in nodes.columns]
    out = nodes[keep].reset_index(drop=True)
    out["category"] = "road_intersection"
    out["group"] = "network"
    return out


def fetch_walk_edges(place: str, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    graph = ox.graph_from_place(place, network_type="walk", simplify=True)
    edges = ox.graph_to_gdfs(graph, nodes=False, edges=True)
    edges = edges.to_crs(METRIC_CRS)
    edges = _clip_to_boundary(edges, boundary)
    keep = [c for c in ["highway", "name", "length", "geometry"] if c in edges.columns]
    out = edges[keep].reset_index(drop=True)
    out["category"] = "walk_way"
    out["group"] = "network"
    return out


def collect_networks(place: str, boundary: gpd.GeoDataFrame) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    print("Downloading drive network (road intersections)...")
    intersections = fetch_road_intersections(place, boundary)
    inter_path = RAW_DIR / "cankaya_road_intersections.geojson"
    save_geojson(intersections, inter_path)
    paths["road_intersections"] = inter_path
    print(f"  intersections: {len(intersections)} -> {inter_path.name}")

    print("Downloading walk network (pedestrian ways)...")
    walk_edges = fetch_walk_edges(place, boundary)
    walk_edges = flatten_tag_columns(walk_edges)
    walk_path = RAW_DIR / "cankaya_walk_edges.parquet"
    walk_edges.to_parquet(walk_path, index=False)
    paths["walk_edges"] = walk_path
    print(f"  walk ways: {len(walk_edges)} -> {walk_path.name}")
    return paths


def run(
    place: str = PLACE_NAME,
    include_networks: bool = True,
    pois_only: bool = False,
    networks_only: bool = False,
) -> dict[str, Path]:
    _ensure_dirs()
    print(f"Downloading boundary: {place}")
    boundary = fetch_boundary(place)
    boundary_path = RAW_DIR / "cankaya_boundary.geojson"
    save_geojson(boundary, boundary_path)
    print(f"  polygons: {len(boundary)} -> {boundary_path.name}")
    paths: dict[str, Path] = {"boundary": boundary_path}

    if not networks_only:
        print("Downloading POIs (cafes, restaurants, demand, transit)...")
        pois = fetch_pois(place)
        pois_path = RAW_DIR / "cankaya_pois.geojson"
        save_geojson(pois, pois_path)
        print(f"  POIs: {len(pois)} -> {pois_path.name}")
        paths["pois"] = pois_path
        paths.update(save_layer_subsets(pois))

    if include_networks and not pois_only:
        paths.update(collect_networks(place, boundary))

    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect OSM backbone data for Cankaya.")
    parser.add_argument("--place", default=PLACE_NAME)
    parser.add_argument(
        "--pois-only",
        action="store_true",
        help="Skip road/walk graphs (faster).",
    )
    parser.add_argument(
        "--networks-only",
        action="store_true",
        help="Skip Overpass POIs; download drive/walk graphs only.",
    )
    args = parser.parse_args()
    run(
        place=args.place,
        include_networks=not args.pois_only,
        pois_only=args.pois_only,
        networks_only=args.networks_only,
    )


if __name__ == "__main__":
    main()
