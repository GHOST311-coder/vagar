"""Storm-alert check for Vagar's ask-first morning briefing.

Runs before the briefing content each morning for your work area (set NWS_LAT/NWS_LON below).
- New STORM-grade NWS alert: briefing leads with the alert + storm-day checklist.
- New non-storm alert (fog, frost, etc.): brief heads-up, no storm checklist.
- Carried-over storm alert: fresh checklist, no re-read of the same alert text.
- Carried-over non-storm alert: brief reminder, no checklist.
- Storm-grade forecast but no alert: checklist with plain uncertainty.
- Calm morning: returns "" (briefing keeps its one-line weather read).
- NWS feed unreachable: says so plainly, falls back to forecast alone.

Off-switch: create vagar\\skills\\storm_off.txt (any content) to disable.
Re-enable: delete that file.
"""
import json
import os
import urllib.request

_SKILLS = os.path.dirname(os.path.abspath(__file__))
_SEEN_FILE = os.path.join(_SKILLS, "storm_seen.json")
_CHECKLIST_FILE = os.path.join(_SKILLS, "storm_checklist.txt")
_OFF_FILE = os.path.join(_SKILLS, "storm_off.txt")
# Your work-area coordinates for NWS alerts (set these to your location)
NWS_LAT = os.environ.get("VAGAR_NWS_LAT", "0.0")  # e.g. "30.38"
NWS_LON = os.environ.get("VAGAR_NWS_LON", "0.0")  # e.g. "-89.60"
_NWS_URL = "https://api.weather.gov/alerts/active?point=%s,%s" % (NWS_LAT, NWS_LON)

_STORM_WORDS = ("thunderstorm", "tornado", "hurricane", "flood", "severe",
                "heavy rain", "flash flood", "tropical storm", "tropical depression")

# NWS event names that warrant the full storm-day checklist.
_STORM_EVENTS = ("thunderstorm", "tornado", "hurricane", "flood", "flash flood",
                 "severe", "tropical", "storm surge", "high wind", "hail",
                 "blizzard", "ice storm", "winter storm")


def enabled():
    return not os.path.exists(_OFF_FILE)


def _is_storm_event(event_name):
    e = (event_name or "").lower()
    return any(k in e for k in _STORM_EVENTS)


def fetch_nws_alerts():
    """Return (alerts, error). alerts = list of dicts with id/event/headline/severity."""
    try:
        req = urllib.request.Request(
            _NWS_URL, headers={"User-Agent": "Vagar/1.0 (morning briefing)"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
        out = []
        for f in data.get("features", []):
            p = f.get("properties", {}) or {}
            out.append({
                "id": p.get("id", ""),
                "event": p.get("event", "Weather alert"),
                "headline": (p.get("headline", "") or "").strip(),
                "severity": p.get("severity", ""),
            })
        return out, None
    except Exception as e:
        return [], "unreachable (%s)" % e


def _load_seen():
    try:
        with open(_SEEN_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return set(d.get("seen_ids", []))
    except Exception:
        return set()


def _save_seen(ids):
    try:
        with open(_SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump({"seen_ids": sorted(ids)}, f)
    except Exception:
        pass


def load_checklist():
    try:
        with open(_CHECKLIST_FILE, encoding="utf-8") as f:
            txt = f.read().strip()
            if txt:
                return txt
    except Exception:
        pass
    return ("Storm-day checklist: rain gear on, watch your footing in mud, "
            "drink water through the shift. Advisory only, sir.")


def storm_briefing_part(weather_text):
    """Build the storm lead-in for the morning briefing (may be "")."""
    if not enabled():
        return ""
    alerts, err = fetch_nws_alerts()
    seen = _load_seen()
    new_alerts = [a for a in alerts if a["id"] not in seen]
    carried = [a for a in alerts if a["id"] in seen]
    _save_seen([a["id"] for a in alerts if a["id"]])

    checklist = load_checklist()

    new_storm = [a for a in new_alerts if _is_storm_event(a["event"])]
    new_other = [a for a in new_alerts if not _is_storm_event(a["event"])]
    carried_storm = [a for a in carried if _is_storm_event(a["event"])]
    carried_other = [a for a in carried if not _is_storm_event(a["event"])]

    if new_storm:
        a = new_storm[0]
        others = [x["event"] for x in new_storm[1:] + carried_storm]
        extra = " Also in effect: %s." % ", ".join(others) if others else ""
        return ("Storm alert for your area: %s. %s%s %s" % (
            a["event"], a["headline"], extra, checklist))
    if carried_storm:
        evts = ", ".join(sorted(set(a["event"] for a in carried_storm)))
        return ("The %s for your area is still in effect. %s" %
                (evts, checklist))
    if new_other:
        # Non-storm alert: heads-up only, no storm checklist.
        a = new_other[0]
        return ("Heads up for your area: %s. %s" % (a["event"], a["headline"]))
    if carried_other:
        evts = ", ".join(sorted(set(a["event"] for a in carried_other)))
        return "The %s for your area is still in effect." % evts

    wl = (weather_text or "").lower()
    storm_in_forecast = any(w in wl for w in _STORM_WORDS)
    if err:
        # Feed down: say so plainly, fall back to forecast alone.
        if storm_in_forecast:
            return ("I could not reach the NWS alert feed this morning, sir. "
                    "The forecast shows storm-grade weather for your area. "
                    "Forecasts can shift. %s" % checklist)
        return "I could not reach the NWS alert feed this morning, sir."
    if storm_in_forecast:
        return ("The forecast shows storm-grade weather for your area today, "
                "though no NWS alert is active. Forecasts can shift, sir. %s" % checklist)
    return ""
