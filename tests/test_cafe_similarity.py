"""Unit tests for src.cafe_similarity — RF model training and scoring."""
from __future__ import annotations

import numpy as np
import geopandas as gpd
import pytest
from shapely.geometry import box

from src.cafe_similarity import (
    _prepare,
    feature_importance_table,
    train_and_score,
)


def _make_grid(n: int = 60, seed: int = 0) -> gpd.GeoDataFrame:
    rng = np.random.default_rng(seed)
    cells = [box(i * 300, 0, (i + 1) * 300, 300) for i in range(n)]
    mahalle_ids = rng.integers(0, max(n // 10, 2), n)
    return gpd.GeoDataFrame(
        {
            "cell_id": range(n),
            "mahalle_name": [f"Mahalle_{m}" for m in mahalle_ids],
            "universities_1000m": rng.integers(0, 5, n),
            "shops_500m": rng.integers(0, 50, n),
            "bus_stops_400m": rng.integers(0, 15, n),
            "metro_distance": rng.uniform(500, 15000, n),
            "parks_500m": rng.integers(0, 8, n),
            "schools_750m": rng.integers(0, 6, n),
            "restaurants_500m": rng.integers(0, 20, n),
            "hospitals_1000m": rng.integers(0, 3, n),
            "road_intersections": rng.integers(0, 12, n),
            "population": rng.uniform(0, 2000, n),
            "population_density": rng.uniform(0, 20000, n),
            "poi_diversity": rng.integers(0, 9, n),
            "cafes_500m": rng.integers(0, 8, n),
        },
        geometry=cells,
        crs="EPSG:32636",
    )


class TestPrepare:
    def test_shapes_match(self):
        grid = _make_grid(n=40)
        X, y, groups = _prepare(grid)
        assert len(X) == len(y) == len(groups) == 40

    def test_target_binary(self):
        grid = _make_grid(n=40)
        _, y, _ = _prepare(grid)
        assert set(y.unique()).issubset({0, 1})

    def test_no_nans_in_X(self):
        grid = _make_grid(n=40)
        X, _, _ = _prepare(grid)
        assert not X.isnull().any().any()

    def test_no_cafe_leakage_in_X(self):
        """cafes_500m must NOT appear in feature matrix."""
        grid = _make_grid(n=40)
        X, _, _ = _prepare(grid)
        assert "cafes_500m" not in X.columns


class TestTrainAndScore:
    def test_similarity_score_column_added(self):
        grid = _make_grid(n=60)
        out, _ = train_and_score(grid, n_estimators=10, n_splits=3)
        assert "cafe_similarity_score" in out.columns

    def test_score_range(self):
        grid = _make_grid(n=60)
        out, _ = train_and_score(grid, n_estimators=10, n_splits=3)
        s = out["cafe_similarity_score"]
        assert s.min() >= 0.0
        assert s.max() <= 100.0

    def test_cv_report_shape(self):
        grid = _make_grid(n=60)
        _, cv = train_and_score(grid, n_estimators=10, n_splits=3)
        assert len(cv) == 3
        assert "roc_auc" in cv.columns

    def test_feature_importances_stored(self):
        grid = _make_grid(n=60)
        train_and_score(grid, n_estimators=10, n_splits=3)
        assert hasattr(train_and_score, "feature_importances_")

    def test_row_count_preserved(self):
        grid = _make_grid(n=60)
        out, _ = train_and_score(grid, n_estimators=10, n_splits=3)
        assert len(out) == 60


class TestFeatureImportanceTable:
    def test_returns_dataframe(self):
        import pandas as pd
        grid = _make_grid(n=60)
        train_and_score(grid, n_estimators=10, n_splits=3)
        imp = train_and_score.feature_importances_
        result = feature_importance_table(imp)
        assert isinstance(result, pd.DataFrame)
        assert "Özellik" in result.columns
        assert "Önem %" in result.columns

    def test_importances_sum_to_100(self):
        grid = _make_grid(n=60)
        train_and_score(grid, n_estimators=10, n_splits=3)
        imp = train_and_score.feature_importances_
        result = feature_importance_table(imp)
        assert abs(result["Önem %"].sum() - 100.0) < 1.0

