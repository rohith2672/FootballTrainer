import datetime
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api.main import app, compute_features_for_match
from src.database import get_db
from src.models import Match, Team


# ---------------------------------------------------------------------------
# Helpers to build fake ORM objects
# ---------------------------------------------------------------------------

def _make_team(name: str) -> MagicMock:
    t = MagicMock(spec=Team)
    t.name = name
    return t


def _make_match(
    id_: int,
    home: str,
    away: str,
    home_goals: int,
    away_goals: int,
    result: str,
    date: datetime.datetime,
    season: int,
) -> MagicMock:
    m = MagicMock(spec=Match)
    m.id = id_
    m.home_team = home
    m.away_team = away
    m.home_goals = home_goals
    m.away_goals = away_goals
    m.result = result
    m.date = date
    m.season = season
    return m


TEAM_A = "Arsenal FC"
TEAM_B = "Chelsea FC"

HISTORICAL_MATCHES = [
    _make_match(1, TEAM_A, TEAM_B, 2, 1, "H", datetime.datetime(2023, 8, 12), 2023),
    _make_match(2, TEAM_B, TEAM_A, 0, 1, "A", datetime.datetime(2023, 11, 5), 2023),
    _make_match(3, TEAM_A, TEAM_B, 1, 1, "D", datetime.datetime(2024, 1, 20), 2024),
]

ALL_TEAMS = [_make_team(TEAM_A), _make_team(TEAM_B)]


# ---------------------------------------------------------------------------
# DB mock factory
# ---------------------------------------------------------------------------

def _make_db(teams: list, matches: list) -> MagicMock:
    """Minimal fake SQLAlchemy session."""
    db = MagicMock()

    def _query(model_cls):
        q = MagicMock()

        if model_cls is Team:
            def _filter(*args, **kwargs):
                fq = MagicMock()
                # Extract team name from the binary expression's right operand
                fq.first.side_effect = lambda: next(
                    (
                        t for t in teams
                        if any(
                            hasattr(a, "right") and str(t.name) == str(a.right.value)
                            for a in args
                        )
                    ),
                    None,
                )
                return fq
            q.filter = _filter

            def _order_by(*a):
                oq = MagicMock()
                oq.all.return_value = sorted(teams, key=lambda t: t.name)
                return oq
            q.order_by = _order_by

        elif model_cls is Match:
            def _filter(*args, **kwargs):
                fq = MagicMock()
                def _order_by(*a):
                    oq = MagicMock()
                    oq.all.return_value = matches
                    return oq
                # chained .filter().filter().order_by()
                fq.filter.return_value.order_by = _order_by
                fq.order_by = _order_by
                return fq
            q.filter = _filter

        return q

    db.query.side_effect = _query
    return db


def _dep_override(db: MagicMock):
    def _dep():
        yield db
    return _dep


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_model():
    model = MagicMock()
    model.predict_proba.return_value = np.array([[0.4, 0.3, 0.3]])
    return model


@pytest.fixture
def client_with_db(fake_model, request):
    """
    Client fixture that accepts (teams, matches) via indirect parametrize or
    uses ALL_TEAMS + HISTORICAL_MATCHES as defaults.
    """
    teams, matches = getattr(request, "param", (ALL_TEAMS, HISTORICAL_MATCHES))
    db = _make_db(teams, matches)
    app.state.model = fake_model
    app.dependency_overrides[get_db] = _dep_override(db)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /predict endpoint
# ---------------------------------------------------------------------------

class TestPredictEndpoint:

    def test_valid_request_returns_probabilities(self, client_with_db):
        resp = client_with_db.post(
            "/predict",
            json={"home_team": TEAM_A, "away_team": TEAM_B, "date": "2024-03-01"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"home_win", "draw", "away_win"}
        total = body["home_win"] + body["draw"] + body["away_win"]
        assert abs(total - 1.0) < 1e-6
        for v in body.values():
            assert 0.0 <= v <= 1.0

    @pytest.mark.parametrize(
        "client_with_db",
        [([_make_team(TEAM_B)], [])],
        indirect=True,
    )
    def test_unknown_home_team_returns_422(self, client_with_db):
        resp = client_with_db.post(
            "/predict",
            json={"home_team": "Unknown FC", "away_team": TEAM_B, "date": "2024-03-01"},
        )
        assert resp.status_code == 422
        assert "Team not found" in resp.json()["detail"]

    @pytest.mark.parametrize(
        "client_with_db",
        [([_make_team(TEAM_A)], [])],
        indirect=True,
    )
    def test_unknown_away_team_returns_422(self, client_with_db):
        resp = client_with_db.post(
            "/predict",
            json={"home_team": TEAM_A, "away_team": "Unknown FC", "date": "2024-03-01"},
        )
        assert resp.status_code == 422
        assert "Team not found" in resp.json()["detail"]

    def test_invalid_date_format_returns_422(self, client_with_db):
        resp = client_with_db.post(
            "/predict",
            json={"home_team": TEAM_A, "away_team": TEAM_B, "date": "01-03-2024"},
        )
        assert resp.status_code == 422

    def test_same_team_returns_422(self, client_with_db):
        resp = client_with_db.post(
            "/predict",
            json={"home_team": TEAM_A, "away_team": TEAM_A, "date": "2024-03-01"},
        )
        assert resp.status_code == 422
        assert "differ" in resp.json()["detail"]

    def test_empty_team_name_returns_422(self, client_with_db):
        resp = client_with_db.post(
            "/predict",
            json={"home_team": "", "away_team": TEAM_B, "date": "2024-03-01"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: compute_features_for_match helper
# ---------------------------------------------------------------------------

class TestComputeFeaturesForMatch:

    def _make_simple_db(self, matches):
        db = MagicMock()
        q = MagicMock()
        db.query.return_value = q
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = matches
        return db

    def test_returns_array_of_correct_shape(self):
        db = self._make_simple_db(HISTORICAL_MATCHES)
        result = compute_features_for_match(
            db, TEAM_A, TEAM_B, datetime.date(2024, 3, 1)
        )
        assert result.shape == (1, 11)

    def test_no_history_returns_array(self):
        """Teams with zero history still return a (1, 11) array (may contain NaN)."""
        db = self._make_simple_db([])
        result = compute_features_for_match(
            db, TEAM_A, TEAM_B, datetime.date(2024, 3, 1)
        )
        assert result.shape == (1, 11)


# ---------------------------------------------------------------------------
# Tests: /health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:

    def test_health_returns_200(self, client_with_db):
        resp = client_with_db.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "model": "xgb_best", "version": "1.0.0"}


# ---------------------------------------------------------------------------
# Tests: /teams endpoint
# ---------------------------------------------------------------------------

class TestTeamsEndpoint:

    def test_teams_returns_sorted_list(self, client_with_db):
        resp = client_with_db.get("/teams")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert TEAM_A in body
        assert TEAM_B in body
        assert body == sorted(body)

    @pytest.mark.parametrize("client_with_db", [([], [])], indirect=True)
    def test_teams_empty_db_returns_empty_list(self, client_with_db):
        resp = client_with_db.get("/teams")
        assert resp.status_code == 200
        assert resp.json() == []
