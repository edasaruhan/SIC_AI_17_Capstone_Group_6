"""Spatial feature engineering for 300 m grid cells."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from src import METRIC_CRS
from src.allocate_population import attach_population
from src.attach_streets import attach_street_names
from src.collect_neighbourhoods import run as collect_mahalle
from src.collect_osm_data import LAYER_FILES, RAW_DIR
from src.cafe_grid_competition import cafe_grid_competition
from src.create_grid import PROCESSED_DIR, build_grid

COUNT_SPECS = [
    ("offices_500m", LAYER_FILES["offices"], 500),
    ("government_500m", LAYER_FILES["government"], 500),
    ("kindergartens_500m", LAYER_FILES["kindergartens"], 500),
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


def poi_diversity(grid: gpd.GeoDataFrame, include_cafes: bool = True) -> pd.Series:
    """Count present POI types; model inputs must exclude the café target."""
    def values(column):
        return pd.to_numeric(grid.get(column, pd.Series(float("nan"), index=grid.index)), errors="coerce")

    columns = ["restaurants_500m", "shops_500m", "parks_500m", "schools_750m",
               "universities_1000m", "hospitals_1000m", "bus_stops_400m"]
    if include_cafes:
        columns.append("cafes_500m")
    flags = [values(column) > 0 for column in columns]
    flags.append(values("metro_distance").fillna(10_000) <= 1000)
    return pd.concat(flags, axis=1).sum(axis=1).astype(int)


def eligible_secondary_schools(points: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, int]:
    """Keep explicit ISCED 2/3 tags; a missing column means all levels are unknown."""
    levels = points.get("isced:level", pd.Series("", index=points.index)).fillna("").astype(str).str.strip()
    unknown = int(levels.eq("").sum())
    eligible = levels.str.contains(r"(?:^|;)\s*[23]\s*(?:;|$)", regex=True)
    return points.loc[eligible].copy(), unknown


def build_features(grid: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    if grid is None:
        grid = build_grid()
    grid = grid.to_crs(METRIC_CRS)
    grid["cell_area_m2"] = grid.geometry.area

    for column, filename, radius in COUNT_SPECS:
        print(f"counting {column}...")
        if not (RAW_DIR / filename).exists():
            grid[column] = float("nan")
        else:
            points = _load_points(filename)
            if column == "schools_750m":
                points, unknown = eligible_secondary_schools(points)
                grid["school_level_unknown_count"] = unknown
            grid = count_in_radius(grid, points, radius, column)

    cafe_path = RAW_DIR / LAYER_FILES["cafes"]
    if cafe_path.exists():
        print("counting cafés in nested grid neighbourhoods...")
        grid = grid.merge(cafe_grid_competition(grid, _load_points(LAYER_FILES["cafes"])), on="cell_id")

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
    print("nearest named street...")
    grid = attach_street_names(grid)
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
