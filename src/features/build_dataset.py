"""Build the training feature table from finished matches (all leagues).

Runs the single point-in-time engine (``src.features.engine``) over every
finished match, maps the result to a target and writes ``features.csv``.
"""
import argparse
import os
import re
from typing import Optional

import pandas as pd

from src.features.columns import FEATURE_COLS
from src.features.engine import compute_features
from src.ingestion.seasons import season_start_year

OUTPUT_PATH = os.path.join("data", "processed", "features.csv")

RESULT_MAP = {"H": 0, "D": 1, "A": 2}
LABELS = {0: "Home Win", 1: "Draw", 2: "Away Win"}

ODDS_COLS = ["odds_home", "odds_draw", "odds_away"]
ID_COLS = ["match_id", "date", "league", "season", "home_team", "away_team", "target"]
OUTPUT_COLS = ID_COLS + ODDS_COLS + FEATURE_COLS

# Match model attribute -> frame column (explicit, so mocks / partial rows are not guessed at).
_MATCH_ATTRS = [
    "id", "date", "kickoff", "season", "league", "home_team", "away_team",
    "home_goals", "away_goals", "result",
    "home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target",
    "odds_home", "odds_draw", "odds_away",
]
DOMESTIC_LEAGUES = ("PL", "PD", "SA", "BL1", "FL1")
CL_LEAGUE = "CL"
DEFAULT_BURN_IN_SEASONS = 1


def load_matches(db_session) -> pd.DataFrame:
    """Finished matches (all leagues) as a DataFrame with the engine's input columns."""
    from src.models import Match  # local import: keep the engine / tests free of the ORM

    raw = (
        db_session.query(Match)
        .filter(Match.home_goals != None, Match.away_goals != None)  # noqa: E711
        .order_by(Match.date)
        .all()
    )
    return pd.DataFrame([{a: getattr(m, a, None) for a in _MATCH_ATTRS} for m in raw], columns=_MATCH_ATTRS)


_COUK_FILE_RE = re.compile(r"^(?P<div>[A-Z0-9]+)_(?P<code>\d{4})\.csv$")


def load_matches_from_csv(csv_dir: str) -> pd.DataFrame:
    """Finished matches from football-data.co.uk CSVs, in the same shape as ``load_matches``.

    Files are named ``{div}_{YYZZ}.csv`` (e.g. ``E0_1516.csv``); division and season
    start year come from the file name. Only finished matches are returned (the
    parser skips rows without full-time goals), unique on league + match day +
    home + away. ``id`` is a synthetic sequence (CSV rows have no provider id);
    ``date`` is naive UTC.
    """
    from src.ingestion.csv_history import COUK_DIVISIONS, parse_couk_csv

    files = []
    for name in sorted(os.listdir(csv_dir)):
        m = _COUK_FILE_RE.match(name)
        if m and m.group("div") in COUK_DIVISIONS:
            files.append((m.group("div"), 2000 + int(m.group("code")[:2]), os.path.join(csv_dir, name)))
    if not files:
        raise FileNotFoundError(f"No football-data.co.uk CSVs ({{div}}_{{YYZZ}}.csv) found in {csv_dir}")

    records = []
    for div, season_start, path in files:
        records.extend(parse_couk_csv(path, div, season_start))
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=_MATCH_ATTRS)
    df = df.drop_duplicates(subset=["league", "match_day", "home_team", "away_team"], keep="first")
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None)
    df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True).dt.tz_localize(None)
    df = df.sort_values(["date", "league", "home_team", "away_team"], kind="mergesort").reset_index(drop=True)
    df["id"] = range(1, len(df) + 1)
    return df[_MATCH_ATTRS]


def _target(df: pd.DataFrame) -> pd.Series:
    """H/D/A -> 0/1/2, derived from goals when ``result`` is missing."""
    hg = pd.to_numeric(df["home_goals"], errors="coerce")
    ag = pd.to_numeric(df["away_goals"], errors="coerce")
    from_goals = pd.Series(1, index=df.index).mask(hg > ag, 0).mask(hg < ag, 2)
    from_result = df["result"].map(RESULT_MAP) if "result" in df.columns else pd.Series(float("nan"), index=df.index)
    return from_result.where(from_result.notna(), from_goals).astype(int)


def burn_in_mask(df: pd.DataFrame, burn_in_seasons: int = DEFAULT_BURN_IN_SEASONS) -> pd.Series:
    """True for rows to KEEP. Each domestic league's first ``burn_in_seasons`` seasons
    are dropped (Elo / form not warmed up); CL shares the earliest domestic cutoff."""
    if burn_in_seasons <= 0 or df.empty:
        return pd.Series(True, index=df.index)
    first = df.groupby("league")["season"].min()
    cutoff = {lg: int(s) + burn_in_seasons for lg, s in first.items()}   # keep season >= cutoff
    dom = [cutoff[lg] for lg in cutoff if lg != CL_LEAGUE]
    if CL_LEAGUE in cutoff and dom:
        cutoff[CL_LEAGUE] = min(dom)
    keep_from = df["league"].map(cutoff)
    return df["season"] >= keep_from


def build_features(matches: pd.DataFrame, burn_in_seasons: int = DEFAULT_BURN_IN_SEASONS) -> pd.DataFrame:
    """Engine features + ids + target (+ odds) for a frame of finished matches."""
    matches = matches.reset_index(drop=True)
    dates = pd.to_datetime(matches["date"])
    season = pd.to_numeric(matches["season"], errors="coerce") if "season" in matches.columns else pd.Series(float("nan"), index=matches.index)
    matches["season"] = season.where(season.notna(), dates.map(season_start_year).astype(float)).astype(int)
    feats = compute_features(matches)

    out = pd.DataFrame({
        "match_id": matches["id"] if "id" in matches.columns else matches["match_id"],
        "date": pd.to_datetime(matches["date"]),
        "league": matches["league"],
        "season": matches["season"],
        "home_team": matches["home_team"],
        "away_team": matches["away_team"],
        "target": _target(matches),
    })
    for c in ODDS_COLS:
        out[c] = pd.to_numeric(matches[c], errors="coerce") if c in matches.columns else float("nan")
    out = pd.concat([out, feats], axis=1)

    out = out[burn_in_mask(out, burn_in_seasons)]
    out = out.sort_values(["date", "league", "home_team", "away_team", "match_id"], kind="mergesort")
    return out[OUTPUT_COLS].reset_index(drop=True)


def build_dataset(
    db_session=None,
    burn_in_seasons: int = DEFAULT_BURN_IN_SEASONS,
    matches: Optional[pd.DataFrame] = None,
    csv_dir: Optional[str] = None,
) -> pd.DataFrame:
    """Build the feature table from ``matches``, a CSV directory, or the DB (in that order)."""
    if matches is None and csv_dir is not None:
        matches = load_matches_from_csv(csv_dir)
    if matches is None:
        close_session = db_session is None
        if db_session is None:
            from src.database import SessionLocal

            db_session = SessionLocal()
        try:
            matches = load_matches(db_session)
        finally:
            if close_session:
                db_session.close()
    return build_features(matches, burn_in_seasons=burn_in_seasons)


def summarize(df: pd.DataFrame) -> str:
    total = len(df)
    lines = [f"Rows: {total}", "", "Class distribution:"]
    dist = df["target"].value_counts().sort_index()
    for code, count in dist.items():
        lines.append(f"  {LABELS[code]} ({code}): {count} ({count / max(total, 1) * 100:.1f}%)")
    lines += ["", "Rows per league:"]
    for lg, count in df["league"].value_counts().sort_index().items():
        lines.append(f"  {lg}: {count}")
    return "\n".join(lines)


def main(
    output_path: str = OUTPUT_PATH,
    db_session=None,
    burn_in_seasons: int = DEFAULT_BURN_IN_SEASONS,
    csv_dir: Optional[str] = None,
) -> pd.DataFrame:
    df = build_dataset(db_session=db_session, burn_in_seasons=burn_in_seasons, csv_dir=csv_dir)
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # Uniform timestamp format: a mix of midnight-only and timed values makes
    # ``read_csv(parse_dates=["date"])`` leave the column as strings.
    df.to_csv(output_path, index=False, date_format="%Y-%m-%d %H:%M:%S")
    print(f"Saved {len(df)} rows to {output_path}\n")
    print(summarize(df))
    return df


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Build the training feature table.")
    p.add_argument("--from-csv", dest="csv_dir", default=None,
                   help="directory of football-data.co.uk CSVs (no database needed)")
    p.add_argument("--output", dest="output_path", default=OUTPUT_PATH)
    p.add_argument("--burn-in-seasons", type=int, default=DEFAULT_BURN_IN_SEASONS)
    return p.parse_args(argv)


if __name__ == "__main__":
    a = _parse_args()
    main(output_path=a.output_path, burn_in_seasons=a.burn_in_seasons, csv_dir=a.csv_dir)
