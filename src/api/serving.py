"""Pure serving logic: fixtures -> engine features -> probabilities + explanation.

There is exactly one feature code path, ``src.features.engine.compute_features``:
the finished history is loaded once, upcoming fixtures are appended as rows with
null goals (the engine emits their features and writes nothing to its state), and
the fixture rows are picked out by position. No database, HTTP or FastAPI imports
here, so everything is unit-testable.

No silent fallback: a fixture that cannot be predicted (team without history,
insufficient features, model error) is returned with ``prediction_available``
false, null probabilities and a ``reason``.
"""
import datetime as dt
import logging
import math
import warnings
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.features.columns import FEATURE_COLS, FEATURE_LABELS
from src.features.engine import compute_features
from src.ingestion.seasons import season_start_year

logger = logging.getLogger(__name__)

HISTORY_COLUMNS = (
    "id", "date", "kickoff", "season", "league", "home_team", "away_team",
    "home_goals", "away_goals",
    "home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target",
)
REFERENCE_WINDOW = 2000          # recent historical rows used for the occlusion reference
TOP_FACTORS = 5
UPCOMING_STATUSES = ("SCHEDULED", "TIMED")
# Features that must be finite for a prediction to be meaningful.
_REQUIRED_FINITE = ("home_elo", "away_elo", "home_form_pts_pg", "away_form_pts_pg")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def num(x, ndigits: Optional[int] = None) -> Optional[float]:
    """Native float, or None for None / NaN / inf (JSON-safe)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return round(v, ndigits) if ndigits is not None else v


def utc_iso(ts: dt.datetime) -> str:
    """Naive-UTC datetime -> ``2026-10-18T14:00:00Z``."""
    return ts.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def parse_fixtures(raw_by_league: Dict[str, dict]) -> List[dict]:
    """football-data.org ``matches`` payloads -> fixture dicts (naive UTC kickoff).

    Skips fixtures without both team names (TBD knockout ties), without a
    parseable ``utcDate`` or with a non-upcoming status. Sorted by kickoff.
    """
    fixtures: List[dict] = []
    for league, payload in raw_by_league.items():
        for m in (payload or {}).get("matches", []) or []:
            status = m.get("status")
            if status is not None and status not in UPCOMING_STATUSES:
                continue
            home = (m.get("homeTeam") or {}).get("name")
            away = (m.get("awayTeam") or {}).get("name")
            raw_date = m.get("utcDate")
            if not home or not away or not raw_date:
                continue
            try:
                kickoff = _parse_utc(raw_date)
            except ValueError:
                continue
            fixtures.append({
                "fixture_id": m.get("id"),
                "league": league,
                "home_team": home,
                "away_team": away,
                "kickoff": kickoff,
            })
    fixtures.sort(key=lambda f: (f["kickoff"], f["league"], f["home_team"], f["away_team"]))
    return fixtures


def build_fixture_frame(fixtures: List[dict]) -> pd.DataFrame:
    """Engine input rows for fixtures: naive-UTC date == kickoff, null goals."""
    kickoffs = pd.to_datetime([f["kickoff"] for f in fixtures])
    return pd.DataFrame({
        "id": np.nan,
        "date": kickoffs,
        "kickoff": kickoffs,
        "season": [season_start_year(f["kickoff"]) for f in fixtures],
        "league": [f["league"] for f in fixtures],
        "home_team": [f["home_team"] for f in fixtures],
        "away_team": [f["away_team"] for f in fixtures],
        "home_goals": np.nan,
        "away_goals": np.nan,
    })


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
def compute_fixture_features(
    history: pd.DataFrame, fixtures: List[dict]
) -> Tuple[pd.DataFrame, np.ndarray]:
    """One ``compute_features`` call over history + fixtures.

    Returns ``(fixture_features, reference)``: the FEATURE_COLS rows of the
    fixtures (same order as ``fixtures``) and the per-feature median of the
    most recent ``REFERENCE_WINDOW`` historical rows (NaN where undefined).
    """
    n_hist = len(history)
    combined = pd.concat([history, build_fixture_frame(fixtures)], ignore_index=True)
    feats = compute_features(combined)

    hist_feats = feats.iloc[:n_hist]
    if n_hist:
        order = np.argsort(pd.to_datetime(history["date"]).to_numpy(), kind="stable")
        recent = hist_feats.iloc[order[-REFERENCE_WINDOW:]].to_numpy(dtype=float)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)  # all-NaN columns
            reference = np.nanmedian(recent, axis=0)
    else:
        reference = np.full(len(FEATURE_COLS), np.nan)
    return feats.iloc[n_hist:].reset_index(drop=True), reference


def history_teams(history: pd.DataFrame) -> set:
    if history.empty:
        return set()
    return set(history["home_team"]).union(history["away_team"])


def details_from_row(row: pd.Series) -> dict:
    def side(p: str) -> dict:
        form_n = num(row[f"{p}_form_n"])
        days = num(row[f"{p}_days_since_last"], 1)
        return {
            "elo": num(row[f"{p}_elo"], 1),
            "form_pts_pg": num(row[f"{p}_form_pts_pg"], 2),
            "goals_for_avg": num(row[f"{p}_form_goals_scored_avg"], 2),
            "goals_against_avg": num(row[f"{p}_form_goals_conceded_avg"], 2),
            "shots_for_avg": num(row[f"{p}_shots_for_avg"], 1),
            "days_since_last": days,
            "form_n": int(form_n) if form_n is not None else None,
        }

    h2h_n = num(row["h2h_n"])
    return {
        "home": side("home"),
        "away": side("away"),
        "h2h": {
            "n": int(h2h_n) if h2h_n is not None else None,
            "home_pts_rate": num(row["h2h_home_pts_rate"], 3),
        },
    }


# ---------------------------------------------------------------------------
# Model calls
# ---------------------------------------------------------------------------
def predict_rows(model, X: np.ndarray) -> np.ndarray:
    """``predict_proba`` -> finite (n, 3) rows summing to one, or ValueError."""
    p = np.asarray(model.predict_proba(X), dtype=float)
    if p.ndim != 2 or p.shape != (len(X), 3):
        raise ValueError(f"model returned probabilities of shape {p.shape}, expected ({len(X)}, 3)")
    if not np.isfinite(p).all() or (p < 0).any():
        raise ValueError("model returned non-finite or negative probabilities")
    total = p.sum(axis=1, keepdims=True)
    if (total <= 0).any():
        raise ValueError("model returned a zero probability row")
    return p / total


def explain_and_predict(
    model, row: np.ndarray, reference: np.ndarray, top_n: int = TOP_FACTORS
) -> Tuple[np.ndarray, List[dict]]:
    """Probabilities for one feature row plus model-agnostic occlusion factors.

    The row and its 45 single-feature occlusions (feature -> reference value)
    go through ONE ``predict_proba`` call. contribution = p_pred(original) -
    p_pred(occluded) for the predicted class: positive means the feature's
    actual value pushes toward the predicted outcome relative to a typical match.
    """
    n = len(FEATURE_COLS)
    X = np.tile(row, (n + 1, 1))
    for j in range(n):
        X[j + 1, j] = reference[j]
    proba = predict_rows(model, X)
    base = proba[0]
    k = int(np.argmax(base))
    contrib = base[k] - proba[1:, k]

    factors: List[dict] = []
    for j in np.argsort(-np.abs(contrib), kind="stable"):
        if len(factors) >= top_n:
            break
        c = float(contrib[j])
        if c == 0.0 or not math.isfinite(c):
            continue
        name = FEATURE_COLS[j]
        factors.append({
            "feature": name,
            "label": FEATURE_LABELS.get(name, name),
            "value": num(row[j], 4),
            "contribution": round(c, 4),
        })
    return base, factors


# ---------------------------------------------------------------------------
# Fixture -> result
# ---------------------------------------------------------------------------
def _unavailable(fx: dict, reason: str, details: Optional[dict] = None) -> dict:
    return {
        **fx,
        "home_win": None, "draw": None, "away_win": None,
        "prediction_available": False, "is_fallback": True, "reason": reason,
        "top_factors": [], "details": details,
    }


def _missing_history_reason(fx: dict, row: pd.Series, known: set) -> Optional[str]:
    missing = []
    for team, form_n in ((fx["home_team"], row["home_form_n"]), (fx["away_team"], row["away_form_n"])):
        if team not in known or not (form_n > 0):
            missing.append(team)
    if not missing:
        return None
    return "No match history for " + " and ".join(dict.fromkeys(missing))


def predict_fixtures(model, history: pd.DataFrame, fixtures: List[dict]) -> List[dict]:
    """Predict every fixture; same order as ``fixtures``.

    Raises only if the feature engine itself fails (a server error); per-fixture
    model failures are reported as ``prediction_available=False``.
    """
    if not fixtures:
        return []
    feats, reference = compute_fixture_features(history, fixtures)
    known = history_teams(history)

    results: List[dict] = []
    for i, fx in enumerate(fixtures):
        row = feats.iloc[i]
        reason = _missing_history_reason(fx, row, known)
        if reason is None and not all(math.isfinite(row[c]) for c in _REQUIRED_FINITE):
            reason = "Insufficient feature data"
        if reason is not None:
            results.append(_unavailable(fx, reason))
            continue
        try:
            probs, factors = explain_and_predict(model, row.to_numpy(dtype=float), reference)
        except Exception:
            logger.exception(
                "Prediction failed for %s vs %s (%s)", fx["home_team"], fx["away_team"], fx["league"]
            )
            results.append(_unavailable(fx, "Prediction error"))
            continue
        results.append({
            **fx,
            "home_win": float(probs[0]), "draw": float(probs[1]), "away_win": float(probs[2]),
            "prediction_available": True, "is_fallback": False, "reason": None,
            "top_factors": factors, "details": details_from_row(row),
        })
    return results


def infer_league(history: pd.DataFrame, team: str) -> Optional[str]:
    """League for /predict (which takes no league): the team's latest domestic
    competition, else its latest competition of any kind; None if unseen."""
    mask = (history["home_team"] == team) | (history["away_team"] == team)
    sub = history.loc[mask]
    if sub.empty:
        return None
    sub = sub.assign(_d=pd.to_datetime(sub["date"])).sort_values("_d", kind="stable")
    domestic = sub.loc[sub["league"] != "CL", "league"]
    return str((domestic if len(domestic) else sub["league"]).iloc[-1])
