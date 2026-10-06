"""Routines: Vagar runs the owner's recurring routines.

Extends the reminder idea to things that repeat: "remind me every weekday
at 7am to check traffic". When a routine fires, it reschedules itself
instead of being marked done.

Local-only: one JSON file on the laptop, no network, no subprocess, no new
packages. Delivery path: the agent calls list_due_routines() at the start of
each call and speaks anything due. Nothing activates until the owner approves
this skill.
"""
try:
    from livekit.agents.llm import function_tool
except ImportError:  # pragma: no cover - allows unit testing off-laptop
    def function_tool(*_a, **_k):
        def _deco(f):
            return f
        return _deco

import json
import os
import re
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover - fallback if tzdata missing
    LOCAL_TZ = timezone(timedelta(hours=-5))

import sys as _cfg_sys
from pathlib import Path as _cfg_Path
_cfg_sys.path.insert(0, str(_cfg_Path(__file__).resolve().parent.parent))
from config import ROUTINES_PATH as STORE
# STORE comes from config.py (ROUTINES_PATH)

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _load():
    try:
        with open(STORE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items):
    tmp = str(STORE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1)
    os.replace(tmp, str(STORE))


def _parse_time(time_str):
    """'7am', '7:30pm', '19:00', '7:30 am', 'noon', 'midnight' -> (hour, min)."""
    t = (time_str or "").strip().lower().replace(" ", "")
    if t == "noon":
        return 12, 0
    if t == "midnight":
        return 0, 0
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)", t)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if not (1 <= h <= 12 and 0 <= mi <= 59):
            return None
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return h, mi
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi
    return None


def parse_recurrence(pattern):
    """Parse a recurrence pattern -> rule dict, or None if not understood.

    Rule dicts:
      {"type": "daily", "hour": H, "minute": M}
      {"type": "weekdays", "hour": H, "minute": M}   # Mon-Fri
      {"type": "weekly", "weekday": 0-6, "hour": H, "minute": M}  # 0=Mon
      {"type": "interval", "interval_minutes": N}
    """
    p = (pattern or "").strip().lower()
    p = re.sub(r"\s+", " ", p)

    m = re.fullmatch(r"every\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)", p)
    if m:
        n = int(m.group(1))
        mins = n * 60 if m.group(2).startswith(("hour", "hr")) else n
        if 1 <= mins <= 10080:  # 1 minute to 1 week
            return {"type": "interval", "interval_minutes": mins}
        return None

    m = re.fullmatch(r"(?:every\s+)?weekdays?\s+at\s+(.+)", p)
    if m:
        t = _parse_time(m.group(1))
        if t:
            return {"type": "weekdays", "hour": t[0], "minute": t[1]}
        return None

    m = re.fullmatch(r"(?:every\s+day|daily)\s+at\s+(.+)", p)
    if m:
        t = _parse_time(m.group(1))
        if t:
            return {"type": "daily", "hour": t[0], "minute": t[1]}
        return None

    m = re.fullmatch(
        r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"\s+at\s+(.+)", p)
    if m:
        t = _parse_time(m.group(2))
        if t:
            return {"type": "weekly", "weekday": WEEKDAYS[m.group(1)],
                    "hour": t[0], "minute": t[1]}
        return None

    return None


def next_occurrence(rule, from_dt=None):
    """Next datetime matching rule after from_dt (default: now)."""
    now = from_dt or datetime.now(LOCAL_TZ)
    rtype = rule.get("type")

    if rtype == "interval":
        return now + timedelta(minutes=rule["interval_minutes"])

    h, mi = rule["hour"], rule["minute"]

    if rtype == "daily":
        cand = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if cand <= now:
            cand += timedelta(days=1)
        return cand

    if rtype == "weekdays":
        cand = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if cand <= now:
            cand += timedelta(days=1)
        while cand.weekday() >= 5:  # skip Sat/Sun
            cand += timedelta(days=1)
        return cand

    if rtype == "weekly":
        target = rule["weekday"]
        cand = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        days_ahead = (target - cand.weekday()) % 7
        if days_ahead == 0 and cand <= now:
            days_ahead = 7
        return cand + timedelta(days=days_ahead)

    return None


def _fmt_time(h, mi):
    return datetime(2000, 1, 1, h, mi).strftime("%I:%M %p").lstrip("0")


def describe_recurrence(rule):
    """Short plain-English description of a rule."""
    rtype = rule.get("type")
    if rtype == "interval":
        mins = rule["interval_minutes"]
        if mins >= 60 and mins % 60 == 0:
            n = mins // 60
            return "every %d hour%s" % (n, "" if n == 1 else "s")
        return "every %d minute%s" % (mins, "" if mins == 1 else "s")
    tstr = _fmt_time(rule["hour"], rule["minute"])
    if rtype == "daily":
        return "every day at %s" % tstr
    if rtype == "weekdays":
        return "every weekday at %s" % tstr
    if rtype == "weekly":
        day = [k for k, v in WEEKDAYS.items()
               if v == rule["weekday"]][0].capitalize()
        return "every %s at %s" % (day, tstr)
    return "unknown schedule"


def _fmt(dt_iso):
    try:
        return datetime.fromisoformat(dt_iso).strftime("%a %b %d, %I:%M %p")
    except ValueError:
        return dt_iso


def _emit(action):
    try:
        import activity as _act  # project root on sys.path (see top of file)
        _act.emit(action)
    except Exception:
        pass


@function_tool(
    name="set_routine",
    description=("Save a recurring routine. 'pattern' is plain English: "
                 "'every day at 7am', 'every weekday at 7:30pm', "
                 "'every Monday at 9am', or 'every 2 hours' / 'every 30 minutes'. "
                 "Times are Central. Use when the user says 'remind me every...' "
                 "or 'every <day> remind me to...'."),
)
async def set_routine(text: str, pattern: str) -> str:
    _emit("Setting routine\u2026")
    rule = parse_recurrence(pattern)
    if rule is None:
        return ("I didn't get the repeat pattern. Try 'every day at 7am', "
                "'every weekday at 7am', 'every Monday at 9am', "
                "or 'every 2 hours'.")
    items = _load()
    rid = max([i.get("id", 0) for i in items] + [0]) + 1
    first = next_occurrence(rule)
    items.append({
        "id": rid,
        "text": text.strip(),
        "recurrence": rule,
        "next_due": first.isoformat(),
        "created": datetime.now(LOCAL_TZ).isoformat(),
        "cancelled": False,
        "fire_count": 0,
    })
    _save(items)
    return ("Routine %d set: %s \u2014 %s. First run %s."
            % (rid, describe_recurrence(rule), text.strip(), _fmt(first.isoformat())))


@function_tool(
    name="list_routines",
    description="List active recurring routines, soonest first.",
)
async def list_routines() -> str:
    items = [i for i in _load() if not i.get("cancelled")]
    if not items:
        return "No active routines."
    items.sort(key=lambda i: i.get("next_due", ""))
    lines = []
    for i in items:
        lines.append("%d. %s \u2014 %s (next: %s, ran %d times)" % (
            i["id"], describe_recurrence(i["recurrence"]), i["text"],
            _fmt(i["next_due"]), i.get("fire_count", 0)))
    return "Active routines:\n" + "\n".join(lines)


@function_tool(
    name="cancel_routine",
    description="Cancel a recurring routine by its id (see list_routines).",
)
async def cancel_routine(routine_id: int) -> str:
    _emit("Cancelling routine\u2026")
    items = _load()
    for i in items:
        if i.get("id") == int(routine_id) and not i.get("cancelled"):
            i["cancelled"] = True
            _save(items)
            return "Routine %d cancelled." % i["id"]
    return "No active routine with id %s." % routine_id


@function_tool(
    name="list_due_routines",
    description=("Routines due right now (or overdue). Call this at the start of "
                 "each call and speak anything it returns. Each firing routine "
                 "reschedules itself for its next run."),
)
async def list_due_routines() -> str:
    now = datetime.now(LOCAL_TZ)
    items = _load()
    due = []
    changed = False
    for i in items:
        if i.get("cancelled"):
            continue
        try:
            if datetime.fromisoformat(i["next_due"]) <= now:
                due.append(i)
                i["fire_count"] = i.get("fire_count", 0) + 1
                # Reschedule: advance until strictly after now (cap iterations
                # so a long-offline laptop can't spin forever).
                nxt = next_occurrence(i["recurrence"], from_dt=now)
                for _ in range(10000):
                    if nxt > now:
                        break
                    nxt = next_occurrence(i["recurrence"], from_dt=nxt)
                i["next_due"] = nxt.isoformat()
                changed = True
        except (ValueError, KeyError, TypeError):
            continue
    if changed:
        _save(items)
    if not due:
        return "Nothing due right now."
    return "Due routines:\n" + "\n".join("- %s" % i["text"] for i in due)
