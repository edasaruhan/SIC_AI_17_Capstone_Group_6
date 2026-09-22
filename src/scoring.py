"""Explainable multi-criteria café suitability (not a profit model).

Existing cafés are *not* treated as successful businesses. This module only
combines demand, access, population, complementary activity and relative
saturation into a 0–100 score a planner can inspect and re-weight.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

from src.create_grid import PROCESSED_DIR, ROOT

# Default mix is a documented prior for a convenience café, not a fitted model.
# See WEIGHT_RATIONALE and README. Sliders in the app re-normalise any mix.
DEFAULT_WEIGHTS = {
    "demand_score": 0.30,
    "accessibility_score": 0.25,
    "population_score": 0.20,
    "complementary_score": 0.15,
    "saturation_score": 0.10,
}

PILLAR_LABELS = {
    "demand_score": "Potential demand",
    "accessibility_score": "Transit / walk access",
    "population_score": "Population density",
    "complementary_score": "Complementary businesses",
    "saturation_score": "Opportunity vs saturation",
}

WEIGHT_RATIONALE = """
Weights are a stated prior for a sit-down / takeaway café, then stress-tested.

They are not estimated from revenue. There is no turnover, rent or closure
label in this project, so we do not fit weights to “success”.

Demand 30%. Gravity / Huff-style retail location work treats the size of the
catchment and activity generators as the main driver of potential visits.
Universities, shops, parks, schools and POI mix stand in for that catchment.

Accessibility 25%. Cafés are convenience goods: bus stops, metro distance and
street intersections condition who can actually arrive. Ranked just below
demand because a well-connected empty fringe still has little café activity.

Population 20%. Residential density is a demand floor. Mahalle totals are
spread by overlapping area onto 300 m cells, so this proxy is coarse; it
must not dominate the map.

Complementary 15%. Restaurants and shops mark mixed-use streets (positive
agglomeration). Same-category cafés are *not* counted here.

Saturation 10%. Competition matters, but a cell with zero cafés is not
automatically a gap — it may have no demand either. Relative saturation is
cafés / (demand proxy + 1), then inverted. The weight is small because OSM
café counts are incomplete and we cannot observe overcrowding in sales.

A one-at-a-time ±0.10 perturbation (re-normalised) is used as a small
sensitivity check: ranks should not collapse when the prior moves a little.
"""


def _minmax(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame.copy()
    cols = [c for c in columns if c in out.columns]
    if not cols:
        return out
    values = out[cols].apply(pd.to_numeric, errors="coerce")
    values = values.replace([np.inf, -np.inf], np.nan)
    fill = values.median(numeric_only=True)
    values = values.fillna(fill).fillna(0)
    scaler = MinMaxScaler()
    out[cols] = scaler.fit_transform(values)
    return out


def _metro_proximity(distance_m: pd.Series) -> pd.Series:
    """Closer metro → higher score. Missing distance → treated as far."""
    dist = pd.to_numeric(distance_m, errors="coerce")
    fallback = float(dist.quantile(0.95)) if dist.notna().any() else 5000.0
    dist = dist.fillna(max(fallback, 1.0))
    return 1.0 / (1.0 + dist)


def demand_proxy(grid: pd.DataFrame) -> pd.Series:
    """Count-like activity used in the saturation ratio (not yet 0–1)."""
    uni = pd.to_numeric(grid.get("universities_1000m", 0), errors="coerce").fillna(0)
    shops = pd.to_numeric(grid.get("shops_500m", 0), errors="coerce").fillna(0)
    parks = pd.to_numeric(grid.get("parks_500m", 0), errors="coerce").fillna(0)
    schools = pd.to_numeric(grid.get("schools_750m", 0), errors="coerce").fillna(0)
    rest = pd.to_numeric(grid.get("restaurants_500m", 0), errors="coerce").fillna(0)
    diversity = pd.to_numeric(grid.get("poi_diversity", 0), errors="coerce").fillna(0)
    return uni * 4.0 + shops + rest * 0.5 + parks + schools * 0.5 + diversity


def normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    mix = dict(DEFAULT_WEIGHTS if weights is None else weights)
    for key in DEFAULT_WEIGHTS:
        mix.setdefault(key, DEFAULT_WEIGHTS[key])
        mix[key] = max(float(mix[key]), 0.0)
    total = sum(mix[k] for k in DEFAULT_WEIGHTS)
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: mix[k] / total for k in DEFAULT_WEIGHTS}


def build_pillars(grid: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Create 0–1 pillar scores from engineered cell features."""
    out = grid.copy()
    out["metro_proximity"] = _metro_proximity(out.get("metro_distance", pd.Series(dtype=float)))
    out["demand_proxy"] = demand_proxy(out)
    cafes = pd.to_numeric(out.get("cafes_500m", 0), errors="coerce").fillna(0)
    out["saturation_ratio"] = cafes / (out["demand_proxy"] + 1.0)

    scaled = _minmax(
        out,
        [
            "universities_1000m",
            "shops_500m",
            "poi_diversity",
            "parks_500m",
            "schools_750m",
            "hospitals_1000m",
            "bus_stops_400m",
            "metro_proximity",
            "road_intersections",
            "population_density",
            "population",
            "restaurants_500m",
            "saturation_ratio",
        ],
    )

    out["demand_score"] = (
        0.30 * scaled["universities_1000m"]
        + 0.25 * scaled["shops_500m"]
        + 0.20 * scaled["poi_diversity"]
        + 0.15 * scaled["parks_500m"]
        + 0.10 * scaled["schools_750m"]
    )
    out["accessibility_score"] = (
        0.45 * scaled["bus_stops_400m"]
        + 0.35 * scaled["metro_proximity"]
        + 0.20 * scaled["road_intersections"]
    )
    pop_col = "population_density" if "population_density" in scaled.columns else "population"
    out["population_score"] = scaled[pop_col]
    out["complementary_score"] = 0.60 * scaled["restaurants_500m"] + 0.40 * scaled["shops_500m"]
    # High café-per-demand → low opportunity. Empty cells with no demand stay mid/low.
    out["saturation_score"] = 1.0 - scaled["saturation_ratio"]
    return out


def apply_weights(grid: gpd.GeoDataFrame, weights: dict[str, float] | None = None) -> gpd.GeoDataFrame:
    mix = normalize_weights(weights)
    out = grid.copy()
    out["suitability_score"] = 100.0 * (
        mix["demand_score"] * out["demand_score"]
        + mix["accessibility_score"] * out["accessibility_score"]
        + mix["population_score"] * out["population_score"]
        + mix["complementary_score"] * out["complementary_score"]
        + mix["saturation_score"] * out["saturation_score"]
    )
    out["suitability_score"] = out["suitability_score"].clip(0, 100).round(1)
    for col in PILLAR_LABELS:
        out[f"{col}_100"] = (100.0 * out[col]).clip(0, 100).round(1)
    return out


def score_grid(
    grid: gpd.GeoDataFrame,
    weights: dict[str, float] | None = None,
) -> gpd.GeoDataFrame:
    return apply_weights(build_pillars(grid), weights)


def top_cells(grid: gpd.GeoDataFrame, n: int = 10) -> pd.DataFrame:
    cols = [
        "cell_id",
        "mahalle_name",
        "street_name",
        "suitability_score",
        "demand_score_100",
        "accessibility_score_100",
        "population_score_100",
        "complementary_score_100",
        "saturation_score_100",
        "cafes_500m",
        "bus_stops_400m",
        "metro_distance",
        "restaurants_500m",
        "shops_500m",
        "universities_1000m",
        "parks_500m",
        "population",
    ]
    keep = [c for c in cols if c in grid.columns]
    ranked = grid.drop(columns="geometry", errors="ignore")
    return ranked[keep].sort_values("suitability_score", ascending=False).head(n)


def sensitivity_table(grid: gpd.GeoDataFrame, delta: float = 0.10, top_n: int = 50) -> pd.DataFrame:
    """One-at-a-time weight shock; share of default top-N cells that remain."""
    base = score_grid(grid, DEFAULT_WEIGHTS)
    base_top = set(top_cells(base, n=top_n)["cell_id"])
    rows = []
    for key in DEFAULT_WEIGHTS:
        for sign, label in ((1.0, f"+{delta:.0%}"), (-1.0, f"-{delta:.0%}")):
            shocked = dict(DEFAULT_WEIGHTS)
            shocked[key] = max(DEFAULT_WEIGHTS[key] + sign * delta, 0.0)
            alt = score_grid(grid, shocked)
            alt_top = set(top_cells(alt, n=top_n)["cell_id"])
            overlap = len(base_top & alt_top) / top_n if top_n else 0.0
            merged = base[["cell_id", "suitability_score"]].merge(
                alt[["cell_id", "suitability_score"]],
                on="cell_id",
                suffixes=("_base", "_alt"),
            )
            rank_corr = (
                merged["suitability_score_base"]
                .rank()
                .corr(merged["suitability_score_alt"].rank(), method="spearman")
            )
            rows.append(
                {
                    "pillar": key,
                    "shock": label,
                    "top50_overlap": round(overlap, 3),
                    "spearman": round(float(rank_corr), 3) if pd.notna(rank_corr) else None,
                }
            )
    return pd.DataFrame(rows)


def load_feature_grid() -> gpd.GeoDataFrame:
    parquet = PROCESSED_DIR / "cankaya_grid_features.parquet"
    geojson = PROCESSED_DIR / "cankaya_grid_features.geojson"
    if parquet.exists():
        return gpd.read_parquet(parquet)
    if geojson.exists():
        return gpd.read_file(geojson)
    raise FileNotFoundError("Run python -m src.build_features first.")


def save_preview_map(grid: gpd.GeoDataFrame) -> None:
    import matplotlib.pyplot as plt

    image_dir = ROOT / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 9))
    grid.plot(
        column="suitability_score",
        cmap="YlGn",
        linewidth=0.05,
        edgecolor="#dddddd",
        legend=True,
        ax=ax,
        vmin=0,
        vmax=100,
    )
    ax.set_axis_off()
    ax.set_title("Çankaya café suitability (0–100, MCDA — not profit)")
    fig.savefig(image_dir / "suitability-map.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    grid = score_grid(load_feature_grid())
    parquet_path = PROCESSED_DIR / "cankaya_grid_scored.parquet"
    geojson_path = PROCESSED_DIR / "cankaya_grid_scored.geojson"
    grid.to_parquet(parquet_path, index=False)
    grid.to_file(geojson_path, driver="GeoJSON")
    save_preview_map(grid)
    print(f"cells: {len(grid)} -> {parquet_path.name}")
    print(grid["suitability_score"].describe().to_string())
    print("\nTop 10")
    print(top_cells(grid, 10).to_string(index=False))
    print("\nSensitivity (weight ±0.10, ranks vs default)")
    print(sensitivity_table(grid).to_string(index=False))


if __name__ == "__main__":
    main()
