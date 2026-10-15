"""Pluggable baselines to benchmark models against.

A baseline is a function ``(train_df, eval_df) -> np.ndarray`` of shape
``(len(eval_df), 3)`` giving probabilities for (home, draw, away). Rows the
baseline cannot score (for example missing odds) are returned as NaN and are
skipped when scoring; the number of scored rows is reported as coverage.

Register a baseline with ``@register_baseline("name")``; ``elo`` (below) is
the reference example. Anything registered before training starts is evaluated automatically on the
same walk-forward folds and on the holdout.
"""
from typing import Callable, Dict, Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

TARGET_COL = "target"
ODDS_COLS = ("odds_home", "odds_draw", "odds_away")
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
# Odds -> probabilities
# ---------------------------------------------------------------------------
def odds_matrix(df: pd.DataFrame) -> np.ndarray:
    """(n, 3) decimal odds; NaN where any odd is missing or not > 1."""
    cols = [pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float) for c in ODDS_COLS]
    odds = np.column_stack(cols)
    bad = ~np.isfinite(odds).all(axis=1) | (odds <= 1.0).any(axis=1)
    odds[bad] = np.nan
    return odds


def implied_proportional(odds: np.ndarray) -> np.ndarray:
    """Remove the overround proportionally (normalise inverse odds)."""
    inv = 1.0 / odds
    return inv / inv.sum(axis=1, keepdims=True)


def implied_shin(odds: np.ndarray, n_iter: int = 80) -> np.ndarray:
    """Shin's method: solve for the insider-trading share z per row.

    p_i(z) = (sqrt(z^2 + 4(1-z) pi_i^2 / B) - z) / (2(1-z)), with pi_i = 1/odds_i
    and B = sum(pi); z is found by bisection so that sum(p_i) = 1. Rows with
    no overround (B <= 1) fall back to the proportional method.
    """
    pi = 1.0 / odds
    booksum = pi.sum(axis=1, keepdims=True)

    def probs(z):
        z = z[:, None]
        return (np.sqrt(z**2 + 4.0 * (1.0 - z) * pi**2 / booksum) - z) / (2.0 * (1.0 - z))

    lo = np.zeros(len(odds))
    hi = np.full(len(odds), 1.0 - 1e-9)
    for _ in range(n_iter):
        mid = (lo + hi) / 2.0
        too_big = probs(mid).sum(axis=1) > 1.0  # sum decreases in z
        lo = np.where(too_big, mid, lo)
        hi = np.where(too_big, hi, mid)
    p = probs((lo + hi) / 2.0)
    p = p / p.sum(axis=1, keepdims=True)
    no_margin = (booksum[:, 0] <= 1.0)
    if no_margin.any():
        p[no_margin] = implied_proportional(odds[no_margin])
    return p


def _odds_available(df: pd.DataFrame) -> bool:
    if not all(c in df.columns for c in ODDS_COLS):
        return False
    return bool(np.isfinite(odds_matrix(df)).all(axis=1).any())


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


def _bookmaker(eval_df: pd.DataFrame, method) -> np.ndarray:
    out = np.full((len(eval_df), 3), np.nan)
    if not all(c in eval_df.columns for c in ODDS_COLS):
        return out
    odds = odds_matrix(eval_df)
    ok = np.isfinite(odds).all(axis=1)
    if ok.any():
        out[ok] = method(odds[ok])
    return out


@register_baseline("bookmaker", requires_columns=ODDS_COLS)
def bookmaker(train_df: pd.DataFrame, eval_df: pd.DataFrame) -> np.ndarray:
    """Closing odds with proportional overround removal (NaN if odds missing)."""
    return _bookmaker(eval_df, implied_proportional)


@register_baseline("bookmaker_shin", requires_columns=ODDS_COLS)
def bookmaker_shin(train_df: pd.DataFrame, eval_df: pd.DataFrame) -> np.ndarray:
    """Closing odds de-margined with Shin's method (NaN if odds missing)."""
    return _bookmaker(eval_df, implied_shin)


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------
def available_baselines(df: pd.DataFrame):
    """Names of registered baselines usable on ``df`` (odds baselines need odds)."""
    names = []
    for name in BASELINES:
        req = _REQUIRED_COLUMNS.get(name, ())
        if req and not all(c in df.columns for c in req):
            continue
        if req and set(req) != set(ODDS_COLS) and any(df[c].isna().all() for c in req):
            continue
        if set(req) == set(ODDS_COLS) and not _odds_available(df):
            continue
        names.append(name)
    return names


def evaluate_baseline(name: str, train_df: pd.DataFrame, eval_df: pd.DataFrame):
    """Score one baseline. Returns ``(scores, mask)`` as in ``score_probs``."""
    probs = BASELINES[name](train_df, eval_df)
    return score_probs(eval_df[TARGET_COL].to_numpy(), probs)
