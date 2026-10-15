"""Isolated PostgreSQL fixture for ingestion tests.

Set TEST_DATABASE_URL to a throwaway database; every test gets its own fresh
schema (created from the SQLAlchemy models and dropped afterwards), so nothing
in the configured application database is touched.  Without the variable the
tests using ``db_session`` are skipped.
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from src.models import Base


@pytest.fixture
def db_session():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set - skipping PostgreSQL integration tests")

    schema = f"t_{uuid.uuid4().hex[:12]}"
    admin = create_engine(url)
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip("TEST_DATABASE_URL is not reachable")

    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
