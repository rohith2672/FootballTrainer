"""Dedicated router does not load a model, reach a publisher, or touch real DB."""
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import OperationalError

from src.api import news
from src.database import DatabaseNotConfigured


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(news.router)
    app.dependency_overrides[news.news_db] = lambda: Mock()
    monkeypatch.setattr(news, "read_news", Mock(return_value={
        "articles": [], "last_attempt_at": None, "last_success_at": None,
        "next_check_at": None, "status": "unavailable", "stale": True,
    }))
    with TestClient(app) as client:
        yield client


def test_news_available_without_model(client):
    response = client.get("/news")
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert news.read_news.call_args.args[1] == 50


@pytest.mark.parametrize("limit", [0, -1, 101, "bad"])
def test_api_limit_validation(client, limit):
    assert client.get(f"/news?limit={limit}").status_code == 422
    news.read_news.assert_not_called()


def test_explicit_api_limit(client):
    assert client.get("/news?limit=100").status_code == 200
    assert news.read_news.call_args.args[1] == 100


def test_db_error_returns_503(client):
    news.read_news.side_effect = OperationalError("select", {}, Exception("offline"))
    response = client.get("/news")
    assert response.status_code == 503
    assert response.json()["detail"] == "News storage unavailable"


def test_missing_db_config_returns_503(monkeypatch):
    def missing():
        raise DatabaseNotConfigured("missing")
        yield
    monkeypatch.setattr(news, "get_db", missing)
    app = FastAPI()
    app.include_router(news.router)
    with TestClient(app) as client:
        assert client.get("/news").status_code == 503
