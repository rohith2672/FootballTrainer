"""Upcoming-fixture pipeline shared by ``GET /upcoming`` and the team profile.

upstream fixtures (cached ``api_client``) -> filters -> cached history ->
``serving.predict_fixtures`` -> optional pre-kickoff persistence. No FastAPI
imports, so the routers can reuse it without importing ``src.api.main``.
"""
import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence, Tuple

from src.api import history_cache, serving, store
from src.ingestion import api_client

logger = logging.getLogger(__name__)


def fetch_upstream_fixtures(leagues: List[str]) -> tuple:
    """Fetch the leagues concurrently (cached). Returns ``(payloads, failed)``."""
    payloads: Dict[str, dict] = {}
    failed: List[str] = []

    def one(code: str):
        return code, api_client.get_upcoming_matches_cached(code)

    with ThreadPoolExecutor(max_workers=max(1, len(leagues))) as pool:
        futures = {code: pool.submit(one, code) for code in leagues}
        for code, fut in futures.items():
            try:
                payloads[code] = fut.result()[1]
            except Exception as exc:
                logger.error("Failed to fetch upcoming matches for %s: %s", code, exc)
                failed.append(code)
    return payloads, failed


def predict_upcoming(
    model_state,
    db,
    leagues: Sequence[str],
    *,
    team: Optional[str] = None,
    day_from: Optional[dt.date] = None,
    day_to: Optional[dt.date] = None,
    limit: Optional[int] = None,
    persist: bool = True,
) -> Tuple[List[dict], List[str]]:
    """``(results, failed_leagues)`` for upcoming fixtures, sorted by kickoff.

    Filters (dates, ``team`` = home or away) are applied before ``limit``.
    History is loaded only when at least one fixture remains.
    """
    leagues = list(leagues)
    payloads, failed = fetch_upstream_fixtures(leagues)
    fixtures = serving.parse_fixtures(payloads)
    if day_from:
        fixtures = [f for f in fixtures if f["kickoff"].date() >= day_from]
    if day_to:
        fixtures = [f for f in fixtures if f["kickoff"].date() <= day_to]
    if team is not None:
        fixtures = [f for f in fixtures if team in (f["home_team"], f["away_team"])]
    if limit is not None:
        fixtures = fixtures[:limit]
    if not fixtures:
        return [], failed

    history = history_cache.get_history(db)      # one (cached) query for all fixtures
    results = serving.predict_fixtures(model_state.model, history, fixtures)

    if persist:
        now = store.utcnow()
        to_store = [r for r in results if r["prediction_available"] and now < r["kickoff"]]
        if to_store:
            try:
                store.persist_predictions(db, to_store, model_state.version, now)
            except Exception:
                logger.exception("Persisting predictions failed; continuing")
    return results, failed


def fixture_payload(r: dict, model_version: str) -> dict:
    """One ``Fixture`` item of the API contract."""
    return {
        "fixture_id": r["fixture_id"], "league": r["league"],
        "home_team": r["home_team"], "away_team": r["away_team"],
        "date": r["kickoff"].date().isoformat(), "kickoff": serving.utc_iso(r["kickoff"]),
        "home_win": r["home_win"], "draw": r["draw"], "away_win": r["away_win"],
        "prediction_available": r["prediction_available"], "is_fallback": r["is_fallback"],
        "reason": r["reason"], "model_version": model_version,
        "top_factors": r["top_factors"], "details": r["details"],
    }
