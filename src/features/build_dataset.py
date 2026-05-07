import os
import pandas as pd
from src.database import SessionLocal
from src.models import Match
from src.features.form import compute_form_features
from src.features.h2h import compute_h2h_features

OUTPUT_PATH = os.path.join("data", "processed", "features.csv")

RESULT_MAP = {"H": 0, "D": 1, "A": 2}


def build_dataset(db_session=None) -> pd.DataFrame:
    close_session = db_session is None
    if db_session is None:
        db_session = SessionLocal()

    try:
        form_df = compute_form_features(db_session)
        h2h_df = compute_h2h_features(db_session)

        raw = (
            db_session.query(Match)
            .filter(Match.home_goals != None)  # noqa: E711
            .order_by(Match.date)
            .all()
        )
        matches_df = pd.DataFrame(
            [
                {
                    "match_id": m.id,
                    "date": m.date,
                    "home_team": m.home_team,
                    "away_team": m.away_team,
                    "result": m.result,
                    "season": m.season,
                }
                for m in raw
            ]
        )
    finally:
        if close_session:
            db_session.close()

    df = matches_df.merge(form_df, on="match_id").merge(h2h_df, on="match_id")
    df["target"] = df["result"].map(RESULT_MAP)
    df = df.drop(columns=["result"])
    df = df.dropna()
    return df


def main():
    os.makedirs(os.path.join("data", "processed"), exist_ok=True)
    df = build_dataset()
    df.to_csv(OUTPUT_PATH, index=False)

    total = len(df)
    dist = df["target"].value_counts().sort_index()
    labels = {0: "Home Win", 1: "Draw", 2: "Away Win"}
    print(f"Saved {total} rows to {OUTPUT_PATH}")
    print("\nClass distribution:")
    for code, count in dist.items():
        pct = count / total * 100
        print(f"  {labels[code]} ({code}): {count} ({pct:.1f}%)")


if __name__ == "__main__":
    main()
