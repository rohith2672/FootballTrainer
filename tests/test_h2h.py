import math
from datetime import datetime, timedelta

from src.features.h2h import _compute_h2h_from_matches

BASE = datetime(2023, 1, 1)


def _day(n):
    return BASE + timedelta(days=n)


def _make_match(id_, date, home, away, hg, ag, result, season=2023):
    return {
        "id": id_,
        "date": date,
        "home_team": home,
        "away_team": away,
        "home_goals": hg,
        "away_goals": ag,
        "result": result,
        "season": season,
    }


EXPECTED_COLUMNS = {
    "match_id",
    "h2h_home_win_rate",
    "home_team_home_win_rate",
    "away_team_away_win_rate",
    "home_days_since_last",
    "away_days_since_last",
}


class TestOutputSchema:
    def test_correct_columns(self):
        matches = [_make_match(1, _day(0), "A", "B", 1, 0, "H")]
        df = _compute_h2h_from_matches(matches)
        assert set(df.columns) == EXPECTED_COLUMNS

    def test_empty_input_returns_empty_dataframe(self):
        df = _compute_h2h_from_matches([])
        assert len(df) == 0
        assert "match_id" in df.columns


class TestNoH2HHistory:
    def test_h2h_rate_is_zero_on_first_meeting(self):
        matches = [_make_match(1, _day(0), "A", "B", 1, 0, "H")]
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[0]["h2h_home_win_rate"] == 0.0

    def test_h2h_rate_is_zero_with_fewer_than_five_meetings(self):
        matches = [_make_match(i + 1, _day(i), "A", "B", 1, 0, "H") for i in range(4)]
        # 5th match has 4 prior meetings — still < 5, must be 0.0
        matches.append(_make_match(5, _day(4), "A", "B", 0, 0, "D"))
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[4]["h2h_home_win_rate"] == 0.0


class TestH2HWithFiveMeetings:
    def test_all_home_wins_gives_rate_one(self):
        # 5 prior meetings, A always wins as home
        matches = [_make_match(i + 1, _day(i), "A", "B", 2, 0, "H") for i in range(6)]
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[5]["h2h_home_win_rate"] == 1.0

    def test_all_away_wins_gives_rate_zero(self):
        # A is always home but always loses
        matches = [_make_match(i + 1, _day(i), "A", "B", 0, 2, "A") for i in range(6)]
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[5]["h2h_home_win_rate"] == 0.0

    def test_mixed_results_correct_rate(self):
        # 5 meetings: 3 home wins (H), 2 away wins (A) for A
        results = ["H", "H", "H", "A", "A"]
        matches = [_make_match(i + 1, _day(i), "A", "B", 1, 0, results[i]) for i in range(5)]
        # 6th match — A is home again, should see 3/5 = 0.6
        matches.append(_make_match(6, _day(5), "A", "B", 0, 0, "D"))
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[5]["h2h_home_win_rate"] == 0.6

    def test_h2h_from_away_teams_perspective(self):
        # 5 meetings where B was home and won ("H"), then B is away against A
        matches = [_make_match(i + 1, _day(i), "B", "A", 1, 0, "H") for i in range(5)]
        # 6th: A is home vs B — B won all 5 prior meetings as home, so A win rate = 0.0
        matches.append(_make_match(6, _day(5), "A", "B", 0, 0, "D"))
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[5]["h2h_home_win_rate"] == 0.0

    def test_h2h_only_uses_last_five(self):
        # 6 meetings: first is home win (old), next 5 are all away wins
        matches = [_make_match(1, _day(0), "A", "B", 2, 0, "H")]
        for i in range(1, 6):
            matches.append(_make_match(i + 1, _day(i), "A", "B", 0, 2, "A"))
        # 7th match: last 5 were all "A" (away wins), so home win rate for A = 0.0
        matches.append(_make_match(7, _day(6), "A", "B", 0, 0, "D"))
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[6]["h2h_home_win_rate"] == 0.0


class TestHomeAwayWinRate:
    def test_no_prior_home_games_gives_zero(self):
        matches = [_make_match(1, _day(0), "A", "B", 1, 0, "H")]
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[0]["home_team_home_win_rate"] == 0.0

    def test_no_prior_away_games_gives_zero(self):
        matches = [_make_match(1, _day(0), "A", "B", 1, 0, "H")]
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[0]["away_team_away_win_rate"] == 0.0

    def test_home_win_rate_correct_value(self):
        # A plays at home 4 times: 3 wins, 1 loss; then another home game
        matches = [
            _make_match(1, _day(0), "A", "C", 2, 0, "H"),
            _make_match(2, _day(1), "A", "D", 1, 0, "H"),
            _make_match(3, _day(2), "A", "E", 1, 0, "H"),
            _make_match(4, _day(3), "A", "F", 0, 1, "A"),
            _make_match(5, _day(4), "A", "B", 0, 0, "D"),
        ]
        df = _compute_h2h_from_matches(matches)
        # Row 5 (idx 4): A has 3 home wins from 4 prior home games
        assert df.iloc[4]["home_team_home_win_rate"] == 0.75

    def test_away_win_rate_correct_value(self):
        # B plays away 4 times: 2 wins, 2 losses; then another away game
        matches = [
            _make_match(1, _day(0), "C", "B", 0, 1, "A"),
            _make_match(2, _day(1), "D", "B", 0, 1, "A"),
            _make_match(3, _day(2), "E", "B", 1, 0, "H"),
            _make_match(4, _day(3), "F", "B", 1, 0, "H"),
            _make_match(5, _day(4), "A", "B", 0, 0, "D"),
        ]
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[4]["away_team_away_win_rate"] == 0.5

    def test_season_boundary_resets_rate(self):
        # A has 3 home wins in season 2022, then new season 2023 — rate should reset to 0.0
        matches = [
            _make_match(1, _day(0), "A", "B", 1, 0, "H", season=2022),
            _make_match(2, _day(1), "A", "B", 1, 0, "H", season=2022),
            _make_match(3, _day(2), "A", "B", 1, 0, "H", season=2022),
            _make_match(4, _day(3), "A", "B", 0, 0, "D", season=2023),
        ]
        df = _compute_h2h_from_matches(matches)
        # Row 4 is first home game of 2023 — no prior 2023 home games for A
        assert df.iloc[3]["home_team_home_win_rate"] == 0.0


class TestDaysSinceLastMatch:
    def test_first_match_is_nan(self):
        matches = [_make_match(1, _day(0), "A", "B", 1, 0, "H")]
        df = _compute_h2h_from_matches(matches)
        assert math.isnan(df.iloc[0]["home_days_since_last"])
        assert math.isnan(df.iloc[0]["away_days_since_last"])

    def test_correct_days_after_prior_match(self):
        matches = [
            _make_match(1, _day(0), "A", "B", 1, 0, "H"),
            _make_match(2, _day(7), "A", "C", 0, 0, "D"),
        ]
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[1]["home_days_since_last"] == 7

    def test_away_team_days_tracked_correctly(self):
        matches = [
            _make_match(1, _day(0), "C", "B", 1, 0, "H"),
            _make_match(2, _day(4), "A", "B", 0, 0, "D"),
        ]
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[1]["away_days_since_last"] == 4

    def test_team_switching_sides_uses_last_match_regardless_of_venue(self):
        # A plays as away on day 0, then as home on day 3
        matches = [
            _make_match(1, _day(0), "C", "A", 1, 0, "H"),
            _make_match(2, _day(3), "A", "B", 0, 0, "D"),
        ]
        df = _compute_h2h_from_matches(matches)
        assert df.iloc[1]["home_days_since_last"] == 3


class TestNoLeakage:
    def test_adding_future_match_does_not_change_prior_rows(self):
        base = [_make_match(i + 1, _day(i), "A", "B", 1, 0, "H") for i in range(5)]
        base_df = _compute_h2h_from_matches(base)

        extended = base + [_make_match(6, _day(5), "A", "B", 99, 0, "H")]
        extended_df = _compute_h2h_from_matches(extended)

        for col in EXPECTED_COLUMNS - {"match_id"}:
            v1 = base_df.iloc[4][col]
            v2 = extended_df.iloc[4][col]
            if math.isnan(v1):
                assert math.isnan(v2)
            else:
                assert v1 == v2, f"Column {col} changed after adding future match"

    def test_match_id_preserved(self):
        matches = [_make_match(i + 1, _day(i), "A", "B", 1, 0, "H") for i in range(3)]
        df = _compute_h2h_from_matches(matches)
        assert list(df["match_id"]) == [1, 2, 3]
