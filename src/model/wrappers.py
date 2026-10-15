"""Picklable model wrappers.

These classes live in their own module (NOT in ``train.py``) so that pickles
written by ``python -m src.model.train`` reference ``src.model.wrappers`` and
can be loaded by the API process. Classes defined in a script run as
``__main__`` pickle as ``__main__.ClassName`` and fail to load elsewhere.

Every wrapper accepts a 2-D array-like of features (the API passes a plain
``numpy`` array) and exposes ``predict_proba`` / ``predict`` over the three
classes 0=home win, 1=draw, 2=away win. Output rows are guaranteed to be
finite, strictly positive and to sum to one.
"""
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

N_CLASSES = 3
PROB_FLOOR = 1e-6
_LOG_FLOOR = 1e-6


def expand_proba(proba, classes=None, n_classes: int = N_CLASSES) -> np.ndarray:
    """Place ``proba`` columns into an ``(n, n_classes)`` array by class label."""
    proba = np.asarray(proba, dtype=float)
    if classes is None:
        classes = np.arange(proba.shape[1])
    classes = [int(c) for c in classes]
    if proba.shape[1] == n_classes and classes == list(range(n_classes)):
        return proba
    out = np.zeros((proba.shape[0], n_classes), dtype=float)
    for col, cls in enumerate(classes):
        out[:, cls] = proba[:, col]
    return out


def normalise_proba(p, floor: float = PROB_FLOOR) -> np.ndarray:
    """Clip, repair and renormalise probability rows.

    * non-finite or negative entries become 0;
    * rows that sum to 0 (e.g. all calibrators output 0) become uniform;
    * every entry is floored at ``floor`` and rows are renormalised to sum to 1.
    """
    p = np.array(p, dtype=float, copy=True)
    p = np.nan_to_num(p, nan=0.0, posinf=0.0, neginf=0.0)
    p = np.clip(p, 0.0, None)
    n_cols = p.shape[1]
    sums = p.sum(axis=1)
    empty = sums <= 0
    if empty.any():
        p[empty] = 1.0 / n_cols
        sums = p.sum(axis=1)
    p = p / sums[:, None]
    p = np.clip(p, floor, None)
    return p / p.sum(axis=1, keepdims=True)


def base_predict_proba(model, X) -> np.ndarray:
    """``predict_proba`` of any fitted classifier, as a normalised (n, 3) array."""
    raw = model.predict_proba(X)
    classes = getattr(model, "classes_", None)
    return normalise_proba(expand_proba(raw, classes))


class CalibratedModel:
    """A fitted classifier followed by a probability calibrator.

    ``method``:
      * ``"sigmoid"``  - ``calibrators`` is one multinomial ``LogisticRegression``
        fitted on log-probabilities (vector scaling; 12 parameters, robust on
        small calibration slices);
      * ``"isotonic"`` - ``calibrators`` is a list of per-class
        ``IsotonicRegression`` (legacy; needs more data);
      * ``"identity"`` - no calibration (calibration slice had a single class).
    """

    def __init__(self, base_model, calibrators=None, method: str = "isotonic"):
        self.base_model = base_model
        self.calibrators = calibrators
        self.method = method

    @property
    def classes_(self):
        return np.arange(N_CLASSES)

    def predict_proba(self, X):
        raw = base_predict_proba(self.base_model, X)
        method = getattr(self, "method", "isotonic")
        if method == "sigmoid":
            z = np.log(np.clip(raw, _LOG_FLOOR, 1.0))
            cal = expand_proba(
                self.calibrators.predict_proba(z), self.calibrators.classes_
            )
        elif method == "isotonic":
            cal = np.column_stack(
                [self.calibrators[i].predict(raw[:, i]) for i in range(raw.shape[1])]
            )
        else:
            cal = raw
        return normalise_proba(cal)

    def predict(self, X):
        return np.argmax(self.predict_proba(X), axis=1)


def calibrate_model(model, X_cal, y_cal, method: str = "sigmoid", C: float = 1.0):
    """Fit a calibrator for ``model`` on a held-out calibration slice."""
    y_cal = np.asarray(y_cal)
    raw = base_predict_proba(model, X_cal)
    if len(np.unique(y_cal)) < 2:
        return CalibratedModel(model, None, method="identity")
    if method == "isotonic":
        calibrators = []
        for i in range(raw.shape[1]):
            iso = IsotonicRegression(out_of_bounds="clip")
            iso.fit(raw[:, i], (y_cal == i).astype(int))
            calibrators.append(iso)
        return CalibratedModel(model, calibrators, method="isotonic")
    if method == "sigmoid":
        lr = LogisticRegression(C=C, max_iter=1000, solver="lbfgs")
        lr.fit(np.log(np.clip(raw, _LOG_FLOOR, 1.0)), y_cal)
        return CalibratedModel(model, lr, method="sigmoid")
    raise ValueError(f"Unknown calibration method: {method!r}")


class EnsembleModel:
    """Stacking ensemble: a meta-learner over base models' probabilities.

    ``use_log=True`` feeds log-probabilities to the meta-learner (default for
    models trained by ``train.py``); ``False`` reproduces the legacy behaviour
    of stacking raw probabilities.
    """

    def __init__(self, base_models, meta, use_log: bool = False):
        self.base_models = base_models
        self.meta = meta
        self.use_log = use_log

    @property
    def classes_(self):
        return np.arange(N_CLASSES)

    @staticmethod
    def stack_features(base_models, X, use_log: bool) -> np.ndarray:
        parts = [base_predict_proba(m, X) for m in base_models]
        if use_log:
            parts = [np.log(np.clip(p, _LOG_FLOOR, 1.0)) for p in parts]
        return np.hstack(parts)

    def predict_proba(self, X):
        stack = self.stack_features(
            self.base_models, X, getattr(self, "use_log", False)
        )
        return normalise_proba(
            expand_proba(self.meta.predict_proba(stack), self.meta.classes_)
        )

    def predict(self, X):
        return np.argmax(self.predict_proba(X), axis=1)


def fit_ensemble(base_models, X_stack, y_stack, C: float = 0.5, use_log: bool = True):
    """Fit the meta-learner on a slice that the base models never saw."""
    y_stack = np.asarray(y_stack)
    if len(np.unique(y_stack)) < 2:
        raise ValueError("stacking slice contains a single class")
    feats = EnsembleModel.stack_features(base_models, X_stack, use_log)
    meta = LogisticRegression(C=C, max_iter=1000, solver="lbfgs")
    meta.fit(feats, y_stack)
    return EnsembleModel(base_models, meta, use_log=use_log)
