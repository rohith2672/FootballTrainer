"""Load the served model + its registry without ever crashing the API.

The API must start (and report 503 on /health, /predict, /upcoming) even when
the artifacts are missing, unreadable, or were trained with a different
feature layout. ``load_model_state`` therefore never raises.

Deliberately does NOT import ``src.model.train`` (heavy: xgboost / optuna /
mlflow); only ``src.features.columns`` for the canonical feature order.
"""
import json
import logging
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.features.columns import FEATURE_COLS

logger = logging.getLogger(__name__)

_ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "model" / "artifacts"
DEFAULT_MODEL_PATH = str(_ARTIFACTS_DIR / "best_model.pkl")
DEFAULT_REGISTRY_PATH = str(_ARTIFACTS_DIR / "model_registry.json")


@dataclass
class ModelState:
    model: Any = None
    registry: Optional[dict] = None
    version: Optional[str] = None
    error: Optional[str] = None           # why serving is disabled (None when ready)
    paths: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.model is not None


def artifact_paths() -> tuple:
    """(model path, registry path) from the environment, read at call time."""
    return (
        os.getenv("BEST_MODEL_PATH") or DEFAULT_MODEL_PATH,
        os.getenv("REGISTRY_PATH") or DEFAULT_REGISTRY_PATH,
    )


def model_version(registry: Optional[dict]) -> str:
    """``"<best_model>@<git commit or unknown> <trained date>"``."""
    reg = registry or {}
    name = reg.get("best_model") or "unknown"
    commit = reg.get("git_commit") or "unknown"
    trained = str(reg.get("trained_at") or "").strip()[:10]
    return f"{name}@{commit} {trained}".strip()


def _read_registry(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        reg = json.load(f)
    if not isinstance(reg, dict):
        raise ValueError("registry is not a JSON object")
    return reg


def load_model_state() -> ModelState:
    model_path, registry_path = artifact_paths()
    state = ModelState(paths={"model": model_path, "registry": registry_path})

    try:
        state.registry = _read_registry(registry_path)
        state.version = model_version(state.registry)
    except Exception as exc:
        logger.error("Model registry unavailable (%s): %s", registry_path, exc)
        state.error = f"Model registry unavailable: {exc}"
        return state

    layout = state.registry.get("feature_cols")
    if layout is None or list(layout) != list(FEATURE_COLS):
        logger.error(
            "Registry feature_cols do not match FEATURE_COLS (registry has %s columns, "
            "code expects %d); refusing to serve a model with a different feature layout.",
            "no" if layout is None else len(layout), len(FEATURE_COLS),
        )
        state.error = "Model was trained with a different feature layout; retrain required"
        return state

    try:
        with open(model_path, "rb") as f:
            state.model = pickle.load(f)
    except Exception as exc:
        logger.error("Could not load model %s: %s", model_path, exc)
        state.model = None
        state.error = f"Model could not be loaded: {exc}"
        return state

    if not hasattr(state.model, "predict_proba"):
        logger.error("Loaded object from %s has no predict_proba", model_path)
        state.model = None
        state.error = "Loaded model has no predict_proba"
        return state

    logger.info("Loaded model %s", state.version)
    return state
