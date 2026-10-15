import math
import os
import pickle
import numpy as np
import pandas as pd
import pytest
import xgboost as xgb

import src.model.train as train_module
from tests.helpers_model import mlflow_uri  # noqa: F401
from src.model.train import (
    FEATURE_COLS,
    load_data,
    split_by_date,
    save_model,
    train_xgboost,
)


def _make_synthetic_df(n: int = 160, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {col: rng.random(n) for col in FEATURE_COLS},
    )
    df["date"] = dates
    df["target"] = rng.integers(0, 3, size=n)
    return df


@pytest.fixture()
def synthetic_csv(tmp_path):
    df = _make_synthetic_df()
    path = tmp_path / "features.csv"
    df.to_csv(path, index=False)
    return str(path)


@pytest.fixture()
def train_test(synthetic_csv):
    df = load_data(synthetic_csv)
    return split_by_date(df)


def test_train_xgboost_returns_xgbclassifier(train_test, monkeypatch):
    monkeypatch.setattr(train_module, "N_TRIALS", 3)
    train, test = train_test
    model, best_params, acc, ll, cm = train_xgboost(train, test, n_trials=3)
    assert isinstance(model, xgb.XGBClassifier)


def test_xgb_log_loss_finite_and_positive(train_test):
    train, test = train_test
    _, _, acc, ll, cm = train_xgboost(train, test, n_trials=3)
    assert math.isfinite(ll)
    assert ll > 0
    assert 0.0 <= acc <= 1.0


def test_xgb_best_params_keys(train_test):
    train, test = train_test
    _, best_params, _, _, _ = train_xgboost(train, test, n_trials=3)
    for key in ("max_depth", "learning_rate", "n_estimators", "subsample"):
        assert key in best_params


def test_xgb_artifact_saved(train_test, tmp_path):
    train, test = train_test
    model, _, _, _, _ = train_xgboost(train, test, n_trials=3)
    out_path = str(tmp_path / "xgb_best.pkl")
    save_model(model, out_path)
    assert os.path.exists(out_path)
    with open(out_path, "rb") as f:
        loaded = pickle.load(f)
    assert isinstance(loaded, xgb.XGBClassifier)


def test_main_creates_xgb_artifact(synthetic_csv, tmp_path, mlflow_uri):
    """main() with every output (pickles, registry, MLflow) redirected to tmp_path."""
    art = tmp_path / "artifacts"
    registry = train_module.main(
        features_path=synthetic_csv,
        artifacts_dir=str(art),
        n_trials=2,
        mlflow_tracking_uri=mlflow_uri,
    )
    for name in ("xgb_best.pkl", "baseline.pkl", "lgbm_best.pkl", "ensemble.pkl",
                 "best_model.pkl", "model_registry.json"):
        assert (art / name).exists(), f"{name} was not created by main()"
    assert registry["best_model"] in train_module.CANDIDATES
    assert math.isfinite(registry["log_loss"])
    with open(art / "xgb_best.pkl", "rb") as f:
        assert isinstance(pickle.load(f), xgb.XGBClassifier)
