"""/health, /predict and /teams (no real pickle, database or network)."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.features.columns import FEATURE_COLS, FEATURE_LABELS
from tests.helpers_api import (  # noqa: F401  (fixtures)
    GIT_COMMIT,
    MODEL_VERSION,
    NO_HISTORY_TEAM,
    TEAMS,
    api_env,
    client,
    db_override,
    harness,
    write_artifacts,
)

A, B = "Arsenal FC", "Chelsea FC"


def test_feature_labels_cover_exactly_feature_cols():
    assert set(FEATURE_LABELS) == set(FEATURE_COLS)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------
class TestHealth:
    def test_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["model_loaded"] is True
        assert body["db"] == "ok"
        assert body["model"] == "logistic_regression"
        assert body["model_version"] == MODEL_VERSION
        assert body["trained_at"] == "2026-05-13 10:41:46"
        assert body["version"] == "2.0.0"

    def test_degraded_when_db_down(self, client, harness):
        harness.db_status = "down"
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded"
        assert resp.json()["db"] == "down"

    def test_503_without_model(self, tmp_path, monkeypatch, harness, db_override):
        monkeypatch.setenv("BEST_MODEL_PATH", str(tmp_path / "nope.pkl"))
        monkeypatch.setenv("REGISTRY_PATH", str(tmp_path / "nope.json"))
        with TestClient(app) as c:     # startup must not crash
            resp = c.get("/health")
        assert resp.status_code == 503
        assert resp.json()["model_loaded"] is False

    def test_503_when_pickle_missing_but_registry_present(self, tmp_path, monkeypatch, harness, db_override):
        sub = tmp_path / "sub"
        sub.mkdir()
        _, registry = write_artifacts(sub, with_model=False)
        monkeypatch.setenv("BEST_MODEL_PATH", str(sub / "best_model.pkl"))
        monkeypatch.setenv("REGISTRY_PATH", str(registry))
        with TestClient(app) as c:
            assert c.get("/health").status_code == 503

    def test_503_when_pickle_is_corrupt(self, tmp_path, monkeypatch, harness, db_override):
        sub = tmp_path / "sub"
        sub.mkdir()
        model, registry = write_artifacts(sub)
        model.write_bytes(b"not a pickle")
        monkeypatch.setenv("BEST_MODEL_PATH", str(model))
        monkeypatch.setenv("REGISTRY_PATH", str(registry))
        with TestClient(app) as c:
            assert c.get("/health").status_code == 503

    @pytest.mark.parametrize("cols", [list(reversed(FEATURE_COLS)), FEATURE_COLS[:11], None])
    def test_refuses_mismatched_feature_layout(self, tmp_path, monkeypatch, harness, db_override, cols):
        model, registry = write_artifacts(tmp_path)
        reg = json.loads(registry.read_text())
        if cols is None:
            del reg["feature_cols"]            # the stale 3-key registries have none
        else:
            reg["feature_cols"] = cols
        registry.write_text(json.dumps(reg))
        monkeypatch.setenv("BEST_MODEL_PATH", str(model))
        monkeypatch.setenv("REGISTRY_PATH", str(registry))
        with TestClient(app) as c:
            assert c.get("/health").status_code == 503
            resp = c.post("/predict", json={"home_team": A, "away_team": B, "date": "2026-03-01"})
            assert resp.status_code == 503
            assert resp.json()["detail"] == "Model not loaded"

    def test_cors_does_not_allow_credentials_or_wildcard(self, client):
        resp = client.options(
            "/health",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
        )
        assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert "access-control-allow-credentials" not in resp.headers


# ---------------------------------------------------------------------------
# /predict
# ---------------------------------------------------------------------------
class TestPredict:
    def test_valid_request_returns_probabilities(self, client):
        resp = client.post("/predict", json={"home_team": A, "away_team": B, "date": "2026-03-01"})
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"home_win", "draw", "away_win"}
        assert abs(sum(body.values()) - 1.0) < 1e-6
        assert all(0.0 <= v <= 1.0 for v in body.values())

    def test_503_without_model(self, tmp_path, monkeypatch, harness, db_override):
        monkeypatch.setenv("BEST_MODEL_PATH", str(tmp_path / "nope.pkl"))
        with TestClient(app) as c:
            resp = c.post("/predict", json={"home_team": A, "away_team": B, "date": "2026-03-01"})
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Model not loaded"

    def test_unknown_team_422(self, client):
        for body in (
            {"home_team": "Unknown FC", "away_team": B, "date": "2026-03-01"},
            {"home_team": A, "away_team": "Unknown FC", "date": "2026-03-01"},
        ):
            resp = client.post("/predict", json=body)
            assert resp.status_code == 422
            assert "Team not found: Unknown FC" in resp.json()["detail"]

    def test_team_without_history_422_not_made_up_probabilities(self, client, harness):
        harness.team_names = sorted(TEAMS + [NO_HISTORY_TEAM])
        resp = client.post(
            "/predict", json={"home_team": A, "away_team": NO_HISTORY_TEAM, "date": "2026-03-01"}
        )
        assert resp.status_code == 422
        assert f"No match history for {NO_HISTORY_TEAM}" in resp.json()["detail"]

    def test_invalid_date_format_422(self, client):
        resp = client.post("/predict", json={"home_team": A, "away_team": B, "date": "01-03-2024"})
        assert resp.status_code == 422

    def test_same_team_422(self, client):
        resp = client.post("/predict", json={"home_team": A, "away_team": A, "date": "2026-03-01"})
        assert resp.status_code == 422
        assert "differ" in resp.json()["detail"]

    def test_empty_team_name_422(self, client):
        resp = client.post("/predict", json={"home_team": "", "away_team": B, "date": "2026-03-01"})
        assert resp.status_code == 422

    def test_date_before_all_history_is_rejected_not_faked(self, client):
        resp = client.post("/predict", json={"home_team": A, "away_team": B, "date": "2001-01-01"})
        assert resp.status_code == 422
        assert "No match history" in resp.json()["detail"]

    def test_model_error_is_500_not_fallback_probabilities(self, client):
        class Broken:
            def predict_proba(self, X):
                raise RuntimeError("boom")

        app.state.model_state.model = Broken()
        resp = client.post("/predict", json={"home_team": A, "away_team": B, "date": "2026-03-01"})
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /teams
# ---------------------------------------------------------------------------
class TestTeams:
    def test_sorted_list(self, client):
        resp = client.get("/teams")
        assert resp.status_code == 200
        assert resp.json() == sorted(TEAMS)

    def test_empty(self, client, harness):
        harness.team_names = []
        assert client.get("/teams").json() == []
