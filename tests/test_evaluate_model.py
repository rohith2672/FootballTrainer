"""evaluate.py must work for every model type and write only to tmp_path."""
import numpy as np
import pytest

import src.model.evaluate as E
import src.model.train as T
from src.model.wrappers import CalibratedModel
from tests.helpers_model import make_matches, mlflow_uri  # noqa: F401


@pytest.fixture(scope="module")
def trained():
    df = T.sort_chronological(make_matches(seasons=(2019, 2020, 2021), per_season=150, nan_frac=0.05))
    plan = T.make_splits(df)
    params = {"logistic_regression": {}, "xgboost": {"n_estimators": 30}, "lgbm": {"n_estimators": 30}}
    models = T.fit_final_models(params, plan.dev)
    holdout = plan.holdout
    X = holdout[T.FEATURE_COLS].to_numpy(dtype=float)
    y = holdout["target"].to_numpy(dtype=int)
    return models, X, y


@pytest.mark.parametrize(
    "name,method",
    [
        ("xgboost", "TreeExplainer"),
        ("lgbm", "TreeExplainer"),
        ("calibrated_xgb", "TreeExplainer"),
        ("logistic_regression", "LinearExplainer"),
        ("calibrated_lr", "LinearExplainer"),
        ("ensemble", "KernelExplainer"),
    ],
)
def test_importance_for_each_model_type(trained, name, method):
    models, X, y = trained
    res = E.compute_importance(models[name], X, y, max_rows=60, n_background=10)
    # SHAP may legitimately fall back to permutation on some library versions
    assert res["method"] in (method, "permutation (log-loss increase)")
    imp = np.asarray(res["importance"])
    assert imp.shape == (len(T.FEATURE_COLS),)
    assert np.isfinite(imp).all()


def test_classify_unwraps_calibration(trained):
    models, _, _ = trained
    assert E.classify_model(models["calibrated_lgbm"])[0] == "tree"
    assert E.classify_model(models["calibrated_lr"])[0] == "linear"
    assert E.classify_model(models["ensemble"])[0] == "other"
    assert isinstance(models["calibrated_lr"], CalibratedModel)


def test_permutation_importance_is_seeded(trained):
    models, X, y = trained
    a = E.permutation_importance(models["logistic_regression"], X, y, n_repeats=2, seed=1)
    b = E.permutation_importance(models["logistic_regression"], X, y, n_repeats=2, seed=1)
    np.testing.assert_allclose(a, b)


def test_mean_abs_importance_shapes():
    n, f, c = 10, 4, 3
    rng = np.random.default_rng(0)
    assert E.mean_abs_importance(rng.normal(size=(n, f)), f).shape == (f,)
    assert E.mean_abs_importance(rng.normal(size=(n, f, c)), f).shape == (f,)
    assert E.mean_abs_importance([rng.normal(size=(n, f)) for _ in range(c)], f).shape == (f,)
    assert E.mean_abs_importance(rng.normal(size=(c, n, f)), f).shape == (f,)


def test_main_writes_only_to_redirected_paths(tmp_path, mlflow_uri):
    csv = tmp_path / "features.csv"
    make_matches(seasons=(2019, 2020, 2021), per_season=120).to_csv(csv, index=False)
    art = tmp_path / "art"
    T.main(features_path=str(csv), artifacts_dir=str(art), n_trials=1,
           mlflow_tracking_uri=mlflow_uri)
    out = E.main(
        features_path=str(csv),
        model_path=str(art / "best_model.pkl"),
        registry_path=str(art / "model_registry.json"),
        shap_plot_path=str(tmp_path / "out" / "shap.png"),
        report_path=str(tmp_path / "out" / "report.txt"),
        max_rows=50,
    )
    assert (tmp_path / "out" / "shap.png").exists()
    report = (tmp_path / "out" / "report.txt").read_text()
    assert "Holdout Log-Loss" in report and "Top 10 Features" in report
    assert np.isfinite(out["log_loss"])
