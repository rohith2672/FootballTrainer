import os
import time
import threading
from collections import deque

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.football-data.org/v4"
_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")

# Rate limiter: free tier allows 10 requests per 60 seconds
_RATE_LIMIT = 10
_RATE_WINDOW = 60.0
_request_times: deque = deque()
_lock = threading.Lock()


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
    headers = {"X-Auth-Token": _API_KEY}

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


def get_matches(league_code: str, season: int) -> dict:
    """Fetch all matches for a competition and season."""
    return _get(f"/competitions/{league_code}/matches", params={"season": season})


def get_teams(league_code: str) -> dict:
    """Fetch all teams for a competition."""
    return _get(f"/competitions/{league_code}/teams")
