"""Probability scoring helpers: overall and per-group (e.g. per-league) metrics.

All functions take labels ``y`` in {0: home win, 1: draw, 2: away win} and an
``(n, 3)`` probability array. Dependency-light (numpy / pandas only).
"""
from typing import Dict, Optional

import numpy as np
import pandas as pd

from src.model.baselines import accuracy_3, log_loss_3

LABELS = (0, 1, 2)


def brier_3(y, probs) -> float:
    """Multiclass Brier score: mean over rows of sum_k (p_k - 1[y = k])^2 (0 best, 2 worst)."""
    y = np.asarray(y, dtype=int)
    probs = np.asarray(probs, dtype=float)
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y)), y] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


def draw_prediction_rate(probs) -> float:
    """Share of rows whose argmax is a draw."""
    probs = np.asarray(probs, dtype=float)
    return float(np.mean(np.argmax(probs, axis=1) == 1)) if len(probs) else float("nan")


def confusion_3(y, probs) -> list:
    """3x3 confusion matrix (rows = actual, columns = argmax prediction) as nested lists."""
    y = np.asarray(y, dtype=int)
    pred = np.argmax(np.asarray(probs, dtype=float), axis=1)
    cm = np.zeros((3, 3), dtype=int)
    np.add.at(cm, (y, pred), 1)
    return cm.tolist()


def score_all(y, probs) -> Dict[str, float]:
    """n, log_loss, brier, accuracy, draw_pred_rate, mean predicted draw probability."""
    y = np.asarray(y, dtype=int)
    probs = np.asarray(probs, dtype=float)
    if len(y) == 0:
        return {"n": 0, "log_loss": None, "brier": None, "accuracy": None,
                "draw_pred_rate": None, "mean_draw_prob": None}
    return {
        "n": int(len(y)),
        "log_loss": log_loss_3(y, probs),
        "brier": brier_3(y, probs),
        "accuracy": accuracy_3(y, probs),
        "draw_pred_rate": draw_prediction_rate(probs),
        "mean_draw_prob": float(np.mean(probs[:, 1])),
    }


def score_by_group(y, probs, groups, min_rows: int = 1) -> Dict[str, Dict[str, float]]:
    """``score_all`` per distinct value of ``groups`` (e.g. the league column).

    Groups with fewer than ``min_rows`` rows are left out. Keys are strings,
    sorted, so the result is JSON-ready.
    """
    y = np.asarray(y, dtype=int)
    probs = np.asarray(probs, dtype=float)
    groups = pd.Series(np.asarray(groups, dtype=object)).astype(str).to_numpy()
    out: Dict[str, Dict[str, float]] = {}
    for g in sorted(set(groups.tolist())):
        mask = groups == g
        if mask.sum() >= min_rows:
            out[g] = score_all(y[mask], probs[mask])
    return out


def per_league_scores(df: pd.DataFrame, probs, league_col: str = "league",
                      target_col: str = "target") -> Optional[Dict[str, Dict[str, float]]]:
    """Per-league scores of ``probs`` (rows aligned with ``df``); None without a league column."""
    if league_col not in df.columns:
        return None
    return score_by_group(df[target_col].to_numpy(dtype=int), probs, df[league_col].to_numpy())
