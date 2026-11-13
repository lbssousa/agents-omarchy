#!/usr/bin/env python3
"""Enrich ~/.local/state/omarchy/agents/usage/agy.json with real-time Antigravity quotas.

Parses agy -p "/usage" to obtain exact ground-truth quotas for:
- Gemini (Flash, Pro): Sessão, Semanal
- Gemini 4 Argon: Semanal
- Claude/GPT: Sessão, Semanal
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

# How long each window runs, from the description agy gives it.
SPANS = {"session": 5 * 3600, "weekly": 7 * 24 * 3600}

# A reset this close to a whole span away is the "now + span" agy reports for
# a window nobody has touched since it renewed.
IDLE_SLACK_SECONDS = 120


def window_idle(remaining, reset_time, kind):
    """Whether a window is renewed but not counting yet.

    agy never says so outright: an untouched window reports 100% left and a
    reset one whole span from now, which slides forward on every query. Its
    clock starts on the next use.
    """
    if remaining < 1.0:
        return False
    try:
        reset = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))
    except ValueError:
        return False
    if reset.tzinfo is None:
        reset = reset.replace(tzinfo=timezone.utc)
    left = (reset - datetime.now(timezone.utc)).total_seconds()
    return left >= SPANS[kind] - IDLE_SLACK_SECONDS


def window_entry(title, label, used, reset_time, idle):
    # An idle window has no reset to count down to.
    reset = "" if idle else reset_time
    entry = {"title": title, "label": label, "percent": used, "resetAt": reset, "resetsAt": reset}
    if idle:
        entry["idle"] = True
    return entry


def update_agy():
    usage_file = os.path.expanduser("~/.local/state/omarchy/agents/usage/agy.json")
    os.makedirs(os.path.dirname(usage_file), exist_ok=True)

    record = None
    # 1. Run the base collector in memory (capturing stdout) to avoid premature/incomplete disk writes
    try:
        cmd = ["omarchy-agent-usage-agy"]
        for arg in sys.argv[1:]:
            if arg in ("--force", "--limits-only"):
                cmd.append(arg)
        raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=15)
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and parsed.get("id") == "agy":
            record = parsed
    except Exception:
        pass

    # Fallback to existing record on disk if base collector was not available
    if not record and os.path.exists(usage_file):
        try:
            with open(usage_file, "r", encoding="utf-8") as f:
                record = json.load(f)
        except Exception:
            pass

    if not record:
        return 1

    # 2. Query real-time quotas via agy -p /usage
    try:
        out = subprocess.check_output(["agy", "-p", "/usage"], stderr=subprocess.DEVNULL, text=True, timeout=12)
    except Exception as e:
        print(f"update-agy: failed to run agy -p /usage: {e}", file=sys.stderr)
        return 1

    groups = [
        {
            "title": "Gemini (Flash, Pro)",
            "id": "gemini",
            "windows": [],
        },
        {
            "title": "Gemini 4 Argon",
            "id": "argon",
            "windows": [],
        },
        {
            "title": "Claude/GPT",
            "id": "claude_gpt",
            "windows": [],
        },
    ]

    gemini_w = {}
    argon_w = {}
    cg_w = {}

    for line in out.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 4:
            continue
        grp, desc, pct_str, reset_time = parts
        rem = float(pct_str.rstrip("%")) / 100.0
        used = round(max(0.0, min(1.0, 1.0 - rem)), 4)
        grp_lower = grp.lower()
        desc_lower = desc.lower()

        if "five hour" in desc_lower or "5h" in desc_lower or "session" in desc_lower:
            kind, title, label = "session", "Session", "Sessão"
        elif "weekly" in desc_lower:
            kind, title, label = "weekly", "Weekly", "Semanal"
        else:
            continue
        entry = window_entry(title, label, used, reset_time, window_idle(rem, reset_time, kind))

        if "gemini models" in grp_lower:
            gemini_w[kind] = entry
        elif "argon" in grp_lower or "argon" in desc_lower:
            if kind == "weekly":
                argon_w[kind] = entry
        elif "claude" in grp_lower or "gpt" in grp_lower:
            cg_w[kind] = entry

    # Gemini (Flash, Pro)
    if "session" in gemini_w:
        groups[0]["windows"].append(gemini_w["session"])
    if "weekly" in gemini_w:
        groups[0]["windows"].append(gemini_w["weekly"])

    # Gemini 4 Argon
    if "weekly" in argon_w:
        groups[1]["windows"].append(argon_w["weekly"])

    # Claude/GPT
    if "session" in cg_w:
        groups[2]["windows"].append(cg_w["session"])
    if "weekly" in cg_w:
        groups[2]["windows"].append(cg_w["weekly"])

    record["quotaGroups"] = groups

    # Flat limits for general components
    flat_limits = []
    for prefix, windows, kinds in (
        ("Gemini", gemini_w, ("session", "weekly")),
        ("Gemini 4 Argon", argon_w, ("weekly",)),
        ("Claude/GPT", cg_w, ("session", "weekly")),
    ):
        for kind in kinds:
            if kind in windows:
                name = f"{prefix} {windows[kind]['label']}"
                flat_limits.append(dict(windows[kind], title=name, label=name))

    record["limits"] = flat_limits
    if not record.get("tierLabel") or record.get("tierLabel") == "":
        record["tierLabel"] = "Pro"

    tmp = usage_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    os.replace(tmp, usage_file)
    return 0


if __name__ == "__main__":
    sys.exit(update_agy())
