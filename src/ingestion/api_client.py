import os
import time
import threading
from collections import deque

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.football-data.org/v4"

# v4 accepts a comma-separated status filter; fixtures with a confirmed kickoff
# are TIMED, not SCHEDULED, so both are needed.
UPCOMING_STATUSES = "SCHEDULED,TIMED"

# Rate limiter: free tier allows 10 requests per 60 seconds
_RATE_LIMIT = 10
_RATE_WINDOW = 60.0
_request_times: deque = deque()
_lock = threading.Lock()


def get_api_key() -> str:
    """The football-data.org token, read from the environment at call time."""
    return os.getenv("FOOTBALL_DATA_API_KEY", "").strip()


def _wait_for_rate_limit() -> None:
    with _lock:
        now = time.monotonic()
        # drop timestamps older than the window
        while _request_times and now - _request_times[0] >= _RATE_WINDOW:
            _request_times.popleft()

        if len(_request_times) >= _RATE_LIMIT:
            sleep_for = _RATE_WINDOW - (now - _request_times[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
            # re-prune after sleeping
            now = time.monotonic()
            while _request_times and now - _request_times[0] >= _RATE_WINDOW:
                _request_times.popleft()

        _request_times.append(time.monotonic())


def _get(path: str, params: dict | None = None, retries: int = 3) -> dict:
    url = f"{BASE_URL}{path}"
    headers = {"X-Auth-Token": get_api_key()}

    for attempt in range(retries):
        _wait_for_rate_limit()
        response = requests.get(url, headers=headers, params=params, timeout=10)

        if response.status_code == 200:
            return response.json()

        if response.status_code == 429:
            # server-side rate limit hit — back off and retry
            retry_after = int(response.headers.get("Retry-After", 60))
            time.sleep(retry_after)
            continue

        if response.status_code >= 500 and attempt < retries - 1:
            time.sleep(2 ** attempt)
            continue

        response.raise_for_status()

    raise RuntimeError(f"Failed to GET {url} after {retries} attempts")


def get_matches(league_code: str, season: int, status: str | None = None) -> dict:
    """Fetch all matches for a competition and season (optionally one status filter)."""
    params: dict = {"season": season}
    if status:
        params["status"] = status
    return _get(f"/competitions/{league_code}/matches", params=params)


def get_teams(league_code: str, season: int | None = None) -> dict:
    """Fetch all teams for a competition."""
    params = {"season": season} if season is not None else None
    return _get(f"/competitions/{league_code}/teams", params=params)


def get_upcoming_matches(league_code: str) -> dict:
    """Fetch upcoming matches (SCHEDULED = date TBC, TIMED = kickoff time set)."""
    return _get(
        f"/competitions/{league_code}/matches", params={"status": UPCOMING_STATUSES}
    )


# ---------------------------------------------------------------------------
# Upcoming-fixture cache (the API fans out to 6 leagues per request; the free
# tier allows 10 requests/minute, so successful responses are reused for a while).
# ---------------------------------------------------------------------------
UPCOMING_TTL_SECONDS = 600.0
_upcoming_cache: dict = {}            # league -> (monotonic fetched_at, payload)
_cache_lock = threading.Lock()        # guards the two dicts
_league_locks: dict = {}              # league -> Lock (one in-flight fetch per league)


def get_upcoming_matches_cached(league_code: str, ttl: float | None = None) -> dict:
    """``get_upcoming_matches`` with an in-memory TTL cache (thread-safe).

    Only successful responses are cached; exceptions propagate and leave the
    cache untouched. Concurrent callers for the same league share one fetch.
    """
    ttl = UPCOMING_TTL_SECONDS if ttl is None else ttl

    def fresh():
        entry = _upcoming_cache.get(league_code)
        if entry is not None and time.monotonic() - entry[0] < ttl:
            return entry[1]
        return None

    with _cache_lock:
        hit = fresh()
        if hit is not None:
            return hit
        league_lock = _league_locks.setdefault(league_code, threading.Lock())

    with league_lock:
        with _cache_lock:
            hit = fresh()
        if hit is not None:
            return hit
        payload = get_upcoming_matches(league_code)
        with _cache_lock:
            _upcoming_cache[league_code] = (time.monotonic(), payload)
        return payload


def clear_cache() -> None:
    """Drop all cached upstream responses (used by tests)."""
    with _cache_lock:
        _upcoming_cache.clear()
