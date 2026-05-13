import datetime
import json
import os
import pickle

import lightgbm as lgb
import mlflow
import mlflow.sklearn
import mlflow.xgboost
import numpy as np
import optuna
import pandas as pd
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, log_loss

optuna.logging.set_verbosity(optuna.logging.WARNING)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FEATURES_PATH = os.path.join("data", "processed", "features.csv")
ARTIFACTS_DIR = os.path.join("src", "model", "artifacts")
BASELINE_PATH = os.path.join(ARTIFACTS_DIR, "baseline.pkl")
XGB_PATH      = os.path.join(ARTIFACTS_DIR, "xgb_best.pkl")
LGBM_PATH     = os.path.join(ARTIFACTS_DIR, "lgbm_best.pkl")
ENSEMBLE_PATH  = os.path.join(ARTIFACTS_DIR, "ensemble.pkl")
BEST_MODEL_PATH = os.path.join(ARTIFACTS_DIR, "best_model.pkl")
REGISTRY_PATH  = os.path.join(ARTIFACTS_DIR, "model_registry.json")
EXPERIMENT_NAME = "football-predictor"
N_TRIALS = 50
DECAY_LAMBDA = 0.001

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


# ---------------------------------------------------------------------------
# Ensemble model (module-level so pickle can round-trip it from the API)
# ---------------------------------------------------------------------------
class EnsembleModel:
    def __init__(self, base_models, meta):
        self.base_models = base_models
        self.meta = meta

    def predict_proba(self, X):
        stack = np.hstack([m.predict_proba(X) for m in self.base_models])
        return self.meta.predict_proba(stack)

    def predict(self, X):
        return np.argmax(self.predict_proba(X), axis=1)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
def load_data(path: str = None):
    if path is None:
        path = FEATURES_PATH
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def split_by_date(df: pd.DataFrame, test_fraction: float = 0.2):
    cutoff_idx = int(len(df) * (1 - test_fraction))
    train = df.iloc[:cutoff_idx]
    test  = df.iloc[cutoff_idx:]
    return train, test


def save_model(model, path: str = None):
    if path is None:
        path = BASELINE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(model, f)


def compute_sample_weights(train_df: pd.DataFrame) -> np.ndarray:
    days = (train_df["date"] - train_df["date"].min()).dt.days.values.astype(float)
    weights = np.exp(DECAY_LAMBDA * days)
    weights = weights / weights.sum() * len(train_df)
    return weights


# ---------------------------------------------------------------------------
# Calibration — per-class isotonic regression (version-independent)
# ---------------------------------------------------------------------------
class CalibratedModel:
    def __init__(self, base_model, calibrators):
        self.base_model = base_model
        self.calibrators = calibrators  # list[IsotonicRegression], one per class

    def predict_proba(self, X):
        raw = self.base_model.predict_proba(X)
        cal = np.column_stack([
            self.calibrators[i].predict(raw[:, i]) for i in range(raw.shape[1])
        ])
        cal = np.clip(cal, 0, None)
        row_sums = cal.sum(axis=1, keepdims=True)
        row_sums = np.where(row_sums == 0, 1, row_sums)
        return cal / row_sums

    def predict(self, X):
        return np.argmax(self.predict_proba(X), axis=1)


def calibrate_model(model, X_cal, y_cal):
    raw = model.predict_proba(X_cal)
    n_classes = raw.shape[1]
    calibrators = []
    for i in range(n_classes):
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(raw[:, i], (np.asarray(y_cal) == i).astype(int))
        calibrators.append(iso)
    return CalibratedModel(model, calibrators)


# ---------------------------------------------------------------------------
# Base model trainers
# ---------------------------------------------------------------------------
def train_baseline(train: pd.DataFrame, test: pd.DataFrame, sample_weight=None):
    X_train = train[FEATURE_COLS]
    y_train = train[TARGET_COL]
    X_test  = test[FEATURE_COLS]
    y_test  = test[TARGET_COL]

    model = LogisticRegression(max_iter=1000, solver="lbfgs")
    model.fit(X_train, y_train, sample_weight=sample_weight)

    y_pred  = model.predict(X_test)
    y_proba = model.predict_proba(X_test)
    acc = accuracy_score(y_test, y_pred)
    ll  = log_loss(y_test, y_proba)
    cm  = confusion_matrix(y_test, y_pred)

    return model, acc, ll, cm


def train_xgboost(
    train: pd.DataFrame,
    test: pd.DataFrame,
    sample_weight=None,
    n_trials: int = N_TRIALS,
):
    X_train_full = train[FEATURE_COLS].values
    y_train_full = train[TARGET_COL].values
    X_test = test[FEATURE_COLS].values
    y_test = test[TARGET_COL].values

    val_cut = int(len(X_train_full) * 0.8)
    X_tr, X_val = X_train_full[:val_cut], X_train_full[val_cut:]
    y_tr, y_val = y_train_full[:val_cut], y_train_full[val_cut:]

    def objective(trial):
        params = {
            "max_depth":    trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "subsample":    trial.suggest_float("subsample", 0.6, 1.0),
            "objective":    "multi:softprob",
            "num_class":    3,
            "eval_metric":  "mlogloss",
            "random_state": 42,
            "verbosity":    0,
        }
        clf = xgb.XGBClassifier(**params)
        w_tr = sample_weight[:val_cut] if sample_weight is not None else None
        clf.fit(X_tr, y_tr, sample_weight=w_tr)
        proba = clf.predict_proba(X_val)
        return log_loss(y_val, proba)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials)

    best_params = study.best_params
    best_params.update(
        {
            "objective":    "multi:softprob",
            "num_class":    3,
            "eval_metric":  "mlogloss",
            "random_state": 42,
            "verbosity":    0,
        }
    )
    model = xgb.XGBClassifier(**best_params)
    model.fit(X_train_full, y_train_full, sample_weight=sample_weight)

    y_pred  = model.predict(X_test)
    y_proba = model.predict_proba(X_test)
    acc = accuracy_score(y_test, y_pred)
    ll  = log_loss(y_test, y_proba)
    cm  = confusion_matrix(y_test, y_pred)

    return model, best_params, acc, ll, cm


def train_lgbm(
    train: pd.DataFrame,
    test: pd.DataFrame,
    sample_weight=None,
    n_trials: int = N_TRIALS,
):
    X_train_full = train[FEATURE_COLS].values
    y_train_full = train[TARGET_COL].values
    X_test = test[FEATURE_COLS].values
    y_test = test[TARGET_COL].values

    val_cut = int(len(X_train_full) * 0.8)
    X_tr, X_val = X_train_full[:val_cut], X_train_full[val_cut:]
    y_tr, y_val = y_train_full[:val_cut], y_train_full[val_cut:]

    def objective(trial):
        params = {
            "num_leaves":      trial.suggest_int("num_leaves", 20, 100),
            "learning_rate":   trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "n_estimators":    trial.suggest_int("n_estimators", 100, 500),
            "subsample":       trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "objective":       "multiclass",
            "num_class":       3,
            "metric":          "multi_logloss",
            "random_state":    42,
            "verbosity":       -1,
        }
        clf = lgb.LGBMClassifier(**params)
        w_tr = sample_weight[:val_cut] if sample_weight is not None else None
        clf.fit(X_tr, y_tr, sample_weight=w_tr)
        proba = clf.predict_proba(X_val)
        return log_loss(y_val, proba)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials)

    best_params = study.best_params
    best_params.update(
        {
            "objective":    "multiclass",
            "num_class":    3,
            "metric":       "multi_logloss",
            "random_state": 42,
            "verbosity":    -1,
        }
    )
    model = lgb.LGBMClassifier(**best_params)
    model.fit(X_train_full, y_train_full, sample_weight=sample_weight)

    y_pred  = model.predict(X_test)
    y_proba = model.predict_proba(X_test)
    acc = accuracy_score(y_test, y_pred)
    ll  = log_loss(y_test, y_proba)
    cm  = confusion_matrix(y_test, y_pred)

    save_model(model, LGBM_PATH)
    return model, best_params, acc, ll, cm


# ---------------------------------------------------------------------------
# Stacking ensemble
# ---------------------------------------------------------------------------
def train_stacking_ensemble(
    cal_lr, cal_xgb, cal_lgbm,
    X_val, y_val,
    X_test, y_test,
):
    base_models = [cal_lr, cal_xgb, cal_lgbm]
    stack_val  = np.hstack([m.predict_proba(X_val)  for m in base_models])
    stack_test = np.hstack([m.predict_proba(X_test) for m in base_models])

    meta = LogisticRegression(max_iter=500, solver="lbfgs")
    meta.fit(stack_val, y_val)

    ensemble = EnsembleModel(base_models, meta)

    y_pred  = ensemble.predict(X_test)
    y_proba = ensemble.predict_proba(X_test)
    acc = accuracy_score(y_test, y_pred)
    ll  = log_loss(y_test, y_proba)
    cm  = confusion_matrix(y_test, y_pred)

    return ensemble, acc, ll, cm


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------
def main():
    df = load_data()
    train, test = split_by_date(df)

    # Split train → train_base (80 %) + val_cal (20 %) for calibration
    base_cut   = int(len(train) * 0.8)
    train_base = train.iloc[:base_cut]
    val_cal    = train.iloc[base_cut:]

    X_val_df  = val_cal[FEATURE_COLS]
    y_val_arr = val_cal[TARGET_COL].values
    X_test    = test[FEATURE_COLS]
    y_test    = test[TARGET_COL]

    sample_weight = compute_sample_weights(train_base)

    mlflow.set_experiment(EXPERIMENT_NAME)

    # ------------------------------------------------------------------
    # 1. Logistic Regression baseline
    # ------------------------------------------------------------------
    with mlflow.start_run(run_name="baseline_logistic_regression"):
        lr_model, acc_bl, ll_bl, cm_bl = train_baseline(
            train_base, test, sample_weight=sample_weight
        )
        mlflow.log_param("model_type", "LogisticRegression")
        mlflow.log_param("max_iter", 1000)
        mlflow.log_param("train_size", len(train_base))
        mlflow.log_param("test_size", len(test))
        mlflow.log_metric("accuracy", acc_bl)
        mlflow.log_metric("log_loss", ll_bl)
        mlflow.sklearn.log_model(lr_model, "baseline_model")
        save_model(lr_model, BASELINE_PATH)

    print(f"\n[Baseline LR]  Accuracy={acc_bl:.4f}  Log-Loss={ll_bl:.4f}")
    print(f"Confusion Matrix:\n{cm_bl}")
    print(f"Model saved to {BASELINE_PATH}")

    # ------------------------------------------------------------------
    # 2. XGBoost with Optuna
    # ------------------------------------------------------------------
    print(f"\nRunning XGBoost Optuna search ({N_TRIALS} trials) ...")
    with mlflow.start_run(run_name="xgboost_optuna"):
        xgb_model, xgb_params, acc_xgb, ll_xgb, cm_xgb = train_xgboost(
            train_base, test, sample_weight=sample_weight
        )
        for k, v in xgb_params.items():
            mlflow.log_param(k, v)
        mlflow.log_param("train_size", len(train_base))
        mlflow.log_param("test_size", len(test))
        mlflow.log_metric("accuracy", acc_xgb)
        mlflow.log_metric("log_loss", ll_xgb)
        mlflow.xgboost.log_model(xgb_model, "xgb_model")
        save_model(xgb_model, XGB_PATH)

    print(f"[XGBoost]      Accuracy={acc_xgb:.4f}  Log-Loss={ll_xgb:.4f}")
    print(f"Confusion Matrix:\n{cm_xgb}")
    print(f"Model saved to {XGB_PATH}")

    # ------------------------------------------------------------------
    # 3. LightGBM with Optuna
    # ------------------------------------------------------------------
    print(f"\nRunning LightGBM Optuna search ({N_TRIALS} trials) ...")
    with mlflow.start_run(run_name="lgbm_optuna"):
        lgbm_model, lgbm_params, acc_lgbm, ll_lgbm, cm_lgbm = train_lgbm(
            train_base, test, sample_weight=sample_weight
        )
        for k, v in lgbm_params.items():
            mlflow.log_param(k, v)
        mlflow.log_param("train_size", len(train_base))
        mlflow.log_param("test_size", len(test))
        mlflow.log_metric("accuracy", acc_lgbm)
        mlflow.log_metric("log_loss", ll_lgbm)

    print(f"[LightGBM]     Accuracy={acc_lgbm:.4f}  Log-Loss={ll_lgbm:.4f}")
    print(f"Confusion Matrix:\n{cm_lgbm}")
    print(f"Model saved to {LGBM_PATH}")

    # ------------------------------------------------------------------
    # 4. Calibrate each base model on val_cal
    # ------------------------------------------------------------------
    print("\nCalibrating base models on validation set ...")
    cal_lr   = calibrate_model(lr_model,   X_val_df,        y_val_arr)
    cal_xgb  = calibrate_model(xgb_model,  X_val_df.values, y_val_arr)
    cal_lgbm = calibrate_model(lgbm_model, X_val_df.values, y_val_arr)

    # Evaluate calibrated models on test set (use .values for uniform input)
    X_test_vals = X_test.values
    y_test_vals = y_test.values

    cal_results = {}
    for name, model in [
        ("calibrated_lr",   cal_lr),
        ("calibrated_xgb",  cal_xgb),
        ("calibrated_lgbm", cal_lgbm),
    ]:
        y_proba = model.predict_proba(X_test_vals)
        y_pred  = model.predict(X_test_vals)
        cal_results[name] = {
            "model": model,
            "acc":   accuracy_score(y_test_vals, y_pred),
            "ll":    log_loss(y_test_vals, y_proba),
        }

    ll_cal_lr   = cal_results["calibrated_lr"]["ll"]
    ll_cal_xgb  = cal_results["calibrated_xgb"]["ll"]
    ll_cal_lgbm = cal_results["calibrated_lgbm"]["ll"]

    # ------------------------------------------------------------------
    # 5. Stacking ensemble
    # ------------------------------------------------------------------
    print("\nTraining stacking ensemble ...")
    ensemble, acc_ens, ll_ens, cm_ens = train_stacking_ensemble(
        cal_lr, cal_xgb, cal_lgbm,
        X_val_df.values, y_val_arr,
        X_test_vals,     y_test_vals,
    )
    save_model(ensemble, ENSEMBLE_PATH)
    print(f"[Ensemble]     Accuracy={acc_ens:.4f}  Log-Loss={ll_ens:.4f}")
    print(f"Confusion Matrix:\n{cm_ens}")
    print(f"Ensemble saved to {ENSEMBLE_PATH}")

    # ------------------------------------------------------------------
    # 6. Auto-select best model (all candidates including uncalibrated)
    # ------------------------------------------------------------------
    candidates = {
        "logistic_regression": (lr_model,   ll_bl),
        "xgboost":             (xgb_model,  ll_xgb),
        "lgbm":                (lgbm_model, ll_lgbm),
        "calibrated_lr":       (cal_lr,     ll_cal_lr),
        "calibrated_xgb":      (cal_xgb,    ll_cal_xgb),
        "calibrated_lgbm":     (cal_lgbm,   ll_cal_lgbm),
        "ensemble":            (ensemble,   ll_ens),
    }
    best_name = min(candidates, key=lambda k: candidates[k][1])
    best_model_obj, best_ll = candidates[best_name]
    save_model(best_model_obj, BEST_MODEL_PATH)

    registry = {
        "best_model": best_name,
        "log_loss":   round(float(best_ll), 6),
        "trained_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)

    print(f"\nBest model: {best_name}  (log-loss={best_ll:.4f})")
    print(f"Saved to {BEST_MODEL_PATH}")
    print(f"Registry written to {REGISTRY_PATH}")

    # ------------------------------------------------------------------
    # 7. Comparison table
    # ------------------------------------------------------------------
    print("\n--- Model Comparison ---")
    print(f"{'Model':<25} {'Accuracy':>10} {'Log-Loss':>10}")
    print("-" * 47)
    print(f"{'LogisticRegression':<25} {acc_bl:>10.4f} {ll_bl:>10.4f}")
    print(f"{'XGBoost (Optuna)':<25} {acc_xgb:>10.4f} {ll_xgb:>10.4f}")
    print(f"{'LightGBM (Optuna)':<25} {acc_lgbm:>10.4f} {ll_lgbm:>10.4f}")
    print(f"{'Calibrated LR':<25} {cal_results['calibrated_lr']['acc']:>10.4f} {ll_cal_lr:>10.4f}")
    print(f"{'Calibrated XGBoost':<25} {cal_results['calibrated_xgb']['acc']:>10.4f} {ll_cal_xgb:>10.4f}")
    print(f"{'Calibrated LightGBM':<25} {cal_results['calibrated_lgbm']['acc']:>10.4f} {ll_cal_lgbm:>10.4f}")
    print(f"{'Stacking Ensemble':<25} {acc_ens:>10.4f} {ll_ens:>10.4f}")


if __name__ == "__main__":
    main()
