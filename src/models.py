from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from src.database import Base


def _default_match_day(context):
    """ORM-insert fallback: UTC day of `date` when match_day is not given."""
    return context.get_current_parameters()["date"].date()


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    league = Column(String, nullable=False)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        # Natural key shared by football-data.org and football-data.co.uk rows.
        UniqueConstraint(
            "league", "match_day", "home_team", "away_team", name="uq_matches_natural_key"
        ),
        UniqueConstraint("provider_id", name="uq_matches_provider_id"),
    )

    # Surrogate key (BIGSERIAL). Pre-existing rows keep their old id, which was
    # the football-data.org match id; that value is also copied to provider_id.
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # football-data.org match id; NULL for football-data.co.uk-only rows.
    provider_id = Column(BigInteger, nullable=True)
    date = Column(DateTime, nullable=False)  # naive UTC; midnight when kickoff is unknown
    kickoff = Column(DateTime, nullable=True)  # naive UTC, only when a real time is known
    match_day = Column(Date, nullable=False, default=_default_match_day)  # UTC calendar day of `date`
    home_team = Column(String, nullable=False)
    away_team = Column(String, nullable=False)
    home_goals = Column(Integer)
    away_goals = Column(Integer)
    result = Column(String(1))  # H / D / A
    season = Column(Integer, nullable=False)  # season start year (July 1 rollover)
    league = Column(String, nullable=False)

    home_shots = Column(Integer, nullable=True)
    away_shots = Column(Integer, nullable=True)
    home_shots_on_target = Column(Integer, nullable=True)
    away_shots_on_target = Column(Integer, nullable=True)

    # Decimal 1X2 odds; odds_source names the bookmaker/market column chain used
    # (e.g. "pinnacle_close"), see src/ingestion/csv_history.py ODDS_CHAIN.
    odds_home = Column(Float, nullable=True)
    odds_draw = Column(Float, nullable=True)
    odds_away = Column(Float, nullable=True)
    odds_source = Column(String, nullable=True)

    source = Column(String, nullable=False, default="fdorg", server_default="fdorg")  # fdorg | couk
