import os
import pickle
import tempfile
import datetime
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from src.model.train import (
    split_by_date,
    train_baseline,
    save_model,
    FEATURE_COLS,
    TARGET_COL,
)


def _make_df(n=100, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-08-01", periods=n, freq="3D")
    data = {col: rng.random(n) for col in FEATURE_COLS}
    data["date"] = dates
    data[TARGET_COL] = rng.integers(0, 3, size=n)
    data["match_id"] = range(n)
    return pd.DataFrame(data).sort_values("date").reset_index(drop=True)


def test_split_by_date_proportions():
    df = _make_df(100)
    train, test = split_by_date(df, test_fraction=0.2)
    assert len(train) == 80
    assert len(test) == 20


def test_split_by_date_no_overlap():
    df = _make_df(100)
    train, test = split_by_date(df, test_fraction=0.2)
    assert train["date"].max() <= test["date"].min()


def test_split_preserves_chronological_order():
    df = _make_df(50)
    train, test = split_by_date(df, test_fraction=0.2)
    all_dates = pd.concat([train["date"], test["date"]])
    assert list(all_dates) == sorted(all_dates)


def test_train_baseline_returns_metrics():
    df = _make_df(80)
    train, test = split_by_date(df, test_fraction=0.2)
    model, acc, ll, cm = train_baseline(train, test)
    assert 0.0 <= acc <= 1.0
    assert ll > 0.0
    assert cm.shape == (3, 3)


def test_train_baseline_probabilities_sum_to_one():
    df = _make_df(80)
    train, test = split_by_date(df, test_fraction=0.2)
    model, _, _, _ = train_baseline(train, test)
    proba = model.predict_proba(test[FEATURE_COLS])
    np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)


def test_save_model_creates_file():
    df = _make_df(80)
    train, test = split_by_date(df, test_fraction=0.2)
    model, _, _, _ = train_baseline(train, test)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "baseline.pkl")
        save_model(model, path)
        assert os.path.exists(path)
        with open(path, "rb") as f:
            loaded = pickle.load(f)
        preds = loaded.predict(test[FEATURE_COLS])
        assert len(preds) == len(test)
