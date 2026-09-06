"""Spatial feature engineering for 300 m grid cells."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from src import METRIC_CRS
from src.allocate_population import attach_population
from src.collect_neighbourhoods import run as collect_mahalle
from src.collect_osm_data import LAYER_FILES, RAW_DIR
from src.create_grid import PROCESSED_DIR, build_grid

COUNT_SPECS = [
    ("cafes_500m", LAYER_FILES["cafes"], 500),
    ("restaurants_500m", LAYER_FILES["restaurants"], 500),
    ("bus_stops_400m", LAYER_FILES["bus_stops"], 400),
    ("universities_1000m", LAYER_FILES["universities"], 1000),
    ("schools_750m", LAYER_FILES["schools"], 750),
    ("parks_500m", LAYER_FILES["parks"], 500),
    ("shops_500m", LAYER_FILES["shops"], 500),
    ("hospitals_1000m", LAYER_FILES["hospitals"], 1000),
]


def _load_points(filename: str) -> gpd.GeoDataFrame:
    path = RAW_DIR / filename
    if not path.exists():
        return gpd.GeoDataFrame(geometry=[], crs=METRIC_CRS)
    return gpd.read_file(path).to_crs(METRIC_CRS)


def count_in_radius(
    grid: gpd.GeoDataFrame,
    points: gpd.GeoDataFrame,
    radius_m: float,
    column: str,
) -> gpd.GeoDataFrame:
    out = grid.copy()
    if points.empty:
        out[column] = 0
        return out
    buffers = out[["cell_id"]].copy()
    buffers["geometry"] = out.geometry.centroid.buffer(radius_m)
    buffers = gpd.GeoDataFrame(buffers, geometry="geometry", crs=out.crs)
    joined = gpd.sjoin(
        points[["geometry"]],
        buffers,
        predicate="within",
        how="inner",
    )
    counts = joined.groupby("cell_id").size().rename(column)
    out = out.merge(counts, on="cell_id", how="left")
    out[column] = out[column].fillna(0).astype(int)
    return out


def nearest_distance(
    grid: gpd.GeoDataFrame,
    points: gpd.GeoDataFrame,
    column: str,
) -> gpd.GeoDataFrame:
    out = grid.copy()
    if points.empty:
        out[column] = pd.NA
        return out
    centroids = out[["cell_id"]].copy()
    centroids["geometry"] = out.geometry.centroid
    centroids = gpd.GeoDataFrame(centroids, geometry="geometry", crs=out.crs)
    joined = gpd.sjoin_nearest(
        centroids,
        points[["geometry"]],
        how="left",
        distance_col=column,
    )
    joined = joined.drop_duplicates("cell_id")
    return out.merge(joined[["cell_id", column]], on="cell_id", how="left")


def count_within_cell(
    grid: gpd.GeoDataFrame,
    points: gpd.GeoDataFrame,
    column: str,
) -> gpd.GeoDataFrame:
    out = grid.copy()
    if points.empty:
        out[column] = 0
        return out
    joined = gpd.sjoin(
        points[["geometry"]],
        out[["cell_id", "geometry"]],
        predicate="within",
        how="inner",
    )
    counts = joined.groupby("cell_id").size().rename(column)
    out = out.merge(counts, on="cell_id", how="left")
    out[column] = out[column].fillna(0).astype(int)
    return out


def poi_diversity(grid: gpd.GeoDataFrame) -> pd.Series:
    flags = [
        grid["cafes_500m"] > 0,
        grid["restaurants_500m"] > 0,
        grid["shops_500m"] > 0,
        grid["parks_500m"] > 0,
        grid["schools_750m"] > 0,
        grid["universities_1000m"] > 0,
        grid["hospitals_1000m"] > 0,
        grid["bus_stops_400m"] > 0,
        grid["metro_distance"].fillna(10_000) <= 1000,
    ]
    stacked = pd.concat(flags, axis=1)
    return stacked.sum(axis=1).astype(int)


def build_features(grid: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    if grid is None:
        grid = build_grid()
    grid = grid.to_crs(METRIC_CRS)
    grid["cell_area_m2"] = grid.geometry.area

    for column, filename, radius in COUNT_SPECS:
        print(f"counting {column}...")
        grid = count_in_radius(grid, _load_points(filename), radius, column)

    print("nearest metro...")
    grid = nearest_distance(grid, _load_points(LAYER_FILES["metro"]), "metro_distance")

    print("intersections in cell...")
    grid = count_within_cell(
        grid,
        _load_points("cankaya_road_intersections.geojson"),
        "road_intersections",
    )
    grid["poi_diversity"] = poi_diversity(grid)

    mahalle_path = RAW_DIR / "cankaya_mahalle.geojson"
    if not mahalle_path.exists():
        collect_mahalle()

    print("allocating population...")
    grid = attach_population(grid)
    return grid


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    grid = build_features()
    parquet_path = PROCESSED_DIR / "cankaya_grid_features.parquet"
    geojson_path = PROCESSED_DIR / "cankaya_grid_features.geojson"
    grid.to_parquet(parquet_path, index=False)
    # GeoJSON is handy for inspection; drop dense unused cols first.
    grid.to_file(geojson_path, driver="GeoJSON")
    print(f"cells: {len(grid)} -> {parquet_path.name}")
    summary = grid.drop(columns="geometry").select_dtypes(include="number")
    print(summary.describe().T[["mean", "min", "max"]].to_string())


if __name__ == "__main__":
    main()
