"""Database access for the API (thin on purpose; tests monkeypatch these)."""
import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import List, Optional, Sequence, Tuple

import pandas as pd
from sqlalchemy import and_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.api.serving import HISTORY_COLUMNS
from src.models import Match, Prediction, Team

logger = logging.getLogger(__name__)

PING_TIMEOUT_SECONDS = 2.0


def utcnow() -> dt.datetime:
    """Naive UTC now (the DB convention for every timestamp column)."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def load_history(db: Session) -> pd.DataFrame:
    """Finished matches with only the columns the feature engine needs (one query)."""
    cols = [getattr(Match, c) for c in HISTORY_COLUMNS]
    rows = (
        db.query(*cols)
        .filter(Match.home_goals.isnot(None), Match.away_goals.isnot(None))
        .order_by(Match.date, Match.id)
        .all()
    )
    return pd.DataFrame([tuple(r) for r in rows], columns=list(HISTORY_COLUMNS))


def list_team_names(db: Session) -> List[str]:
    return [name for (name,) in db.query(Team.name).order_by(Team.name).all()]


def persist_predictions(
    db: Session, rows: Sequence[dict], model_version: str, now: Optional[dt.datetime] = None
) -> int:
    """Upsert pre-kickoff predictions; returns the number of rows submitted.

    Each row needs fixture_id, league, home_team, away_team, kickoff (naive UTC),
    home_win, draw, away_win. Only fixtures with ``now < kickoff`` are written,
    and an existing row whose kickoff has passed is never updated. Failures are
    logged and rolled back, never raised.
    """
    now = now or utcnow()
    values = {}
    for r in rows:
        if not now < r["kickoff"]:
            continue
        key = (r["league"], r["kickoff"].date(), r["home_team"], r["away_team"])
        values[key] = {
            "fixture_id": r.get("fixture_id"),
            "league": r["league"],
            "match_day": r["kickoff"].date(),
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "kickoff": r["kickoff"],
            "model_version": model_version,
            "home_win": r["home_win"],
            "draw": r["draw"],
            "away_win": r["away_win"],
            "created_at": now,
            "updated_at": now,
        }
    if not values:
        return 0
    try:
        tbl = Prediction.__table__
        stmt = pg_insert(tbl).values(list(values.values()))
        stmt = stmt.on_conflict_do_update(
            index_elements=["league", "match_day", "home_team", "away_team", "model_version"],
            set_={
                "fixture_id": stmt.excluded.fixture_id,
                "kickoff": stmt.excluded.kickoff,
                "home_win": stmt.excluded.home_win,
                "draw": stmt.excluded.draw,
                "away_win": stmt.excluded.away_win,
                "updated_at": stmt.excluded.updated_at,
            },
            where=tbl.c.kickoff > now,
        )
        db.execute(stmt)
        db.commit()
        return len(values)
    except Exception:
        logger.exception("Could not persist %d predictions", len(values))
        try:
            db.rollback()
        except Exception:  # pragma: no cover - best effort
            pass
        return 0


def fetch_settled(
    db: Session,
    *,
    league: Optional[str],
    weeks: int,
    model_version: Optional[str],
    now: Optional[dt.datetime] = None,
) -> Tuple[int, List[dict]]:
    """``(n_predictions, settled_rows)`` for predictions with kickoff in the window.

    A prediction is settled when the matches table holds a result for the same
    natural key (league, match_day, home_team, away_team) AND the prediction was
    last written strictly before kickoff.
    """
    now = now or utcnow()
    cutoff = now - dt.timedelta(weeks=weeks)
    q = (
        db.query(Prediction, Match.result, Match.odds_home, Match.odds_draw, Match.odds_away)
        .outerjoin(
            Match,
            and_(
                Match.league == Prediction.league,
                Match.match_day == Prediction.match_day,
                Match.home_team == Prediction.home_team,
                Match.away_team == Prediction.away_team,
            ),
        )
        .filter(Prediction.kickoff >= cutoff)
    )
    if league:
        q = q.filter(Prediction.league == league)
    if model_version:
        q = q.filter(Prediction.model_version == model_version)
    fetched = q.all()

    settled: List[dict] = []
    for pred, result, o_h, o_d, o_a in fetched:
        if result not in ("H", "D", "A") or not pred.updated_at < pred.kickoff:
            continue
        settled.append({
            "fixture_id": pred.fixture_id,
            "league": pred.league,
            "kickoff": pred.kickoff,
            "home_team": pred.home_team,
            "away_team": pred.away_team,
            "home_win": pred.home_win,
            "draw": pred.draw,
            "away_win": pred.away_win,
            "result": result,
            "odds_home": o_h, "odds_draw": o_d, "odds_away": o_a,
        })
    return len(fetched), settled


def class_counts_before(db: Session, day: dt.date, league: Optional[str] = None) -> List[int]:
    """H / D / A counts of finished matches strictly before ``day``."""
    from sqlalchemy import func

    q = db.query(Match.result, func.count()).filter(
        Match.match_day < day, Match.result.in_(("H", "D", "A"))
    )
    if league:
        q = q.filter(Match.league == league)
    counts = {res: n for res, n in q.group_by(Match.result).all()}
    return [int(counts.get(k, 0)) for k in ("H", "D", "A")]


def ping_db(timeout: float = PING_TIMEOUT_SECONDS) -> str:
    """``"ok"``, ``"down"`` or ``"unconfigured"`` (no DATABASE_URL). Bounded by ``timeout``."""
    from src import database

    if database.engine is None:
        return "unconfigured"

    def _ping() -> None:
        with database.engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        pool.submit(_ping).result(timeout=timeout)
        return "ok"
    except FutureTimeout:
        logger.warning("DB ping timed out after %.1fs", timeout)
        return "down"
    except Exception as exc:
        logger.warning("DB ping failed: %s", exc)
        return "down"
    finally:
        pool.shutdown(wait=False)
