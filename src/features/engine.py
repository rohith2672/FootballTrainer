"""Point-in-time feature engine shared by training and serving.

``compute_features(matches)`` walks the matches once in chronological order.
For every row it FIRST emits features from the current state and only THEN
(after the whole calendar day has been emitted) updates the state with the
finished matches of that day. Consequences:

* A row never sees its own result, nor the result of any match played the
  same UTC calendar day, nor anything later (no leakage).
* Rows without a result (``home_goals`` / ``away_goals`` null) are fixtures to
  predict: they get features but write nothing into the state.
* Training calls this on all finished matches; the API calls it on finished
  history plus appended upcoming fixtures, so there is exactly one code path.

The engine computes every column of ``ENGINE_COLS``; ``FEATURE_COLS`` (the
model's inputs) is a subset and the default output.

Dependencies are kept light (pandas / numpy / stdlib) - no DB or ORM imports.
"""
import math
from collections import deque
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from src.features import elo as elo_mod
from src.features.columns import ENGINE_COLS, FEATURE_COLS, LEAGUES
from src.ingestion.seasons import season_start_year

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
FORM_WINDOW = 5
H2H_PRIOR_K = 3.0           # pseudo-meetings pulling h2h toward the league prior
VENUE_PRIOR_K = 5.0         # pseudo-games pulling season home/away win rates to the league prior
LEAGUE_PRIOR_M = 30.0       # pseudo-matches smoothing the running league prior itself
DEFAULT_HOME_WIN = 0.45     # league-prior fallbacks before any data is seen
DEFAULT_DRAW = 0.26
DEFAULT_AWAY_WIN = 0.29
REST_CAP_DAYS = 30.0
SEASON_GAMES = {"PL": 38, "PD": 38, "SA": 38, "BL1": 34, "FL1": 38, "CL": 13}
DEFAULT_SEASON_GAMES = 38
FL1_34_GAME_FROM_SEASON = 2023   # Ligue 1 went 20 -> 18 clubs (34 matches per team) in 2023-24

# Online Poisson goals model: log(lambda_home) = league_home_base + attack_home - defence_away
# (and symmetrically for the away side). After every finished match the strengths take
# one stochastic-gradient step on the Poisson log-likelihood. Tuned on walk-forward
# dev folds only (docs/model_experiments_2026-10-20.md); the holdout was not used.
POIS_LR = 0.025             # learning rate of team strengths (per goal of error)
POIS_LEAGUE_LR = 0.002      # learning rate of the league home / away log-means
POIS_SEASON_REGRESSION = 0.0    # share of a team's strength removed at its first match of a new season
POIS_PROMOTED = -0.15       # initial attack and defence of a team new to a league after its first season
POIS_HOME_BASE = math.log(1.50)
POIS_AWAY_BASE = math.log(1.15)
POIS_RHO = -0.10            # Dixon-Coles low-score dependence (fixed; < 0 lifts 0-0 / 1-1)
POIS_MAX_GOALS = 10
# The update target blends goals with a shots-on-target "expected goals" proxy
# (when both sides' shots on target are known; otherwise goals only).
POIS_SOT_WEIGHT = 0.35
POIS_SOT_CONVERSION = 0.32  # goals per shot on target (big-5 average)

REQUIRED_COLUMNS = ("date", "league", "home_team", "away_team", "home_goals", "away_goals")
SHOT_COLUMNS = ("home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target")
_NAN = float("nan")
_SECONDS_PER_DAY = 86400.0


def season_games(league: str, season: int) -> int:
    """Matches per team in a competition's season (denominator of ``season_progress``)."""
    if league == "FL1" and season >= FL1_34_GAME_FROM_SEASON:
        return 34
    return SEASON_GAMES.get(league, DEFAULT_SEASON_GAMES)


class _Team:
    """Rolling per-team history (all competitions)."""

    __slots__ = ("recent", "home_recent", "away_recent", "shots", "last_ts", "att", "dfn", "pois_season")

    def __init__(self) -> None:
        self.recent = deque(maxlen=FORM_WINDOW)        # (pts, gf, ga)
        self.home_recent = deque(maxlen=FORM_WINDOW)   # pts in home games
        self.away_recent = deque(maxlen=FORM_WINDOW)   # pts in away games
        self.shots = deque(maxlen=FORM_WINDOW)         # (shots_for, shots_against, sot_for, sot_against)
        self.last_ts = None
        self.att = 0.0                                 # Poisson log attack strength
        self.dfn = 0.0                                 # Poisson log defence strength (higher = concedes less)
        self.pois_season = None                        # latest season with a Poisson update


class _LeagueStats:
    """Running outcome counts for a competition -> smoothed league priors."""

    __slots__ = ("n", "hw", "d", "aw")

    def __init__(self) -> None:
        self.n = self.hw = self.d = self.aw = 0

    def probs(self):
        m = LEAGUE_PRIOR_M
        den = self.n + m
        return (
            (self.hw + m * DEFAULT_HOME_WIN) / den,
            (self.d + m * DEFAULT_DRAW) / den,
            (self.aw + m * DEFAULT_AWAY_WIN) / den,
        )

    def home_win_prior(self) -> float:
        return self.probs()[0]

    def away_win_prior(self) -> float:
        return self.probs()[2]

    def points_share_prior(self) -> float:
        """Average points per team-game as a share of the 3-point maximum."""
        ph, pd_, pa = self.probs()
        return (3.0 * (ph + pa) + 2.0 * pd_) / 2.0 / 3.0


def _pts(goals_for: int, goals_against: int) -> int:
    if goals_for > goals_against:
        return 3
    return 1 if goals_for == goals_against else 0


def _isnum(x) -> bool:
    return x == x  # False only for NaN


def _mean(values) -> float:
    return sum(values) / len(values) if values else _NAN


def _shot_means(team: _Team):
    """(shots_for, shots_against, sot_for, sot_against) over the last <=5 matches with shots."""
    if not team.shots:
        return _NAN, _NAN, _NAN, _NAN
    sf = [e[0] for e in team.shots]
    sa = [e[1] for e in team.shots]
    tf = [e[2] for e in team.shots if _isnum(e[2])]
    ta = [e[3] for e in team.shots if _isnum(e[3])]
    return _mean(sf), _mean(sa), _mean(tf), _mean(ta)


def poisson_outcome_probs(lam_home, lam_away, rho: Optional[float] = None, max_goals: int = POIS_MAX_GOALS):
    """Vectorised (home, draw, away) probabilities of independent Poisson goals with
    the Dixon-Coles low-score correction ``rho`` (default ``POIS_RHO``), truncated at
    ``max_goals`` and renormalised. Rows with a non-finite rate are NaN."""
    rho = POIS_RHO if rho is None else rho
    lh = np.asarray(lam_home, dtype=float)
    la = np.asarray(lam_away, dtype=float)
    out = np.full((len(lh), 3), np.nan)
    ok = np.isfinite(lh) & np.isfinite(la) & (lh > 0) & (la > 0)
    if not ok.any():
        return out
    lh, la = lh[ok], la[ok]
    k = np.arange(max_goals + 1)
    logfact = np.cumsum(np.log(np.maximum(k, 1)))
    ph = np.exp(-lh[:, None] + k[None, :] * np.log(lh[:, None]) - logfact[None, :])
    pa = np.exp(-la[:, None] + k[None, :] * np.log(la[:, None]) - logfact[None, :])
    grid = ph[:, :, None] * pa[:, None, :]
    if rho:
        grid[:, 0, 0] *= np.maximum(1.0 - lh * la * rho, 0.0)
        grid[:, 0, 1] *= np.maximum(1.0 + lh * rho, 0.0)
        grid[:, 1, 0] *= np.maximum(1.0 + la * rho, 0.0)
        grid[:, 1, 1] *= np.maximum(1.0 - rho, 0.0)
    home_wins = np.tril(np.ones((max_goals + 1, max_goals + 1), dtype=bool), -1)   # home goals > away goals
    p_home = grid[:, home_wins].sum(axis=1)
    p_draw = np.einsum("nii->n", grid)
    p_away = grid[:, home_wins.T].sum(axis=1)
    tot = p_home + p_draw + p_away
    out[ok] = np.column_stack([p_home, p_draw, p_away]) / tot[:, None]
    return out


def _prepare(matches: pd.DataFrame) -> Dict[str, np.ndarray]:
    missing = [c for c in REQUIRED_COLUMNS if c not in matches.columns]
    if missing:
        raise ValueError(f"matches is missing required columns: {missing}")
    n = len(matches)
    date = pd.to_datetime(matches["date"])
    if getattr(date.dt, "tz", None) is not None:
        date = date.dt.tz_convert("UTC").dt.tz_localize(None)

    if "season" in matches.columns:
        season = pd.to_numeric(matches["season"], errors="coerce")
    else:
        season = pd.Series(np.nan, index=matches.index)
    derived = date.map(season_start_year).astype(float)
    season = season.where(season.notna(), derived).astype(int)

    if "kickoff" in matches.columns:
        kick = pd.to_datetime(matches["kickoff"])
        if getattr(kick.dt, "tz", None) is not None:
            kick = kick.dt.tz_convert("UTC").dt.tz_localize(None)
        ts_dt = kick.where(kick.notna(), date)
    else:
        ts_dt = date

    ident = None
    for name in ("id", "match_id"):
        if name in matches.columns:
            ident = matches[name].to_numpy()
            break

    cols = {
        "date": date.to_numpy(),
        "day": date.to_numpy().astype("datetime64[D]").astype(np.int64),
        "ts": ts_dt.to_numpy().astype("datetime64[s]").astype(np.int64),
        "season": season.to_numpy(dtype=np.int64),
        "league": matches["league"].astype(object).to_numpy(),
        "home": matches["home_team"].astype(object).to_numpy(),
        "away": matches["away_team"].astype(object).to_numpy(),
        "hg": pd.to_numeric(matches["home_goals"], errors="coerce").to_numpy(dtype=float),
        "ag": pd.to_numeric(matches["away_goals"], errors="coerce").to_numpy(dtype=float),
        "id": ident,
    }
    for c in SHOT_COLUMNS:
        if c in matches.columns:
            cols[c] = pd.to_numeric(matches[c], errors="coerce").to_numpy(dtype=float)
        else:
            cols[c] = np.full(n, np.nan)
    return cols


def _sort_order(cols: Dict[str, np.ndarray]) -> np.ndarray:
    """Chronological order, tiebreak: date, league, home_team, away_team, id, position."""
    n = len(cols["home"])
    frame = pd.DataFrame({
        "date": cols["date"],
        "league": cols["league"],
        "home": cols["home"],
        "away": cols["away"],
        "id": cols["id"] if cols["id"] is not None else np.arange(n),
        "pos": np.arange(n),
    })
    return frame.sort_values(
        ["date", "league", "home", "away", "id", "pos"], kind="mergesort"
    )["pos"].to_numpy()


def _pois_pre(team: Optional[_Team], league: str, season: int, league_first: Dict[str, int]):
    """(attack, defence) a team brings into a match, without writing any state.

    A team never updated starts at 0 (league average), or at ``POIS_PROMOTED`` when
    it joins a domestic league after that league's first season in the data. At a
    team's first match of a new season its strengths are shrunk by
    ``POIS_SEASON_REGRESSION``.
    """
    if team is None or team.pois_season is None:
        first = league_first.get(league)
        promoted = league != elo_mod.CL_LEAGUE and first is not None and season > first
        v = POIS_PROMOTED if promoted else 0.0
        return v, v
    if season > team.pois_season:
        f = 1.0 - POIS_SEASON_REGRESSION
        return team.att * f, team.dfn * f
    return team.att, team.dfn


def compute_features(
    matches: pd.DataFrame,
    elo_params: Optional[dict] = None,
    columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Point-in-time features for every row of ``matches``.

    Parameters
    ----------
    matches : DataFrame with columns ``date``, ``league``, ``home_team``,
        ``away_team``, ``home_goals``, ``away_goals`` (null for fixtures to
        predict). Optional: ``season`` (derived from ``date`` when null/absent),
        ``kickoff``, ``home_shots``, ``away_shots``, ``home_shots_on_target``,
        ``away_shots_on_target``, ``id`` (or ``match_id``; only used as a sort
        tiebreak). Row order does not matter; the engine sorts internally.
    elo_params : optional keyword arguments for ``elo.EloRatings`` (tuning /
        experiments only; ``None`` = the module defaults used in production).
    columns : columns to return (any of ``ENGINE_COLS``); default ``FEATURE_COLS``.

    Returns
    -------
    DataFrame with ``columns`` (default ``FEATURE_COLS``, in that order) and the
    same index / row order as ``matches``.
    """
    columns = list(FEATURE_COLS if columns is None else columns)
    unknown = [c for c in columns if c not in ENGINE_COLS]
    if unknown:
        raise ValueError(f"unknown feature columns: {unknown}")
    n = len(matches)
    if n == 0:
        return pd.DataFrame(np.full((0, len(columns)), np.nan), columns=columns, index=matches.index)
    fidx = {name: i for i, name in enumerate(ENGINE_COLS)}
    out = np.full((n, len(ENGINE_COLS)), np.nan)

    c = _prepare(matches)
    order = _sort_order(c)

    elo = elo_mod.EloRatings(**(elo_params or {}))
    teams: Dict[str, _Team] = {}
    leagues: Dict[str, _LeagueStats] = {}
    league_base: Dict[str, list] = {}      # league -> [log mean home goals, log mean away goals]
    league_first: Dict[str, int] = {}      # domestic league -> first season with a result
    season_ctr: Dict[tuple, list] = {}     # (team, season, league) -> [home_n, home_w, away_n, away_w]
    h2h: Dict[tuple, list] = {}            # (first, second) -> [n, pts_first, pts_second]

    day_a, ts_a, season_a = c["day"], c["ts"], c["season"]
    league_a, home_a, away_a = c["league"], c["home"], c["away"]
    hg_a, ag_a = c["hg"], c["ag"]
    hs_a, as_a = c["home_shots"], c["away_shots"]
    hst_a, ast_a = c["home_shots_on_target"], c["away_shots_on_target"]

    pending: List[tuple] = []

    def flush() -> None:
        for (home, away, lg, season, hg, ag, ts, h_elo, a_elo, shots, pois) in pending:
            elo.apply_result(home, away, lg, season, hg, ag, h_elo, a_elo)
            th, ta = teams[home], teams[away]
            ph, pa = _pts(hg, ag), _pts(ag, hg)
            th.recent.append((ph, hg, ag))
            ta.recent.append((pa, ag, hg))
            th.home_recent.append(ph)
            ta.away_recent.append(pa)
            hs, as_, hst, ast = shots
            if _isnum(hs) and _isnum(as_):
                th.shots.append((hs, as_, hst, ast))
                ta.shots.append((as_, hs, ast, hst))
            th.last_ts = ts
            ta.last_ts = ts

            # online Poisson goals model (strengths entering the match come from `pois`)
            att_h, dfn_h, att_a, dfn_a = pois
            base = league_base.setdefault(lg, [POIS_HOME_BASE, POIS_AWAY_BASE])
            lam_h = math.exp(base[0] + att_h - dfn_a)
            lam_a = math.exp(base[1] + att_a - dfn_h)
            target_h, target_a = float(hg), float(ag)
            if POIS_SOT_WEIGHT > 0.0 and _isnum(hst) and _isnum(ast):
                w = POIS_SOT_WEIGHT
                target_h = (1.0 - w) * target_h + w * POIS_SOT_CONVERSION * hst
                target_a = (1.0 - w) * target_a + w * POIS_SOT_CONVERSION * ast
            err_h, err_a = target_h - lam_h, target_a - lam_a
            th.att = att_h + POIS_LR * err_h
            ta.dfn = dfn_a - POIS_LR * err_h
            ta.att = att_a + POIS_LR * err_a
            th.dfn = dfn_h - POIS_LR * err_a
            th.pois_season = season if th.pois_season is None else max(th.pois_season, season)
            ta.pois_season = season if ta.pois_season is None else max(ta.pois_season, season)
            base[0] += POIS_LEAGUE_LR * err_h
            base[1] += POIS_LEAGUE_LR * err_a
            if lg != elo_mod.CL_LEAGUE:
                league_first.setdefault(lg, season)

            hc = season_ctr.setdefault((home, season, lg), [0, 0, 0, 0])
            ac = season_ctr.setdefault((away, season, lg), [0, 0, 0, 0])
            hc[0] += 1
            ac[2] += 1
            if hg > ag:
                hc[1] += 1
            elif ag > hg:
                ac[3] += 1

            pair = (home, away) if home <= away else (away, home)
            rec = h2h.setdefault(pair, [0, 0, 0])
            rec[0] += 1
            if pair[0] == home:
                rec[1] += ph
                rec[2] += pa
            else:
                rec[1] += pa
                rec[2] += ph

            ls = leagues.setdefault(lg, _LeagueStats())
            ls.n += 1
            if hg > ag:
                ls.hw += 1
            elif hg == ag:
                ls.d += 1
            else:
                ls.aw += 1
        pending.clear()

    current_day = None
    for i in order:
        day = day_a[i]
        if current_day is not None and day != current_day:
            flush()
        current_day = day

        home, away, lg, season = home_a[i], away_a[i], league_a[i], int(season_a[i])
        finished = _isnum(hg_a[i]) and _isnum(ag_a[i])
        ts = int(ts_a[i])

        if finished:
            h_elo = elo.commit(home, lg, season)
            a_elo = elo.commit(away, lg, season)
        else:
            h_elo = elo.peek(home, lg, season)
            a_elo = elo.peek(away, lg, season)

        th = teams.get(home)
        ta = teams.get(away)
        pois = _pois_pre(th, lg, season, league_first) + _pois_pre(ta, lg, season, league_first)
        if finished:
            if th is None:
                th = teams[home] = _Team()
            if ta is None:
                ta = teams[away] = _Team()
        th_state = th if th is not None else _Team()
        ta_state = ta if ta is not None else _Team()

        row = out[i]
        # ----- Elo -----
        diff = h_elo - a_elo + elo.home_advantage_for(lg)
        row[fidx["home_elo"]] = h_elo
        row[fidx["away_elo"]] = a_elo
        row[fidx["elo_diff"]] = diff
        row[fidx["elo_expected_home"]] = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))

        # ----- Poisson goals model (rates; probabilities are vectorised after the loop) -----
        base = league_base.get(lg, (POIS_HOME_BASE, POIS_AWAY_BASE))
        row[fidx["pois_lambda_home"]] = math.exp(base[0] + pois[0] - pois[3])
        row[fidx["pois_lambda_away"]] = math.exp(base[1] + pois[2] - pois[1])

        # ----- Form (all competitions) -----
        for side, st in (("home", th_state), ("away", ta_state)):
            k = len(st.recent)
            row[fidx[f"{side}_form_n"]] = k
            if k:
                row[fidx[f"{side}_form_pts_pg"]] = sum(e[0] for e in st.recent) / k
                row[fidx[f"{side}_form_goals_scored_avg"]] = sum(e[1] for e in st.recent) / k
                row[fidx[f"{side}_form_goals_conceded_avg"]] = sum(e[2] for e in st.recent) / k
        if th_state.home_recent:
            row[fidx["home_venue_form_pts_pg"]] = _mean(th_state.home_recent)
        if ta_state.away_recent:
            row[fidx["away_venue_form_pts_pg"]] = _mean(ta_state.away_recent)

        # ----- Shots form -----
        for side, st in (("home", th_state), ("away", ta_state)):
            sf, sa, tf, tg = _shot_means(st)
            row[fidx[f"{side}_shots_for_avg"]] = sf
            row[fidx[f"{side}_shots_against_avg"]] = sa
            row[fidx[f"{side}_sot_for_avg"]] = tf
            row[fidx[f"{side}_sot_against_avg"]] = tg

        # ----- Head-to-head (all prior meetings, shrunk to the league prior) -----
        ls = leagues.get(lg)
        stats = ls if ls is not None else _LeagueStats()
        pair = (home, away) if home <= away else (away, home)
        rec = h2h.get(pair)
        if rec is None:
            n_meet, pts_home = 0, 0.0
        else:
            n_meet = rec[0]
            pts_home = rec[1] if pair[0] == home else rec[2]
        prior = stats.points_share_prior()
        row[fidx["h2h_home_pts_rate"]] = (pts_home + 3.0 * H2H_PRIOR_K * prior) / (3.0 * (n_meet + H2H_PRIOR_K))
        row[fidx["h2h_n"]] = n_meet

        # ----- Season venue win rates (shrunk to the league prior) -----
        hc = season_ctr.get((home, season, lg))
        ac = season_ctr.get((away, season, lg))
        hn, hw = (hc[0], hc[1]) if hc else (0, 0)
        an, aw = (ac[2], ac[3]) if ac else (0, 0)
        row[fidx["home_team_home_win_rate"]] = (hw + VENUE_PRIOR_K * stats.home_win_prior()) / (hn + VENUE_PRIOR_K)
        row[fidx["away_team_away_win_rate"]] = (aw + VENUE_PRIOR_K * stats.away_win_prior()) / (an + VENUE_PRIOR_K)
        row[fidx["home_home_games_n"]] = hn
        row[fidx["away_away_games_n"]] = an

        # ----- Rest -----
        if th_state.last_ts is not None:
            row[fidx["home_days_since_last"]] = min((ts - th_state.last_ts) / _SECONDS_PER_DAY, REST_CAP_DAYS)
        if ta_state.last_ts is not None:
            row[fidx["away_days_since_last"]] = min((ts - ta_state.last_ts) / _SECONDS_PER_DAY, REST_CAP_DAYS)

        # ----- Context -----
        for name in LEAGUES:
            row[fidx[f"league_{name}"]] = 1.0 if lg == name else 0.0
        played = (hc[0] + hc[2]) if hc else 0
        row[fidx["season_progress"]] = played / season_games(lg, season)

        if finished:
            pending.append((
                home, away, lg, season, int(hg_a[i]), int(ag_a[i]), ts, h_elo, a_elo,
                (hs_a[i], as_a[i], hst_a[i], ast_a[i]), pois,
            ))

    flush()

    probs = poisson_outcome_probs(out[:, fidx["pois_lambda_home"]], out[:, fidx["pois_lambda_away"]])
    out[:, fidx["pois_p_home"]] = probs[:, 0]
    out[:, fidx["pois_p_draw"]] = probs[:, 1]
    out[:, fidx["pois_p_away"]] = probs[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[:, fidx["pois_logit_home"]] = np.log(probs[:, 0] / probs[:, 1])
        out[:, fidx["pois_logit_away"]] = np.log(probs[:, 2] / probs[:, 1])
    sel = [fidx[name] for name in columns]
    return pd.DataFrame(out[:, sel], columns=columns, index=matches.index)
