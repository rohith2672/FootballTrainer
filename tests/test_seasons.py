from datetime import date, datetime

import pytest

from src.ingestion.seasons import couk_season_code, season_from_couk_code, season_start_year


@pytest.mark.parametrize(
    "d, expected",
    [
        (date(2023, 8, 12), 2023),
        (date(2024, 1, 1), 2023),
        (date(2024, 6, 30), 2023),
        (date(2024, 7, 1), 2024),
        (date(2024, 12, 31), 2024),
        (datetime(2025, 5, 25, 14, 0), 2024),
    ],
)
def test_season_start_year(d, expected):
    assert season_start_year(d) == expected


@pytest.mark.parametrize(
    "start, code",
    [(2023, "2324"), (2015, "1516"), (2009, "0910"), (1999, "9900"), (2025, "2526")],
)
def test_couk_code_round_trip(start, code):
    assert couk_season_code(start) == code
    assert season_from_couk_code(code) == start


@pytest.mark.parametrize("bad", ["", "23", "2325", "abcd", "23245"])
def test_season_from_couk_code_rejects_garbage(bad):
    with pytest.raises(ValueError):
        season_from_couk_code(bad)
