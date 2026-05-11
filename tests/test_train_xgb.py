import math
import os
import pickle
import numpy as np
import pandas as pd
import pytest
import xgboost as xgb

import src.model.train as train_module
from src.model.train import (
    FEATURE_COLS,
    load_data,
    split_by_date,
    save_model,
    train_xgboost,
)


def _make_synthetic_df(n: int = 80, seed: int = 0) -> pd.DataFrame:
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


def test_main_creates_xgb_artifact(synthetic_csv, tmp_path, monkeypatch):
    xgb_out = str(tmp_path / "xgb_best.pkl")
    baseline_out = str(tmp_path / "baseline.pkl")
    monkeypatch.setattr(train_module, "FEATURES_PATH", synthetic_csv)
    monkeypatch.setattr(train_module, "BASELINE_PATH", baseline_out)
    monkeypatch.setattr(train_module, "XGB_PATH", xgb_out)
    monkeypatch.setattr(train_module, "N_TRIALS", 3)

    import mlflow
    mlruns_dir = (tmp_path / "mlruns").as_posix()
    mlflow.set_tracking_uri(f"file:///{mlruns_dir}")

    train_module.main()

    assert os.path.exists(xgb_out), "xgb_best.pkl was not created by main()"
    assert os.path.exists(baseline_out), "baseline.pkl was not created by main()"
