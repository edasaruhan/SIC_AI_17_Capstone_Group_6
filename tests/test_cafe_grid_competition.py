"""Checks that nested competition thresholds count each café only once per area."""

import pandas as pd

from src.cafe_grid_competition import cafe_grid_competition


class Point:
    geom_type = "Point"

    def __init__(self, x, y):
        self.x, self.y = x, y
        self.is_empty = False

    def within(self, cell):
        x0, y0, x1, y1 = cell.bounds
        return x0 < self.x < x1 and y0 < self.y < y1


class Cell:
    def __init__(self, x, y):
        self.bounds = (x * 300, y * 300, (x + 1) * 300, (y + 1) * 300)

    def representative_point(self):
        return Point(self.bounds[0] + 150, self.bounds[1] + 150)


def grid_5x5():
    return pd.DataFrame({
        "cell_id": range(25),
        "geometry": [Cell(x, y) for y in range(5) for x in range(5)],
    })


def cafes_at(points):
    return pd.DataFrame({"geometry": [Point(x * 300 + 100 + i, y * 300 + 100)
                                      for x, y, i in points]})


def test_three_thresholds_and_unique_nested_counts():
    cafe_positions = ([(2, 2, i) for i in range(2)]
                      + [(1, 2, i) for i in range(4)]
                      + [(0, 0, i) for i in range(7)])
    result = cafe_grid_competition(grid_5x5(), cafes_at(cafe_positions))
    center = result.loc[result.cell_id == 12].iloc[0]
    assert (center.cafes_cell, center.cafes_9_cells, center.cafes_25_cells) == (2, 6, 13)
    assert center.competition_level == 3
    assert (center.covered_cells_9, center.covered_cells_25) == (9, 25)


def test_below_thresholds_and_district_edge():
    positions = ([(2, 2, 0)] + [(1, 2, i) for i in range(4)]
                 + [(0, 0, i) for i in range(7)])
    result = cafe_grid_competition(grid_5x5(), cafes_at(positions))
    assert result.loc[result.cell_id == 12, "competition_level"].item() == 0
    corner = result.loc[result.cell_id == 0].iloc[0]
    assert (corner.covered_cells_9, corner.covered_cells_25) == (4, 9)
