"""/track-record with a mocked settled set (no DB)."""
import datetime as dt
import json
import math
import os

import numpy as np
import pytest

from src.api.track_record import backtest_block
from tests.helpers_api import (  # noqa: F401  (fixtures)
    MODEL_VERSION,
    api_env,
    client,
    db_override,
    harness,
    settled_row,
)

RESULTS = ["H", "D", "A", "H", "H", "A", "D", "H", "A", "H", "D", "H"]
PROBS = [(0.5, 0.3, 0.2), (0.2, 0.3, 0.5), (0.4, 0.3, 0.3)]
CODE = {"H": 0, "D": 1, "A": 2}


def _rows():
    rows = []
    for i, res in enumerate(RESULTS):
        rows.append(settled_row(
            i, league="PL" if i % 3 else "PD", result=res, probs=PROBS[i % 3],
        ))
    return rows


def _expected(rows):
    y = np.array([CODE[r["result"]] for r in rows])
    p = np.array([[r["home_win"], r["draw"], r["away_win"]] for r in rows])
    ll = -np.mean(np.log(p[np.arange(len(y)), y]))
    acc = np.mean(p.argmax(axis=1) == y)
    brier = np.mean(np.sum((p - np.eye(3)[y]) ** 2, axis=1))
    return ll, acc, brier


def test_metrics_from_settled_rows(client, harness):
    rows = _rows()
    harness.settled = (15, rows)
    harness.class_counts = [450, 250, 300]
    body = client.get("/track-record").json()

    ll, acc, brier = _expected(rows)
    assert body["model_version"] == MODEL_VERSION
    assert body["n_predictions"] == 15 and body["n_settled"] == len(rows)
    assert body["overall"]["log_loss"] == pytest.approx(ll, abs=1e-4)
    assert body["overall"]["accuracy"] == pytest.approx(acc, abs=1e-4)
    assert body["overall"]["brier"] == pytest.approx(brier, abs=1e-4)

    assert set(body["baselines"]) == {"class_prior", "uniform"}
    counts = np.array([450, 250, 300]) + 1.0
    prior = counts / counts.sum()
    exp_prior = -np.mean([math.log(prior[CODE[r["result"]]]) for r in rows])
    assert body["baselines"]["class_prior"]["log_loss"] == pytest.approx(exp_prior, abs=1e-4)
    assert body["baselines"]["class_prior"]["n"] == len(rows)
    assert body["baselines"]["uniform"]["log_loss"] == pytest.approx(math.log(3), abs=1e-4)

    assert [x["league"] for x in body["by_league"]] == ["PD", "PL"]
    assert sum(x["n"] for x in body["by_league"]) == len(rows)

    weeks = [t["week_start"] for t in body["timeline"]]
    assert weeks == sorted(weeks)
    assert all(dt.date.fromisoformat(w).weekday() == 0 for w in weeks)     # Mondays
    assert sum(t["n"] for t in body["timeline"]) == len(rows)

    recent = body["recent"]
    assert len(recent) == len(rows) and len(recent) <= 20
    dates = [r["date"] for r in recent]
    assert dates == sorted(dates, reverse=True)
    first = recent[0]
    assert first["correct"] == (np.argmax([first["home_win"], first["draw"], first["away_win"]])
                                == CODE[first["result"]])

    bt = body["backtest"]
    assert bt["source"] == "model_registry.json holdout"
    assert bt["best_model"] == "logistic_regression"
    assert bt["holdout_window"] == ["2025-08-15", "2026-05-24"]
    assert bt["holdout_log_loss"] == 0.975 and bt["holdout_accuracy"] == 0.52
    assert set(bt["baselines"]) == {"class_prior", "uniform", "elo"}
    assert bt["baselines"]["class_prior"] == 1.061 and bt["baselines"]["elo"] is None


def test_recent_is_capped_at_20(client, harness):
    rows = [settled_row(i, result="H") for i in range(30)]
    harness.settled = (30, rows)
    body = client.get("/track-record").json()
    assert len(body["recent"]) == 20 and body["n_settled"] == 30


def test_zero_settled_has_null_metrics_but_backtest(client, harness):
    harness.settled = (7, [])
    body = client.get("/track-record").json()
    assert body["n_predictions"] == 7 and body["n_settled"] == 0
    assert body["overall"] == {"log_loss": None, "accuracy": None, "brier": None}
    assert body["baselines"]["class_prior"]["log_loss"] is None
    assert body["baselines"]["uniform"]["log_loss"] is None
    assert body["by_league"] == [] and body["timeline"] == [] and body["recent"] == []
    assert body["backtest"]["holdout_log_loss"] == 0.975


def _all_keys(obj):
    """Every dict key anywhere in a JSON-like structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_keys(v)


def test_no_bookmaker_keys_anywhere(client, harness):
    """The bookmaker comparison is retired: no key may mention it, backtest included,
    even though the fixture registry still carries legacy bookmaker baselines."""
    rows = _rows()
    harness.settled = (len(rows), rows)
    harness.class_counts = [450, 250, 300]
    body = client.get("/track-record").json()
    assert body["by_league"] and body["timeline"] and body["recent"] and body["backtest"]
    keys = list(_all_keys(body))
    assert keys and not [k for k in keys if "bookmaker" in k.lower() or "odds" in k.lower()]


def test_committed_registry_backtest_has_no_bookmaker():
    """The committed registry still holds legacy bookmaker baselines; they are filtered on read."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "src", "model", "artifacts", "model_registry.json")
    with open(path, encoding="utf-8") as f:
        registry = json.load(f)
    bt = backtest_block(registry)
    assert bt is not None
    assert "elo" in bt["baselines"]
    assert not [k for k in bt["baselines"] if "bookmaker" in k.lower()]


def test_unknown_league_422(client):
    assert client.get("/track-record?league=XX").status_code == 422
    assert client.get("/track-record?weeks=0").status_code == 422


def test_works_without_a_model(client, harness):
    client.app.state.model_state.model = None
    harness.settled = (0, [])
    body = client.get("/track-record").json()
    assert body["n_settled"] == 0 and body["model_version"] is None
