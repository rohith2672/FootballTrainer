# FootballTrainer session handoff

Last updated: 2026-10-15. Local `dev` has tickets 018-022 committed (5 commits on
top of `6172844`; not pushed). Recheck Git and source on resume.

## Resume here

- 2026-10-15 session: audit -> user chose "genuinely predictive", all 6 leagues,
  football-data.co.uk history, odds as benchmark only, CL via shared Elo, target
  "within ~0.01 log-loss of bookmaker closing odds". Plan:
  `~/.claude/plans/check-the-repo-and-serene-mango.md`. Contract: `docs/api_contract.md`.
- All five phases are implemented by subagents, reviewed, and committed one commit
  per ticket (018-022). User accepted the +0.018 gap for now (odds stay benchmark-only).
- `TEST_REPORT_2026-10-15.md` is an untracked output of a scheduled offline test run
  (not part of these tickets); review or delete it yourself.
- **Decision gate (open, user's call):** real-data holdout (2025-08-15..2026-10-12,
  2049 matches) gives selected LightGBM log-loss 0.9942 vs bookmaker (Pinnacle
  closing, proportional) 0.9764 on the same rows: gap +0.018 (target 0.01).
  Options: add odds as a feature (needs a live odds source at serve time) or
  accept the gap and rely on the honest track-record page.
- User has no football-data.org key and no running Postgres (Docker Desktop off).
  Without them `/upcoming`, `/predict`, `/teams`, `/track-record` return 503.

## What was built (committed in 018-022)

- TICKET-018 eval (`src/model/train.py`, `wrappers.py`, `baselines.py`,
  `evaluate.py`): `make_splits` = season walk-forward folds + last complete season
  (plus partial current season) as untouched holdout; selection on fold-mean
  log-loss; seeded Optuna; sigmoid calibration on disjoint slices; refit on all
  dev data; baselines uniform/class_prior/elo/bookmaker/bookmaker_shin; rich
  `model_registry.json`. CLI: `--features --artifacts-dir --n-trials --mlflow-uri`.
- TICKET-019 data (`src/ingestion/`): `csv_history.py` (co.uk download/parse, odds
  chain Pinnacle close -> avg close -> B365 close -> pre-close), `team_names.py`
  (co.uk -> football-data.org canonical; `# ?` entries unverified), `seasons.py`,
  `upsert.py` (natural key league+match_day+home+away, COALESCE merge),
  `refresh.py`, parametrised `ingest.py`. Migration `0002` (shots, odds, kickoff,
  match_day, provider_id, source, natural key).
- TICKET-020 features (`src/features/engine.py`, `elo.py`, `columns.py`):
  single point-in-time engine `compute_features(matches)` used by training AND
  serving; 37 `FEATURE_COLS` (Elo, form, venue form, shots, shrunk H2H, venue win
  rates, rest, league one-hots, season_progress). `build_dataset --from-csv
  data/raw/couk` builds without a DB.
- TICKET-021 API (`src/api/main.py`, `serving.py`, `model_store.py`, `store.py`,
  `track_record.py`): engine-based features, no silent fallback
  (`prediction_available=false` + reason), occlusion `top_factors`, `details`,
  cached concurrent upstream, `Prediction` table + migration `0003`,
  `/track-record`, real `/health`, env CORS. Missing DATABASE_URL -> 503.
- TICKET-022 UI (`frontend/`): filters/search/sort/refresh, a11y, honest
  no-prediction cards, explanation panel, hash-routed track-record page with SVG
  chart, `VITE_API_URL`, nginx.conf (`/api` proxy, SPA fallback), npm ci.

## Data and artifacts

- `data/raw/couk/` has 60 CSVs (E0, SP1, I1, D1, F1; seasons 2015-16..2026-27),
  20,060 matches (gitignored). `data/processed/features.csv` 18,234 rows after
  burn-in; `train_log.txt`, `eval_report.txt`, `shap_summary.png`,
  `mlflow_local.db` there. Tracked `mlflow.db` untouched.
- `src/model/artifacts/best_model.pkl` = LightGBM (loads in a fresh interpreter);
  registry updated. Top features: elo_diff, elo_expected_home, home_elo, h2h.
- Python 3.11 venv at `.venv` (requirements + tzdata). Frontend node_modules installed.

## Verification done (2026-10-15)

- `.venv\Scripts\python.exe -m pytest -q` -> 315 passed, 18 skipped.
- `npm run lint` clean, `npm run build` OK. UI checked by agents against stub API
  at 375-390px and 1100px.
- Real model via serving path on CSV history: sensible probabilities, Celtic
  (no history) -> "No match history". `/health` -> degraded (no DB), model loaded.

## Not verified / known gaps

- Postgres never ran: migrations 0002/0003 (only rendered offline), 18 DB tests
  (need `TEST_DATABASE_URL`), upsert/settlement SQL, `load_history`.
- No live football-data.org call: status `SCHEDULED,TIMED`, `regularTime` field,
  canonical team names (`# ?` in team_names.py), CL linking all unverified.
- Docker images not rebuilt; nginx config untested.
- Model never predicts draws by argmax (normal for 1X2); model ~= Elo baseline.
- `/track-record` resets per model_version; same-day retrains from one commit
  share a version.
- Intermediate commits were split by file/hunk and are not individually tested;
  only the final `dev` tip was verified (full suite).
