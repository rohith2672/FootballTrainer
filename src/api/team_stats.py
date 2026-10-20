"""Pure team-analysis computations over finished-match history (no DB / FastAPI).

Everything here takes pandas DataFrames and returns plain dicts / lists, so it
is unit-testable without a database. Inputs are never mutated (the API shares
one cached history frame between requests).

The central piece is :func:`replay_elo`, which rebuilds the per-match rating
trace with the public API of ``src.features.elo`` in exactly the order the
feature engine (``src.features.engine.compute_features``) applies it. Keep it in
sync with the engine if that changes; ``tests/test_team_stats.py`` asserts parity.
"""
import datetime as dt
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from src.features import elo as elo_mod
from src.features.columns import LEAGUES
from src.ingestion.seasons import season_start_year

DOMESTIC_LEAGUES = tuple(lg for lg in LEAGUES if lg != elo_mod.CL_LEAGUE)
FORM_N = 5
AVERAGES_N = 10
SHOT_COLUMNS = ("home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target")

ENRICHED_COLUMNS = (
    "day", "date", "league", "season", "home_team", "away_team", "home_goals", "away_goals",
    *SHOT_COLUMNS,
    "home_elo_before", "away_elo_before", "home_elo_after", "away_elo_after", "src_index",
)


def _r(x, nd: int) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    return round(v, nd)


def _naive_utc(values) -> pd.Series:
    s = pd.to_datetime(values)
    if getattr(s.dt, "tz", None) is not None:
        s = s.dt.tz_convert("UTC").dt.tz_localize(None)
    return s


# ---------------------------------------------------------------------------
# Elo replay (mirrors src/features/engine.py; public elo.py API only)
# ---------------------------------------------------------------------------
def replay_elo(history: pd.DataFrame) -> pd.DataFrame:
    """Finished history -> chronologically sorted frame with pre/post-match Elo.

    Mirrors the engine: sort by (date, league, home_team, away_team, id,
    position) with a stable sort; for every row ``commit`` home then away (the
    pre-match rating); results are applied with ``apply_result`` only when the
    UTC calendar day of ``date`` changes, in the same order. ``*_elo_after`` is
    the rating right after that match's update. Rows without goals are dropped.
    ``src_index`` is the row's index label in ``history``.
    """
    if len(history) == 0:
        return pd.DataFrame(columns=list(ENRICHED_COLUMNS))
    hg_all = pd.to_numeric(history["home_goals"], errors="coerce")
    ag_all = pd.to_numeric(history["away_goals"], errors="coerce")
    keep = (hg_all.notna() & ag_all.notna()).to_numpy()
    src = history.loc[keep]
    n = len(src)
    if n == 0:
        return pd.DataFrame(columns=list(ENRICHED_COLUMNS))

    date = _naive_utc(src["date"]).reset_index(drop=True)
    if "season" in src.columns:
        season = pd.to_numeric(src["season"], errors="coerce").reset_index(drop=True)
    else:
        season = pd.Series(np.nan, index=range(n))
    season = season.where(season.notna(), date.map(season_start_year).astype(float)).astype(int)

    ident = None
    for name in ("id", "match_id"):
        if name in src.columns:
            ident = src[name].to_numpy()
            break
    league = src["league"].astype(object).to_numpy()
    home = src["home_team"].astype(object).to_numpy()
    away = src["away_team"].astype(object).to_numpy()
    order = pd.DataFrame({
        "date": date.to_numpy(), "league": league, "home": home, "away": away,
        "id": ident if ident is not None else np.arange(n), "pos": np.arange(n),
    }).sort_values(["date", "league", "home", "away", "id", "pos"], kind="mergesort")["pos"].to_numpy()

    day = date.to_numpy().astype("datetime64[D]").astype(np.int64)
    hg = hg_all[keep].to_numpy(dtype=float)
    ag = ag_all[keep].to_numpy(dtype=float)
    seasons = season.to_numpy(dtype=np.int64)

    before = np.full((n, 2), np.nan)
    after = np.full((n, 2), np.nan)
    ratings = elo_mod.EloRatings()
    pending: List[int] = []

    def flush() -> None:
        for p in pending:
            ratings.apply_result(
                home[p], away[p], league[p], int(seasons[p]), int(hg[p]), int(ag[p]),
                before[p, 0], before[p, 1],
            )
            after[p, 0] = ratings.rating[home[p]]
            after[p, 1] = ratings.rating[away[p]]
        pending.clear()

    current = None
    for p in order:
        if current is not None and day[p] != current:
            flush()
        current = day[p]
        s = int(seasons[p])
        before[p, 0] = ratings.commit(home[p], league[p], s)
        before[p, 1] = ratings.commit(away[p], league[p], s)
        pending.append(p)
    flush()

    out = pd.DataFrame({
        "day": date.dt.normalize(),
        "date": date,
        "league": league,
        "season": seasons,
        "home_team": home,
        "away_team": away,
        "home_goals": hg.astype(int),
        "away_goals": ag.astype(int),
    })
    for c in SHOT_COLUMNS:
        out[c] = (pd.to_numeric(src[c], errors="coerce").to_numpy(dtype=float)
                  if c in src.columns else np.full(n, np.nan))
    out["home_elo_before"], out["away_elo_before"] = before[:, 0], before[:, 1]
    out["home_elo_after"], out["away_elo_after"] = after[:, 0], after[:, 1]
    out["src_index"] = src.index.to_numpy()
    return out.iloc[order].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Slicing helpers
# ---------------------------------------------------------------------------
def _ts(day) -> pd.Timestamp:
    return pd.Timestamp(day).normalize()


def before_day(enriched: pd.DataFrame, as_of: Optional[dt.date]) -> pd.DataFrame:
    """Rows with match day strictly before ``as_of`` (all rows when None)."""
    if as_of is None or enriched.empty:
        return enriched
    return enriched.loc[enriched["day"] < _ts(as_of)]


def known_teams(enriched: pd.DataFrame) -> set:
    if enriched.empty:
        return set()
    return set(enriched["home_team"]).union(enriched["away_team"])


def team_matches(enriched: pd.DataFrame, team: str) -> pd.DataFrame:
    """The team's matches from its perspective, chronological (engine order)."""
    cols = ["day", "league", "season", "venue", "opponent", "gf", "ga", "result",
            "shots_for", "shots_against", "sot_for", "sot_against", "elo_before", "elo_after"]
    if enriched.empty:
        return pd.DataFrame(columns=cols)
    is_home = (enriched["home_team"] == team).to_numpy()
    mask = is_home | (enriched["away_team"] == team).to_numpy()
    sub = enriched.loc[mask]
    h = is_home[mask]

    def pick(home_col, away_col):
        return np.where(h, sub[home_col].to_numpy(), sub[away_col].to_numpy())

    gf = pick("home_goals", "away_goals").astype(int)
    ga = pick("away_goals", "home_goals").astype(int)
    return pd.DataFrame({
        "day": sub["day"].to_numpy(),
        "league": sub["league"].to_numpy(),
        "season": sub["season"].to_numpy(),
        "venue": np.where(h, "home", "away"),
        "opponent": pick("away_team", "home_team"),
        "gf": gf,
        "ga": ga,
        "result": np.where(gf > ga, "W", np.where(gf == ga, "D", "L")),
        "shots_for": pick("home_shots", "away_shots").astype(float),
        "shots_against": pick("away_shots", "home_shots").astype(float),
        "sot_for": pick("home_shots_on_target", "away_shots_on_target").astype(float),
        "sot_against": pick("away_shots_on_target", "home_shots_on_target").astype(float),
        "elo_before": pick("home_elo_before", "away_elo_before").astype(float),
        "elo_after": pick("home_elo_after", "away_elo_after").astype(float),
    })


def _long(enriched: pd.DataFrame) -> pd.DataFrame:
    """One row per (match, side) in chronological order: team, league, season, elo_after."""
    n = len(enriched)
    seq = np.arange(n)
    return pd.DataFrame({
        "seq": np.concatenate([seq, seq]),
        "side": np.concatenate([np.zeros(n, int), np.ones(n, int)]),
        "team": np.concatenate([enriched["home_team"].to_numpy(), enriched["away_team"].to_numpy()]),
        "league": np.concatenate([enriched["league"].to_numpy()] * 2),
        "season": np.concatenate([enriched["season"].to_numpy()] * 2),
        "elo_after": np.concatenate([enriched["home_elo_after"].to_numpy(dtype=float),
                                     enriched["away_elo_after"].to_numpy(dtype=float)]),
    }).sort_values(["seq", "side"], kind="mergesort")


def domestic_league_map(enriched: pd.DataFrame) -> Dict[str, str]:
    """team -> league of its latest domestic (non-CL) match."""
    if enriched.empty:
        return {}
    lg = _long(enriched)
    lg = lg.loc[lg["league"].isin(DOMESTIC_LEAGUES)]
    return lg.groupby("team", sort=False)["league"].last().to_dict()


def latest_ratings(enriched: pd.DataFrame) -> Dict[str, float]:
    """team -> rating after its latest match."""
    if enriched.empty:
        return {}
    return _long(enriched).groupby("team", sort=False)["elo_after"].last().to_dict()


def latest_domestic_league(tm: pd.DataFrame) -> Optional[str]:
    """League of the team's latest domestic match (``tm`` from ``team_matches``)."""
    dom = tm.loc[tm["league"].isin(DOMESTIC_LEAGUES), "league"]
    return str(dom.iloc[-1]) if len(dom) else None


def resolve_league(table_league: Optional[str], history_league: Optional[str]) -> Optional[str]:
    """``teams.league`` when it is a domestic league, else the history one, else None."""
    if table_league in DOMESTIC_LEAGUES:
        return table_league
    if history_league in DOMESTIC_LEAGUES:
        return history_league
    return None


def team_index(table_rows: Iterable, enriched: pd.DataFrame) -> List[dict]:
    """All known teams with their league, sorted by league then name (null league last)."""
    table = {name: lg for name, lg in table_rows}
    hist = domestic_league_map(enriched)
    names = set(table) | known_teams(enriched)
    out = [{"name": n, "league": resolve_league(table.get(n), hist.get(n))} for n in names]
    out.sort(key=lambda t: (t["league"] is None, t["league"] or "", t["name"]))
    return out


# ---------------------------------------------------------------------------
# Profile pieces (each takes the team's matches from team_matches)
# ---------------------------------------------------------------------------
def form_summary(tm: pd.DataFrame, n: int = FORM_N) -> dict:
    last = tm.tail(n)
    k = len(last)
    if not k:
        return {"last5": "", "pts_pg": None, "n": 0}
    pts = last["result"].map({"W": 3, "D": 1, "L": 0})
    return {"last5": "".join(last["result"]), "pts_pg": _r(pts.mean(), 3), "n": int(k)}


def _record(rows: pd.DataFrame) -> dict:
    res = rows["result"]
    return {
        "played": int(len(rows)), "w": int((res == "W").sum()), "d": int((res == "D").sum()),
        "l": int((res == "L").sum()), "gf": int(rows["gf"].sum()), "ga": int(rows["ga"].sum()),
    }


def season_summary(tm: pd.DataFrame) -> Optional[dict]:
    """Domestic league record (overall / home / away) for the season of the latest domestic match."""
    dom = tm.loc[tm["league"].isin(DOMESTIC_LEAGUES)]
    if dom.empty:
        return None
    lg, season = dom["league"].iloc[-1], int(dom["season"].iloc[-1])
    rows = dom.loc[(dom["league"] == lg) & (dom["season"] == season)]
    rec = _record(rows)
    return {
        "season": season, **rec, "pts": 3 * rec["w"] + rec["d"],
        "home": _record(rows.loc[rows["venue"] == "home"]),
        "away": _record(rows.loc[rows["venue"] == "away"]),
    }


def averages_summary(tm: pd.DataFrame, n: int = AVERAGES_N) -> dict:
    last = tm.tail(n)
    k = len(last)
    shots = last.loc[last["shots_for"].notna() & last["shots_against"].notna()]
    ks = len(shots)
    out = {"n": int(k), "n_shots": int(ks)}

    def mean(s) -> Optional[float]:
        s = s.dropna()
        return _r(s.mean(), 3) if len(s) else None

    if k:
        out.update({
            "goals_for": _r(last["gf"].mean(), 3),
            "goals_against": _r(last["ga"].mean(), 3),
        })
    else:
        out.update({"goals_for": None, "goals_against": None})
    out.update({
        "shots_for": mean(shots["shots_for"]) if ks else None,
        "shots_against": mean(shots["shots_against"]) if ks else None,
        "sot_for": mean(shots["sot_for"]) if ks else None,
        "sot_against": mean(shots["sot_against"]) if ks else None,
    })
    if k:
        out.update({
            "clean_sheet_rate": _r((last["ga"] == 0).mean(), 3),
            "btts_rate": _r(((last["gf"] > 0) & (last["ga"] > 0)).mean(), 3),
            "over25_rate": _r(((last["gf"] + last["ga"]) >= 3).mean(), 3),
        })
    else:
        out.update({"clean_sheet_rate": None, "btts_rate": None, "over25_rate": None})
    return out


def league_rank(enriched: pd.DataFrame, team: str, league: Optional[str]):
    """``(rank, league_size)`` by current rating among teams whose latest domestic
    league is ``league`` and that played in that league's most recent season."""
    if league is None or enriched.empty:
        return None, None
    in_league = enriched.loc[enriched["league"] == league]
    if in_league.empty:
        return None, 0
    latest = in_league["season"].max()
    cur = in_league.loc[in_league["season"] == latest]
    players = set(cur["home_team"]).union(cur["away_team"])
    lg_map = domestic_league_map(enriched)
    ratings = latest_ratings(enriched)
    pool = sorted((t for t in players if lg_map.get(t) == league), key=lambda t: (-ratings[t], t))
    rank = pool.index(team) + 1 if team in pool else None
    return rank, len(pool)


def elo_summary(enriched: pd.DataFrame, tm: pd.DataFrame, team: str, league: Optional[str]) -> dict:
    rank, size = league_rank(enriched, team, league)
    if tm.empty:
        return {"rating": None, "rank_in_league": rank, "league_size": size, "change_last_5": None}
    last = tm.tail(FORM_N)
    return {
        "rating": _r(tm["elo_after"].iloc[-1], 1),
        "rank_in_league": rank,
        "league_size": size,
        "change_last_5": _r(last["elo_after"].iloc[-1] - last["elo_before"].iloc[0], 1),
    }


def _iso(day) -> str:
    return pd.Timestamp(day).date().isoformat()


def build_profile(
    enriched: pd.DataFrame,
    team: str,
    league: Optional[str],
    *,
    as_of: Optional[dt.date],
    today: dt.date,
) -> dict:
    """``GET /teams/{name}`` body without ``next_fixture`` (strictly before ``as_of``)."""
    hist = before_day(enriched, as_of)
    tm = team_matches(hist, team)
    last_day = pd.Timestamp(tm["day"].iloc[-1]).date() if len(tm) else None
    ref = as_of or today
    return {
        "name": team,
        "league": league,
        "as_of": as_of.isoformat() if as_of else None,
        "elo": elo_summary(hist, tm, team, league),
        "form": form_summary(tm),
        "season": season_summary(tm),
        "averages": averages_summary(tm),
        "rest_days": (ref - last_day).days if last_day else None,
        "last_match_date": last_day.isoformat() if last_day else None,
    }


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------
def _int_or_none(x) -> Optional[int]:
    v = _r(x, 0)
    return int(v) if v is not None else None


def match_list(tm: pd.DataFrame, *, limit: int, venue: str = "all") -> List[dict]:
    """Newest first, all competitions; ``venue`` in all|home|away."""
    rows = tm if venue == "all" else tm.loc[tm["venue"] == venue]
    rows = rows.iloc[::-1].head(limit)
    return [{
        "date": _iso(r.day), "league": r.league, "season": int(r.season), "venue": r.venue,
        "opponent": r.opponent, "gf": int(r.gf), "ga": int(r.ga), "result": r.result,
        "shots_for": _int_or_none(r.shots_for), "shots_against": _int_or_none(r.shots_against),
        "sot_for": _int_or_none(r.sot_for), "sot_against": _int_or_none(r.sot_against),
        "elo_before": _r(r.elo_before, 1), "elo_after": _r(r.elo_after, 1),
    } for r in rows.itertuples(index=False)]


def elo_points(tm: pd.DataFrame, since: dt.date) -> List[dict]:
    """Post-match rating for every match on/after ``since``, ascending."""
    rows = tm.loc[tm["day"] >= _ts(since)]
    return [{"date": _iso(r.day), "elo": _r(r.elo_after, 1), "opponent": r.opponent, "result": r.result}
            for r in rows.itertuples(index=False)]


def h2h_summary(enriched: pd.DataFrame, a: str, b: str, *, limit: int) -> dict:
    """All finished meetings of ``a`` and ``b`` (any venue / competition)."""
    out = {"a": a, "b": b, "n": 0, "a_wins": 0, "draws": 0, "b_wins": 0,
           "a_goals": 0, "b_goals": 0, "meetings": []}
    if enriched.empty:
        return out
    h, w = enriched["home_team"], enriched["away_team"]
    m = enriched.loc[((h == a) & (w == b)) | ((h == b) & (w == a))]
    if m.empty:
        return out
    a_home = (m["home_team"] == a).to_numpy()
    ag = np.where(a_home, m["home_goals"], m["away_goals"])
    bg = np.where(a_home, m["away_goals"], m["home_goals"])
    out.update({
        "n": int(len(m)), "a_wins": int((ag > bg).sum()), "draws": int((ag == bg).sum()),
        "b_wins": int((ag < bg).sum()), "a_goals": int(ag.sum()), "b_goals": int(bg.sum()),
        "meetings": [{
            "date": _iso(r.day), "league": r.league, "home_team": r.home_team, "away_team": r.away_team,
            "home_goals": int(r.home_goals), "away_goals": int(r.away_goals),
        } for r in m.iloc[::-1].head(limit).itertuples(index=False)],
    })
    return out
