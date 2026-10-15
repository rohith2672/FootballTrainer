"""Synthetic match data shared by the model-training tests."""
import numpy as np
import pandas as pd
import pytest

from src.model.train import FEATURE_COLS


def make_matches(
    seasons=(2019, 2020, 2021, 2022),
    per_season=150,
    seed=0,
    leagues=None,
    with_odds=False,
    nan_frac=0.0,
    with_season=True,
):
    """Random matches with a weak, learnable signal in a couple of features.

    Several matches share a date (so tests exercise date-aware cutoffs).
    """
    rng = np.random.default_rng(seed)
    frames = []
    mid = 0
    for si, season in enumerate(seasons):
        start = pd.Timestamp(f"{season}-08-10")
        n_days = per_season // 3  # ~3 matches per matchday
        days = start + pd.to_timedelta(np.arange(n_days) * 3, unit="D")
        dates = np.repeat(days.values, 3)[:per_season]
        n = len(dates)
        feats = {c: rng.random(n) for c in FEATURE_COLS}
        edge = feats["home_form_pts_pg"] - feats["away_form_pts_pg"]
        logits = np.column_stack([0.9 * edge, np.full(n, -0.3), -0.9 * edge])
        probs = np.exp(logits)
        probs /= probs.sum(axis=1, keepdims=True)
        target = np.array([rng.choice(3, p=p) for p in probs])
        df = pd.DataFrame(feats)
        df["date"] = pd.to_datetime(dates)
        df["home_team"] = [f"H{(mid + i) % 9}" for i in range(n)]
        df["away_team"] = [f"A{(mid + i) % 7}" for i in range(n)]
        df["target"] = target
        if with_season:
            df["season"] = season
        if leagues:
            df["league"] = [leagues[i % len(leagues)] for i in range(n)]
        if with_odds:
            true = probs * 0.95
            inv = np.clip(true / true.sum(axis=1, keepdims=True) * 1.06, 0.02, None)
            odds = 1.0 / inv
            df["odds_home"], df["odds_draw"], df["odds_away"] = odds[:, 0], odds[:, 1], odds[:, 2]
            df.loc[df.index % 5 == 0, ["odds_home", "odds_draw", "odds_away"]] = np.nan
        frames.append(df)
        mid += n
    out = pd.concat(frames, ignore_index=True)
    if nan_frac:
        mask = rng.random((len(out), len(FEATURE_COLS))) < nan_frac
        vals = out[FEATURE_COLS].to_numpy(dtype=float, copy=True)
        vals[mask] = np.nan
        out[FEATURE_COLS] = vals
    return out


@pytest.fixture()
def mlflow_uri(tmp_path, monkeypatch):
    """File-store tracking URI under tmp_path (never the repo's mlflow.db/mlruns)."""
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
    return (tmp_path / "mlruns").as_uri()
