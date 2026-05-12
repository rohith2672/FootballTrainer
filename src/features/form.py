import pandas as pd
from src.models import Match


def _team_form(history: list[dict], n: int = 5) -> dict:
    recent = history[-n:]
    pts_pg = sum(e["pts"] for e in recent) / len(recent)
    goals_scored_avg = sum(e["goals_for"] for e in recent) / len(recent)
    goals_conceded_avg = sum(e["goals_against"] for e in recent) / len(recent)
    return {
        "pts_pg": pts_pg,
        "goals_scored_avg": goals_scored_avg,
        "goals_conceded_avg": goals_conceded_avg,
    }


def _pts_for_result(team_side: str, result: str) -> int:
    if result == "D":
        return 1
    if (team_side == "home" and result == "H") or (team_side == "away" and result == "A"):
        return 3
    return 0


def _compute_form_from_matches(matches: list[dict]) -> pd.DataFrame:
    team_history: dict[str, list[dict]] = {}
    rows = []

    for m in matches:
        home = m["home_team"]
        away = m["away_team"]
        home_goals = m["home_goals"]
        away_goals = m["away_goals"]
        result = m["result"]

        home_history = team_history.get(home, [])
        away_history = team_history.get(away, [])

        nan = float("nan")
        if not home_history:
            home_form = {"pts_pg": nan, "goals_scored_avg": nan, "goals_conceded_avg": nan}
        else:
            home_form = _team_form(home_history)

        if not away_history:
            away_form = {"pts_pg": nan, "goals_scored_avg": nan, "goals_conceded_avg": nan}
        else:
            away_form = _team_form(away_history)

        rows.append(
            {
                "match_id": m["id"],
                "home_form_pts_pg": home_form["pts_pg"],
                "home_form_goals_scored_avg": home_form["goals_scored_avg"],
                "home_form_goals_conceded_avg": home_form["goals_conceded_avg"],
                "away_form_pts_pg": away_form["pts_pg"],
                "away_form_goals_scored_avg": away_form["goals_scored_avg"],
                "away_form_goals_conceded_avg": away_form["goals_conceded_avg"],
            }
        )

        team_history.setdefault(home, []).append(
            {"goals_for": home_goals, "goals_against": away_goals, "pts": _pts_for_result("home", result)}
        )
        team_history.setdefault(away, []).append(
            {"goals_for": away_goals, "goals_against": home_goals, "pts": _pts_for_result("away", result)}
        )

    return pd.DataFrame(rows, columns=[
        "match_id",
        "home_form_pts_pg",
        "home_form_goals_scored_avg",
        "home_form_goals_conceded_avg",
        "away_form_pts_pg",
        "away_form_goals_scored_avg",
        "away_form_goals_conceded_avg",
    ])


def compute_form_features(db_session) -> pd.DataFrame:
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
        }
        for m in raw
    ]
    return _compute_form_from_matches(matches)
