import os
import pickle
import subprocess
import sys

import numpy as np
import pytest
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

import src.model.train as train_module
import src.model.wrappers as wrappers
from src.model.wrappers import (
    CalibratedModel,
    EnsembleModel,
    calibrate_model,
    fit_ensemble,
    normalise_proba,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data(n=300, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 4))
    logits = np.column_stack([X[:, 0], np.zeros(n), -X[:, 0]])
    p = np.exp(logits)
    p /= p.sum(axis=1, keepdims=True)
    y = np.array([rng.choice(3, p=r) for r in p])
    return X, y


def _fit_lr(X, y):
    return LogisticRegression(max_iter=500).fit(X, y)


def test_train_reexports_wrapper_classes():
    assert train_module.CalibratedModel is wrappers.CalibratedModel
    assert train_module.EnsembleModel is wrappers.EnsembleModel


def test_wrapper_classes_are_defined_in_wrappers_module():
    assert CalibratedModel.__module__ == "src.model.wrappers"
    assert EnsembleModel.__module__ == "src.model.wrappers"


def test_normalise_proba_never_yields_zero_rows():
    p = normalise_proba(np.array([[0, 0, 0], [np.nan, 0, 0], [-1, 0.5, 0.5], [1, 0, 0]]))
    np.testing.assert_allclose(p.sum(axis=1), 1.0)
    assert (p > 0).all()
    np.testing.assert_allclose(p[0], 1 / 3)


@pytest.mark.parametrize("method", ["sigmoid", "isotonic"])
def test_calibrated_rows_sum_to_one(method):
    X, y = _data()
    base = _fit_lr(X[:150], y[:150])
    cal = calibrate_model(base, X[150:225], y[150:225], method=method)
    p = cal.predict_proba(X[225:])
    assert p.shape == (75, 3)
    np.testing.assert_allclose(p.sum(axis=1), 1.0)
    assert (p > 0).all()


def test_isotonic_calibrator_with_all_zero_output_yields_uniform_not_zero_rows():
    X, y = _data()
    base = _fit_lr(X, y)

    class Zero:
        def predict(self, v):
            return np.zeros(len(v))

    cal = CalibratedModel(base, [Zero(), Zero(), Zero()], method="isotonic")
    p = cal.predict_proba(X[:20])
    np.testing.assert_allclose(p.sum(axis=1), 1.0)
    assert (p > 0).all()
    np.testing.assert_allclose(p, 1 / 3)


def test_isotonic_extreme_step_function_never_zero_rows():
    X, y = _data()
    base = _fit_lr(X[:100], y[:100])
    raw = base.predict_proba(X[100:140])
    # calibrators that map everything outside a narrow band to 0
    calibrators = []
    for i in range(3):
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit([0.0, 0.01, 0.99, 1.0], [0, 0, 0, 0])
        calibrators.append(iso)
    p = CalibratedModel(base, calibrators, method="isotonic").predict_proba(X[100:140])
    assert np.isfinite(p).all()
    np.testing.assert_allclose(p.sum(axis=1), 1.0)
    assert raw.shape == p.shape


def test_calibration_with_single_class_slice_is_identity():
    X, y = _data()
    base = _fit_lr(X, y)
    cal = calibrate_model(base, X[:30], np.zeros(30, dtype=int))
    assert cal.method == "identity"
    np.testing.assert_allclose(cal.predict_proba(X[:5]).sum(axis=1), 1.0)


def test_ensemble_predicts_valid_probabilities():
    X, y = _data()
    b1, b2 = _fit_lr(X[:100], y[:100]), _fit_lr(X[:100, :2], y[:100])

    class OnTwoCols:
        classes_ = np.arange(3)

        def __init__(self, m):
            self.m = m

        def predict_proba(self, A):
            return self.m.predict_proba(np.asarray(A)[:, :2])

    ens = fit_ensemble([b1, OnTwoCols(b2)], X[100:200], y[100:200])
    p = ens.predict_proba(X[200:])
    np.testing.assert_allclose(p.sum(axis=1), 1.0)
    assert ens.predict(X[200:]).shape == (100,)


def test_fit_ensemble_rejects_single_class_slice():
    X, y = _data()
    with pytest.raises(ValueError):
        fit_ensemble([_fit_lr(X, y)], X[:20], np.zeros(20, dtype=int))


def _load_in_subprocess(path, n_features):
    """Load a pickle in a fresh interpreter that never imported train.py."""
    code = (
        "import pickle, sys\n"
        f"m = pickle.load(open(r'{path}', 'rb'))\n"
        "import numpy as np\n"
        f"p = m.predict_proba(np.zeros((2, {n_features})))\n"
        "assert 'src.model.train' not in sys.modules\n"
        "assert abs(p.sum(axis=1) - 1).max() < 1e-9\n"
        "print(type(m).__module__, type(m).__name__)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_wrappers_unpickle_in_fresh_process(tmp_path):
    X, y = _data()
    base = _fit_lr(X[:150], y[:150])
    cal = calibrate_model(base, X[150:225], y[150:225], method="sigmoid")
    cal_iso = calibrate_model(base, X[150:225], y[150:225], method="isotonic")
    ens = fit_ensemble([cal, cal_iso], X[225:], y[225:])
    for name, obj, expected in [
        ("cal.pkl", cal, "src.model.wrappers CalibratedModel"),
        ("cal_iso.pkl", cal_iso, "src.model.wrappers CalibratedModel"),
        ("ens.pkl", ens, "src.model.wrappers EnsembleModel"),
    ]:
        path = tmp_path / name
        with open(path, "wb") as f:
            pickle.dump(obj, f)
        assert _load_in_subprocess(path, 4) == expected
