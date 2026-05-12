import datetime
import logging
import pickle
from contextlib import asynccontextmanager

import numpy as np
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from src.database import get_db
from src.features.form import _compute_form_from_matches
from src.features.h2h import _compute_h2h_from_matches
from src.model.train import FEATURE_COLS, XGB_PATH
from src.models import Match, Team

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with open(XGB_PATH, "rb") as f:
        app.state.model = pickle.load(f)
    yield


app = FastAPI(title="Football Match Predictor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PredictRequest(BaseModel):
    home_team: str
    away_team: str
    date: str

    @field_validator("home_team", "away_team")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()

    @field_validator("date")
    @classmethod
    def valid_date(cls, v: str) -> str:
        try:
            datetime.date.fromisoformat(v)
        except ValueError:
            raise ValueError("must be YYYY-MM-DD format")
        return v


class PredictResponse(BaseModel):
    home_win: float
    draw: float
    away_win: float


def _check_team(name: str, db: Session) -> None:
    if not db.query(Team).filter(Team.name == name).first():
        raise HTTPException(status_code=422, detail=f"Team not found: {name}")


def compute_features_for_match(
    db: Session, home_team: str, away_team: str, match_date: datetime.date
) -> np.ndarray:
    match_dt = datetime.datetime.combine(match_date, datetime.time.min)

    raw = (
        db.query(Match)
        .filter(Match.home_goals != None, Match.date < match_dt)  # noqa: E711
        .order_by(Match.date)
        .all()
    )

    matches = [
        {
            "id": m.id,
            "date": m.date,
            "home_team": m.home_team,
            "away_team": m.away_team,
            "home_goals": m.home_goals,
            "away_goals": m.away_goals,
            "result": m.result,
            "season": m.season,
        }
        for m in raw
    ]

    synthetic = {
        "id": -1,
        "date": match_dt,
        "home_team": home_team,
        "away_team": away_team,
        "home_goals": 0,
        "away_goals": 0,
        "result": "H",
        "season": match_date.year,
    }
    matches.append(synthetic)

    form_row = _compute_form_from_matches(matches).iloc[-1]
    h2h_row = _compute_h2h_from_matches(matches).iloc[-1]

    feature_values = [
        form_row["home_form_pts_pg"],
        form_row["home_form_goals_scored_avg"],
        form_row["home_form_goals_conceded_avg"],
        form_row["away_form_pts_pg"],
        form_row["away_form_goals_scored_avg"],
        form_row["away_form_goals_conceded_avg"],
        h2h_row["h2h_home_win_rate"],
        h2h_row["home_team_home_win_rate"],
        h2h_row["away_team_away_win_rate"],
        h2h_row["home_days_since_last"],
        h2h_row["away_days_since_last"],
    ]

    return np.array([feature_values], dtype=float)


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest, db: Session = Depends(get_db)):
    if request.home_team == request.away_team:
        raise HTTPException(status_code=422, detail="home_team and away_team must differ")

    _check_team(request.home_team, db)
    _check_team(request.away_team, db)

    match_date = datetime.date.fromisoformat(request.date)
    features = compute_features_for_match(db, request.home_team, request.away_team, match_date)

    model = app.state.model
    proba = model.predict_proba(features)[0]

    logger.info(
        "predict | home=%s away=%s date=%s -> home_win=%.3f draw=%.3f away_win=%.3f",
        request.home_team, request.away_team, request.date,
        proba[0], proba[1], proba[2],
    )

    return PredictResponse(home_win=float(proba[0]), draw=float(proba[1]), away_win=float(proba[2]))


@app.get("/health")
def health():
    return {"status": "ok", "model": "xgb_best", "version": "1.0.0"}


@app.get("/teams")
def list_teams(db: Session = Depends(get_db)):
    teams = db.query(Team).order_by(Team.name).all()
    logger.info("teams | returned %d teams", len(teams))
    return [t.name for t in teams]


from src.ingestion.api_client import get_upcoming_matches

class UpcomingMatchResponse(BaseModel):
    home_team: str
    away_team: str
    date: str
    home_win: float
    draw: float
    away_win: float

@app.get("/upcoming", response_model=list[UpcomingMatchResponse])
def get_upcoming(db: Session = Depends(get_db)):
    try:
        raw_data = get_upcoming_matches("PL")
    except Exception as e:
        logger.error("Failed to fetch upcoming matches: %s", e)
        raise HTTPException(status_code=502, detail="Failed to fetch upcoming matches from upstream API")
    
    matches = raw_data.get("matches", [])
    results = []
    for m in matches:
        home_team = m.get("homeTeam", {}).get("name")
        away_team = m.get("awayTeam", {}).get("name")
        match_date_str = m.get("utcDate")
        if not home_team or not away_team or not match_date_str:
            continue
            
        try:
            match_date = datetime.datetime.fromisoformat(match_date_str.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        
        if not db.query(Team).filter(Team.name == home_team).first() or \
           not db.query(Team).filter(Team.name == away_team).first():
            continue
            
        try:
            features = compute_features_for_match(db, home_team, away_team, match_date)
            model = app.state.model
            proba = model.predict_proba(features)[0]
            results.append(
                UpcomingMatchResponse(
                    home_team=home_team,
                    away_team=away_team,
                    date=match_date.isoformat(),
                    home_win=float(proba[0]),
                    draw=float(proba[1]),
                    away_win=float(proba[2])
                )
            )
        except Exception as e:
            logger.warning("Could not compute prediction for %s vs %s: %s", home_team, away_team, e)
            
    return results
