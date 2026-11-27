#!/usr/bin/env python3
"""Keep the Gemini weekly limit that Omarchy's Antigravity collector can't see.

Google serves some accounts through AICode rather than Cloud Code (agy logs
"CCPA routed this account to AICode"). For those, the Cloud Code quota
summary omarchy-agent-usage-agy asks lists only the Claude and GPT group, so
it falls back to retrieveUserQuota, which only has Gemini's 5-hour buckets.
AICode's own summary has the weekly one too, in the same shape under
summary.response (omacom/omarchy#16906).

This asks AICode with the sign-in the collector itself would use, reads the
answer with the collector's own extract_limits(), and writes the Weekly limit
it finds to a file the panel merges into the agy record in memory. agy.json
is never touched, so whatever else rewrites it can't drop the weekly limit.
Accounts Cloud Code still serves in full already get their weekly limit from
the collector; the panel then ignores this file.
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import time
import urllib.request

STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "omarchy", "agents")
OUT = os.path.join(STATE, "lbssousa.agents", "gemini-weekly.json")
AICODE_SUMMARY = "https://aicode.googleapis.com/v1alpha/remote:getUserQuotaSummary"

# A panel opened and shut repeatedly mustn't ask Google on every flick.
MAX_AGE_MS = 60 * 1000


def now_ms():
    return int(time.time() * 1000)


def collector():
    """Omarchy's Antigravity collector as a module: its sign-in readers and
    its quota parser, so this file never disagrees with it on either."""
    path = shutil.which("omarchy-agent-usage-agy")
    if not path:
        return None
    loader = importlib.machinery.SourceFileLoader("omarchy_agent_usage_agy", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def weekly_limit(agy, token):
    request = urllib.request.Request(AICODE_SUMMARY, headers={"Authorization": f"Bearer {token}", "User-Agent": "antigravity"})
    data = agy.open_json(request, timeout=8)
    summary = data.get("summary") if isinstance(data, dict) else None
    limits = agy.extract_limits(summary.get("response") if isinstance(summary, dict) else None) or []
    return next((limit for limit in limits if limit.get("title") == "Weekly"), None)


def main():
    force = "--force" in sys.argv[1:]
    try:
        with open(OUT, encoding="utf-8") as f:
            kept = json.load(f)
    except (OSError, ValueError):
        kept = {}
    if not force and now_ms() - int(kept.get("fetchedAt") or 0) < MAX_AGE_MS:
        return 0

    try:
        agy = collector()
        if agy is None:
            return 1
        now = time.time()
        # The token refreshed most recently first, as the collector asks them.
        entries = sorted((e for e in agy.logins() if agy.token_fresh(e, now)), key=lambda e: -e["expiresAt"])
    except Exception:
        return 1

    for entry in entries:
        try:
            limit = weekly_limit(agy, entry["accessToken"])
        except Exception:
            continue
        if not limit:
            continue
        data = {
            "fetchedAt": now_ms(),
            # The account the collector names the record after, so another
            # Google account's weekly never stands in for this one.
            "accountName": str(entry.get("email") or ""),
            "limit": limit,
        }
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, OUT)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
