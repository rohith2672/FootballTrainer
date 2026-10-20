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


def test_available_baselines_ignore_odds_columns():
    no_odds = make_matches(seasons=(2020,), per_season=30)
    # make_matches carries every FEATURE_COLS column, so the elo baseline (needs elo_diff) is available
    assert B.available_baselines(no_odds) == ["uniform", "class_prior", "elo"]
    assert B.available_baselines(no_odds.drop(columns=["elo_diff"])) == ["uniform", "class_prior"]
    # odds columns in the data never create an odds-based baseline
    with_odds = make_matches(seasons=(2020,), per_season=30, with_odds=True)
    assert B.available_baselines(with_odds) == ["uniform", "class_prior", "elo"]
    assert set(B.BASELINES) == {"uniform", "class_prior", "elo"}


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
