"""Fetch only headline metadata from the configured BBC Sport RSS feed."""
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from defusedxml import ElementTree
import requests

SOURCE = "bbc-football"
PUBLISHER = "BBC Sport"
FEED_URL = "https://feeds.bbci.co.uk/sport/football/rss.xml"
MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class FeedResult:
    articles: list[dict]
    not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None


def safe_url(value: str) -> str | None:
    """Accept absolute web links only; remove fragments and marketing tags."""
    value = value.strip()
    if not value or "\\" in value or any(ord(c) < 33 for c in value):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return None
        if parts.username is not None or parts.password is not None:
            return None
        _ = parts.port  # reject malformed ports
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_")]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                           urlencode(query), ""))
    except ValueError:
        return None


def parse_feed(payload: bytes) -> list[dict]:
    if len(payload) > MAX_BYTES:
        raise ValueError("News feed exceeds size limit")
    root = ElementTree.fromstring(payload)
    channel = root.find("channel") if root.tag == "rss" else None
    if channel is None:
        raise ValueError("Expected an RSS channel")
    articles, ids, urls = [], set(), set()
    items = channel.findall("item")
    for item in items:
        title = (item.findtext("title") or "").strip()
        url = safe_url(item.findtext("link") or "")
        if not title or not url:
            continue
        guid = (item.findtext("guid") or "").strip() or url
        identifier = hashlib.sha256(f"{SOURCE}:{guid}".encode()).hexdigest()
        if identifier in ids or url in urls:
            continue
        published = None
        try:
            parsed = parsedate_to_datetime(item.findtext("pubDate") or "")
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            published = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError, OverflowError):
            pass
        articles.append({"id": identifier, "source": SOURCE, "provider_id": guid, "title": title,
                         "url": url, "publisher": PUBLISHER, "published_at": published})
        ids.add(identifier)
        urls.add(url)
    if items and not articles:
        raise ValueError("News feed contains no usable entries")
    return articles


def fetch_feed(etag=None, last_modified=None, *, get=requests.get, sleep=time.sleep):
    headers = {"User-Agent": "FootballTrainer/1.0 (personal RSS reader)",
               "Accept": "application/rss+xml, application/xml, text/xml"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    for attempt in range(3):
        try:
            with get(FEED_URL, headers=headers, timeout=(5, 10), stream=True,
                     allow_redirects=False) as response:
                if response.status_code == 304:
                    return FeedResult([], True, response.headers.get("ETag"),
                                      response.headers.get("Last-Modified"))
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        delay = retry_delay(response.headers.get("Retry-After"), attempt)
                        if delay is not None:
                            sleep(delay)
                            continue
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("Unexpected news provider response")
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=16384):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("News feed exceeds size limit")
                    chunks.append(chunk)
                return FeedResult(parse_feed(b"".join(chunks)), False,
                                  response.headers.get("ETag"),
                                  response.headers.get("Last-Modified"))
        except requests.HTTPError:
            raise
        except requests.RequestException:
            if attempt == 2:
                raise
            sleep(2 ** attempt)


def retry_delay(retry_after, attempt):
    """Never sleep beyond five seconds; defer long provider limits to next run."""
    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError):
                return None
        return max(0, delay) if delay <= 5 else None
    return 2 ** attempt
