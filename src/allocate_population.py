"""Spread mahalle population onto 300 m cells by overlapping area."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from src import METRIC_CRS
from src.collect_osm_data import RAW_DIR
from src.tuik import (
    CANKAYA_POP_TOTAL,
    load_tuik_mahalle_table,
    normalize_mahalle_name,
)

MAHALLE_PATH = RAW_DIR / "cankaya_mahalle.geojson"


def load_mahalle() -> gpd.GeoDataFrame:
    if not MAHALLE_PATH.exists():
        raise FileNotFoundError("Run python -m src.collect_neighbourhoods first.")
    gdf = gpd.read_file(MAHALLE_PATH).to_crs(METRIC_CRS)
    gdf["mahalle_name"] = gdf["name"].fillna("").astype(str)
    gdf["mahalle_key"] = gdf["mahalle_name"].map(normalize_mahalle_name)
    gdf["mahalle_area_m2"] = gdf.geometry.area
    return gdf


def assign_mahalle(grid: gpd.GeoDataFrame, mahalle: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    pieces = gpd.overlay(
        grid[["cell_id", "geometry"]],
        mahalle[["mahalle_name", "mahalle_key", "mahalle_area_m2", "geometry"]],
        how="intersection",
        keep_geom_type=False,
    )
    pieces["overlap_m2"] = pieces.geometry.area
    pieces = pieces.loc[pieces["overlap_m2"] > 1].copy()
    idx = pieces.groupby("cell_id")["overlap_m2"].idxmax()
    primary = pieces.loc[idx, ["cell_id", "mahalle_name", "mahalle_key"]]
    return grid.merge(primary, on="cell_id", how="left")


def areal_weight_population(
    grid: gpd.GeoDataFrame,
    mahalle: gpd.GeoDataFrame,
    tuik: pd.DataFrame | None,
) -> gpd.GeoDataFrame:
    """Allocate mahalle counts in proportion to overlap area / mahalle area."""
    out = grid.copy()
    out["cell_area_m2"] = out.geometry.area

    if tuik is None:
        district_area = float(out["cell_area_m2"].sum())
        share = out["cell_area_m2"] / district_area
        out["population"] = share * CANKAYA_POP_TOTAL
        out["pop_15_34"] = pd.NA
        out["population_source"] = "district_uniform"
        out["population_density"] = out["population"] / (out["cell_area_m2"] / 1_000_000)
        return out

    joined = mahalle.merge(
        tuik.drop(columns=["mahalle_name"], errors="ignore"),
        on="mahalle_key",
        how="left",
    )
    matched = int(joined["pop_total"].notna().sum())
    missing = joined.loc[joined["pop_total"].isna(), "mahalle_name"]
    print(f"TUIK name matches: {matched}/{len(joined)} mahalle polygons")
    if len(missing):
        print("OSM mahalle without TUIK pop_total:", ", ".join(missing.astype(str)))

    has_age = bool(joined["pop_15_34"].notna().any())
    overlay_cols = ["mahalle_key", "mahalle_area_m2", "pop_total", "geometry"]
    if has_age:
        overlay_cols.insert(3, "pop_15_34")

    pieces = gpd.overlay(
        out[["cell_id", "geometry"]],
        joined[overlay_cols],
        how="intersection",
        keep_geom_type=False,
    )
    pieces["overlap_m2"] = pieces.geometry.area
    pieces["share"] = pieces["overlap_m2"] / pieces["mahalle_area_m2"].replace(0, pd.NA)
    pieces["pop_part"] = pieces["pop_total"] * pieces["share"]

    totals = pieces.groupby("cell_id", as_index=False).agg(population=("pop_part", "sum"))
    if has_age:
        pieces["young_part"] = pieces["pop_15_34"] * pieces["share"]
        young = pieces.groupby("cell_id", as_index=False).agg(pop_15_34=("young_part", "sum"))
        totals = totals.merge(young, on="cell_id", how="left")

    out = out.merge(totals, on="cell_id", how="left")
    out["population"] = out["population"].fillna(0)
    if has_age:
        out["population_source"] = "tuik_areal_weight"
    else:
        out["pop_15_34"] = pd.NA
        out["population_source"] = "tuik_areal_weight_total_only"
    out["population_density"] = out["population"] / (out["cell_area_m2"] / 1_000_000)
    return out


def attach_population(grid: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    mahalle = load_mahalle()
    grid = assign_mahalle(grid, mahalle)
    tuik = load_tuik_mahalle_table()
    return areal_weight_population(grid, mahalle, tuik)
