"""Pluggable baselines to benchmark models against.

A baseline is a function ``(train_df, eval_df) -> np.ndarray`` of shape
``(len(eval_df), 3)`` giving probabilities for (home, draw, away). Rows the
baseline cannot score (for example a missing ``elo_diff``) are returned as NaN
and are skipped when scoring; the number of scored rows is reported as coverage.

Betting odds are deliberately neither a baseline nor a model input (user
decision, 2026-10-20); odds columns may exist in the data but are ignored here.

Register a baseline with ``@register_baseline("name")``; ``elo`` (below) is
the reference example. Anything registered before training starts is evaluated automatically on the
same walk-forward folds and on the holdout.
"""
from typing import Callable, Dict, Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

TARGET_COL = "target"
_LL_EPS = 1e-15

BaselineFn = Callable[[pd.DataFrame, pd.DataFrame], np.ndarray]
BASELINES: Dict[str, BaselineFn] = {}
_REQUIRED_COLUMNS: Dict[str, Sequence[str]] = {}


def register_baseline(name: str, requires_columns: Sequence[str] = ()):
    """Decorator registering a baseline under ``name``."""

    def deco(fn: BaselineFn) -> BaselineFn:
        BASELINES[name] = fn
        _REQUIRED_COLUMNS[name] = tuple(requires_columns)
        return fn

    return deco


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------
def log_loss_3(y, probs) -> float:
    """Multiclass log-loss with clipping; ``y`` holds labels 0..2."""
    y = np.asarray(y, dtype=int)
    probs = np.asarray(probs, dtype=float)
    p = np.clip(probs[np.arange(len(y)), y], _LL_EPS, 1.0)
    return float(-np.mean(np.log(p)))


def accuracy_3(y, probs) -> float:
    return float(np.mean(np.argmax(np.asarray(probs), axis=1) == np.asarray(y)))


def score_probs(y, probs):
    """Score probabilities, skipping rows that are NaN / not a distribution.

    Returns ``(scores, mask)``; ``scores`` has log_loss, accuracy (None when
    nothing could be scored), n_scored and n_total.
    """
    y = np.asarray(y, dtype=int)
    probs = np.asarray(probs, dtype=float)
    mask = np.isfinite(probs).all(axis=1) & (probs.sum(axis=1) > 0)
    n_scored = int(mask.sum())
    scores = {
        "log_loss": log_loss_3(y[mask], probs[mask]) if n_scored else None,
        "accuracy": accuracy_3(y[mask], probs[mask]) if n_scored else None,
        "n_scored": n_scored,
        "n_total": int(len(y)),
    }
    return scores, mask


# ---------------------------------------------------------------------------
# Built-in baselines
# ---------------------------------------------------------------------------
@register_baseline("uniform")
def uniform(train_df: pd.DataFrame, eval_df: pd.DataFrame) -> np.ndarray:
    """1/3 each; log-loss = ln 3."""
    return np.full((len(eval_df), 3), 1.0 / 3.0)


@register_baseline("class_prior")
def class_prior(train_df: pd.DataFrame, eval_df: pd.DataFrame) -> np.ndarray:
    """Training-set class frequencies (Laplace-smoothed) for every match."""
    counts = np.bincount(train_df[TARGET_COL].astype(int), minlength=3)[:3].astype(float)
    counts = counts + 1.0
    prior = counts / counts.sum()
    return np.tile(prior, (len(eval_df), 1))


@register_baseline("elo", requires_columns=("elo_diff",))
def elo(train_df: pd.DataFrame, eval_df: pd.DataFrame) -> np.ndarray:
    """Multinomial logistic regression on ``elo_diff`` alone (NaN if unavailable).

    ``elo_diff`` is computed point-in-time by the feature engine, so fitting on
    the train slice and predicting the eval slice is leakage-free.
    """
    out = np.full((len(eval_df), 3), np.nan)
    if "elo_diff" not in train_df.columns or "elo_diff" not in eval_df.columns:
        return out
    x_tr = pd.to_numeric(train_df["elo_diff"], errors="coerce").to_numpy(dtype=float)
    y_tr = train_df[TARGET_COL].to_numpy()
    ok_tr = np.isfinite(x_tr)
    if ok_tr.sum() == 0 or len(np.unique(y_tr[ok_tr])) < 2:
        return out
    model = LogisticRegression(max_iter=1000)
    model.fit(x_tr[ok_tr].reshape(-1, 1) / 100.0, y_tr[ok_tr].astype(int))
    x_ev = pd.to_numeric(eval_df["elo_diff"], errors="coerce").to_numpy(dtype=float)
    ok_ev = np.isfinite(x_ev)
    if ok_ev.any():
        proba = np.full((int(ok_ev.sum()), 3), 1e-3)   # classes absent from train stay near 0
        proba[:, model.classes_.astype(int)] = model.predict_proba(x_ev[ok_ev].reshape(-1, 1) / 100.0)
        out[ok_ev] = proba / proba.sum(axis=1, keepdims=True)
    return out


POISSON_COLUMNS = ("pois_p_home", "pois_p_draw", "pois_p_away")


@register_baseline("poisson", requires_columns=POISSON_COLUMNS)
def poisson(train_df: pd.DataFrame, eval_df: pd.DataFrame) -> np.ndarray:
    """The engine's online Poisson / Dixon-Coles probabilities as they are (no fitting).

    They are point-in-time engine features, so using them directly is leakage-free.
    """
    if not all(c in eval_df.columns for c in POISSON_COLUMNS):
        return np.full((len(eval_df), 3), np.nan)
    p = eval_df[list(POISSON_COLUMNS)].to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return p / p.sum(axis=1, keepdims=True)   # already sums to 1; guards rounding / synthetic data


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------
def available_baselines(df: pd.DataFrame):
    """Names of registered baselines usable on ``df``.

    A baseline is skipped when a required column is missing or entirely NaN.
    """
    names = []
    for name in BASELINES:
        req = _REQUIRED_COLUMNS.get(name, ())
        if req and (not all(c in df.columns for c in req) or any(df[c].isna().all() for c in req)):
            continue
        names.append(name)
    return names


def evaluate_baseline(name: str, train_df: pd.DataFrame, eval_df: pd.DataFrame):
    """Score one baseline. Returns ``(scores, mask)`` as in ``score_probs``."""
    probs = BASELINES[name](train_df, eval_df)
    return score_probs(eval_df[TARGET_COL].to_numpy(), probs)
