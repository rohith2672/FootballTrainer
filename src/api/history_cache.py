"""In-process caches derived from finished-match history.

* History (TTL 300 s) plus its Elo replay and a lazily derived
  ``team_stats.HistoryIndex`` (long frame, known teams, league map, ratings).
  Shared by ``/upcoming`` and the team endpoints. One entry for the whole
  process, guarded by a lock: concurrent requests after expiry share one DB
  load. Failed loads raise and leave nothing cached. The cached frames are
  shared between requests, so callers must treat them as read-only.
* Per-key next-fixture results of ``GET /teams/{name}`` (TTL 120 s for real
  answers, 30 s for ``"unavailable"`` so a transient upstream failure
  recovers). Separate lock; values are computed by the caller OUTSIDE any lock
  (the pipeline itself takes ``_lock``), so concurrent misses may compute twice.

``invalidate()`` drops everything.
"""
import copy
import threading
import time
from typing import Any, Optional

import pandas as pd

from src.api import store, team_stats

TTL_SECONDS = 300.0
FIXTURE_TTL_SECONDS = 120.0
FIXTURE_UNAVAILABLE_TTL_SECONDS = 30.0
_now = time.monotonic          # patched by tests

_lock = threading.Lock()
_entry: Optional[dict] = None  # {"loaded_at", "history", "enriched", "index"}

_fixture_lock = threading.Lock()
_fixtures: dict = {}           # key -> (expires_at, value)
_generation = 0                # bumped by invalidate(); stale computations are not stored


def _fresh_entry(db) -> dict:
    """Current entry, reloading history when missing or expired. Caller holds ``_lock``."""
    global _entry
    if _entry is None or _now() - _entry["loaded_at"] >= TTL_SECONDS:
        history = store.load_history(db)      # module attribute: tests monkeypatch it
        _entry = {"loaded_at": _now(), "history": history, "enriched": None, "index": None}
    return _entry


def get_history(db) -> pd.DataFrame:
    """Finished-match history (``store.load_history`` shape), cached for ``TTL_SECONDS``."""
    with _lock:
        return _fresh_entry(db)["history"]


def _enriched_of(entry: dict) -> pd.DataFrame:
    if entry["enriched"] is None:
        entry["enriched"] = team_stats.replay_elo(entry["history"])
    return entry["enriched"]


def get_enriched(db) -> pd.DataFrame:
    """``team_stats.replay_elo`` of the cached history; rebuilt with the history."""
    with _lock:
        return _enriched_of(_fresh_entry(db))


def get_index(db) -> "team_stats.HistoryIndex":
    """``HistoryIndex`` over the cached replay (``index.enriched``); rebuilt with the history.

    Its properties are computed lazily on first use and then reused by later
    requests until the history entry is replaced.
    """
    with _lock:
        entry = _fresh_entry(db)
        if entry["index"] is None:
            entry["index"] = team_stats.HistoryIndex(_enriched_of(entry))
        return entry["index"]


# ---------------------------------------------------------------------------
# Next-fixture results (per key)
# ---------------------------------------------------------------------------
def fixture_generation() -> int:
    """Token to pass to :func:`fixture_put`; an ``invalidate()`` in between voids the put."""
    with _fixture_lock:
        return _generation


def fixture_get(key) -> Optional[Any]:
    """Deep copy of the cached value for ``key``, or None when missing / expired."""
    with _fixture_lock:
        hit = _fixtures.get(key)
        if hit is None:
            return None
        if _now() >= hit[0]:
            del _fixtures[key]
            return None
        return copy.deepcopy(hit[1])


def fixture_put(key, value, ttl: float, generation: int) -> None:
    with _fixture_lock:
        if generation != _generation:
            return
        _fixtures[key] = (_now() + ttl, copy.deepcopy(value))


def invalidate() -> None:
    """Drop the cached history, replay, index and next-fixture results (tests; after an ingest)."""
    global _entry, _generation
    with _lock:
        _entry = None
    with _fixture_lock:
        _fixtures.clear()
        _generation += 1
