from pathlib import Path
import numpy as np
import pandas as pd
from src.scoring import apply_weights, build_pillars
from tests.test_scoring import _make_grid


def test_exact_ceiling_floor_and_penalties():
    frame = pd.DataFrame({"demand_score": [1, 1, 1, 1, 0], "accessibility_score": [1, 1, 1, 1, 0], "population_score": [1, 1, 1, 1, 0], "similar_place_density_score": [0, 0, 0, 1, 1], "competition_score": [0, 1/3, 2/3, 1, 1]})
    result = apply_weights(frame)
    assert result.suitability_score.tolist() == [100, 98.3, 96.7, 95, 0]
    assert np.allclose(result.competition_penalty[:4], [0, 5/3, 10/3, 5])


def test_cafes_restaurants_do_not_raise_demand():
    grid = _make_grid()
    baseline = build_pillars(grid)
    grid['cafes_500m'] *= 100
    grid['restaurants_500m'] *= 100
    grid['poi_diversity'] *= 100
    assert np.allclose(baseline.demand_score, build_pillars(grid).demand_score)


def test_missing_competition_is_not_zero():
    result = apply_weights(build_pillars(_make_grid().drop(columns='competition_level')))
    assert result.competition_penalty.isna().all()
    assert result.score_provisional.all()


def test_popularity_has_no_effect():
    grid = _make_grid()
    a = apply_weights(build_pillars(grid))
    grid['popularity_score'] = 100
    b = apply_weights(build_pillars(grid), {'popularity_score': .6})
    assert a.suitability_score.equals(b.suitability_score)


def test_constant_cafe_density_and_absence():
    grid = _make_grid()
    grid['cafes_500m'] = 5
    assert (build_pillars(grid).similar_place_density_score == 1).all()
    grid['cafes_500m'] = 0
    assert (build_pillars(grid).similar_place_density_score == 0).all()
    grid['cafes_500m'] = float('nan')
    assert build_pillars(grid).similar_place_density_score.isna().all()


def test_home_and_analysis_open():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=60).run()
    assert not app.exception
    assert any('Temel Kullanım' in item.value for item in app.markdown)
    app.radio[0].set_value('Analiz').run()
    assert not app.exception
    assert any('geçici' in item.value for item in app.warning)
    mode = next(item for item in app.selectbox if item.label == 'Harita türü')
    mode.set_value('Benzer yer yoğunluğu').run()
    assert not app.exception
    mode.set_value('Kafe rekabeti (25 kare)').run()
    assert not app.exception
    assert any('koordinat' in item.value for item in app.warning)

    mode.set_value('OSM noktaları').run()
    assert not app.exception
    assert any('Yerel OSM' in item.value for item in app.warning)
    mode.set_value('Ham grid özelliği').run()
    assert not app.exception
    neighbourhood = next(item for item in app.multiselect if item.label == 'Mahalle')
    neighbourhood.set_value(neighbourhood.options[:2]).run()
    assert not app.exception
    minimum = next(item for item in app.slider if item.label == 'Minimum uygunluk')
    minimum.set_value(100).run()
    assert not app.exception
    assert any('Filtreye uyan hücre yok' in item.value for item in app.info)


def test_schools_require_explicit_secondary_levels():
    import geopandas as gpd
    from shapely.geometry import Point
    from src.build_features import eligible_secondary_schools
    schools = gpd.GeoDataFrame({"isced:level": ["2", "3", "1;2", "1", None, " "]},
                               geometry=[Point(i, 0) for i in range(6)], crs="EPSG:32636")
    eligible, unknown = eligible_secondary_schools(schools)
    assert eligible.index.tolist() == [0, 1, 2]
    assert unknown == 2
    eligible, unknown = eligible_secondary_schools(schools.drop(columns="isced:level"))
    assert eligible.empty
    assert unknown == 6


def test_unavailable_model_does_not_show_legacy_similarity(monkeypatch):
    import geopandas as gpd
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    original_read = gpd.read_parquet

    def single_class_read(*args, **kwargs):
        grid = original_read(*args, **kwargs)
        grid["cafes_500m"] = 0
        grid["cafe_similarity_score"] = 99.0
        return grid

    st.cache_data.clear()
    monkeypatch.setattr(gpd, "read_parquet", single_class_read)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=60).run()
    app.radio[0].set_value('Analiz').run()
    assert not app.exception
    assert any('Benzerlik modeli hesaplanamadı' in item.value for item in app.warning)
    assert not any(item.label == 'Benzerlik skoru' for item in app.metric)
    assert 'Kafe Benzerlik Skoru /100' not in app.dataframe[0].value.columns
    st.cache_data.clear()

