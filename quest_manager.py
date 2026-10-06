"""Quest tracker for Vagar. Updated when the user completes quests;
Vagar reads it at session start and announces completions."""

import json
import os

import sys as _cfg_sys
from pathlib import Path as _cfg_Path
_cfg_sys.path.insert(0, str(_cfg_Path(__file__).resolve().parent.parent))
from config import QUESTS_PATH

# QUESTS_PATH comes from config.py

def _load():
    try:
        with open(QUESTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"xp": 0, "level": 1, "completed_quests": [],
                "active_quests": [], "pending_announcements": [],
                "level_thresholds": {"2": 300, "3": 600, "4": 1000}}

def _save(data):
    with open(QUESTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_status():
    """Return (xp, level, xp_for_next, active_quest_names)."""
    d = _load()
    xp = d.get("xp", 0)
    thresholds = {int(k): v for k, v in d.get("level_thresholds", {}).items()}
    level = 1
    for lvl, req in sorted(thresholds.items()):
        if xp >= req:
            level = lvl
    # next level
    next_req = None
    for lvl, req in sorted(thresholds.items()):
        if req > xp:
            next_req = req
            break
    active = [q["name"] for q in d.get("active_quests", [])]
    return xp, level, next_req, active

def status_text():
    xp, level, next_req, active = get_status()
    lines = ["Level %d, %d XP" % (level, xp)]
    if next_req:
        lines.append("%d XP to Level %d" % (next_req - xp, level + 1))
    if active:
        lines.append("Active quests: " + ", ".join(
            "%s (%d XP)" % (q["name"], q["xp"])
            for q in _load().get("active_quests", [])))
    return ". ".join(lines) + "."

def pop_announcements():
    """Return and clear pending quest-completion announcements."""
    d = _load()
    pending = d.get("pending_announcements", [])
    if pending:
        d["pending_announcements"] = []
        _save(d)
    return pending

def complete_quest(name, xp_award):
    """Mark a quest complete, award XP, queue an announcement. Called by Rumi."""
    d = _load()
    # remove from active
    d["active_quests"] = [q for q in d.get("active_quests", [])
                          if q["name"] != name]
    d["completed_quests"].append({"name": name, "xp_awarded": xp_award})
    d["xp"] = d.get("xp", 0) + xp_award
    # recompute level
    thresholds = {int(k): v for k, v in d.get("level_thresholds", {}).items()}
    new_level = 1
    for lvl, req in sorted(thresholds.items()):
        if d["xp"] >= req:
            new_level = lvl
    leveled_up = new_level > d.get("level", 1)
    d["level"] = new_level
    d.setdefault("pending_announcements", []).append({
        "quest": name, "xp_award": xp_award,
        "total_xp": d["xp"], "level": new_level,
        "leveled_up": leveled_up,
    })
    _save(d)
    return d
