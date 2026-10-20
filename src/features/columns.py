"""Single source of truth for the feature columns and the model feature order.

Dependency-free on purpose (no pandas / SQLAlchemy) so training, evaluation and
the API can import it cheaply.

* ``ENGINE_COLS``: every column ``src.features.engine.compute_features`` can
  produce (pass ``columns=`` to get any of them).
* ``FEATURE_COLS``: the model's inputs, in order. ``compute_features`` returns
  exactly these by default and ``src.model.train`` re-exports it. The trained
  model's registry stores this list; the API refuses a model whose list differs.
"""

LEAGUES = ["PL", "PD", "SA", "BL1", "FL1", "CL"]

ELO_COLS = ["home_elo", "away_elo", "elo_diff", "elo_expected_home"]

# Online Poisson / Dixon-Coles goals model (src/features/engine.py).
POISSON_COLS = [
    "pois_lambda_home",
    "pois_lambda_away",
    "pois_p_home",
    "pois_p_draw",
    "pois_p_away",
    "pois_logit_home",   # log(p_home / p_draw)
    "pois_logit_away",   # log(p_away / p_draw)
]

FORM_COLS = [
    "home_form_pts_pg",
    "home_form_goals_scored_avg",
    "home_form_goals_conceded_avg",
    "away_form_pts_pg",
    "away_form_goals_scored_avg",
    "away_form_goals_conceded_avg",
    "home_form_n",
    "away_form_n",
    "home_venue_form_pts_pg",   # home team, last 5 HOME games
    "away_venue_form_pts_pg",   # away team, last 5 AWAY games
]

SHOTS_COLS = [
    "home_shots_for_avg",
    "home_shots_against_avg",
    "home_sot_for_avg",
    "home_sot_against_avg",
    "away_shots_for_avg",
    "away_shots_against_avg",
    "away_sot_for_avg",
    "away_sot_against_avg",
]

H2H_COLS = ["h2h_home_pts_rate", "h2h_n"]

SEASON_VENUE_COLS = [
    "home_team_home_win_rate",
    "away_team_away_win_rate",
    "home_home_games_n",
    "away_away_games_n",
]

REST_COLS = ["home_days_since_last", "away_days_since_last"]

CONTEXT_COLS = [f"league_{lg}" for lg in LEAGUES] + ["season_progress"]

ENGINE_COLS = (
    ELO_COLS + POISSON_COLS + FORM_COLS + SHOTS_COLS + H2H_COLS + SEASON_VENUE_COLS
    + REST_COLS + CONTEXT_COLS
)

# Model inputs (selected on walk-forward log-loss, docs/model_experiments_2026-10-20.md).
# The columns the API reads for match details / availability checks
# (src/api/serving.py) are all included.
FEATURE_COLS = ELO_COLS + POISSON_COLS + [
    "home_form_pts_pg",
    "away_form_pts_pg",
    "home_form_goals_scored_avg",
    "home_form_goals_conceded_avg",
    "away_form_goals_scored_avg",
    "away_form_goals_conceded_avg",
    "home_shots_for_avg",
    "away_shots_for_avg",
    "home_days_since_last",
    "away_days_since_last",
    "home_form_n",
    "away_form_n",
    "h2h_n",
    "h2h_home_pts_rate",
]

assert len(set(ENGINE_COLS)) == len(ENGINE_COLS), "duplicate engine column"
assert len(set(FEATURE_COLS)) == len(FEATURE_COLS), "duplicate feature column"
assert set(FEATURE_COLS) <= set(ENGINE_COLS), "feature column the engine does not compute"


# Human-readable labels for every engine column.
ENGINE_LABELS = {
    "home_elo": "Home team Elo rating",
    "away_elo": "Away team Elo rating",
    "elo_diff": "Elo rating gap (incl. home advantage)",
    "elo_expected_home": "Elo-expected home score",
    "pois_lambda_home": "Expected home goals (goals model)",
    "pois_lambda_away": "Expected away goals (goals model)",
    "pois_p_home": "Goals-model home win probability",
    "pois_p_draw": "Goals-model draw probability",
    "pois_p_away": "Goals-model away win probability",
    "pois_logit_home": "Goals-model home win vs draw odds",
    "pois_logit_away": "Goals-model away win vs draw odds",
    "home_form_pts_pg": "Home team recent form (points per game)",
    "home_form_goals_scored_avg": "Home team goals scored (last 5)",
    "home_form_goals_conceded_avg": "Home team goals conceded (last 5)",
    "away_form_pts_pg": "Away team recent form (points per game)",
    "away_form_goals_scored_avg": "Away team goals scored (last 5)",
    "away_form_goals_conceded_avg": "Away team goals conceded (last 5)",
    "home_form_n": "Home team matches in form window",
    "away_form_n": "Away team matches in form window",
    "home_venue_form_pts_pg": "Home team form at home (points per game)",
    "away_venue_form_pts_pg": "Away team form away (points per game)",
    "home_shots_for_avg": "Home team shots taken (last 5)",
    "home_shots_against_avg": "Home team shots faced (last 5)",
    "home_sot_for_avg": "Home team shots on target (last 5)",
    "home_sot_against_avg": "Home team shots on target faced (last 5)",
    "away_shots_for_avg": "Away team shots taken (last 5)",
    "away_shots_against_avg": "Away team shots faced (last 5)",
    "away_sot_for_avg": "Away team shots on target (last 5)",
    "away_sot_against_avg": "Away team shots on target faced (last 5)",
    "h2h_home_pts_rate": "Head-to-head record (home side)",
    "h2h_n": "Number of previous meetings",
    "home_team_home_win_rate": "Home team home win rate this season",
    "away_team_away_win_rate": "Away team away win rate this season",
    "home_home_games_n": "Home team home games this season",
    "away_away_games_n": "Away team away games this season",
    "home_days_since_last": "Home team rest days",
    "away_days_since_last": "Away team rest days",
    "league_PL": "Premier League context",
    "league_PD": "La Liga context",
    "league_SA": "Serie A context",
    "league_BL1": "Bundesliga context",
    "league_FL1": "Ligue 1 context",
    "league_CL": "Champions League context",
    "season_progress": "Point in the season",
}

# Labels used by the API's "top factors" explanation: exactly FEATURE_COLS (the
# test suite checks the coverage; no import-time assert on purpose: this module
# is imported by training).
FEATURE_LABELS = {name: ENGINE_LABELS[name] for name in FEATURE_COLS if name in ENGINE_LABELS}
