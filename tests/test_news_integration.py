"""Real PostgreSQL news persistence and cross-connection locking checks.

Uses only TEST_DATABASE_URL and the isolated schema fixture; never application DB.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import NewsArticle, NewsFeedState
from src.news.feed import FeedResult, SOURCE, parse_feed
from src.news.service import read_news
from src.news.worker import refresh_lock, run_once
from tests._pgtest import db_session  # noqa: F401


NOW = datetime(2026, 10, 16, 12)


def feed_result(title="Match preview", etag='"revision-1"'):
    payload = (
        f"<rss><channel><item><guid>match-preview</guid><title>{title}</title>"
        "<link>https://www.bbc.com/sport/football/articles/test-match</link>"
        "<pubDate>Fri, 16 Oct 2026 11:00:00 GMT</pubDate>"
        "</item></channel></rss>"
    )
    articles = parse_feed(payload.encode())
    return FeedResult(articles, etag=etag)


def test_hourly_schedule_and_revalidation_survive_new_sessions(db_session):
    engine = db_session.get_bind()
    calls = []

    def fetch(etag, modified):
        calls.append((etag, modified))
        return feed_result()

    assert run_once(engine, NOW, fetch=fetch) is True
    assert run_once(engine, NOW + timedelta(minutes=59), fetch=fetch) is False
    assert len(calls) == 1
    with Session(engine) as check:
        assert check.scalar(select(func.count()).select_from(NewsArticle)) == 1
        assert read_news(check, now=NOW)["status"] == "ok"

    def revalidate(etag, modified):
        assert etag == '"revision-1"'
        return FeedResult([], not_modified=True)

    assert run_once(engine, NOW + timedelta(hours=1), fetch=revalidate) is True
    with Session(engine) as check:
        article = check.scalar(select(NewsArticle))
        assert article.fetched_at == NOW + timedelta(hours=1)
        assert check.get(NewsFeedState, SOURCE).last_success_at == article.fetched_at


def test_worker_lock_blocks_other_connection_after_scheduling_commit(db_session):
    engine = db_session.get_bind()
    fetching, release = Event(), Event()

    def slow_fetch(etag, modified):
        fetching.set()
        assert release.wait(10), "test did not release fetch"
        return feed_result()

    def forbidden_fetch(*args):
        pytest.fail("second worker fetched while first worker held the lock")

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(run_once, engine, NOW, fetch=slow_fetch)
        try:
            assert fetching.wait(5), "first worker never began fetching"
            # The first worker committed next_check_at before entering fetch.
            # Advancing time prevents the hourly gate from masking a broken lock.
            assert run_once(engine, NOW + timedelta(hours=2), fetch=forbidden_fetch) is False
        finally:
            release.set()
        assert first.result(timeout=5) is True
    assert run_once(engine, NOW + timedelta(hours=2), fetch=lambda *_: feed_result()) is True


def test_advisory_lock_released_after_exception(db_session):
    engine = db_session.get_bind()
    with engine.connect() as first, engine.connect() as second:
        with pytest.raises(RuntimeError, match="simulated"):
            with refresh_lock(first) as acquired:
                assert acquired
                with refresh_lock(second) as competing:
                    assert not competing
                raise RuntimeError("simulated worker failure")
        with refresh_lock(second) as acquired:
            assert acquired


def test_failed_refresh_keeps_cache_but_expiry_removes_it(db_session):
    engine = db_session.get_bind()
    assert run_once(engine, NOW, fetch=lambda *_: feed_result())

    def fail(*args):
        raise TimeoutError("provider timed out")

    assert run_once(engine, NOW + timedelta(hours=2), fetch=fail)
    with Session(engine) as check:
        snapshot = read_news(check, now=NOW + timedelta(hours=2))
        assert snapshot["status"] == "stale"
        assert len(snapshot["articles"]) == 1
    assert run_once(engine, NOW + timedelta(hours=24), fetch=fail)
    with Session(engine) as check:
        assert read_news(check, now=NOW + timedelta(hours=24))["status"] == "unavailable"
        assert check.scalar(select(func.count()).select_from(NewsArticle)) == 0


def test_refresh_replaces_snapshot_without_duplicate_ids(db_session):
    engine = db_session.get_bind()
    assert run_once(engine, NOW, fetch=lambda *_: feed_result())
    assert run_once(engine, NOW + timedelta(hours=1), fetch=lambda *_: feed_result("Updated preview"))
    with Session(engine) as check:
        articles = check.scalars(select(NewsArticle)).all()
        assert len(articles) == 1
        assert articles[0].title == "Updated preview"
