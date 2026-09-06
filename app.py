"""OSM backbone map: target businesses, demand generators, transport."""

from pathlib import Path

import geopandas as gpd
import streamlit as st

from src.collect_osm_data import LAYER_FILES, RAW_DIR, run as collect_osm
from src.visualization import grid_deck, osm_deck

st.set_page_config(page_title="Retail Location Intelligence", layout="wide")
st.title("Retail Location Intelligence")
st.caption(
    "Çankaya, Ankara · OpenStreetMap omurgası: hedef işletmeler, talep üreticileri, ulaşım ağı"
)

BOUNDARY_PATH = RAW_DIR / "cankaya_boundary.geojson"
POIS_PATH = RAW_DIR / "cankaya_pois.geojson"
WALK_PATH = RAW_DIR / "cankaya_walk_edges.parquet"
GRID_PATH = RAW_DIR.parent / "processed" / "cankaya_grid_features.parquet"

CATEGORY_FILE = {
    "cafe": LAYER_FILES["cafes"],
    "restaurant": LAYER_FILES["restaurants"],
    "university": LAYER_FILES["universities"],
    "school": LAYER_FILES["schools"],
    "hospital": LAYER_FILES["hospitals"],
    "park": LAYER_FILES["parks"],
    "shop": LAYER_FILES["shops"],
    "bus_stop": LAYER_FILES["bus_stops"],
    "metro": LAYER_FILES["metro"],
    "road_intersection": "cankaya_road_intersections.geojson",
}


@st.cache_data(show_spinner=False)
def _read_file(path_str: str) -> gpd.GeoDataFrame:
    path = Path(path_str)
    if not path.exists():
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:32636")
    if path.suffix == ".parquet":
        return gpd.read_parquet(path)
    return gpd.read_file(path)


with st.sidebar:
    st.header("Kapsam")
    st.selectbox("İlçe", ["Çankaya"], disabled=True)
    st.selectbox("İşletme türü", ["Kafe (hedef)"], disabled=True)
    map_mode = st.radio("Harita", ["OSM noktaları", "300 m grid"], index=0)

    with st.expander("TÜİK dosyası"):
        st.markdown(
            """
Mahalle toplam nüfus yüklü: `data/raw/tuik/cankaya_mahalle_nufus.csv`

`pop_15_34` yok; hücre nüfusu mahalle toplamının alana göre dağıtımı.
            """
        )

    st.subheader("Hedef işletmeler")
    show_cafe = st.checkbox("Kafeler (amenity=cafe)", value=True)
    show_rest = st.checkbox("Restoran / fast food", value=True)

    st.subheader("Talep üreticileri")
    show_uni = st.checkbox("Üniversiteler", value=True)
    show_school = st.checkbox("Okullar", value=True)
    show_hosp = st.checkbox("Hastane / klinik", value=True)
    show_park = st.checkbox("Parklar", value=True)
    show_shop = st.checkbox("Alışveriş (shop=*)", value=False)

    st.subheader("Ulaşım ağları")
    show_bus = st.checkbox("Otobüs durakları", value=True)
    show_metro = st.checkbox("Metro girişleri / istasyonlar", value=True)
    show_inter = st.checkbox("Yol kesişimleri", value=False)
    show_walk = st.checkbox("Yaya yolları (örneklem)", value=False)

    if st.button("OSM verisini indir / yenile"):
        with st.spinner("Overpass + yol ağı indiriliyor..."):
            collect_osm()
            _read_file.clear()
        st.rerun()

    grid_metric = "cafes_500m"
    if map_mode == "300 m grid":
        grid_metric = st.selectbox(
            "Hücre rengi",
            [
                "cafes_500m",
                "restaurants_500m",
                "bus_stops_400m",
                "metro_distance",
                "universities_1000m",
                "schools_750m",
                "parks_500m",
                "shops_500m",
                "road_intersections",
                "population",
                "population_density",
                "poi_diversity",
            ],
        )

visible: set[str] = set()
if show_cafe:
    visible.add("cafe")
if show_rest:
    visible.add("restaurant")
if show_uni:
    visible.add("university")
if show_school:
    visible.add("school")
if show_hosp:
    visible.add("hospital")
if show_park:
    visible.add("park")
if show_shop:
    visible.add("shop")
if show_bus:
    visible.add("bus_stop")
if show_metro:
    visible.add("metro")
if show_inter:
    visible.add("road_intersection")

if not BOUNDARY_PATH.exists() or not POIS_PATH.exists():
    st.warning("Yerel OSM çıktısı yok. Kenar çubuğundan indirin veya `python -m src.collect_osm_data` çalıştırın.")
    st.stop()

boundary = _read_file(str(BOUNDARY_PATH))
layers = {key: _read_file(str(RAW_DIR / filename)) for key, filename in CATEGORY_FILE.items()}

m1, m2, m3, m4 = st.columns(4)
m1.metric("Kafeler", len(layers["cafe"]))
m2.metric("Restoran / FF", len(layers["restaurant"]))
m3.metric("Duraklar", len(layers["bus_stop"]))
m4.metric("Metro / istasyon", len(layers["metro"]))

m5, m6, m7, m8 = st.columns(4)
m5.metric("Üniversite", len(layers["university"]))
m6.metric("Okul", len(layers["school"]))
m7.metric("Park", len(layers["park"]))
m8.metric("Mağaza", len(layers["shop"]))

if map_mode == "300 m grid":
    if not GRID_PATH.exists():
        st.warning("Grid henüz yok. `python -m src.build_features` çalıştırın.")
        st.stop()
    grid = _read_file(str(GRID_PATH))
    source = (
        grid["population_source"].dropna().iloc[0]
        if "population_source" in grid.columns and grid["population_source"].notna().any()
        else "unknown"
    )
    st.caption(
        f"{len(grid)} hücre · nüfus kaynağı: `{source}` · "
        "15–34 yaş yoksa genç nüfus sütunu boş kalır."
    )
    st.pydeck_chart(grid_deck(grid, grid_metric), width="stretch")
    preview_cols = list(
        dict.fromkeys(
            c
            for c in [
                "cell_id",
                "mahalle_name",
                grid_metric,
                "cafes_500m",
                "bus_stops_400m",
                "metro_distance",
                "population",
            ]
            if c in grid.columns
        )
    )
    st.dataframe(
        grid.drop(columns="geometry", errors="ignore")[preview_cols].head(25),
        width="stretch",
        hide_index=True,
    )
else:
    walk_edges = _read_file(str(WALK_PATH)) if show_walk and WALK_PATH.exists() else None
    st.pydeck_chart(
        osm_deck(
            boundary,
            layers,
            visible=visible,
            walk_edges=walk_edges,
            show_walk=show_walk,
        ),
        width="stretch",
    )

with st.expander("Katman renkleri ve OSM etiketleri"):
    st.markdown(
        """
| Grup | OSM | Harita |
| --- | --- | --- |
| Hedef isletme | `amenity=cafe` | kirmizi |
| Hedef isletme | `amenity=restaurant`, `fast_food` | turuncu |
| Talep | `amenity=university`, `school`, `hospital` | mor / mavi / pembe |
| Talep | `leisure=park`, `shop=*` | yesil / sari |
| Ulasim | `highway=bus_stop` | camgobegi |
| Ulasim | `railway=subway_entrance` / `station` | koyu gri |
| Ag | drive graph kesisim (`street_count >= 3`) | acik gri |
| Ag | walk graph kenarlari | ince cizgi |
        """
    )

with st.expander("Sınırlılıklar"):
    st.markdown(
        """
- Veri OpenStreetMap'ten gelir; eksik veya güncel olmayan kayıtlar olabilir.
- Poligonlar (kampüs, park, hastane) centroid'e indirgenir.
- Yol kesişimleri ve yaya ağı yoğun katmanlardır; varsayılan kapalı / örneklemli.
- Nüfus: mahalle `pop_total` hücreye areal weighting ile dağıtılır. 15–34 yaş mahallede yok.
- Sakarya Mahallesi tabloda boş; o hücrelerde nüfus 0 kalabilir.
- Bu ekran henüz uygunluk puanı üretmez.
        """
    )
