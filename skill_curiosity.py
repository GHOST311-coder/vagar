"""Skill curiosity: Vagar's "always wanting to learn" loop.

- log_gap(description): record something the user asked for that no current tool
  can do (or a tool that keeps failing at). Dedupes by normalized description,
  counts repeats, tracks first/last seen.
- get_top_gap(): the highest-count gap that isn't snoozed or dismissed.
- Suggestion policy: surface at most ONE gap per session, and each gap is only
  suggested once per day (no nagging).

Nothing here drafts, stages, or imports anything. Proposing is fine;
activating always needs the user's explicit approval (approve_skill).
"""

import json
import os
import re
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GAPS_FILE = os.path.join(BASE_DIR, "skills", "skill_gaps.json")

_MAX_DESC = 140


def _today():
    return date.today().isoformat()


def _normalize(desc):
    d = re.sub(r"\s+", " ", str(desc or "").strip().lower())
    d = re.sub(r"[.?!;:]+$", "", d).strip()
    return d[:_MAX_DESC]


def _load():
    try:
        with open(GAPS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    os.makedirs(os.path.dirname(GAPS_FILE), exist_ok=True)
    tmp = GAPS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, GAPS_FILE)


def log_gap(description):
    """Record a capability gap. Returns the entry dict (with count)."""
    key = _normalize(description)
    if not key:
        return {"description": "", "count": 0}
    data = _load()
    e = data.get(key)
    now = _today()
    if e is None:
        e = {
            "description": key,
            "count": 0,
            "first_seen": now,
            "last_seen": now,
            "snoozed": False,
            "dismissed": False,
            "last_suggested": None,
        }
    e["count"] = int(e.get("count", 0)) + 1
    e["last_seen"] = now
    # A fresh mention re-arms a snoozed gap only if the user brings it up again
    # via the voice tool path is out of scope; snooze stays until unsnoozed.
    data[key] = e
    _save(data)
    e["key"] = key
    return e


def get_top_gap():
    """Highest-count gap that isn't snoozed/dismissed. Returns entry + key, or None."""
    data = _load()
    cands = [dict(v, key=k) for k, v in data.items()
             if not v.get("snoozed") and not v.get("dismissed")]
    if not cands:
        return None
    cands.sort(key=lambda e: (-int(e.get("count", 0)), str(e.get("last_seen", ""))))
    return cands[0]


def should_suggest(entry):
    """True if this gap may be suggested today (once-per-day anti-nag)."""
    if not entry:
        return False
    return entry.get("last_suggested") != _today()


def mark_suggested(key):
    data = _load()
    if key in data:
        data[key]["last_suggested"] = _today()
        _save(data)


def snooze_gap(description):
    """Stop suggesting this gap (stays logged). Returns True if it was logged."""
    key = _normalize(description)
    data = _load()
    # also match by substring so "pdf" can snooze "read text from pdf files"
    if key not in data:
        for k in data:
            if key and (key in k or k in key):
                key = k
                break
    if key not in data:
        return False
    data[key]["snoozed"] = True
    _save(data)
    return True


def unsnooze_gap(description):
    key = _normalize(description)
    data = _load()
    if key not in data:
        return False
    data[key]["snoozed"] = False
    data[key]["dismissed"] = False
    _save(data)
    return True


def list_gaps():
    """All logged gaps, most-seen first."""
    data = _load()
    items = [dict(v, key=k) for k, v in data.items()]
    items.sort(key=lambda e: (-int(e.get("count", 0)), str(e.get("last_seen", ""))))
    return items
