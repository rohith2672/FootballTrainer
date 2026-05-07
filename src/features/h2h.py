import pandas as pd
from src.models import Match


def _compute_h2h_from_matches(matches: list[dict]) -> pd.DataFrame:
    # h2h_history keyed by canonical pair (team_a, team_b) alphabetically sorted
    # stores result from perspective of the home team in each meeting
    h2h_history: dict[tuple[str, str], list[str]] = {}
    # home_results[(team, season)] = list of "W"/"L"/"D" for home games
    home_results: dict[tuple[str, int], list[str]] = {}
    # away_results[(team, season)] = list of "W"/"L"/"D" for away games
    away_results: dict[tuple[str, int], list[str]] = {}
    # last match date per team
    last_match: dict[str, object] = {}

    rows = []

    for m in matches:
        home = m["home_team"]
        away = m["away_team"]
        result = m["result"]
        season = m["season"]
        date = m["date"]

        # --- H2H ---
        # Store (home_in_meeting, result) tuples so we can correctly attribute wins
        # to the current home team regardless of which side they played in prior meetings.
        pair = (min(home, away), max(home, away))
        h2h = h2h_history.get(pair, [])
        if len(h2h) < 5:
            h2h_home_win_rate = 0.0
        else:
            last5 = h2h[-5:]
            wins = sum(
                1 for (meeting_home, r) in last5
                if (meeting_home == home and r == "H") or (meeting_home == away and r == "A")
            )
            h2h_home_win_rate = wins / 5

        # --- Home win rate (current season, prior home games) ---
        home_key = (home, season)
        prior_home = home_results.get(home_key, [])
        if not prior_home:
            home_team_home_win_rate = 0.0
        else:
            home_team_home_win_rate = sum(1 for r in prior_home if r == "W") / len(prior_home)

        # --- Away win rate (current season, prior away games) ---
        away_key = (away, season)
        prior_away = away_results.get(away_key, [])
        if not prior_away:
            away_team_away_win_rate = 0.0
        else:
            away_team_away_win_rate = sum(1 for r in prior_away if r == "W") / len(prior_away)

        # --- Days since last match ---
        nan = float("nan")
        if home in last_match:
            home_days_since_last = (date - last_match[home]).days
        else:
            home_days_since_last = nan

        if away in last_match:
            away_days_since_last = (date - last_match[away]).days
        else:
            away_days_since_last = nan

        rows.append({
            "match_id": m["id"],
            "h2h_home_win_rate": h2h_home_win_rate,
            "home_team_home_win_rate": home_team_home_win_rate,
            "away_team_away_win_rate": away_team_away_win_rate,
            "home_days_since_last": home_days_since_last,
            "away_days_since_last": away_days_since_last,
        })

        # --- Update state AFTER recording features (no leakage) ---
        # H2H: store (home_team, result) so future lookups can reconstruct correct win attribution
        h2h_history.setdefault(pair, []).append((home, result))

        # Home/away win rates
        if result == "H":
            home_results.setdefault(home_key, []).append("W")
            away_results.setdefault(away_key, []).append("L")
        elif result == "A":
            home_results.setdefault(home_key, []).append("L")
            away_results.setdefault(away_key, []).append("W")
        else:
            home_results.setdefault(home_key, []).append("D")
            away_results.setdefault(away_key, []).append("D")

        last_match[home] = date
        last_match[away] = date

    return pd.DataFrame(rows, columns=[
        "match_id",
        "h2h_home_win_rate",
        "home_team_home_win_rate",
        "away_team_away_win_rate",
        "home_days_since_last",
        "away_days_since_last",
    ])


def compute_h2h_features(db_session) -> pd.DataFrame:
    raw = (
        db_session.query(Match)
        .filter(Match.home_goals != None)  # noqa: E711
        .order_by(Match.date)
        .all()
    )
    matches = [
        {
            "id": m.id,
            "date": m.date,
            "home_team": m.home_team,
            "away_team": m.away_team,
            "home_goals": m.home_goals,
            "away_goals": m.away_goals,
            "result": m.result,
            "season": m.season,
        }
        for m in raw
    ]
    return _compute_h2h_from_matches(matches)
