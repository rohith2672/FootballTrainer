"""Persistent hourly snapshot and model-independent API projection."""
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import delete, select, update

from src.models import NewsArticle, NewsFeedState
from src.news.feed import SOURCE, fetch_feed

logger = logging.getLogger(__name__)
INTERVAL = timedelta(hours=1)
STALE_AFTER = timedelta(minutes=90)
EXPIRES_AFTER = timedelta(hours=24)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def refresh_due(db, now=None, *, fetch=fetch_feed):
    """Caller holds the worker lock. A failed refresh never replaces good data."""
    now = now or utcnow()
    state = db.get(NewsFeedState, SOURCE)
    # Expire physical cached data even when an upstream request fails.
    db.execute(delete(NewsArticle).where(NewsArticle.fetched_at <= now - EXPIRES_AFTER))
    if state is not None and state.next_check_at and now < state.next_check_at:
        db.commit()
        return False
    if state is None:
        state = NewsFeedState(source=SOURCE)
        db.add(state)
    state.last_attempt_at = now
    state.next_check_at = now + INTERVAL
    db.commit()  # persist scheduling even when the worker crashes in the request
    try:
        # After expiry ask for a fresh body: a 304 cannot restore purged records.
        can_revalidate = state.last_success_at and now - state.last_success_at < EXPIRES_AFTER
        result = fetch(state.etag if can_revalidate else None,
                       state.last_modified if can_revalidate else None)
        if result.not_modified and not can_revalidate:
            raise ValueError("Provider returned 304 without a valid cached snapshot")
    except Exception:
        logger.warning("Football news refresh failed; retaining unexpired cache", exc_info=True)
        return True
    if result.not_modified:
        db.execute(update(NewsArticle).where(NewsArticle.source == SOURCE).values(fetched_at=now))
        state.etag = result.etag or state.etag
        state.last_modified = result.last_modified or state.last_modified
    else:
        # RSS is a current snapshot: remove withdrawn items and retain no archive.
        db.execute(delete(NewsArticle).where(NewsArticle.source == SOURCE))
        db.add_all([NewsArticle(**article, fetched_at=now) for article in result.articles])
        state.etag = result.etag
        state.last_modified = result.last_modified
    state.last_success_at = now
    db.commit()
    logger.info("Football news refreshed: source=%s not_modified=%s articles=%s next_check=%s",
                SOURCE, result.not_modified,
                "unchanged" if result.not_modified else len(result.articles), state.next_check_at)
    return True


def read_news(db, limit=50, now=None):
    now = now or utcnow()
    state = db.get(NewsFeedState, SOURCE)
    success = state.last_success_at if state else None
    if not success or now - success >= EXPIRES_AFTER:
        status = "unavailable"
    elif now - success > STALE_AFTER:
        status = "stale"
    else:
        status = "ok"
    rows = [] if status == "unavailable" else db.scalars(
        select(NewsArticle).where(NewsArticle.source == SOURCE,
                                 NewsArticle.fetched_at > now - EXPIRES_AFTER)
        .order_by(NewsArticle.published_at.desc().nulls_last(), NewsArticle.id)
        .limit(limit)
    ).all()
    return {
        "articles": [{"id": row.id, "title": row.title, "url": row.url,
                      "publisher": row.publisher, "published_at": iso(row.published_at),
                      "fetched_at": iso(row.fetched_at)} for row in rows],
        "last_attempt_at": iso(state.last_attempt_at) if state else None,
        "last_success_at": iso(success),
        "next_check_at": iso(state.next_check_at) if state else None,
        "status": status, "stale": status != "ok",
    }
