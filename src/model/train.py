import os
import pickle
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss, confusion_matrix
import mlflow
import mlflow.sklearn

FEATURES_PATH = os.path.join("data", "processed", "features.csv")
ARTIFACTS_DIR = os.path.join("src", "model", "artifacts")
BASELINE_PATH = os.path.join(ARTIFACTS_DIR, "baseline.pkl")
EXPERIMENT_NAME = "football-predictor"

FEATURE_COLS = [
    "home_form_pts_pg",
    "home_form_goals_scored_avg",
    "home_form_goals_conceded_avg",
    "away_form_pts_pg",
    "away_form_goals_scored_avg",
    "away_form_goals_conceded_avg",
    "h2h_home_win_rate",
    "home_team_home_win_rate",
    "away_team_away_win_rate",
    "home_days_since_last",
    "away_days_since_last",
]
TARGET_COL = "target"


def load_data(path: str = FEATURES_PATH):
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def split_by_date(df: pd.DataFrame, test_fraction: float = 0.2):
    cutoff_idx = int(len(df) * (1 - test_fraction))
    train = df.iloc[:cutoff_idx]
    test = df.iloc[cutoff_idx:]
    return train, test


def train_baseline(train: pd.DataFrame, test: pd.DataFrame):
    X_train = train[FEATURE_COLS]
    y_train = train[TARGET_COL]
    X_test = test[FEATURE_COLS]
    y_test = test[TARGET_COL]

    model = LogisticRegression(max_iter=1000, solver="lbfgs")
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)

    acc = accuracy_score(y_test, y_pred)
    ll = log_loss(y_test, y_proba)
    cm = confusion_matrix(y_test, y_pred)

    return model, acc, ll, cm


def save_model(model, path: str = BASELINE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(model, f)


def main():
    df = load_data()
    train, test = split_by_date(df)

    mlflow.set_experiment(EXPERIMENT_NAME)
    with mlflow.start_run(run_name="baseline_logistic_regression"):
        model, acc, ll, cm = train_baseline(train, test)

        mlflow.log_param("model_type", "LogisticRegression")
        mlflow.log_param("max_iter", 1000)
        mlflow.log_param("train_size", len(train))
        mlflow.log_param("test_size", len(test))
        mlflow.log_metric("accuracy", acc)
        mlflow.log_metric("log_loss", ll)
        mlflow.sklearn.log_model(model, "baseline_model")

        save_model(model)

        print(f"Accuracy : {acc:.4f}")
        print(f"Log-Loss : {ll:.4f}")
        print(f"Confusion Matrix:\n{cm}")
        print(f"Model saved to {BASELINE_PATH}")


if __name__ == "__main__":
    main()
