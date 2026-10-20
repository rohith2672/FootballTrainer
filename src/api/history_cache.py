"""In-process cache of finished-match history (TTL 300 s) plus its Elo replay.

Shared by ``/upcoming`` and the team endpoints. One entry for the whole
process, guarded by a lock: concurrent requests after expiry share one DB load.
Failed loads raise and leave nothing cached. The cached frames are shared
between requests, so callers must treat them as read-only.
"""
import threading
import time
from typing import Optional

import pandas as pd

from src.api import store, team_stats

TTL_SECONDS = 300.0
_now = time.monotonic          # patched by tests

_lock = threading.Lock()
_entry: Optional[dict] = None  # {"loaded_at", "history", "enriched"}


def _fresh_entry(db) -> dict:
    """Current entry, reloading history when missing or expired. Caller holds ``_lock``."""
    global _entry
    if _entry is None or _now() - _entry["loaded_at"] >= TTL_SECONDS:
        history = store.load_history(db)      # module attribute: tests monkeypatch it
        _entry = {"loaded_at": _now(), "history": history, "enriched": None}
    return _entry


def get_history(db) -> pd.DataFrame:
    """Finished-match history (``store.load_history`` shape), cached for ``TTL_SECONDS``."""
    with _lock:
        return _fresh_entry(db)["history"]


def get_enriched(db) -> pd.DataFrame:
    """``team_stats.replay_elo`` of the cached history; rebuilt with the history."""
    with _lock:
        entry = _fresh_entry(db)
        if entry["enriched"] is None:
            entry["enriched"] = team_stats.replay_elo(entry["history"])
        return entry["enriched"]


def invalidate() -> None:
    """Drop the cached history and replay (tests; after an ingest)."""
    global _entry
    with _lock:
        _entry = None
