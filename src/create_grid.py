"""Create a metric 300 m analysis grid over Çankaya (Week 2)."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import box

from src import CELL_SIZE_M, METRIC_CRS

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"


def load_boundary() -> gpd.GeoDataFrame:
    path = RAW_DIR / "cankaya_boundary.geojson"
    if not path.exists():
        raise FileNotFoundError("Run python -m src.collect_osm_data first.")
    return gpd.read_file(path).to_crs(METRIC_CRS)


def build_grid(
    boundary: gpd.GeoDataFrame | None = None,
    cell_size: int = CELL_SIZE_M,
) -> gpd.GeoDataFrame:
    if boundary is None:
        boundary = load_boundary()
    minx, miny, maxx, maxy = boundary.total_bounds
    cells = [
        box(x, y, x + cell_size, y + cell_size)
        for x in np.arange(minx, maxx, cell_size)
        for y in np.arange(miny, maxy, cell_size)
    ]
    grid = gpd.GeoDataFrame(
        {"cell_id": range(len(cells))},
        geometry=cells,
        crs=METRIC_CRS,
    )
    clipped = gpd.overlay(grid, boundary[["geometry"]], how="intersection")
    clipped = clipped.reset_index(drop=True)
    clipped["cell_id"] = range(len(clipped))
    return clipped


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    grid = build_grid()
    out = PROCESSED_DIR / "cankaya_grid_300m.geojson"
    grid.to_file(out, driver="GeoJSON")
    print(f"Wrote {len(grid)} cells -> {out}")


if __name__ == "__main__":
    main()
