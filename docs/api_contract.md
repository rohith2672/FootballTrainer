# API contract (v2) — `/upcoming`, `/track-record`, `/health`

## `GET /news` (added 2026-10-16)

Read-only cache endpoint, independent of the prediction model and fixture API
key. Query `limit` defaults to 50, with bounds 1–100 (invalid values return 422).
Articles are newest first, undated entries last. This request never fetches the
publisher feed; a separate worker checks hourly.

```json
{
  "articles": [
    {"id": "stable-source-id-hash", "title": "Football headline",
     "url": "https://www.bbc.com/sport/football/articles/example",
     "publisher": "BBC Sport", "published_at": "2026-10-16T10:00:00Z",
     "fetched_at": "2026-10-16T10:30:00Z"}
  ],
  "last_attempt_at": "2026-10-16T10:30:00Z",
  "last_success_at": "2026-10-16T10:30:00Z",
  "next_check_at": "2026-10-16T11:30:00Z",
  "status": "ok",
  "stale": false
}
```

- Timestamps are UTC ISO 8601 strings; publication/check times can be null
  when not known. `fetched_at` includes successful conditional revalidation.
- `status` is `ok` after a successful check within 90 minutes, `stale` after
  90 minutes, and `unavailable` if never successfully checked or expired at
  24 hours. `stale` is true for either non-ok state.
- A successfully fetched empty feed returns `articles: []`, `status: "ok"`.
  Expired cache returns no articles. An HTTP 304 advances successful-check time.
- A missing/unreachable database returns 503 with `detail: "News storage unavailable"`.
- Only headline metadata and links are returned. Provider failures preserve
  the unexpired snapshot; the UI must not retain an expired snapshot on errors.

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
  `details.*.days_since_last` is the model input and is capped at 30
  (`REST_CAP_DAYS`): show `30` as "30+". The team profile's `rest_days` is uncapped.
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
    "class_prior": {"log_loss": 1.064, "n": 380},
    "uniform": {"log_loss": 1.0986, "n": 380}
  },
  "by_league": [
    {"league": "PL", "n": 80, "log_loss": 0.97, "accuracy": 0.53}
  ],
  "timeline": [
    {"week_start": "2026-10-12", "n": 38, "log_loss": 1.01, "accuracy": 0.47}
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
    "baselines": {"class_prior": 1.061, "uniform": 1.0986, "elo": 0.99}
  }
}
```

- Yardsticks are class prior and uniform (live) plus Elo (backtest). Betting
  odds are not a model input and there is no market comparison (user decision,
  2026-10-20); legacy registry baselines of that kind are dropped when the
  backtest block is read.

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

## Team analysis (added 2026-10-20)

Read-only endpoints over finished matches. They need only the database: no model
and no fixture API key (except `next_fixture`, see below). Common rules:

- **Known team** = a name in the `teams` table or in finished-match history
  (CL-only sides may exist only in history). Names are exact canonical names,
  case-sensitive; clients must `encodeURIComponent` them in paths and queries
  (names contain spaces, `&`, `.`). Unknown name → `404 {"detail": "Team not found: <name>"}`.
- DB missing/unreachable → `503 {"detail": "..."}`. Bad params → `422`
  (dates must be `YYYY-MM-DD`; out-of-range ints use FastAPI's 422).
- Dates are UTC calendar days (`match_day`), `YYYY-MM-DD`. `season` is the
  season start year. Elo values are rounded to 1 decimal, rates/averages to 3.
- **Elo** is computed by replaying `src/features/elo.py` over full history
  exactly as the feature engine does (all competitions incl. CL share one
  rating; K=20, home advantage 60, goal-difference multiplier, 25% regression to
  the league mean at a team's first match of a new season, results applied
  per day). Ratings are therefore identical to those the model sees.
  Consequences: a team's first-match-of-season `elo_before` differs from the
  previous match's `elo_after` (season regression); the profile's
  `elo.rating` is the post-last-match value and can differ from `/upcoming`
  `details.*.elo`, which includes pending regression.
- Route order: `/teams/index` is declared before `/teams/{name}`, so `index` is
  a reserved name.

### `GET /teams/index`

All known teams, sorted by league then name (null league last). `GET /teams`
is unchanged (flat, alphabetically sorted `str[]`).

```json
[{"name": "Arsenal FC", "league": "PL"}, {"name": "Celtic FC", "league": null}]
```

`league` is the team's latest domestic league (`teams.league` when it is a
domestic code, else the league of its latest domestic match in history);
`null` when the team only has CL matches (CL-only rows in `teams` carry
`league = "CL"`, which is reported as `null`).

### `GET /teams/{name}`

Query `as_of` (optional, YYYY-MM-DD): use only matches with match day strictly
before it. Default: all finished matches (all are before "now").

```json
{
  "name": "Arsenal FC",
  "league": "PL",
  "as_of": null,
  "elo": {"rating": 1712.3, "rank_in_league": 2, "league_size": 20, "change_last_5": 14.6},
  "form": {"last5": "WDLWW", "pts_pg": 2.0, "n": 5},
  "season": {
    "season": 2026, "played": 8, "w": 5, "d": 2, "l": 1, "gf": 16, "ga": 6, "pts": 17,
    "home": {"played": 4, "w": 3, "d": 1, "l": 0, "gf": 10, "ga": 2},
    "away": {"played": 4, "w": 2, "d": 1, "l": 1, "gf": 6, "ga": 4}
  },
  "averages": {
    "n": 10, "n_shots": 8,
    "goals_for": 1.9, "goals_against": 0.8, "shots_for": 15.2, "shots_against": 9.1,
    "sot_for": 5.6, "sot_against": 3.0,
    "clean_sheet_rate": 0.4, "btts_rate": 0.4, "over25_rate": 0.5
  },
  "rest_days": 4,
  "last_match_date": "2026-10-16",
  "next_fixture": null,
  "next_fixture_status": "unavailable"
}
```

- `elo.rating`: rating after the team's last match. `rank_in_league` /
  `league_size`: rank (1 = highest) by current rating (post-last-match Elo)
  within the league's pool, restricted to teams whose latest domestic league is
  `league`. Pool = every team that played the league's most recent season in
  history, plus — while that roster is smaller than the reference roster (the
  most recent earlier season with at least `elo.MIN_TABLE_TEAMS` = 8 teams) —
  reference-season teams that have not played yet, best previous-table
  position first, up to the reference roster size (early season, postponed
  openers keep a rank; the worst unplayed sides drop out as promoted teams
  appear). Without a reference season the pool is the most recent season's
  roster. Both `null` when `league` is null; `rank_in_league` alone is `null`
  when the team is not in the pool. `change_last_5` = `elo_after` of the latest
  match − `elo_before` of the 5th latest (fewer if fewer matches); `null` with
  no matches.
- `form` and `averages` span all competitions (as the engine's form does).
  `form.last5` is newest-last, chars `W`/`D`/`L`, up to 5 chars; `pts_pg` is
  `null` and `last5` `""` when `n` is 0.
- `averages` cover the last 10 matches (`n` ≤ 10). Shot fields use only the
  `n_shots` of those matches that have shot data (CL rows lack shots) and are
  `null` when `n_shots` is 0; every average/rate is `null` when `n` is 0.
  `btts_rate` = both scored; `over25_rate` = total goals ≥ 3.
- `season` is domestic league only (CL excluded), for the season of the team's
  latest domestic match; `null` for CL-only teams.
- `rest_days`: days from `last_match_date` to today (or to `as_of`), true
  value, never capped; both `null` without matches.
- `next_fixture`: the team's next `/upcoming` item (same `Fixture` shape incl.
  probabilities, `top_factors`, `details`), from its domestic league and CL.
  `next_fixture_status`: `"ok"` (fixture present), `"none"` (source reachable,
  no fixture scheduled), `"unavailable"` (API key missing, any needed league
  request failed, model not loaded, or `as_of` given — then `next_fixture` is
  always null). These conditions never fail the profile, and the profile does
  not store the prediction (unlike `/upcoming`). Results are cached in process
  per team: `ok`/`none` for 120 s, `unavailable` (upstream/pipeline failure) for
  30 s; cleared with the history cache. Matching relies on upstream names
  equalling canonical DB names, as in `/upcoming`.

### `GET /teams/{name}/matches`

Query `limit` (default 20, 1–100), `venue` (`all`|`home`|`away`, default `all`;
other values → 422). Newest first; all competitions.

```json
[
  {"date": "2026-10-16", "league": "PL", "season": 2026, "venue": "home",
   "opponent": "Chelsea FC", "gf": 2, "ga": 1, "result": "W",
   "shots_for": 14, "shots_against": 9, "sot_for": 6, "sot_against": 3,
   "elo_before": 1705.1, "elo_after": 1712.3}
]
```

Shot fields are `null` when missing. `result` is from the team's perspective.
No matches → `[]`.

### `GET /teams/{name}/elo-history`

Query `since` (optional, YYYY-MM-DD; default today − 365 days). One point per
finished match on/after `since`, post-match rating, ascending by date.

```json
{"team": "Arsenal FC",
 "points": [{"date": "2026-10-16", "elo": 1712.3, "opponent": "Chelsea FC", "result": "W"}]}
```

No matches in the window → `points: []`.

### `GET /h2h`

Query `a`, `b` (required; missing → 422), `limit` (default 10, 1–100). Both
must be known teams (404 otherwise); `a == b` → `422 {"detail": "a and b must differ"}`.

```json
{"a": "Arsenal FC", "b": "Chelsea FC", "n": 21,
 "a_wins": 9, "draws": 6, "b_wins": 6, "a_goals": 31, "b_goals": 24,
 "meetings": [{"date": "2026-10-16", "league": "PL", "home_team": "Arsenal FC",
               "away_team": "Chelsea FC", "home_goals": 2, "away_goals": 1}]}
```

Totals (`n`, wins, draws, goals) cover **all** finished meetings in history, any
venue and competition; `meetings` is the newest `limit` of them, newest first.
No meetings → `n: 0`, counts 0, `meetings: []`.

### `team` filter on `/upcoming` and `/track-record`

- `GET /upcoming?team=<name>`: only fixtures where `home_team` or `away_team`
  equals `team`. Applied before `limit`. Combines with `league` and dates.
- `GET /track-record?team=<name>`: only stored predictions where home or away
  equals `team`; `n_predictions`, `n_settled`, `overall`, `by_league`,
  `timeline` and `recent` are all filtered. `backtest` is unchanged, and the
  live `class_prior` baseline keeps its league/global class counts (scored on
  the filtered rows). The response gains `"team": "<name>"` (`null` when not
  filtered).
- On filters an unknown name is not an error: it yields `[]` / `n_settled: 0`
  (fixture names can exist without history).

### Caching

Finished-match history is cached in-process with a short TTL (300 s) and shared
by `/upcoming`, the team endpoints and `/h2h`; the derived Elo replay is cached
with it and rebuilt when it expires. Newly ingested results appear within one
TTL. Upstream fixtures keep their existing `api_client` cache.

### Client-side favourites

Favourite teams live only in browser `localStorage` under `ft.favourites.v1`:
`{"teams": ["Arsenal FC"], "primary": "Arsenal FC"}` (`primary`: `str|null`,
one of `teams`). There is no server endpoint; reads/writes must tolerate a
missing or throwing storage.
