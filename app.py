"""Explainable café location decision support for Çankaya."""

from pathlib import Path
import shutil
import tempfile

import geopandas as gpd
import pandas as pd
import streamlit as st

import importlib
import src.visualization
import src.scoring
import src.cafe_similarity

importlib.reload(src.visualization)
importlib.reload(src.scoring)
importlib.reload(src.cafe_similarity)

from src.build_features import main as rebuild_features
from src.attach_streets import attach_street_names
from src.collect_osm_data import LAYER_FILES, RAW_DIR, run as collect_osm
from src.scoring import (
    DEFAULT_WEIGHTS,
    PILLAR_LABELS,
    WEIGHT_RATIONALE,
    score_grid,
    sensitivity_table,
    top_cells,
)
from src.visualization import grid_deck, osm_deck
from src.cafe_similarity import train_and_score, feature_importance_table
from src.cafe_grid_competition import cafe_grid_competition


st.set_page_config(page_title="Retail Location Intelligence - AI Destekli Pazar Planlama", layout="wide")

# ── Loading & Stale Styling: Ekran kararmasını engelle, dönen çember ekle ──
st.markdown(
    """
    <style>
    /* 1. Güncelleme anında ekranın kararmasını (stale opacity) tamamen engelle */
    [data-stale="true"],
    div[data-stale="true"],
    .stApp [data-stale="true"],
    div[data-testid="stAppViewBlockContainer"] [data-stale="true"],
    div[data-testid="stDeckGlJsonChart"][data-stale="true"],
    div[data-testid="stDeckGlJsonChart"] {
        opacity: 1 !important;
        transition: none !important;
        filter: none !important;
    }
    .stApp div[data-stale="true"] * {
        opacity: 1 !important;
    }
    div[data-testid="stAppViewBlockContainer"] {
        transition: none !important;
    }

    /* Tooltip coordinates are relative to the map container. */
    [data-testid="stDeckGlJsonChart"] { position: relative; }
    [data-testid="stDeckGlJsonChart"] .deckgl-tooltip,
    [data-testid="stDeckGlJsonChart"] .deck-tooltip {
        pointer-events: none !important;
        max-width: min(340px, 80vw);
    }

    /* 2. Sağ üstteki Streamlit yüklenme ibresini görünür tut */
    [data-testid="stStatusWidget"] {
        visibility: visible !important;
        display: inline-flex !important;
    }

    /* 3. Yükleme ibresi (Spinner) stili: Metin kesinlikle dönmez, şık ve sabit kalır */
    .stSpinner {
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        margin: 16px auto !important;
        padding: 10px 22px !important;
        background: rgba(30, 41, 59, 0.85) !important;
        border: 1px solid rgba(46, 204, 113, 0.5) !important;
        border-radius: 24px !important;
        width: fit-content !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3) !important;
    }
    .stSpinner span,
    .stSpinner p,
    .stSpinner div[data-testid="stMarkdownContainer"] {
        color: #2ecc71 !important;
        font-weight: 500 !important;
        font-size: 14px !important;
        margin: 0 !important;
    }
    .stSpinner svg,
    .stSpinner i {
        stroke: #2ecc71 !important;
        fill: #2ecc71 !important;
        color: #2ecc71 !important;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


st.caption(
    "Samsung Innovation Campus — AI in Marketing Capstone Projesi · Grup 6"
)


BOUNDARY_PATH = RAW_DIR / "cankaya_boundary.geojson"
POIS_PATH = RAW_DIR / "cankaya_pois.geojson"
WALK_PATH = RAW_DIR / "cankaya_walk_edges.parquet"
PROCESSED = RAW_DIR.parent / "processed"
GRID_CANDIDATES = [
    PROCESSED / "cankaya_grid_features.parquet",
    PROCESSED / "cankaya_grid_features.geojson",
]

CATEGORY_FILE = {
    "office": LAYER_FILES["offices"],
    "government": LAYER_FILES["government"],
    "kindergarten": LAYER_FILES["kindergartens"],
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

PILLAR_HELP = {
    "demand_score": "Üniversite, alışveriş, okul, park, ofis, devlet dairesi ve kreş. Kafe/restoran hariç.",
    "accessibility_score": "Durak sayısı, metroya yakınlık ve yol kesişimleri.",
    "population_score": "Mahalle nüfusunun hücreye alan payıyla dağıtımı.",
    "similar_place_density_score": "500 m içindeki kafe sayısı, tüm Çankaya maksimumuna oranlanır. Rekabet eşiği aşılmadığında en fazla +5 puan.",
    "competition_score": "Kafe eşikleri: merkez ≥2, 9 kare ≥6, 25 kare ≥13; her eşik cezanın üçte biri.",
}
ALL_MAHALLE = "Tüm Çankaya"
PILLAR_CHART_LABELS = {f"{k}_100": v for k, v in PILLAR_LABELS.items()}


@st.cache_data(show_spinner=False)
def _read_file(path_str: str) -> gpd.GeoDataFrame:
    path = Path(path_str)
    if not path.exists():
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:32636")
    if path.suffix == ".parquet":
        return gpd.read_parquet(path)
    return gpd.read_file(path)


@st.cache_data(show_spinner="Cadde adları ekleniyor…")
def _with_streets(path_str: str, mtime: float) -> gpd.GeoDataFrame:
    grid = _read_file(path_str)
    if "street_name" in grid.columns and grid["street_name"].notna().any():
        return grid
    return attach_street_names(grid)


@st.cache_data(show_spinner="Duyarlılık hesaplanıyor…")
def _sensitivity(grid: pd.DataFrame) -> pd.DataFrame:
    return sensitivity_table(grid)


@st.cache_data(show_spinner="Kafe benzerlik modeli hesaplanıyor… (ilk açılışta ~30 sn)")
def _similarity_scores(path_str: str, mtime: float) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Train RF café-similarity model and return grid with scores and importance table."""
    grid = _read_file(path_str)
    grid_out, _cv = train_and_score(grid)
    imp_df = feature_importance_table(train_and_score.feature_importances_)
    return grid_out, imp_df


@st.cache_data(show_spinner="Kafe rekabet katmanı hesaplanıyor…")
def _competition_counts(grid_path: str, grid_mtime: float, cafe_path: str, cafe_mtime: float) -> pd.DataFrame:
    grid = _read_file(grid_path)
    cafes = _read_file(cafe_path).to_crs(grid.crs)
    return cafe_grid_competition(grid, cafes)



def _feature_grid_path() -> Path | None:
    for path in GRID_CANDIDATES:
        if path.exists():
            return path
    return None


def _headline(cell: pd.Series) -> str:
    mahalle = str(cell.get("mahalle_name") or "Hücre").strip()
    street = str(cell.get("street_name") or "").strip()
    cell_id = int(cell["cell_id"])
    score = float(cell["suitability_score"])
    if street:
        return f"{mahalle}, {street} çevresi: {score:.0f}/100"
    return f"{mahalle} (hücre {cell_id}): {score:.0f}/100"


def _render_explanation(cell: pd.Series) -> None:
    st.markdown(f"**{_headline(cell)}**")

    # ── MCDA Pillar Bar Chart ──────────────────────────────────────────────
    pillars = pd.DataFrame(
        {
            "Bileşen": list(PILLAR_CHART_LABELS.values()),
            "Puan": [float(cell[k]) for k in PILLAR_CHART_LABELS],
        }
    )
    st.bar_chart(pillars.set_index("Bileşen"))
    st.caption("Rekabet eşiği aşılmadığında yoğunluk bonusu eklenir; aşıldığında bonus kapanır ve rekabet cezası uygulanır.")
    st.write(f"Olumlu katkı: {cell['positive_contribution']:.2f} puan")
    for label, key in (("Rekabet cezası", "competition_penalty"),):
        value = cell.get(key)
        st.write(f"{label}: −{value:.2f} puan" if pd.notna(value) else f"{label}: veri yok — puan geçici")
    bonus = cell.get("similar_place_density_bonus")
    st.write(f"Benzer yer yoğunluğu katkısı: +{bonus:.2f} puan" if pd.notna(bonus) else "Benzer yer yoğunluğu katkısı: veri yok — puan geçici")
    st.caption("Popülerlik–mekân uyumluluğu: veri yok; %10 planlanan ağırlık hesaplamaya kapalı.")

    # ── Ham metrikler ──────────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    c1.metric("Kafe (500 m)", int(cell.get("cafes_500m", 0)))
    c2.metric("Durak (400 m)", int(cell.get("bus_stops_400m", 0)))
    c3.metric("Park (500 m)", int(cell.get("parks_500m", 0)))
    d1, d2, d3 = st.columns(3)
    metro = cell.get("metro_distance")
    d1.metric("Metro mesafesi", f"{metro:.0f} m" if pd.notna(metro) else "—")
    d2.metric("Okul (750 m)", int(cell.get("schools_750m", 0)))
    d3.metric("Üniversite (1 km)", int(cell.get("universities_1000m", 0)))
    e1, e2, e3 = st.columns(3)
    e1.metric("Restoran (500 m)", int(cell.get("restaurants_500m", 0)))
    e2.metric("Mağaza (500 m)", int(cell.get("shops_500m", 0)))
    pop = cell.get("population")
    e3.metric("Hücre nüfus vekili", f"{pop:.0f}" if pd.notna(pop) else "—")

    if "competition_level" in cell.index:
        st.markdown("**Kafe rekabeti · 300 m kareler**")
        k1, k9, k25 = st.columns(3)
        k1.metric("Merkez", int(cell["cafes_cell"]))
        k9.metric("Toplam 9 kare", int(cell["cafes_9_cells"]))
        k25.metric("Toplam 25 kare", int(cell["cafes_25_cells"]))
        st.caption(
            f"{int(cell['competition_level'])}/3 rekabet eşiği aşıldı: merkez ≥2, "
            "9 kare ≥6, 25 kare ≥13. Bu eşikler başlangıç varsayımıdır."
        )
        if int(cell["covered_cells_25"]) < 25:
            st.caption(
                f"İlçe sınırı: geniş çevrede {int(cell['covered_cells_25'])}/25 kare kapsanıyor; "
                "sayılar ilçenin dışındaki kafeleri içermez."
            )
        if int(cell["cafes_25_cells"]) > 0:
            st.info("Mevcut kafe kümelenmesi var; talep ve rekabet sahada incelenmeli.")
        else:
            st.info("Yakın çevrede kayıtlı kafe yok; bu tek başına fırsat anlamına gelmez.")

    # ── RF Kafe Benzerlik Skoru ────────────────────────────────────────────
    sim = cell.get("cafe_similarity_score")
    if pd.notna(sim):
        st.divider()
        st.markdown("**🤖 Mevcut Kafe Lokasyonlarına Benzerlik — Random Forest (Karşılaştırma Katmanı)**")
        rf1, rf2 = st.columns([1, 2])
        rf1.metric(
            "Benzerlik skoru",
            f"{float(sim):.0f}/100",
            help="Bu hücrenin mevcut kafe bulunan yerlere özellik benzerliği. Kârlılık tahmini DEĞİLDİR.",
        )
        rf2.warning(
            "Bu skor **'bu hücre mevcut kafelerin bulunduğu yerlere benziyor mu?'** "
            "sorusuna yanıt verir — kâr, ciro veya başarı tahmini **değildir**. "
            "MCDA puanıyla birlikte ek bir karşılaştırma katmanı olarak kullanın."
        )



with st.sidebar:
    home = st.radio("Temel Kullanım", ["Ana ekran", "Analiz"], index=0)
    st.subheader("Verileri Güncelle")
    if st.button("OSM verilerini indir / yenile"):
        try:
            with st.spinner("Veriler indiriliyor ve analiz yeniden hesaplanıyor…"):
                # Restore last usable local dataset on download/build failure.
                with tempfile.TemporaryDirectory() as backup:
                    data_dir = RAW_DIR.parent
                    shutil.copytree(data_dir, Path(backup) / "data")
                    try:
                        collect_osm()
                        rebuild_features()
                    except Exception:
                        shutil.rmtree(data_dir)
                        shutil.copytree(Path(backup) / "data", data_dir)
                        raise
                st.cache_data.clear()
            st.success("Veriler ve analiz güncellendi.")
        except Exception as exc:
            st.cache_data.clear()
            st.error(f"Güncelleme tamamlanamadı: {exc}")
            st.stop()
    st.subheader("Kapsam")
    st.selectbox("İlçe", ["Çankaya"], disabled=True)
    st.selectbox("İşletme türü", ["Kafe"], disabled=True)
    st.caption("Restoran — yakında (pasif)")
    region_controls = st.container()
    with region_controls:
        st.subheader("Harita ve bölge")
        map_mode = st.selectbox("Harita türü", ["Uygunluk puanı", "Kafe rekabeti (25 kare)", "Benzer yer yoğunluğu", "OSM noktaları", "Ham grid özelliği"])
        # Use lightweight stored features; no RF training on the home page.
        control_path = _feature_grid_path()
        control_grid = _read_file(str(control_path)) if control_path else None
        names = sorted(control_grid["mahalle_name"].dropna().astype(str).unique()) if control_grid is not None and "mahalle_name" in control_grid else []
        mahalle = st.multiselect("Mahalle", names, placeholder="Tüm Çankaya")
        cell_controls = st.container()
        grid_metric = "suitability_score"
        if map_mode == "Ham grid özelliği":
            grid_metric = st.selectbox("Hücre rengi", ["cafes_500m", "restaurants_500m", "population", "bus_stops_400m", "metro_distance"])
    st.subheader("Puan Ağırlıkları")
    st.caption("Temel katkılar kendi toplamına oranlanır. Yoğunluk bonusu ve rekabet cezası ayrı uygulanır.")
    if st.button("Varsayılan ağırlıklara dön"):
        for key, default in DEFAULT_WEIGHTS.items():
            st.session_state[f"w_{key}"] = float(default)
        st.rerun()
    weights = {key: st.slider(PILLAR_LABELS[key], 0.0, 0.60, float(default), 0.01, help=PILLAR_HELP[key], key=f"w_{key}") for key, default in DEFAULT_WEIGHTS.items()}
    st.slider("Popülerlik–mekân uyumluluğu (veri yok)", 0.0, 0.60, 0.10, 0.01, disabled=True)
    st.subheader("Min uygunluk")
    min_score = st.slider("Minimum uygunluk", 0, 100, 0)
    st.subheader("OSM Katmanları")
    show_cafe = st.checkbox("Kafeler", True)
    show_rest = st.checkbox("Restoran / fast food", False)
    show_uni = st.checkbox("Üniversiteler", False)
    show_school = st.checkbox("Okullar", False)
    show_hosp = st.checkbox("Hastane / klinik", False)
    show_park = st.checkbox("Parklar", False)
    show_shop = st.checkbox("Alışveriş", False)
    show_office = st.checkbox("Ofisler", False)
    show_government = st.checkbox("Devlet daireleri", False)
    show_kindergarten = st.checkbox("Kreş / anaokulu", False)
    show_bus = st.checkbox("Otobüs durakları", False)
    show_metro = st.checkbox("Metro / istasyon", False)
    show_inter = st.checkbox("Yol kesişimleri", False)
    show_walk = st.checkbox("Yaya yolları (örneklem)", False)

if home == "Ana ekran":
    st.markdown((Path(__file__).parent / "docs" / "temel_kullanim.md").read_text(encoding="utf-8"))
    with st.expander("Bu ağırlıklar neden böyle? (Yöntem ve literatür)"):
        st.markdown(WEIGHT_RATIONALE)
        st.write("Huff/gravity yaklaşımı talep ve erişimi ele almak için kavramsal çerçevedir; bu sürümdeki sayısal ağırlıklar ve eşikler kullanıcı tercihleridir.")
    with st.expander("Random Forest Benzerlik Modeli hakkında"):
        st.write("Mevcut kafe lokasyonlarına özellik benzerliğini gösterir. Kâr veya başarı tahmini değildir. Mahalle gruplarıyla çapraz doğrulama yapılır; komşu mahalleler arasındaki mekânsal bağımlılık tamamen ortadan kalkmaz.")
    with st.expander("TÜİK dosyası"):
        st.write("Mahalle toplam nüfusu: data/raw/tuik/cankaya_mahalle_nufus.csv. Hücre nüfusu alansal dağıtımla hesaplanır; mahalle düzeyinde 15–34 yaş verisi kullanılmaz.")
    st.stop()


visible: set[str] = set()
for enabled, category in ((show_office, "office"), (show_government, "government"), (show_kindergarten, "kindergarten")):
    if enabled:
        visible.add(category)
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

has_osm = BOUNDARY_PATH.exists() and POIS_PATH.exists()
grid_path = _feature_grid_path()

if map_mode == "OSM noktaları" and not has_osm:
    st.warning("Yerel OSM çıktısı yok. Kenar çubuğundan indirin veya `python -m src.collect_osm_data` çalıştırın.")
    st.stop()

if has_osm:
    layers = {key: _read_file(str(RAW_DIR / filename)) for key, filename in CATEGORY_FILE.items()}
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Kafeler", len(layers["cafe"]))
    m2.metric("Restoran / FF", len(layers["restaurant"]))
    m3.metric("Duraklar", len(layers["bus_stop"]))
    m4.metric("Metro / istasyon", len(layers["metro"]))
else:
    layers = {}
    st.info("OSM nokta katmanları yok; uygunluk haritası işlenmiş grid ile açılır.")

if map_mode == "OSM noktaları":
    with st.spinner("OSM noktaları ve harita hazırlanıyor…"):
        boundary = _read_file(str(BOUNDARY_PATH))
        if mahalle and control_grid is not None:
            selected_region = control_grid[control_grid["mahalle_name"].astype(str).isin(mahalle)].to_crs(boundary.crs)
            region_geom = selected_region.geometry.union_all()
            boundary = gpd.GeoDataFrame(geometry=[region_geom], crs=boundary.crs)
            layers = {key: value[value.to_crs(boundary.crs).intersects(region_geom)].copy() if not value.empty else value for key, value in layers.items()}
        walk_edges = _read_file(str(WALK_PATH)) if show_walk and WALK_PATH.exists() else None
        if mahalle and walk_edges is not None and not walk_edges.empty:
            walk_edges = walk_edges[walk_edges.to_crs(boundary.crs).intersects(region_geom)].copy()
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

else:
    if grid_path is None:
        st.warning("Grid henüz yok. `python -m src.build_features` çalıştırın.")
        st.stop()

    features = _with_streets(str(grid_path), grid_path.stat().st_mtime)
    scored_all = features.copy()

    competition_cols = ["cafes_cell", "cafes_9_cells", "cafes_25_cells", "competition_level",
                        "covered_cells_9", "covered_cells_25"]
    if not set(competition_cols).issubset(scored_all.columns):
        cafe_path = RAW_DIR / LAYER_FILES["cafes"]
        if cafe_path.exists():
            counts = _competition_counts(str(grid_path), grid_path.stat().st_mtime,
                                         str(cafe_path), cafe_path.stat().st_mtime)
            scored_all = scored_all.drop(columns=competition_cols, errors="ignore").merge(counts, on="cell_id")
    competition_available = set(competition_cols).issubset(scored_all.columns)
    scored_all = score_grid(scored_all, weights)
    if scored_all["score_provisional"].any():
        st.warning("Rekabet veya benzer yer yoğunluğu verisi eksik: doğrulanamayan bonus/ceza uygulanmadı; uygunluk puanları geçicidir. Verileri Güncelle bölümünü kullanın.")
    missing = scored_all["demand_missing_features"].iloc[0]
    if missing:
        st.warning(f"Eksik talep katmanları: {missing}. Talep yalnızca mevcut göstergelerle hesaplanır; verileri güncelleyin.")
    if "school_level_unknown_count" not in scored_all:
        st.caption("Eski okul verisi kademeleri ayırt etmiyor; güncellemeden önce genel okul sayıları kullanılır.")
    elif scored_all["school_level_unknown_count"].max() > 0:
        st.caption("Kademesi bilinmeyen okullar ortaokul/lise talep sayımından çıkarıldı; okul katmanında görülebilir.")
    if map_mode == "Kafe rekabeti (25 kare)" and not competition_available:
        st.warning("Kafe koordinatları bu depoda yok. Kenar çubuğundaki ‘OSM verisini indir / yenile’ "
                   "düğmesiyle veriyi alıp yeniden açın; 500 m toplamlarından 25 kare sayısı türetilemez.")
        st.stop()
    if map_mode == "Ham grid özelliği" and grid_metric in competition_cols and not competition_available:
        st.warning("Bu sayılar için önce OSM kafe koordinatlarını indirin.")
        st.stop()

    # RF café-similarity scores (cached — only recomputed when parquet changes)
    try:
        sim_grid, imp_df = _similarity_scores(str(grid_path), grid_path.stat().st_mtime)
    except ValueError as exc:
        st.warning(f"Benzerlik modeli hesaplanamadı; uygunluk analizi devam ediyor: {exc}")
        sim_grid, imp_df = scored_all.drop(columns=["cafe_similarity_score", "cafe_similarity_raw"], errors="ignore"), pd.DataFrame()
        scored_all = sim_grid.copy()
    if "cafe_similarity_score" in sim_grid.columns:
        if "cafe_similarity_score" in scored_all.columns:
            scored_all = scored_all.drop(columns=["cafe_similarity_score"])
        sim_cols = sim_grid[["cell_id", "cafe_similarity_score"]].copy()
        scored_all = scored_all.merge(sim_cols, on="cell_id", how="left")



    score_ceiling = float(scored_all["suitability_score"].max())

    mahalle_names = sorted(
        scored_all["mahalle_name"].dropna().astype(str).unique().tolist()
    ) if "mahalle_name" in scored_all.columns else []

    scored = scored_all.loc[scored_all["suitability_score"] >= min_score].copy()
    if mahalle:
        scored = scored.loc[scored["mahalle_name"].astype(str).isin(mahalle)].copy()

    if scored.empty:
        st.info("Filtreye uyan hücre yok. Mahalleyi veya minimum puanı değiştirin.")
        st.stop()

    ranked = top_cells(scored, 10)

    with cell_controls:
        labels = []
        ids = []
        for _, row in scored.sort_values("suitability_score", ascending=False).head(200).iterrows():
            ids.append(int(row["cell_id"]))
            street = str(row.get("street_name") or "").strip()
            extra = f" · {street}" if street else ""
            labels.append(
                f"{int(row['cell_id'])} · {row.get('mahalle_name', '')}{extra} · {row['suitability_score']:.0f}"
            )
        current = st.session_state.get("selected_cell_id")
        if current is not None and current not in ids:
            ids.insert(0, int(current))
            labels.insert(0, f"{int(current)} · seçili hücre")
        lookup = dict(zip(labels, ids))
        default_idx = 0
        if current in ids:
            default_idx = ids.index(current)
        chosen = st.selectbox("Hücre seç (puana göre, ilk 200)", labels, index=min(default_idx, len(labels) - 1))
        st.session_state.selected_cell_id = lookup[chosen]
        typed = st.text_input("veya hücre numarası yazın", value="")
        if typed.strip().isdigit():
            typed_id = int(typed.strip())
            if typed_id in set(scored_all["cell_id"].astype(int)):
                st.session_state.selected_cell_id = typed_id

    selected_id = int(st.session_state.selected_cell_id)
    if selected_id not in set(scored["cell_id"].astype(int)):
        selected_id = int(ranked.iloc[0]["cell_id"])
        st.session_state.selected_cell_id = selected_id

    color_col = ("competition_level" if map_mode == "Kafe rekabeti (25 kare)" else
                 "similar_place_density_score_100" if map_mode == "Benzer yer yoğunluğu" else
                 "suitability_score" if map_mode == "Uygunluk puanı" else grid_metric)
    invert = color_col == "metro_distance"
    with st.spinner("Uygunluk haritası hazırlanıyor…"):
        st.pydeck_chart(
            grid_deck(scored, color_col, invert=invert, selected_cell_id=selected_id),
            width="stretch",
        )
    if map_mode == "Kafe rekabeti (25 kare)":
        st.caption("Renkler aşılan eşik sayısını gösterir: gri 0, sarı 1, turuncu 2, kırmızı 3. "
                   "Eşikler merkez ≥2, toplam 9 kare ≥6, toplam 25 kare ≥13. "
                   "Gri alan otomatik olarak iyi konum değildir; bu eşikler uygunluk puanına rekabet cezası olarak yansır.")

    st.caption(f"{len(scored)} hücre · gözlenen en yüksek puan {score_ceiling:.1f}/100 · teorik üst sınır 100. Sarı çerçeve seçilen hücredir.")
    if map_mode == "Uygunluk puanı":
        st.caption("Yeşil ölçek: 0 puan açık yeşil, 100 puan koyu yeşil. Her hücre kendi uygunluk puanına göre tonlanır; mahalle filtresi renk ölçeğini değiştirmez.")
    if map_mode == "Benzer yer yoğunluğu":
        st.caption("Kafe sayısı 500 metrede ölçülür ve tüm Çankaya maksimumuna oranlanır. Rekabet eşiği aşılmadığında en fazla +5 puan ekler. Mahalle filtresi ölçeği değiştirmez.")

    left, right = st.columns((1.15, 1.0))
    with left:
        st.subheader("En uygun 10 hücre")
        st.caption("Satır seçince sağdaki açıklama ve harita vurgusu güncellenir.")
        display = ranked.copy()
        # Sayısal değerleri temiz biçimlendirme
        for c in [
            "suitability_score",
            "cafe_similarity_score",
            "demand_score_100",
            "accessibility_score_100",
            "population_score_100",
            "competition_score_100",
            "similar_place_density_score_100",
        ]:
            if c in display.columns:
                display[c] = pd.to_numeric(display[c], errors="coerce").round(1)

        if "metro_distance" in display.columns:
            display["metro_distance"] = (
                pd.to_numeric(display["metro_distance"], errors="coerce").round(0).fillna(0).astype(int)
            )
        if "population" in display.columns:
            display["population"] = (
                pd.to_numeric(display["population"], errors="coerce").round(0).fillna(0).astype(int)
            )

        display = display.rename(
            columns={
                "cell_id": "Hücre No",
                "mahalle_name": "Mahalle",
                "street_name": "Cadde / Sokak",
                "suitability_score": "Uygunluk Puanı /100",
                "cafe_similarity_score": "Kafe Benzerlik Skoru /100",
                "demand_score_100": "Talep /100",
                "accessibility_score_100": "Ulaşım /100",
                "population_score_100": "Nüfus /100",
                "competition_score_100": "Rekabet /100",
                "competition_penalty": "Rekabet cezası",
                "similar_place_density_bonus": "Yoğunluk bonusu",
                "score_provisional": "Geçici puan",
                "similar_place_density_score_100": "Benzer yer yoğunluğu /100",
                "cafes_500m": "Kafe (500m)",
                "bus_stops_400m": "Durak (400m)",
                "metro_distance": "Metro Mesafesi (m)",
                "restaurants_500m": "Restoran (500m)",
                "shops_500m": "Mağaza (500m)",
                "universities_1000m": "Üniversite (1km)",
                "parks_500m": "Park (500m)",
                "population": "Hücre Nüfusu",
            }
        )

        event = st.dataframe(
            display,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="top10",
        )
        rows = event.selection.rows if event.selection else []
        if rows:
            new_id = int(ranked.iloc[rows[0]]["cell_id"])
            if new_id != st.session_state.get("selected_cell_id"):
                st.session_state.selected_cell_id = new_id
                st.rerun()
    with right:
        st.subheader("Neden bu bölge?")
        hit = scored_all.loc[scored_all["cell_id"] == selected_id]
        if hit.empty:
            st.info("Hücre bu filtrede yok.")
        else:
            _render_explanation(hit.iloc[0])

    with st.expander("Ağırlık duyarlılığı (varsayılan ağırlıklar, ±10 yüzde puan)"):
        st.caption(
            "Her ağırlığı tek tek değiştiriyoruz; olumlu katkıları kendi toplamına oranlıyoruz, cezaları ayrıca çıkarıyoruz. "
            "Spearman, tüm hücre sıralamasının ne kadar durduğunu; top-50 örtüşmesi önerilen listenin ne kadar kaydığını gösterir."
        )
        sens = _sensitivity(pd.DataFrame(scored_all.drop(columns="geometry")))
        show = sens.copy()
        show["pillar"] = show["pillar"].map(PILLAR_LABELS).fillna(show["pillar"])
        show = show.rename(
            columns={
                "pillar": "Bileşen",
                "shock": "Şok",
                "top50_overlap": "İlk 50 örtüşme",
                "spearman": "Spearman",
            }
        )
        st.dataframe(show, hide_index=True, width="stretch")

    with st.expander("🔍 Random Forest — Özellik Önemleri (Gini)"):
        st.caption(
            "RF modelinin hangi özelliklere daha çok ağırlık verdiğini gösterir. "
            "Yüksek önem = o özellik 'kafe olan yerleri' sınıflandırmada daha belirleyici."
        )
        if imp_df is not None and not imp_df.empty:
            st.bar_chart(imp_df.set_index("Özellik")["Önem %"])
            st.dataframe(imp_df, hide_index=True, width="stretch")
        else:
            st.info("Benzerlik modeli yüklenmedi — uygunluk puanı modunda açın.")


with st.expander("Bu çıktı neyi iddia etmez"):
    st.markdown(
        """
Bu uygulama **kafe girişimcilerinin hedef müşteri çevresine erişim ve rekabet koşullarını karşılaştırarak aday bölgeleri daha hızlı seçmesini amaçlayan AI destekli pazar planlama aracıdır.**

Nüfus, çevredeki kurumlar ve ulaşım dolaylı göstergelerdir; müşteri tercihi veya gerçek yaya sayısını ölçmez. Süre tasarrufu henüz kullanıcı pilotuyla doğrulanmamıştır.

- Hücrede kafe olması o işletmenin **basarili** oldugu anlamina gelmez.
- Random Forest modeli **"mevcut kafe lokasyonlarina benzerlik"** ogrenir — karlılık degil.
  Mahalle bazlı çapraz doğrulama kullanır; mahalle sınırlarında mekânsal bağımlılık kalabilir.
- Ciro, gunluk musteri, kira, kapanma tarihi verisi yoktur.
- MCDA ağırlıkları kullanıcı tarafından belirlenmiş senaryo tercihleridir; kaydırıp değiştirebilirsiniz.
        """
    )

with st.expander("Katman renkleri ve OSM etiketleri"):
    st.markdown(
        """
| Grup | OSM | Harita |
| --- | --- | --- |
| Hedef işletme | `amenity=cafe` | kırmızı |
| Hedef işletme | `amenity=restaurant`, `fast_food` | turuncu |
| Talep | `amenity=university`, `school`, `hospital` | mor / mavi / pembe |
| Talep | `leisure=park`, `shop=*` | yeşil / sarı |
| Ulaşım | `highway=bus_stop` | camgöbeği |
| Ulaşım | `railway=subway_entrance` / `station` | koyu gri |
        """
    )

with st.expander("Sınırlılıklar"):
    st.markdown(
        """
- Talep OSM ve mahalle nüfus vekilidir; yaya sayımı yoktur.
- 15–34 yaş mahallede yok.
- Sakarya Mahallesi tabloda boş kalabilir.
- OSM eksik olabilir. Poligonlar centroid’e indirgenir.
- Analiz yarıçapı canlı değiştirilmez; özellikleri yeniden üretmek gerekir.
- Şeffaf Ankara / ABB katmanı henüz yok; ulaşım OSM durak ve metroya dayanır.
- Bu sürüm yalnızca Çankaya + kafe; restoran analizi yakında.
- 25 karelik rekabet eşikleri kullanıcı varsayımıdır; satış veya kârlılık verisiyle kalibre edilmemiştir.
        """
    )
