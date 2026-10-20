"""Team analysis endpoints (contract: docs/api_contract.md, "Team analysis").

Read-only views over finished matches: team index, profile, match list, Elo
history and head-to-head. They need only the database; the profile's
``next_fixture`` additionally uses the fixture source and model when present
and degrades to ``"unavailable"`` otherwise. Statistics live in the pure
``src.api.team_stats`` module; history comes from ``src.api.history_cache``.
"""
import datetime as dt
import logging
from typing import Optional, Tuple

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.api import history_cache, store, team_stats, upcoming
from src.database import get_db
from src.ingestion import api_client

logger = logging.getLogger(__name__)

router = APIRouter()

HISTORY_UNAVAILABLE = "Match history unavailable (database error)"
ELO_HISTORY_DAYS = 365
VENUES = ("all", "home", "away")


def today() -> dt.date:
    """UTC calendar day (patched by tests)."""
    return dt.datetime.now(dt.timezone.utc).date()


def _parse_day(name: str, value: Optional[str]) -> Optional[dt.date]:
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} must be YYYY-MM-DD format")


def _load(db: Session) -> Tuple[list, pd.DataFrame, team_stats.HistoryIndex]:
    """``(teams table rows, enriched history, its cached index)``; DB errors -> 503."""
    try:
        rows = store.list_teams(db)
        index = history_cache.get_index(db)
        return rows, index.enriched, index
    except SQLAlchemyError as exc:
        logger.error("Team endpoints: database error: %s", exc)
        raise HTTPException(status_code=503, detail=HISTORY_UNAVAILABLE)


def _require_team(name: str, table_rows, enriched, index=None) -> Optional[str]:
    """404 unless known; returns the team's ``teams.league`` (or None)."""
    table = dict(table_rows)
    if name not in table and name not in team_stats.known_teams(enriched, index):
        raise HTTPException(status_code=404, detail=f"Team not found: {name}")
    return table.get(name)


def _league(name: str, table_league: Optional[str], enriched) -> Optional[str]:
    tm = team_stats.team_matches(enriched, name)
    return team_stats.resolve_league(table_league, team_stats.latest_domestic_league(tm))


def next_fixture(request: Request, db: Session, team: str, league: Optional[str], as_of) -> Tuple[Optional[dict], str]:
    """``(fixture, status)`` from the /upcoming pipeline; never raises.

    ``"unavailable"`` when ``as_of`` is given, the model or API key is missing,
    or any needed league request failed; ``"none"`` when every source answered
    and no fixture of the team is scheduled. Nothing is persisted (read-only).

    Pipeline outcomes are cached per ``(team, league, model version)`` in
    ``history_cache`` (``ok`` / ``none`` for ``FIXTURE_TTL_SECONDS``,
    ``unavailable`` for ``FIXTURE_UNAVAILABLE_TTL_SECONDS``); the cheap
    ``as_of`` / model / key checks are never cached.
    """
    if as_of is not None:
        return None, "unavailable"
    state = getattr(request.app.state, "model_state", None)
    if state is None or not state.ready or not api_client.get_api_key():
        return None, "unavailable"
    key = (team, league, state.version)
    hit = history_cache.fixture_get(key)
    if hit is not None:
        return hit
    gen = history_cache.fixture_generation()
    result = _compute_next_fixture(state, db, team, league)
    ttl = (history_cache.FIXTURE_UNAVAILABLE_TTL_SECONDS if result[1] == "unavailable"
           else history_cache.FIXTURE_TTL_SECONDS)
    history_cache.fixture_put(key, result, ttl, gen)
    return result


def _compute_next_fixture(state, db: Session, team: str, league: Optional[str]) -> Tuple[Optional[dict], str]:
    """Runs the /upcoming pipeline (upstream fetch + features + model); never raises."""
    leagues = [league, "CL"] if league else ["CL"]
    try:
        results, failed = upcoming.predict_upcoming(state, db, leagues, team=team, limit=1, persist=False)
    except Exception:
        logger.exception("next_fixture failed for %s", team)
        return None, "unavailable"
    if failed:
        return None, "unavailable"
    if not results:
        return None, "none"
    return upcoming.fixture_payload(results[0], state.version), "ok"


# Declared before /teams/{name} so "index" is not captured as a team name.
@router.get("/teams/index")
def teams_index(db: Session = Depends(get_db)):
    table_rows, enriched, index = _load(db)
    return team_stats.team_index(table_rows, enriched, index)


@router.get("/teams/{name}")
def team_profile(
    name: str,
    request: Request,
    as_of: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    as_of_day = _parse_day("as_of", as_of)
    table_rows, enriched, index = _load(db)
    table_league = _require_team(name, table_rows, enriched, index)
    league = _league(name, table_league, team_stats.before_day(enriched, as_of_day))
    body = team_stats.build_profile(enriched, name, league, as_of=as_of_day, today=today(), index=index)
    body["next_fixture"], body["next_fixture_status"] = next_fixture(request, db, name, league, as_of_day)
    return body


@router.get("/teams/{name}/matches")
def team_match_list(
    name: str,
    limit: int = Query(20, ge=1, le=100),
    venue: str = Query("all"),
    db: Session = Depends(get_db),
):
    if venue not in VENUES:
        raise HTTPException(status_code=422, detail="venue must be one of all, home, away")
    table_rows, enriched, index = _load(db)
    _require_team(name, table_rows, enriched, index)
    return team_stats.match_list(team_stats.team_matches(enriched, name), limit=limit, venue=venue)


@router.get("/teams/{name}/elo-history")
def team_elo_history(
    name: str,
    since: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    since_day = _parse_day("since", since) or (today() - dt.timedelta(days=ELO_HISTORY_DAYS))
    table_rows, enriched, index = _load(db)
    _require_team(name, table_rows, enriched, index)
    return {"team": name, "points": team_stats.elo_points(team_stats.team_matches(enriched, name), since_day)}


@router.get("/h2h")
def head_to_head(
    a: str = Query(...),
    b: str = Query(...),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if a == b:
        raise HTTPException(status_code=422, detail="a and b must differ")
    table_rows, enriched, index = _load(db)
    _require_team(a, table_rows, enriched, index)
    _require_team(b, table_rows, enriched, index)
    return team_stats.h2h_summary(enriched, a, b, limit=limit)
