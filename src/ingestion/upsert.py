"""Idempotent PostgreSQL upserts for matches and teams.

Merge rules for ``upsert_matches`` (conflict target = natural key
``(league, match_day, home_team, away_team)``):

* a NULL in the incoming row never overwrites a stored value
  (``COALESCE(excluded.col, matches.col)``), so football-data.org rows
  (no shots/odds) do not erase football-data.co.uk data and vice versa;
* a non-NULL incoming value replaces the stored one, so corrected results and
  newly available shots/odds propagate;
* ``provider_id`` is kept from whichever source has it;
* ``kickoff``/``date`` are replaced only by a row with a real kickoff time that
  comes from football-data.org (has a provider id) or when none is stored yet;
* ``source`` records the source that first created the row and is not changed.

Rows are only touched when something would actually change, which is what makes
the inserted / updated / unchanged counts meaningful on a re-run.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime, timezone

from sqlalchemy import and_, case, delete, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.models import Match, Team

logger = logging.getLogger(__name__)

NATURAL_KEY = ("league", "match_day", "home_team", "away_team")

# Columns merged with COALESCE(excluded, existing).
_COALESCE_COLS = (
    "provider_id",
    "home_goals",
    "away_goals",
    "result",
    "home_shots",
    "away_shots",
    "home_shots_on_target",
    "away_shots_on_target",
    "odds_home",
    "odds_draw",
    "odds_away",
    "odds_source",
)

_INSERT_COLS = (
    "provider_id", "date", "kickoff", "match_day", "home_team", "away_team",
    "home_goals", "away_goals", "result", "season", "league",
    "home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target",
    "odds_home", "odds_draw", "odds_away", "odds_source", "source",
)

_BATCH_SIZE = 1000


def _naive_utc(value: datetime | None) -> datetime | None:
    """Store everything as naive UTC (the `date` column is timestamp without tz)."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _normalise(record: dict) -> dict:
    row = {col: record.get(col) for col in _INSERT_COLS}
    row["date"] = _naive_utc(record.get("date") or record.get("kickoff"))
    row["kickoff"] = _naive_utc(record.get("kickoff"))
    if row["date"] is None:
        raise ValueError(f"Match record has no date: {record!r}")
    match_day = record.get("match_day")
    if isinstance(match_day, datetime):
        match_day = match_day.date()
    row["match_day"] = match_day or row["date"].date()
    row["source"] = record.get("source") or "fdorg"
    for col in ("league", "season", "home_team", "away_team"):
        if row[col] is None:
            raise ValueError(f"Match record missing {col!r}: {record!r}")
    return row


def _dedupe(rows: Iterable[dict]) -> list[dict]:
    """Collapse rows sharing a natural key (later non-null values win).

    A single INSERT .. ON CONFLICT DO UPDATE cannot touch one row twice.
    """
    merged: dict[tuple, dict] = {}
    for row in rows:
        key = tuple(row[c] for c in NATURAL_KEY)
        if key not in merged:
            merged[key] = dict(row)
            continue
        current = merged[key]
        for col, value in row.items():
            if value is not None and col not in ("source",):
                current[col] = value
    return list(merged.values())


def _release_moved_provider_ids(session, rows: list[dict]) -> None:
    """Handle a football-data.org match whose natural key changed (rescheduled).

    If a row with the same provider_id already exists under a different natural
    key, move it to the new key; if the new key is already taken by another row
    (e.g. a co.uk row), drop the stale row so the upsert merges onto that row.
    """
    tbl = Match.__table__
    by_provider = {r["provider_id"]: r for r in rows if r["provider_id"] is not None}
    if not by_provider:
        return
    existing = session.execute(
        select(tbl.c.id, tbl.c.provider_id, tbl.c.league, tbl.c.match_day,
               tbl.c.home_team, tbl.c.away_team)
        .where(tbl.c.provider_id.in_(list(by_provider)))
    ).all()
    for row in existing:
        new = by_provider[row.provider_id]
        old_key = (row.league, row.match_day, row.home_team, row.away_team)
        new_key = tuple(new[c] for c in NATURAL_KEY)
        if old_key == new_key:
            continue
        taken = session.execute(
            select(tbl.c.id).where(and_(*[tbl.c[c] == new[c] for c in NATURAL_KEY]))
        ).first()
        if taken is not None:
            session.execute(delete(tbl).where(tbl.c.id == row.id))
        else:
            session.execute(
                update(tbl).where(tbl.c.id == row.id).values(
                    league=new["league"], match_day=new["match_day"],
                    home_team=new["home_team"], away_team=new["away_team"],
                    date=new["date"],
                )
            )


def upsert_matches(session, records: Iterable[dict]) -> dict:
    """Upsert match dicts; returns {"inserted", "updated", "unchanged"} counts.

    The caller owns the transaction (commit / rollback).
    """
    rows = _dedupe(_normalise(r) for r in records)
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    if not rows:
        return counts

    tbl = Match.__table__
    _release_moved_provider_ids(session, rows)

    for start in range(0, len(rows), _BATCH_SIZE):
        batch = rows[start : start + _BATCH_SIZE]
        stmt = pg_insert(tbl).values(batch)
        excluded = stmt.excluded

        new_values = {c: func.coalesce(excluded[c], tbl.c[c]) for c in _COALESCE_COLS}
        # Kickoff/date: football-data.org (has provider_id) is authoritative; a
        # co.uk time only fills a missing one.  Prevents flip-flopping when the
        # two sources disagree by a few minutes.
        take_time = and_(
            excluded["kickoff"].isnot(None),
            or_(excluded["provider_id"].isnot(None), tbl.c.kickoff.is_(None)),
        )
        new_values["kickoff"] = case((take_time, excluded["kickoff"]), else_=tbl.c.kickoff)
        new_values["date"] = case((take_time, excluded["date"]), else_=tbl.c.date)
        new_values["season"] = excluded["season"]

        changed = or_(*[tbl.c[c].is_distinct_from(v) for c, v in new_values.items()])
        stmt = stmt.on_conflict_do_update(
            index_elements=list(NATURAL_KEY), set_=new_values, where=changed
        ).returning(tbl.c.id, literal_column("(xmax = 0)").label("inserted"))

        returned = session.execute(stmt).all()
        inserted = sum(1 for r in returned if r.inserted)
        counts["inserted"] += inserted
        counts["updated"] += len(returned) - inserted
        counts["unchanged"] += len(batch) - len(returned)

    logger.info(
        "Matches upserted - inserted=%(inserted)d updated=%(updated)d unchanged=%(unchanged)d",
        counts,
    )
    return counts


def upsert_teams(session, teams: dict[str, str], overwrite_league: bool = True) -> int:
    """Upsert Team rows from {canonical_name: league}. Returns the number of names.

    ``Team.name`` is globally unique.  With ``overwrite_league`` the league of an
    existing team is updated (domestic leagues, so promoted/relegated clubs follow
    their latest league); without it existing rows are left alone (Champions
    League participants keep their domestic league).  Ids come from the sequence.
    """
    if not teams:
        return 0
    rows = [{"name": name, "league": league} for name, league in sorted(teams.items())]
    stmt = pg_insert(Team.__table__).values(rows)
    if overwrite_league:
        stmt = stmt.on_conflict_do_update(
            index_elements=["name"],
            set_={"league": stmt.excluded["league"]},
            where=Team.__table__.c.league.is_distinct_from(stmt.excluded["league"]),
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=["name"])
    session.execute(stmt)
    return len(rows)


def teams_from_records(records: Iterable[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """Split team names in match records into (domestic, other-competition) maps."""
    domestic: dict[str, str] = {}
    other: dict[str, str] = {}
    for rec in records:
        target = other if rec["league"] == "CL" else domestic
        target[rec["home_team"]] = rec["league"]
        target[rec["away_team"]] = rec["league"]
    return domestic, other


__all__ = ["upsert_matches", "upsert_teams", "teams_from_records", "NATURAL_KEY"]
