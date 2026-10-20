# Football Match Outcome Predictor

## Hourly football news (2026-10-16)

The **News** dashboard tab shows BBC Sport football headline links, publication
times, and server refresh status. The worker checks the feed every hour even
when the browser is closed. The page reads cached headlines every five minutes
while visible; its Refresh button also reads the cache. New stories depend on
publisher activity. The computer/server and worker must remain running.

If `.env` is missing, copy `.env.example` to `.env` and configure your database
settings privately. With `.env` configured, run:

```sh
docker compose up --build -d db app news-worker frontend
```

The app applies migrations, including the additive `0004` news tables. The news
worker retries while the database schema starts up. No news API key is needed;
the football-data.org key and trained model are needed for predictions, not news.
For local development with PostgreSQL and the project environment active:

```sh
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m src.news.worker
```

Run `python -m uvicorn src.api.main:app --reload` and the frontend in separate
terminals. `GET /news?limit=50` returns cached headline metadata and source check
times. News is marked delayed after 90 minutes without a successful check;
cached headlines expire after 24 hours. An empty successful feed is distinguished
from an unavailable source. Browser refresh times are not source freshness.

This personal-use feature links to the publisher; it stores no article bodies
and supplies no news-derived ML features. The current implementation uses the
[BBC football RSS feed](https://feeds.bbci.co.uk/sport/football/rss.xml), following
[BBC RSS guidance](https://www.bbc.co.uk/sport/articles/cqllxj2n4kyo).

For tests, use `TEST_DATABASE_URL` pointing to a disposable PostgreSQL database.
Database tests create isolated schemas and never use the application database.
Both ordinary `postgresql://` URLs and explicit `postgresql+psycopg2://` URLs
select the installed psycopg2 driver for application and migration connections.

The sections below include historical setup/model descriptions. See `MEMORY.md`
and `docs/api_contract.md` for the current model and API context.

An end-to-end ML pipeline that predicts Premier League match outcomes (Home Win / Draw / Away Win) using historical match data, feature engineering, and an XGBoost classifier served via FastAPI.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Pipeline                            │
│                                                                 │
│  football-data.org API                                          │
│         │                                                       │
│         ▼                                                       │
│  src/ingestion/api_client.py  ──►  src/ingestion/ingest.py      │
│         │                               │                       │
│         │                               ▼                       │
│         │                        PostgreSQL DB                  │
│         │                               │                       │
│         │              ┌────────────────┤                       │
│         │              ▼                ▼                       │
│         │       src/features/     src/features/                 │
│         │          form.py           h2h.py                     │
│         │              │                │                       │
│         │              └───────┬────────┘                       │
│         │                      ▼                                │
│         │         src/features/build_dataset.py                 │
│         │                      │                                │
│         │                      ▼                                │
│         │              data/processed/features.csv              │
│         │                      │                                │
└─────────┼──────────────────────┼─────────────────────────────┘
          │                      │
┌─────────┼──────────────────────▼─────────────────────────────┐
│         │              Modelling Pipeline                      │
│         │                                                      │
│         │       src/model/train.py                            │
│         │       ├── LogisticRegression (baseline)             │
│         │       └── XGBoost + Optuna (50 trials)              │
│         │               │                                     │
│         │               ├──► MLflow Tracking (port 5000)      │
│         │               └──► src/model/artifacts/xgb_best.pkl │
│         │                         │                           │
│         │       src/model/evaluate.py                         │
│         │       ├── SHAP summary plot                         │
│         │       └── eval_report.txt                           │
│         │                                                      │
└─────────┼──────────────────────────────────────────────────────┘
          │
┌─────────▼──────────────────────────────────────────────────────┐
│                      API Layer                                  │
│                                                                 │
│         src/api/main.py  (FastAPI, port 8000)                  │
│         ├── POST /predict                                       │
│         ├── GET  /upcoming                                      │
│         ├── GET  /health                                        │
│         └── GET  /teams                                         │
│                                                                 │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼──────────────────────────────────────┐
│                    Frontend UI (Port 3000)                     │
│                                                                │
│        React / Vite application with premium styling          │
│        Displays upcoming match predictions dynamically         │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Python 3.11
- Docker and Docker Compose
- PostgreSQL 15 (only needed for local runs without Docker)
- A free API key from [football-data.org](https://www.football-data.org/)

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd FootballTrainer
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```
DATABASE_URL=postgresql://user:password@localhost:5432/football_predictor
FOOTBALL_DATA_API_KEY=your_api_key_here
MLFLOW_TRACKING_URI=http://localhost:5000
```

### 3. Start all services with Docker

```bash
docker-compose up --build
```

This starts four services:

| Service | Port | Description |
|---------|------|-------------|
| `frontend`| 3000 | React Vite UI Dashboard |
| `app`   | 8000 | FastAPI prediction server |
| `db`    | 5432 | PostgreSQL 15 database |
| `mlflow`| 5000 | MLflow tracking UI |

The `app` container automatically runs Alembic migrations and starts the API server on startup.

Verify everything is running:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "ok", "model": "xgb_best", "version": "1.0.0"}
```

## Running Each Stage Manually

For local development outside Docker, activate the virtual environment first:

```bash
# Windows
venv\Scripts\Activate.ps1

# macOS / Linux
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run Alembic migrations:

```bash
alembic upgrade head
```

### 1. Ingest match data

Pulls 3 seasons (2021–2023) of Premier League matches from the API and stores them in PostgreSQL. Safe to re-run — duplicates are skipped.

```bash
python -m src.ingestion.ingest
```

### 2. Build the feature dataset

Computes rolling form, head-to-head, and home/away split features, then saves the master table to `data/processed/features.csv`.

```bash
python -m src.features.build_dataset
```

### 3. Train models

Trains a Logistic Regression baseline and an XGBoost model with 50 Optuna trials. Logs all metrics to MLflow and saves the best model to `src/model/artifacts/xgb_best.pkl`.

```bash
python -m src.model.train
```

### 4. Evaluate and generate reports

Loads the best XGBoost model, computes SHAP values, and writes `data/processed/shap_summary.png` and `data/processed/eval_report.txt`.

```bash
python -m src.model.evaluate
```

## Making Predictions

### Example `curl` request

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"home_team": "Arsenal FC", "away_team": "Chelsea FC", "date": "2024-03-15"}'
```

Expected response:

```json
{
  "home_win": 0.482,
  "draw": 0.271,
  "away_win": 0.247
}
```

Probabilities always sum to approximately 1.0. The endpoint returns HTTP 422 if a team name is not found in the database or if the date format is invalid.

### List available teams

```bash
curl http://localhost:8000/teams
```

## MLflow UI

Open the MLflow tracking UI at [http://localhost:5000](http://localhost:5000) to compare experiments, view logged parameters, and inspect metrics for each training run.

The experiment is named `football-predictor`. Each run logs:

- `accuracy`, `log_loss` — evaluation metrics
- `n_estimators`, `max_depth`, `learning_rate`, `subsample` — XGBoost hyperparameters
- Model artifact (`xgb_best.pkl`)

## Project Structure

```
FootballTrainer/
├── data/
│   ├── raw/                        # Raw API responses (git-ignored)
│   └── processed/                  # features.csv, shap_summary.png, eval_report.txt
├── notebooks/
│   └── eda.ipynb
├── src/
│   ├── database.py                 # SQLAlchemy engine + session factory
│   ├── models.py                   # Match and Team ORM models
│   ├── ingestion/
│   │   ├── api_client.py           # football-data.org API client with rate limiting
│   │   └── ingest.py               # Fetch and upsert matches to PostgreSQL
│   ├── features/
│   │   ├── form.py                 # Rolling form features (last 5 matches)
│   │   ├── h2h.py                  # H2H, home/away win rate, fatigue features
│   │   └── build_dataset.py        # Join all features → features.csv
│   ├── model/
│   │   ├── train.py                # Baseline + XGBoost training with Optuna + MLflow
│   │   ├── evaluate.py             # SHAP analysis and evaluation report
│   │   └── artifacts/              # Saved model pickles
│   └── api/
│       └── main.py                 # FastAPI app (predict, health, teams, upcoming endpoints)
├── frontend/                       # React / Vite Frontend Application
│   ├── src/
│   │   ├── components/             # MatchCard and Dashboard components
│   │   ├── App.jsx                 # Main application component
│   │   └── index.css               # Premium dark-mode UI styling
│   ├── Dockerfile                  # Multi-stage build for frontend
│   └── package.json
├── tests/                          # pytest test suite
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh                   # Runs migrations then starts uvicorn
├── .env.example
├── requirements.txt
└── README.md
```

## Known Limitations and Next Steps

- **Data coverage**: Only Premier League (PL) seasons 2021–2023. Adding more leagues (La Liga, Bundesliga) and more seasons would improve model robustness.
- **No Elo ratings**: Team strength is captured only via recent form. Adding Elo or FIFA ratings as features could significantly improve accuracy.
- **No betting odds feature**: Market odds encode crowd wisdom and injury news. Integrating them as a feature is a known performance booster.
- **No injury / lineup data**: Squad availability is a strong predictor but is not currently modelled.
- **Static model**: The model is trained once offline. A scheduled retraining pipeline (e.g., weekly) would keep predictions fresh as the season progresses.
- **Single-label target**: The model predicts match outcome only. Extending to scoreline or goal totals would require additional modelling work.
