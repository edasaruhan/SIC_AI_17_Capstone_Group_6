"""Download Çankaya mahalle polygons from OSM (admin_level=8)."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import osmnx as ox

from src import METRIC_CRS, PLACE_NAME, WGS84_CRS
from src.collect_osm_data import RAW_DIR, flatten_tag_columns, save_geojson

KEEP = ["name", "name:tr", "admin_level", "geometry"]


def fetch_mahalle_polygons(place: str = PLACE_NAME) -> gpd.GeoDataFrame:
    boundary_path = RAW_DIR / "cankaya_boundary.geojson"
    if not boundary_path.exists():
        raise FileNotFoundError("Run python -m src.collect_osm_data first.")
    boundary = gpd.read_file(boundary_path).to_crs(METRIC_CRS)
    district = boundary.union_all() if hasattr(boundary, "union_all") else boundary.unary_union

    raw = ox.features_from_place(
        place,
        tags={"boundary": "administrative", "admin_level": "8"},
    )
    if raw.crs is None:
        raw = raw.set_crs(WGS84_CRS)
    polys = raw[raw.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    polys = polys.to_crs(METRIC_CRS)
    centroids = polys.geometry.centroid
    polys = polys.loc[centroids.within(district)].copy()
    keep = [c for c in KEEP if c in polys.columns]
    out = polys[keep].reset_index(drop=True)
    if "name" not in out.columns:
        out["name"] = ""
    out["name"] = out["name"].fillna("").astype(str)
    out = out.loc[out["name"].str.contains(r"mahalle", case=False, na=False)].copy()
    district_area = float(district.area)
    out["area_m2"] = out.geometry.area
    out = out.loc[out["area_m2"] < 0.4 * district_area].copy()
    out = flatten_tag_columns(out)
    return out


def run(place: str = PLACE_NAME) -> Path:
    mahalle = fetch_mahalle_polygons(place)
    path = RAW_DIR / "cankaya_mahalle.geojson"
    save_geojson(mahalle, path)
    print(f"mahalle polygons: {len(mahalle)} -> {path}")
    return path


if __name__ == "__main__":
    run()
