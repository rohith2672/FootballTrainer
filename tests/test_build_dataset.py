import datetime
import pytest
from unittest.mock import MagicMock
from src.features.build_dataset import build_dataset, RESULT_MAP


def _make_match(id, date, home, away, home_goals, away_goals, result, season="2023"):
    m = MagicMock()
    m.id = id
    m.date = datetime.datetime.strptime(date, "%Y-%m-%d")
    m.home_team = home
    m.away_team = away
    m.home_goals = home_goals
    m.away_goals = away_goals
    m.result = result
    m.season = season
    m.league = "PL"
    return m


# Build 12 matches (enough for form features to produce non-NaN for late matches)
_TEAMS = ["A", "B", "C", "D"]

_MATCHES = [
    _make_match(1,  "2023-08-01", "A", "B", 2, 1, "H"),
    _make_match(2,  "2023-08-02", "C", "D", 0, 0, "D"),
    _make_match(3,  "2023-08-08", "B", "C", 1, 2, "A"),
    _make_match(4,  "2023-08-09", "D", "A", 1, 1, "D"),
    _make_match(5,  "2023-08-15", "A", "C", 3, 0, "H"),
    _make_match(6,  "2023-08-16", "B", "D", 0, 1, "A"),
    _make_match(7,  "2023-08-22", "C", "A", 1, 2, "A"),
    _make_match(8,  "2023-08-23", "D", "B", 2, 0, "H"),
    _make_match(9,  "2023-08-29", "A", "D", 1, 0, "H"),
    _make_match(10, "2023-08-30", "B", "C", 2, 2, "D"),
    _make_match(11, "2023-09-05", "C", "B", 0, 1, "A"),
    _make_match(12, "2023-09-06", "D", "A", 0, 2, "A"),
]


def _mock_session(matches):
    session = MagicMock()
    query_mock = MagicMock()
    filter_mock = MagicMock()
    order_mock = MagicMock()
    order_mock.all.return_value = matches
    filter_mock.order_by.return_value = order_mock
    query_mock.filter.return_value = filter_mock
    session.query.return_value = query_mock
    return session


def test_output_columns():
    session = _mock_session(_MATCHES)
    df = build_dataset(db_session=session)
    assert "target" in df.columns
    assert "result" not in df.columns
    assert "match_id" in df.columns


def test_target_encoding():
    session = _mock_session(_MATCHES)
    df = build_dataset(db_session=session)
    assert set(df["target"].unique()).issubset({0, 1, 2})


def test_no_nan_in_output():
    session = _mock_session(_MATCHES)
    df = build_dataset(db_session=session)
    assert not df.isnull().any().any(), "Output DataFrame must have no NaN values"


def test_rows_dropped_for_early_matches():
    session = _mock_session(_MATCHES)
    df = build_dataset(db_session=session)
    # Early matches (insufficient form history) should be dropped
    assert len(df) < len(_MATCHES)


def test_class_distribution_all_outcomes_present():
    session = _mock_session(_MATCHES)
    df = build_dataset(db_session=session)
    assert set(df["target"].unique()) == {0, 1, 2}, "All three outcomes must appear in test data"


def test_result_map_values():
    assert RESULT_MAP == {"H": 0, "D": 1, "A": 2}
