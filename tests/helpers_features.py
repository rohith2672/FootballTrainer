"""Synthetic multi-league, multi-season match generator for the feature tests."""
import numpy as np
import pandas as pd


def make_league_matches(
    leagues=("PL",),
    seasons=(2018, 2019, 2020),
    n_teams=8,
    seed=0,
    spread=0.45,
    with_shots=False,
    with_cl=False,
    start_id=1,
):
    """Double round-robin per league-season, Aug-May, results drawn from latent strengths.

    Team strengths are persistent across seasons so Elo / form carry real signal.
    With ``with_cl`` a few cross-league games per season are added (league 'CL').
    """
    rng = np.random.default_rng(seed)
    strength = {}
    rows = []
    mid = start_id
    for season in seasons:
        season_rows = []
        for lg in leagues:
            names = [f"{lg}_T{t}" for t in range(n_teams)]
            for t in names:
                strength.setdefault(t, rng.normal(0.0, spread))
            # circle-method round robin, then the reverse fixtures
            order = list(names)
            rounds = []
            for _ in range(n_teams - 1):
                rounds.append([(order[i], order[n_teams - 1 - i]) for i in range(n_teams // 2)])
                order = [order[0]] + [order[-1]] + order[1:-1]
            rounds = rounds + [[(b, a) for a, b in r] for r in rounds]
            start = pd.Timestamp(f"{season}-08-10")
            for md, fixtures in enumerate(rounds):
                day = start + pd.Timedelta(days=7 * md)
                for h, a in fixtures:
                    season_rows.append((day, lg, h, a))
        if with_cl and len(leagues) > 1:
            first = [f"{lg}_T0" for lg in leagues]
            second = [f"{lg}_T1" for lg in leagues]
            for k in range(len(first)):
                for j, (h, a) in enumerate([(first[k], second[(k + 1) % len(first)]),
                                            (second[(k + 1) % len(first)], first[k])]):
                    season_rows.append((pd.Timestamp(f"{season}-09-20") + pd.Timedelta(days=14 * j), "CL", h, a))
        for day, lg, h, a in season_rows:
            lam_h = np.exp(0.25 + strength[h] - strength[a])
            lam_a = np.exp(strength[a] - strength[h])
            hg, ag = int(rng.poisson(lam_h)), int(rng.poisson(lam_a))
            row = {
                "id": mid, "date": day, "kickoff": pd.NaT, "league": lg, "season": season,
                "home_team": h, "away_team": a, "home_goals": hg, "away_goals": ag,
                "result": "H" if hg > ag else ("D" if hg == ag else "A"),
            }
            if with_shots and lg != "CL":
                row["home_shots"] = int(rng.poisson(10 + 3 * hg))
                row["away_shots"] = int(rng.poisson(8 + 3 * ag))
                row["home_shots_on_target"] = int(rng.poisson(3 + hg))
                row["away_shots_on_target"] = int(rng.poisson(2 + ag))
            mid += 1
            rows.append(row)
    df = pd.DataFrame(rows)
    return df.sort_values(["date", "league", "home_team", "away_team", "id"]).reset_index(drop=True)


def match_row(id_, date, home, away, hg, ag, league="PL", season=None, **extra):
    """One match dict for hand-built scenarios (hg/ag None = fixture to predict)."""
    date = pd.Timestamp(date)
    row = {
        "id": id_, "date": date, "league": league,
        "season": season if season is not None else (date.year if date.month >= 7 else date.year - 1),
        "home_team": home, "away_team": away, "home_goals": hg, "away_goals": ag,
    }
    row.update(extra)
    return row


def frame(*rows):
    df = pd.DataFrame(list(rows))
    for col in ("home_goals", "away_goals"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
