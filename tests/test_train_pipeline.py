"""End-to-end tests of walk-forward training; all output goes under tmp_path."""
import json
import math
import os
import pickle
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

import src.model.train as T
from tests.helpers_model import make_matches, mlflow_uri  # noqa: F401

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_KEYS = {
    "best_model", "log_loss", "walk_forward_log_loss", "walk_forward_accuracy",
    "holdout_log_loss", "holdout_accuracy", "models", "baselines", "feature_cols",
    "n_rows", "data_window", "leagues", "trained_at", "git_commit", "selection",
}


def _run(df, tmp_path, mlflow_uri, n_trials=2, **kw):
    art = tmp_path / "artifacts"
    reg = T.main(df=df, artifacts_dir=str(art), n_trials=n_trials, mlflow_tracking_uri=mlflow_uri, **kw)
    return reg, art


def test_end_to_end_season_mode(tmp_path, mlflow_uri):
    df = make_matches(seasons=(2018, 2019, 2020, 2021, 2022), per_season=120, with_odds=True,
                      leagues=["PL", "PD"], nan_frac=0.05)
    reg, art = _run(df, tmp_path, mlflow_uri)

    assert REGISTRY_KEYS <= set(reg)
    assert reg["best_model"] in T.CANDIDATES
    assert reg["selection"]["mode"] == "season"
    assert reg["selection"]["n_folds"] == 3
    assert reg["log_loss"] == reg["holdout_log_loss"]
    assert reg["leagues"] == ["PD", "PL"]
    assert reg["feature_cols"] == T.FEATURE_COLS
    assert reg["data_window"]["seasons"] == [2018, 2019, 2020, 2021, 2022]
    assert reg["holdout_window"]["seasons"] == [2022]
    assert reg["n_rows"] == len(df)
    assert set(reg["baselines"]) == {"uniform", "class_prior", "bookmaker", "bookmaker_shin", "elo"}
    assert reg["baselines"]["uniform"]["holdout_log_loss"] == pytest.approx(math.log(3), abs=1e-5)
    bm = reg["baselines"]["bookmaker"]
    assert 0 < bm["holdout_n_scored"] < bm["holdout_n_total"]  # 1 in 5 odds missing
    assert len(reg["models"]["xgboost"]["fold_log_loss"]) == 3

    # selection ignores the holdout
    best_by_wf = min(T.CANDIDATES, key=lambda n: (reg["models"][n]["walk_forward_log_loss"], n))
    assert reg["best_model"] == best_by_wf

    # registry on disk equals the returned dict and is valid JSON (no NaN)
    text = (art / "model_registry.json").read_text()
    assert json.loads(text, parse_constant=lambda c: pytest.fail(f"non-finite {c}")) == reg

    for fname in ["best_model.pkl", "baseline.pkl", "xgb_best.pkl", "lgbm_best.pkl", "ensemble.pkl"]:
        assert (art / fname).exists(), fname
    assert (tmp_path / "mlruns").exists()

    # the saved best model takes a plain numpy row, as the API supplies
    with open(art / "best_model.pkl", "rb") as f:
        best = pickle.load(f)
    proba = best.predict_proba(np.full((1, len(T.FEATURE_COLS)), 0.5))
    assert proba.shape == (1, 3)
    assert proba.sum() == pytest.approx(1.0)


def test_end_to_end_no_season_no_league_no_odds(tmp_path, mlflow_uri):
    df = make_matches(seasons=(2021, 2022), per_season=150, with_season=False)
    reg, art = _run(df, tmp_path, mlflow_uri)
    assert reg["selection"]["mode"] == "date"
    assert reg["leagues"] is None
    assert reg["data_window"]["seasons"] is None
    assert set(reg["baselines"]) == {"uniform", "class_prior", "elo"}
    assert math.isfinite(reg["holdout_log_loss"])


def test_training_is_deterministic(tmp_path, mlflow_uri):
    df = make_matches(seasons=(2019, 2020, 2021), per_season=150)
    r1, _ = _run(df, tmp_path / "a", mlflow_uri)
    r2, _ = _run(df, tmp_path / "b", mlflow_uri)
    assert r1["best_model"] == r2["best_model"]
    assert r1["walk_forward_log_loss"] == r2["walk_forward_log_loss"]
    assert r1["holdout_log_loss"] == r2["holdout_log_loss"]


def test_main_reads_csv_and_uses_module_constants(tmp_path, monkeypatch, mlflow_uri):
    csv = tmp_path / "features.csv"
    make_matches(seasons=(2020, 2021, 2022), per_season=120).to_csv(csv, index=False)
    art = tmp_path / "arts"
    monkeypatch.setattr(T, "FEATURES_PATH", str(csv))
    monkeypatch.setattr(T, "N_TRIALS", 2)
    for const, name in [("BEST_MODEL_PATH", "best_model.pkl"), ("REGISTRY_PATH", "model_registry.json"),
                        ("BASELINE_PATH", "baseline.pkl"), ("XGB_PATH", "xgb_best.pkl"),
                        ("LGBM_PATH", "lgbm_best.pkl"), ("ENSEMBLE_PATH", "ensemble.pkl")]:
        monkeypatch.setattr(T, const, str(art / name))
    T.main(mlflow_tracking_uri=mlflow_uri)
    for name in ["best_model.pkl", "model_registry.json", "baseline.pkl", "xgb_best.pkl",
                 "lgbm_best.pkl", "ensemble.pkl"]:
        assert (art / name).exists()


def test_logistic_pipeline_handles_nan_features():
    df = make_matches(seasons=(2020, 2021), per_season=100, nan_frac=0.2)
    df = T.sort_chronological(df)
    model, acc, ll, cm = T.train_baseline(df.iloc[:120], df.iloc[120:])
    assert math.isfinite(ll) and cm.shape == (3, 3)
    assert [n for n, _ in model.steps] == ["imputer", "scaler", "logreg"]
    X = df[T.FEATURE_COLS].to_numpy(dtype=float)
    assert np.isnan(X).any()
    assert np.isfinite(model.predict_proba(X)).all()


def test_logreg_receives_recency_weights():
    df = T.sort_chronological(make_matches(seasons=(2020, 2021), per_season=100))
    w = T.compute_sample_weights(df)
    a = T.make_logreg()
    T.fit_estimator(a, df[T.FEATURE_COLS].to_numpy(), df["target"].to_numpy(), w)
    b = T.make_logreg()
    T.fit_estimator(b, df[T.FEATURE_COLS].to_numpy(), df["target"].to_numpy(), None)
    assert not np.allclose(a.steps[-1][1].coef_, b.steps[-1][1].coef_)


def test_tuning_is_seeded():
    df = T.sort_chronological(make_matches(seasons=(2019, 2020, 2021, 2022), per_season=100))
    plan = T.make_splits(df)
    p1 = T.tune_model("xgboost", plan.df, plan.folds, n_trials=3, seed=7)
    p2 = T.tune_model("xgboost", plan.df, plan.folds, n_trials=3, seed=7)
    assert p1 == p2
    assert {"min_child_weight", "reg_lambda"} <= set(p1)
    l1 = T.tune_model("lgbm", plan.df, plan.folds, n_trials=2, seed=7)
    assert {"min_child_samples", "reg_lambda"} <= set(l1)


def test_calibration_and_stacking_use_disjoint_slices():
    df = T.sort_chronological(make_matches(seasons=(2019, 2020), per_season=200))
    fit_df, cal_df, stack_df = T.chronological_slices(df)
    assert fit_df["date"].max() < cal_df["date"].min()
    assert cal_df["date"].max() < stack_df["date"].min()
    params = {"logistic_regression": {}, "xgboost": {"n_estimators": 20}, "lgbm": {"n_estimators": 20}}
    calibrated, ensemble = T.build_calibrated_stack(params, df)
    X = df[T.FEATURE_COLS].to_numpy()
    for p in [ensemble.predict_proba(X)] + [m.predict_proba(X) for m in calibrated.values()]:
        np.testing.assert_allclose(p.sum(axis=1), 1.0)
        assert (p > 0).all()


def test_final_models_are_refit_on_all_dev_data():
    df = T.sort_chronological(make_matches(seasons=(2019, 2020, 2021), per_season=150))
    plan = T.make_splits(df)
    params = {"logistic_regression": {}, "xgboost": {"n_estimators": 20}, "lgbm": {"n_estimators": 20}}
    final = T.fit_final_models(params, plan.dev)
    assert set(final) == set(T.CANDIDATES)
    # LR was refit on all of dev: matches a direct fit on dev with recency weights
    ref = T.fit_plain("logistic_regression", params, plan.dev)
    np.testing.assert_allclose(
        final["logistic_regression"].steps[-1][1].coef_, ref.steps[-1][1].coef_
    )
    # calibrated/ensemble wrappers hold the dev-refit base, not the small slice fit
    assert final["calibrated_lr"].base_model is final["logistic_regression"]
    assert final["ensemble"].base_models[1].base_model is final["xgboost"]


def test_pickles_from_cli_load_in_a_fresh_process(tmp_path, mlflow_uri):
    """`python -m src.model.train` must not pickle classes as __main__.X."""
    csv = tmp_path / "features.csv"
    make_matches(seasons=(2020, 2021, 2022), per_season=100).to_csv(csv, index=False)
    art = tmp_path / "art"
    run = subprocess.run(
        [sys.executable, "-m", "src.model.train", "--features", str(csv), "--artifacts-dir", str(art),
         "--n-trials", "1", "--mlflow-uri", mlflow_uri],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    for name in ["best_model.pkl", "ensemble.pkl"]:
        code = (
            "import pickle, numpy as np\n"
            f"m = pickle.load(open(r'{art / name}', 'rb'))\n"
            f"p = m.predict_proba(np.zeros((1, {len(T.FEATURE_COLS)})))\n"
            "assert abs(p.sum() - 1) < 1e-9\n"
        )
        out = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
                             text=True, timeout=120)
        assert out.returncode == 0, out.stderr
    with open(art / "ensemble.pkl", "rb") as f:
        raw = f.read()
    assert b"__main__" not in raw
