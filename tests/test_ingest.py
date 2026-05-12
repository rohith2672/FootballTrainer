from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from src.database import SessionLocal, engine
from src.ingestion.ingest import ingest_matches, ingest_teams
from src.models import Match, Team


# ---------------------------------------------------------------------------
# DB availability guard (same pattern as test_db.py)
# ---------------------------------------------------------------------------

def _db_reachable() -> bool:
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False


requires_db = pytest.mark.skipif(
    not _db_reachable(),
    reason="PostgreSQL not reachable — skipping DB integration tests",
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TEST_MATCH_IDS = [9900001, 9900002]

FINISHED_PAYLOAD = {
    "matches": [
        {
            "id": 9900001,
            "utcDate": "2021-08-14T14:00:00Z",
            "status": "FINISHED",
            "homeTeam": {"name": "__TestHome FC"},
            "awayTeam": {"name": "__TestAway FC"},
            "score": {"fullTime": {"home": 2, "away": 1}},
        },
        {
            "id": 9900002,
            "utcDate": "2021-08-21T14:00:00Z",
            "status": "FINISHED",
            "homeTeam": {"name": "__TestAway FC"},
            "awayTeam": {"name": "__TestHome FC"},
            "score": {"fullTime": {"home": 0, "away": 0}},
        },
    ]
}

MIXED_PAYLOAD = {
    "matches": [
        *FINISHED_PAYLOAD["matches"],
        {
            "id": 9900099,
            "utcDate": "2021-09-01T14:00:00Z",
            "status": "SCHEDULED",
            "homeTeam": {"name": "__TestHome FC"},
            "awayTeam": {"name": "__TestAway FC"},
            "score": {"fullTime": {"home": None, "away": None}},
        },
    ]
}

TEAMS_PAYLOAD = {
    "teams": [
        {"id": 99001, "name": "__TestHome FC"},
        {"id": 99002, "name": "__TestAway FC"},
    ]
}


def _cleanup(session):
    session.query(Match).filter(Match.id.in_(TEST_MATCH_IDS)).delete(
        synchronize_session=False
    )
    session.query(Team).filter(
        Team.name.in_(["__TestHome FC", "__TestAway FC"])
    ).delete(synchronize_session=False)
    session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@requires_db
def test_ingest_returns_summary():
    session = SessionLocal()
    try:
        _cleanup(session)
    finally:
        session.close()

    with patch("src.ingestion.ingest.get_matches", return_value=FINISHED_PAYLOAD):
        result = ingest_matches(league="PL", seasons=[2021])

    assert result["fetched"] == 2
    assert result["inserted"] == 2
    assert result["skipped"] == 0

    session = SessionLocal()
    try:
        _cleanup(session)
    finally:
        session.close()


@requires_db
def test_ingest_idempotent():
    session = SessionLocal()
    try:
        _cleanup(session)
    finally:
        session.close()

    with patch("src.ingestion.ingest.get_matches", return_value=FINISHED_PAYLOAD):
        first = ingest_matches(league="PL", seasons=[2021])
        second = ingest_matches(league="PL", seasons=[2021])

    assert first["inserted"] == 2
    assert second["inserted"] == 0
    assert second["skipped"] == 2

    session = SessionLocal()
    try:
        _cleanup(session)
    finally:
        session.close()


@requires_db
def test_ingest_skips_non_finished():
    session = SessionLocal()
    try:
        _cleanup(session)
    finally:
        session.close()

    with patch("src.ingestion.ingest.get_matches", return_value=MIXED_PAYLOAD):
        result = ingest_matches(league="PL", seasons=[2021])

    # SCHEDULED match must not count toward fetched or inserted
    assert result["fetched"] == 2
    assert result["inserted"] == 2

    session = SessionLocal()
    try:
        _cleanup(session)
    finally:
        session.close()


@requires_db
def test_ingest_result_encoding():
    """Verify H/D/A encoding is correct."""
    session = SessionLocal()
    try:
        _cleanup(session)
    finally:
        session.close()

    with patch("src.ingestion.ingest.get_matches", return_value=FINISHED_PAYLOAD):
        ingest_matches(league="PL", seasons=[2021])

    session = SessionLocal()
    try:
        home_win = session.query(Match).filter_by(id=9900001).one()
        draw = session.query(Match).filter_by(id=9900002).one()

        assert home_win.result == "H"
        assert draw.result == "D"
    finally:
        _cleanup(session)
        session.close()


@requires_db
def test_ingest_teams():
    session = SessionLocal()
    try:
        _cleanup(session)
    finally:
        session.close()

    with patch("src.ingestion.ingest.get_teams", return_value=TEAMS_PAYLOAD):
        ingest_teams(league="PL")

    session = SessionLocal()
    try:
        names = {t.name for t in session.query(Team).filter(
            Team.name.in_(["__TestHome FC", "__TestAway FC"])
        ).all()}
        assert "__TestHome FC" in names
        assert "__TestAway FC" in names

        # idempotent — second call must not raise
        with patch("src.ingestion.ingest.get_teams", return_value=TEAMS_PAYLOAD):
            ingest_teams(league="PL")
    finally:
        _cleanup(session)
        session.close()
