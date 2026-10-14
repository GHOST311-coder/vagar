"""Alien Quest: "The Signal in the Static" boss-battle tracker.

Local-only: one JSON file on the laptop, no network, no subprocess, no new
packages. Tracks the user's "firsts" for the free radio-listening / SETI quest.
Tools: log_first(achievement), list_firsts(), quest_status().
Nothing activates until the user approves this skill.
"""
from livekit.agents.llm import function_tool

import json
import os
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover - fallback if tzdata missing
    LOCAL_TZ = timezone.utc

STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alien_quest.json")

# Canonical achievement ids -> display names
ACHIEVEMENTS = {
    "first_boinc_workunit": "First BOINC/Einstein@Home work unit completed",
    "first_zooniverse": "First Zooniverse SETI classification",
    "first_jupiter_storm": "First Jupiter radio storm heard (20.1 MHz)",
    "first_iss_spotted": "First ISS pass spotted in the sky",
    "first_iss_heard": "First ISS voice heard on radio",
    "first_meteor_scatter": "First meteor scatter ping heard",
    "first_noaa_image": "First NOAA satellite image decoded",
    "first_satnogs": "First SatNOGS telemetry browsed",
    "first_ham_contact": "First ham radio contact heard",
    "first_dsn": "First Deep Space Network dish tracked live",
}


def _load():
    try:
        with open(STORE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data):
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, STORE)


@function_tool
def log_first(achievement: str) -> str:
    """Log one of the user's alien-quest "firsts".

    achievement: one of the known ids, e.g. 'first_jupiter_storm',
    'first_iss_spotted', 'first_zooniverse', 'first_boinc_workunit',
    'first_meteor_scatter', 'first_noaa_image'. Free text is accepted too
    and stored as a custom achievement.
    """
    key = (achievement or "").strip().lower().replace(" ", "_")
    if not key:
        return "No achievement given."
    data = _load()
    done = data.setdefault("achievements", {})
    if key in done:
        return f"Already logged: {done[key]['name']} ({done[key]['when']})."
    name = ACHIEVEMENTS.get(key, achievement.strip())
    when = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z")
    done[key] = {"name": name, "when": when}
    _save(data)
    total = len(done)
    return f"Logged: {name} ({when}). {total} of {len(ACHIEVEMENTS)} achievements unlocked."


@function_tool
def list_firsts() -> str:
    """List which alien-quest achievements the user has unlocked and which remain."""
    data = _load()
    done = data.get("achievements", {})
    lines = ["Unlocked:"]
    if done:
        for _k, v in sorted(done.items(), key=lambda kv: kv[1]["when"]):
            lines.append(f"  [x] {v['name']} â€” {v['when']}")
    else:
        lines.append("  (none yet)")
    lines.append("Remaining:")
    remaining = [k for k in ACHIEVEMENTS if k not in done]
    if remaining:
        for k in remaining:
            lines.append(f"  [ ] {ACHIEVEMENTS[k]}")
    else:
        lines.append("  (all done â€” boss battle complete!)")
    return "\n".join(lines)


@function_tool
def quest_status() -> str:
    """One-line status of the alien-contact boss battle for quick check-ins."""
    data = _load()
    done = data.get("achievements", {})
    n, total = len(done), len(ACHIEVEMENTS)
    if n >= total:
        return f"Boss battle complete: all {total} achievements unlocked. The signal was heard."
    return f"Alien quest: {n}/{total} firsts logged. {total - n} to go."
