# FootballTrainer session handoff

Last updated: 2026-10-20 (evening).

## Current handoff: team analysis, favourites, UI polish and model v2 (2026-10-20)

Branch `codex`, commits `53afd06..7d55279` plus this docs commit (see
`git log --oneline 888dc66..HEAD`). Nothing pushed. Plan:
`C:/Users/rohit/.claude/plans/go-through-the-relevant-recursive-iverson.md`
(team analysis + favourites -> UI polish -> model accuracy; all three done).
Preserve the untracked `TEST_REPORT_2026-10-15.md`.

### What was built

- **News** (`53afd06`) and **bookmaker removal** (`10ae2de`): see the two
  sections below. Yardsticks are Elo, class prior and uniform; odds are never a
  model input.
- **Team analysis API** (`ca4c2a9` contract, `09bebc5` + `eafaab5`;
  `src/api/teams.py`, `team_stats.py`, `history_cache.py`): `/teams/index`,
  `/teams/{name}` (Elo, season-robust league rank, form, season home/away split,
  last-10 averages, uncapped rest days, cached `next_fixture`),
  `/teams/{name}/matches`, `/teams/{name}/elo-history` (replay of `elo.py`,
  parity-tested against the engine), `/h2h`, and a `team` filter on `/upcoming`
  and `/track-record`. History cached 300 s (with `HistoryIndex`); next-fixture
  results cached 120 s (30 s when the source is unavailable).
- **Frontend** (`06f682c`, `7815106`, `e4401d2`, `be7508b`, `713fe40`, `5b6fb1c`,
  `937275d`, `0d6cd24`, `27ce6b7`): favourites store (localStorage
  `ft.favourites.v1`, several teams + a primary) used on dashboard, cards and
  news; team page `#/team/<name>` with picker and reusable SVG `LineChart`;
  URL-hash dashboard filters; SVG icons and league badges; light/dark/system
  theme (`ft.theme.v1`); compact shell with mobile bottom tab bar; design
  tokens, AA contrast, aligned breakpoints; review and real-data fixes.
- **Model v2** (`4199a25`, `429e22d`, merged in `7d55279`): tuned adaptive Elo
  (K=14, season regression 0.05, per-league online home advantage), online
  Poisson/Dixon-Coles goals model features (7 `pois_*` columns),
  `FEATURE_COLS` 37 -> 25 (`ENGINE_COLS` still computes all 44), XGBoost
  selected after 100 Optuna trials (`--n-trials 100`; code default is 50).
  Holdout 2025-08-15..2026-10-12 (2,049 rows): log-loss 0.99424 -> 0.98835,
  accuracy 0.5188 -> 0.5212, Brier 0.5925 -> 0.5886. Walk-forward 0.98907 ->
  0.98292 (all 8 folds better). Holdout baselines in the new registry: Elo
  0.9932, Poisson 0.9916, class prior 1.0712, uniform 1.0986 (Poisson's
  walk-forward 0.9815 beats the model but is partly in-sample, because its
  constants were tuned on those folds). Per-league holdout: BL1 .9725 -> .9623,
  FL1 .9942 -> .9944, PD .9828 -> .9685, PL 1.0356 -> 1.0356, SA .9821 -> .9776.
  Rejected: draw features, HT/corners/fouls/cards (migration 0005 never
  written), EWMA form, congestion, league one-hots. The model still never
  argmax-predicts a draw. Elo values shown in the UI shifted (Arsenal
  1680.3 -> 1746.2). Details: `docs/model_experiments_2026-10-20.md`.
- Artifacts (gitignored) are installed in `src/model/artifacts`; the committed
  `model_registry.json` matches them and no longer has `bookmaker*` keys.
  `data/processed/features.csv` rebuilt (18,234 rows).

### Verification actually run

- pytest at the tip: 437 passed, 23 skipped (no PG). With a disposable
  PostgreSQL 18 cluster at `937275d`: 432 passed, 0 skipped; migrations
  0001 -> 0004; ingest of 20,060 rows, idempotent on re-run.
- Real API + Vite browser checks at 375 and 1100 px, light and dark, on real
  data (before the model merge).
- Frontend: 109 Node tests, lint and build clean.
- Serving smoke with the new model: Arsenal v Chelsea 0.618/0.241/0.140.
- 2026-10-20 post-merge (9a7a400): PG 18 suite 460 passed/0 skipped; real API+UI on model v2 at 375/1100 light/dark OK (poisson baseline label fixed afterwards).

### Not verified

- `next_fixture` / match prep against a real fixture (no
  `FOOTBALL_DATA_API_KEY`); live track record with settled predictions; a real
  news-worker run this session; CL history (not in co.uk data, so CL sides only
  get the shared Elo); Docker/nginx rebuild; screen reader; touch gestures on
  charts. The UI was not re-checked in a browser after the model merge.

### Known issues and follow-ups

- `docs/api_contract.md` "Team analysis" still describes the old Elo (K=20,
  25 % season regression, fixed home advantage 60). Code is K=14, 0.05,
  per-league online home advantage. Update the contract.
- Team picker cannot tag relegated teams; needs a backend `current` flag in
  `/teams/index`. Relegated sides may keep a rank early in a season until
  promoted sides have played.
- Draws are never the argmax; PL holdout did not improve (1.0356).
- Model-v2 scratch material is in the session temp scratchpad and is **not
  durable**: `.../scratchpad/backup_pre_model_merge/` (previous artifacts and
  features.csv), `.../scratchpad/phase3/experimental_full.patch` (HT/corners/
  fouls/cards capture, if ever wanted) and `.../scratchpad/phase3/settings_local.patch`
  (a local `.claude/settings.local.json` edit set aside from the model
  worktree; the user should review it). Full prefix:
  `C:/Users/rohit/AppData/Local/Temp/claude/C--Users-rohit-OneDrive-Desktop-projects-FootballTrainer/da08ef47-dca2-4645-bc26-70753728fcf8/scratchpad/`.

## Previous handoff: bookmaker comparison removed (2026-10-20)

- Branch `codex`. News work committed as `53afd06` (`feat(news): ...`); this
  change is the follow-up commit `refactor: remove bookmaker comparison from
  evaluation, API and UI`. Nothing pushed.
- Verification run 2026-10-20 (no Postgres running): pytest 344 passed,
  23 skipped (all PG tests needing `TEST_DATABASE_URL`); frontend 9 Node tests
  passed, lint clean, build OK. Browser not re-checked after the UI change.
- User decision: the bookmaker / market comparison is gone from evaluation, API
  and UI. Removed the `bookmaker` and `bookmaker_shin` baselines (and Shin /
  proportional de-margining helpers), live bookmaker log-loss and per-league /
  per-week `bookmaker_log_loss` in `/track-record`, odds in `store.fetch_settled`,
  and the bookmaker tile, columns, gap and chart series in the UI.
- Retired: the "within ~0.01 log-loss of bookmaker closing odds" target, the
  related decision gate below, and the "matched-row bookmaker comparisons"
  follow-up. Yardsticks are now Elo (backtest), class prior and uniform, plus
  walk-forward / holdout improvements.
- Odds DB columns, migrations, co.uk odds parsing and `build_dataset` odds
  columns are kept but unused. Odds must never become a model input.
- The committed `model_registry.json` still has legacy `bookmaker*` baseline
  keys (no retrain done); `track_record.backtest_block` filters them at read time.
  *(Superseded: the model-v2 registry has no bookmaker keys; the filter is now a no-op.)*
- This is the start of the plan at
  `C:/Users/rohit/.claude/plans/go-through-the-relevant-recursive-iverson.md`:
  team analysis + favourite teams -> UI polish -> model accuracy.

## Previous handoff: hourly news on `codex` (2026-10-16)

- Actual repository: `C:/Users/rohit/OneDrive/Desktop/projects/FootballTrainer`.
  The saved Codex project path without `projects/` is obsolete.
- Created the user-requested branch `codex` from `dev` at `888dc66`.
  News implementation and documentation are uncommitted; no push requested.
  Preserve the pre-existing untracked `TEST_REPORT_2026-10-15.md`.
- Three subagents implemented backend/frontend and independently verified news.
  Added BBC Sport football RSS metadata ingestion, migration `0004`, `/news`,
  and a separate Compose `news-worker`. Hourly checks persist their schedule and
  use a PostgreSQL session advisory lock held across commits. Retries are bounded;
  ETag/Last-Modified conditional requests are supported when supplied upstream.
- The News tab (`#/news`) shows safe attributed headline links, publication age,
  attempt/success timestamps and stale/unavailable/empty states. It reads cache
  every five minutes while visible and on manual refresh. Local and server cache
  expires at 24 hours; source staleness begins after 90 minutes. No article bodies,
  model features, team matching, or paid news integration were added.
- Fixed default PostgreSQL URL driver selection for SQLAlchemy via
  `src/db_url.py`, used by application, migrations and isolated PG tests.
  Existing `tests/test_db.py` now uses isolated test schemas rather than app DB.
- Verification actually run: full pytest **370 passed**, including real isolated
  PostgreSQL tests (no skips). Frontend **9 Node tests passed**, lint/build passed.
  Chrome smoke at 375px and 1100px checked keyboard refresh, states, navigation,
  overflow and console errors. Root inspected the mobile screenshot.
- Real migrations tested on a disposable PostgreSQL 18 cluster:
  base -> 0004 -> 0003 -> 0004, including final provider ID column. Cross-connection
  locks, persisted scheduling, duplicates, 304, failed refresh and expiry tested.
- Ran the actual worker against that isolated database with no browser open:
  76 live BBC headlines fetched. Integrated FastAPI `/news?limit=50` returned
  50 articles and `ok` with the model deliberately unavailable; invalid limit 101
  returned 422. No real model artifacts, application DB or user PG service changed.
- Temporary worker, Vite preview, browser, and isolated PG cluster are stopped.
  Temporary PG files/logs remain under TEMP; this is not a running deployment.
- Compose config validated with `--env-file .env.example --no-env-resolution`.
  Docker images/full stack not run (Docker daemon not active; `.env` missing).
  Configure `.env` then use the README startup command for continuous operation.
- Prediction improvements remain separately evaluated follow-ups: PL slice metrics
  and matched-row bookmaker comparisons (retired 2026-10-20), PL-specialist experiment, richer form /
  shot freshness, football parameter tuning, and a match preparation page.
  This news task makes no claim of improved prediction accuracy.

## Previous handoff (2026-10-15; historical context)

> Superseded on 2026-10-20: 37 features -> 25, LightGBM -> XGBoost as the served
> model, the bookmaker decision gate and baselines retired, and Postgres has
> since been exercised (disposable PG 18 at `937275d`). Numbers below are as of
> 2026-10-15.

Local `dev` had tickets 018-022 committed (5 commits on
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
- **Decision gate (retired 2026-10-20, bookmaker comparison removed):** real-data holdout (2025-08-15..2026-10-12,
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
  serving; 37 `FEATURE_COLS` (now 25, see current handoff) (Elo, form, venue form, shots, shrunk H2H, venue win
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
- `src/model/artifacts/best_model.pkl` = LightGBM (now XGBoost, model v2) (loads in a fresh interpreter);
  registry updated. Top features: elo_diff, elo_expected_home, home_elo, h2h.
- Python 3.11 venv at `.venv` (requirements + tzdata). Frontend node_modules installed.

## Verification done (2026-10-15)

- `.venv\Scripts\python.exe -m pytest -q` -> 315 passed, 18 skipped.
- `npm run lint` clean, `npm run build` OK. UI checked by agents against stub API
  at 375-390px and 1100px.
- Real model via serving path on CSV history: sensible probabilities, Celtic
  (no history) -> "No match history". `/health` -> degraded (no DB), model loaded.

## Not verified / known gaps

- Postgres never ran (since run at `937275d`, 2026-10-20): migrations 0002/0003 (only rendered offline), 18 DB tests
  (need `TEST_DATABASE_URL`), upsert/settlement SQL, `load_history`.
- No live football-data.org call: status `SCHEDULED,TIMED`, `regularTime` field,
  canonical team names (`# ?` in team_names.py), CL linking all unverified.
- Docker images not rebuilt; nginx config untested.
- Model never predicts draws by argmax (normal for 1X2); model ~= Elo baseline.
- `/track-record` resets per model_version; same-day retrains from one commit
  share a version.
- Intermediate commits were split by file/hunk and are not individually tested;
  only the final `dev` tip was verified (full suite).
