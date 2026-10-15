import math

import numpy as np
import pandas as pd
import pytest

from src.model import baselines as B
from tests.helpers_model import make_matches


def _df(n=30, odds=True):
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"target": rng.integers(0, 3, n)})
    if odds:
        df["odds_home"] = 2.0
        df["odds_draw"] = 3.5
        df["odds_away"] = 4.0
    return df


def test_uniform_log_loss_is_ln3():
    df = _df(odds=False)
    scores, _ = B.evaluate_baseline("uniform", df, df)
    assert scores["log_loss"] == pytest.approx(math.log(3))
    assert scores["n_scored"] == len(df)


def test_class_prior_uses_train_frequencies():
    train = pd.DataFrame({"target": [0] * 6 + [1] * 2 + [2] * 2})
    p = B.class_prior(train, _df(5, odds=False))
    assert p.shape == (5, 3)
    np.testing.assert_allclose(p.sum(axis=1), 1.0)
    assert p[0, 0] > p[0, 1] >= p[0, 2]
    assert (p > 0).all()  # Laplace smoothing: a missing class never gives p=0


def test_class_prior_missing_class_is_finite():
    train = pd.DataFrame({"target": [0, 0, 1, 1]})
    scores, _ = B.evaluate_baseline("class_prior", train, pd.DataFrame({"target": [2, 0]}))
    assert math.isfinite(scores["log_loss"])


def test_proportional_overround_removal():
    odds = np.array([[2.0, 3.5, 4.0]])
    p = B.implied_proportional(odds)
    np.testing.assert_allclose(p.sum(), 1.0)
    inv = 1 / odds
    np.testing.assert_allclose(p, inv / inv.sum())


def test_shin_sums_to_one_and_differs_from_proportional():
    odds = np.array([[1.5, 4.0, 7.0], [2.0, 3.5, 4.0], [3.1, 3.2, 2.4]])
    p = B.implied_shin(odds)
    np.testing.assert_allclose(p.sum(axis=1), 1.0, atol=1e-9)
    assert (p > 0).all()
    prop = B.implied_proportional(odds)
    assert not np.allclose(p, prop)
    # Shin shifts mass away from longshots relative to proportional
    assert p[0, 2] < prop[0, 2]


def test_shin_no_overround_falls_back_to_proportional():
    odds = np.array([[2.0, 4.0, 4.0]])  # book sum exactly 1
    np.testing.assert_allclose(B.implied_shin(odds), B.implied_proportional(odds))


def test_bookmaker_skips_missing_odds_and_reports_coverage():
    df = _df(10)
    df.loc[[0, 3], "odds_draw"] = np.nan
    df.loc[5, "odds_home"] = 0.5  # invalid decimal odds
    scores, mask = B.evaluate_baseline("bookmaker", df, df)
    assert scores["n_total"] == 10
    assert scores["n_scored"] == 7
    assert mask.sum() == 7
    assert math.isfinite(scores["log_loss"])
    scores_shin, _ = B.evaluate_baseline("bookmaker_shin", df, df)
    assert scores_shin["n_scored"] == 7


def test_available_baselines_depends_on_odds_columns():
    no_odds = make_matches(seasons=(2020,), per_season=30)
    # make_matches carries every FEATURE_COLS column, so the elo baseline (needs elo_diff) is available
    assert B.available_baselines(no_odds) == ["uniform", "class_prior", "elo"]
    assert B.available_baselines(no_odds.drop(columns=["elo_diff"])) == ["uniform", "class_prior"]
    with_odds = make_matches(seasons=(2020,), per_season=30, with_odds=True)
    names = B.available_baselines(with_odds)
    assert "bookmaker" in names and "bookmaker_shin" in names
    all_null = with_odds.copy()
    all_null[["odds_home", "odds_draw", "odds_away"]] = np.nan
    assert "bookmaker" not in B.available_baselines(all_null)


def test_register_baseline_hook():
    try:
        @B.register_baseline("always_home")
        def always_home(train_df, eval_df):
            out = np.zeros((len(eval_df), 3))
            out[:, 0] = 1.0
            return out

        assert "always_home" in B.available_baselines(_df(odds=False))
        scores, _ = B.evaluate_baseline("always_home", _df(odds=False), _df(odds=False))
        assert scores["n_scored"] == 30
    finally:
        B.BASELINES.pop("always_home", None)
        B._REQUIRED_COLUMNS.pop("always_home", None)


def test_score_probs_skips_nan_rows():
    probs = np.array([[0.5, 0.3, 0.2], [np.nan] * 3, [0.2, 0.2, 0.6]])
    scores, mask = B.score_probs(np.array([0, 1, 2]), probs)
    assert mask.tolist() == [True, False, True]
    assert scores["n_scored"] == 2
