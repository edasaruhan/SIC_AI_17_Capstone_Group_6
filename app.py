"""Explainable café location decision support for Çankaya."""

from pathlib import Path

import geopandas as gpd
import pandas as pd
import streamlit as st

from src.attach_streets import attach_street_names
from src.collect_osm_data import LAYER_FILES, RAW_DIR, run as collect_osm
from src.scoring import (
    DEFAULT_WEIGHTS,
    PILLAR_LABELS,
    WEIGHT_RATIONALE,
    normalize_weights,
    score_grid,
    sensitivity_table,
    top_cells,
)
from src.visualization import grid_deck, osm_deck
from src.cafe_similarity import train_and_score, feature_importance_table

st.set_page_config(page_title="Retail Location Intelligence", layout="wide")

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


st.title("Retail Location Intelligence")
st.caption(
    "Çankaya kafe konum karar desteği · açıklanabilir 0–100 puan · kârlılık tahmini değil"
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
    "demand_score": "Üniversite, mağaza, park, okul ve POI çeşitliliği (talep vekili).",
    "accessibility_score": "Durak sayısı, metroya yakınlık, yol kesişimi.",
    "population_score": "Mahalle nüfusunun hücreye alan payıyla dağıtımı.",
    "complementary_score": "Yakın restoran ve mağazalar; kafeler burada sayılmaz.",
    "saturation_score": "Kafe / (talep + 1) oranının tersi. Sıfır kafe otomatik avantaj değil.",
}

ALL_MAHALLE = "Tüm Çankaya"
PILLAR_CHART_LABELS = {
    "accessibility_score_100": "Toplu ulaşıma yakınlık",
    "demand_score_100": "Potansiyel müşteri yoğunluğu",
    "population_score_100": "Nüfus yoğunluğu",
    "complementary_score_100": "Tamamlayıcı işletmeler",
    "saturation_score_100": "Rakip doygunluğu (ters)",
}


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
def _sensitivity(path_str: str, mtime: float) -> pd.DataFrame:
    return sensitivity_table(_read_file(path_str))


@st.cache_data(show_spinner="Kafe benzerlik modeli hesaplanıyor… (ilk açılışta ~30 sn)")
def _similarity_scores(path_str: str, mtime: float) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Train RF café-similarity model and return grid with scores and importance table."""
    grid = _read_file(path_str)
    grid_out, _cv = train_and_score(grid)
    imp_df = feature_importance_table(train_and_score.feature_importances_)
    return grid_out, imp_df



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

    st.caption(
        "⚠️ Ağırlıklar Huff/gravity model literatürüne dayalı önceden belirlenmiş bir öncellik (prior); "
        "kârlılık verisinden öğrenilmedi. Duyarlılık tablosunda ±10 puan şoku altında sıralama kararlılığı "
        "gösterilmiştir. Boş hücre otomatik olarak yüksek fırsat sayılmaz."
    )




with st.sidebar:
    st.header("Kapsam")
    st.selectbox("İlçe", ["Çankaya"], disabled=True)
    st.selectbox("İşletme türü", ["Kafe"], disabled=True)
    st.selectbox(
        "Analiz ızgarası",
        ["300 m hücre (sabit)"],
        disabled=True,
        help="POI yarıçapları özellikte sabit: durak 400 m, kafe/park/mağaza 500 m, okul 750 m, üniversite 1 km.",
    )

    map_mode = st.radio(
        "Harita",
        ["Uygunluk puanı", "OSM noktaları", "Ham grid özelliği"],
        index=0,
    )

    st.subheader("Puan ağırlıkları")
    st.caption("Varsayılan prior; kaydırınca 100’e oranlanır. Kârlılıktan öğrenilmedi.")
    if st.button("Varsayılan ağırlıklara dön"):
        for key, default in DEFAULT_WEIGHTS.items():
            st.session_state[f"w_{key}"] = float(default)
        st.rerun()
    raw_weights = {}
    for key, default in DEFAULT_WEIGHTS.items():
        raw_weights[key] = st.slider(
            PILLAR_LABELS[key],
            min_value=0.0,
            max_value=0.60,
            value=float(default),
            step=0.01,
            help=PILLAR_HELP[key],
            key=f"w_{key}",
        )
    weights = normalize_weights(raw_weights)
    mix_df = pd.DataFrame(
        {
            "Bileşen": [PILLAR_LABELS[k] for k in DEFAULT_WEIGHTS],
            "Pay %": [round(weights[k] * 100, 1) for k in DEFAULT_WEIGHTS],
        }
    )
    st.dataframe(mix_df, hide_index=True, width="stretch")

    min_score = st.slider("Minimum uygunluk", 0, 100, 0)

    with st.expander("📚 Bu ağırlıklar neden böyle? (Literatür gerekçesi)"):
        st.markdown(WEIGHT_RATIONALE)
        st.markdown("""
**Referans:** Huff (1964) gravity modeli ve perakende konum MCDA çalışmaları
(Baviera-Puig vd. 2016; Hernández vd. 2004) catchment aktivitesini
erişilebilirliğin önüne koyar. Bu yaklaşım aynı önceliği yansıtır.

| Bileşen | Ağırlık | Gerekçe |
|---|---:|---|
| Potansiyel talep | %30 | Huff/gravity: havuz aktivitesi ana sürücü |
| Erişilebilirlik | %25 | Kafe = kolaylık malı, bağlantı kritik |
| Nüfus | %20 | Mahalle bazlı veri kaba; baskın olmasın |
| Tamamlayıcı | %15 | Karışık kullanım agglomeration etkisi |
| Doygunluk | %10 | OSM eksik; düşük ağırlık güvenli |

*Duyarlılık tablosunda her ağırlığa ±10 puan şoku uygulanmış ve Spearman
sıralama korelasyonu ile ilk-50 örtüşmesi raporlanmıştır.*
""")

    with st.expander("🤖 Random Forest Benzerlik Modeli hakkında"):
        st.markdown("""
**Ne öğrenir?**
`cafes_500m ≥ 1` → bu hücre mevcut kafeli lokasyonlara benziyor mu?

**Ne öğrenmez?**
Kârlılık, ciro, başarı/başarısızlık — bu veriler projede **yoktur**.

**Doğrulama yöntemi:**
Mahalle bazlı spatial cross-validation (k=5). Komşu hücreler aynı
fold'a düşmez; yani sınır sızması (spatial leakage) önlenir.
ROC-AUC konsola yazdırılır. Beklenen aralık: 0.70 – 0.85.

**Çıktı:**
Her hücre için 0–100 arası `cafe_similarity_score`. MCDA uygunluk
puanıyla yan yana karşılaştırma katmanı olarak kullanın.
""")

    with st.expander("TÜİK dosyası"):
        st.markdown(
            """
Mahalle toplam nüfus: `data/raw/tuik/cankaya_mahalle_nufus.csv`

`pop_15_34` yok; hücre nüfusu mahalle toplamının alana göre dağıtımı.
            """
        )

    st.subheader("OSM katmanları")
    show_cafe = st.checkbox("Kafeler", value=True)
    show_rest = st.checkbox("Restoran / fast food", value=False)
    show_uni = st.checkbox("Üniversiteler", value=False)
    show_school = st.checkbox("Okullar", value=False)
    show_hosp = st.checkbox("Hastane / klinik", value=False)
    show_park = st.checkbox("Parklar", value=False)
    show_shop = st.checkbox("Alışveriş (shop=*)", value=False)
    show_bus = st.checkbox("Otobüs durakları", value=False)
    show_metro = st.checkbox("Metro / istasyon", value=False)
    show_inter = st.checkbox("Yol kesişimleri", value=False)
    show_walk = st.checkbox("Yaya yolları (örneklem)", value=False)

    if st.button("OSM verisini indir / yenile"):
        with st.spinner("Overpass + yol ağı indiriliyor..."):
            collect_osm()
            _read_file.clear()
            _with_streets.clear()
            _sensitivity.clear()
        st.rerun()

    grid_metric = "suitability_score"
    if map_mode == "Ham grid özelliği":
        grid_metric = st.selectbox(
            "Hücre rengi",
            [
                "cafe_similarity_score",
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

else:
    if grid_path is None:
        st.warning("Grid henüz yok. `python -m src.build_features` çalıştırın.")
        st.stop()

    features = _with_streets(str(grid_path), grid_path.stat().st_mtime)
    scored_all = score_grid(features, weights)

    # RF café-similarity scores (cached — only recomputed when parquet changes)
    sim_grid, imp_df = _similarity_scores(str(grid_path), grid_path.stat().st_mtime)
    if "cafe_similarity_score" in sim_grid.columns:
        sim_cols = sim_grid[["cell_id", "cafe_similarity_score"]].copy()
        scored_all = scored_all.merge(sim_cols, on="cell_id", how="left")


    score_ceiling = float(scored_all["suitability_score"].max())

    mahalle_names = sorted(
        scored_all["mahalle_name"].dropna().astype(str).unique().tolist()
    ) if "mahalle_name" in scored_all.columns else []

    with st.sidebar:
        st.subheader("Bölge")
        mahalle = st.selectbox("Mahalle", [ALL_MAHALLE, *mahalle_names])

    scored = scored_all.loc[scored_all["suitability_score"] >= min_score].copy()
    if mahalle != ALL_MAHALLE:
        scored = scored.loc[scored["mahalle_name"].astype(str) == mahalle].copy()

    if scored.empty:
        st.info("Filtreye uyan hücre yok. Mahalleyi veya minimum puanı değiştirin.")
        st.stop()

    ranked = top_cells(scored, 10)

    with st.sidebar:
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

    color_col = "suitability_score" if map_mode == "Uygunluk puanı" else grid_metric
    invert = color_col == "metro_distance"
    with st.spinner("Uygunluk haritası hazırlanıyor…"):
        st.pydeck_chart(
            grid_deck(scored, color_col, invert=invert, selected_cell_id=selected_id),
            width="stretch",
        )

    st.caption(
        f"{len(scored)} hücre gösteriliyor · tavan {score_ceiling:.0f}/100 "
        "(teorik 100, tüm bileşenler aynı anda en yüksek olsa). "
        "Sarı çerçeve seçilen hücre. PyDeck tıklaması Streamlit’e dönmez; mahalle/hücre kutusundan seçin. "
        "Kızılay / Bahçelievler karışık kullanımla öne çıkar; kafe haritası boş ama nüfusu yüksek mahalleler "
        "doygunlukta “açık” görünebilir."
    )

    left, right = st.columns((1.15, 1.0))
    with left:
        st.subheader("En uygun 10 hücre")
        st.caption("Satır seçince sağdaki açıklama ve harita vurgusu güncellenir.")
        display = ranked.rename(
            columns={
                "cell_id": "Hücre",
                "mahalle_name": "Mahalle",
                "street_name": "Cadde",
                "suitability_score": "Puan",
                "demand_score_100": "Talep",
                "accessibility_score_100": "Ulaşım",
                "population_score_100": "Nüfus",
                "complementary_score_100": "Tamamlayıcı",
                "saturation_score_100": "Fırsat",
                "cafe_similarity_score": "RF Benzerlik",
                "cafes_500m": "Kafe 500m",
                "bus_stops_400m": "Durak 400m",
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

    with st.expander("Ağırlık duyarlılığı (varsayılan prior, ±10 puan)"):
        st.caption(
            "Her bileşeni tek tek şişirip diğerlerini yeniden oranlıyoruz. "
            "Spearman, tüm hücre sıralamasının ne kadar durduğunu; top-50 örtüşmesi önerilen listenin ne kadar kaydığını gösterir."
        )
        sens = _sensitivity(str(grid_path), grid_path.stat().st_mtime)
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
Bu uygulama **veri temelli, açıklanabilir bir kafe konum karar destek sistemidir.**

- Hücrede kafe olması o işletmenin **basarili** oldugu anlamina gelmez.
- Random Forest modeli **"mevcut kafe lokasyonlarina benzerlik"** ogrenir — karlılık degil.
  Mahalle bazlı spatial cross-validation ile degerlendirmistir (spatial leakage onlenir).
- Ciro, gunluk musteri, kira, kapanma tarihi verisi yoktur.
- MCDA agırlıkları Huff/gravity literaturune dayalı bir **on kabul**dur; kaydırıp degistirebilirsiniz.
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
- İlk sürüm yalnızca Çankaya + kafe.
        """
    )
