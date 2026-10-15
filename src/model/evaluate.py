"""Evaluate the selected model on the untouched holdout and explain it.

The explainer is chosen from the model type:

* XGBoost / LightGBM (unwrapped from calibration wrappers) -> ``TreeExplainer``
* impute->scale->LogisticRegression pipeline -> ``LinearExplainer`` on the
  transformed features
* anything else (e.g. the stacking ensemble) -> ``KernelExplainer`` on a small
  seeded background sample
* if SHAP fails for any reason -> seeded permutation importance (increase in
  holdout log-loss when a feature is shuffled).

The holdout comes from ``train.make_splits`` so it is exactly the data that was
never used for tuning or selection.
"""
import datetime
import json
import os
import pickle
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import confusion_matrix
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression

from src.model import train as T
from src.model.baselines import accuracy_3, log_loss_3
from src.model.wrappers import CalibratedModel, base_predict_proba

SHAP_PLOT_PATH = os.path.join("data", "processed", "shap_summary.png")
EVAL_REPORT_PATH = os.path.join("data", "processed", "eval_report.txt")
SEED = 42


def load_model(path: Optional[str] = None):
    path = path or T.BEST_MODEL_PATH
    with open(path, "rb") as f:
        return pickle.load(f)


# ---------------------------------------------------------------------------
# Choosing an explainer
# ---------------------------------------------------------------------------
def classify_model(model):
    """Return ``(kind, estimator)`` with kind in {"tree", "linear", "other"}.

    Calibration wrappers are unwrapped: the importance then describes the base
    model (calibration is a monotone-ish remapping of its probabilities).
    """
    est = model
    while isinstance(est, CalibratedModel):
        est = est.base_model
    name = type(est).__name__
    if name in ("XGBClassifier", "LGBMClassifier"):
        return "tree", est
    if isinstance(est, Pipeline) and isinstance(est.steps[-1][1], LogisticRegression):
        return "linear", est
    if isinstance(est, LogisticRegression):
        return "linear", est
    return "other", model


def mean_abs_importance(shap_values, n_features: int) -> np.ndarray:
    """Mean |SHAP| per feature from a list, 2-D or 3-D shap output."""
    if isinstance(shap_values, list):
        return np.mean([np.abs(np.asarray(sv)).mean(axis=0) for sv in shap_values], axis=0)
    arr = np.abs(np.asarray(shap_values))
    if arr.ndim == 2:
        return arr.mean(axis=0)
    if arr.ndim == 3:
        # (n, features, classes) in recent shap, (classes, n, features) in some
        feat_axis = [ax for ax, size in enumerate(arr.shape) if size == n_features]
        feat_axis = feat_axis[-1] if feat_axis else 1
        other = tuple(ax for ax in range(3) if ax != feat_axis)
        return arr.mean(axis=other)
    raise ValueError(f"Unexpected SHAP output shape {arr.shape}")


def permutation_importance(model, X, y, n_repeats: int = 5, seed: int = SEED) -> np.ndarray:
    """Mean increase in log-loss when each column is shuffled (seeded)."""
    rng = np.random.default_rng(seed)
    X = np.asarray(X, dtype=float)
    base = log_loss_3(y, base_predict_proba(model, X))
    out = np.zeros(X.shape[1])
    for j in range(X.shape[1]):
        deltas = []
        for _ in range(n_repeats):
            Xp = X.copy()
            Xp[:, j] = rng.permutation(Xp[:, j])
            deltas.append(log_loss_3(y, base_predict_proba(model, Xp)) - base)
        out[j] = float(np.mean(deltas))
    return out


def _sample_rows(n: int, max_rows: int, seed: int):
    if n <= max_rows:
        return np.arange(n)
    return np.sort(np.random.default_rng(seed).choice(n, size=max_rows, replace=False))


def compute_importance(model, X, y, max_rows: int = 200, seed: int = SEED, n_background: int = 30):
    """Feature importance with the most appropriate method for ``model``.

    Returns ``dict(method, importance, shap_values, X_used)``.
    """
    X = np.asarray(X, dtype=float)
    idx = _sample_rows(len(X), max_rows, seed)
    Xs, ys = X[idx], np.asarray(y)[idx]
    kind, est = classify_model(model)
    n_feat = X.shape[1]
    errors = []

    try:
        import shap

        if kind == "tree":
            sv = shap.TreeExplainer(est).shap_values(Xs)
            return {"method": "TreeExplainer", "importance": mean_abs_importance(sv, n_feat),
                    "shap_values": sv, "X_used": Xs}
        if kind == "linear":
            if isinstance(est, Pipeline):
                Z = est[:-1].transform(Xs)
                clf = est.steps[-1][1]
            else:
                Z, clf = Xs, est
            sv = shap.LinearExplainer(clf, Z).shap_values(Z)
            return {"method": "LinearExplainer", "importance": mean_abs_importance(sv, n_feat),
                    "shap_values": sv, "X_used": Z}
        bg = shap.sample(Xs, min(n_background, len(Xs)), random_state=seed)
        rows = Xs[: min(40, len(Xs))]
        explainer = shap.KernelExplainer(lambda Z: base_predict_proba(model, np.asarray(Z)), bg)
        sv = explainer.shap_values(rows, nsamples=100, silent=True)
        return {"method": "KernelExplainer", "importance": mean_abs_importance(sv, n_feat),
                "shap_values": sv, "X_used": rows}
    except Exception as exc:  # SHAP/version quirks must not kill evaluation
        errors.append(repr(exc))

    imp = permutation_importance(model, Xs, ys, seed=seed)
    return {"method": "permutation (log-loss increase)", "importance": imp,
            "shap_values": None, "X_used": Xs, "fallback_reason": errors[0] if errors else None}


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
def save_importance_plot(result: dict, feature_names, path: Optional[str] = None):
    path = path or SHAP_PLOT_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    plotted = False
    if result.get("shap_values") is not None:
        try:
            import shap

            shap.summary_plot(
                result["shap_values"], result["X_used"], feature_names=list(feature_names), show=False
            )
            plt.savefig(path, bbox_inches="tight")
            plotted = True
        except Exception:
            plotted = False
        finally:
            plt.close("all")
    if not plotted:
        imp = np.asarray(result["importance"])
        order = np.argsort(imp)
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.barh([feature_names[i] for i in order], imp[order])
        ax.set_xlabel(result["method"])
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
    return path


def save_eval_report(
    model_path, training_date, acc, ll, cm, feature_names, importance,
    path: Optional[str] = None, method: str = "", holdout_info: str = "", registry: Optional[dict] = None,
):
    path = path or EVAL_REPORT_PATH
    importance = np.asarray(importance)
    top10_idx = np.argsort(importance)[::-1][:10]
    top10 = [(feature_names[i], float(importance[i])) for i in top10_idx]

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write("=== Football Predictor - Evaluation Report ===\n\n")
        f.write(f"Model:          {os.path.basename(str(model_path))}\n")
        f.write(f"Training date:  {training_date}\n")
        if registry:
            f.write(f"Selected:       {registry.get('best_model')}\n")
            f.write(f"Walk-forward:   log-loss {registry.get('walk_forward_log_loss')}\n")
        f.write(f"Holdout:        {holdout_info}\n\n")
        f.write(f"Holdout Accuracy:  {acc:.4f}\n")
        f.write(f"Holdout Log-Loss:  {ll:.4f}   (uniform = ln 3 = 1.0986)\n\n")
        f.write("Confusion Matrix (rows=actual, cols=predicted):\n")
        f.write("  Labels: 0=Home Win, 1=Draw, 2=Away Win\n")
        f.write(f"{cm}\n\n")
        f.write(f"Top 10 Features by importance ({method}):\n")
        for rank, (feat, val) in enumerate(top10, 1):
            f.write(f"  {rank:2d}. {feat:<40s} {val:.4f}\n")
    return top10


def main(
    features_path: Optional[str] = None,
    model_path: Optional[str] = None,
    shap_plot_path: Optional[str] = None,
    report_path: Optional[str] = None,
    registry_path: Optional[str] = None,
    max_rows: int = 200,
):
    model_path = model_path or T.BEST_MODEL_PATH
    shap_plot_path = shap_plot_path or SHAP_PLOT_PATH
    report_path = report_path or EVAL_REPORT_PATH
    registry_path = registry_path or T.REGISTRY_PATH

    model = load_model(model_path)
    training_date = datetime.datetime.fromtimestamp(os.path.getmtime(model_path)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    registry = None
    if os.path.exists(registry_path):
        with open(registry_path) as f:
            registry = json.load(f)

    df = T.load_data(features_path)
    holdout = T.make_splits(df).holdout
    X = holdout[T.FEATURE_COLS].to_numpy(dtype=float)
    y = holdout[T.TARGET_COL].to_numpy(dtype=int)

    proba = base_predict_proba(model, X)
    y_pred = np.argmax(proba, axis=1)
    acc, ll = accuracy_3(y, proba), log_loss_3(y, proba)
    cm = confusion_matrix(y, y_pred, labels=[0, 1, 2])

    result = compute_importance(model, X, y, max_rows=max_rows)
    save_importance_plot(result, T.FEATURE_COLS, shap_plot_path)
    info = (f"{len(holdout)} rows, {holdout['date'].min():%Y-%m-%d} to "
            f"{holdout['date'].max():%Y-%m-%d}")
    top10 = save_eval_report(
        model_path, training_date, acc, ll, cm, T.FEATURE_COLS, result["importance"],
        path=report_path, method=result["method"], holdout_info=info, registry=registry,
    )

    print(f"Holdout ({info})")
    print(f"Accuracy:  {acc:.4f}")
    print(f"Log-Loss:  {ll:.4f}")
    print(f"\nConfusion Matrix:\n{cm}")
    print(f"\nTop 10 Features ({result['method']}):")
    for rank, (feat, val) in enumerate(top10, 1):
        print(f"  {rank:2d}. {feat:<40s} {val:.4f}")
    print(f"\nPlot saved to {shap_plot_path}")
    print(f"Eval report saved to {report_path}")
    return {"accuracy": acc, "log_loss": ll, "method": result["method"], "top10": top10}


if __name__ == "__main__":
    main()
