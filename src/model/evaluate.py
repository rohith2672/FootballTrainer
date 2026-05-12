import os
import pickle
import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shap
from sklearn.metrics import accuracy_score, log_loss, confusion_matrix

from src.model.train import (
    FEATURE_COLS,
    TARGET_COL,
    XGB_PATH,
    load_data,
    split_by_date,
)

SHAP_PLOT_PATH = os.path.join("data", "processed", "shap_summary.png")
EVAL_REPORT_PATH = os.path.join("data", "processed", "eval_report.txt")


def load_model(path: str = XGB_PATH):
    with open(path, "rb") as f:
        return pickle.load(f)


def compute_shap_importance(model, X_test_df):
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test_df)

    # Handle both list-of-arrays (older shap) and 3D array (newer shap)
    if isinstance(shap_values, list):
        mean_abs = np.mean([np.abs(sv).mean(axis=0) for sv in shap_values], axis=0)
    else:
        mean_abs = np.abs(shap_values).mean(axis=(0, 2))

    return shap_values, mean_abs


def save_shap_plot(model, X_test_df, path: str = SHAP_PLOT_PATH):
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test_df)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    shap.summary_plot(shap_values, X_test_df, show=False)
    plt.savefig(path, bbox_inches="tight")
    plt.close()
    return shap_values


def save_eval_report(
    model_path, training_date, acc, ll, cm, feature_names, mean_abs_shap, path=EVAL_REPORT_PATH
):
    top10_idx = np.argsort(mean_abs_shap)[::-1][:10]
    top10 = [(feature_names[i], mean_abs_shap[i]) for i in top10_idx]

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("=== Football Predictor - Evaluation Report ===\n\n")
        f.write(f"Model:          {os.path.basename(model_path)}\n")
        f.write(f"Training date:  {training_date}\n\n")
        f.write(f"Test Accuracy:  {acc:.4f}\n")
        f.write(f"Test Log-Loss:  {ll:.4f}\n\n")
        f.write("Confusion Matrix (rows=actual, cols=predicted):\n")
        f.write("  Labels: 0=Home Win, 1=Draw, 2=Away Win\n")
        f.write(f"{cm}\n\n")
        f.write("Top 10 Features by Mean |SHAP|:\n")
        for rank, (feat, val) in enumerate(top10, 1):
            f.write(f"  {rank:2d}. {feat:<40s} {val:.4f}\n")

    return top10


def main():
    model = load_model()
    training_date = datetime.datetime.fromtimestamp(os.path.getmtime(XGB_PATH)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    df = load_data()
    _, test = split_by_date(df)
    X_test = test[FEATURE_COLS]
    y_test = test[TARGET_COL]

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)
    acc = accuracy_score(y_test, y_pred)
    ll = log_loss(y_test, y_proba)
    cm = confusion_matrix(y_test, y_pred)

    shap_values = save_shap_plot(model, X_test)

    # Compute mean abs SHAP for ranking (re-use cached shap_values)
    if isinstance(shap_values, list):
        mean_abs = np.mean([np.abs(sv).mean(axis=0) for sv in shap_values], axis=0)
    else:
        mean_abs = np.abs(shap_values).mean(axis=(0, 2))

    top10 = save_eval_report(XGB_PATH, training_date, acc, ll, cm, FEATURE_COLS, mean_abs)

    print(f"Accuracy:  {acc:.4f}")
    print(f"Log-Loss:  {ll:.4f}")
    print(f"\nConfusion Matrix:\n{cm}")
    print("\nTop 10 Features by Mean |SHAP|:")
    for rank, (feat, val) in enumerate(top10, 1):
        print(f"  {rank:2d}. {feat:<40s} {val:.4f}")

    print(f"\nSHAP plot saved to {SHAP_PLOT_PATH}")
    print(f"Eval report saved to {EVAL_REPORT_PATH}")


if __name__ == "__main__":
    main()
