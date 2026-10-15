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

Dependencies are kept light (pandas / numpy / stdlib) - no DB or ORM imports.
"""
import math
from collections import deque
from typing import Dict, List

import numpy as np
import pandas as pd

from src.features import elo as elo_mod
from src.features.columns import FEATURE_COLS, LEAGUES
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


def season_games(league: str, season: int) -> int:
    """Matches per team in a competition's season (denominator of ``season_progress``)."""
    if league == "FL1" and season >= FL1_34_GAME_FROM_SEASON:
        return 34
    return SEASON_GAMES.get(league, DEFAULT_SEASON_GAMES)

REQUIRED_COLUMNS = ("date", "league", "home_team", "away_team", "home_goals", "away_goals")
SHOT_COLUMNS = ("home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target")
_NAN = float("nan")
_SECONDS_PER_DAY = 86400.0


class _Team:
    """Rolling per-team history (all competitions)."""

    __slots__ = ("recent", "home_recent", "away_recent", "shots", "last_ts")

    def __init__(self) -> None:
        self.recent = deque(maxlen=FORM_WINDOW)        # (pts, gf, ga)
        self.home_recent = deque(maxlen=FORM_WINDOW)   # pts in home games
        self.away_recent = deque(maxlen=FORM_WINDOW)   # pts in away games
        self.shots = deque(maxlen=FORM_WINDOW)         # (shots_for, shots_against, sot_for, sot_against)
        self.last_ts = None


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


def compute_features(matches: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time features for every row of ``matches``.

    Parameters
    ----------
    matches : DataFrame with columns ``date``, ``league``, ``home_team``,
        ``away_team``, ``home_goals``, ``away_goals`` (null for fixtures to
        predict). Optional: ``season`` (derived from ``date`` when null/absent),
        ``kickoff``, ``home_shots``, ``away_shots``, ``home_shots_on_target``,
        ``away_shots_on_target``, ``id`` (or ``match_id``; only used as a sort
        tiebreak). Row order does not matter; the engine sorts internally.

    Returns
    -------
    DataFrame with the columns ``FEATURE_COLS`` (in that order) and the same
    index / row order as ``matches``.
    """
    n = len(matches)
    out = np.full((n, len(FEATURE_COLS)), np.nan)
    if n == 0:
        return pd.DataFrame(out, columns=FEATURE_COLS, index=matches.index)

    c = _prepare(matches)
    order = _sort_order(c)
    fidx = {name: i for i, name in enumerate(FEATURE_COLS)}

    elo = elo_mod.EloRatings()
    teams: Dict[str, _Team] = {}
    leagues: Dict[str, _LeagueStats] = {}
    season_ctr: Dict[tuple, list] = {}     # (team, season, league) -> [home_n, home_w, away_n, away_w]
    h2h: Dict[tuple, list] = {}            # (first, second) -> [n, pts_first, pts_second]

    day_a, ts_a, season_a = c["day"], c["ts"], c["season"]
    league_a, home_a, away_a = c["league"], c["home"], c["away"]
    hg_a, ag_a = c["hg"], c["ag"]
    hs_a, as_a = c["home_shots"], c["away_shots"]
    hst_a, ast_a = c["home_shots_on_target"], c["away_shots_on_target"]

    pending: List[tuple] = []

    def flush() -> None:
        for (home, away, lg, season, hg, ag, ts, h_elo, a_elo, shots) in pending:
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
        if finished:
            if th is None:
                th = teams[home] = _Team()
            if ta is None:
                ta = teams[away] = _Team()
        th_state = th if th is not None else _Team()
        ta_state = ta if ta is not None else _Team()

        row = out[i]
        # ----- Elo -----
        diff = h_elo - a_elo + elo_mod.HOME_ADVANTAGE
        row[fidx["home_elo"]] = h_elo
        row[fidx["away_elo"]] = a_elo
        row[fidx["elo_diff"]] = diff
        row[fidx["elo_expected_home"]] = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))

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
                (hs_a[i], as_a[i], hst_a[i], ast_a[i]),
            ))

    flush()
    return pd.DataFrame(out, columns=FEATURE_COLS, index=matches.index)
