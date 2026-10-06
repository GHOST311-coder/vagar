"""Reminders: Vagar remembers things the user wants to be told later.

Local-only: one JSON file on the laptop, no network, no subprocess, no new
packages. Delivery path: the agent calls list_due_reminders() at the start of
each call and speaks anything due. Nothing activates until the user approves
this skill.
"""
from livekit.agents.llm import function_tool

import json
import os
import re
from datetime import datetime, timedelta, timezone

import sys as _cfg_sys
from pathlib import Path as _cfg_Path
_cfg_sys.path.insert(0, str(_cfg_Path(__file__).resolve().parent.parent))
from config import REMINDERS_PATH as STORE

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover - fallback if tzdata missing
    LOCAL_TZ = timezone(timedelta(hours=-5))

# STORE comes from config.py (REMINDERS_PATH)


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


def _parse_when(when):
    """'YYYY-MM-DD HH:MM' (24h, Central) or 'in N minutes|hours'."""
    when = (when or "").strip().lower()
    m = re.fullmatch(r"in\s+(\d+)\s*(minutes?|hours?)", when)
    if m:
        n = int(m.group(1))
        delta = timedelta(minutes=n) if m.group(2).startswith("minute") else timedelta(hours=n)
        return datetime.now(LOCAL_TZ) + delta
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})[ t](\d{1,2}):(\d{2})", when)
    if m:
        y, mo, d, h, mi = map(int, m.groups())
        return datetime(y, mo, d, h, mi, tzinfo=LOCAL_TZ)
    return None


def _fmt(dt_iso):
    try:
        return datetime.fromisoformat(dt_iso).strftime("%a %b %d, %I:%M %p")
    except ValueError:
        return dt_iso


@function_tool(
    name="set_reminder",
    description=("Save a reminder for later. 'when' is 'YYYY-MM-DD HH:MM' (24-hour, "
                 "Central time) or 'in N minutes/hours'. Use when the user says 'remind me'."),
)
async def set_reminder(text: str, when: str) -> str:
    try:
        import sys as _asys  # project root on sys.path (see top of file)
        import activity as _act
        _act.emit("Setting reminder\u2026")
    except Exception:
        pass
    due = _parse_when(when)
    if due is None:
        return ("I couldn't understand the time. Use 'YYYY-MM-DD HH:MM' like "
                "'2026-10-02 09:00', or 'in 30 minutes'.")
    items = _load()
    rid = max([i.get("id", 0) for i in items] + [0]) + 1
    items.append({"id": rid, "text": text.strip(), "due": due.isoformat(),
                  "created": datetime.now(LOCAL_TZ).isoformat(), "done": False})
    _save(items)
    return "Reminder %d saved for %s: %s" % (rid, _fmt(due.isoformat()), text.strip())


@function_tool(
    name="list_reminders",
    description="List pending reminders, soonest first. Overdue ones are flagged.",
)
async def list_reminders() -> str:
    items = [i for i in _load() if not i.get("done")]
    if not items:
        return "No pending reminders."
    now = datetime.now(LOCAL_TZ)
    items.sort(key=lambda i: i.get("due", ""))
    lines = []
    for i in items:
        try:
            overdue = datetime.fromisoformat(i["due"]) <= now
        except ValueError:
            overdue = False
        lines.append("%d. %s -- %s%s" % (i["id"], i["text"], _fmt(i["due"]),
                                         " (OVERDUE)" if overdue else ""))
    return "\n".join(lines)


@function_tool(
    name="cancel_reminder",
    description="Cancel a pending reminder by its id (see list_reminders).",
)
async def cancel_reminder(reminder_id: int) -> str:
    try:
        import sys as _asys  # project root on sys.path (see top of file)
        import activity as _act
        _act.emit("Cancelling reminder\u2026")
    except Exception:
        pass
    items = _load()
    for i in items:
        if i.get("id") == int(reminder_id) and not i.get("done"):
            i["done"] = True
            _save(items)
            return "Reminder %d cancelled." % i["id"]
    return "No pending reminder with id %s." % reminder_id


@function_tool(
    name="list_due_reminders",
    description=("Reminders due right now (or overdue). Call this at the start of "
                 "each call and speak anything it returns. Each reminder is "
                 "reported once."),
)
async def list_due_reminders() -> str:
    now = datetime.now(LOCAL_TZ)
    items = _load()
    due = []
    changed = False
    for i in items:
        if i.get("done"):
            continue
        try:
            if datetime.fromisoformat(i["due"]) <= now:
                due.append(i)
                i["done"] = True
                changed = True
        except ValueError:
            continue
    if changed:
        _save(items)
    if not due:
        return "Nothing due right now."
    return "Due reminders:\n" + "\n".join("- %s" % i["text"] for i in due)
