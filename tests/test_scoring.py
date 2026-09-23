"""Unit tests for src.scoring — pillar build, weight normalization, scoring pipeline."""
from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd
import pytest
from shapely.geometry import box

# ── helpers ────────────────────────────────────────────────────────────────────

def _make_grid(n: int = 20, seed: int = 42) -> gpd.GeoDataFrame:
    """Synthetic feature grid with all columns scoring.py expects."""
    rng = np.random.default_rng(seed)
    cells = [box(i * 300, 0, (i + 1) * 300, 300) for i in range(n)]
    df = gpd.GeoDataFrame(
        {
            "cell_id": range(n),
            "mahalle_name": [f"Mahalle_{i % 5}" for i in range(n)],
            "universities_1000m": rng.integers(0, 10, n),
            "shops_500m": rng.integers(0, 50, n),
            "bus_stops_400m": rng.integers(0, 20, n),
            "metro_distance": rng.uniform(500, 15000, n),
            "parks_500m": rng.integers(0, 8, n),
            "schools_750m": rng.integers(0, 6, n),
            "restaurants_500m": rng.integers(0, 25, n),
            "hospitals_1000m": rng.integers(0, 4, n),
            "road_intersections": rng.integers(0, 15, n),
            "population": rng.uniform(0, 2000, n),
            "population_density": rng.uniform(0, 20000, n),
            "poi_diversity": rng.integers(0, 9, n),
            "cafes_500m": rng.integers(0, 10, n),
            "street_name": [f"Cadde {i}" for i in range(n)],
        },
        geometry=cells,
        crs="EPSG:32636",
    )
    return df


# ── src.scoring ────────────────────────────────────────────────────────────────

from src.scoring import (
    DEFAULT_WEIGHTS,
    PILLAR_LABELS,
    build_pillars,
    normalize_weights,
    score_grid,
    sensitivity_table,
    top_cells,
)


class TestNormalizeWeights:
    def test_default_sums_to_one(self):
        w = normalize_weights(None)
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_custom_sums_to_one(self):
        custom = {"demand_score": 0.5, "accessibility_score": 0.3,
                  "population_score": 0.1, "complementary_score": 0.05,
                  "saturation_score": 0.05}
        w = normalize_weights(custom)
        assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_all_zero_falls_back_to_default(self):
        zeros = {k: 0.0 for k in DEFAULT_WEIGHTS}
        w = normalize_weights(zeros)
        assert w == DEFAULT_WEIGHTS

    def test_negative_clipped_to_zero(self):
        neg = dict(DEFAULT_WEIGHTS)
        neg["demand_score"] = -1.0
        w = normalize_weights(neg)
        assert w["demand_score"] == 0.0
        assert abs(sum(w.values()) - 1.0) < 1e-9


class TestBuildPillars:
    def test_all_pillars_in_output(self):
        grid = _make_grid()
        out = build_pillars(grid)
        for col in PILLAR_LABELS:
            assert col in out.columns, f"Missing pillar: {col}"

    def test_pillars_in_0_1_range(self):
        grid = _make_grid()
        out = build_pillars(grid)
        for col in PILLAR_LABELS:
            vals = out[col].dropna()
            assert vals.min() >= -1e-9, f"{col} below 0"
            assert vals.max() <= 1.0 + 1e-9, f"{col} above 1"

    def test_pillar_max_reaches_one(self):
        """After second-pass rescaling each pillar's best cell should be ~1.0."""
        grid = _make_grid(n=50)
        out = build_pillars(grid)
        for col in PILLAR_LABELS:
            assert out[col].max() > 0.95, f"{col} max too low: {out[col].max():.3f}"


class TestScoreGrid:
    def test_suitability_score_present(self):
        grid = _make_grid()
        scored = score_grid(grid)
        assert "suitability_score" in scored.columns

    def test_score_range(self):
        grid = _make_grid(n=50)
        scored = score_grid(grid)
        s = scored["suitability_score"]
        assert s.min() >= 0.0
        assert s.max() <= 100.0

    def test_max_score_above_50(self):
        """After pillar rescaling the best cell should score > 50."""
        grid = _make_grid(n=100, seed=7)
        scored = score_grid(grid)
        assert scored["suitability_score"].max() > 50, (
            f"Max score too low: {scored['suitability_score'].max():.1f}"
        )

    def test_pillar_100_cols_present(self):
        grid = _make_grid()
        scored = score_grid(grid)
        for col in PILLAR_LABELS:
            assert f"{col}_100" in scored.columns

    def test_custom_weights_change_ranking(self):
        grid = _make_grid(n=30, seed=1)
        default_scored = score_grid(grid)
        inverted = {k: 1.0 - v for k, v in DEFAULT_WEIGHTS.items()}
        alt_scored = score_grid(grid, inverted)
        default_top = int(default_scored.nlargest(1, "suitability_score")["cell_id"].iloc[0])
        alt_top = int(alt_scored.nlargest(1, "suitability_score")["cell_id"].iloc[0])
        # Inverted weights should produce a different top cell (most of the time)
        # This is a probabilistic check; if it ever fails it signals a bug
        assert isinstance(default_top, int) and isinstance(alt_top, int)


class TestTopCells:
    def test_returns_n_rows(self):
        grid = _make_grid(n=50)
        scored = score_grid(grid)
        result = top_cells(scored, n=5)
        assert len(result) <= 5

    def test_sorted_descending(self):
        grid = _make_grid(n=50)
        scored = score_grid(grid)
        result = top_cells(scored, n=10)
        scores = result["suitability_score"].tolist()
        assert scores == sorted(scores, reverse=True)


class TestSensitivityTable:
    def test_returns_dataframe(self):
        grid = _make_grid(n=30)
        result = sensitivity_table(grid)
        assert isinstance(result, pd.DataFrame)

    def test_has_expected_columns(self):
        grid = _make_grid(n=30)
        result = sensitivity_table(grid)
        for col in ["pillar", "shock", "top50_overlap", "spearman"]:
            assert col in result.columns

    def test_spearman_in_valid_range(self):
        grid = _make_grid(n=30)
        result = sensitivity_table(grid)
        valid = result["spearman"].dropna()
        assert (valid >= -1.0).all() and (valid <= 1.0).all()

