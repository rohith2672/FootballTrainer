"""Persistence / settlement queries: SQL shape with a fake session, real behaviour
against PostgreSQL when TEST_DATABASE_URL is set (skipped otherwise)."""
import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from src.api import store
from src.models import Match, Prediction
from tests._pgtest import db_session  # noqa: F401  (fixture)

NOW = dt.datetime(2026, 10, 15, 12, 0)


def _row(i=1, kickoff=None, home="Arsenal FC", away="Chelsea FC", league="PL"):
    return {
        "fixture_id": 500 + i, "league": league, "home_team": home, "away_team": away,
        "kickoff": kickoff or NOW + dt.timedelta(days=2),
        "home_win": 0.5, "draw": 0.3, "away_win": 0.2,
    }


def test_persist_skips_kicked_off_fixtures():
    db = MagicMock()
    assert store.persist_predictions(db, [_row(kickoff=NOW - dt.timedelta(minutes=1))], "v1", NOW) == 0
    db.execute.assert_not_called()


def test_persist_statement_is_guarded_upsert():
    db = MagicMock()
    n = store.persist_predictions(db, [_row(1), _row(1), _row(2, home="Everton FC")], "v1", NOW)
    assert n == 2                                    # duplicate natural key collapsed
    stmt = db.execute.call_args[0][0]
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (league, match_day, home_team, away_team, model_version) DO UPDATE" in sql
    assert "predictions.kickoff >" in sql             # never update a row whose kickoff has passed
    assert "created_at=" not in sql.replace(" ", "")  # created_at is never overwritten
    db.commit.assert_called_once()


def test_persist_failure_is_logged_and_rolled_back(caplog):
    db = MagicMock()
    db.execute.side_effect = RuntimeError("db gone")
    assert store.persist_predictions(db, [_row()], "v1", NOW) == 0
    db.rollback.assert_called_once()
    assert "Could not persist" in caplog.text


def test_fetch_settled_requires_result_and_pre_kickoff_write():
    ko = NOW - dt.timedelta(days=1)

    def pred(updated_at, **kw):
        return SimpleNamespace(
            fixture_id=1, league="PL", kickoff=ko, home_team="A", away_team="B",
            home_win=0.5, draw=0.3, away_win=0.2, updated_at=updated_at, **kw,
        )

    rows = [
        (pred(ko - dt.timedelta(hours=3)), "H", 2.0, 3.0, 4.0),     # settled
        (pred(ko - dt.timedelta(hours=3)), None, None, None, None),   # no result yet
        (pred(ko + dt.timedelta(minutes=1)), "D", None, None, None),  # written after kickoff
    ]
    q = MagicMock()
    q.outerjoin.return_value = q
    q.filter.return_value = q
    q.all.return_value = rows
    db = MagicMock()
    db.query.return_value = q
    n, settled = store.fetch_settled(db, league="PL", weeks=26, model_version="v1", now=NOW)
    assert n == 3 and len(settled) == 1
    assert settled[0]["result"] == "H" and settled[0]["odds_home"] == 2.0


def test_ping_db_unconfigured(monkeypatch):
    from src import database

    monkeypatch.setattr(database, "engine", None)
    assert store.ping_db() == "unconfigured"


def test_ping_db_failure_is_down(monkeypatch):
    from src import database

    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("refused")
    monkeypatch.setattr(database, "engine", engine)
    assert store.ping_db(timeout=1.0) == "down"


# ---------------------------------------------------------------------------
# PostgreSQL-backed (skipped without TEST_DATABASE_URL)
# ---------------------------------------------------------------------------
def test_pg_persist_upsert_and_settlement(db_session):
    now = dt.datetime(2026, 10, 15, 12, 0)
    ko = dt.datetime(2026, 10, 17, 15, 0)
    assert store.persist_predictions(db_session, [_row(1, kickoff=ko)], "v1", now) == 1

    # latest pre-kickoff prediction wins
    changed = {**_row(1, kickoff=ko), "home_win": 0.6, "draw": 0.25, "away_win": 0.15}
    store.persist_predictions(db_session, [changed], "v1", now + dt.timedelta(hours=1))
    rows = db_session.query(Prediction).all()
    assert len(rows) == 1 and rows[0].home_win == 0.6
    assert rows[0].created_at == now and rows[0].updated_at == now + dt.timedelta(hours=1)

    # once the stored kickoff has passed the row is never touched, even if the
    # same fixture is re-submitted with a (later) kickoff on the same day
    late = {**changed, "home_win": 0.1, "draw": 0.1, "away_win": 0.8,
            "kickoff": ko + dt.timedelta(minutes=30)}
    store.persist_predictions(db_session, [late], "v1", ko + dt.timedelta(minutes=10))
    db_session.expire_all()
    assert db_session.query(Prediction).one().home_win == 0.6

    # settle: result known + prediction written before kickoff
    db_session.add(Match(
        provider_id=501, date=ko, kickoff=ko, match_day=ko.date(), home_team="Arsenal FC",
        away_team="Chelsea FC", home_goals=2, away_goals=1, result="H", season=2026,
        league="PL", odds_home=2.0, odds_draw=3.5, odds_away=4.0,
    ))
    db_session.commit()
    n, settled = store.fetch_settled(
        db_session, league=None, weeks=4, model_version="v1", now=ko + dt.timedelta(hours=3)
    )
    assert n == 1 and len(settled) == 1 and settled[0]["result"] == "H"
    assert store.class_counts_before(db_session, ko.date() + dt.timedelta(days=1)) == [1, 0, 0]
