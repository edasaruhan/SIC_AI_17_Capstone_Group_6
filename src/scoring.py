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
    "demand_score": 0.45,
    "accessibility_score": 0.25,
    "population_score": 0.20,
    "saturation_score": 0.03,
    "competition_score": 0.07,
}
PILLAR_LABELS = {
    "demand_score": "Potansiyel talep (+)",
    "accessibility_score": "Ulaşım ve yaya erişimi (+)",
    "population_score": "Nüfus yoğunluğu (+)",
    "saturation_score": "Restoran / fast food doygunluğu (−)",
    "competition_score": "Aynı tür işletme rekabeti (−)",
}
POSITIVE_KEYS = ("demand_score", "accessibility_score", "population_score")
WEIGHT_RATIONALE = """
Ağırlıklar kullanıcı tarafından belirlenmiş senaryo tercihleridir; kârlılıktan öğrenilmedi.
Talep %45, erişim %25, nüfus %20; restoran/fast food cezası en fazla 3,
kafe rekabet cezası en fazla 7 puandır. Olumlu katkılar toplamlarına bölünerek
100 ölçeğine taşınır, cezalar daha sonra çıkarılır ve sonuç en az 0 olur.
Popülerlik–mekân uyumluluğu %10 olarak planlanmıştır; bağımsız veri yoktur,
hesaplamaya katılmaz. Eski literatür gerekçesi bu yeni ağırlıkları doğrulamaz.
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


DEMAND_FEATURES = {
    "universities_1000m": 0.30, "shops_500m": 0.25,
    "schools_750m": 0.15, "parks_500m": 0.10,
    "offices_500m": 0.10, "government_500m": 0.05,
    "kindergartens_500m": 0.05,
}


def demand_proxy(grid: pd.DataFrame) -> pd.Series:
    """Demand generators only; cafés/restaurants are excluded."""
    result = pd.Series(0.0, index=grid.index)
    for col, weight in DEMAND_FEATURES.items():
        if col in grid:
            result += weight * pd.to_numeric(grid[col], errors="coerce").fillna(0).clip(lower=0)
    return result


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
    out = grid.copy()
    demand_cols = [c for c in DEMAND_FEATURES if c in out and out[c].notna().any()]
    scaled = _minmax(out, demand_cols)
    total = sum(DEMAND_FEATURES[c] for c in demand_cols)
    out["demand_score"] = sum(
        (DEMAND_FEATURES[c] * scaled[c].fillna(0) for c in demand_cols),
        pd.Series(0.0, index=out.index),
    ) / total if total else 0.0
    out["demand_missing_features"] = ", ".join(c for c in DEMAND_FEATURES if c not in demand_cols)
    out["metro_proximity"] = _metro_proximity(out.get("metro_distance", pd.Series(index=out.index, dtype=float)))
    scaled = _minmax(out, ["bus_stops_400m", "metro_proximity", "road_intersections", "population_density", "population"])
    out["accessibility_score"] = (
        .45 * scaled["bus_stops_400m"] + .35 * scaled["metro_proximity"] + .20 * scaled["road_intersections"]
    )
    out["population_score"] = scaled["population_density" if "population_density" in scaled else "population"]
    out = _minmax(out, list(POSITIVE_KEYS))
    # Constant positive counts must not become zero pressure after MinMax.
    restaurants = pd.to_numeric(out.get("restaurants_500m", pd.Series(float("nan"), index=out.index)), errors="coerce").clip(lower=0)
    lo, hi = restaurants.min(), restaurants.max()
    out["saturation_score"] = ((restaurants - lo) / (hi - lo) if hi > lo else restaurants.where(restaurants.isna(), float(hi > 0)))
    level = pd.to_numeric(out.get("competition_level", pd.Series(float("nan"), index=out.index)), errors="coerce")
    out["competition_score"] = level.clip(0, 3) / 3.0
    out["popularity_score"] = float("nan")
    return out


def apply_weights(grid: gpd.GeoDataFrame, weights: dict[str, float] | None = None) -> gpd.GeoDataFrame:
    # Keep penalty magnitudes unchanged; only positive contributions are normalized.
    raw = dict(DEFAULT_WEIGHTS)
    if weights is not None:
        raw.update({k: max(float(v), 0.0) for k, v in weights.items() if k in DEFAULT_WEIGHTS})
    if not any(raw.values()):
        raw = dict(DEFAULT_WEIGHTS)
    out = grid.copy()
    positive_total = sum(raw[k] for k in POSITIVE_KEYS)
    positive = sum((raw[k] * out[k] for k in POSITIVE_KEYS), pd.Series(0.0, index=out.index))
    out["positive_contribution"] = 100 * positive / positive_total if positive_total else 0.0
    for key, name in (("saturation_score", "saturation_penalty"), ("competition_score", "competition_penalty")):
        out[name] = 100 * raw[key] * out[key]
    out["score_provisional"] = ((out["saturation_score"].isna() & (raw["saturation_score"] > 0)) | (out["competition_score"].isna() & (raw["competition_score"] > 0)))
    out["suitability_score"] = (
        out["positive_contribution"] - out["saturation_penalty"].fillna(0) - out["competition_penalty"].fillna(0)
    ).clip(0, 100).round(1)
    for col in PILLAR_LABELS:
        out[f"{col}_100"] = (100 * out[col]).clip(0, 100).round(1)
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
        "competition_score_100",
        "competition_penalty", "saturation_penalty", "score_provisional",
        "saturation_score_100",
        "cafe_similarity_score",
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
