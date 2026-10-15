from datetime import date, datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

from src.ingestion.upsert import (
    _dedupe,
    _normalise,
    teams_from_records,
    upsert_matches,
    upsert_teams,
)
from src.models import Match, Team
from tests._pgtest import db_session  # noqa: F401  (fixture)


def rec(**kw):
    base = {
        "league": "PL",
        "season": 2023,
        "date": datetime(2023, 8, 12, 14, 0, tzinfo=timezone.utc),
        "kickoff": datetime(2023, 8, 12, 14, 0, tzinfo=timezone.utc),
        "match_day": date(2023, 8, 12),
        "home_team": "Manchester United FC",
        "away_team": "Wolverhampton Wanderers FC",
        "home_goals": 1,
        "away_goals": 0,
        "result": "H",
        "source": "couk",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Pure tests (no database)
# ---------------------------------------------------------------------------

def test_normalise_strips_tz_and_defaults():
    row = _normalise(rec(match_day=None, kickoff=None, source=None))
    assert row["date"].tzinfo is None and row["date"] == datetime(2023, 8, 12, 14, 0)
    assert row["kickoff"] is None
    assert row["match_day"] == date(2023, 8, 12)
    assert row["source"] == "fdorg"
    assert row["provider_id"] is None and row["odds_home"] is None


def test_normalise_requires_core_fields():
    with pytest.raises(ValueError):
        _normalise(rec(home_team=None))


def test_dedupe_merges_non_null_values_later_wins():
    a = _normalise(rec(home_shots=10, odds_home=None))
    b = _normalise(rec(home_shots=None, odds_home=2.0, home_goals=2, result="H"))
    merged = _dedupe([a, b])
    assert len(merged) == 1
    assert merged[0]["home_shots"] == 10 and merged[0]["odds_home"] == 2.0
    assert merged[0]["home_goals"] == 2


class _StubResult:
    def all(self):
        return []

    def first(self):
        return None


class _StubSession:
    def __init__(self):
        self.statements = []

    def execute(self, stmt):
        self.statements.append(stmt)
        return _StubResult()


def test_upsert_sql_shape():
    session = _StubSession()
    counts = upsert_matches(session, [rec(provider_id=123), rec(home_team="Chelsea FC")])
    assert counts == {"inserted": 0, "updated": 0, "unchanged": 2}
    sql = str(session.statements[-1].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (league, match_day, home_team, away_team) DO UPDATE" in sql
    assert "coalesce(excluded.home_shots, matches.home_shots)" in sql
    assert "coalesce(excluded.provider_id, matches.provider_id)" in sql
    assert "IS DISTINCT FROM" in sql and "RETURNING" in sql
    assert "xmax = 0" in sql


def test_upsert_empty_is_noop():
    session = _StubSession()
    assert upsert_matches(session, []) == {"inserted": 0, "updated": 0, "unchanged": 0}
    assert session.statements == []


def test_teams_from_records_splits_cl():
    domestic, other = teams_from_records(
        [rec(), rec(league="CL", home_team="Celtic FC", away_team="Arsenal FC")]
    )
    assert domestic == {"Manchester United FC": "PL", "Wolverhampton Wanderers FC": "PL"}
    assert other == {"Celtic FC": "CL", "Arsenal FC": "CL"}


# ---------------------------------------------------------------------------
# PostgreSQL integration (skipped without TEST_DATABASE_URL)
# ---------------------------------------------------------------------------

def _all(session):
    return session.query(Match).order_by(Match.id).all()


def test_insert_then_rerun_is_idempotent(db_session):
    records = [rec(home_shots=14, odds_home=2.1, odds_draw=3.4, odds_away=3.6, odds_source="pinnacle_close"),
               rec(home_team="Chelsea FC", away_team="Everton FC")]
    first = upsert_matches(db_session, records)
    db_session.commit()
    second = upsert_matches(db_session, records)
    db_session.commit()

    assert first == {"inserted": 2, "updated": 0, "unchanged": 0}
    assert second == {"inserted": 0, "updated": 0, "unchanged": 2}
    assert db_session.query(Match).count() == 2


def test_merge_couk_then_fdorg_keeps_both_sides(db_session):
    upsert_matches(
        db_session,
        [rec(home_shots=14, away_shots=9, odds_home=2.1, odds_draw=3.4, odds_away=3.6,
             odds_source="pinnacle_close", kickoff=None,
             date=datetime(2023, 8, 12, tzinfo=timezone.utc))],
    )
    result = upsert_matches(
        db_session,
        [rec(provider_id=444001, source="fdorg",
             date=datetime(2023, 8, 12, 14, 0, tzinfo=timezone.utc))],
    )
    db_session.commit()

    assert result == {"inserted": 0, "updated": 1, "unchanged": 0}
    (m,) = _all(db_session)
    assert m.provider_id == 444001
    assert m.source == "couk"  # first creator is kept
    assert m.home_shots == 14 and m.odds_source == "pinnacle_close"  # NULL did not erase
    assert m.kickoff == datetime(2023, 8, 12, 14, 0)
    assert m.date == datetime(2023, 8, 12, 14, 0)  # real kickoff replaces midnight placeholder


def test_couk_kickoff_does_not_override_fdorg_kickoff(db_session):
    fd = datetime(2023, 8, 12, 14, 0, tzinfo=timezone.utc)
    upsert_matches(db_session, [rec(provider_id=9, source="fdorg", date=fd, kickoff=fd)])
    shifted = datetime(2023, 8, 12, 14, 5, tzinfo=timezone.utc)
    result = upsert_matches(db_session, [rec(date=shifted, kickoff=shifted, home_shots=7)])
    db_session.commit()
    assert result["updated"] == 1  # shots added, kickoff untouched
    (m,) = _all(db_session)
    assert m.kickoff == datetime(2023, 8, 12, 14, 0) and m.home_shots == 7
    again = upsert_matches(db_session, [rec(date=shifted, kickoff=shifted, home_shots=7)])
    assert again["unchanged"] == 1


def test_corrected_result_propagates_and_null_never_overwrites(db_session):
    upsert_matches(db_session, [rec(home_shots=5)])
    corrected = upsert_matches(
        db_session, [rec(home_goals=2, away_goals=2, result="D", home_shots=None)]
    )
    db_session.commit()
    assert corrected["updated"] == 1
    (m,) = _all(db_session)
    assert (m.home_goals, m.away_goals, m.result) == (2, 2, "D")
    assert m.home_shots == 5


def test_duplicates_within_one_batch(db_session):
    result = upsert_matches(db_session, [rec(home_shots=3), rec(away_shots=4)])
    db_session.commit()
    assert result["inserted"] == 1
    (m,) = _all(db_session)
    assert (m.home_shots, m.away_shots) == (3, 4)


def test_rescheduled_provider_match_moves_instead_of_violating_unique(db_session):
    upsert_matches(db_session, [rec(provider_id=777, source="fdorg")])
    moved = rec(
        provider_id=777, source="fdorg",
        date=datetime(2023, 8, 13, 14, 0, tzinfo=timezone.utc),
        kickoff=datetime(2023, 8, 13, 14, 0, tzinfo=timezone.utc),
        match_day=date(2023, 8, 13),
    )
    upsert_matches(db_session, [moved])
    db_session.commit()
    (m,) = _all(db_session)
    assert m.provider_id == 777 and m.match_day == date(2023, 8, 13)


def test_surrogate_ids_come_from_sequence(db_session):
    db_session.add(Match(id=500000, provider_id=500000, date=datetime(2023, 8, 1, 12),
                         match_day=date(2023, 8, 1), home_team="A", away_team="B",
                         season=2023, league="PL"))
    db_session.commit()
    upsert_matches(db_session, [rec()])  # no provider id -> id from sequence
    db_session.commit()
    assert db_session.query(Match).filter(Match.provider_id.is_(None)).count() == 1


def test_upsert_teams(db_session):
    upsert_teams(db_session, {"Arsenal FC": "PL", "Celtic FC": "CL"}, overwrite_league=True)
    upsert_teams(db_session, {"Arsenal FC": "CL", "Rangers FC": "CL"}, overwrite_league=False)
    upsert_teams(db_session, {"Celtic FC": "SPFL"}, overwrite_league=True)
    db_session.commit()
    leagues = {t.name: t.league for t in db_session.query(Team).all()}
    assert leagues == {"Arsenal FC": "PL", "Celtic FC": "SPFL", "Rangers FC": "CL"}
