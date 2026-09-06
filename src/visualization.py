"""PyDeck layers for the OSM backbone map."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pydeck as pdk

from src import WGS84_CRS

CANKAYA_VIEW = pdk.ViewState(latitude=39.90, longitude=32.86, zoom=11, pitch=0)

LAYER_STYLE = {
    "cafe": {"color": [220, 50, 47, 210], "radius": 45, "label": "Kafe"},
    "restaurant": {"color": [230, 126, 34, 200], "radius": 40, "label": "Restoran / fast food"},
    "university": {"color": [142, 68, 173, 220], "radius": 80, "label": "Üniversite"},
    "school": {"color": [41, 128, 185, 200], "radius": 50, "label": "Okul"},
    "hospital": {"color": [219, 112, 147, 210], "radius": 60, "label": "Hastane / klinik"},
    "park": {"color": [39, 174, 96, 200], "radius": 55, "label": "Park"},
    "shop": {"color": [241, 196, 15, 170], "radius": 28, "label": "Mağaza"},
    "bus_stop": {"color": [22, 160, 133, 200], "radius": 32, "label": "Otobüs durağı"},
    "metro": {"color": [44, 62, 80, 230], "radius": 70, "label": "Metro / istasyon"},
    "road_intersection": {"color": [127, 140, 141, 90], "radius": 18, "label": "Yol kesişimi"},
}


def _to_wgs(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84_CRS)
    return gdf.to_crs(WGS84_CRS)


def _geojson(gdf: gpd.GeoDataFrame) -> dict:
    return _to_wgs(gdf).__geo_interface__


def boundary_layer(boundary: gpd.GeoDataFrame) -> pdk.Layer:
    return pdk.Layer(
        "GeoJsonLayer",
        data=_geojson(boundary),
        stroked=True,
        filled=True,
        get_fill_color=[16, 80, 140, 35],
        get_line_color=[16, 80, 140, 220],
        get_line_width=40,
        line_width_min_pixels=2,
        pickable=False,
    )


def points_to_records(gdf: gpd.GeoDataFrame, category: str) -> list[dict]:
    if gdf is None or gdf.empty:
        return []
    style = LAYER_STYLE[category]
    points = _to_wgs(gdf.copy())
    points = points[points.geometry.geom_type == "Point"]
    if points.empty:
        return []
    labels = pd.Series(style["label"], index=points.index)
    if "name" in points.columns:
        names = points["name"].fillna("").astype(str).str.strip()
        labels = labels.where(names.eq(""), style["label"] + ": " + names)
    frame = pd.DataFrame(
        {
            "lon": points.geometry.x.to_numpy(),
            "lat": points.geometry.y.to_numpy(),
            "label": labels.to_numpy(),
            "category": category,
            "radius": style["radius"],
        }
    )
    records = frame.to_dict("records")
    color = style["color"]
    for row in records:
        row["color"] = color
    return records


def scatter_layer(records: list[dict], name: str) -> pdk.Layer:
    return pdk.Layer(
        "ScatterplotLayer",
        data=records,
        id=name,
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius="radius",
        radius_min_pixels=2,
        radius_max_pixels=14,
        pickable=True,
    )


def walk_path_layer(edges: gpd.GeoDataFrame, max_features: int = 4000) -> pdk.Layer | None:
    if edges is None or edges.empty:
        return None
    sample = edges
    if len(sample) > max_features:
        sample = sample.sample(n=max_features, random_state=42)
    sample = _to_wgs(sample)
    paths = []
    for geom in sample.geometry:
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "MultiLineString":
            lines = list(geom.geoms)
        else:
            lines = [geom]
        for line in lines:
            coords = [[float(x), float(y)] for x, y in line.coords]
            if len(coords) >= 2:
                paths.append({"path": coords})
    if not paths:
        return None
    return pdk.Layer(
        "PathLayer",
        data=paths,
        get_path="path",
        get_color=[52, 73, 94, 40],
        get_width=8,
        width_min_pixels=1,
        pickable=False,
    )


def osm_deck(
    boundary: gpd.GeoDataFrame,
    layers: dict[str, gpd.GeoDataFrame],
    visible: set[str],
    walk_edges: gpd.GeoDataFrame | None = None,
    show_walk: bool = False,
) -> pdk.Deck:
    deck_layers = [boundary_layer(boundary)]
    if show_walk:
        walk = walk_path_layer(walk_edges)
        if walk is not None:
            deck_layers.append(walk)

    records: list[dict] = []
    for category in LAYER_STYLE:
        if category not in visible:
            continue
        gdf = layers.get(category)
        records.extend(points_to_records(gdf, category))
    if records:
        deck_layers.append(scatter_layer(records, "osm-points"))

    return pdk.Deck(
        initial_view_state=CANKAYA_VIEW,
        layers=deck_layers,
        tooltip={"html": "<b>{label}</b>", "style": {"color": "white"}},
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    )


def _color_ramp(values: pd.Series) -> list[list[int]]:
    series = pd.to_numeric(values, errors="coerce").fillna(0)
    vmax = float(series.max()) if len(series) else 0
    if vmax <= 0:
        return [[16, 80, 140, 40] for _ in series]
    t = (series / vmax).clip(0, 1)
    colors = []
    for x in t:
        # yellow -> red
        r = int(255)
        g = int(220 * (1 - x) + 40 * x)
        b = int(40)
        a = int(70 + 110 * x)
        colors.append([r, g, b, a])
    return colors


def grid_deck(grid: gpd.GeoDataFrame, value_col: str) -> pdk.Deck:
    frame = grid.copy()
    if frame.crs is None:
        frame = frame.set_crs(WGS84_CRS)
    frame = frame.to_crs(WGS84_CRS)
    if value_col not in frame.columns:
        value_col = "cafes_500m"
    colors = _color_ramp(frame[value_col])
    frame["r"] = [c[0] for c in colors]
    frame["g"] = [c[1] for c in colors]
    frame["b"] = [c[2] for c in colors]
    frame["a"] = [c[3] for c in colors]
    if "mahalle_name" not in frame.columns:
        frame["mahalle_name"] = ""
    frame["tooltip"] = frame[value_col].map(lambda v: f"{value_col}: {v}")
    keep = [
        c
        for c in ["cell_id", "mahalle_name", "tooltip", "r", "g", "b", "a", "geometry"]
        if c in frame.columns
    ]
    layer = pdk.Layer(
        "GeoJsonLayer",
        data=frame[keep].__geo_interface__,
        get_fill_color="[r, g, b, a]",
        get_line_color=[30, 30, 30, 80],
        get_line_width=20,
        line_width_min_pixels=0.4,
        pickable=True,
        auto_highlight=True,
    )
    return pdk.Deck(
        initial_view_state=CANKAYA_VIEW,
        layers=[layer],
        tooltip={
            "html": "<b>{mahalle_name}</b><br/>Hücre {cell_id}<br/>{tooltip}",
            "style": {"color": "white"},
        },
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    )
