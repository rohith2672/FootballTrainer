# Football Match Outcome Predictor

An end-to-end ML pipeline that predicts football match outcomes (Home Win / Draw /
Away Win) for the Premier League, La Liga, Serie A, Bundesliga, Ligue 1 and the
Champions League. It ingests historical results, builds point-in-time features,
trains a walk-forward-validated model and serves predictions, team analysis and
football news through FastAPI to a React dashboard.

## Highlights

- **Data:** about ten seasons of football-data.co.uk history for the five
  domestic leagues (results, shots, kick-off times), plus current-season
  fixtures and results from football-data.org. All writes are idempotent upserts.
- **Features:** one point-in-time engine (`src/features/engine.py`) shared by
  training and serving, so the API sees exactly the features the model was
  trained on. Only data from before each match is used.
- **Model:** XGBoost on 25 features, selected by season walk-forward
  cross-validation and scored once on an untouched holdout (see
  [Model](#model)).
- **API:** predictions with top contributing factors, a stored-prediction track
  record, team profiles, Elo history, head-to-head and cached news headlines.
- **Dashboard:** upcoming fixtures by league, team pages, favourite teams,
  track record, news, light/dark/system theme and a mobile bottom tab bar.

Betting odds are parsed and stored, but by design they are never a model input
or an evaluation baseline. The yardsticks are Elo, the class prior and a uniform
guess.

## Architecture

```
football-data.co.uk CSVs ──┐
                           ├─► src/ingestion (ingest, refresh, upsert) ─► PostgreSQL
football-data.org API ─────┘                                                │
                                                                            ▼
                 src/features/engine.py (Elo, Poisson goals model, form, shots, H2H, rest)
                                    │                                   │
                                    ▼                                   │
        src/features/build_dataset.py ─► data/processed/features.csv    │
                                    │                                   │
                                    ▼                                   │
     src/model/train.py (LR, XGBoost, LightGBM, calibrated, ensemble;   │
     walk-forward CV + holdout; MLflow) ─► src/model/artifacts/         │
                                           best_model.pkl               │
                                           model_registry.json          │
                                    │                                   │
                                    ▼                                   ▼
               src/api (FastAPI, port 8000): predictions, track record, teams, h2h, news
                                    │                       ▲
                                    ▼                       │
               frontend (React + Vite, nginx on port 3000)  src/news/worker.py (hourly BBC RSS)
```

## Prerequisites

- Python 3.11
- Node.js (for the frontend) and npm
- Docker and Docker Compose (for the full stack)
- PostgreSQL 15+ (only for local runs without Docker)
- A free [football-data.org](https://www.football-data.org/) API key for
  upcoming fixtures and current-season results. History, training, team
  analysis and news work without it.

## Setup

### 1. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```
DATABASE_URL=postgresql://user:password@localhost:5433/football_predictor
FOOTBALL_DATA_API_KEY=your_api_key_here
MLFLOW_TRACKING_URI=http://localhost:5000
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

Optional: `BEST_MODEL_PATH` and `REGISTRY_PATH` override where the API loads the
model and its registry. Never commit `.env`.

### 2. Start the stack with Docker

```bash
docker compose up --build -d
```

| Service | Host port | Description |
|---------|-----------|-------------|
| `frontend` | 3000 | React dashboard served by nginx (proxies `/api` to the app) |
| `app` | 8000 | FastAPI server; runs `alembic upgrade head` on start |
| `db` | 5433 | PostgreSQL 15 (container port 5432) |
| `mlflow` | 5000 | MLflow tracking UI |
| `news-worker` | – | Hourly BBC Sport RSS headline refresh |

The `app` container mounts `./data` and `./src/model/artifacts`, so train a model
(below) before expecting predictions. Check it with:

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok", "model_loaded": true, "db": "ok", "model": "xgboost",
 "model_version": "...", "trained_at": "2026-10-20 16:12:08", "version": "2.0.0"}
```

`status` is `degraded` when the database is unreachable, and the endpoint returns
`503` with `"status": "unavailable"` when no model is loaded.

## Running each stage manually

Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv

# Windows
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
```

### 1. Ingest match data

```bash
# football-data.co.uk history (5 domestic leagues, 10 completed seasons + current); no API key needed
python -m src.ingestion.ingest --source couk

# Everything: co.uk history plus football-data.org current season (CL also gets the previous season)
python -m src.ingestion.ingest
```

Other flags: `--leagues PL PD ...`, `--seasons 2023 2024` (season start years),
`--raw-dir`, `--no-download` (use CSVs already in `data/raw/couk`) and
`--force-download`. Re-running is safe.

Weekly refresh of the current season only (needs `DATABASE_URL` and
`FOOTBALL_DATA_API_KEY`):

```bash
python -m src.ingestion.refresh
```

### 2. Build the feature table

```bash
# From the database
python -m src.features.build_dataset

# Or straight from downloaded co.uk CSVs, no database needed
python -m src.features.build_dataset --from-csv data/raw/couk
```

Writes `data/processed/features.csv` (one burn-in season is dropped; override with
`--burn-in-seasons`, output path with `--output`).

### 3. Train

```bash
python -m src.model.train --n-trials 100
```

Tunes Logistic Regression, XGBoost and LightGBM with Optuna on season
walk-forward folds, adds calibrated variants and a stacking ensemble, selects on
mean walk-forward log-loss, refits on all development data and scores once on the
holdout. Saves `src/model/artifacts/best_model.pkl` and `model_registry.json`.
The default is 50 trials; the shipped model used 100. Other flags: `--features`,
`--artifacts-dir`, `--mlflow-uri`, `--seed`.

### 4. Evaluate

```bash
python -m src.model.evaluate
```

Scores the saved model on the holdout and writes `data/processed/eval_report.txt`
and a feature-importance plot at `data/processed/shap_summary.png` (SHAP where the
model supports it, otherwise a fallback method named in the report).

### 5. Serve

```bash
python -m uvicorn src.api.main:app --reload
python -m src.news.worker          # optional, separate terminal

cd frontend
npm ci
npm run dev                        # http://localhost:5173, calls http://localhost:8000
```

## Model

The current model (trained 2026-10-20) is XGBoost on 25 features:

- **Elo (4):** tuned adaptive Elo shared across competitions (K=14, 5 % season
  regression to the league mean, per-league online home advantage).
- **Poisson goals model (7, `pois_*`):** online Poisson/Dixon–Coles expected goals
  and outcome probabilities.
- **Form (6) and shots (2):** last-5 points per game, goals for/against, shots.
- **Rest (2), form sample size (2) and shrunk head-to-head (2).**

The engine computes 44 columns (`ENGINE_COLS`); the model uses the 25 in
`FEATURE_COLS` (`src/features/columns.py`).

Holdout: 2,049 matches, 2025-08-15 to 2026-10-12, five domestic leagues.

| | Holdout log-loss | Holdout accuracy |
|---|---|---|
| **XGBoost (served)** | **0.9884** | **0.521** |
| Poisson goals model alone | 0.9916 | 0.520 |
| Elo | 0.9932 | 0.519 |
| Class prior | 1.0712 | 0.442 |
| Uniform | 1.0986 | 0.442 |

Walk-forward (8 seasons) log-loss is 0.9829. The Poisson baseline scores 0.9815
there, but its constants were tuned on those folds, so only the holdout is a clean
comparison. Like most 1X2 models it almost never predicts a draw as the most
likely outcome. Experiment log: `docs/model_experiments_2026-10-20.md`.

## API

Full contract: `docs/api_contract.md`. Interactive docs: `http://localhost:8000/docs`.

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Model, database and version status |
| `POST /predict` | `{home_team, away_team, date}` → `{home_win, draw, away_win}` |
| `GET /upcoming` | Upcoming fixtures with predictions, top factors and details. Query: `league`, `date_from`, `date_to`, `team`, `limit`. Needs the football-data.org key |
| `GET /track-record` | Accuracy and log-loss of stored predictions against results, plus the backtest. Query: `league`, `weeks`, `team` |
| `GET /teams` | Flat, alphabetically sorted list of team names |
| `GET /teams/index` | All known teams with their league, sorted by league then name |
| `GET /teams/{name}` | Team profile: Elo, league rank, form, home/away split, recent averages, rest days, next fixture. Query: `as_of` |
| `GET /teams/{name}/matches` | Recent results. Query: `limit`, `venue` (`all`, `home`, `away`) |
| `GET /teams/{name}/elo-history` | Elo after each match (last 365 days by default). Query: `since` |
| `GET /h2h?a=&b=` | Head-to-head summary and recent meetings. Query: `limit` |
| `GET /news` | Cached BBC Sport football headlines and source status. Query: `limit` (max 100) |

Team names are exact canonical names (for example `Arsenal FC`); URL-encode them.
Unknown teams return `404` on team endpoints and `422` on `/predict`. Finished-match
history is cached in-process for 300 seconds.

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"home_team": "Arsenal FC", "away_team": "Chelsea FC", "date": "2026-11-01"}'

curl "http://localhost:8000/teams/Arsenal%20FC"
curl "http://localhost:8000/h2h?a=Arsenal%20FC&b=Chelsea%20FC"
```

## Dashboard

- **Upcoming:** fixtures grouped by league with probability bars, an explanation
  panel and honest "no prediction" cards, plus a "My teams" view. League, search,
  date and sort filters are kept in the URL hash so views can be shared.
- **Team page** (`#/team/<name>`): Elo history chart, season and recent-average
  cards, recent matches, match preparation for the next fixture (with
  head-to-head), how the model has done on the team, and team news; with a team
  picker.
- **Favourites:** star any number of teams and choose a primary one; favourites
  are highlighted on the dashboard, cards and news. Stored only in the browser
  (`localStorage` key `ft.favourites.v1`).
- **Track record** (`#/track-record`) and **News** (`#/news`).
- Light, dark or system theme (`ft.theme.v1`), a compact header on desktop and a
  bottom tab bar on mobile.

## News

The `news-worker` checks the
[BBC football RSS feed](https://feeds.bbci.co.uk/sport/football/rss.xml) every
hour, even when no browser is open, following
[BBC RSS guidance](https://www.bbc.co.uk/sport/articles/cqllxj2n4kyo). The News tab
reads the cache every five minutes while visible. News is marked delayed after 90
minutes without a successful check and cached headlines expire after 24 hours.
Only headline metadata and links are stored; news never feeds the model.

## Tests

```bash
python -m pytest -q

cd frontend
npm test
npm run lint
```

PostgreSQL tests are skipped unless `TEST_DATABASE_URL` points to a disposable
database; they create isolated schemas and never touch the application database.
Both `postgresql://` and `postgresql+psycopg2://` URLs select the psycopg2 driver.

## MLflow

Training logs to the `football-predictor` experiment at `--mlflow-uri` (or
`MLFLOW_TRACKING_URI`). Each run records the selected model, CV settings, tuned
parameters, walk-forward and holdout metrics for every model and baseline, and the
registry and model files. With Docker the UI is at
[http://localhost:5000](http://localhost:5000).

## Project structure

```
FootballTrainer/
├── alembic/versions/          # 0001 initial, 0002 multi-league matches, 0003 predictions, 0004 news
├── data/                      # raw/couk CSVs, processed/features.csv and reports (git-ignored)
├── docs/                      # api_contract.md, model_experiments_2026-10-20.md
├── src/
│   ├── database.py, models.py, db_url.py
│   ├── ingestion/             # api_client, csv_history, team_names, seasons, upsert, ingest, refresh
│   ├── features/              # engine, elo, columns, build_dataset (form.py / h2h.py: original helpers, tests only)
│   ├── model/                 # train, evaluate, wrappers, baselines, scoring, artifacts/
│   ├── api/                   # main, serving, upcoming, track_record, teams, team_stats, history_cache, news, store
│   └── news/                  # feed, service, worker
├── frontend/                  # React + Vite app (components, hooks, lib, styles), nginx Dockerfile
├── tests/                     # pytest suite
├── Dockerfile, docker-compose.yml, entrypoint.sh
└── requirements.txt, .env.example
```

## Known limitations and next steps

- **Champions League** has no co.uk history; CL fixtures rely on the shared Elo
  and domestic form.
- **Draws** are almost never the most likely outcome; Premier League holdout
  log-loss (1.036) did not improve with model v2.
- **No injury, lineup or transfer data.**
- **Retraining is manual**; run the refresh, rebuild and train steps to update.
- The team picker cannot yet mark relegated teams, and a relegated side can keep a
  league rank early in a season until promoted sides have played.
- Odds stay unused by design.
