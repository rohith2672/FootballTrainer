# API contract (v2) — `/upcoming`, `/track-record`, `/health`

This is the shared contract between the FastAPI backend (`src/api/main.py`) and the
React frontend. Everything is backward compatible with v1: the existing flat
probability fields remain.

## `GET /upcoming`

Query params (all optional): `league` (PL|PD|SA|BL1|FL1|CL), `date_from`, `date_to`
(YYYY-MM-DD), `limit` (default 500).

Response: `Fixture[]`. Each item:

```json
{
  "fixture_id": 537123,
  "league": "PL",
  "home_team": "Arsenal FC",
  "away_team": "Chelsea FC",
  "date": "2026-10-18",
  "kickoff": "2026-10-18T14:00:00Z",
  "home_win": 0.48, "draw": 0.27, "away_win": 0.25,
  "prediction_available": true,
  "is_fallback": false,
  "reason": null,
  "model_version": "logistic_regression@a1b2c3d 2026-10-20",
  "top_factors": [
    {"feature": "elo_diff", "label": "Elo rating gap", "value": 112.4, "contribution": 0.21}
  ],
  "details": {
    "home": {"elo": 1712.3, "form_pts_pg": 2.2, "goals_for_avg": 2.0, "goals_against_avg": 0.8,
             "shots_for_avg": 15.2, "days_since_last": 4, "form_n": 5},
    "away": {"elo": 1640.1, "form_pts_pg": 1.4, "goals_for_avg": 1.2, "goals_against_avg": 1.4,
             "shots_for_avg": 11.0, "days_since_last": 7, "form_n": 5},
    "h2h": {"n": 12, "home_pts_rate": 0.58}
  }
}
```

- When no prediction can be made (team without history, model error), the
  response has `prediction_available: false`, all three probabilities `null`,
  `reason` set (e.g. `"No match history for Celtic FC"`), and no `top_factors`.
  `is_fallback` stays for compatibility and is `true` exactly when
  `prediction_available` is false. The API never returns made-up 0.33/0.34/0.33.
- `top_factors`: up to 5, sorted by |contribution| descending; `contribution` is
  the feature's push toward the predicted outcome in probability-ish units
  (positive = toward the predicted outcome). `label` is human readable.
- `details` values may be `null` when the data is missing (e.g. shots for CL).
- Errors: `503` with `{"detail": "..."}` when every upstream league call failed;
  partial failures return the successful leagues plus header
  `X-Partial-Failure: PD,SA`.

## `GET /track-record`

Query params: `league` (optional), `weeks` (default 26).

```json
{
  "model_version": "logistic_regression@a1b2c3d 2026-10-20",
  "n_predictions": 412,
  "n_settled": 380,
  "overall": {"log_loss": 0.982, "accuracy": 0.51, "brier": 0.58},
  "baselines": {
    "bookmaker": {"log_loss": 0.968, "n": 371},
    "class_prior": {"log_loss": 1.064, "n": 380},
    "uniform": {"log_loss": 1.0986, "n": 380}
  },
  "by_league": [
    {"league": "PL", "n": 80, "log_loss": 0.97, "accuracy": 0.53, "bookmaker_log_loss": 0.95}
  ],
  "timeline": [
    {"week_start": "2026-10-12", "n": 38, "log_loss": 1.01, "accuracy": 0.47, "bookmaker_log_loss": 0.99}
  ],
  "recent": [
    {"fixture_id": 537001, "league": "PL", "date": "2026-10-11", "home_team": "...", "away_team": "...",
     "home_win": 0.5, "draw": 0.26, "away_win": 0.24, "result": "H", "correct": true}
  ],
  "backtest": {
    "source": "model_registry.json holdout",
    "best_model": "logistic_regression",
    "holdout_window": ["2025-08-15", "2026-05-24"],
    "holdout_log_loss": 0.975, "holdout_accuracy": 0.52,
    "baselines": {"bookmaker": 0.962, "class_prior": 1.061, "uniform": 1.0986, "elo": 0.99}
  }
}
```

- Live metrics come only from predictions stored *before* kickoff and settled
  after the result is known. When there are none yet, `n_settled` is 0, metric
  fields are `null`, and `backtest` is still returned so the UI can show it.

## `GET /health`

```json
{"status": "ok", "model_loaded": true, "db": "ok", "model": "logistic_regression",
 "model_version": "...", "trained_at": "...", "version": "2.0.0"}
```

`status` is `"degraded"` (HTTP 200) when the DB is unreachable, and HTTP 503 when
no model is loaded.
