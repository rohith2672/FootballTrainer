"""Shared fixtures/helpers for the API tests: no real pickle, DB or network."""
import datetime as dt
import itertools
import json
import pickle
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from src.api import store
from src.api.main import app
from src.database import get_db
from src.features.columns import FEATURE_COLS
from src.ingestion import api_client
from src.ingestion.seasons import season_start_year

TEAMS = ["Arsenal FC", "Chelsea FC", "Liverpool FC", "Everton FC"]
NO_HISTORY_TEAM = "Celtic FC"
TRAINED_AT = "2026-05-13 10:41:46"
GIT_COMMIT = "abc1234"
MODEL_VERSION = f"logistic_regression@{GIT_COMMIT} 2026-05-13"


def make_history(seasons=(2023, 2024, 2025), seed=0) -> pd.DataFrame:
    """Finished PL matches: every ordered pair of TEAMS once per season, 15:00 kickoffs."""
    rng = np.random.default_rng(seed)
    rows, mid = [], 0
    for season in seasons:
        day = dt.datetime(season, 8, 16, 15, 0)
        for k, (home, away) in enumerate(itertools.permutations(TEAMS, 2)):
            mid += 1
            ko = day + dt.timedelta(days=7 * (k // 2))   # two matches share each day
            rows.append({
                "id": mid, "date": ko, "kickoff": ko, "season": season_start_year(ko),
                "league": "PL", "home_team": home, "away_team": away,
                "home_goals": int(rng.poisson(1.5)), "away_goals": int(rng.poisson(1.1)),
                "home_shots": float(rng.integers(5, 20)), "away_shots": float(rng.integers(5, 20)),
                "home_shots_on_target": float(rng.integers(1, 9)),
                "away_shots_on_target": float(rng.integers(1, 9)),
            })
    return pd.DataFrame(rows)


def write_artifacts(directory, feature_cols=None, with_model=True):
    """Pickle a tiny imputer+LogisticRegression on synthetic data and write a registry."""
    rng = np.random.default_rng(1)
    X = rng.random((300, len(FEATURE_COLS)))
    y = rng.integers(0, 3, 300)
    model = Pipeline([("imp", SimpleImputer()), ("lr", LogisticRegression(max_iter=500))]).fit(X, y)
    model_path = directory / "best_model.pkl"
    registry_path = directory / "model_registry.json"
    if with_model:
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
    registry = {
        "best_model": "logistic_regression",
        "git_commit": GIT_COMMIT,
        "trained_at": TRAINED_AT,
        "log_loss": 1.0,
        "holdout_log_loss": 0.975,
        "holdout_accuracy": 0.52,
        "holdout_window": {"min_date": "2025-08-15 00:00:00", "max_date": "2026-05-24 00:00:00"},
        "baselines": {
            "bookmaker": {"holdout_log_loss": 0.962},
            "class_prior": {"holdout_log_loss": 1.061},
            "uniform": {"holdout_log_loss": 1.0986},
            "elo": {"holdout_log_loss": None},
        },
        "feature_cols": list(FEATURE_COLS if feature_cols is None else feature_cols),
    }
    with open(registry_path, "w") as f:
        json.dump(registry, f)
    return model_path, registry_path


def fx_payload(*specs):
    """football-data.org style payload; specs = (id, home, away, kickoff datetime, status)."""
    return {"matches": [
        {
            "id": fid, "status": status,
            "utcDate": ko.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "homeTeam": {"name": home}, "awayTeam": {"name": away},
        }
        for fid, home, away, ko, status in specs
    ]}


def soon(days=3, hour=15):
    base = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    return (base + dt.timedelta(days=days)).replace(hour=hour)


class ApiHarness:
    """Handles to what the client fixture patched."""

    def __init__(self):
        self.history = make_history()
        self.team_names = sorted(TEAMS)
        self.upstream = {}            # league -> payload | Exception
        self.upstream_calls = []      # league codes actually requested
        self.persisted = []           # (rows, model_version)
        self.persist_error = None
        self.db_status = "ok"
        self.settled = (0, [])
        self.class_counts = None


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    model_path, registry_path = write_artifacts(tmp_path)
    monkeypatch.setenv("BEST_MODEL_PATH", str(model_path))
    monkeypatch.setenv("REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "test-key")
    api_client.clear_cache()
    yield tmp_path
    api_client.clear_cache()


@pytest.fixture
def harness(api_env, monkeypatch):
    h = ApiHarness()

    monkeypatch.setattr(store, "load_history", lambda db: h.history.copy())
    monkeypatch.setattr(store, "list_team_names", lambda db: list(h.team_names))
    monkeypatch.setattr(store, "ping_db", lambda timeout=2.0: h.db_status)
    monkeypatch.setattr(store, "fetch_settled", lambda db, **kw: h.settled)
    monkeypatch.setattr(store, "class_counts_before", lambda db, day, league=None: h.class_counts)

    def persist(db, rows, model_version, now=None):
        if h.persist_error:
            raise h.persist_error
        h.persisted.append((list(rows), model_version))
        return len(rows)

    monkeypatch.setattr(store, "persist_predictions", persist)

    def fake_get(path, params=None, retries=3):
        league = path.split("/")[2]
        h.upstream_calls.append(league)
        out = h.upstream.get(league, {"matches": []})
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(api_client, "_get", fake_get)
    return h


@pytest.fixture
def db_override():
    def _db():
        yield MagicMock()

    app.dependency_overrides[get_db] = _db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(harness, db_override):
    with TestClient(app) as c:
        yield c


def settled_row(i, league="PL", result="H", probs=(0.5, 0.3, 0.2), odds=(2.0, 3.5, 4.0),
                kickoff=None):
    return {
        "fixture_id": 1000 + i, "league": league,
        "kickoff": kickoff or dt.datetime(2026, 10, 3, 15, 0) + dt.timedelta(days=i),
        "home_team": f"H{i}", "away_team": f"A{i}",
        "home_win": probs[0], "draw": probs[1], "away_win": probs[2], "result": result,
        "odds_home": odds[0] if odds else None,
        "odds_draw": odds[1] if odds else None,
        "odds_away": odds[2] if odds else None,
    }


ns = SimpleNamespace
