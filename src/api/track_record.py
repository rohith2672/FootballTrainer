"""Live track-record metrics (pure functions, no DB / FastAPI imports).

Input rows are predictions that were stored BEFORE kickoff and have since been
settled against a known result; see ``store.fetch_settled``.
"""
import datetime as dt
import math
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from src.api.serving import num
from src.model.baselines import (
    ODDS_COLS,
    accuracy_3,
    implied_proportional,
    log_loss_3,
    odds_matrix,
)

RESULT_CODE = {"H": 0, "D": 1, "A": 2}
RECENT_N = 20


def _ll(y, p) -> Optional[float]:
    return num(log_loss_3(y, p), 4) if len(y) else None


def _acc(y, p) -> Optional[float]:
    return num(accuracy_3(y, p), 4) if len(y) else None


def _bookmaker_log_loss(sub: pd.DataFrame) -> tuple:
    """(log-loss, n) of overround-free bookmaker probabilities on rows with odds."""
    odds = odds_matrix(sub)
    ok = np.isfinite(odds).all(axis=1)
    if not ok.any():
        return None, 0
    y = sub["y"].to_numpy()[ok]
    return num(log_loss_3(y, implied_proportional(odds[ok])), 4), int(ok.sum())


def _frame(rows: Sequence[dict]) -> pd.DataFrame:
    df = pd.DataFrame(list(rows))
    for c in ODDS_COLS:
        if c not in df.columns:
            df[c] = np.nan
    df["y"] = df["result"].map(RESULT_CODE).astype(int)
    df["kickoff"] = pd.to_datetime(df["kickoff"])
    return df


def _probs(df: pd.DataFrame) -> np.ndarray:
    return df[["home_win", "draw", "away_win"]].to_numpy(dtype=float)


def week_start(ts) -> dt.date:
    d = pd.Timestamp(ts).date()
    return d - dt.timedelta(days=d.weekday())


def backtest_block(registry: Optional[dict]) -> Optional[dict]:
    """Holdout numbers from the training registry (None if the registry has none)."""
    if not registry or registry.get("holdout_log_loss") is None:
        return None
    window = registry.get("holdout_window") or {}
    lo, hi = window.get("min_date"), window.get("max_date")
    baselines = {
        name: num((b or {}).get("holdout_log_loss"), 4)
        for name, b in (registry.get("baselines") or {}).items()
    }
    return {
        "source": "model_registry.json holdout",
        "best_model": registry.get("best_model"),
        "holdout_window": [str(lo)[:10], str(hi)[:10]] if lo and hi else None,
        "holdout_log_loss": num(registry.get("holdout_log_loss"), 4),
        "holdout_accuracy": num(registry.get("holdout_accuracy"), 4),
        "baselines": baselines,
    }


def compute_track_record(
    rows: Sequence[dict],
    *,
    n_predictions: int,
    class_counts: Optional[Sequence[int]],
    model_version: Optional[str],
    registry: Optional[dict],
) -> dict:
    """Assemble the /track-record payload.

    ``rows`` are settled predictions (dicts with fixture_id, league, kickoff,
    home_team, away_team, home_win, draw, away_win, result H/D/A and optional
    odds_home/odds_draw/odds_away). ``class_counts`` are H/D/A counts of
    matches played before the prediction window (None/empty -> no class_prior).
    """
    out: dict = {
        "model_version": model_version,
        "n_predictions": int(n_predictions),
        "n_settled": len(rows),
        "overall": {"log_loss": None, "accuracy": None, "brier": None},
        "baselines": {
            "bookmaker": {"log_loss": None, "n": 0},
            "class_prior": {"log_loss": None, "n": 0},
            "uniform": {"log_loss": None, "n": 0},
        },
        "by_league": [],
        "timeline": [],
        "recent": [],
        "backtest": backtest_block(registry),
    }
    if not rows:
        return out

    df = _frame(rows)
    y, p = df["y"].to_numpy(), _probs(df)
    onehot = np.eye(3)[y]
    out["overall"] = {
        "log_loss": _ll(y, p),
        "accuracy": _acc(y, p),
        "brier": num(np.mean(np.sum((p - onehot) ** 2, axis=1)), 4),
    }

    bm_ll, bm_n = _bookmaker_log_loss(df)
    baselines = out["baselines"]
    baselines["bookmaker"] = {"log_loss": bm_ll, "n": bm_n}
    baselines["uniform"] = {"log_loss": num(math.log(3.0), 4), "n": len(df)}
    if class_counts is not None and sum(class_counts) > 0:
        prior = (np.asarray(class_counts, dtype=float) + 1.0)
        prior = prior / prior.sum()
        baselines["class_prior"] = {"log_loss": _ll(y, np.tile(prior, (len(y), 1))), "n": len(df)}

    for league, sub in sorted(df.groupby("league"), key=lambda kv: kv[0]):
        ys, ps = sub["y"].to_numpy(), _probs(sub)
        out["by_league"].append({
            "league": league, "n": len(sub),
            "log_loss": _ll(ys, ps), "accuracy": _acc(ys, ps),
            "bookmaker_log_loss": _bookmaker_log_loss(sub)[0],
        })

    df["week"] = df["kickoff"].map(week_start)
    for week, sub in sorted(df.groupby("week"), key=lambda kv: kv[0]):
        ys, ps = sub["y"].to_numpy(), _probs(sub)
        out["timeline"].append({
            "week_start": week.isoformat(), "n": len(sub),
            "log_loss": _ll(ys, ps), "accuracy": _acc(ys, ps),
            "bookmaker_log_loss": _bookmaker_log_loss(sub)[0],
        })

    recent = df.sort_values("kickoff", ascending=False, kind="stable").head(RECENT_N)
    for _, r in recent.iterrows():
        probs = [r["home_win"], r["draw"], r["away_win"]]
        fid = r.get("fixture_id")
        out["recent"].append({
            "fixture_id": int(fid) if fid is not None and fid == fid else None,
            "league": r["league"],
            "date": r["kickoff"].date().isoformat(),
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "home_win": num(r["home_win"], 4),
            "draw": num(r["draw"], 4),
            "away_win": num(r["away_win"], 4),
            "result": r["result"],
            "correct": bool(int(np.argmax(probs)) == int(r["y"])),
        })
    return out
