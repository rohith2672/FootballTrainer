#!/usr/bin/env python3
"""Claude Code status line: usage vs. expected usage for the 5h and 7d rate-limit windows.

Prints e.g.:  5h 42%/35% ▲ · 7d 61%/58% ≈
  used% / expected%   ▲ ahead of expected   ▼ under expected   ≈ on pace

Expected = the average of what you had used at this same point in your previous windows
(recorded in ~/.claude/usage-pace/history.json). Until a past window has been recorded, it
falls back to an even pace (straight line to 100% by the reset).

Needs a subscription: Claude Code only passes rate-limit figures to the status line there,
and only after the first response of a session.
"""
import json
import os
import sys
import time

DIR = os.path.join(os.path.expanduser("~"), ".claude", "usage-pace")
HIST = os.path.join(DIR, "history.json")
WINDOWS = (("five_hour", "5h", 5 * 3600), ("seven_day", "7d", 7 * 86400))
KEEP = 8  # past windows kept per kind
BUCKET = 600  # resets_at jitters by seconds; bucket to 10 min


def to_epoch(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) / 1000 if v > 1e11 else float(v)  # seconds (or ms)
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def load():
    try:
        with open(HIST) as f:
            return json.load(f)
    except Exception:
        return {}


def save(h):
    try:
        os.makedirs(DIR, exist_ok=True)
        tmp = HIST + ".tmp"
        with open(tmp, "w") as f:
            json.dump(h, f)
        os.replace(tmp, HIST)
    except OSError:
        pass


def expected_from_history(windows, current_key, frac):
    vals = []
    for key, samples in windows.items():
        if key == current_key:
            continue
        at = None
        for f, p in samples:
            if f <= frac:
                at = p
            else:
                break
        if at is not None:
            vals.append(at)
    return sum(vals) / len(vals) if vals else None


def main():
    # Windows consoles default to cp1252, which cannot encode the ▲ ▼ ≈ marks.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    limits = data.get("rate_limits") or {}
    now = time.time()
    hist = load()
    parts = []

    for kind, label, dur in WINDOWS:
        w = limits.get(kind) or {}
        used = w.get("used_percentage")
        end = to_epoch(w.get("resets_at"))
        if used is None or end is None:
            continue
        frac = min(1.0, max(0.0, (now - (end - dur)) / dur))
        key = str(int(round(end / BUCKET)))

        by_window = hist.setdefault(kind, {})
        samples = by_window.setdefault(key, [])
        if not samples or samples[-1][1] != used:
            samples.append([frac, used])
        for old in sorted(by_window, key=int)[:-KEEP]:
            del by_window[old]

        exp = expected_from_history(by_window, key, frac)
        basis_linear = exp is None
        if exp is None:
            exp = frac * 100
        mark = "▲" if used > exp + 2 else ("▼" if used < exp - 2 else "≈")
        parts.append("%s %.0f%%/%.0f%%%s %s" % (label, used, exp, "*" if basis_linear else "", mark))

    if parts:
        save(hist)
        print(" · ".join(parts))
    else:
        print("usage: waiting for first reading")


if __name__ == "__main__":
    main()
