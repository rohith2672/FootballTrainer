# Model experiments, 2026-10-20

Branch `worktree-agent-a85c28054c5498e53` (cut from `codex` at `ca4c2a9`).
Data: 60 football-data.co.uk CSVs (E0/SP1/I1/D1/F1, 2015-16..2026-27), 18,234
rows after the one-season burn-in. Odds are never a model input.

## Protocol

- Same split as production (`train.make_splits`): 8 season walk-forward folds
  (validation seasons 2017..2024) and an untouched holdout (2025-08-15..2026-10-12,
  2,049 matches, includes the partial 2026-27 season).
- Screening used fixed model parameters (the baseline's tuned LightGBM/XGBoost
  parameters plus the plain logistic regression), so differences come from the
  features, not from re-tuning. Each change was judged on mean walk-forward
  log-loss. A change was kept only if it improved the mean by more than 0.002,
  improved most folds and made no league worse by more than 0.003.
- The holdout was looked at only for the baseline and the final candidates
  (A, B and the final run).
- Elo and Poisson-model constants were chosen with about 250 configurations on
  the same 8 dev folds. Their walk-forward numbers are therefore partly
  in-sample for those choices. Only the holdout is a clean estimate.

## Baseline (reproduced)

`python -m src.features.build_dataset --from-csv ...` and then `src.model.train`
with 25 trials reproduced the committed registry exactly. LightGBM was selected
with walk-forward 0.98907 and holdout 0.99424 (accuracy 0.5188). The holdout
confusion matrix was `[[712,1,192],[320,0,201],[272,0,351]]`. The Elo baseline
scored 0.99227 walk-forward and 0.99784 on the holdout. Features matched the
main checkout's `features.csv` to within 7e-13.

## Screening results (walk-forward mean log-loss, fixed parameters)

| # | Experiment | LR | LightGBM | Δ LightGBM vs ref | Folds better | Decision |
|---|---|---|---|---|---|---|
| 0 | Baseline, 37 features, old Elo | 0.99345 | 0.98907 | – | – | reference |
| 1 | Elo tuning (Elo-only LR proxy 0.99227 → 0.98874) | 0.99337 | 0.98675 | −0.00232 | 7/8 | **kept** |
| 2a | + draw features (abs Elo gap, league / team draw and under-2.5 rates) | 0.99644 | 0.98669 | −0.00006 | 3/8 | dropped |
| 2b | + online Poisson / Dixon–Coles goals model (5 columns) | 0.99186 | 0.98374 | −0.00301 | 6/8 | **kept** |
| 2c | Poisson columns alone (LR) | 0.98219 | 0.98506 | – | – | basis of B |
| 3 | + EWMA (half-life 5) of HT goals, corners, fouls, yellow and red cards | 0.99747 | 0.98640 | −0.00035 | 5/8 | dropped |
| 4a | + EWMA form (half-lives 3/8/20: points, goals, shots, SoT) | 1.00073 | 0.98573 | −0.00102 | 5/8 | dropped |
| 4b | EWMA form replacing the 5-match means | 0.99805 | 0.98582 | −0.00093 | 5/8 | dropped |
| 5 | + congestion (matches in the last 7 / 14 days) | 0.99512 | 0.98665 | −0.00010 | 5/8 | dropped |

Rows 2a–5 are relative to row 1. Retested on top of finalist A (LightGBM):

| Addition to A | Δ walk-forward | Folds better |
|---|---|---|
| raw stats (row 3) | −0.00010 | 5/8 |
| EWMA form (row 4a) | +0.00016 | 4/8 |
| EWMA half-life 8 only | +0.00035 | 4/8 |
| congestion | −0.00011 | 6/8 |
| draw features | +0.00060 | 3/8 |
| league one-hots + season progress | +0.00005 | 4/8 |

All were dropped. Raw stats: the HT goals, corners, fouls and cards parsing,
model columns and migration were reverted. Nothing ships for them; see
`experimental_full.patch` in the scratch directory if they are wanted as data
capture. Kickoff `Time` was already parsed into `kickoff` (UTC) by
`csv_history`, so experiment 5 needed no parsing change.

### Elo tuning (experiment 1; `src/features/elo.py`)

| Setting | Elo-only LR walk-forward |
|---|---|
| Old: K=20, home advantage 60, season regression 0.25 | 0.99227 |
| K=14, season regression 0.05 (grid K 6–34 × HA 40–100 × regression 0–0.55) | 0.98956 |
| + margin cap (none / 0 / 1 / 2 / 3 / 5) | best = none |
| + promoted-team penalty (50 / 100 / 175) | no effect |
| + static per-league home advantage (PD 90, SA 40) | 0.98918 |
| + **adaptive per-league home advantage**, rate 4 (no static overrides needed) | **0.98874** |

The adaptive home advantage captures, for example, the 2020 empty-stadium
drop. After every result, the competition's home advantage moves by
`rate × (home score − expected)`.

### Poisson goals model (experiment 2b; `src/features/engine.py`)

The model is `log λ_home = base_home(league) + attack_home − defence_away`, and
symmetrically for the away side. After each match it takes one SGD step on the
Poisson likelihood. The update target is `0.65 × goals + 0.35 × 0.32 × shots on
target`. The outcome probabilities use a Dixon–Coles correction with ρ = −0.10.
All state is updated in the engine's end-of-day `flush`. Tuning proxy: the raw
probabilities' walk-forward log-loss.

| Setting | Raw probability walk-forward |
|---|---|
| Initial: lr 0.04, season regression 0.2, ρ −0.05 | 0.98969 |
| lr 0.02, regression 0, ρ −0.10, league lr 0.002 | 0.98315 |
| + shots-on-target blend 0.35, lr 0.025 | **0.98150** |
| + all-shots blend (0.1–0.3) | 0.98147 (noise, dropped) |

## Final candidates (real pipeline)

| Candidate | Columns | Selected | Walk-forward | Holdout |
|---|---|---|---|---|
| A: Elo 4 + Poisson 7 + the 14 columns serving reads | 25 | xgboost | 0.9838 | 0.9894 |
| B: Poisson 7 only | 7 | logistic_regression | 0.9822 | 0.9907 |

Both runs used 25 trials and the pre-hygiene `train.py`. B was 0.0016 better on
walk-forward, which is below the 0.002 rule, and worse on the holdout. It would
also need a `src/api/serving.py` change, because the API reads detail columns
from the feature row. **A was chosen.**

## Final model (A, 100 Optuna trials, recency decay tuned)

| | Baseline (LightGBM, 37 features) | **Final (XGBoost, 25 features)** |
|---|---|---|
| Walk-forward log-loss | 0.98907 | **0.98292** (−0.0062) |
| Walk-forward accuracy | 0.5252 | 0.5302 |
| Walk-forward Brier | 0.5891 | 0.5849 |
| Holdout log-loss | 0.99424 | **0.98835** (−0.0059) |
| Holdout accuracy | 0.5188 | 0.5212 |
| Holdout Brier | 0.5925 | 0.5886 |
| Holdout draw-prediction rate (argmax) | 0.0005 | 0.0000 |
| Holdout confusion (rows H/D/A actual) | `[[712,1,192],[320,0,201],[272,0,351]]` | `[[712,0,193],[325,0,196],[267,0,356]]` |

Fold log-loss: `0.9701, 0.9767, 0.9872, 0.9989, 0.9893, 0.9876, 0.9732, 0.9803`.
The baseline's folds were `0.9778, 0.9820, 0.9971, 1.0038, 0.9977, 0.9883,
0.9793, 0.9865`, so all 8 improved.

Per league:

| League | Walk-forward baseline | Walk-forward final | Holdout baseline | Holdout final |
|---|---|---|---|---|
| BL1 | 0.9980 | 0.9938 | 0.9725 | 0.9623 |
| FL1 | 1.0084 | 1.0044 | 0.9942 | 0.9944 |
| PD | 0.9956 | 0.9896 | 0.9828 | 0.9685 |
| PL | 0.9682 | 0.9617 | 1.0356 | 1.0356 |
| SA | 0.9785 | 0.9691 | 0.9821 | 0.9776 |

Other candidates and baselines from the same run:

| Name | Walk-forward | Holdout |
|---|---|---|
| logistic_regression | 0.9857 | 0.9900 |
| xgboost (selected) | 0.9829 | 0.9884 |
| lgbm | 0.9831 | 0.9893 |
| calibrated_lr | 0.9919 | 0.9885 |
| calibrated_xgb | 0.9864 | 0.9881 |
| calibrated_lgbm | 0.9865 | 0.9885 |
| ensemble | 0.9862 | 0.9903 |
| baseline elo (new Elo) | 0.9887 | 0.9932 |
| baseline poisson (raw engine probabilities) | 0.9815* | 0.9916 |

\* In-sample for the Poisson constants.

The yardstick moved too: with the old Elo, the Elo baseline scored 0.99227
walk-forward and 0.99784 on the holdout.

Draws are still never the argmax prediction. That is normal for 1X2 log-loss
models, and the draw-prediction rate was not optimised. The mean predicted draw
probability is about 0.25.

## Code changes

- `src/features/elo.py`:
  - New defaults: K=14, season regression 0.05, adaptive home advantage rate 4.
  - Optional `EloRatings(...)` keyword arguments and `margin_cap`.
  - Per-league overrides and `home_advantage_for(league)`.
  - The public names and signatures are unchanged; new arguments are optional
    with defaults.
  - A replay through `commit` / `apply_result` matches the engine; this was
    tested, including `codex`'s `team_stats.replay_elo` parity tests.
  - With the adaptive home advantage, the effective home advantage of a league is
    `EloRatings.home_advantage_for(league)`, not the constant `HOME_ADVANTAGE`.
- `src/features/engine.py`:
  - Online Poisson / Dixon–Coles model.
  - `compute_features(matches, elo_params=None, columns=None)`.
  - The engine computes `ENGINE_COLS`, 44 columns.
- `src/features/columns.py`:
  - New `ENGINE_COLS` and `POISSON_COLS`.
  - `FEATURE_COLS` goes from 37 to 25 columns: the league one-hots, including
    the always-zero `league_CL`, are dropped, along with venue form, shots
    against, SoT, venue win rates and season progress.
  - CL fixtures are still served through the shared Elo and Poisson strengths.
  - `FEATURE_LABELS` is derived from `ENGINE_LABELS`.
- `src/model/train.py`:
  - Recency decay is tuned inside Optuna for XGBoost and LightGBM.
  - The logistic regression gets a C × decay grid.
  - The registry gains per-candidate walk-forward and holdout Brier,
    draw-prediction rate, confusion matrix, and per-league scores.
- `src/model/scoring.py`: new per-league and overall scoring helpers.
- `src/model/baselines.py`: new `poisson` baseline.

## Caveats

- Serving skew: the Poisson update uses shots on target when both are known.
  Rows from football-data.org that co.uk has not refreshed yet, and CL matches,
  update on goals only. Rest days were already counted across all competitions.
- The registry's `git_commit` is set to the commit that contains this code. The
  model was trained from the identical working tree before that commit.
