import logging
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database import SessionLocal
from src.ingestion.api_client import get_matches, get_teams
from src.models import Match, Team

logger = logging.getLogger(__name__)

LEAGUE = "PL"
SEASONS = [2023, 2024]


def _parse_result(home_goals: int | None, away_goals: int | None) -> str | None:
    if home_goals is None or away_goals is None:
        return None
    if home_goals > away_goals:
        return "H"
    if home_goals == away_goals:
        return "D"
    return "A"


def ingest_teams(league: str = LEAGUE) -> None:
    data = get_teams(league, season=SEASONS[-1])
    teams = data.get("teams", [])

    rows = [{"id": t["id"], "name": t["name"], "league": league} for t in teams]
    if not rows:
        return

    session = SessionLocal()
    try:
        stmt = pg_insert(Team).values(rows).on_conflict_do_nothing(index_elements=["name"])
        session.execute(stmt)
        session.commit()
        logger.info("Teams upserted — count=%d league=%s", len(rows), league)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ingest_matches(league: str = LEAGUE, seasons: list[int] = None) -> dict:
    if seasons is None:
        seasons = SEASONS

    total_fetched = 0
    total_inserted = 0
    total_skipped = 0

    session = SessionLocal()
    try:
        for season in seasons:
            data = get_matches(league, season)
            all_matches = data.get("matches", [])
            finished = [m for m in all_matches if m.get("status") == "FINISHED"]
            total_fetched += len(finished)

            existing_ids: set[int] = {
                row[0]
                for row in session.query(Match.id)
                .filter(Match.league == league, Match.season == season)
                .all()
            }

            new_rows = []
            for m in finished:
                if m["id"] in existing_ids:
                    total_skipped += 1
                    continue

                home_goals = m["score"]["fullTime"].get("home")
                away_goals = m["score"]["fullTime"].get("away")
                new_rows.append(
                    {
                        "id": m["id"],
                        "date": datetime.fromisoformat(
                            m["utcDate"].replace("Z", "+00:00")
                        ),
                        "home_team": m["homeTeam"]["name"],
                        "away_team": m["awayTeam"]["name"],
                        "home_goals": home_goals,
                        "away_goals": away_goals,
                        "result": _parse_result(home_goals, away_goals),
                        "season": season,
                        "league": league,
                    }
                )

            if new_rows:
                stmt = pg_insert(Match).values(new_rows).on_conflict_do_nothing(
                    index_elements=["id"]
                )
                session.execute(stmt)
                total_inserted += len(new_rows)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info(
        "Ingestion complete — fetched=%d inserted=%d skipped=%d",
        total_fetched,
        total_inserted,
        total_skipped,
    )
    return {"fetched": total_fetched, "inserted": total_inserted, "skipped": total_skipped}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ingest_teams()
    ingest_matches()
