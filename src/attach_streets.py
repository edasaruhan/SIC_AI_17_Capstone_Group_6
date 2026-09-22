"""Nearest named OSM way for each 300 m cell (label only, not a score input)."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from src import METRIC_CRS
from src.collect_osm_data import RAW_DIR
from src.create_grid import PROCESSED_DIR

WALK_PATH = RAW_DIR / "cankaya_walk_edges.parquet"
MAX_DISTANCE_M = 250


def _flatten_name(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (list, tuple)):
        parts = [str(x).strip() for x in value if str(x).strip()]
        return parts[0] if parts else ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", ""}:
        return ""
    if ";" in text:
        return text.split(";")[0].strip()
    return text


def attach_street_names(grid: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = grid.copy()
    if not WALK_PATH.exists():
        out["street_name"] = ""
        return out
    edges = gpd.read_parquet(WALK_PATH)
    if edges.empty or "name" not in edges.columns:
        out["street_name"] = ""
        return out
    edges = edges.to_crs(METRIC_CRS)
    edges["street_name"] = edges["name"].map(_flatten_name)
    named = edges.loc[edges["street_name"] != "", ["street_name", "geometry"]]
    if named.empty:
        out["street_name"] = ""
        return out
    centroids = out[["cell_id"]].copy()
    centroids["geometry"] = out.geometry.centroid
    centroids = gpd.GeoDataFrame(centroids, geometry="geometry", crs=out.crs).to_crs(METRIC_CRS)
    joined = gpd.sjoin_nearest(
        centroids,
        named,
        how="left",
        max_distance=MAX_DISTANCE_M,
        distance_col="street_dist_m",
    )
    joined = joined.drop_duplicates("cell_id")
    out = out.drop(columns=["street_name"], errors="ignore")
    return out.merge(joined[["cell_id", "street_name"]], on="cell_id", how="left")


def main() -> None:
    parquet = PROCESSED_DIR / "cankaya_grid_features.parquet"
    geojson = PROCESSED_DIR / "cankaya_grid_features.geojson"
    if parquet.exists():
        grid = gpd.read_parquet(parquet)
    elif geojson.exists():
        grid = gpd.read_file(geojson)
    else:
        raise FileNotFoundError("Run python -m src.build_features first.")
    grid = attach_street_names(grid)
    grid.to_parquet(parquet, index=False)
    named = int(grid["street_name"].fillna("").astype(str).str.len().gt(0).sum())
    print(f"street labels: {named}/{len(grid)} -> {parquet.name}")


if __name__ == "__main__":
    main()
