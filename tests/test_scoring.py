"""Tests for src/model/scoring.py (overall and per-league probability scores)."""
import math

import numpy as np
import pandas as pd
import pytest

from src.model import scoring as S


def test_brier_perfect_uniform_and_worst():
    y = np.array([0, 1, 2])
    assert S.brier_3(y, np.eye(3)) == 0.0
    assert S.brier_3(y, np.full((3, 3), 1 / 3)) == pytest.approx(2 / 3)
    assert S.brier_3(y, np.eye(3)[[1, 2, 0]]) == pytest.approx(2.0)


def test_draw_rate_confusion_and_score_all():
    y = np.array([0, 1, 2, 1])
    p = np.array([[0.6, 0.3, 0.1], [0.2, 0.5, 0.3], [0.1, 0.2, 0.7], [0.5, 0.3, 0.2]])
    assert S.draw_prediction_rate(p) == 0.25
    assert S.confusion_3(y, p) == [[1, 0, 0], [1, 1, 0], [0, 0, 1]]
    s = S.score_all(y, p)
    assert s["n"] == 4 and s["accuracy"] == 0.75
    assert s["log_loss"] == pytest.approx(-np.mean(np.log([0.6, 0.5, 0.7, 0.3])))
    assert s["mean_draw_prob"] == pytest.approx(0.325)
    assert S.score_all([], np.zeros((0, 3)))["log_loss"] is None


def test_per_league_scores_split_rows_by_league():
    df = pd.DataFrame({"league": ["PL", "PL", "SA"], "target": [0, 2, 1]})
    p = np.array([[0.5, 0.3, 0.2], [0.2, 0.3, 0.5], [0.3, 0.4, 0.3]])
    out = S.per_league_scores(df, p)
    assert list(out) == ["PL", "SA"]
    assert out["PL"]["n"] == 2 and out["PL"]["log_loss"] == pytest.approx(-math.log(0.5))
    assert out["SA"]["log_loss"] == pytest.approx(-math.log(0.4))
    assert S.per_league_scores(df.drop(columns=["league"]), p) is None
    assert set(S.score_by_group(df["target"], p, df["league"], min_rows=2)) == {"PL"}
