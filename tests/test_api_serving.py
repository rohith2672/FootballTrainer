"""Serving internals: engine parity, occlusion, labels."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from src.api import serving
from src.features.build_dataset import build_features
from src.features.columns import FEATURE_COLS
from src.features.engine import compute_features
from tests.helpers_api import TEAMS, make_history


class ConstModel:
    """predict_proba depends only on feature 0, so occlusion effects are known."""

    def predict_proba(self, X):
        X = np.nan_to_num(np.asarray(X, dtype=float))
        a = 1.0 / (1.0 + np.exp(-X[:, 0] / 100.0))
        return np.column_stack([a, (1 - a) / 2, (1 - a) / 2])


@pytest.mark.parametrize("target_id", [5, 12, 20, 30])
def test_serving_feature_row_equals_offline_dataset_row(target_id):
    hist = make_history()
    offline = build_features(hist.copy(), burn_in_seasons=0)
    expected = offline.loc[offline["match_id"] == target_id, FEATURE_COLS].to_numpy()
    assert expected.shape == (1, len(FEATURE_COLS))

    m = hist.loc[hist["id"] == target_id].iloc[0]
    fixture = {
        "fixture_id": None, "league": m["league"], "home_team": m["home_team"],
        "away_team": m["away_team"], "kickoff": m["kickoff"].to_pydatetime(),
    }
    served, _ = serving.compute_fixture_features(hist[hist["id"] != target_id], [fixture])
    np.testing.assert_array_equal(served.to_numpy(), expected)       # NaN positions must match too


def test_fixture_rows_do_not_change_history_features():
    hist = make_history()
    fixtures = [
        {"fixture_id": 1, "league": "PL", "home_team": TEAMS[0], "away_team": TEAMS[1],
         "kickoff": dt.datetime(2026, 10, 20, 15, 0)},
        {"fixture_id": 2, "league": "PL", "home_team": TEAMS[2], "away_team": TEAMS[3],
         "kickoff": dt.datetime(2026, 10, 20, 17, 30)},
    ]
    served, ref = serving.compute_fixture_features(hist, fixtures)
    base = compute_features(hist)
    combined = compute_features(pd.concat([hist, serving.build_fixture_frame(fixtures)], ignore_index=True))
    np.testing.assert_array_equal(combined.iloc[: len(hist)].to_numpy(), base.to_numpy())
    assert len(served) == 2 and ref.shape == (len(FEATURE_COLS),)


def test_reference_is_median_of_recent_rows(monkeypatch):
    hist = make_history()
    monkeypatch.setattr(serving, "REFERENCE_WINDOW", 10)
    fx = [{"fixture_id": 1, "league": "PL", "home_team": TEAMS[0], "away_team": TEAMS[1],
           "kickoff": dt.datetime(2026, 10, 20, 15, 0)}]
    _, ref = serving.compute_fixture_features(hist, fx)
    feats = compute_features(hist)
    order = np.argsort(hist["date"].to_numpy(), kind="stable")[-10:]
    expected = np.nanmedian(feats.iloc[order].to_numpy(), axis=0)
    np.testing.assert_array_equal(ref, expected)


def test_occlusion_contributions_and_single_predict_call():
    calls = []

    class Spy(ConstModel):
        def predict_proba(self, X):
            calls.append(len(X))
            return super().predict_proba(X)

    row = np.zeros(len(FEATURE_COLS))
    row[0] = 400.0                       # home_elo drives class 0
    ref = np.zeros(len(FEATURE_COLS))
    probs, factors = serving.explain_and_predict(Spy(), row, ref)
    assert calls == [len(FEATURE_COLS) + 1]
    assert abs(probs.sum() - 1.0) < 1e-12
    assert len(factors) == 1 and factors[0]["feature"] == "home_elo"
    assert factors[0]["value"] == 400.0
    assert factors[0]["contribution"] > 0                      # toward the predicted outcome
    assert factors[0]["contribution"] == pytest.approx(1 / (1 + np.exp(-4.0)) - 0.5, abs=1e-4)


def test_occlusion_nan_value_and_nan_reference_give_zero_contribution():
    row = np.full(len(FEATURE_COLS), np.nan)
    row[0] = 1.0
    ref = np.full(len(FEATURE_COLS), np.nan)
    _, factors = serving.explain_and_predict(ConstModel(), row, ref)
    assert all(f["feature"] == "home_elo" for f in factors)


def test_num_converts_non_finite_to_none():
    assert serving.num(float("nan")) is None
    assert serving.num(np.float64("inf")) is None
    assert serving.num(np.int64(3)) == 3.0 and isinstance(serving.num(np.int64(3)), float)
    assert serving.num(None) is None


def test_infer_league_prefers_domestic_over_cl():
    hist = make_history()
    cl = hist.iloc[[-1]].copy()
    cl["league"] = "CL"
    cl["date"] = cl["date"] + pd.Timedelta(days=30)
    hist = pd.concat([hist, cl], ignore_index=True)
    team = cl.iloc[0]["home_team"]
    assert serving.infer_league(hist, team) == "PL"
    assert serving.infer_league(hist, "Nobody FC") is None
