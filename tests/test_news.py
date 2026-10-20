"""News parsing, HTTP behavior and cache lifecycle without network or real DB."""
from datetime import datetime, timedelta
from unittest.mock import Mock

from defusedxml.common import DefusedXmlException
import pytest
import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.models import NewsArticle, NewsFeedState
from src.news import feed, service

NOW = datetime(2026, 10, 16, 12)
ITEM = """<item><guid>story-1</guid><title>Football headline</title>
<link>https://www.bbc.com/sport/football/articles/123?utm_source=rss</link>
<pubDate>Fri, 16 Oct 2026 11:00:00 GMT</pubDate></item>"""


def xml(items=ITEM):
    return f"<rss><channel>{items}</channel></rss>".encode()


def result(items=ITEM, **kwargs):
    return feed.FeedResult(feed.parse_feed(xml(items)), **kwargs)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    NewsArticle.__table__.create(engine)
    NewsFeedState.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_parser_deduplicates_guid_and_canonical_url():
    duplicate_url = ITEM.replace("story-1", "another-guid").replace("utm_source=rss", "utm_source=other")
    duplicate_guid = ITEM.replace("articles/123", "articles/other")
    rows = feed.parse_feed(xml(ITEM + duplicate_url + duplicate_guid))
    assert len(rows) == 1
    assert rows[0]["url"] == "https://www.bbc.com/sport/football/articles/123"
    assert rows[0]["published_at"] == datetime(2026, 10, 16, 11)
    assert rows[0]["publisher"] == "BBC Sport"
    assert rows[0]["provider_id"] == "story-1"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "//example.com/a", "file:///etc/passwd",
                                      "https://user:password@example.com/a", "https://example.com:bad/a",
                                      "https://example.com/\nscript", "https://host\\other/a"])
def test_unsafe_links_rejected(url):
    assert feed.safe_url(url) is None


def test_parser_missing_date_guid_and_malformed_entry():
    item = "<item><title>Good</title><link>https://example.com/a</link><pubDate>bad</pubDate></item>"
    rows = feed.parse_feed(xml("<item><title>Missing link</title></item>" + item))
    assert len(rows) == 1 and rows[0]["published_at"] is None
    assert rows[0]["id"] == feed.parse_feed(xml(item))[0]["id"]


def test_parser_rejects_entities_and_bad_documents():
    with pytest.raises(DefusedXmlException):
        feed.parse_feed(b'<!DOCTYPE rss [<!ENTITY x "unsafe">]><rss><channel>&x;</channel></rss>')
    with pytest.raises(ValueError):
        feed.parse_feed(b"<html></html>")
    with pytest.raises(ValueError):
        feed.parse_feed(xml("<item/>"))
    assert feed.parse_feed(xml("")) == []


def test_success_snapshot_idempotency_and_removal(db):
    fetch = Mock(return_value=result(etag='"v1"'))
    assert service.refresh_due(db, NOW, fetch=fetch)
    assert not service.refresh_due(db, NOW + timedelta(minutes=59), fetch=fetch)
    assert service.refresh_due(db, NOW + timedelta(hours=1), fetch=fetch)
    assert len(db.scalars(select(NewsArticle)).all()) == 1
    assert fetch.call_count == 2
    fetch.assert_called_with('"v1"', None)
    service.refresh_due(db, NOW + timedelta(hours=2), fetch=lambda *_: result(""))
    response = service.read_news(db, now=NOW + timedelta(hours=2))
    assert response["articles"] == [] and response["status"] == "ok"
    assert response["next_check_at"] == "2026-10-16T15:00:00Z"


def test_failed_fetch_preserves_content_and_original_success_time(db):
    service.refresh_due(db, NOW, fetch=lambda *_: result())
    failed = Mock(side_effect=requests.Timeout())
    service.refresh_due(db, NOW + timedelta(hours=1), fetch=failed)
    response = service.read_news(db, now=NOW + timedelta(minutes=91))
    assert response["status"] == "stale" and response["stale"]
    assert len(response["articles"]) == 1
    assert response["last_success_at"] == "2026-10-16T12:00:00Z"
    assert response["last_attempt_at"] == "2026-10-16T13:00:00Z"


def test_malformed_feed_keeps_last_valid_snapshot(db):
    service.refresh_due(db, NOW, fetch=lambda *_: result())
    def malformed(*_):
        return feed.FeedResult(feed.parse_feed(b"<rss><broken>"))
    service.refresh_due(db, NOW + timedelta(hours=1), fetch=malformed)
    response = service.read_news(db, now=NOW + timedelta(hours=1))
    assert len(response["articles"]) == 1
    assert response["last_success_at"] == "2026-10-16T12:00:00Z"


def test_empty_never_fetched_and_first_failure(db):
    assert service.read_news(db, now=NOW)["status"] == "unavailable"
    service.refresh_due(db, NOW, fetch=Mock(side_effect=ValueError("bad feed")))
    response = service.read_news(db, now=NOW)
    assert response["status"] == "unavailable" and response["articles"] == []
    assert response["last_success_at"] is None
    assert response["last_attempt_at"] == "2026-10-16T12:00:00Z"


def test_304_revalidates_current_snapshot(db):
    service.refresh_due(db, NOW, fetch=lambda *_: result(etag='"v1"', last_modified="yesterday"))
    fetch = Mock(return_value=feed.FeedResult([], not_modified=True))
    service.refresh_due(db, NOW + timedelta(hours=1), fetch=fetch)
    fetch.assert_called_once_with('"v1"', "yesterday")
    response = service.read_news(db, now=NOW + timedelta(hours=1))
    assert response["last_success_at"] == "2026-10-16T13:00:00Z"
    assert response["articles"][0]["fetched_at"] == "2026-10-16T13:00:00Z"


def test_expired_cache_hidden_and_deleted_even_on_failure(db):
    service.refresh_due(db, NOW, fetch=lambda *_: result(etag='"v1"'))
    later = NOW + timedelta(hours=24)
    assert service.read_news(db, now=later)["articles"] == []
    assert service.read_news(db, now=later)["status"] == "unavailable"
    failed = Mock(side_effect=requests.Timeout())
    service.refresh_due(db, later, fetch=failed)
    failed.assert_called_once_with(None, None)
    assert db.scalars(select(NewsArticle)).all() == []


def test_304_without_valid_snapshot_cannot_create_false_success(db):
    service.refresh_due(db, NOW, fetch=lambda *_: feed.FeedResult([], not_modified=True))
    assert service.read_news(db, now=NOW)["status"] == "unavailable"


def response(status=200, headers=None, payload=None):
    response = Mock()
    response.status_code = status
    response.headers = headers or {}
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [payload if payload is not None else xml()]
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError()
    return response


def test_http_conditional_headers_and_304():
    get = Mock(return_value=response(304))
    assert feed.fetch_feed('"tag"', "yesterday", get=get).not_modified
    kwargs = get.call_args.kwargs
    assert kwargs["headers"]["If-None-Match"] == '"tag"'
    assert kwargs["headers"]["If-Modified-Since"] == "yesterday"
    assert kwargs["timeout"] == (5, 10)


def test_http_retries_transient_and_stops_at_three():
    get, sleep = Mock(side_effect=[response(503), requests.Timeout(), response()]), Mock()
    assert len(feed.fetch_feed(get=get, sleep=sleep).articles) == 1
    assert get.call_count == 3 and sleep.call_count == 2
    get = Mock(side_effect=requests.Timeout())
    with pytest.raises(requests.Timeout):
        feed.fetch_feed(get=get, sleep=Mock())
    assert get.call_count == 3


def test_long_rate_limit_not_retried_early():
    get, sleep = Mock(return_value=response(429, {"Retry-After": "3600"})), Mock()
    with pytest.raises(requests.HTTPError):
        feed.fetch_feed(get=get, sleep=sleep)
    assert get.call_count == 1
    sleep.assert_not_called()


def test_http_caps_payload():
    with pytest.raises(ValueError):
        feed.fetch_feed(get=Mock(return_value=response(payload=b"x" * (feed.MAX_BYTES + 1))))
