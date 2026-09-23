"""Café location similarity model (Week 4 — comparison layer only).

This module answers ONE question:
    "Does this 300 m cell share the spatial characteristics of cells where
     cafés are already mapped?"

It does NOT predict profitability, revenue, or whether a new café will
succeed.  The output column is named ``cafe_similarity_score`` (0–1) to make
that clear.  It is intended as a secondary comparison layer in the Streamlit
app, shown alongside the MCDA suitability score.

Model choice: Random Forest (easy to explain feature importances).
Validation: mahalle-based spatial cross-validation (k = 5 folds built from
mahalle groups so adjacent cells don't leak between train and test sets).
"""

from __future__ import annotations

import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import LabelEncoder

from src.create_grid import PROCESSED_DIR

warnings.filterwarnings("ignore")

MODEL_FEATURE_COLS = [
    "universities_1000m",
    "shops_500m",
    "bus_stops_400m",
    "metro_distance",
    "parks_500m",
    "schools_750m",
    "restaurants_500m",
    "population",
    "population_density",
    "poi_diversity",
    "road_intersections",
    "hospitals_1000m",
]

# ── helpers ────────────────────────────────────────────────────────────────────

def _prepare(grid: gpd.GeoDataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Return feature matrix X, binary target y, and group labels for CV."""
    df = grid.copy()

    # Target: cell has at least one mapped café within 500 m
    y = (pd.to_numeric(df.get("cafes_500m", 0), errors="coerce").fillna(0) >= 1).astype(int)

    # Features: only numeric, no café counts (would be leakage)
    feat_cols = [c for c in MODEL_FEATURE_COLS if c in df.columns]
    X = df[feat_cols].copy()
    for col in feat_cols:
        X[col] = pd.to_numeric(X[col], errors="coerce")
    # Replace inf / NaN with column medians then 0
    X = X.replace([np.inf, -np.inf], np.nan)
    fill = X.median()
    X = X.fillna(fill).fillna(0)

    # Groups for spatial CV: mahalle name (cells in the same mahalle are kept together)
    if "mahalle_name" in df.columns:
        groups_raw = df["mahalle_name"].fillna("unknown").astype(str)
    else:
        # Fallback: coarse grid quadrant (4 groups)
        centroids = df.geometry.centroid
        qx = (centroids.x > centroids.x.median()).astype(int)
        qy = (centroids.y > centroids.y.median()).astype(int)
        groups_raw = (qx * 2 + qy).astype(str)

    le = LabelEncoder()
    groups = pd.Series(le.fit_transform(groups_raw), index=df.index)
    return X, y, groups


def train_and_score(
    grid: gpd.GeoDataFrame,
    n_estimators: int = 300,
    n_splits: int = 5,
    random_state: int = 42,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Train RF with spatial CV, attach ``cafe_similarity_score`` to grid.

    Returns
    -------
    grid_out : GeoDataFrame
        Original grid with ``cafe_similarity_score`` column added.
    cv_report : DataFrame
        Per-fold ROC-AUC and class counts (for console / app display).
    """
    X, y, groups = _prepare(grid)

    rf = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=8,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=random_state,
        n_jobs=-1,
    )

    # ── Spatial cross-validation ────────────────────────────────────────────
    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    oof_proba = np.zeros(len(X))   # out-of-fold probabilities
    fold_rows = []
    for fold, (train_idx, test_idx) in enumerate(sgkf.split(X, y, groups)):
        X_tr, X_te = X.iloc[train_idx], X.iloc[test_idx]
        y_tr, y_te = y.iloc[train_idx], y.iloc[test_idx]
        rf_fold = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=8,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=random_state,
            n_jobs=-1,
        )
        rf_fold.fit(X_tr, y_tr)
        proba = rf_fold.predict_proba(X_te)[:, 1]
        oof_proba[test_idx] = proba
        auc = roc_auc_score(y_te, proba) if y_te.nunique() > 1 else float("nan")
        fold_rows.append(
            {
                "fold": fold + 1,
                "train_cells": len(train_idx),
                "test_cells": len(test_idx),
                "positive_rate": float(y_te.mean().round(3)),
                "roc_auc": round(auc, 3),
            }
        )

    cv_report = pd.DataFrame(fold_rows)
    mean_auc = cv_report["roc_auc"].mean()
    print(f"  Spatial CV mean ROC-AUC: {mean_auc:.3f}  (5 mahalle-based folds)")

    # ── Final model on all data ─────────────────────────────────────────────
    rf.fit(X, y)
    final_proba = rf.predict_proba(X)[:, 1]

    # Blend OOF (honest) and full-model scores: 70% OOF, 30% full-model.
    # OOF scores are unbiased but noisier; full-model fills the signal.
    blended = 0.70 * oof_proba + 0.30 * final_proba

    grid_out = grid.copy()
    grid_out["cafe_similarity_score"] = (blended * 100).clip(0, 100).round(1)
    grid_out["cafe_similarity_raw"] = blended.round(4)

    # Feature importances (Gini) — attached as a module-level attribute for app access
    importances = pd.Series(rf.feature_importances_, index=X.columns).sort_values(ascending=False)
    train_and_score.feature_importances_ = importances   # type: ignore[attr-defined]

    return grid_out, cv_report


def load_and_attach(
    parquet_path: Path | None = None,
    save: bool = True,
) -> gpd.GeoDataFrame:
    """Load feature grid, compute similarity scores, save updated parquet."""
    if parquet_path is None:
        parquet_path = PROCESSED_DIR / "cankaya_grid_features.parquet"
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"{parquet_path} not found. Run python -m src.build_features first."
        )
    grid = gpd.read_parquet(parquet_path)
    grid_out, cv_report = train_and_score(grid)
    if save:
        grid_out.to_parquet(parquet_path, index=False)
        print(f"  Saved to {parquet_path.name}")
    return grid_out


def feature_importance_table(importances: pd.Series) -> pd.DataFrame:
    """Format feature importance Series into a display DataFrame."""
    LABEL_MAP = {
        "universities_1000m": "Üniversite (1 km)",
        "shops_500m": "Mağaza (500 m)",
        "bus_stops_400m": "Otobüs durağı (400 m)",
        "metro_distance": "Metro uzaklığı",
        "parks_500m": "Park (500 m)",
        "schools_750m": "Okul (750 m)",
        "restaurants_500m": "Restoran (500 m)",
        "population": "Nüfus",
        "population_density": "Nüfus yoğunluğu",
        "poi_diversity": "POI çeşitliliği",
        "road_intersections": "Yol kesişimi",
        "hospitals_1000m": "Hastane (1 km)",
    }
    df = importances.reset_index()
    df.columns = ["feature", "importance"]
    df["Özellik"] = df["feature"].map(LABEL_MAP).fillna(df["feature"])
    df["Önem %"] = (df["importance"] * 100).round(1)
    return df[["Özellik", "Önem %"]].reset_index(drop=True)


def main() -> None:
    print("Training café-location similarity model (spatial CV)…")
    grid = load_and_attach(save=True)

    sim = grid["cafe_similarity_score"]
    print(f"\ncafe_similarity_score — max={sim.max():.1f}  mean={sim.mean():.1f}  "
          f"p90={sim.quantile(0.9):.1f}")

    if hasattr(train_and_score, "feature_importances_"):
        print("\nFeature importances (Gini):")
        print(feature_importance_table(train_and_score.feature_importances_).to_string(index=False))


if __name__ == "__main__":
    main()

