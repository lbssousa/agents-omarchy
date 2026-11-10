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

        if "gemini models" in grp_lower:
            if "five hour" in desc_lower or "5h" in desc_lower or "session" in desc_lower:
                gemini_w["session"] = {"title": "Session", "label": "Sessão", "percent": used, "resetAt": reset_time, "resetsAt": reset_time}
            elif "weekly" in desc_lower:
                gemini_w["weekly"] = {"title": "Weekly", "label": "Semanal", "percent": used, "resetAt": reset_time, "resetsAt": reset_time}
        elif "argon" in grp_lower or "argon" in desc_lower:
            if "weekly" in desc_lower:
                argon_w["weekly"] = {"title": "Weekly", "label": "Semanal", "percent": used, "resetAt": reset_time, "resetsAt": reset_time}
        elif "claude" in grp_lower or "gpt" in grp_lower:
            if "five hour" in desc_lower or "5h" in desc_lower or "session" in desc_lower:
                cg_w["session"] = {"title": "Session", "label": "Sessão", "percent": used, "resetAt": reset_time, "resetsAt": reset_time}
            elif "weekly" in desc_lower:
                cg_w["weekly"] = {"title": "Weekly", "label": "Semanal", "percent": used, "resetAt": reset_time, "resetsAt": reset_time}

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
    if "session" in gemini_w:
        flat_limits.append({"title": "Gemini Sessão", "label": "Gemini Sessão", "percent": gemini_w["session"]["percent"], "resetAt": gemini_w["session"]["resetAt"], "resetsAt": gemini_w["session"]["resetAt"]})
    if "weekly" in gemini_w:
        flat_limits.append({"title": "Gemini Semanal", "label": "Gemini Semanal", "percent": gemini_w["weekly"]["percent"], "resetAt": gemini_w["weekly"]["resetAt"], "resetsAt": gemini_w["weekly"]["resetAt"]})
    if "weekly" in argon_w:
        flat_limits.append({"title": "Gemini 4 Argon Semanal", "label": "Gemini 4 Argon Semanal", "percent": argon_w["weekly"]["percent"], "resetAt": argon_w["weekly"]["resetAt"], "resetsAt": argon_w["weekly"]["resetAt"]})
    if "session" in cg_w:
        flat_limits.append({"title": "Claude/GPT Sessão", "label": "Claude/GPT Sessão", "percent": cg_w["session"]["percent"], "resetAt": cg_w["session"]["resetAt"], "resetsAt": cg_w["session"]["resetAt"]})
    if "weekly" in cg_w:
        flat_limits.append({"title": "Claude/GPT Semanal", "label": "Claude/GPT Semanal", "percent": cg_w["weekly"]["percent"], "resetAt": cg_w["weekly"]["resetAt"], "resetsAt": cg_w["weekly"]["resetAt"]})

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
