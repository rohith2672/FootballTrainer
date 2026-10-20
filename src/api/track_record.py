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
from src.model.baselines import accuracy_3, log_loss_3

RESULT_CODE = {"H": 0, "D": 1, "A": 2}
RECENT_N = 20
# Bookmaker/market baselines were retired (user decision, 2026-10-20). Older
# registries still carry them, so they are dropped when the backtest is read.
RETIRED_BASELINE_MARKER = "bookmaker"


def _ll(y, p) -> Optional[float]:
    return num(log_loss_3(y, p), 4) if len(y) else None


def _acc(y, p) -> Optional[float]:
    return num(accuracy_3(y, p), 4) if len(y) else None


def _frame(rows: Sequence[dict]) -> pd.DataFrame:
    df = pd.DataFrame(list(rows))
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
        if RETIRED_BASELINE_MARKER not in str(name).lower()
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
    home_team, away_team, home_win, draw, away_win and result H/D/A).
    ``class_counts`` are H/D/A counts of
    matches played before the prediction window (None/empty -> no class_prior).
    """
    out: dict = {
        "model_version": model_version,
        "n_predictions": int(n_predictions),
        "n_settled": len(rows),
        "overall": {"log_loss": None, "accuracy": None, "brier": None},
        "baselines": {
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

    baselines = out["baselines"]
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
        })

    df["week"] = df["kickoff"].map(week_start)
    for week, sub in sorted(df.groupby("week"), key=lambda kv: kv[0]):
        ys, ps = sub["y"].to_numpy(), _probs(sub)
        out["timeline"].append({
            "week_start": week.isoformat(), "n": len(sub),
            "log_loss": _ll(ys, ps), "accuracy": _acc(ys, ps),
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
