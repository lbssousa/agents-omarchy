#!/usr/bin/env python3
"""Keep the Gemini weekly limit that Omarchy's Antigravity collector can't see.

omarchy-agent-usage-agy reads Gemini's limits from Cloud Code's
retrieveUserQuotaSummary, which (on Pro, as on Ultra) lists only the Claude
and GPT group, so it falls back to retrieveUserQuota, which only has the
5-hour buckets. The agy CLI still reports the weekly one in `agy -p /usage`:

  Gemini Models<TAB>Weekly Limit Remaining<TAB>96%<TAB>2026-12-03T20:01:20Z

This writes that row, as a limit shaped like the collector's own, to a file
the panel merges into the agy record in memory. agy.json is never touched,
so whatever else rewrites it can't drop the weekly limit.
"""

import json
import os
import subprocess
import sys
import time

STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "omarchy", "agents")
OUT = os.path.join(STATE, "lbssousa.agents", "gemini-weekly.json")
RECORD = os.path.join(STATE, "usage", "agy.json")

# A panel opened and shut repeatedly mustn't run agy on every flick.
MAX_AGE_MS = 60 * 1000


def now_ms():
    return int(time.time() * 1000)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def weekly_row(output):
    for line in output.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 4:
            continue
        group, name, remaining, reset = parts[:4]
        if "gemini" not in group.lower() or "week" not in name.lower():
            continue
        try:
            left = float(remaining.strip().rstrip("%")) / 100.0
        except ValueError:
            return None
        return max(0.0, min(1.0, left)), reset.strip()
    return None


def main():
    force = "--force" in sys.argv[1:]
    kept = read_json(OUT)
    if not force and now_ms() - int(kept.get("fetchedAt") or 0) < MAX_AGE_MS:
        return 0

    try:
        output = subprocess.run(
            ["agy", "-p", "/usage"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return 1
    row = weekly_row(output)
    if row is None:
        return 1
    left, reset = row
    used = round(1.0 - left, 4)

    data = {
        "fetchedAt": now_ms(),
        # The account the agy record names now, so another Google account's
        # weekly never stands in for this one.
        "accountName": str(read_json(RECORD).get("accountName") or ""),
        "limit": {
            "label": "Weekly (7-day)",
            "title": "Weekly",
            "percent": used,
            # An untouched window reports a reset a whole week from now that
            # slides forward on every query; like the collector does for
            # Gemini's untouched 5-hour buckets, it gets no reset at all.
            "resetsAt": reset if used > 0 else "",
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
