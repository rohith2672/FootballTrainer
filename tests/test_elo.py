"""Elo rating tests (src/features/elo.py) incl. the engine's Elo columns."""
import math

import pytest

from src.features import elo as E
from src.features.engine import compute_features
from tests.helpers_features import frame, match_row


def test_expected_score_properties():
    assert E.expected_home_score(1500, 1500, home_advantage=0) == pytest.approx(0.5)
    assert E.expected_home_score(1500, 1500) > 0.5                      # home advantage
    assert E.expected_home_score(1700, 1500) > E.expected_home_score(1600, 1500)


def test_goal_difference_multiplier_never_zero_and_monotone():
    assert E.goal_diff_multiplier(0) == 1.0
    assert E.goal_diff_multiplier(1) < E.goal_diff_multiplier(3)
    assert E.goal_diff_multiplier(-3) == E.goal_diff_multiplier(3)


def test_winner_gains_loser_loses_and_sum_conserved():
    d = E.rating_delta(1500, 1500, 2, 0)
    assert d > 0
    r = E.EloRatings()
    r.commit("A", "PL", 2020)
    r.commit("B", "PL", 2020)
    before = r.rating["A"] + r.rating["B"]
    r.apply_result("A", "B", "PL", 2020, 2, 0, r.rating["A"], r.rating["B"])
    assert r.rating["A"] > 1500 > r.rating["B"]
    assert r.rating["A"] + r.rating["B"] == pytest.approx(before)


def test_draw_pulls_unequal_teams_together_and_upset_moves_more():
    assert E.rating_delta(1700, 1500, 1, 1) < 0          # favourite drops
    assert E.rating_delta(1500, 1700, 1, 1) > 0          # underdog rises
    assert abs(E.rating_delta(1500, 1700, 1, 0)) > abs(E.rating_delta(1700, 1500, 1, 0))


def test_bigger_margin_moves_more():
    assert E.rating_delta(1500, 1500, 4, 0) > E.rating_delta(1500, 1500, 1, 0)


def _season(r, teams, season, winner=None):
    for i, h in enumerate(teams):
        for a in teams[i + 1:]:
            he, ae = r.commit(h, "PL", season), r.commit(a, "PL", season)
            hg, ag = (3, 0) if h == winner else ((0, 3) if a == winner else (1, 1))
            r.apply_result(h, a, "PL", season, hg, ag, he, ae)


TEAMS = [f"T{i}" for i in range(10)]


def test_season_regression_moves_toward_league_mean():
    r = E.EloRatings()
    _season(r, TEAMS, 2020, winner="T0")
    top = r.rating["T0"]
    mean = sum(r.rating[t] for t in TEAMS) / len(TEAMS)
    assert top > mean
    new = r.commit("T0", "PL", 2021)
    assert new == pytest.approx(top + E.SEASON_REGRESSION * (mean - top))
    assert mean < new < top
    # regressed once only: a second 2021 match does not regress again
    assert r.commit("T0", "PL", 2021) == pytest.approx(new)


def test_promoted_team_starts_at_mean_of_previous_bottom_three():
    r = E.EloRatings()
    _season(r, TEAMS, 2020, winner="T0")
    table = r.table[("PL", 2020)]
    worst = sorted(table.items(), key=lambda kv: (kv[1][0], kv[1][1], kv[1][2], kv[0]))[: E.N_RELEGATED]
    expected = sum(r.rating[t] for t, _ in worst) / E.N_RELEGATED
    assert r.commit("NEWBIE", "PL", 2021) == pytest.approx(expected)
    # a second promoted team in the same season gets the same prior (order independent)
    assert r.commit("NEWBIE2", "PL", 2021) == pytest.approx(expected)


def test_promoted_team_fallback_is_league_mean_minus_penalty():
    r = E.EloRatings()
    for t in ("A", "B", "C"):                      # too few teams for a usable table
        r.commit(t, "PL", 2020)
    r.apply_result("A", "B", "PL", 2020, 1, 0, 1500, 1500)
    mean = sum(r.rating[t] for t in "ABC") / 3
    assert r.commit("N", "PL", 2021) == pytest.approx(mean - E.PROMOTED_PENALTY)


def test_new_team_in_first_season_and_cl_only_team_start_at_base():
    r = E.EloRatings()
    assert r.commit("X", "PL", 2020) == E.BASE_RATING
    assert r.commit("Y", "PL", 2020) == E.BASE_RATING     # same (first) season of the league
    assert r.commit("Z", "CL", 2021) == E.BASE_RATING     # CL-only team, global mean


def test_peek_does_not_mutate():
    r = E.EloRatings()
    _season(r, TEAMS, 2020, winner="T0")
    snap = (dict(r.rating), dict(r.last_season), dict(r.team_league), dict(r._refs),
            {k: set(v) for k, v in r.roster.items()})
    r.peek("T0", "PL", 2021)
    r.peek("BRAND_NEW", "PL", 2021)
    assert snap == (r.rating, r.last_season, r.team_league, r._refs, r.roster)


def test_engine_elo_columns_consistent():
    rows = [match_row(1, "2020-08-01", "A", "B", 2, 0),
            match_row(2, "2020-08-08", "A", "B", 0, 0)]
    out = compute_features(frame(*rows))
    assert out.iloc[0]["home_elo"] == 1500 and out.iloc[0]["away_elo"] == 1500
    assert out.iloc[0]["elo_diff"] == pytest.approx(E.HOME_ADVANTAGE)
    assert out.iloc[0]["elo_expected_home"] == pytest.approx(E.expected_home_score(1500, 1500))
    r1 = out.iloc[1]
    assert r1["home_elo"] > 1500 > r1["away_elo"]
    assert r1["home_elo"] + r1["away_elo"] == pytest.approx(3000.0)
    # the league's home advantage was learned from game 1 (a home win)
    ha1 = E.HOME_ADVANTAGE + E.HOME_ADVANTAGE_RATE * (1.0 - E.expected_home_score(1500, 1500))
    assert r1["elo_diff"] == pytest.approx(r1["home_elo"] - r1["away_elo"] + ha1)
    assert 1 / (1 + 10 ** (-r1["elo_diff"] / 400)) == pytest.approx(r1["elo_expected_home"])
    assert math.isfinite(r1["elo_expected_home"])


def test_engine_elo_matches_public_api_replay():
    """Replaying matches day by day through EloRatings() reproduces the engine's Elo columns."""
    from tests.helpers_features import make_league_matches

    df = make_league_matches(leagues=("PL", "PD"), seasons=(2019, 2020), n_teams=6, with_cl=True)
    out = compute_features(df)
    r = E.EloRatings()
    pending = []
    for day, grp in df.groupby(df["date"].dt.normalize(), sort=True):
        for i, m in grp.iterrows():
            he = r.commit(m.home_team, m.league, m.season)
            ae = r.commit(m.away_team, m.league, m.season)
            assert out.loc[i, "home_elo"] == pytest.approx(he)
            assert out.loc[i, "elo_diff"] == pytest.approx(he - ae + r.home_advantage_for(m.league))
            pending.append((m, he, ae))
        for m, he, ae in pending:
            r.apply_result(m.home_team, m.away_team, m.league, m.season, m.home_goals, m.away_goals, he, ae)
        pending.clear()


def test_defaults_are_module_constants_and_kwargs_override():
    r = E.EloRatings()
    assert (r.k_factor, r.home_advantage, r.season_regression, r.margin_cap, r.home_advantage_rate) == (
        E.K_FACTOR, E.HOME_ADVANTAGE, E.SEASON_REGRESSION, E.MARGIN_CAP, E.HOME_ADVANTAGE_RATE)
    assert r.home_advantage_for("PL") == E.HOME_ADVANTAGE
    c = E.EloRatings(k_factor=30, home_advantage=80, season_regression=0.5, margin_cap=2,
                     league_home_advantage={"PD": 100}, home_advantage_rate=0)
    assert c.home_advantage_for("PL") == 80 and c.home_advantage_for("PD") == 100
    assert E.rating_delta(1500, 1500, 1, 0, k_factor=30) == pytest.approx(
        1.5 * E.rating_delta(1500, 1500, 1, 0, k_factor=20))


def test_margin_cap_limits_goal_difference_multiplier():
    assert E.goal_diff_multiplier(5, margin_cap=2) == E.goal_diff_multiplier(2, margin_cap=None)
    assert E.goal_diff_multiplier(1, margin_cap=2) == E.goal_diff_multiplier(1, margin_cap=None)
    assert E.goal_diff_multiplier(0, margin_cap=0) == 1.0


def test_adaptive_home_advantage_moves_with_home_results_per_league():
    r = E.EloRatings(home_advantage_rate=5.0)
    start = r.home_advantage_for("PL")
    for i in range(20):                      # equal teams, home side keeps losing in PL
        he, ae = r.commit(f"H{i}", "PL", 2020), r.commit(f"A{i}", "PL", 2020)
        r.apply_result(f"H{i}", f"A{i}", "PL", 2020, 0, 1, he, ae)
    assert r.home_advantage_for("PL") < start
    assert r.home_advantage_for("PD") == start              # other competitions unaffected
    fixed = E.EloRatings(home_advantage_rate=0.0)
    he, ae = fixed.commit("X", "PL", 2020), fixed.commit("Y", "PL", 2020)
    fixed.apply_result("X", "Y", "PL", 2020, 0, 1, he, ae)
    assert fixed.home_advantage_for("PL") == fixed.home_advantage
