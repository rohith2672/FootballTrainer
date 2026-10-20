"""Team analysis endpoints, team filters and the history cache (mocked DB / upstream)."""
import datetime as dt
from urllib.parse import quote

import pandas as pd
import pytest
from sqlalchemy.exc import OperationalError

from src.api import history_cache, model_store, store, team_stats, teams
from src.api.main import app
from src.database import DatabaseNotConfigured, get_db
from src.ingestion import api_client
from tests.helpers_api import (  # noqa: F401  (fixtures)
    MODEL_VERSION,
    NO_HISTORY_TEAM,
    api_env,
    client,
    db_override,
    fx_payload,
    harness,
    settled_row,
    soon,
)

A, B, C, D = "Arsenal FC", "Chelsea FC", "Liverpool FC", "Everton FC"
AMP = "Brighton & Hove Albion FC"
TODAY = dt.date(2026, 1, 15)

PROFILE_KEYS = {
    "name", "league", "as_of", "elo", "form", "season", "averages", "rest_days",
    "last_match_date", "next_fixture", "next_fixture_status",
}


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(teams, "today", lambda: TODAY)


def _boom(*a, **k):
    raise OperationalError("SELECT 1", {}, Exception("connection refused"))


# ---------------------------------------------------------------------------
# /teams/index
# ---------------------------------------------------------------------------
def test_index_sorted_with_cl_only_null_last(client, harness):
    cl_row = {**harness.history.iloc[0].to_dict(), "id": 999, "league": "CL",
              "home_team": "Celtic FC", "away_team": A, "date": pd.Timestamp("2025-10-01 20:00")}
    cl_row["kickoff"] = cl_row["date"]
    harness.history = pd.concat([harness.history, pd.DataFrame([cl_row])], ignore_index=True)
    harness.team_rows = [(n, "PL") for n in harness.team_names] + [("Celtic FC", "CL"), ("FC Barcelona", "PD")]
    body = client.get("/teams/index").json()
    assert body[0] == {"name": "FC Barcelona", "league": "PD"}
    assert [t["name"] for t in body[1:5]] == sorted([A, B, C, D])
    assert all(t["league"] == "PL" for t in body[1:5])
    assert body[-1] == {"name": "Celtic FC", "league": None}


def test_existing_flat_teams_endpoint_unchanged(client, harness):
    assert client.get("/teams").json() == sorted([A, B, C, D])


# ---------------------------------------------------------------------------
# /teams/{name}
# ---------------------------------------------------------------------------
def test_profile_shape_and_values(client, harness):
    resp = client.get(f"/teams/{quote(A)}")
    assert resp.status_code == 200
    p = resp.json()
    assert set(p) == PROFILE_KEYS
    assert p["name"] == A and p["league"] == "PL" and p["as_of"] is None
    assert set(p["elo"]) == {"rating", "rank_in_league", "league_size", "change_last_5"}
    assert p["elo"]["league_size"] == 4 and 1 <= p["elo"]["rank_in_league"] <= 4
    assert p["form"]["n"] == 5 and len(p["form"]["last5"]) == 5
    assert p["season"]["season"] == 2025 and p["season"]["played"] == 6
    assert p["season"]["home"]["played"] == 3 and p["season"]["away"]["played"] == 3
    assert p["averages"]["n"] == 10 and p["averages"]["n_shots"] == 10
    last = dt.date.fromisoformat(p["last_match_date"])
    assert p["rest_days"] == (TODAY - last).days
    # no upstream fixture for Arsenal -> "none" (source reachable)
    assert p["next_fixture"] is None and p["next_fixture_status"] == "none"


def test_profile_rating_matches_replay_of_history(client, harness):
    enr = team_stats.replay_elo(harness.history)
    expected = round(float(team_stats.team_matches(enr, A)["elo_after"].iloc[-1]), 1)
    assert client.get(f"/teams/{quote(A)}").json()["elo"]["rating"] == expected


def test_profile_404_and_422(client):
    r = client.get("/teams/Unknown%20FC")
    assert r.status_code == 404 and r.json()["detail"] == "Team not found: Unknown FC"
    assert client.get(f"/teams/{quote(A)}?as_of=2025-13-01").status_code == 422


def test_profile_team_in_table_without_history_and_encoded_name(client, harness):
    harness.team_rows = [(n, "PL") for n in harness.team_names] + [(AMP, "PL")]
    r = client.get(f"/teams/{quote(AMP, safe='')}")
    assert r.status_code == 200
    p = r.json()
    assert p["name"] == AMP and p["league"] == "PL"
    assert p["form"] == {"last5": "", "pts_pg": None, "n": 0}
    assert p["season"] is None and p["rest_days"] is None and p["elo"]["rating"] is None


def test_profile_as_of_uses_only_earlier_matches(client, harness):
    p = client.get(f"/teams/{quote(A)}?as_of=2024-09-01").json()
    assert p["as_of"] == "2024-09-01"
    assert p["last_match_date"] < "2024-09-01"
    assert p["season"]["season"] == 2024
    assert p["rest_days"] == (dt.date(2024, 9, 1) - dt.date.fromisoformat(p["last_match_date"])).days
    assert p["next_fixture"] is None and p["next_fixture_status"] == "unavailable"


def test_next_fixture_ok_reuses_upcoming_and_does_not_persist(client, harness):
    harness.upstream["PL"] = fx_payload(
        (201, C, D, soon(2), "TIMED"),
        (202, B, A, soon(5), "TIMED"),
        (203, A, C, soon(9), "TIMED"),
    )
    p = client.get(f"/teams/{quote(A)}").json()
    assert p["next_fixture_status"] == "ok"
    fx = p["next_fixture"]
    assert fx["fixture_id"] == 202 and fx["model_version"] == MODEL_VERSION
    assert fx["prediction_available"] is True
    assert abs(fx["home_win"] + fx["draw"] + fx["away_win"] - 1) < 1e-9
    assert {"top_factors", "details", "kickoff", "is_fallback"} <= set(fx)
    assert set(harness.upstream_calls) == {"PL", "CL"}
    assert harness.persisted == []                     # read-only endpoint


@pytest.mark.parametrize("case", ["no_key", "no_model", "upstream_down", "cl_down"])
def test_next_fixture_unavailable_never_fails_profile(client, harness, monkeypatch, case):
    harness.upstream["PL"] = fx_payload((202, B, A, soon(5), "TIMED"))
    if case == "no_key":
        monkeypatch.delenv("FOOTBALL_DATA_API_KEY")
    elif case == "no_model":
        client.app.state.model_state = model_store.ModelState(error="missing")
    elif case == "upstream_down":
        harness.upstream["PL"] = RuntimeError("down")
    else:
        harness.upstream["CL"] = RuntimeError("down")
    r = client.get(f"/teams/{quote(A)}")
    assert r.status_code == 200
    assert r.json()["next_fixture"] is None and r.json()["next_fixture_status"] == "unavailable"
    if case in ("no_key", "no_model"):
        assert harness.upstream_calls == []


def test_next_fixture_pipeline_error_is_unavailable(client, harness, monkeypatch):
    from src.api import upcoming

    def explode(*a, **k):
        raise RuntimeError("engine failure")

    monkeypatch.setattr(upcoming, "predict_upcoming", explode)
    r = client.get(f"/teams/{quote(A)}")
    assert r.status_code == 200 and r.json()["next_fixture_status"] == "unavailable"


# ---------------------------------------------------------------------------
# /teams/{name}/matches
# ---------------------------------------------------------------------------
def test_matches_newest_first_limit_and_venue(client, harness):
    rows = client.get(f"/teams/{quote(A)}/matches?limit=4").json()
    assert len(rows) == 4
    assert [r["date"] for r in rows] == sorted((r["date"] for r in rows), reverse=True)
    r0 = rows[0]
    assert set(r0) == {"date", "league", "season", "venue", "opponent", "gf", "ga", "result",
                       "shots_for", "shots_against", "sot_for", "sot_against", "elo_before", "elo_after"}
    assert r0["result"] == ("W" if r0["gf"] > r0["ga"] else "D" if r0["gf"] == r0["ga"] else "L")
    assert isinstance(r0["shots_for"], int)
    homes = client.get(f"/teams/{quote(A)}/matches?venue=home&limit=100").json()
    assert len(homes) == 9 and all(r["venue"] == "home" for r in homes)
    assert len(client.get(f"/teams/{quote(A)}/matches").json()) == 18


@pytest.mark.parametrize("q", ["venue=neutral", "limit=0", "limit=101"])
def test_matches_422(client, q):
    assert client.get(f"/teams/{quote(A)}/matches?{q}").status_code == 422


def test_matches_404_and_empty(client, harness):
    assert client.get("/teams/Nobody/matches").status_code == 404
    harness.team_rows = [(AMP, "PL")]
    assert client.get(f"/teams/{quote(AMP, safe='')}/matches").json() == []


# ---------------------------------------------------------------------------
# /teams/{name}/elo-history
# ---------------------------------------------------------------------------
def test_elo_history_since_and_default_window(client, harness):
    body = client.get(f"/teams/{quote(A)}/elo-history?since=2025-01-01").json()
    assert body["team"] == A
    pts = body["points"]
    assert len(pts) == 6 and all(p["date"] >= "2025-01-01" for p in pts)
    assert [p["date"] for p in pts] == sorted(p["date"] for p in pts)
    assert set(pts[0]) == {"date", "elo", "opponent", "result"}
    latest = client.get(f"/teams/{quote(A)}/matches?limit=1").json()[0]
    assert pts[-1]["elo"] == latest["elo_after"]
    # default: TODAY - 365 days = 2025-01-15 -> the 2025 season only
    assert client.get(f"/teams/{quote(A)}/elo-history").json()["points"] == pts
    assert client.get(f"/teams/{quote(A)}/elo-history?since=2030-01-01").json()["points"] == []
    assert client.get(f"/teams/{quote(A)}/elo-history?since=bad").status_code == 422
    assert client.get("/teams/Nobody/elo-history").status_code == 404


# ---------------------------------------------------------------------------
# /h2h
# ---------------------------------------------------------------------------
def test_h2h(client, harness):
    body = client.get("/h2h", params={"a": A, "b": B, "limit": 2}).json()
    assert body["a"] == A and body["b"] == B and body["n"] == 6
    assert body["a_wins"] + body["draws"] + body["b_wins"] == 6
    assert len(body["meetings"]) == 2
    assert body["meetings"][0]["date"] >= body["meetings"][1]["date"]
    rev = client.get("/h2h", params={"a": B, "b": A}).json()
    assert (rev["a_wins"], rev["b_wins"], rev["a_goals"]) == (body["b_wins"], body["a_wins"], body["b_goals"])


def test_h2h_errors(client, harness):
    r = client.get("/h2h", params={"a": A, "b": A})
    assert r.status_code == 422 and r.json()["detail"] == "a and b must differ"
    assert client.get("/h2h", params={"a": A}).status_code == 422
    assert client.get("/h2h", params={"a": A, "b": B, "limit": 0}).status_code == 422
    r = client.get("/h2h", params={"a": A, "b": "Nobody"})
    assert r.status_code == 404 and r.json()["detail"] == "Team not found: Nobody"
    harness.team_rows = [(n, "PL") for n in harness.team_names] + [(AMP, "PL")]
    empty = client.get("/h2h", params={"a": A, "b": AMP}).json()
    assert empty["n"] == 0 and empty["meetings"] == [] and empty["a_goals"] == 0


# ---------------------------------------------------------------------------
# 503 paths
# ---------------------------------------------------------------------------
PATHS = ["/teams/index", f"/teams/{quote(A)}", f"/teams/{quote(A)}/matches",
         f"/teams/{quote(A)}/elo-history", f"/h2h?a={quote(A)}&b={quote(B)}"]


@pytest.mark.parametrize("path", PATHS)
def test_db_error_is_503(client, harness, monkeypatch, path):
    monkeypatch.setattr(store, "load_history", _boom)
    r = client.get(path)
    assert r.status_code == 503 and r.json()["detail"]


@pytest.mark.parametrize("path", PATHS)
def test_db_unconfigured_is_503(harness, path):
    from fastapi.testclient import TestClient

    def no_db():
        raise DatabaseNotConfigured("DATABASE_URL is not set")
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = no_db
    try:
        with TestClient(app) as c:
            r = c.get(path)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 503 and "DATABASE_URL" in r.json()["detail"]


# ---------------------------------------------------------------------------
# History cache
# ---------------------------------------------------------------------------
def test_history_cache_ttl_invalidate_and_errors(harness, monkeypatch):
    calls = []
    clock = [1000.0]
    monkeypatch.setattr(history_cache, "_now", lambda: clock[0])
    monkeypatch.setattr(store, "load_history", lambda db: calls.append(1) or harness.history.copy())
    history_cache.invalidate()

    h1 = history_cache.get_history(None)
    e1 = history_cache.get_enriched(None)
    assert history_cache.get_history(None) is h1 and history_cache.get_enriched(None) is e1
    assert len(calls) == 1
    clock[0] += history_cache.TTL_SECONDS - 1
    history_cache.get_enriched(None)
    assert len(calls) == 1
    clock[0] += 2                                        # expired: history and replay rebuilt
    e2 = history_cache.get_enriched(None)
    assert len(calls) == 2 and e2 is not e1
    history_cache.invalidate()
    history_cache.get_history(None)
    assert len(calls) == 3

    history_cache.invalidate()
    monkeypatch.setattr(store, "load_history", _boom)
    with pytest.raises(OperationalError):
        history_cache.get_history(None)
    monkeypatch.setattr(store, "load_history", lambda db: calls.append(1) or harness.history.copy())
    assert len(history_cache.get_history(None)) == len(harness.history)   # failure not cached


def test_endpoints_share_one_history_load(client, harness, monkeypatch):
    calls = []
    monkeypatch.setattr(store, "load_history", lambda db: calls.append(1) or harness.history.copy())
    history_cache.invalidate()
    harness.upstream["PL"] = fx_payload((301, A, B, soon(3), "TIMED"))
    client.get("/upcoming")
    client.get(f"/teams/{quote(A)}")
    client.get(f"/teams/{quote(A)}/matches")
    client.get("/h2h", params={"a": A, "b": B})
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# team filters on /upcoming and /track-record
# ---------------------------------------------------------------------------
def test_upcoming_team_filter_before_limit(client, harness):
    harness.upstream["PL"] = fx_payload(
        (401, C, D, soon(2), "TIMED"),
        (402, B, A, soon(3), "TIMED"),
        (403, A, C, soon(4), "TIMED"),
    )
    ids = [m["fixture_id"] for m in client.get("/upcoming", params={"team": A}).json()]
    assert ids == [402, 403]
    ids = [m["fixture_id"] for m in client.get("/upcoming", params={"team": A, "limit": 1}).json()]
    assert ids == [402]
    both = client.get("/upcoming", params={"team": A, "league": "PL", "date_to": soon(3).date().isoformat()})
    assert [m["fixture_id"] for m in both.json()] == [402]
    assert client.get("/upcoming", params={"team": "Nobody FC"}).json() == []
    assert len(client.get("/upcoming").json()) == 3


def test_track_record_team_filter_and_echo(client, harness):
    harness.settled = (2, [settled_row(1), settled_row(2, result="A")])
    body = client.get("/track-record", params={"team": "H1"}).json()
    assert body["team"] == "H1"
    assert harness.settled_kwargs[-1]["team"] == "H1"
    plain = client.get("/track-record").json()
    assert plain["team"] is None and harness.settled_kwargs[-1]["team"] is None
    harness.settled = (0, [])
    empty = client.get("/track-record", params={"team": "Nobody"}).json()
    assert empty["n_settled"] == 0 and empty["team"] == "Nobody" and empty["backtest"] is not None


# ---------------------------------------------------------------------------
# next_fixture cache and cached history index
# ---------------------------------------------------------------------------
@pytest.fixture
def pipeline_calls(monkeypatch):
    """Counts /upcoming pipeline runs and drives the cache clock."""
    from src.api import upcoming

    calls, clock = [], [5000.0]
    real = upcoming.predict_upcoming
    monkeypatch.setattr(upcoming, "predict_upcoming", lambda *a, **k: calls.append(k.get("team")) or real(*a, **k))
    monkeypatch.setattr(history_cache, "_now", lambda: clock[0])
    return calls, clock


def test_next_fixture_cached_per_team(client, harness, pipeline_calls):
    calls, clock = pipeline_calls
    harness.upstream["PL"] = fx_payload((202, B, A, soon(5), "TIMED"))
    first = client.get(f"/teams/{quote(A)}").json()
    second = client.get(f"/teams/{quote(A)}").json()
    assert first["next_fixture_status"] == second["next_fixture_status"] == "ok"
    assert first["next_fixture"] == second["next_fixture"]
    assert calls == [A]                                   # second profile: no pipeline run
    client.get(f"/teams/{quote(B)}")                      # keyed by team
    assert calls == [A, B]
    # as_of is never cached and never runs the pipeline
    assert client.get(f"/teams/{quote(A)}?as_of=2025-01-01").json()["next_fixture_status"] == "unavailable"
    assert calls == [A, B]


def test_next_fixture_cache_ttl_and_invalidate(client, harness, pipeline_calls):
    calls, clock = pipeline_calls
    harness.upstream["PL"] = fx_payload((202, B, A, soon(5), "TIMED"))
    client.get(f"/teams/{quote(A)}")
    clock[0] += history_cache.FIXTURE_TTL_SECONDS - 1
    client.get(f"/teams/{quote(A)}")
    assert len(calls) == 1
    clock[0] += 2                                         # expired
    client.get(f"/teams/{quote(A)}")
    assert len(calls) == 2
    history_cache.invalidate()                            # cleared together with the history
    client.get(f"/teams/{quote(A)}")
    assert len(calls) == 3


def test_next_fixture_unavailable_cached_briefly_then_recovers(client, harness, pipeline_calls):
    calls, clock = pipeline_calls
    harness.upstream["PL"] = RuntimeError("down")
    assert client.get(f"/teams/{quote(A)}").json()["next_fixture_status"] == "unavailable"
    harness.upstream["PL"] = fx_payload((202, B, A, soon(5), "TIMED"))
    api_client.clear_cache()                              # upstream responses are cached too
    clock[0] += history_cache.FIXTURE_UNAVAILABLE_TTL_SECONDS - 1
    assert client.get(f"/teams/{quote(A)}").json()["next_fixture_status"] == "unavailable"
    assert len(calls) == 1
    clock[0] += 2                                         # short TTL elapsed: upstream retried
    assert client.get(f"/teams/{quote(A)}").json()["next_fixture_status"] == "ok"
    assert len(calls) == 2
    assert history_cache.FIXTURE_UNAVAILABLE_TTL_SECONDS < history_cache.FIXTURE_TTL_SECONDS


def test_next_fixture_cheap_unavailable_paths_not_cached(client, harness, monkeypatch, pipeline_calls):
    calls, _ = pipeline_calls
    harness.upstream["PL"] = fx_payload((202, B, A, soon(5), "TIMED"))
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY")
    assert client.get(f"/teams/{quote(A)}").json()["next_fixture_status"] == "unavailable"
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-key")
    assert client.get(f"/teams/{quote(A)}").json()["next_fixture_status"] == "ok"
    assert calls == [A]


def test_cached_payload_is_not_shared_mutable(client, harness, pipeline_calls):
    harness.upstream["PL"] = fx_payload((202, B, A, soon(5), "TIMED"))
    client.get(f"/teams/{quote(A)}")
    key = next(iter(history_cache._fixtures))
    got = history_cache.fixture_get(key)
    got[0]["home_team"] = "mutated"
    assert history_cache.fixture_get(key)[0]["home_team"] == B


def test_history_index_built_once_per_history_entry(client, harness, monkeypatch):
    calls = []
    real = team_stats._long
    monkeypatch.setattr(team_stats, "_long", lambda e: calls.append(1) or real(e))
    history_cache.invalidate()
    for _ in range(3):
        client.get(f"/teams/{quote(A)}")
        client.get("/teams/index")
    assert len(calls) == 1
    history_cache.invalidate()
    client.get(f"/teams/{quote(A)}")
    assert len(calls) == 2


def test_profile_as_of_rank_ignores_cached_full_history_index(client, harness):
    as_of = "2025-01-01"
    client.get(f"/teams/{quote(A)}")                      # warm the full-history index
    cached = client.get(f"/teams/{quote(A)}?as_of={as_of}").json()["elo"]
    hist = harness.history
    truncated = hist.loc[pd.to_datetime(hist["date"]).dt.normalize() < pd.Timestamp(as_of)]
    enr = team_stats.replay_elo(truncated)
    tm = team_stats.team_matches(enr, A)
    expected = team_stats.elo_summary(enr, tm, A, "PL")
    assert cached == expected
    full = client.get(f"/teams/{quote(A)}").json()["elo"]
    assert full["rating"] != cached["rating"]


def test_profile_rest_days_uncapped(client, harness, monkeypatch):
    last = dt.date.fromisoformat(client.get(f"/teams/{quote(A)}").json()["last_match_date"])
    monkeypatch.setattr(teams, "today", lambda: last + dt.timedelta(days=90))
    assert client.get(f"/teams/{quote(A)}").json()["rest_days"] == 90
