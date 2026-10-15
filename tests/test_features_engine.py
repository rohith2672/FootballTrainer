"""Tests for the point-in-time feature engine (src/features/engine.py)."""
import math
import time

import numpy as np
import pandas as pd
import pytest

from src.features import engine as E
from src.features.columns import FEATURE_COLS, LEAGUES
from src.features.engine import compute_features
from tests.helpers_features import frame, make_league_matches, match_row


def same(a, b):
    return np.array_equal(np.asarray(a, dtype=float), np.asarray(b, dtype=float), equal_nan=True)


def row_of(df, id_):
    return df.index[df["id"] == id_][0]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
def test_columns_equal_feature_cols_and_index_preserved():
    df = make_league_matches(leagues=("PL", "PD"), seasons=(2019,), n_teams=4)
    shuffled = df.sample(frac=1.0, random_state=3)
    out = compute_features(shuffled)
    assert list(out.columns) == FEATURE_COLS
    assert out.index.equals(shuffled.index)


def test_row_order_of_input_does_not_matter():
    df = make_league_matches(leagues=("PL", "PD"), seasons=(2019, 2020), n_teams=6, with_shots=True)
    base = compute_features(df)
    shuffled = df.sample(frac=1.0, random_state=11)
    out = compute_features(shuffled).loc[df.index]
    assert same(base.to_numpy(), out.to_numpy())


def test_empty_input():
    df = make_league_matches(seasons=(2019,), n_teams=4).iloc[:0]
    out = compute_features(df)
    assert list(out.columns) == FEATURE_COLS and len(out) == 0


def test_missing_required_column_raises():
    df = make_league_matches(seasons=(2019,), n_teams=4).drop(columns=["league"])
    with pytest.raises(ValueError):
        compute_features(df)


def test_no_constant_columns_on_realistic_data():
    df = make_league_matches(leagues=("PL", "PD"), seasons=(2018, 2019, 2020), n_teams=8,
                             with_shots=True, with_cl=True)
    out = compute_features(df)
    for col in FEATURE_COLS:
        vals = out[col].dropna()
        if col in ("league_SA", "league_BL1", "league_FL1"):  # leagues absent from this fixture
            continue
        assert vals.nunique() > 1, f"{col} is constant"


# ---------------------------------------------------------------------------
# Leakage
# ---------------------------------------------------------------------------
def test_future_result_does_not_change_earlier_or_same_day_rows():
    df = make_league_matches(leagues=("PL", "PD"), seasons=(2019, 2020), n_teams=6, with_shots=True)
    base = compute_features(df)
    k = len(df) // 2
    target_day = df.loc[k, "date"].normalize()
    perturbed = df.copy()
    perturbed.loc[k, ["home_goals", "away_goals", "home_shots", "away_shots"]] = [9, 0, 40, 1]
    out = compute_features(perturbed)

    before_or_same_day = (df["date"].dt.normalize() <= target_day).to_numpy()
    assert same(base[before_or_same_day].to_numpy(), out[before_or_same_day].to_numpy())
    # detector sanity: later rows DO change
    assert not same(base[~before_or_same_day].to_numpy(), out[~before_or_same_day].to_numpy())


def test_same_day_rows_do_not_see_each_other_via_league_priors():
    # A-B and C-D are played the same day; prior matches provide history.
    hist = [match_row(i, f"2020-08-{i:02d}", "A", "B", 1, 0) for i in range(1, 4)]
    hist += [match_row(10 + i, f"2020-08-{i:02d}", "C", "D", 0, 1) for i in range(1, 4)]
    day = "2020-09-01"
    nxt = match_row(99, "2020-09-02", "A", "C", 0, 0)

    def run(score):
        rows = hist + [match_row(20, day, "A", "B", *score), match_row(21, day, "C", "D", 1, 1), nxt]
        return compute_features(frame(*rows))

    a, b = run((0, 0)), run((7, 0))
    assert same(a.iloc[7].to_numpy(), b.iloc[7].to_numpy())   # same-day C-D row ignores the A-B result
    assert same(a.iloc[6].to_numpy(), b.iloc[6].to_numpy())   # the perturbed row never sees its own result
    assert not same(a.iloc[8].to_numpy(), b.iloc[8].to_numpy())  # next day does see it


def test_same_calendar_day_with_different_kickoff_times_is_one_batch():
    rows = [
        match_row(1, "2020-08-01 12:00", "A", "B", 1, 0),
        match_row(2, "2020-08-01 19:00", "C", "D", 2, 2),
        match_row(3, "2020-08-08", "A", "C", 0, 0),
    ]
    out = compute_features(frame(*rows))
    # the 19:00 game must not see the 12:00 game's result: league has no history
    assert out.loc[1, "h2h_n"] == 0
    assert out.loc[1, "home_form_n"] == 0
    assert out.loc[1, "elo_diff"] == pytest.approx(E.elo_mod.HOME_ADVANTAGE)


# ---------------------------------------------------------------------------
# Fixtures (rows with a null result)
# ---------------------------------------------------------------------------
def _promotion_scenario():
    """2020: 8-team PL; 2021: one promoted team 'NEW'. Returns (history, fixture row)."""
    h = make_league_matches(leagues=("PL",), seasons=(2020,), n_teams=8, seed=5)
    nxt = make_league_matches(leagues=("PL",), seasons=(2021,), n_teams=8, seed=6, start_id=1000)
    nxt = nxt.replace({"PL_T7": "NEW"})
    return pd.concat([h, nxt], ignore_index=True)


def test_fixture_rows_write_no_state():
    full = _promotion_scenario()
    first_2021 = full.index[full["season"] == 2021][0]
    fixture = match_row(5000, full.loc[first_2021, "date"], "NEW", "PL_T0", None, None, season=2021)
    fixtures_late = [
        match_row(5001, "2022-01-05", "PL_T1", "PL_T2", None, None, season=2021),
        match_row(5002, "2022-01-05", "NEW", "PL_T3", None, None, season=2021),
    ]
    base = compute_features(full)
    mixed = pd.concat([full.iloc[:first_2021], frame(fixture), full.iloc[first_2021:], frame(*fixtures_late)],
                      ignore_index=True)
    out = compute_features(mixed)
    fin = mixed["home_goals"].notna().to_numpy()
    assert same(base.to_numpy(), out[fin].to_numpy())
    # fixtures do get features
    assert not out[~fin][["home_elo", "elo_diff", "league_PL"]].isna().any().any()


def test_fixture_features_equal_those_of_the_same_row_with_a_result():
    full = _promotion_scenario()
    first_2021 = full.index[full["season"] == 2021][0]
    day = full.loc[first_2021, "date"]
    fx = dict(id=5000, date=day, league="PL", season=2021, home_team="NEW", away_team="PL_T0")
    as_fixture = pd.concat([full.iloc[:first_2021], frame(dict(fx, home_goals=None, away_goals=None)),
                            full.iloc[first_2021:]], ignore_index=True)
    as_finished = pd.concat([full.iloc[:first_2021], frame(dict(fx, home_goals=2, away_goals=2)),
                             full.iloc[first_2021:]], ignore_index=True)
    i = row_of(as_fixture, 5000)
    assert same(compute_features(as_fixture).iloc[i].to_numpy(), compute_features(as_finished).iloc[i].to_numpy())


def test_appended_future_fixtures_match_history_features():
    hist = make_league_matches(leagues=("PL", "PD"), seasons=(2019, 2020), n_teams=6, with_shots=True)
    day = hist["date"].max() + pd.Timedelta(days=7)
    fx = frame(match_row(9001, day, "PL_T0", "PL_T1", None, None, season=2020),
               match_row(9002, day, "PD_T2", "PD_T3", None, None, season=2020))
    out = compute_features(pd.concat([hist, fx], ignore_index=True))
    assert same(compute_features(hist).to_numpy(), out.iloc[: len(hist)].to_numpy())
    assert out.iloc[-2]["home_form_n"] == 5 and out.iloc[-2]["h2h_n"] > 0


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
def test_form_values_counts_and_venue_form():
    rows = [
        match_row(1, "2020-08-01", "A", "B", 2, 1),   # A home win
        match_row(2, "2020-08-08", "C", "A", 0, 3),   # A away win
        match_row(3, "2020-08-15", "A", "D", 1, 1),   # A home draw
        match_row(4, "2020-08-22", "A", "B", 0, 0),   # target: A home
    ]
    out = compute_features(frame(*rows))
    r = out.iloc[3]
    assert r["home_form_n"] == 3
    assert r["home_form_pts_pg"] == pytest.approx((3 + 3 + 1) / 3)
    assert r["home_form_goals_scored_avg"] == pytest.approx((2 + 3 + 1) / 3)
    assert r["home_form_goals_conceded_avg"] == pytest.approx((1 + 0 + 1) / 3)
    assert r["home_venue_form_pts_pg"] == pytest.approx((3 + 1) / 2)   # home games only
    assert r["away_form_n"] == 1                                       # B lost once as away
    assert r["away_venue_form_pts_pg"] == 0.0
    first = out.iloc[0]
    assert first["home_form_n"] == 0 and math.isnan(first["home_form_pts_pg"])
    assert math.isnan(first["home_venue_form_pts_pg"])


def test_form_window_is_last_five_only():
    rows = [match_row(i + 1, f"2020-08-{i + 1:02d}", "A", f"X{i}", 0 if i < 3 else 2, 1 if i < 3 else 0)
            for i in range(9)]
    out = compute_features(frame(*rows))
    # before the 9th game the window is the last five (idx 3..7), all wins
    assert out.iloc[8]["home_form_pts_pg"] == pytest.approx(3.0)
    assert out.iloc[8]["home_form_n"] == 5


def test_shots_nan_when_absent_and_window_skips_games_without_shots():
    rows = [
        match_row(1, "2020-08-01", "A", "B", 1, 0, home_shots=10, away_shots=4,
                  home_shots_on_target=5, away_shots_on_target=1),
        match_row(2, "2020-08-08", "A", "C", 1, 0),                                  # no shots data
        match_row(3, "2020-08-15", "A", "D", 2, 0, home_shots=20, away_shots=6,
                  home_shots_on_target=np.nan, away_shots_on_target=np.nan),
        match_row(4, "2020-08-22", "A", "B", 0, 0),
    ]
    out = compute_features(frame(*rows))
    assert out.iloc[0][["home_shots_for_avg", "away_sot_against_avg"]].isna().all()
    assert math.isnan(out.iloc[1]["away_sot_against_avg"])        # C has no shots history
    # game 2 only sees game 1's shots; the shot-less game 2 is skipped for the window
    assert out.iloc[1]["home_shots_for_avg"] == 10 and out.iloc[1]["home_sot_for_avg"] == 5
    r = out.iloc[3]
    assert r["home_shots_for_avg"] == pytest.approx(15) and r["home_shots_against_avg"] == pytest.approx(5)
    assert r["home_sot_for_avg"] == pytest.approx(5)                 # NaN sot entry ignored
    assert r["away_shots_for_avg"] == pytest.approx(4) and r["away_shots_against_avg"] == pytest.approx(10)
    assert out["home_shots_for_avg"].isna().sum() == 1


def test_h2h_with_no_meetings_equals_league_prior_and_n_is_zero():
    out = compute_features(frame(match_row(1, "2020-08-01", "A", "B", 1, 0)))
    prior = E._LeagueStats().points_share_prior()
    assert out.iloc[0]["h2h_n"] == 0
    assert out.iloc[0]["h2h_home_pts_rate"] == pytest.approx(prior)


def test_h2h_shrinkage_uses_all_meetings_without_a_five_game_gate():
    rows = [match_row(1, "2020-08-01", "A", "B", 2, 0),
            match_row(2, "2020-08-08", "B", "A", 0, 1),     # A (away) wins again
            match_row(3, "2020-08-15", "A", "B", 0, 0)]
    out = compute_features(frame(*rows))
    prior0 = E._LeagueStats().points_share_prior()
    assert out.iloc[1]["h2h_n"] == 1
    # B is the home team in game 2: it lost the only meeting (0 pts)
    k = E.H2H_PRIOR_K
    ls = E._LeagueStats()
    ls.n, ls.hw = 1, 1
    expected_b = (0 + 3 * k * ls.points_share_prior()) / (3 * (1 + k))
    assert out.iloc[1]["h2h_home_pts_rate"] == pytest.approx(expected_b)
    assert out.iloc[1]["h2h_home_pts_rate"] < prior0
    # A won both prior meetings, whichever side it played
    assert out.iloc[2]["h2h_n"] == 2
    assert out.iloc[2]["h2h_home_pts_rate"] > prior0
    assert out.iloc[2]["h2h_home_pts_rate"] < 1.0


def test_season_venue_rates_shrink_to_league_prior_and_reset_each_season():
    rows = [match_row(1, "2020-08-01", "A", "B", 1, 0),
            match_row(2, "2020-08-08", "A", "C", 1, 0),
            match_row(3, "2020-08-15", "A", "D", 0, 0),
            match_row(4, "2021-08-15", "A", "E", 0, 0, season=2021)]
    out = compute_features(frame(*rows))
    assert out.iloc[0]["home_home_games_n"] == 0
    assert out.iloc[0]["home_team_home_win_rate"] == pytest.approx(E.DEFAULT_HOME_WIN)
    assert out.iloc[2]["home_home_games_n"] == 2
    assert out.iloc[2]["home_team_home_win_rate"] > out.iloc[0]["home_team_home_win_rate"]
    assert out.iloc[2]["home_team_home_win_rate"] < 1.0
    assert out.iloc[3]["home_home_games_n"] == 0     # new season: counters reset
    assert out.iloc[3]["season_progress"] == 0.0
    assert out.iloc[2]["season_progress"] == pytest.approx(2 / 38)


def test_rest_days_cap_kickoff_and_first_match_nan():
    rows = [match_row(1, "2020-08-01", "A", "B", 1, 0),
            match_row(2, "2020-08-05", "A", "C", 1, 0),
            match_row(3, "2020-10-20", "A", "B", 1, 0)]
    out = compute_features(frame(*rows))
    assert math.isnan(out.iloc[0]["home_days_since_last"])
    assert out.iloc[1]["home_days_since_last"] == pytest.approx(4.0)
    assert out.iloc[1]["away_days_since_last"] != out.iloc[1]["away_days_since_last"]   # C unseen -> NaN
    assert out.iloc[2]["home_days_since_last"] == E.REST_CAP_DAYS                       # off-season gap capped
    assert out.iloc[2]["away_days_since_last"] == E.REST_CAP_DAYS

    k = frame(match_row(1, "2020-08-01", "A", "B", 1, 0, kickoff=pd.Timestamp("2020-08-01 19:00")),
              match_row(2, "2020-08-05", "A", "C", 1, 0, kickoff=pd.Timestamp("2020-08-05 13:00")))
    assert compute_features(k).iloc[1]["home_days_since_last"] == pytest.approx(3 + 18 / 24)


def test_context_one_hot_and_season_derived_from_date():
    rows = [match_row(1, "2021-03-01", "A", "B", 1, 0, league="BL1", season=None),
            match_row(2, "2021-03-08", "A", "C", 1, 0, league="CL", season=None)]
    df = frame(*rows)
    df["season"] = np.nan
    out = compute_features(df)
    for i, lg in enumerate(["BL1", "CL"]):
        for name in LEAGUES:
            assert out.iloc[i][f"league_{name}"] == (1.0 if name == lg else 0.0)
    assert out.iloc[1]["season_progress"] == 0.0   # CL counter is separate from BL1
    explicit = frame(*[dict(r, season=2020) for r in rows])
    assert same(out.to_numpy(), compute_features(explicit).to_numpy())


def test_cl_matches_link_leagues_through_shared_elo():
    # PL team beats a PD team in CL -> both carry the shifted rating back into their leagues
    rows = [match_row(1, "2020-09-20", "PLX", "PDX", 3, 0, league="CL"),
            match_row(2, "2020-10-20", "PLX", "PLY", 0, 0, league="PL"),
            match_row(3, "2020-10-20", "PDY", "PDX", 0, 0, league="PD")]
    out = compute_features(frame(*rows))
    assert out.iloc[1]["home_elo"] > 1500 and out.iloc[2]["away_elo"] < 1500


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------
def test_performance_20k_rows():
    base = make_league_matches(leagues=("PL", "PD", "SA", "BL1", "FL1"), seasons=tuple(range(2012, 2022)),
                               n_teams=10, with_shots=True, with_cl=True)
    reps = int(np.ceil(20000 / len(base)))
    big = pd.concat(
        [base.assign(id=base["id"] + r * 1_000_000,
                     home_team=base["home_team"] + f"_{r}", away_team=base["away_team"] + f"_{r}")
         for r in range(reps)],
        ignore_index=True,
    )
    assert len(big) >= 20000
    t0 = time.perf_counter()
    out = compute_features(big)
    assert time.perf_counter() - t0 < 15.0
    assert len(out) == len(big)


def test_season_games_denominator_per_league_and_season():
    assert E.season_games("PL", 2019) == 38 and E.season_games("PD", 2024) == 38
    assert E.season_games("BL1", 2019) == 34 and E.season_games("BL1", 2024) == 34
    assert E.season_games("CL", 2024) == 13
    assert E.season_games("FL1", 2022) == 38        # 20 clubs
    assert E.season_games("FL1", 2023) == 34        # 18 clubs from 2023-24
    assert E.season_games("FL1", 2025) == 34


def test_season_progress_uses_fl1_season_specific_denominator():
    def fl1(season):
        rows = [match_row(1, f"{season}-08-01", "A", "B", 1, 0, league="FL1", season=season),
                match_row(2, f"{season}-08-08", "A", "C", 1, 0, league="FL1", season=season),
                match_row(3, f"{season}-08-15", "A", "D", 1, 0, league="FL1", season=season)]
        return compute_features(frame(*rows)).iloc[2]["season_progress"]

    assert fl1(2022) == pytest.approx(2 / 38)
    assert fl1(2023) == pytest.approx(2 / 34)
