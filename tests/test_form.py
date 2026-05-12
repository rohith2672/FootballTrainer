import math
from datetime import datetime, timedelta

from src.features.form import _compute_form_from_matches


def _make_match(id_, date, home, away, hg, ag, result):
    return {"id": id_, "date": date, "home_team": home, "away_team": away,
            "home_goals": hg, "away_goals": ag, "result": result}


BASE = datetime(2023, 1, 1)


def _day(n):
    return BASE + timedelta(days=n)


class TestFirstMatchIsNan:
    def test_first_match_is_nan(self):
        matches = [_make_match(1, _day(0), "A", "B", 2, 1, "H")]
        df = _compute_form_from_matches(matches)
        for col in ["home_form_pts_pg", "home_form_goals_scored_avg",
                    "home_form_goals_conceded_avg", "away_form_pts_pg",
                    "away_form_goals_scored_avg", "away_form_goals_conceded_avg"]:
            assert math.isnan(df.iloc[0][col]), f"{col} should be NaN on first match"


class TestBasicFormValues:
    def _six_sequential_wins(self):
        # A beats B 2-1 in six consecutive matches
        matches = []
        for i in range(6):
            matches.append(_make_match(i + 1, _day(i), "A", "B", 2, 1, "H"))
        return _compute_form_from_matches(matches)

    def test_basic_form_values(self):
        df = self._six_sequential_wins()
        row6 = df.iloc[5]
        assert row6["home_form_pts_pg"] == 3.0
        assert row6["home_form_goals_scored_avg"] == 2.0
        assert row6["home_form_goals_conceded_avg"] == 1.0
        assert row6["away_form_pts_pg"] == 0.0
        assert row6["away_form_goals_scored_avg"] == 1.0
        assert row6["away_form_goals_conceded_avg"] == 2.0

    def test_match_id_preserved(self):
        df = self._six_sequential_wins()
        assert list(df["match_id"]) == [1, 2, 3, 4, 5, 6]


class TestFewerThan5Games:
    def _three_matches(self):
        # Match 1: A beats B 2-1, Match 2: A draws B 1-1, Match 3: A vs B (form computed from 2 prior)
        return _compute_form_from_matches([
            _make_match(1, _day(0), "A", "B", 2, 1, "H"),
            _make_match(2, _day(1), "A", "B", 1, 1, "D"),
            _make_match(3, _day(2), "A", "B", 0, 0, "D"),
        ])

    def test_fewer_than_5_games_no_crash(self):
        df = self._three_matches()
        assert len(df) == 3

    def test_fewer_than_5_games_correct_values(self):
        df = self._three_matches()
        row3 = df.iloc[2]
        # Home team A: 2 prior games — W(3pts,2gf,1ga) and D(1pt,1gf,1ga)
        assert row3["home_form_pts_pg"] == (3 + 1) / 2
        assert row3["home_form_goals_scored_avg"] == (2 + 1) / 2
        assert row3["home_form_goals_conceded_avg"] == (1 + 1) / 2

    def test_second_match_uses_single_prior_game(self):
        df = self._three_matches()
        row2 = df.iloc[1]
        # Home A: 1 prior game — W(3pts, 2gf, 1ga)
        assert row2["home_form_pts_pg"] == 3.0
        assert row2["home_form_goals_scored_avg"] == 2.0
        assert row2["home_form_goals_conceded_avg"] == 1.0


class TestNoLeakage:
    def _base_matches(self):
        return [_make_match(i + 1, _day(i), "A", "B", 1, 0, "H") for i in range(5)]

    def test_no_leakage_future_match_does_not_affect_past_row(self):
        base = self._base_matches()
        baseline_df = _compute_form_from_matches(base)

        # Append a future match (day 5, after all others)
        extended = base + [_make_match(6, _day(5), "A", "B", 99, 0, "H")]
        extended_df = _compute_form_from_matches(extended)

        # Row 5 (index 4) should be identical in both runs
        for col in ["home_form_pts_pg", "home_form_goals_scored_avg", "home_form_goals_conceded_avg"]:
            assert baseline_df.iloc[4][col] == extended_df.iloc[4][col]

    def test_no_leakage_extreme_future_values_not_present(self):
        matches = [_make_match(i + 1, _day(i), "A", "B", 1, 0, "H") for i in range(5)]
        matches.append(_make_match(6, _day(5), "A", "B", 99, 0, "H"))
        df = _compute_form_from_matches(matches)

        # No row before the last should have goals_scored_avg influenced by 99
        for i in range(5):
            avg = df.iloc[i]["home_form_goals_scored_avg"]
            if not math.isnan(avg):
                assert avg < 10, f"Row {i} home_form_goals_scored_avg={avg} looks contaminated by future data"


class TestBothTeamsComputedIndependently:
    def test_isolated_teams_do_not_cross_contaminate(self):
        # X vs Y (5 games, 3-0 wins), then Z vs W (1 game)
        matches = [_make_match(i + 1, _day(i), "X", "Y", 3, 0, "H") for i in range(5)]
        matches.append(_make_match(6, _day(5), "Z", "W", 1, 1, "D"))
        df = _compute_form_from_matches(matches)

        row6 = df.iloc[5]
        # Z and W are both on their first match — should be NaN
        assert math.isnan(row6["home_form_pts_pg"])
        assert math.isnan(row6["away_form_pts_pg"])

        # X's form in row 6 (row index 5 = match 5 for X vs Y) should be 3.0 pts_pg
        row5 = df.iloc[4]
        assert row5["home_form_pts_pg"] == 3.0
        assert row5["home_form_goals_scored_avg"] == 3.0

    def test_away_team_history_contributes_to_own_form(self):
        # B plays as away in matches 1-3 (all wins for A, so B loses)
        # Then B plays as home in match 4
        matches = [
            _make_match(1, _day(0), "A", "B", 2, 0, "H"),
            _make_match(2, _day(1), "A", "B", 2, 0, "H"),
            _make_match(3, _day(2), "A", "B", 2, 0, "H"),
            _make_match(4, _day(3), "B", "C", 1, 0, "H"),  # B now home
        ]
        df = _compute_form_from_matches(matches)
        row4 = df.iloc[3]
        # B has 3 prior matches (all away losses: 0pts, 0gf, 2ga)
        assert row4["home_form_pts_pg"] == 0.0
        assert row4["home_form_goals_scored_avg"] == 0.0
        assert row4["home_form_goals_conceded_avg"] == 2.0


class TestOutputSchema:
    def test_output_columns(self):
        matches = [_make_match(1, _day(0), "A", "B", 1, 0, "H")]
        df = _compute_form_from_matches(matches)
        expected = {"match_id", "home_form_pts_pg", "home_form_goals_scored_avg",
                    "home_form_goals_conceded_avg", "away_form_pts_pg",
                    "away_form_goals_scored_avg", "away_form_goals_conceded_avg"}
        assert set(df.columns) == expected

    def test_empty_input_returns_empty_dataframe(self):
        df = _compute_form_from_matches([])
        assert len(df) == 0
        assert "match_id" in df.columns
