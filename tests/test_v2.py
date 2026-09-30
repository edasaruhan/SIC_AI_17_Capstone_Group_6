from pathlib import Path
import numpy as np
import pandas as pd
from src.scoring import apply_weights, build_pillars
from tests.test_scoring import _make_grid


def test_exact_ceiling_floor_and_penalties():
    frame = pd.DataFrame({"demand_score": [1, 1, 1, 1, 0], "accessibility_score": [1, 1, 1, 1, 0], "population_score": [1, 1, 1, 1, 0], "saturation_score": [0, 0, 0, 1, 1], "competition_score": [0, 1/3, 2/3, 1, 1]})
    result = apply_weights(frame)
    assert result.suitability_score.tolist() == [100, 97.7, 95.3, 90, 0]
    assert np.allclose(result.competition_penalty[:4], [0, 7/3, 14/3, 7])


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


def test_constant_restaurant_pressure_and_absence():
    grid = _make_grid()
    grid['restaurants_500m'] = 5
    assert (build_pillars(grid).saturation_score == 1).all()
    grid['restaurants_500m'] = 0
    assert (build_pillars(grid).saturation_score == 0).all()
    grid['restaurants_500m'] = float('nan')
    assert build_pillars(grid).saturation_score.isna().all()


def test_home_and_analysis_open():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=60).run()
    assert not app.exception
    assert any('Temel Kullanım' in item.value for item in app.markdown)
    app.radio[0].set_value('Analiz').run()
    assert not app.exception
    assert any('geçici' in item.value for item in app.warning)
    mode = next(item for item in app.selectbox if item.label == 'Harita türü')
    mode.set_value('Doygunluk').run()
    assert not app.exception
    mode.set_value('Kafe rekabeti (25 kare)').run()
    assert not app.exception
    assert any('koordinat' in item.value for item in app.warning)
