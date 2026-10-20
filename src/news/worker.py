"""Hourly worker: python -m src.news.worker (PostgreSQL, migrated schema)."""
from contextlib import contextmanager
import logging
import signal
import threading

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.news.service import refresh_due

logger = logging.getLogger(__name__)
LOCK_ID = 706641892173  # application-specific, PostgreSQL signed bigint


@contextmanager
def refresh_lock(connection):
    """Hold a session advisory lock on one connection across ORM commits."""
    acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID})
    connection.commit()
    try:
        yield bool(acquired)
    finally:
        if acquired:
            connection.rollback()
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
            connection.commit()


def run_once(engine, now=None, **kwargs):
    with engine.connect() as connection:
        with refresh_lock(connection) as acquired:
            if not acquired:
                return False
            with Session(bind=connection) as db:
                return refresh_due(db, now, **kwargs)


def main():
    from src.database import engine
    if engine is None:
        raise SystemExit("DATABASE_URL is required for the news worker")
    if engine.dialect.name != "postgresql":
        raise SystemExit("The news worker requires PostgreSQL")
    logging.basicConfig(level=logging.INFO)
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    while not stopped.is_set():
        try:
            run_once(engine)
        except Exception:
            logger.exception("News worker could not refresh; will retry")
        # Persisted next_check_at gates upstream calls to once per hour.
        # Short checks recover promptly from DB/migration startup delays.
        stopped.wait(30)


if __name__ == "__main__":
    main()
