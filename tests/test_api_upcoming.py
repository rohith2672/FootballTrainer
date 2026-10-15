"""/upcoming with mocked upstream (api_client._get) and mocked history loader."""
import datetime as dt
import numpy as np

from src.api import serving
from src.ingestion import api_client
from tests.helpers_api import (  # noqa: F401  (fixtures)
    MODEL_VERSION,
    NO_HISTORY_TEAM,
    api_env,
    client,
    db_override,
    fx_payload,
    harness,
    soon,
)

A, B, C, D = "Arsenal FC", "Chelsea FC", "Liverpool FC", "Everton FC"


def _pl(*extra):
    return fx_payload(
        (101, A, B, soon(3), "TIMED"),
        (102, C, D, soon(4), "SCHEDULED"),
        *extra,
    )


def test_predictions_sum_to_one_and_match_contract(client, harness):
    harness.upstream["PL"] = _pl()
    resp = client.get("/upcoming")
    assert resp.status_code == 200
    assert "X-Partial-Failure" not in resp.headers
    body = resp.json()
    assert [m["fixture_id"] for m in body] == [101, 102]      # TIMED and SCHEDULED, by kickoff
    m = body[0]
    assert set(m) == {
        "fixture_id", "league", "home_team", "away_team", "date", "kickoff",
        "home_win", "draw", "away_win", "prediction_available", "is_fallback", "reason",
        "model_version", "top_factors", "details",
    }
    assert abs(m["home_win"] + m["draw"] + m["away_win"] - 1.0) < 1e-9
    assert m["prediction_available"] is True and m["is_fallback"] is False and m["reason"] is None
    assert m["model_version"] == MODEL_VERSION
    assert m["league"] == "PL"
    assert m["kickoff"].endswith("Z") and m["kickoff"].startswith(m["date"])
    d = m["details"]
    assert set(d) == {"home", "away", "h2h"}
    assert set(d["home"]) == {
        "elo", "form_pts_pg", "goals_for_avg", "goals_against_avg",
        "shots_for_avg", "days_since_last", "form_n",
    }
    assert d["home"]["form_n"] == 5 and d["h2h"]["n"] >= 1


def test_top_factors_sorted_and_limited(client, harness):
    harness.upstream["PL"] = _pl()
    for m in client.get("/upcoming").json():
        factors = m["top_factors"]
        assert 0 < len(factors) <= 5
        mags = [abs(f["contribution"]) for f in factors]
        assert mags == sorted(mags, reverse=True)
        for f in factors:
            assert set(f) == {"feature", "label", "value", "contribution"}
            assert f["label"] and f["label"] != f["feature"]


def test_team_without_history_is_unavailable_never_033(client, harness):
    harness.upstream["PL"] = _pl((103, A, NO_HISTORY_TEAM, soon(5), "TIMED"))
    body = client.get("/upcoming").json()
    bad = next(m for m in body if m["fixture_id"] == 103)
    assert bad["prediction_available"] is False
    assert bad["is_fallback"] is True
    assert bad["home_win"] is None and bad["draw"] is None and bad["away_win"] is None
    assert bad["reason"] == f"No match history for {NO_HISTORY_TEAM}"
    assert bad["top_factors"] == []
    assert bad["details"] is None
    for m in body:        # the old silent fallback triple must never appear
        triple = [m["home_win"], m["draw"], m["away_win"]]
        assert triple != [0.33, 0.34, 0.33]
    ok = next(m for m in body if m["fixture_id"] == 101)
    assert ok["prediction_available"] is True       # other fixtures unaffected


def test_both_teams_missing_reason_names_both(client, harness):
    harness.upstream["PL"] = fx_payload((9, "Celtic FC", "Rangers FC", soon(2), "TIMED"))
    m = client.get("/upcoming").json()[0]
    assert m["reason"] == "No match history for Celtic FC and Rangers FC"


def test_model_exception_marks_fixture_unavailable(client, harness, caplog):
    class Broken:
        def predict_proba(self, X):
            raise RuntimeError("boom")

    harness.upstream["PL"] = _pl()
    client.app.state.model_state.model = Broken()
    with caplog.at_level("ERROR"):
        body = client.get("/upcoming").json()
    assert all(m["prediction_available"] is False and m["reason"] == "Prediction error" for m in body)
    assert all(m["home_win"] is None for m in body)
    assert "Prediction failed" in caplog.text


def test_non_finite_model_output_is_prediction_error(client, harness):
    class Nan:
        def predict_proba(self, X):
            return np.full((len(X), 3), np.nan)

    harness.upstream["PL"] = _pl()
    client.app.state.model_state.model = Nan()
    assert all(m["reason"] == "Prediction error" for m in client.get("/upcoming").json())


def test_partial_failure_header(client, harness):
    harness.upstream["PL"] = _pl()
    harness.upstream["PD"] = RuntimeError("upstream down")
    harness.upstream["SA"] = RuntimeError("upstream down")
    resp = client.get("/upcoming")
    assert resp.status_code == 200
    assert resp.headers["X-Partial-Failure"] == "PD,SA"
    assert len(resp.json()) == 2


def test_all_leagues_failing_is_503(client, harness):
    from src.features.columns import LEAGUES

    for code in LEAGUES:
        harness.upstream[code] = RuntimeError("down")
    resp = client.get("/upcoming")
    assert resp.status_code == 503
    assert "detail" in resp.json()


def test_missing_api_key_is_503(client, harness, monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)
    resp = client.get("/upcoming")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Fixture source not configured (FOOTBALL_DATA_API_KEY missing)"
    assert harness.upstream_calls == []


def test_503_when_model_not_loaded(client, harness):
    client.app.state.model_state.model = None
    resp = client.get("/upcoming")
    assert resp.status_code == 503 and resp.json()["detail"] == "Model not loaded"


def test_cache_hit_avoids_second_upstream_call(client, harness):
    harness.upstream["PL"] = _pl()
    assert client.get("/upcoming").status_code == 200
    first = len(harness.upstream_calls)
    assert first == 6                                       # all six leagues, once each
    assert client.get("/upcoming").status_code == 200
    assert len(harness.upstream_calls) == first            # served from the TTL cache


def test_failures_are_not_cached(client, harness):
    harness.upstream["PL"] = RuntimeError("down")
    assert client.get("/upcoming?league=PL").status_code == 503
    harness.upstream["PL"] = _pl()
    assert client.get("/upcoming?league=PL").status_code == 200


def test_league_filter_only_fetches_that_league(client, harness):
    harness.upstream["PL"] = _pl()
    body = client.get("/upcoming?league=PL").json()
    assert harness.upstream_calls == ["PL"]
    assert len(body) == 2


def test_invalid_params_422(client):
    assert client.get("/upcoming?league=XX").status_code == 422
    assert client.get("/upcoming?date_from=18-10-2026").status_code == 422
    assert client.get("/upcoming?limit=0").status_code == 422


def test_date_and_limit_filters(client, harness):
    harness.upstream["PL"] = _pl((103, A, C, soon(10), "TIMED"))
    day = soon(4).date().isoformat()
    assert [m["fixture_id"] for m in client.get(f"/upcoming?date_from={day}").json()] == [102, 103]
    assert [m["fixture_id"] for m in client.get(f"/upcoming?date_to={day}").json()] == [101, 102]
    assert [m["fixture_id"] for m in client.get("/upcoming?limit=1").json()] == [101]


def test_non_upcoming_and_tbd_fixtures_are_skipped(client, harness):
    payload = _pl((104, A, B, soon(6), "POSTPONED"))
    payload["matches"].append({"id": 105, "status": "TIMED", "utcDate": "2099-01-01T12:00:00Z",
                               "homeTeam": {"name": None}, "awayTeam": {"name": B}})
    harness.upstream["PL"] = payload
    assert [m["fixture_id"] for m in client.get("/upcoming").json()] == [101, 102]


def test_persists_only_available_future_predictions(client, harness):
    past = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(hours=1)
    harness.upstream["PL"] = _pl(
        (103, A, NO_HISTORY_TEAM, soon(5), "TIMED"),      # unavailable -> not stored
        (104, B, C, past, "TIMED"),                       # already kicked off -> not stored
    )
    assert client.get("/upcoming").status_code == 200
    assert len(harness.persisted) == 1
    rows, version = harness.persisted[0]
    assert version == MODEL_VERSION
    assert sorted(r["fixture_id"] for r in rows) == [101, 102]


def test_persistence_failure_does_not_break_upcoming(client, harness):
    harness.upstream["PL"] = _pl()
    harness.persist_error = RuntimeError("db down")
    resp = client.get("/upcoming")
    assert resp.status_code == 200 and len(resp.json()) == 2


def test_february_fixture_uses_previous_year_season_key():
    fx = {"fixture_id": 1, "league": "PL", "home_team": A, "away_team": B,
          "kickoff": dt.datetime(2026, 2, 14, 15, 0)}
    frame = serving.build_fixture_frame([fx, {**fx, "kickoff": dt.datetime(2026, 8, 22, 12, 30)}])
    assert list(frame["season"]) == [2025, 2026]
    assert frame["home_goals"].isna().all()


def test_cache_unit_ttl_and_thread_safety(monkeypatch):
    import threading

    api_client.clear_cache()
    calls = []

    def fake(code):
        calls.append(code)
        return {"matches": [], "code": code}

    monkeypatch.setattr(api_client, "get_upcoming_matches", fake)
    threads = [threading.Thread(target=api_client.get_upcoming_matches_cached, args=("PL",))
               for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert calls == ["PL"]                                 # concurrent callers share one fetch
    api_client.get_upcoming_matches_cached("PL", ttl=0)    # expired -> refetch
    assert calls == ["PL", "PL"]
    api_client.clear_cache()
