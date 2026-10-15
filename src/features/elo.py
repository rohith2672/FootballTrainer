"""Elo ratings across all competitions (domestic leagues + Champions League).

One rating per team, shared by league and CL matches, so CL games link the
strength of different leagues. Pure Python / stdlib only (no DB, no pandas).

Design notes
------------
* Home advantage is added to the home rating when forming the expectation.
* The update is scaled by a goal-difference multiplier ``1 + ln(1 + |gd|)``
  (never 0, so draws between unequal teams still move ratings).
* At a team's first match of a new season its rating is regressed toward the
  mean of its (domestic) league. The mean is computed ONCE per (league, season)
  from the previous season's roster and then cached, so it does not depend on
  the order in which same-season matches are processed.
* A team never seen before is initialised at ``BASE_RATING`` when its league is
  in its first season in the data, otherwise (promoted team) at the mean
  rating of the previous season's bottom ``N_RELEGATED`` teams of that league,
  falling back to ``league mean - PROMOTED_PENALTY``. CL-only teams start at
  ``BASE_RATING``.
* ``peek`` computes the rating a team would have without writing anything, so
  fixtures (rows without a result) leave the state completely untouched.
"""
import math
from typing import Dict, Optional, Set, Tuple

BASE_RATING = 1500.0
K_FACTOR = 20.0
HOME_ADVANTAGE = 60.0
SEASON_REGRESSION = 0.25        # share of the gap to the league mean removed each new season
PROMOTED_PENALTY = 100.0        # used when previous-season relegated teams are unknown
N_RELEGATED = 3                 # bottom-N of the previous table define the promoted-team prior
MIN_TABLE_TEAMS = 8             # ignore tables with fewer teams (truncated / partial seasons)
CL_LEAGUE = "CL"


def expected_home_score(home_elo: float, away_elo: float, home_advantage: float = HOME_ADVANTAGE) -> float:
    """Logistic expectation (win=1, draw=0.5) for the home side incl. home advantage."""
    diff = home_elo - away_elo + home_advantage
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def goal_diff_multiplier(goal_diff: int) -> float:
    """1 for a draw, growing logarithmically with the margin of victory."""
    return 1.0 + math.log(1.0 + abs(goal_diff))


def rating_delta(home_elo: float, away_elo: float, home_goals: int, away_goals: int) -> float:
    """Rating points moved from away to home (negative if the home side lost ground)."""
    if home_goals > away_goals:
        score = 1.0
    elif home_goals == away_goals:
        score = 0.5
    else:
        score = 0.0
    exp = expected_home_score(home_elo, away_elo)
    return K_FACTOR * goal_diff_multiplier(home_goals - away_goals) * (score - exp)


class EloRatings:
    """Mutable rating state. Feed finished matches through ``commit`` + ``apply_result``."""

    def __init__(self) -> None:
        self.rating: Dict[str, float] = {}
        self.last_season: Dict[str, int] = {}
        self.team_league: Dict[str, str] = {}
        self.roster: Dict[Tuple[str, int], Set[str]] = {}
        self.table: Dict[Tuple[str, int], Dict[str, list]] = {}   # team -> [pts, gd, gf]
        self.first_season: Dict[str, int] = {}
        self._refs: Dict[Tuple[str, int], Tuple[float, float]] = {}

    # ----- reference values (cached, order independent) -----
    def _mean_rating(self, teams) -> Optional[float]:
        vals = [self.rating[t] for t in teams if t in self.rating]
        return sum(vals) / len(vals) if vals else None

    def _reference(self, league: str, season: int, store: bool = True) -> Tuple[float, float]:
        """(league mean, promoted-team initial rating) for ``league`` in ``season``.

        With ``store=False`` (fixtures) the value is computed from the current
        state and nothing is cached or written.
        """
        key = (league, season)
        cached = self._refs.get(key)
        if cached is not None:
            return cached
        prev = self.roster.get((league, season - 1))
        mean = self._mean_rating(prev) if prev else None
        if mean is None:
            cur = self.roster.get(key)
            mean = self._mean_rating(cur) if cur else None
        if mean is None:
            mean = BASE_RATING

        promoted = mean - PROMOTED_PENALTY
        table = self.table.get((league, season - 1))
        if table and len(table) >= MIN_TABLE_TEAMS:
            worst = sorted(table.items(), key=lambda kv: (kv[1][0], kv[1][1], kv[1][2], kv[0]))[:N_RELEGATED]
            rel_mean = self._mean_rating([t for t, _ in worst])
            if rel_mean is not None:
                promoted = rel_mean
        if not store:
            return mean, promoted
        self._refs[key] = (mean, promoted)
        return self._refs[key]

    # ----- ratings -----
    def _resolve(self, team: str, league: str, season: int, store: bool = True) -> Tuple[float, bool]:
        cur = self.rating.get(team)
        if cur is None:
            if league == CL_LEAGUE:
                return BASE_RATING, True
            fs = self.first_season.get(league)
            if fs is None or season <= fs:
                return BASE_RATING, True
            return self._reference(league, season, store)[1], True
        if season > self.last_season.get(team, season):
            lg = league if league != CL_LEAGUE else self.team_league.get(team)
            mean = self._reference(lg, season, store)[0] if lg else BASE_RATING
            return cur + SEASON_REGRESSION * (mean - cur), True
        return cur, False

    def peek(self, team: str, league: str, season: int) -> float:
        """Pre-match rating without changing any rating / roster state."""
        return self._resolve(team, league, season, store=False)[0]

    def commit(self, team: str, league: str, season: int) -> float:
        """Pre-match rating, persisting initialisation / season regression."""
        r, _ = self._resolve(team, league, season)
        self.rating[team] = r
        prev = self.last_season.get(team)
        self.last_season[team] = season if prev is None else max(prev, season)
        if league != CL_LEAGUE:
            self.team_league[team] = league
            self.roster.setdefault((league, season), set()).add(team)
            self.first_season.setdefault(league, season)
        return r

    def apply_result(
        self, home: str, away: str, league: str, season: int,
        home_goals: int, away_goals: int, home_elo: float, away_elo: float,
    ) -> float:
        """Update both ratings from a finished match; returns the delta moved to home."""
        delta = rating_delta(home_elo, away_elo, home_goals, away_goals)
        self.rating[home] = self.rating.get(home, home_elo) + delta
        self.rating[away] = self.rating.get(away, away_elo) - delta
        if league != CL_LEAGUE:
            tbl = self.table.setdefault((league, season), {})
            hp = 3 if home_goals > away_goals else (1 if home_goals == away_goals else 0)
            ap = 3 if away_goals > home_goals else (1 if home_goals == away_goals else 0)
            for team, pts, gf, ga in ((home, hp, home_goals, away_goals), (away, ap, away_goals, home_goals)):
                row = tbl.setdefault(team, [0, 0, 0])
                row[0] += pts
                row[1] += gf - ga
                row[2] += gf
        return delta
