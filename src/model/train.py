"""Model training with chronological walk-forward evaluation.

Evaluation design (no data leakage, nothing random):

* Rows are sorted by date with a deterministic tiebreak.
* The most recent complete season (or, with fewer than three seasons, the last
  ``HOLDOUT_FRACTION`` of distinct dates) is an untouched **holdout**. It is
  never used for tuning or model selection - only to report the final score.
* The rest ("dev") is evaluated with an expanding-window **walk-forward CV**:
  by season (train on seasons < s, validate on s) when at least three dev
  seasons exist, otherwise by chronological date blocks. Folds never split a
  single date.
* Optuna tunes XGBoost / LightGBM on mean walk-forward log-loss (seeded TPE).
* The model is chosen by mean walk-forward log-loss, then refit on all dev
  data. Calibrated / stacked variants are fitted with a chronological
  base | calibration | stacking carve-up so the calibrators and the
  meta-learner never see data the base models trained on, nor each other's.
"""
import argparse
import copy
import datetime
import json
import math
import os
import pickle
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional

import lightgbm as lgb
import mlflow
import numpy as np
import optuna
import pandas as pd
import xgboost as xgb
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

FEATURE_COLS = [
    "home_form_pts_pg",
    "home_form_goals_scored_avg",
    "home_form_goals_conceded_avg",
    "away_form_pts_pg",
    "away_form_goals_scored_avg",
    "away_form_goals_conceded_avg",
    "h2h_home_win_rate",
    "home_team_home_win_rate",
    "away_team_away_win_rate",
    "home_days_since_last",
    "away_days_since_last",
]
from src.model import baselines as baselines_mod
from src.model.baselines import accuracy_3, log_loss_3, score_probs
# Re-exported for backward compatibility (pickles now live in wrappers.py).
from src.model.wrappers import (  # noqa: F401
    CalibratedModel,
    EnsembleModel,
    base_predict_proba,
    calibrate_model,
    fit_ensemble,
    normalise_proba,
)

optuna.logging.set_verbosity(optuna.logging.WARNING)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FEATURES_PATH = os.path.join("data", "processed", "features.csv")
ARTIFACTS_DIR = os.path.join("src", "model", "artifacts")
BASELINE_PATH = os.path.join(ARTIFACTS_DIR, "baseline.pkl")
XGB_PATH      = os.path.join(ARTIFACTS_DIR, "xgb_best.pkl")
LGBM_PATH     = os.path.join(ARTIFACTS_DIR, "lgbm_best.pkl")
ENSEMBLE_PATH  = os.path.join(ARTIFACTS_DIR, "ensemble.pkl")
BEST_MODEL_PATH = os.path.join(ARTIFACTS_DIR, "best_model.pkl")
REGISTRY_PATH  = os.path.join(ARTIFACTS_DIR, "model_registry.json")
EXPERIMENT_NAME = "football-predictor"
N_TRIALS = 50
DECAY_LAMBDA = 0.001
SEED = 42
N_FOLDS = 4                 # date-block folds when season folds are not possible
HOLDOUT_FRACTION = 0.2      # holdout share of distinct dates when < 3 seasons
MIN_SEASONS_FOR_SEASON_HOLDOUT = 3
MIN_SEASONS_FOR_SEASON_FOLDS = 3   # dev seasons needed for season folds
PARTIAL_SEASON_RATIO = 0.5  # trailing season smaller than this x median = partial
CAL_SLICES = (0.6, 0.2, 0.2)  # base | calibration | stacking
CALIBRATION_METHOD = "sigmoid"

TARGET_COL = "target"

BASE_KINDS = ("logistic_regression", "xgboost", "lgbm")
CAL_NAMES = {
    "logistic_regression": "calibrated_lr",
    "xgboost": "calibrated_xgb",
    "lgbm": "calibrated_lgbm",
}
CANDIDATES = list(BASE_KINDS) + list(CAL_NAMES.values()) + ["ensemble"]
LABELS = [0, 1, 2]

SORT_KEYS = ["date", "league", "home_team", "away_team", "match_id"]

XGB_FIXED = {
    "objective": "multi:softprob",
    "num_class": 3,
    "eval_metric": "mlogloss",
    "random_state": 42,
    "verbosity": 0,
    "n_jobs": 1,
    "tree_method": "hist",
}
LGBM_FIXED = {
    "objective": "multiclass",
    "num_class": 3,
    "metric": "multi_logloss",
    "random_state": 42,
    "verbosity": -1,
    "n_jobs": 1,
    "subsample_freq": 1,
}


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
def sort_chronological(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by date with a deterministic tiebreak (league/teams/match_id if present)."""
    keys = [k for k in SORT_KEYS if k in df.columns]
    return df.sort_values(keys, kind="mergesort").reset_index(drop=True)


def load_data(path: str = None):
    if path is None:
        path = FEATURES_PATH
    df = pd.read_csv(path, parse_dates=["date"])
    return sort_chronological(df)


def _date_cutoff(dates: np.ndarray, idx: int) -> int:
    """Row index <= idx at which a cut never separates rows sharing a date."""
    n = len(dates)
    if idx <= 0:
        return 0
    if idx >= n:
        return n
    return int(np.searchsorted(dates, dates[idx], side="left"))


def _date_block_bounds(dates: np.ndarray, n_blocks: int) -> List[int]:
    n = len(dates)
    cuts = [0] + [_date_cutoff(dates, int(round(n * i / n_blocks))) for i in range(1, n_blocks)] + [n]
    out: List[int] = []
    for c in cuts:
        if not out or c > out[-1]:
            out.append(c)
    return out


def split_by_date(df: pd.DataFrame, test_fraction: float = 0.2):
    """Chronological train/test split; rows sharing a date stay on one side."""
    df = sort_chronological(df)
    dates = df["date"].to_numpy()
    cutoff = _date_cutoff(dates, int(len(df) * (1 - test_fraction)))
    return df.iloc[:cutoff], df.iloc[cutoff:]


def save_model(model, path: str = None):
    if path is None:
        path = BASELINE_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(model, f)


def compute_sample_weights(train_df: pd.DataFrame) -> np.ndarray:
    """Exponential recency weights (mean 1), relative to the newest training row."""
    age_days = (train_df["date"].max() - train_df["date"]).dt.days.values.astype(float)
    weights = np.exp(-DECAY_LAMBDA * age_days)
    return weights / weights.mean()


def _X(df: pd.DataFrame) -> np.ndarray:
    return df[FEATURE_COLS].to_numpy(dtype=float)


def _y(df: pd.DataFrame) -> np.ndarray:
    return df[TARGET_COL].to_numpy(dtype=int)


def _require_all_classes(df: pd.DataFrame, what: str):
    present = set(np.unique(_y(df)).tolist())
    if present != set(LABELS):
        raise ValueError(f"{what} is missing classes {sorted(set(LABELS) - present)}")


# ---------------------------------------------------------------------------
# Chronological split plan (walk-forward folds + untouched holdout)
# ---------------------------------------------------------------------------
@dataclass
class SplitPlan:
    df: pd.DataFrame            # all rows, chronologically sorted, 0..n-1 index
    holdout_start: int          # df.iloc[:holdout_start] = dev, rest = holdout
    folds: list                 # [(train_positions, val_positions)] within dev
    fold_labels: List[str]
    mode: str                   # "season" | "season_holdout+date_folds" | "date"
    holdout_partial: bool       # a trailing in-progress season was appended to the holdout

    @property
    def dev(self) -> pd.DataFrame:
        return self.df.iloc[: self.holdout_start]

    @property
    def holdout(self) -> pd.DataFrame:
        return self.df.iloc[self.holdout_start:]


def _season_layout(df: pd.DataFrame):
    """[(season, start, stop, n)] in chronological order, or None if not usable."""
    if "season" not in df.columns or df["season"].isna().any():
        return None
    seasons = df["season"].to_numpy()
    info = []
    for s in pd.unique(seasons):
        idx = np.flatnonzero(seasons == s)
        a, b = int(idx.min()), int(idx.max()) + 1
        if b - a != len(idx):   # seasons interleave in time -> not trustworthy
            return None
        info.append((s, a, b, len(idx)))
    return info


def _date_folds(dates: np.ndarray, n_folds: int):
    """Expanding-window folds over date blocks of ``dates`` (sorted)."""
    bounds = _date_block_bounds(dates, n_folds + 1)
    folds, labels = [], []
    for i in range(1, len(bounds) - 1):
        tr = np.arange(0, bounds[i])
        va = np.arange(bounds[i], bounds[i + 1])
        folds.append((tr, va))
        labels.append(
            f"{pd.Timestamp(dates[bounds[i]]):%Y-%m-%d}..{pd.Timestamp(dates[bounds[i + 1] - 1]):%Y-%m-%d}"
        )
    return folds, labels


def make_splits(
    df: pd.DataFrame,
    n_folds: int = N_FOLDS,
    holdout_fraction: float = HOLDOUT_FRACTION,
) -> SplitPlan:
    """Build the walk-forward folds and the holdout. Single source of truth:
    train.py and evaluate.py both call this so they agree on the holdout."""
    df = sort_chronological(df)
    n = len(df)
    if n < 20:
        raise ValueError(f"Not enough rows to evaluate ({n})")
    dates = df["date"].to_numpy()

    layout = _season_layout(df)
    complete, partial = None, False
    if layout is not None and len(layout) >= 2:
        median_prev = float(np.median([e[3] for e in layout[:-1]]))
        partial = layout[-1][3] < PARTIAL_SEASON_RATIO * median_prev
        complete = layout[:-1] if partial else layout
    elif layout is not None:
        complete = layout

    if complete is not None and len(complete) >= MIN_SEASONS_FOR_SEASON_HOLDOUT:
        holdout_start = complete[-1][1]
        dev_seasons = complete[:-1]
        if len(dev_seasons) >= MIN_SEASONS_FOR_SEASON_FOLDS:
            folds, labels = [], []
            for s, a, b, _ in dev_seasons[1:]:
                folds.append((np.arange(0, a), np.arange(a, b)))
                labels.append(f"season {s}")
            mode = "season"
        else:
            folds, labels = _date_folds(dates[:holdout_start], n_folds)
            mode = "season_holdout+date_folds"
        hold_partial = partial
    else:
        holdout_start = _date_cutoff(dates, int(n * (1 - holdout_fraction)))
        folds, labels = _date_folds(dates[:holdout_start], n_folds)
        mode, hold_partial = "date", False

    if holdout_start <= 0 or holdout_start >= n or not folds:
        raise ValueError("Could not build a non-empty dev set, folds and holdout")

    # Chronology guarantees (strict: no date appears on both sides of any cut).
    for tr, va in folds:
        if not dates[tr].max() < dates[va].min():
            raise ValueError("walk-forward fold leaks: train dates overlap validation")
    if not dates[:holdout_start].max() < dates[holdout_start:].min():
        raise ValueError("holdout leaks: dev dates overlap holdout")

    return SplitPlan(df, holdout_start, folds, labels, mode, hold_partial)


def chronological_slices(df: pd.DataFrame, fractions=CAL_SLICES):
    """base | calibration | stacking slices, cut on distinct-date boundaries."""
    df = sort_chronological(df)
    dates = df["date"].to_numpy()
    n = len(df)
    c1 = _date_cutoff(dates, int(n * fractions[0]))
    c2 = _date_cutoff(dates, int(n * (fractions[0] + fractions[1])))
    parts = (df.iloc[:c1], df.iloc[c1:c2], df.iloc[c2:])
    if any(len(p) == 0 for p in parts):
        raise ValueError("not enough distinct dates for base/calibration/stacking slices")
    return parts


# ---------------------------------------------------------------------------
# Model factories
# ---------------------------------------------------------------------------
def make_logreg() -> Pipeline:
    """Impute -> scale -> multinomial logistic regression (NaN-tolerant)."""
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("scaler", StandardScaler()),
        ("logreg", LogisticRegression(max_iter=1000, solver="lbfgs")),
    ])


def make_model(kind: str, params: Optional[dict] = None):
    params = dict(params or {})
    if kind == "logistic_regression":
        return make_logreg()
    if kind == "xgboost":
        return xgb.XGBClassifier(**{**XGB_FIXED, **params})
    if kind == "lgbm":
        return lgb.LGBMClassifier(**{**LGBM_FIXED, **params})
    raise ValueError(f"Unknown model kind: {kind!r}")


def fit_estimator(model, X, y, sample_weight=None):
    """Fit with sample weights, routing them to the last step of a Pipeline."""
    if isinstance(model, Pipeline):
        last = model.steps[-1][0]
        model.fit(X, y, **{f"{last}__sample_weight": sample_weight})
    else:
        model.fit(X, y, sample_weight=sample_weight)
    return model


def fit_plain(kind: str, params: dict, train_df: pd.DataFrame, sample_weight=None):
    _require_all_classes(train_df, f"{kind} training slice")
    if sample_weight is None:
        sample_weight = compute_sample_weights(train_df)
    model = make_model(kind, params.get(kind) if kind in params else None)
    return fit_estimator(model, _X(train_df), _y(train_df), sample_weight)


def _suggest(kind: str, trial) -> dict:
    if kind == "xgboost":
        return {
            "max_depth": trial.suggest_int("max_depth", 2, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "min_child_weight": trial.suggest_float("min_child_weight", 1.0, 50.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-2, 50.0, log=True),
        }
    if kind == "lgbm":
        return {
            "num_leaves": trial.suggest_int("num_leaves", 4, 64),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 100),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-2, 50.0, log=True),
        }
    raise ValueError(kind)


def _usable_folds(df: pd.DataFrame, folds):
    """Folds whose training part has every class (required by XGB/LGBM)."""
    ok = []
    for tr, va in folds:
        if set(np.unique(_y(df.iloc[tr])).tolist()) == set(LABELS) and len(va):
            ok.append((tr, va))
    return ok


def tune_model(kind: str, df: pd.DataFrame, folds, n_trials: int = N_TRIALS, seed: int = SEED) -> dict:
    """Optuna (seeded TPE) minimising mean walk-forward log-loss."""
    folds = _usable_folds(df, folds)
    if not folds:
        raise ValueError("no usable walk-forward folds for tuning")
    prepared = []
    for tr, va in folds:
        tr_df, va_df = df.iloc[tr], df.iloc[va]
        prepared.append((_X(tr_df), _y(tr_df), compute_sample_weights(tr_df), _X(va_df), _y(va_df)))

    def objective(trial):
        params = _suggest(kind, trial)
        losses = []
        for X_tr, y_tr, w_tr, X_va, y_va in prepared:
            model = make_model(kind, params)
            fit_estimator(model, X_tr, y_tr, w_tr)
            losses.append(log_loss_3(y_va, base_predict_proba(model, X_va)))
        return float(np.mean(losses))

    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials)
    return dict(study.best_params)


# ---------------------------------------------------------------------------
# Candidate construction
# ---------------------------------------------------------------------------
def build_calibrated_stack(params: dict, train_df: pd.DataFrame, method: str = CALIBRATION_METHOD):
    """Calibrated variants + stacking ensemble fitted on disjoint slices.

    base models <- first slice; calibrators <- second; meta-learner <- third.
    Returns ({base_kind: CalibratedModel}, EnsembleModel).
    """
    fit_df, cal_df, stack_df = chronological_slices(train_df)
    calibrated = {}
    for kind in BASE_KINDS:
        base = fit_plain(kind, params, fit_df)
        calibrated[kind] = calibrate_model(base, _X(cal_df), _y(cal_df), method=method)
    ensemble = fit_ensemble(
        [calibrated[k] for k in BASE_KINDS], _X(stack_df), _y(stack_df)
    )
    return calibrated, ensemble


def fold_predictions(params: dict, train_df: pd.DataFrame, val_df: pd.DataFrame, method: str = CALIBRATION_METHOD):
    """Validation-set probabilities of every candidate trained on ``train_df``."""
    X_val = _X(val_df)
    preds = {}
    for kind in BASE_KINDS:
        preds[kind] = base_predict_proba(fit_plain(kind, params, train_df), X_val)
    calibrated, ensemble = build_calibrated_stack(params, train_df, method)
    for kind in BASE_KINDS:
        preds[CAL_NAMES[kind]] = calibrated[kind].predict_proba(X_val)
    preds["ensemble"] = ensemble.predict_proba(X_val)
    return preds


def fit_final_models(params: dict, dev_df: pd.DataFrame, method: str = CALIBRATION_METHOD) -> Dict[str, object]:
    """Refit every candidate on all dev data.

    Plain models are refit on 100% of dev. Calibrated/ensemble variants take
    their calibrators and meta-learner from the chronological base|cal|stack
    carve-up of dev, then swap in the base models refit on all of dev.
    """
    plain = {k: fit_plain(k, params, dev_df) for k in BASE_KINDS}
    calibrated, ensemble = build_calibrated_stack(params, dev_df, method)
    final = dict(plain)
    for kind in BASE_KINDS:
        cm = calibrated[kind]
        final[CAL_NAMES[kind]] = CalibratedModel(plain[kind], cm.calibrators, method=cm.method)
    final["ensemble"] = EnsembleModel(
        [final[CAL_NAMES[k]] for k in BASE_KINDS], ensemble.meta, use_log=ensemble.use_log
    )
    return final


# ---------------------------------------------------------------------------
# Walk-forward evaluation
# ---------------------------------------------------------------------------
def walk_forward_evaluate(plan: SplitPlan, params: dict, method: str = CALIBRATION_METHOD):
    """Score every candidate and every baseline on every walk-forward fold.

    A fold that cannot be fitted for ANY candidate (e.g. a class is missing
    from a slice) is dropped for ALL candidates so means stay comparable.
    """
    df = plan.df
    names = baselines_mod.available_baselines(plan.dev)
    models = {n: {"log_loss": [], "accuracy": []} for n in CANDIDATES}
    base_res = {n: {"log_loss": [], "accuracy": [], "n_scored": [], "n_total": []} for n in names}
    labels, sizes = [], []

    for (tr, va), label in zip(plan.folds, plan.fold_labels):
        train_df, val_df = df.iloc[tr], df.iloc[va]
        try:
            preds = fold_predictions(params, train_df, val_df, method)
        except ValueError as exc:
            print(f"  [skip fold {label}] {exc}")
            continue
        y_val = _y(val_df)
        for name, proba in preds.items():
            models[name]["log_loss"].append(log_loss_3(y_val, proba))
            models[name]["accuracy"].append(accuracy_3(y_val, proba))
        for bname in names:
            scores, _ = baselines_mod.evaluate_baseline(bname, train_df, val_df)
            base_res[bname]["log_loss"].append(scores["log_loss"])
            base_res[bname]["accuracy"].append(scores["accuracy"])
            base_res[bname]["n_scored"].append(scores["n_scored"])
            base_res[bname]["n_total"].append(scores["n_total"])
        labels.append(label)
        sizes.append((len(train_df), len(val_df)))

    if not labels:
        raise ValueError("No walk-forward fold could be evaluated")
    return {"fold_labels": labels, "fold_sizes": sizes, "models": models, "baselines": base_res}


def _mean(values):
    vals = [v for v in values if v is not None]
    return float(np.mean(vals)) if vals else None


# ---------------------------------------------------------------------------
# Legacy single-model trainers (kept for scripts/tests; tune on date folds)
# ---------------------------------------------------------------------------
def train_baseline(train: pd.DataFrame, test: pd.DataFrame, sample_weight=None):
    model = make_logreg()
    fit_estimator(model, _X(train), _y(train), sample_weight)
    y_test = _y(test)
    proba = base_predict_proba(model, _X(test))
    y_pred = np.argmax(proba, axis=1)
    return model, accuracy_3(y_test, proba), log_loss_3(y_test, proba), confusion_matrix(y_test, y_pred, labels=LABELS)


def _train_tree(kind, train, test, sample_weight, n_trials, n_folds, seed):
    train = sort_chronological(train)
    folds, _ = _date_folds(train["date"].to_numpy(), n_folds)
    best = tune_model(kind, train, folds, n_trials=n_trials, seed=seed)
    fixed = XGB_FIXED if kind == "xgboost" else LGBM_FIXED
    best_params = {**best, **fixed}
    if sample_weight is None:
        sample_weight = compute_sample_weights(train)
    model = make_model(kind, best_params)
    fit_estimator(model, _X(train), _y(train), sample_weight)
    y_test = _y(test)
    proba = base_predict_proba(model, _X(test))
    y_pred = np.argmax(proba, axis=1)
    return (
        model, best_params, accuracy_3(y_test, proba), log_loss_3(y_test, proba),
        confusion_matrix(y_test, y_pred, labels=LABELS),
    )


def train_xgboost(train, test, sample_weight=None, n_trials: int = N_TRIALS, n_folds: int = N_FOLDS, seed: int = SEED):
    return _train_tree("xgboost", train, test, sample_weight, n_trials, n_folds, seed)


def train_lgbm(train, test, sample_weight=None, n_trials: int = N_TRIALS, n_folds: int = N_FOLDS, seed: int = SEED):
    return _train_tree("lgbm", train, test, sample_weight, n_trials, n_folds, seed)


def train_stacking_ensemble(cal_lr, cal_xgb, cal_lgbm, X_val, y_val, X_test, y_test):
    """Fit the meta-learner on (X_val, y_val); score on the test arrays."""
    ensemble = fit_ensemble([cal_lr, cal_xgb, cal_lgbm], X_val, y_val)
    proba = ensemble.predict_proba(X_test)
    y_pred = np.argmax(proba, axis=1)
    return ensemble, accuracy_3(y_test, proba), log_loss_3(y_test, proba), confusion_matrix(y_test, y_pred, labels=LABELS)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def resolve_paths(artifacts_dir: Optional[str] = None) -> Dict[str, str]:
    """All output paths. ``None`` uses the module-level constants (read at call time)."""
    if artifacts_dir is None:
        return {
            "baseline": BASELINE_PATH, "xgb": XGB_PATH, "lgbm": LGBM_PATH,
            "ensemble": ENSEMBLE_PATH, "best": BEST_MODEL_PATH, "registry": REGISTRY_PATH,
        }
    return {
        "baseline": os.path.join(artifacts_dir, "baseline.pkl"),
        "xgb": os.path.join(artifacts_dir, "xgb_best.pkl"),
        "lgbm": os.path.join(artifacts_dir, "lgbm_best.pkl"),
        "ensemble": os.path.join(artifacts_dir, "ensemble.pkl"),
        "best": os.path.join(artifacts_dir, "best_model.pkl"),
        "registry": os.path.join(artifacts_dir, "model_registry.json"),
    }


def _git_commit() -> Optional[str]:
    try:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=repo_root,
        )
        value = out.stdout.strip()
        return value if out.returncode == 0 and value else None
    except Exception:
        return None


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return round(f, 6) if math.isfinite(f) else None
    if isinstance(obj, (pd.Timestamp, datetime.datetime, datetime.date)):
        return obj.strftime("%Y-%m-%d")
    return obj


def _window(df: pd.DataFrame) -> dict:
    seasons = None
    if "season" in df.columns and df["season"].notna().all():
        seasons = [_jsonable(s) for s in sorted(pd.unique(df["season"]))]
    return {
        "min_date": df["date"].min(), "max_date": df["date"].max(),
        "n_rows": int(len(df)), "seasons": seasons,
    }


def format_comparison_table(registry: dict) -> str:
    lines = [
        f"{'Model / baseline':<26}{'WF logloss':>12}{'WF acc':>9}{'Hold logloss':>14}{'Hold acc':>10}  coverage",
        "-" * 82,
    ]

    def fmt(v, w, nd=4):
        return f"{'-':>{w}}" if v is None else f"{v:>{w}.{nd}f}"

    for name, m in registry["models"].items():
        star = " *" if name == registry["best_model"] else ""
        lines.append(
            f"{name + star:<26}{fmt(m['walk_forward_log_loss'], 12)}{fmt(m['walk_forward_accuracy'], 9)}"
            f"{fmt(m['holdout_log_loss'], 14)}{fmt(m['holdout_accuracy'], 10)}"
        )
    lines.append("-" * 82)
    for name, b in registry["baselines"].items():
        cov = f"{b['holdout_n_scored']}/{b['holdout_n_total']} holdout rows"
        lines.append(
            f"{'[baseline] ' + name:<26}{fmt(b['walk_forward_log_loss'], 12)}{fmt(b['walk_forward_accuracy'], 9)}"
            f"{fmt(b['holdout_log_loss'], 14)}{fmt(b['holdout_accuracy'], 10)}  {cov}"
        )
    lines.append("(* = selected by mean walk-forward log-loss; uniform baseline = ln 3 = 1.0986)")
    return "\n".join(lines)


def _log_to_mlflow(registry: dict, paths: dict, tracking_uri: Optional[str]):
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)
    with mlflow.start_run(run_name="walk_forward_selection"):
        mlflow.log_param("best_model", registry["best_model"])
        mlflow.log_param("cv_mode", registry["selection"]["mode"])
        mlflow.log_param("n_folds", registry["selection"]["n_folds"])
        mlflow.log_param("optuna_trials", registry["selection"]["optuna_trials"])
        mlflow.log_param("n_rows", registry["n_rows"])
        for kind, p in registry["best_params"].items():
            for k, v in p.items():
                mlflow.log_param(f"{kind}.{k}", v)
        mlflow.log_metric("walk_forward_log_loss", registry["walk_forward_log_loss"])
        mlflow.log_metric("walk_forward_accuracy", registry["walk_forward_accuracy"])
        mlflow.log_metric("holdout_log_loss", registry["holdout_log_loss"])
        mlflow.log_metric("holdout_accuracy", registry["holdout_accuracy"])
        for name, m in registry["models"].items():
            mlflow.log_metric(f"wf_log_loss.{name}", m["walk_forward_log_loss"])
        for name, b in registry["baselines"].items():
            if b["walk_forward_log_loss"] is not None:
                mlflow.log_metric(f"wf_log_loss.baseline_{name}", b["walk_forward_log_loss"])
            if b["holdout_log_loss"] is not None:
                mlflow.log_metric(f"holdout_log_loss.baseline_{name}", b["holdout_log_loss"])
        mlflow.log_artifact(paths["registry"])
        mlflow.log_artifact(paths["best"])


def main(
    features_path: Optional[str] = None,
    artifacts_dir: Optional[str] = None,
    n_trials: Optional[int] = None,
    mlflow_tracking_uri: Optional[str] = None,
    seed: int = SEED,
    n_folds: int = N_FOLDS,
    calibration_method: str = CALIBRATION_METHOD,
    df: Optional[pd.DataFrame] = None,
) -> dict:
    """Run walk-forward selection, refit, evaluate on the holdout, save artifacts.

    ``features_path`` / ``artifacts_dir`` / ``n_trials`` default to the module
    constants at call time. Returns the registry dict that was written.
    """
    n_trials = N_TRIALS if n_trials is None else n_trials
    paths = resolve_paths(artifacts_dir)
    if df is None:
        df = load_data(features_path if features_path is not None else FEATURES_PATH)
    else:
        df = sort_chronological(df)

    plan = make_splits(df, n_folds=n_folds)
    dev, holdout = plan.dev, plan.holdout
    print(
        f"Rows: {len(df)}  dev: {len(dev)}  holdout: {len(holdout)}  "
        f"CV mode: {plan.mode}  folds: {len(plan.folds)}"
    )

    # 1. Tune tree models on walk-forward folds (holdout untouched).
    params = {"logistic_regression": {}}
    for kind in ("xgboost", "lgbm"):
        print(f"Running {kind} Optuna search ({n_trials} trials, seed={seed}) ...")
        params[kind] = tune_model(kind, plan.df, plan.folds, n_trials=n_trials, seed=seed)

    # 2. Walk-forward scores for every candidate and baseline.
    print("Walk-forward evaluation ...")
    wf = walk_forward_evaluate(plan, params, calibration_method)
    wf_mean = {n: _mean(r["log_loss"]) for n, r in wf["models"].items()}

    # 3. Select on walk-forward log-loss only.
    best_name = min(CANDIDATES, key=lambda n: (wf_mean[n], n))

    # 4. Refit on all dev data; the holdout is scored exactly once, for reporting.
    final_models = fit_final_models(params, dev, calibration_method)
    X_hold, y_hold = _X(holdout), _y(holdout)
    hold_proba = {n: m.predict_proba(X_hold) for n, m in final_models.items()}
    best_model = final_models[best_name]
    hold_pred = np.argmax(hold_proba[best_name], axis=1)
    hold_cm = confusion_matrix(y_hold, hold_pred, labels=LABELS)

    models_reg = {}
    for name in CANDIDATES:
        models_reg[name] = {
            "walk_forward_log_loss": wf_mean[name],
            "walk_forward_accuracy": _mean(wf["models"][name]["accuracy"]),
            "fold_log_loss": wf["models"][name]["log_loss"],
            "fold_accuracy": wf["models"][name]["accuracy"],
            "holdout_log_loss": log_loss_3(y_hold, hold_proba[name]),
            "holdout_accuracy": accuracy_3(y_hold, hold_proba[name]),
        }

    baselines_reg = {}
    for bname, res in wf["baselines"].items():
        scores, mask = baselines_mod.evaluate_baseline(bname, dev, holdout)
        same_rows = (
            log_loss_3(y_hold[mask], hold_proba[best_name][mask]) if mask.any() else None
        )
        baselines_reg[bname] = {
            "walk_forward_log_loss": _mean(res["log_loss"]),
            "walk_forward_accuracy": _mean(res["accuracy"]),
            "fold_log_loss": res["log_loss"],
            "fold_accuracy": res["accuracy"],
            "fold_n_scored": res["n_scored"],
            "fold_n_total": res["n_total"],
            "holdout_log_loss": scores["log_loss"],
            "holdout_accuracy": scores["accuracy"],
            "holdout_n_scored": scores["n_scored"],
            "holdout_n_total": scores["n_total"],
            "holdout_best_model_log_loss_same_rows": same_rows,
        }

    registry = {
        "best_model": best_name,
        "log_loss": models_reg[best_name]["holdout_log_loss"],
        "walk_forward_log_loss": wf_mean[best_name],
        "walk_forward_accuracy": models_reg[best_name]["walk_forward_accuracy"],
        "holdout_log_loss": models_reg[best_name]["holdout_log_loss"],
        "holdout_accuracy": models_reg[best_name]["holdout_accuracy"],
        "holdout_confusion_matrix": hold_cm.tolist(),
        "selection": {
            "metric": "mean walk-forward log-loss (holdout excluded)",
            "mode": plan.mode,
            "n_folds": len(wf["fold_labels"]),
            "fold_labels": wf["fold_labels"],
            "fold_sizes": wf["fold_sizes"],
            "optuna_trials": n_trials,
            "seed": seed,
            "calibration_method": calibration_method,
            "holdout_includes_partial_season": plan.holdout_partial,
        },
        "models": models_reg,
        "baselines": baselines_reg,
        "best_params": {k: v for k, v in params.items() if v},
        "feature_cols": list(FEATURE_COLS),
        "n_rows": int(len(df)),
        "n_dev_rows": int(len(dev)),
        "n_holdout_rows": int(len(holdout)),
        "data_window": _window(df),
        "dev_window": _window(dev),
        "holdout_window": _window(holdout),
        "leagues": (
            sorted(str(x) for x in df["league"].dropna().unique()) if "league" in df.columns else None
        ),
        "trained_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "git_commit": _git_commit(),
    }
    registry = _jsonable(registry)

    # 5. Persist.
    save_model(final_models["logistic_regression"], paths["baseline"])
    save_model(final_models["xgboost"], paths["xgb"])
    save_model(final_models["lgbm"], paths["lgbm"])
    save_model(final_models["ensemble"], paths["ensemble"])
    save_model(best_model, paths["best"])
    os.makedirs(os.path.dirname(paths["registry"]) or ".", exist_ok=True)
    with open(paths["registry"], "w") as f:
        json.dump(registry, f, indent=2)

    try:
        _log_to_mlflow(registry, paths, mlflow_tracking_uri)
    except Exception as exc:  # tracking must never lose a trained model
        print(f"[warning] MLflow logging failed: {exc!r}")

    print(f"\nBest model: {best_name}  "
          f"(walk-forward log-loss={wf_mean[best_name]:.4f}, "
          f"holdout log-loss={registry['holdout_log_loss']:.4f})")
    print(f"Saved to {paths['best']}\nRegistry written to {paths['registry']}\n")
    print(format_comparison_table(registry))
    return registry


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Train football outcome models (walk-forward).")
    p.add_argument("--features", dest="features_path", default=None)
    p.add_argument("--artifacts-dir", default=None)
    p.add_argument("--n-trials", type=int, default=None)
    p.add_argument("--mlflow-uri", dest="mlflow_tracking_uri", default=None)
    p.add_argument("--seed", type=int, default=SEED)
    return p.parse_args(argv)


if __name__ == "__main__":
    main(**vars(_parse_args()))
