"""Database checks use only the explicitly configured isolated test schema."""

from sqlalchemy import inspect, text

from tests._pgtest import db_session  # noqa: F401
from src.models import Team


def test_engine_connects(db_session):
    assert db_session.execute(text("SELECT 1")).scalar() == 1


def test_tables_exist(db_session):
    tables = inspect(db_session.bind).get_table_names()
    assert "matches" in tables
    assert "teams" in tables


def test_session_roundtrip(db_session):
    db_session.add(Team(id=999999, name="Test FC", league="PL"))
    db_session.commit()
    assert db_session.query(Team).filter_by(name="Test FC").one().league == "PL"
