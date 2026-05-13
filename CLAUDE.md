# Football Match Outcome Predictor — Claude Code Context

## Project Overview
An end-to-end ML pipeline that predicts Premier League match outcomes (Home Win / Draw / Away Win)
using historical match data, feature engineering, and an XGBoost classifier served via FastAPI.

## Tech Stack
- **Data**: football-data.org API, PostgreSQL, SQLAlchemy, Alembic
- **Processing**: pandas, numpy
- **Modeling**: scikit-learn, XGBoost, Optuna, MLflow, SHAP
- **API**: FastAPI, Pydantic
- **Frontend**: React, Vite, CSS (Premium UI)
- **Infra**: Docker, docker-compose, python-dotenv

## Folder Structure
```
football-predictor/
├── data/
│   ├── raw/
│   └── processed/
├── notebooks/
│   └── eda.ipynb
├── src/
│   ├── ingestion/
│   │   ├── api_client.py
│   │   └── ingest.py
│   ├── features/
│   │   ├── form.py
│   │   ├── h2h.py
│   │   └── build_dataset.py
│   ├── model/
│   │   ├── train.py
│   │   ├── evaluate.py
│   │   └── artifacts/
│   └── api/
│       └── main.py
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── App.jsx
│   │   └── index.css
│   ├── package.json
│   └── Dockerfile
├── tests/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── README.md
```

## Environment Variables (.env)
```
DATABASE_URL=postgresql://user:password@localhost:5432/football_predictor
FOOTBALL_DATA_API_KEY=your_api_key_here
MLFLOW_TRACKING_URI=http://localhost:5000
```

## Execution Order
Complete tickets in this order — each ticket depends on the previous:
```
001 → 002 → 003 → 004 → 005 → 006 → 007 → 008 → 009 → 010 → 011 → 012 → 013 → 014 → 015 → 016
```

---

## Tickets

---

### TICKET-001: Initialize project structure
**Status:** DONE

**Task:**
Create the full folder structure for `football-predictor/`:
- `data/raw`, `data/processed`
- `src/ingestion`, `src/features`, `src/model`, `src/api`
- `tests/`
- `notebooks/`
- `Dockerfile`, `.env.example`, `requirements.txt`, `README.md`
- Initialize a Python virtual environment
- Add `.gitignore` for Python + `.env` files

**Done when:** All folders and files exist, venv is created, `.gitignore` excludes `.env` and `__pycache__`

---

### TICKET-002: Set up PostgreSQL with SQLAlchemy
**Status:** DONE  
**Depends on:** TICKET-001

**Task:**
- Create a database config using SQLAlchemy + psycopg2
- Load DB credentials from `.env` via `python-dotenv`
- Define SQLAlchemy models for:
  - `Match` (id, date, home_team, away_team, home_goals, away_goals, result, season, league)
  - `Team` (id, name, league)
- Write Alembic migration `V1` to create both tables
- Write a test to verify the DB connection

**Done when:** `alembic upgrade head` runs clean, test passes against a local PostgreSQL instance

---

### TICKET-003: Football Data API client
**Status:** DONE  
**Depends on:** TICKET-001

**Task:**
- Register and store API key for `football-data.org` in `.env`
- Create `src/ingestion/api_client.py`
- Implement functions:
  - `get_matches(league_code, season)` → raw JSON
  - `get_teams(league_code)` → raw JSON
- Add retry logic and rate limiting (free tier: 10 req/min)
- Write unit tests with mocked HTTP responses using `responses` or `unittest.mock`

**Done when:** Unit tests pass with mocked responses, rate limiter prevents > 10 req/min

---

### TICKET-004: Ingest and persist raw match data
**Status:** DONE  
**Depends on:** TICKET-002, TICKET-003

**Task:**
- Create `src/ingestion/ingest.py`
- Pull Premier League (`PL`) matches for seasons 2021, 2022, 2023
- Parse raw JSON → `Match` model
- Upsert into PostgreSQL (skip duplicates on re-run via `ON CONFLICT DO NOTHING`)
- Log ingestion summary (total fetched, inserted, skipped)
- Write an integration test against a test DB

**Done when:** DB is populated with 3 seasons of PL matches, re-running ingest produces 0 inserts

---

### TICKET-005: Rolling form features
**Status:** DONE  
**Depends on:** TICKET-004

**Task:**
- Create `src/features/form.py`
- For each match, compute for **both** home and away team:
  - Last 5 match results (W/D/L encoded as 3/1/0)
  - Points per game (last 5)
  - Goals scored avg (last 5)
  - Goals conceded avg (last 5)
- Use **only data available BEFORE the match date** (no data leakage)
- Return as a `pandas` DataFrame
- Write tests to explicitly verify no data leakage (check that no future match data bleeds into features)

**Done when:** Tests pass, DataFrame has no NaNs for matches after first 5 games of a team's history

---

### TICKET-006: Head-to-head and home/away split features
**Status:** DONE  
**Depends on:** TICKET-004

**Task:**
- Create `src/features/h2h.py`
- For each match, compute:
  - H2H: last 5 meetings win rate for home team (0 if fewer than 5 meetings)
  - Home team's home win rate (current season, games before match date)
  - Away team's away win rate (current season, games before match date)
  - Days since last match for each team (fatigue proxy)
- Write tests with synthetic match data covering edge cases (team with no H2H history, first match of season)

**Done when:** All edge cases handled, tests pass

---

### TICKET-007: Build master feature table
**Status:** DONE  
**Depends on:** TICKET-005, TICKET-006

**Task:**
- Create `src/features/build_dataset.py`
- Join all features from TICKET-005 and TICKET-006 on match id
- Encode target: `Home Win=0`, `Draw=1`, `Away Win=2`
- Drop rows with NaN features (early season matches with insufficient history)
- Save final DataFrame to `data/processed/features.csv`
- Print class distribution summary

**Done when:** `features.csv` is saved, class distribution is printed, no NaN values in output

---

### TICKET-008: Baseline model — Logistic Regression
**Status:** DONE  
**Depends on:** TICKET-007

**Task:**
- Create `src/model/train.py`
- Load `data/processed/features.csv`
- Train/test split **by date** (not random — last 20% of dates = test set to avoid leakage)
- Train a `LogisticRegression` classifier with `max_iter=1000`
- Evaluate: accuracy, log-loss, confusion matrix
- Save model to `src/model/artifacts/baseline.pkl`
- Log all metrics to MLflow (experiment name: `"football-predictor"`)

**Done when:** Model saved, metrics logged to MLflow, log-loss and accuracy printed to console

---

### TICKET-009: XGBoost model with hyperparameter tuning
**Status:** DONE  
**Depends on:** TICKET-008

**Task:**
- In `src/model/train.py`, add XGBoost training flow
- Use `Optuna` for hyperparameter search (50 trials):
  - `max_depth` (3–10)
  - `learning_rate` (0.01–0.3)
  - `n_estimators` (100–500)
  - `subsample` (0.6–1.0)
- Optimize for **log-loss** on validation set
- Log best params + all metrics to MLflow
- Save best model to `src/model/artifacts/xgb_best.pkl`
- Print a comparison table: Baseline vs XGBoost (accuracy + log-loss)

**Done when:** Best model saved, MLflow shows both runs, XGBoost log-loss ≤ baseline log-loss

---

### TICKET-010: Feature importance analysis
**Status:** DONE  
**Depends on:** TICKET-009

**Task:**
- Create `src/model/evaluate.py`
- Load `src/model/artifacts/xgb_best.pkl`
- Compute SHAP values using `shap.TreeExplainer`
- Save SHAP summary plot to `data/processed/shap_summary.png`
- Print top 10 most important features by mean absolute SHAP value
- Save a text evaluation report to `data/processed/eval_report.txt` including:
  - Model name, training date
  - Test accuracy, log-loss, confusion matrix
  - Top 10 features

**Done when:** `shap_summary.png` and `eval_report.txt` both exist and are populated

---

### TICKET-011: FastAPI prediction endpoint
**Status:** DONE  
**Depends on:** TICKET-010

**Task:**
- Create `src/api/main.py` with a FastAPI app
- `POST /predict` endpoint:
  - **Input:** `{ "home_team": str, "away_team": str, "date": str (YYYY-MM-DD) }`
  - **Output:** `{ "home_win": float, "draw": float, "away_win": float }`
- Load XGBoost model at app startup using a lifespan context
- Compute features on-the-fly from DB for the given teams (reuse logic from TICKET-005, TICKET-006)
- Add input validation with Pydantic (validate date format, non-empty team names)
- Return `422` with descriptive error if team not found in DB
- Write `pytest` tests for the endpoint using `TestClient`

**Done when:** `pytest tests/test_api.py` passes, `/predict` returns valid probabilities that sum to ~1.0

---

### TICKET-012: Health check and team listing endpoints
**Status:** DONE  
**Depends on:** TICKET-011

**Task:**
- `GET /health` → `{ "status": "ok", "model": "xgb_best", "version": "1.0.0" }`
- `GET /teams` → list of all team names in DB, sorted alphabetically
- Add structured logging throughout the API using Python's `logging` module (log each request with team names + predicted probabilities)
- Write tests for both endpoints

**Done when:** All 3 endpoints tested and passing, logs appear in console on each request

---

### TICKET-013: Dockerize the application
**Status:** DONE  
**Depends on:** TICKET-012

**Task:**
- Write `Dockerfile` for the FastAPI app (use `python:3.11-slim`, multi-stage build optional)
- Write `docker-compose.yml` with three services:
  - `app`: FastAPI (port 8000)
  - `db`: PostgreSQL 15 (port 5432, volume for persistence)
  - `mlflow`: MLflow tracking server (port 5000)
- Add a `entrypoint.sh` that:
  1. Runs `alembic upgrade head`
  2. Starts the FastAPI server with `uvicorn`
- Ensure `.env` is loaded from the host
- Test with `docker-compose up --build` and hit `GET /health`

**Done when:** `docker-compose up --build` starts all services, `/health` returns 200 from inside Docker

---

### TICKET-014: Write project README
**Status:** DONE  
**Depends on:** TICKET-013

**Task:**
Write `README.md` covering:
- Project overview and motivation
- Architecture diagram (ASCII is fine)
- Prerequisites (Python 3.11, Docker, PostgreSQL)
- Setup instructions (clone, `.env` setup, `docker-compose up`)
- How to run each stage manually:
  - `python -m src.ingestion.ingest`
  - `python -m src.features.build_dataset`
  - `python -m src.model.train`
  - `python -m src.model.evaluate`
- Example `curl` request to `/predict`
- MLflow UI instructions (`http://localhost:5000`)
- Known limitations and next steps (e.g., add more leagues, Elo ratings feature, betting odds as feature)

**Done when:** README renders cleanly on GitHub, all commands are copy-pasteable and correct

---

### TICKET-015: Build Premium Frontend UI for Upcoming Matches
**Status:** DONE  
**Depends on:** TICKET-013

**Task:**
- Add a new `GET /upcoming` endpoint to the FastAPI app that computes predictions for future matches.
- Enable `CORSMiddleware` in FastAPI.
- Initialize a React + Vite application in the `frontend/` directory.
- Design a premium, dark-mode, glassmorphism UI using vanilla CSS (`index.css`).
- Build `Dashboard.jsx` to fetch and render the `/upcoming` predictions dynamically.
- Build `MatchCard.jsx` to visualize win/draw/loss probabilities using animated bars.
- Add a multi-stage `Dockerfile` to the frontend utilizing Nginx.
- Add the `frontend` service (port 3000) to `docker-compose.yml`.

**Done when:** Running `docker-compose up` serves the beautiful UI on port 3000 displaying upcoming matches securely fetched from the backend.

---

### TICKET-016: Live Endpoint Testing & Validation
**Status:** DONE  
**Date completed:** 2026-05-12  
**Depends on:** TICKET-012, TICKET-013

**Task:**
- Run the full `pytest tests/test_api.py` suite against the FastAPI app using `TestClient` (mocked DB + model)
- Spin up the PostgreSQL DB via `docker-compose up -d db` and start the uvicorn server locally
- Run Alembic migrations (`alembic upgrade head`) against the live Docker DB
- Validate all 3 endpoints live via Swagger UI at `http://localhost:8000/docs`:
  - `GET /health` → `200 {"status": "ok", "model": "xgb_best", "version": "1.0.0"}`
  - `GET /teams` → `200` alphabetically sorted list of 20 Premier League teams
  - `POST /predict` (valid) → `200` with probabilities summing to 1.0
  - `POST /predict` (same team) → `422` "home_team and away_team must differ"
  - `POST /predict` (bad date) → `422` "must be YYYY-MM-DD format"
  - `POST /predict` (unknown team) → `422` "Team not found: Unknown FC"

**Results:**
- `pytest tests/test_api.py` — **11/11 passed** in 4.32s (Python 3.14.0 / pytest 9.0.3)
- Live server — all 6 Swagger UI tests passed
- Example live prediction: Arsenal FC vs Chelsea FC (2024-03-01) →
  `{"home_win": 0.5066, "draw": 0.0821, "away_win": 0.4112}` (sums to 1.0 ✅)
- Structured request logs confirmed in uvicorn console output

**Done when:** All unit tests pass and all 3 live endpoints return correct responses with the Docker DB running

### TICKET-017: Multi-League Dashboard Support
**Status:** DONE  
**Date completed:** 2026-05-12  
**Depends on:** TICKET-015

**Task:**
- Update `/upcoming` backend endpoint to fetch matches for top 5 leagues + Champions League (`PL`, `PD`, `SA`, `BL1`, `FL1`, `CL`).
- Include `league` property in the API response.
- Remove strict DB check to allow matches to be returned even if missing historical features (falling back to generic predictions).
- Update frontend `Dashboard.jsx` to group and display matches by league.
- Add CSS styling for league section headers.
- Rebuild Docker containers.

**Results:**
- Dashboard successfully displays upcoming fixtures categorized by league.

---

## Key Rules for Claude Code

1. **No data leakage** — features must only use data available strictly before the match date. Tests must enforce this.
2. **Train/test split by date** — never use random splits for time-series data.
3. **Upserts over inserts** — all DB writes must be idempotent (safe to re-run).
4. **Environment variables only** — no hardcoded credentials anywhere.
5. **One ticket at a time** — complete and verify each ticket before starting the next.
