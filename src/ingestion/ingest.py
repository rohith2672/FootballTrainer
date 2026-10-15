"""Match ingestion: football-data.co.uk history + football-data.org results.

Usage (from the repository root)::

    python -m src.ingestion.ingest                        # --source all, default leagues/seasons
    python -m src.ingestion.ingest --source couk          # history CSVs only (5 domestic leagues)
    python -m src.ingestion.ingest --source fdorg --leagues CL --seasons 2024 2025
    python -m src.ingestion.ingest --source couk --leagues PL PD --seasons 2022 2023 2024

``--seasons`` are season START years (2023 = 2023/24).  Defaults:

* couk: the 5 domestic leagues, last 10 completed seasons plus the current one;
* fdorg: CL for the current and previous season, and the current season for
  all six leagues (PL PD SA BL1 FL1 CL).  Only FINISHED matches are stored.

Both sources write through the same canonical-team-name + upsert path
(``src.ingestion.upsert``), so re-runs are idempotent and shots/odds from
football-data.co.uk merge onto football-data.org rows (and vice versa).
football-data.org names are already canonical and are stored as given.
"""

from __future__ import annotations

import argparse
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.ingestion import csv_history
from src.ingestion.api_client import get_matches, get_teams
from src.ingestion.seasons import season_start_year
from src.ingestion.team_names import unmapped_names
from src.ingestion.upsert import teams_from_records, upsert_matches, upsert_teams

logger = logging.getLogger(__name__)

LEAGUE = "PL"
DOMESTIC_LEAGUES = ["PL", "PD", "SA", "BL1", "FL1"]
ALL_LEAGUES = DOMESTIC_LEAGUES + ["CL"]
COUK_HISTORY_COMPLETED_SEASONS = 10
_DOWNLOAD_PAUSE_SECONDS = 1.0


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def current_season(today: datetime | None = None) -> int:
    today = today or datetime.now(timezone.utc)
    return season_start_year(today)


def default_couk_seasons(today: datetime | None = None) -> list[int]:
    cur = current_season(today)
    return list(range(cur - COUK_HISTORY_COMPLETED_SEASONS, cur + 1))


def default_fdorg_seasons(league: str, today: datetime | None = None) -> list[int]:
    cur = current_season(today)
    return [cur - 1, cur] if league == "CL" else [cur]


@contextmanager
def _session_scope(session=None):
    """Yield a session; commit on success. Closes it only if created here."""
    owned = session is None
    if owned:
        from src.database import SessionLocal

        if SessionLocal is None:
            raise EnvironmentError("DATABASE_URL is not set - copy .env.example to .env")
        session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if owned:
            session.close()


def _parse_result(home_goals: int | None, away_goals: int | None) -> str | None:
    if home_goals is None or away_goals is None:
        return None
    if home_goals > away_goals:
        return "H"
    if home_goals == away_goals:
        return "D"
    return "A"


def _regulation_goals(score: dict) -> tuple[int | None, int | None]:
    """90-minute goals when the API reports them separately, else fullTime.

    Knockout ties decided in extra time / penalties would otherwise be recorded
    with the post-90-minute score and a misleading H/A instead of D.
    """
    if score.get("duration") in ("EXTRA_TIME", "PENALTY_SHOOTOUT"):
        regular = score.get("regularTime") or {}
        if regular.get("home") is not None and regular.get("away") is not None:
            return regular["home"], regular["away"]
    full = score.get("fullTime") or {}
    return full.get("home"), full.get("away")


def fdorg_match_records(payload: dict, league: str, season: int) -> list[dict]:
    """Convert a football-data.org /matches payload to upsert records (FINISHED only)."""
    records = []
    for m in payload.get("matches", []):
        if m.get("status") != "FINISHED":
            continue
        home_goals, away_goals = _regulation_goals(m.get("score") or {})
        if home_goals is None or away_goals is None:
            continue
        kickoff = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        records.append(
            {
                "provider_id": m["id"],
                "league": league,
                "season": season,
                "date": kickoff,
                "kickoff": kickoff,
                "match_day": kickoff.astimezone(timezone.utc).date(),
                # football-data.org names ARE the canonical names.
                "home_team": m["homeTeam"]["name"],
                "away_team": m["awayTeam"]["name"],
                "home_goals": home_goals,
                "away_goals": away_goals,
                "result": _parse_result(home_goals, away_goals),
                "source": "fdorg",
            }
        )
    return records


def _store(session, records: list[dict]) -> dict:
    counts = upsert_matches(session, records)
    domestic, other = teams_from_records(records)
    upsert_teams(session, domestic, overwrite_league=True)
    upsert_teams(session, other, overwrite_league=False)
    return counts


# --------------------------------------------------------------------------
# football-data.org
# --------------------------------------------------------------------------

def ingest_teams(league: str = LEAGUE, season: int | None = None, session=None) -> None:
    """Upsert the club list from football-data.org for one competition."""
    data = get_teams(league, season=season if season is not None else current_season())
    names = {t["name"]: league for t in data.get("teams", []) if t.get("name")}
    if not names:
        return
    with _session_scope(session) as s:
        upsert_teams(s, names, overwrite_league=(league != "CL"))
    logger.info("Teams upserted - count=%d league=%s", len(names), league)


def ingest_matches(league: str = LEAGUE, seasons: list[int] | None = None, session=None) -> dict:
    """Ingest FINISHED football-data.org matches for one league.

    Returns fetched/inserted/updated/unchanged counts; ``skipped`` is kept as an
    alias of ``unchanged`` for backward compatibility.
    """
    if seasons is None:
        seasons = default_fdorg_seasons(league)

    totals = {"fetched": 0, "inserted": 0, "updated": 0, "unchanged": 0}
    with _session_scope(session) as s:
        for season in seasons:
            records = fdorg_match_records(get_matches(league, season), league, season)
            totals["fetched"] += len(records)
            counts = _store(s, records)
            for key in ("inserted", "updated", "unchanged"):
                totals[key] += counts[key]

    totals["skipped"] = totals["unchanged"]
    logger.info(
        "football-data.org %s complete - fetched=%d inserted=%d updated=%d unchanged=%d",
        league, totals["fetched"], totals["inserted"], totals["updated"], totals["unchanged"],
    )
    return totals


def ingest_fdorg(leagues: list[str], seasons: list[int] | None = None, session=None) -> dict:
    totals = {"fetched": 0, "inserted": 0, "updated": 0, "unchanged": 0, "errors": 0}
    for league in leagues:
        league_seasons = seasons if seasons else default_fdorg_seasons(league)
        for season in league_seasons:
            try:
                result = ingest_matches(league, [season], session=session)
            except requests.RequestException as exc:
                logger.warning("football-data.org %s %s failed: %s", league, season, exc)
                totals["errors"] += 1
                continue
            for key in ("fetched", "inserted", "updated", "unchanged"):
                totals[key] += result[key]
    return totals


# --------------------------------------------------------------------------
# football-data.co.uk
# --------------------------------------------------------------------------

def ingest_couk(
    leagues: list[str] | None = None,
    seasons: list[int] | None = None,
    raw_dir: str | Path = csv_history.DEFAULT_RAW_DIR,
    download: bool = True,
    force_download: bool = False,
    session=None,
) -> dict:
    """Download (if needed) and upsert football-data.co.uk CSVs.

    Existing CSVs are reused unless ``force_download``; the current season's file
    is always re-downloaded because it changes weekly.
    """
    leagues = [lg for lg in (leagues or DOMESTIC_LEAGUES) if lg in csv_history.LEAGUE_TO_DIV]
    seasons = seasons or default_couk_seasons()
    cur = current_season()

    totals = {"files": 0, "rows": 0, "inserted": 0, "updated": 0, "unchanged": 0, "errors": 0}
    with _session_scope(session) as s:
        for league in leagues:
            div = csv_history.LEAGUE_TO_DIV[league]
            for season in seasons:
                path = csv_history.couk_path(season, div, raw_dir)
                if download and (force_download or season == cur or not path.exists()):
                    try:
                        csv_history.download_season(season, div, raw_dir)
                    except (requests.RequestException, ValueError) as exc:
                        logger.warning("Download failed %s %s: %s", div, season, exc)
                        totals["errors"] += 1
                    time.sleep(_DOWNLOAD_PAUSE_SECONDS)
                if not path.exists():
                    continue

                records = csv_history.parse_couk_csv(path, div, season)
                review = unmapped_names(csv_history.raw_team_names(path), league)
                if review:
                    logger.warning(
                        "Team names not in the explicit map (%s) in %s: %s",
                        "fallback = resolved by normalisation, check it", path.name, review,
                    )

                counts = _store(s, records)
                totals["files"] += 1
                totals["rows"] += len(records)
                for key in ("inserted", "updated", "unchanged"):
                    totals[key] += counts[key]
                logger.info("couk %s %s: rows=%d %s", div, season, len(records), counts)
    return totals


# --------------------------------------------------------------------------
# Orchestration / CLI
# --------------------------------------------------------------------------

def run(
    source: str = "all",
    leagues: list[str] | None = None,
    seasons: list[int] | None = None,
    raw_dir: str | Path = csv_history.DEFAULT_RAW_DIR,
    download: bool = True,
    force_download: bool = False,
    session=None,
) -> dict:
    """Run one or both sources; co.uk first, then football-data.org (adds provider ids/kickoffs)."""
    if source not in ("couk", "fdorg", "all"):
        raise ValueError(f"Unknown source: {source!r}")
    leagues = leagues or (DOMESTIC_LEAGUES if source == "couk" else ALL_LEAGUES)

    summary: dict = {}
    if source in ("couk", "all"):
        summary["couk"] = ingest_couk(
            leagues, seasons, raw_dir, download=download, force_download=force_download, session=session
        )
    if source in ("fdorg", "all"):
        summary["fdorg"] = ingest_fdorg(leagues, seasons, session=session)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest football match data into PostgreSQL.")
    parser.add_argument("--source", choices=["couk", "fdorg", "all"], default="all")
    parser.add_argument("--leagues", nargs="+", choices=ALL_LEAGUES, default=None,
                        help="default: all six (couk uses only the 5 domestic ones)")
    parser.add_argument("--seasons", nargs="+", type=int, default=None,
                        help="season start years, e.g. 2023 = 2023/24")
    parser.add_argument("--raw-dir", default=str(csv_history.DEFAULT_RAW_DIR))
    parser.add_argument("--no-download", action="store_true",
                        help="couk: only use CSVs already in --raw-dir")
    parser.add_argument("--force-download", action="store_true",
                        help="couk: re-download CSVs even if present")
    return parser


def main(argv: list[str] | None = None) -> dict:
    args = _build_parser().parse_args(argv)
    summary = run(
        source=args.source,
        leagues=args.leagues,
        seasons=args.seasons,
        raw_dir=args.raw_dir,
        download=not args.no_download,
        force_download=args.force_download,
    )
    logger.info("Ingestion summary: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
