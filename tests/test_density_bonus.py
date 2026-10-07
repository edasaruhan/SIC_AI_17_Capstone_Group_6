import numpy as np
import pandas as pd
from src.scoring import apply_weights, build_pillars
from tests.test_scoring import _make_grid


def test_bonus_and_competition_are_mutually_exclusive():
    frame = pd.DataFrame({
        "demand_score": [.7] * 6, "accessibility_score": [.7] * 6,
        "population_score": [.7] * 6,
        "similar_place_density_score": [0, .5, 1, 1, 1, 1],
        "competition_score": [0, 0, 0, 1/3, 2/3, 1],
    })
    result = apply_weights(frame)
    assert result.suitability_score.tolist() == [70, 72.5, 75, 68.3, 66.7, 65]
    assert np.allclose(result.similar_place_density_bonus, [0, 2.5, 5, 0, 0, 0])


def test_unknown_competition_does_not_enable_bonus_even_if_penalty_disabled():
    grid = _make_grid().drop(columns="competition_level")
    out = apply_weights(build_pillars(grid), {"competition_score": 0})
    assert out.similar_place_density_bonus.isna().all()
    assert out.score_provisional.all()


def test_density_zero_stays_zero_and_restaurants_have_no_effect():
    grid = _make_grid()
    grid["cafes_500m"] = [0] + [10] * (len(grid) - 1)
    base = build_pillars(grid)
    grid["restaurants_500m"] *= 100
    assert base.similar_place_density_score.equals(build_pillars(grid).similar_place_density_score)
    assert base.similar_place_density_score.iloc[0] == 0


def test_missing_density_matters_only_where_bonus_is_eligible():
    grid = _make_grid()
    grid["cafes_500m"] = np.nan
    grid["competition_level"] = 1
    assert not apply_weights(build_pillars(grid)).score_provisional.any()
    grid["competition_level"] = 0
    assert apply_weights(build_pillars(grid)).score_provisional.all()
