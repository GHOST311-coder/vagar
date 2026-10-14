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


# ---------------------------------------------------------------------------
# Inventory / weapons / spells (D&D flavor layer - no real-world effects)
# ---------------------------------------------------------------------------
# QUEST REWARD HOOK: when a future quest completes, call award_item() with the
# new gear and it lands in the inventory below. Example:
#   award_item("Wrench of Second Chances", "weapon",
#              "1d8 bludgeoning",
#              "Found in the wreckage of a failed deploy.")
# Spells are learned the same way with kind="spell". Keep names unique;
# award_item() will refuse a duplicate name so nothing is granted twice.

_VALID_KINDS = ("weapon", "item", "spell")

def _ensure_character(d):
    """Make sure the character/inventory block exists; seed if missing."""
    char = d.get("character")
    if not isinstance(char, dict):
        char = {}
        d["character"] = char
    char.setdefault("name", "Player")
    char.setdefault("class", "Artificer")
    char.setdefault("level", 3)
    char.setdefault("weapons", [])
    char.setdefault("items", [])
    char.setdefault("spells", [])
    return char

def get_character():
    """Return the character block (class, level, weapons, items, spells)."""
    d = _load()
    return _ensure_character(d)

def inventory_text():
    """Human/voice-readable summary of the full inventory."""
    char = get_character()
    char_name = char.get("name", "Player")
    lines = ["%s, level %d %s" % (
        char_name, char.get("level", 3), char.get("class", "Artificer"))]
    weapons = char.get("weapons", [])
    items = char.get("items", [])
    spells = char.get("spells", [])
    if weapons:
        lines.append("Weapons: " + "; ".join(
            "%s (%s)" % (w.get("name"), w.get("detail") or "?")
            for w in weapons))
    if items:
        lines.append("Items: " + "; ".join(
            i.get("name") for i in items))
    if spells:
        lines.append("Spells: " + ", ".join(
            s.get("name") for s in spells))
    if not (weapons or items or spells):
        lines.append("Inventory is empty.")
    return ". ".join(lines) + "."

def award_item(name, kind, detail="", flavor=""):
    """Grant a weapon, item, or spell. Returns True if new, False if dup.

    kind: 'weapon' | 'item' | 'spell'
    detail: damage dice for weapons (e.g. '1d8 bludgeoning'),
            level/school for spells (e.g. 'cantrip'), '' for items.
    flavor: one-line story of where it came from.
    """
    kind = (kind or "").lower()
    if kind not in _VALID_KINDS:
        raise ValueError("kind must be one of %s" % (_VALID_KINDS,))
    d = _load()
    char = _ensure_character(d)
    bucket = {"weapon": "weapons", "item": "items",
              "spell": "spells"}[kind]
    for existing in char[bucket]:
        if existing.get("name", "").lower() == name.lower():
            return False  # already owned
    char[bucket].append({
        "name": name, "detail": detail, "flavor": flavor,
    })
    _save(d)
    return True

def describe_item(name):
    """Full description of one named weapon/item/spell, or None."""
    char = get_character()
    for bucket in ("weapons", "items", "spells"):
        for entry in char.get(bucket, []):
            if entry.get("name", "").lower() == name.lower():
                bits = [entry["name"]]
                if entry.get("detail"):
                    bits.append(entry["detail"])
                if entry.get("flavor"):
                    bits.append(entry["flavor"])
                return " -- ".join(bits)
    return None

def cast_spell(name):
    """Flavor-only spellcasting. Returns a line to speak, or a miss note.

    No real-world effects -- this is the RPG layer, not a tool call.
    """
    char = get_character()
    for s in char.get("spells", []):
        if s.get("name", "").lower() == name.lower():
            flavor = s.get("flavor") or "The air hums for a moment."
            return "%s! %s" % (s["name"], flavor)
    known = [s.get("name") for s in char.get("spells", [])]
    if known:
        return "Unknown spell: %s. Known spells: %s." % (
            name, ", ".join(known))
    return "Unknown spell: %s (no spells known yet)." % name
