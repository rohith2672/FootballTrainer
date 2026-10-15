"""football-data.co.uk historical CSV download + parsing.

Covers the five domestic leagues (E0/SP1/I1/D1/F1).  Rows are returned as
plain dicts that go through ``src.ingestion.upsert.upsert_matches``.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from src.ingestion.seasons import couk_season_code
from src.ingestion.team_names import to_canonical

logger = logging.getLogger(__name__)

# co.uk division code -> football-data.org competition code
COUK_DIVISIONS = {"E0": "PL", "SP1": "PD", "I1": "SA", "D1": "BL1", "F1": "FL1"}
LEAGUE_TO_DIV = {v: k for k, v in COUK_DIVISIONS.items()}

COUK_BASE_URL = "https://www.football-data.co.uk/mmz4281"
DEFAULT_RAW_DIR = Path("data") / "raw" / "couk"
DOWNLOAD_TIMEOUT = 30
USER_AGENT = "FootballTrainer/1.0 (research project)"

_UK = ZoneInfo("Europe/London")

# (odds_source, home col, draw col, away col) in order of preference.
# Closing prices first (best benchmark), then pre-closing, then bookmaker fallbacks.
ODDS_CHAIN: list[tuple[str, str, str, str]] = [
    ("pinnacle_close", "PSCH", "PSCD", "PSCA"),
    ("avg_close", "AvgCH", "AvgCD", "AvgCA"),
    ("b365_close", "B365CH", "B365CD", "B365CA"),
    ("pinnacle", "PSH", "PSD", "PSA"),
    ("avg", "AvgH", "AvgD", "AvgA"),
    ("bbavg", "BbAvH", "BbAvD", "BbAvA"),
    ("b365", "B365H", "B365D", "B365A"),
]


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------

def couk_url(season_start: int, div: str) -> str:
    return f"{COUK_BASE_URL}/{couk_season_code(season_start)}/{div}.csv"


def couk_path(season_start: int, div: str, dest_dir: str | Path = DEFAULT_RAW_DIR) -> Path:
    return Path(dest_dir) / f"{div}_{couk_season_code(season_start)}.csv"


def download_season(season_start: int, div: str, dest_dir: str | Path = DEFAULT_RAW_DIR) -> Path:
    """Download one season/division CSV to ``{dest_dir}/{div}_{code}.csv``.

    Raises requests.HTTPError for non-2xx responses (e.g. 404 for a season that
    has not started yet).  The file is only written after a successful response.
    """
    url = couk_url(season_start, div)
    response = requests.get(url, timeout=DOWNLOAD_TIMEOUT, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    if not response.content.strip():
        raise ValueError(f"Empty response from {url}")

    dest = couk_path(season_start, div, dest_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)
    logger.info("Downloaded %s -> %s (%d bytes)", url, dest, len(response.content))
    return dest


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def _clean(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    text = str(value).strip()
    return text or None


def _read_rows(source) -> list[dict[str, str | None]]:
    """Normalise a path / bytes / DataFrame into a list of {column: str|None}."""
    if hasattr(source, "to_dict") and hasattr(source, "columns"):  # DataFrame
        records = source.to_dict(orient="records")
        return [{str(k).strip(): _clean(v) for k, v in rec.items()} for rec in records]

    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    else:
        raw = Path(source).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    text = text.lstrip("﻿")

    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        return []
    # Drop trailing blank header cells (trailing commas).
    while header and not header[-1]:
        header.pop()

    rows = []
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue  # blank / all-comma line
        cells = cells[: len(header)] + [""] * (len(header) - len(cells))
        rows.append({h: _clean(c) for h, c in zip(header, cells) if h})
    return rows


def _parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean(value)
    if not text:
        return None
    text = text.split(" ")[0]
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(value) -> tuple[int, int] | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parts = text.split(":")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None


def _to_int(value) -> int | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _to_float(value) -> float | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def select_odds(row: dict) -> tuple[float | None, float | None, float | None, str | None]:
    """First fully-present triple (all > 1.0) along ODDS_CHAIN, else all None."""
    for source, h_col, d_col, a_col in ODDS_CHAIN:
        h, d, a = _to_float(row.get(h_col)), _to_float(row.get(d_col)), _to_float(row.get(a_col))
        if h is not None and d is not None and a is not None and h > 1.0 and d > 1.0 and a > 1.0:
            return h, d, a, source
    return None, None, None, None


def _result_from(ftr: str | None, hg: int, ag: int) -> str:
    if ftr and ftr.strip().upper() in ("H", "D", "A"):
        return ftr.strip().upper()
    return "H" if hg > ag else ("D" if hg == ag else "A")


def parse_couk_csv(path_or_df, div: str, season_start: int) -> list[dict]:
    """Parse a football-data.co.uk CSV (path, bytes or DataFrame) into match dicts.

    Rows without a date, team names or full-time goals (unplayed / junk /
    trailing empty rows) are skipped.  Kickoff times are UK local time and are
    converted to UTC; without a Time column ``date`` is midnight UTC of the
    listed day and ``kickoff`` is None.
    """
    if div not in COUK_DIVISIONS:
        raise ValueError(f"Unknown football-data.co.uk division: {div!r}")
    league = COUK_DIVISIONS[div]

    records: list[dict] = []
    for row in _read_rows(path_or_df):
        day = _parse_date(row.get("Date"))
        home_raw, away_raw = row.get("HomeTeam"), row.get("AwayTeam")
        hg, ag = _to_int(row.get("FTHG")), _to_int(row.get("FTAG"))
        if day is None or not home_raw or not away_raw or hg is None or ag is None:
            continue

        hm = _parse_time(row.get("Time"))
        if hm is not None:
            local = datetime(day.year, day.month, day.day, hm[0], hm[1], tzinfo=_UK)
            kickoff = local.astimezone(timezone.utc)
            when = kickoff
        else:
            kickoff = None
            when = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)

        odds_h, odds_d, odds_a, odds_source = select_odds(row)
        records.append(
            {
                "league": league,
                "season": season_start,
                "date": when,
                "kickoff": kickoff,
                "match_day": when.date(),
                "home_team": to_canonical(home_raw, league),
                "away_team": to_canonical(away_raw, league),
                "home_goals": hg,
                "away_goals": ag,
                "result": _result_from(row.get("FTR"), hg, ag),
                "home_shots": _to_int(row.get("HS")),
                "away_shots": _to_int(row.get("AS")),
                "home_shots_on_target": _to_int(row.get("HST")),
                "away_shots_on_target": _to_int(row.get("AST")),
                "odds_home": odds_h,
                "odds_draw": odds_d,
                "odds_away": odds_a,
                "odds_source": odds_source,
                "provider_id": None,
                "source": "couk",
            }
        )
    return records


def raw_team_names(path_or_df) -> set[str]:
    """Distinct raw team names in a CSV (for reviewing unmapped_names)."""
    names: set[str] = set()
    for row in _read_rows(path_or_df):
        for col in ("HomeTeam", "AwayTeam"):
            if row.get(col):
                names.add(row[col])
    return names
