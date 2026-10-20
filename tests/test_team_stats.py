"""Pure team-analysis functions (src/api/team_stats.py): Elo replay parity, leakage, stats."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from src.api import team_stats as ts
from src.features.engine import compute_features
from tests.helpers_features import make_league_matches, match_row


def rich_history(seed=3) -> pd.DataFrame:
    """Two leagues, three seasons, CL ties, a promoted team, a CL-only side and
    a team playing twice on one day; rows shuffled (the replay must sort)."""
    df = make_league_matches(leagues=("PL", "PD"), seasons=(2018, 2019, 2020), n_teams=8,
                             seed=seed, with_shots=True, with_cl=True)
    late = df["season"] >= 2019                               # PL_T7 relegated, PL_NEW promoted
    for col in ("home_team", "away_team"):
        df.loc[late & (df[col] == "PL_T7"), col] = "PL_NEW"
    extra = [
        match_row(90001, "2019-09-25", "CLONLY", "PL_T0", 2, 1, league="CL", season=2019),
        match_row(90002, "2019-10-09", "PL_T0", "CLONLY", 0, 0, league="CL", season=2019),
        match_row(90003, "2020-03-03", "PD_T2", "CLONLY", 3, 0, league="CL", season=2019),
    ]
    day = df.loc[(df["home_team"] == "PL_T0") & (df["season"] == 2020), "date"].iloc[3]
    extra.append(match_row(90004, day, "PL_T5", "PL_T0", 1, 1, league="PL", season=2020))  # same-day double
    df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
    return df.sample(frac=1.0, random_state=7).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Elo replay
# ---------------------------------------------------------------------------
def test_replayed_pre_match_elo_equals_engine_features():
    hist = rich_history()
    feats = compute_features(hist)
    enr = ts.replay_elo(hist)
    assert len(enr) == len(hist)
    exp_home = feats.loc[enr["src_index"], "home_elo"].to_numpy()
    exp_away = feats.loc[enr["src_index"], "away_elo"].to_numpy()
    np.testing.assert_allclose(enr["home_elo_before"].to_numpy(dtype=float), exp_home, rtol=0, atol=1e-9)
    np.testing.assert_allclose(enr["away_elo_before"].to_numpy(dtype=float), exp_away, rtol=0, atol=1e-9)
    # the hard branches were exercised
    assert "PL_NEW" in set(enr["home_team"]) and "CLONLY" in set(enr["home_team"])


def test_replay_parity_with_fixture_rows_appended():
    """Fixtures (null goals) are dropped by the replay and leave the engine state untouched."""
    hist = rich_history(seed=5)
    fx = pd.DataFrame([match_row(99999, "2020-12-30", "PL_T0", "PL_T1", None, None, season=2020)])
    feats = compute_features(pd.concat([hist, fx], ignore_index=True))
    enr = ts.replay_elo(hist)
    np.testing.assert_allclose(
        enr["home_elo_before"].to_numpy(dtype=float),
        feats.loc[enr["src_index"], "home_elo"].to_numpy(), atol=1e-9, rtol=0,
    )


def test_elo_after_carries_to_next_match_within_a_season():
    enr = ts.replay_elo(rich_history())
    tm = ts.team_matches(enr, "PL_T3")
    same = (tm["season"].to_numpy()[1:] == tm["season"].to_numpy()[:-1]) & (
        tm["day"].to_numpy()[1:] != tm["day"].to_numpy()[:-1])
    np.testing.assert_allclose(tm["elo_before"].to_numpy()[1:][same], tm["elo_after"].to_numpy()[:-1][same])
    # new season: regression toward the league mean, so before != previous after
    new = tm["season"].to_numpy()[1:] != tm["season"].to_numpy()[:-1]
    assert new.any()
    assert not np.allclose(tm["elo_before"].to_numpy()[1:][new], tm["elo_after"].to_numpy()[:-1][new])


def test_replay_does_not_mutate_input_and_handles_empty():
    hist = rich_history()
    copy = hist.copy()
    ts.replay_elo(hist)
    pd.testing.assert_frame_equal(hist, copy)
    empty = ts.replay_elo(hist.iloc[:0])
    assert empty.empty and ts.team_matches(empty, "X").empty


# ---------------------------------------------------------------------------
# Leakage: as_of uses strictly earlier match days only
# ---------------------------------------------------------------------------
def test_profile_as_of_equals_profile_of_truncated_history():
    hist = rich_history()
    team = "PL_T0"
    as_of = dt.date(2020, 10, 1)
    future = pd.DataFrame([
        match_row(80001, "2020-10-01", team, "PL_T1", 9, 0, season=2020, home_shots=40, away_shots=1),  # same day: excluded
        match_row(80002, "2020-10-20", "PL_T2", team, 0, 7, season=2020),
        match_row(80003, "2021-08-20", team, "PL_T3", 5, 0, season=2021),
    ])
    full = pd.concat([hist, future], ignore_index=True)
    truncated = full.loc[pd.to_datetime(full["date"]).dt.normalize() < pd.Timestamp(as_of)]

    a = ts.build_profile(ts.replay_elo(full), team, "PL", as_of=as_of, today=dt.date(2026, 1, 1))
    b = ts.build_profile(ts.replay_elo(truncated), team, "PL", as_of=None, today=as_of)
    assert a.pop("as_of") == "2020-10-01" and b.pop("as_of") is None
    assert a == b
    assert a["last_match_date"] < "2020-10-01"
    assert a["season"]["season"] == 2020
    # sanity: without as_of the blowouts are visible
    c = ts.build_profile(ts.replay_elo(full), team, "PL", as_of=None, today=dt.date(2026, 1, 1))
    assert c["last_match_date"] == "2021-08-20" and c["season"]["season"] == 2021
    assert c["form"] != a["form"] or c["elo"] != a["elo"]


# ---------------------------------------------------------------------------
# Hand-built stats
# ---------------------------------------------------------------------------
def small_history() -> pd.DataFrame:
    rows = [
        # season 2023 (previous)
        match_row(1, "2024-04-01", "A", "B", 1, 0, home_shots=10, away_shots=5,
                  home_shots_on_target=4, away_shots_on_target=1),
        # season 2024
        match_row(2, "2024-08-10", "A", "B", 2, 2, home_shots=12, away_shots=8,
                  home_shots_on_target=5, away_shots_on_target=3),
        match_row(3, "2024-08-17", "C", "A", 0, 3, home_shots=6, away_shots=14,
                  home_shots_on_target=2, away_shots_on_target=7),
        match_row(4, "2024-09-18", "A", "X", 1, 1, league="CL", season=2024),        # no shots
        match_row(5, "2024-08-24", "A", "C", 0, 1, home_shots=9, away_shots=9,
                  home_shots_on_target=3, away_shots_on_target=4),
        match_row(6, "2024-09-01", "B", "A", 1, 2, home_shots=7, away_shots=11,
                  home_shots_on_target=None, away_shots_on_target=None),
        match_row(7, "2024-09-28", "B", "C", 4, 0),
    ]
    return pd.DataFrame(rows)


def test_form_season_averages_and_rest():
    enr = ts.replay_elo(small_history())
    p = ts.build_profile(enr, "A", "PL", as_of=None, today=dt.date(2024, 10, 1))
    # chronological: 04-01 W, 08-10 D, 08-17 W, 08-24 L, 09-01 W, 09-18 (CL) D
    assert p["form"] == {"last5": "DWLWD", "pts_pg": round(8 / 5, 3), "n": 5}
    s = p["season"]
    assert (s["season"], s["played"], s["w"], s["d"], s["l"], s["gf"], s["ga"], s["pts"]) == (
        2024, 4, 2, 1, 1, 7, 4, 7)                                  # CL excluded
    assert s["home"] == {"played": 2, "w": 0, "d": 1, "l": 1, "gf": 2, "ga": 3}
    assert s["away"] == {"played": 2, "w": 2, "d": 0, "l": 0, "gf": 5, "ga": 1}
    av = p["averages"]
    assert av["n"] == 6 and av["n_shots"] == 5                      # CL row has no shots
    assert av["goals_for"] == round(9 / 6, 3) and av["goals_against"] == round(5 / 6, 3)
    assert av["shots_for"] == round((10 + 12 + 14 + 9 + 11) / 5, 3)
    assert av["sot_for"] == round((4 + 5 + 7 + 3) / 4, 3)          # one row lacks SoT
    assert av["clean_sheet_rate"] == round(2 / 6, 3)
    assert av["btts_rate"] == round(3 / 6, 3)
    assert av["over25_rate"] == round(3 / 6, 3)
    assert p["last_match_date"] == "2024-09-18" and p["rest_days"] == 13
    assert p["elo"]["rating"] == round(ts.team_matches(enr, "A")["elo_after"].iloc[-1], 1)


def test_empty_profile_for_team_without_matches():
    enr = ts.replay_elo(small_history())
    p = ts.build_profile(enr, "Nobody", None, as_of=None, today=dt.date(2024, 10, 1))
    assert p["form"] == {"last5": "", "pts_pg": None, "n": 0}
    assert p["season"] is None and p["rest_days"] is None and p["last_match_date"] is None
    assert p["elo"] == {"rating": None, "rank_in_league": None, "league_size": None, "change_last_5": None}
    assert p["averages"]["n"] == 0 and all(
        v is None for k, v in p["averages"].items() if k not in ("n", "n_shots"))


def test_change_last_5_and_rank():
    enr = ts.replay_elo(small_history())
    tm = ts.team_matches(enr, "A")
    e = ts.elo_summary(enr, tm, "A", "PL")
    last5 = tm.tail(5)
    assert e["change_last_5"] == round(last5["elo_after"].iloc[-1] - last5["elo_before"].iloc[0], 1)
    ratings = ts.latest_ratings(enr)
    order = sorted(["A", "B", "C"], key=lambda t: -ratings[t])         # X is CL-only: excluded
    assert e["league_size"] == 3 and e["rank_in_league"] == order.index("A") + 1
    assert ts.league_rank(enr, "X", None) == (None, None)


def test_team_index_league_resolution():
    enr = ts.replay_elo(small_history())
    idx = ts.team_index([("A", "PL"), ("X", "CL"), ("Z", "PD")], enr)
    # teams.league "CL" -> null; history fills B / C; PD < PL alphabetically; null last
    assert idx == [
        {"name": "Z", "league": "PD"},
        {"name": "A", "league": "PL"}, {"name": "B", "league": "PL"}, {"name": "C", "league": "PL"},
        {"name": "X", "league": None},
    ]


def test_match_list_and_elo_points():
    enr = ts.replay_elo(small_history())
    tm = ts.team_matches(enr, "A")
    rows = ts.match_list(tm, limit=3)
    assert [r["date"] for r in rows] == ["2024-09-18", "2024-09-01", "2024-08-24"]
    cl = rows[0]
    assert cl["league"] == "CL" and cl["venue"] == "home" and cl["opponent"] == "X"
    assert cl["shots_for"] is None and cl["result"] == "D"
    assert rows[1]["venue"] == "away" and rows[1]["gf"] == 2 and rows[1]["ga"] == 1 and rows[1]["result"] == "W"
    assert rows[1]["sot_for"] is None and rows[1]["shots_for"] == 11
    assert all(r["venue"] == "away" for r in ts.match_list(tm, limit=10, venue="away"))
    pts = ts.elo_points(tm, dt.date(2024, 8, 24))
    assert [p["date"] for p in pts] == ["2024-08-24", "2024-09-01", "2024-09-18"]
    assert pts[-1]["elo"] == rows[0]["elo_after"]


def test_h2h_summary_totals_and_newest_first():
    enr = ts.replay_elo(small_history())
    h = ts.h2h_summary(enr, "A", "B", limit=2)
    # A-B 1-0, A-B 2-2, B-A 1-2  -> A: 2 wins, 1 draw; goals 5-3
    assert (h["n"], h["a_wins"], h["draws"], h["b_wins"], h["a_goals"], h["b_goals"]) == (3, 2, 1, 0, 5, 3)
    assert [m["date"] for m in h["meetings"]] == ["2024-09-01", "2024-08-10"]
    assert h["meetings"][0] == {"date": "2024-09-01", "league": "PL", "home_team": "B", "away_team": "A",
                                "home_goals": 1, "away_goals": 2}
    r = ts.h2h_summary(enr, "B", "A", limit=10)
    assert (r["a_wins"], r["b_wins"], r["a_goals"]) == (0, 2, 3)
    none = ts.h2h_summary(enr, "A", "Nobody", limit=10)
    assert none["n"] == 0 and none["meetings"] == []


@pytest.mark.parametrize("table,hist,expected", [
    ("PL", "PD", "PL"), ("CL", "PD", "PD"), (None, None, None), ("CL", None, None), (None, "CL", None),
])
def test_resolve_league(table, hist, expected):
    assert ts.resolve_league(table, hist) == expected
