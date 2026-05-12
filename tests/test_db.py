import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from src.database import SessionLocal, engine
from src.models import Match, Team


def db_reachable() -> bool:
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False


requires_db = pytest.mark.skipif(
    not db_reachable(),
    reason="PostgreSQL not reachable — skipping DB integration tests",
)


@requires_db
def test_engine_connects():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


@requires_db
def test_tables_exist():
    from sqlalchemy import inspect

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "matches" in tables, "matches table missing — run alembic upgrade head"
    assert "teams" in tables, "teams table missing — run alembic upgrade head"


@requires_db
def test_session_roundtrip():
    session = SessionLocal()
    try:
        team = Team(name="Test FC", league="PL")
        session.add(team)
        session.commit()

        fetched = session.query(Team).filter_by(name="Test FC").one()
        assert fetched.league == "PL"
    finally:
        session.query(Team).filter_by(name="Test FC").delete()
        session.commit()
        session.close()
