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
from typing import Dict, Mapping, Optional, Set, Tuple

BASE_RATING = 1500.0
K_FACTOR = 14.0
HOME_ADVANTAGE = 60.0           # default home advantage (rating points)
SEASON_REGRESSION = 0.05        # share of the gap to the league mean removed each new season
MARGIN_CAP: Optional[int] = None  # |goal difference| above this counts as this (None = no cap)
PROMOTED_PENALTY = 100.0        # used when previous-season relegated teams are unknown
N_RELEGATED = 3                 # bottom-N of the previous table define the promoted-team prior
MIN_TABLE_TEAMS = 8             # ignore tables with fewer teams (truncated / partial seasons)
CL_LEAGUE = "CL"
_DEFAULT = object()   # "use the module default" sentinel (None is a meaningful margin_cap)
# Per-competition home advantage overrides (rating points); leagues not listed
# use HOME_ADVANTAGE. Use ``home_advantage_for`` rather than reading this directly.
LEAGUE_HOME_ADVANTAGE: Dict[str, float] = {}
# Online learning rate of each competition's home advantage (rating points per
# unit of home-score residual); 0 keeps the home advantage fixed.
HOME_ADVANTAGE_RATE = 4.0


def home_advantage_for(league: Optional[str], overrides: Optional[Mapping[str, float]] = None,
                       default: Optional[float] = None) -> float:
    """Home advantage used for ``league`` (module defaults unless overridden)."""
    table = LEAGUE_HOME_ADVANTAGE if overrides is None else overrides
    base = HOME_ADVANTAGE if default is None else default
    return float(table.get(league, base)) if league is not None else float(base)


def expected_home_score(home_elo: float, away_elo: float, home_advantage: float = HOME_ADVANTAGE) -> float:
    """Logistic expectation (win=1, draw=0.5) for the home side incl. home advantage.

    The default argument is the global ``HOME_ADVANTAGE``; for a specific
    competition pass ``home_advantage_for(league)`` (what the engine uses).
    """
    diff = home_elo - away_elo + home_advantage
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def goal_diff_multiplier(goal_diff: int, margin_cap: Optional[int] = MARGIN_CAP) -> float:
    """1 for a draw, growing logarithmically with the margin of victory (optionally capped)."""
    gd = abs(goal_diff)
    if margin_cap is not None:
        gd = min(gd, margin_cap)
    return 1.0 + math.log(1.0 + gd)


def rating_delta(
    home_elo: float, away_elo: float, home_goals: int, away_goals: int,
    k_factor: float = K_FACTOR, home_advantage: float = HOME_ADVANTAGE,
    margin_cap: Optional[int] = MARGIN_CAP,
) -> float:
    """Rating points moved from away to home (negative if the home side lost ground)."""
    if home_goals > away_goals:
        score = 1.0
    elif home_goals == away_goals:
        score = 0.5
    else:
        score = 0.0
    exp = expected_home_score(home_elo, away_elo, home_advantage)
    return k_factor * goal_diff_multiplier(home_goals - away_goals, margin_cap) * (score - exp)


class EloRatings:
    """Mutable rating state. Feed finished matches through ``commit`` + ``apply_result``.

    All tuning parameters default to the module constants, so ``EloRatings()``
    is exactly the rating system the feature engine uses.
    """

    def __init__(
        self,
        k_factor: Optional[float] = None,
        home_advantage: Optional[float] = None,
        season_regression: Optional[float] = None,
        margin_cap=_DEFAULT,
        league_home_advantage: Optional[Mapping[str, float]] = None,
        promoted_penalty: Optional[float] = None,
        home_advantage_rate: Optional[float] = None,
    ) -> None:
        self.home_advantage_rate = HOME_ADVANTAGE_RATE if home_advantage_rate is None else float(home_advantage_rate)
        # Learned per-competition home advantage (only when home_advantage_rate > 0).
        self.ha_state: Dict[str, float] = {}
        self.k_factor = K_FACTOR if k_factor is None else float(k_factor)
        self.home_advantage = HOME_ADVANTAGE if home_advantage is None else float(home_advantage)
        self.season_regression = SEASON_REGRESSION if season_regression is None else float(season_regression)
        self.margin_cap = MARGIN_CAP if margin_cap is _DEFAULT else margin_cap
        if league_home_advantage is None:
            # Overrides only apply with the default global value (a custom global
            # home advantage without explicit overrides means "same everywhere").
            league_home_advantage = dict(LEAGUE_HOME_ADVANTAGE) if home_advantage is None else {}
        self.league_home_advantage = dict(league_home_advantage)
        self.promoted_penalty = PROMOTED_PENALTY if promoted_penalty is None else float(promoted_penalty)
        self.rating: Dict[str, float] = {}
        self.last_season: Dict[str, int] = {}
        self.team_league: Dict[str, str] = {}
        self.roster: Dict[Tuple[str, int], Set[str]] = {}
        self.table: Dict[Tuple[str, int], Dict[str, list]] = {}   # team -> [pts, gd, gf]
        self.first_season: Dict[str, int] = {}
        self._refs: Dict[Tuple[str, int], Tuple[float, float]] = {}

    # ----- parameters -----
    def home_advantage_for(self, league: Optional[str]) -> float:
        """Home advantage (rating points) applied to a match in ``league``."""
        learned = self.ha_state.get(league)
        if learned is not None:
            return learned
        return home_advantage_for(league, self.league_home_advantage, self.home_advantage)

    def expected_home(self, home_elo: float, away_elo: float, league: Optional[str]) -> float:
        """Expected home score for a match in ``league`` (incl. its home advantage)."""
        return expected_home_score(home_elo, away_elo, self.home_advantage_for(league))

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

        promoted = mean - self.promoted_penalty
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
            return cur + self.season_regression * (mean - cur), True
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
        ha = self.home_advantage_for(league)
        delta = rating_delta(
            home_elo, away_elo, home_goals, away_goals,
            k_factor=self.k_factor, home_advantage=ha, margin_cap=self.margin_cap,
        )
        if self.home_advantage_rate > 0.0:
            score = 1.0 if home_goals > away_goals else (0.5 if home_goals == away_goals else 0.0)
            residual = score - expected_home_score(home_elo, away_elo, ha)
            self.ha_state[league] = ha + self.home_advantage_rate * residual
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
