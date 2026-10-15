"""Season helpers shared by ingestion and (later) the API.

Dependency-free on purpose: only the standard library is imported so this
module can be used anywhere without pulling in pandas/SQLAlchemy.

European seasons start on July 1: a match played in January-June belongs to
the season that started the previous calendar year (the "season start year").
"""

from __future__ import annotations

from datetime import date, datetime

SEASON_START_MONTH = 7  # July


def season_start_year(dt: date | datetime) -> int:
    """Return the season start year for a match date (Jul 1 rollover).

    >>> season_start_year(date(2024, 3, 1))
    2023
    >>> season_start_year(date(2023, 8, 12))
    2023
    """
    return dt.year if dt.month >= SEASON_START_MONTH else dt.year - 1


def couk_season_code(season_start: int) -> str:
    """football-data.co.uk season code: 2023 -> '2324', 1999 -> '9900'."""
    return f"{season_start % 100:02d}{(season_start + 1) % 100:02d}"


def season_from_couk_code(code: str) -> int:
    """Inverse of couk_season_code: '2324' -> 2023, '9900' -> 1999.

    Two-digit years >= 70 are treated as 19xx, otherwise 20xx.
    """
    code = str(code).strip()
    if len(code) != 4 or not code.isdigit():
        raise ValueError(f"Invalid football-data.co.uk season code: {code!r}")
    start, end = int(code[:2]), int(code[2:])
    if (start + 1) % 100 != end:
        raise ValueError(f"Season code is not two consecutive years: {code!r}")
    return (1900 if start >= 70 else 2000) + start
