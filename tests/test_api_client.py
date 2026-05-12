import time
from unittest.mock import patch, MagicMock

import pytest
import requests

from src.ingestion.api_client import get_matches, get_teams, _wait_for_rate_limit, _request_times, _RATE_LIMIT, _RATE_WINDOW


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status_code: int, json_body: dict, headers: dict | None = None):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_body
    mock.headers = headers or {}
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        mock.raise_for_status.side_effect = requests.HTTPError(response=mock)
    return mock


MATCHES_PAYLOAD = {
    "matches": [
        {
            "id": 1,
            "utcDate": "2023-08-12T14:00:00Z",
            "homeTeam": {"name": "Arsenal FC"},
            "awayTeam": {"name": "Nottingham Forest FC"},
            "score": {"fullTime": {"home": 2, "away": 1}},
        }
    ]
}

TEAMS_PAYLOAD = {
    "teams": [
        {"id": 57, "name": "Arsenal FC"},
        {"id": 61, "name": "Chelsea FC"},
    ]
}


# ---------------------------------------------------------------------------
# get_matches
# ---------------------------------------------------------------------------

class TestGetMatches:
    def test_returns_json_on_200(self):
        with patch("src.ingestion.api_client.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, MATCHES_PAYLOAD)
            result = get_matches("PL", 2023)

        assert result == MATCHES_PAYLOAD
        call_args = mock_get.call_args
        assert "/competitions/PL/matches" in call_args.args[0]
        assert call_args.kwargs["params"] == {"season": 2023}

    def test_passes_auth_header(self):
        with patch("src.ingestion.api_client.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, MATCHES_PAYLOAD)
            get_matches("PL", 2023)

        headers = mock_get.call_args.kwargs["headers"]
        assert "X-Auth-Token" in headers

    def test_raises_on_404(self):
        with patch("src.ingestion.api_client.requests.get") as mock_get:
            mock_get.return_value = _make_response(404, {"message": "not found"})
            with pytest.raises(requests.HTTPError):
                get_matches("XX", 2023)

    def test_retries_on_500(self):
        ok = _make_response(200, MATCHES_PAYLOAD)
        err = _make_response(500, {})
        with patch("src.ingestion.api_client.requests.get", side_effect=[err, ok]) as mock_get:
            with patch("src.ingestion.api_client.time.sleep"):
                result = get_matches("PL", 2023)

        assert result == MATCHES_PAYLOAD
        assert mock_get.call_count == 2

    def test_raises_after_all_retries_fail(self):
        err = _make_response(500, {})
        with patch("src.ingestion.api_client.requests.get", return_value=err):
            with patch("src.ingestion.api_client.time.sleep"):
                with pytest.raises((requests.HTTPError, RuntimeError)):
                    get_matches("PL", 2023)

    def test_retries_on_429_with_retry_after(self):
        rate_limited = _make_response(429, {}, headers={"Retry-After": "1"})
        ok = _make_response(200, MATCHES_PAYLOAD)
        with patch("src.ingestion.api_client.requests.get", side_effect=[rate_limited, ok]):
            with patch("src.ingestion.api_client.time.sleep") as mock_sleep:
                result = get_matches("PL", 2023)

        assert result == MATCHES_PAYLOAD
        mock_sleep.assert_called_with(1)


# ---------------------------------------------------------------------------
# get_teams
# ---------------------------------------------------------------------------

class TestGetTeams:
    def test_returns_json_on_200(self):
        with patch("src.ingestion.api_client.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, TEAMS_PAYLOAD)
            result = get_teams("PL")

        assert result == TEAMS_PAYLOAD
        assert "/competitions/PL/teams" in mock_get.call_args.args[0]

    def test_no_season_param_sent(self):
        with patch("src.ingestion.api_client.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, TEAMS_PAYLOAD)
            get_teams("PL")

        # get_teams should not pass a season param
        params = mock_get.call_args.kwargs.get("params")
        assert params is None or "season" not in (params or {})


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_does_not_exceed_rate_limit(self):
        """Firing RATE_LIMIT+1 calls must trigger at least one sleep."""
        _request_times.clear()

        sleep_calls = []

        real_sleep = time.sleep

        def fake_sleep(secs):
            sleep_calls.append(secs)
            # advance the deque timestamps so the window expires quickly
            now = time.monotonic()
            for i in range(len(_request_times)):
                # age them out by replacing — easier to just clear and re-add
                pass
            _request_times.clear()

        with patch("src.ingestion.api_client.time.sleep", side_effect=fake_sleep):
            with patch("src.ingestion.api_client.time.monotonic") as mock_mono:
                # all calls happen at t=0, so they stack up
                mock_mono.return_value = 0.0
                for _ in range(_RATE_LIMIT + 1):
                    _wait_for_rate_limit()

        assert len(sleep_calls) >= 1, "Rate limiter should have slept at least once"
