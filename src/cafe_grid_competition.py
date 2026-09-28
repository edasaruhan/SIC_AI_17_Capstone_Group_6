"""Count distinct mapped cafés in nested 300 m grid neighbourhoods.

These counts describe local competition; they are not a profit forecast and do
not change the existing MCDA suitability score.
"""

from __future__ import annotations

from collections import Counter
from math import floor

import pandas as pd

from src import CELL_SIZE_M


def _lattice_key(x: float, y: float, origin_x: float, origin_y: float, size: int) -> tuple[int, int]:
    return floor((x - origin_x) / size), floor((y - origin_y) / size)


def cafe_grid_competition(grid, cafes, cell_size: int = CELL_SIZE_M) -> pd.DataFrame:
    """Return café counts for the cell, its 3×3 block and its 5×5 block.

    A café belongs to one lattice cell and is counted once in each surrounding
    block. Neighbourhoods outside the district are absent, and their coverage
    is reported so boundary cells can be interpreted with care.
    """
    if cell_size <= 0:
        raise ValueError("cell_size must be positive")
    if grid.empty or not grid["cell_id"].is_unique:
        raise ValueError("grid must contain unique cells")

    bounds = [geom.bounds for geom in grid.geometry]
    origin_x = min(box[0] for box in bounds)
    origin_y = min(box[1] for box in bounds)
    keys = [
        _lattice_key(point.x, point.y, origin_x, origin_y, cell_size)
        for point in (geom.representative_point() for geom in grid.geometry)
    ]
    if len(set(keys)) != len(keys):
        raise ValueError("multiple cells mapped to the same lattice position")

    cells_by_key = dict(zip(keys, grid.geometry))
    valid_keys = set(keys)
    cafe_counts = Counter()
    for geom in cafes.geometry:
        if geom is None or geom.is_empty:
            continue
        point = geom if geom.geom_type == "Point" else geom.representative_point()
        key = _lattice_key(point.x, point.y, origin_x, origin_y, cell_size)
        if key in valid_keys and point.within(cells_by_key[key]):
            cafe_counts[key] += 1

    rows = []
    for cell_id, (x, y) in zip(grid["cell_id"], keys):
        near = [(x + dx, y + dy) for dx in range(-1, 2) for dy in range(-1, 2)]
        wide = [(x + dx, y + dy) for dx in range(-2, 3) for dy in range(-2, 3)]
        center = cafe_counts[x, y]
        count_9 = sum(cafe_counts[key] for key in near)
        count_25 = sum(cafe_counts[key] for key in wide)
        # Three independent warnings; nested counts are never added together.
        level = int(center >= 2) + int(count_9 >= 6) + int(count_25 >= 13)
        rows.append({
            "cell_id": cell_id,
            "cafes_cell": center,
            "cafes_9_cells": count_9,
            "cafes_25_cells": count_25,
            "competition_level": level,
            "covered_cells_9": sum(key in valid_keys for key in near),
            "covered_cells_25": sum(key in valid_keys for key in wide),
        })
    return pd.DataFrame(rows)
