import os
import pickle
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss, confusion_matrix
import mlflow
import mlflow.sklearn
import mlflow.xgboost
import optuna
import xgboost as xgb

optuna.logging.set_verbosity(optuna.logging.WARNING)

FEATURES_PATH = os.path.join("data", "processed", "features.csv")
ARTIFACTS_DIR = os.path.join("src", "model", "artifacts")
BASELINE_PATH = os.path.join(ARTIFACTS_DIR, "baseline.pkl")
XGB_PATH = os.path.join(ARTIFACTS_DIR, "xgb_best.pkl")
EXPERIMENT_NAME = "football-predictor"
N_TRIALS = 50

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


def load_data(path: str = None):
    if path is None:
        path = FEATURES_PATH
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


def save_model(model, path: str = None):
    if path is None:
        path = BASELINE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(model, f)


def train_xgboost(train: pd.DataFrame, test: pd.DataFrame, n_trials: int = N_TRIALS):
    X_train_full = train[FEATURE_COLS].values
    y_train_full = train[TARGET_COL].values
    X_test = test[FEATURE_COLS].values
    y_test = test[TARGET_COL].values

    val_cut = int(len(X_train_full) * 0.8)
    X_tr, X_val = X_train_full[:val_cut], X_train_full[val_cut:]
    y_tr, y_val = y_train_full[:val_cut], y_train_full[val_cut:]

    def objective(trial):
        params = {
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "objective": "multi:softprob",
            "num_class": 3,
            "eval_metric": "mlogloss",
            "random_state": 42,
            "verbosity": 0,
        }
        clf = xgb.XGBClassifier(**params)
        clf.fit(X_tr, y_tr)
        proba = clf.predict_proba(X_val)
        return log_loss(y_val, proba)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials)

    best_params = study.best_params
    best_params.update(
        {
            "objective": "multi:softprob",
            "num_class": 3,
            "eval_metric": "mlogloss",
            "random_state": 42,
            "verbosity": 0,
        }
    )
    model = xgb.XGBClassifier(**best_params)
    model.fit(X_train_full, y_train_full)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)
    acc = accuracy_score(y_test, y_pred)
    ll = log_loss(y_test, y_proba)
    cm = confusion_matrix(y_test, y_pred)

    return model, best_params, acc, ll, cm


def main():
    df = load_data()
    train, test = split_by_date(df)

    mlflow.set_experiment(EXPERIMENT_NAME)
    with mlflow.start_run(run_name="baseline_logistic_regression"):
        model, acc_bl, ll_bl, cm_bl = train_baseline(train, test)

        mlflow.log_param("model_type", "LogisticRegression")
        mlflow.log_param("max_iter", 1000)
        mlflow.log_param("train_size", len(train))
        mlflow.log_param("test_size", len(test))
        mlflow.log_metric("accuracy", acc_bl)
        mlflow.log_metric("log_loss", ll_bl)
        mlflow.sklearn.log_model(model, "baseline_model")

        save_model(model)

    print(f"\n[Baseline] Accuracy={acc_bl:.4f}  Log-Loss={ll_bl:.4f}")
    print(f"Confusion Matrix:\n{cm_bl}")
    print(f"Model saved to {BASELINE_PATH}")

    print(f"\nRunning Optuna search ({N_TRIALS} trials) …")
    with mlflow.start_run(run_name="xgboost_optuna"):
        xgb_model, best_params, acc_xgb, ll_xgb, cm_xgb = train_xgboost(train, test)

        for k, v in best_params.items():
            mlflow.log_param(k, v)
        mlflow.log_param("train_size", len(train))
        mlflow.log_param("test_size", len(test))
        mlflow.log_metric("accuracy", acc_xgb)
        mlflow.log_metric("log_loss", ll_xgb)
        mlflow.xgboost.log_model(xgb_model, "xgb_model")

        save_model(xgb_model, XGB_PATH)

    print(f"[XGBoost]  Accuracy={acc_xgb:.4f}  Log-Loss={ll_xgb:.4f}")
    print(f"Confusion Matrix:\n{cm_xgb}")
    print(f"Model saved to {XGB_PATH}")

    print("\n--- Comparison ---")
    print(f"{'Model':<25} {'Accuracy':>10} {'Log-Loss':>10}")
    print("-" * 47)
    print(f"{'LogisticRegression':<25} {acc_bl:>10.4f} {ll_bl:>10.4f}")
    print(f"{'XGBoost (Optuna)':<25} {acc_xgb:>10.4f} {ll_xgb:>10.4f}")


if __name__ == "__main__":
    main()
