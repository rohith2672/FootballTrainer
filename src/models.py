from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from src.database import Base


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    league = Column(String, nullable=False)


class Match(Base):
    __tablename__ = "matches"

    id = Column(BigInteger, primary_key=True)  # football-data.org match id
    date = Column(DateTime, nullable=False)
    home_team = Column(String, nullable=False)
    away_team = Column(String, nullable=False)
    home_goals = Column(Integer)
    away_goals = Column(Integer)
    result = Column(String(1))  # H / D / A
    season = Column(Integer, nullable=False)
    league = Column(String, nullable=False)
