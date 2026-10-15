"""Synthetic matches -> feature engine -> training pipeline (artifacts under tmp_path)."""
import math

import numpy as np
import pytest

import src.model.train as T
from src.features.build_dataset import build_features
from src.features.columns import FEATURE_COLS
from src.model import baselines as baselines_mod
from tests.helpers_features import make_league_matches
from tests.helpers_model import mlflow_uri  # noqa: F401


def test_engine_features_train_and_register_elo_baseline(tmp_path, mlflow_uri):
    matches = make_league_matches(
        leagues=("PL", "PD", "SA"), seasons=tuple(range(2016, 2022)), n_teams=10,
        spread=0.7, with_cl=True, with_shots=True, seed=4,
    )
    feats = build_features(matches, burn_in_seasons=1)
    assert feats["season"].min() == 2017 and list(feats.columns[-len(FEATURE_COLS):]) == FEATURE_COLS

    art = tmp_path / "artifacts"
    reg = T.main(df=feats, artifacts_dir=str(art), n_trials=2, mlflow_tracking_uri=mlflow_uri)

    assert reg["selection"]["mode"] == "season"
    assert reg["feature_cols"] == FEATURE_COLS
    assert "elo" in reg["baselines"]
    elo = reg["baselines"]["elo"]
    assert elo["holdout_n_scored"] == elo["holdout_n_total"] == reg["n_holdout_rows"]
    # a correctly signed Elo (with home advantage) beats the uniform guess on latent-strength data
    assert elo["holdout_log_loss"] < math.log(3)
    assert elo["walk_forward_log_loss"] < math.log(3)
    assert (art / "best_model.pkl").exists() and (art / "model_registry.json").exists()


def test_elo_baseline_skipped_when_column_missing_or_all_nan():
    matches = make_league_matches(seasons=(2018, 2019, 2020), n_teams=6)
    feats = build_features(matches, burn_in_seasons=0)
    assert "elo" in baselines_mod.available_baselines(feats)
    assert "elo" not in baselines_mod.available_baselines(feats.drop(columns=["elo_diff"]))
    assert "elo" not in baselines_mod.available_baselines(feats.assign(elo_diff=np.nan))
    nan_eval = feats.assign(elo_diff=np.nan)
    p = baselines_mod.elo(feats, nan_eval)
    assert np.isnan(p).all()


def test_elo_baseline_probabilities_are_valid():
    matches = make_league_matches(seasons=(2018, 2019, 2020), n_teams=8, spread=0.7)
    feats = build_features(matches, burn_in_seasons=0)
    train, ev = feats[feats["season"] < 2020], feats[feats["season"] == 2020]
    p = baselines_mod.elo(train, ev)
    assert p.shape == (len(ev), 3)
    np.testing.assert_allclose(p.sum(axis=1), 1.0)
    # larger elo_diff -> higher home-win probability
    order = np.argsort(ev["elo_diff"].to_numpy())
    assert p[order[-1], 0] > p[order[0], 0]
