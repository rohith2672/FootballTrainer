"""Football match predictor API (contract: docs/api_contract.md, v2).

Features come from exactly one place, ``src.features.engine.compute_features``
(see ``src.api.serving``). A missing / incompatible model never crashes startup:
prediction endpoints answer 503 until a valid model is available.
"""
import datetime as dt
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from src.api import model_store, serving, store
from src.api import track_record as tr
from src.database import DatabaseNotConfigured, get_db
from src.features.columns import LEAGUES
from src.ingestion import api_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)

API_VERSION = "2.0.0"
DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://localhost:5173"
NO_MODEL_DETAIL = "Model not loaded"
NO_SOURCE_DETAIL = "Fixture source not configured (FOOTBALL_DATA_API_KEY missing)"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model_state = model_store.load_model_state()
    yield


app = FastAPI(title="Football Match Predictor", version=API_VERSION, lifespan=lifespan)


def cors_origins() -> List[str]:
    raw = os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Partial-Failure"],
)


@app.exception_handler(DatabaseNotConfigured)
async def database_not_configured(request: Request, exc: DatabaseNotConfigured):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _state(request: Request) -> model_store.ModelState:
    return getattr(request.app.state, "model_state", None) or model_store.ModelState(
        error=NO_MODEL_DETAIL
    )


def require_model(request: Request) -> model_store.ModelState:
    state = _state(request)
    if not state.ready:
        raise HTTPException(status_code=503, detail=NO_MODEL_DETAIL)
    return state


# ---------------------------------------------------------------------------
# /predict
# ---------------------------------------------------------------------------
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
            dt.date.fromisoformat(v)
        except ValueError:
            raise ValueError("must be YYYY-MM-DD format")
        return v


class PredictResponse(BaseModel):
    home_win: float
    draw: float
    away_win: float


@app.post("/predict", response_model=PredictResponse)
def predict(request: PredictRequest, req: Request, db: Session = Depends(get_db)):
    state = require_model(req)
    if request.home_team == request.away_team:
        raise HTTPException(status_code=422, detail="home_team and away_team must differ")

    history = store.load_history(db)
    known = set(store.list_team_names(db)) | serving.history_teams(history)
    for name in (request.home_team, request.away_team):
        if name not in known:
            raise HTTPException(status_code=422, detail=f"Team not found: {name}")

    league = serving.infer_league(history, request.home_team) or serving.infer_league(
        history, request.away_team
    )
    if league is None:
        raise HTTPException(status_code=422, detail=f"No match history for {request.home_team}")
    kickoff = dt.datetime.combine(dt.date.fromisoformat(request.date), dt.time.min)
    fixture = {
        "fixture_id": None, "league": league,
        "home_team": request.home_team, "away_team": request.away_team, "kickoff": kickoff,
    }
    result = serving.predict_fixtures(state.model, history, [fixture])[0]
    if not result["prediction_available"]:
        if result["reason"] == "Prediction error":
            raise HTTPException(status_code=500, detail="Prediction error")
        raise HTTPException(status_code=422, detail=result["reason"])

    logger.info(
        "predict | home=%s away=%s date=%s -> home_win=%.3f draw=%.3f away_win=%.3f",
        request.home_team, request.away_team, request.date,
        result["home_win"], result["draw"], result["away_win"],
    )
    return PredictResponse(
        home_win=result["home_win"], draw=result["draw"], away_win=result["away_win"]
    )


# ---------------------------------------------------------------------------
# /health, /teams
# ---------------------------------------------------------------------------
@app.get("/health")
def health(request: Request):
    state = _state(request)
    reg = state.registry or {}
    body = {
        "status": "ok",
        "model_loaded": state.ready,
        "db": store.ping_db(),
        "model": reg.get("best_model") if state.ready else None,
        "model_version": state.version if state.ready else None,
        "trained_at": reg.get("trained_at") if state.ready else None,
        "version": API_VERSION,
    }
    if not state.ready:
        body["status"] = "unavailable"
        body["detail"] = state.error or NO_MODEL_DETAIL
        return JSONResponse(status_code=503, content=body)
    if body["db"] != "ok":
        body["status"] = "degraded"
    return body


@app.get("/teams")
def list_teams(db: Session = Depends(get_db)):
    teams = store.list_team_names(db)
    logger.info("teams | returned %d teams", len(teams))
    return teams


# ---------------------------------------------------------------------------
# /upcoming
# ---------------------------------------------------------------------------
class Factor(BaseModel):
    feature: str
    label: str
    value: Optional[float] = None
    contribution: float


class SideDetails(BaseModel):
    elo: Optional[float] = None
    form_pts_pg: Optional[float] = None
    goals_for_avg: Optional[float] = None
    goals_against_avg: Optional[float] = None
    shots_for_avg: Optional[float] = None
    days_since_last: Optional[float] = None
    form_n: Optional[int] = None


class H2HDetails(BaseModel):
    n: Optional[int] = None
    home_pts_rate: Optional[float] = None


class Details(BaseModel):
    home: SideDetails
    away: SideDetails
    h2h: H2HDetails


class UpcomingMatchResponse(BaseModel):
    fixture_id: Optional[int] = None
    league: str
    home_team: str
    away_team: str
    date: str
    kickoff: str
    home_win: Optional[float] = None
    draw: Optional[float] = None
    away_win: Optional[float] = None
    prediction_available: bool
    is_fallback: bool
    reason: Optional[str] = None
    model_version: str
    top_factors: List[Factor] = []
    details: Optional[Details] = None


def _parse_day(name: str, value: Optional[str]) -> Optional[dt.date]:
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} must be YYYY-MM-DD format")


def fetch_upstream_fixtures(leagues: List[str]) -> tuple:
    """Fetch the leagues concurrently (cached). Returns ``(payloads, failed)``."""
    payloads: Dict[str, dict] = {}
    failed: List[str] = []

    def one(code: str):
        return code, api_client.get_upcoming_matches_cached(code)

    with ThreadPoolExecutor(max_workers=max(1, len(leagues))) as pool:
        futures = {code: pool.submit(one, code) for code in leagues}
        for code, fut in futures.items():
            try:
                payloads[code] = fut.result()[1]
            except Exception as exc:
                logger.error("Failed to fetch upcoming matches for %s: %s", code, exc)
                failed.append(code)
    return payloads, failed


@app.get("/upcoming", response_model=List[UpcomingMatchResponse])
def get_upcoming(
    request: Request,
    response: Response,
    league: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    state = require_model(request)
    if league is not None and league not in LEAGUES:
        raise HTTPException(status_code=422, detail=f"league must be one of {', '.join(LEAGUES)}")
    day_from, day_to = _parse_day("date_from", date_from), _parse_day("date_to", date_to)
    if not api_client.get_api_key():
        raise HTTPException(status_code=503, detail=NO_SOURCE_DETAIL)

    leagues = [league] if league else list(LEAGUES)
    payloads, failed = fetch_upstream_fixtures(leagues)
    if len(failed) == len(leagues):
        raise HTTPException(status_code=503, detail="Fixture source unavailable (all league requests failed)")
    if failed:
        response.headers["X-Partial-Failure"] = ",".join(c for c in leagues if c in failed)

    fixtures = serving.parse_fixtures(payloads)
    if day_from:
        fixtures = [f for f in fixtures if f["kickoff"].date() >= day_from]
    if day_to:
        fixtures = [f for f in fixtures if f["kickoff"].date() <= day_to]
    fixtures = fixtures[:limit]
    if not fixtures:
        return []

    history = store.load_history(db)             # one query for all fixtures
    results = serving.predict_fixtures(state.model, history, fixtures)

    now = store.utcnow()
    to_store = [r for r in results if r["prediction_available"] and now < r["kickoff"]]
    if to_store:
        try:
            store.persist_predictions(db, to_store, state.version, now)
        except Exception:
            logger.exception("Persisting predictions failed; continuing")

    return [
        UpcomingMatchResponse(
            fixture_id=r["fixture_id"], league=r["league"],
            home_team=r["home_team"], away_team=r["away_team"],
            date=r["kickoff"].date().isoformat(), kickoff=serving.utc_iso(r["kickoff"]),
            home_win=r["home_win"], draw=r["draw"], away_win=r["away_win"],
            prediction_available=r["prediction_available"], is_fallback=r["is_fallback"],
            reason=r["reason"], model_version=state.version,
            top_factors=r["top_factors"], details=r["details"],
        )
        for r in results
    ]


# ---------------------------------------------------------------------------
# /track-record
# ---------------------------------------------------------------------------
@app.get("/track-record")
def track_record(
    request: Request,
    league: Optional[str] = Query(None),
    weeks: int = Query(26, ge=1, le=520),
    db: Session = Depends(get_db),
):
    if league is not None and league not in LEAGUES:
        raise HTTPException(status_code=422, detail=f"league must be one of {', '.join(LEAGUES)}")
    state = _state(request)
    version = state.version if state.ready else None

    n_predictions, rows = store.fetch_settled(db, league=league, weeks=weeks, model_version=version)
    counts = None
    if rows:
        start = min(r["kickoff"] for r in rows).date()
        counts = store.class_counts_before(db, start, league)
    return tr.compute_track_record(
        rows,
        n_predictions=n_predictions,
        class_counts=counts,
        model_version=version,
        registry=state.registry,
    )
