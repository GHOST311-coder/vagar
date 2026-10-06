"""Vagar evolving self-healer: learns which recovery strategies work.

Layer on top of self_heal.py circuit breakers. Instead of fixed rules,
this module:
1. Journals every healing event (failure, strategy tried, outcome)
2. Ranks strategies by historical success rate per service
3. Escalates adaptively: tries best-known strategy first, falls through
   to alternatives, alerts the owner only when all known strategies fail
4. Proposes new strategies via skill_manager when patterns emerge

Never rewrites code or deploys changes autonomously. New strategies
go through the owner's approval gate, per his standing rule.
Thread-safe. Never crashes the worker.
"""
import json
import os
import threading
import time

JOURNAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "healing_journal.jsonl")

_lock = threading.Lock()

# Default strategy rankings (used until journal has enough data)
# Each service maps to ordered list of (strategy_name, handler_hint)
DEFAULT_STRATEGIES = {
    "ollama": ["restart_service", "fallback_model", "cooldown_wait"],
    "moondream": ["cooldown_wait", "fallback_yolo", "restart_service"],
    "livekit": ["restart_service", "check_port", "cooldown_wait"],
    "yolo_watch": ["restart_thread", "cooldown_wait"],
    "laptop_cam": ["restart_thread", "cooldown_wait"],
}


def _read_journal():
    """Read all journal entries. Returns list of dicts."""
    entries = []
    if not os.path.exists(JOURNAL_PATH):
        return entries
    try:
        with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception:
        pass
    return entries


def log_healing_event(service, failure_type, strategy, outcome,
                      duration_secs=0.0, notes=""):
    """Journal a healing attempt. Outcome: 'success' or 'failed'."""
    entry = {
        "ts": time.time(),
        "service": service,
        "failure_type": failure_type,
        "strategy": strategy,
        "outcome": outcome,
        "duration_secs": round(duration_secs, 2),
        "notes": notes[:200],
    }
    with _lock:
        try:
            with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass


def ranked_strategies(service):
    """Return strategies for a service ordered by historical success rate.

    Falls back to DEFAULT_STRATEGIES when journal has <3 events for
    the service. Minimum 3 events avoids over-fitting to noise.
    """
    entries = _read_journal()
    svc_entries = [e for e in entries if e.get("service") == service]

    if len(svc_entries) < 3:
        return DEFAULT_STRATEGIES.get(service, ["cooldown_wait"])

    # Score each strategy: success_rate weighted by recency
    scores = {}
    now = time.time()
    for e in svc_entries:
        strat = e.get("strategy", "unknown")
        # Recency weight: events in last 7 days count full, older decay
        age_days = (now - e.get("ts", now)) / 86400
        weight = max(0.2, 1.0 - (age_days / 30.0))
        if strat not in scores:
            scores[strat] = {"wins": 0.0, "total": 0.0}
        scores[strat]["total"] += weight
        if e.get("outcome") == "success":
            scores[strat]["wins"] += weight

    ranked = sorted(
        scores.items(),
        key=lambda kv: (kv[1]["wins"] / kv[1]["total"]) if kv[1]["total"] > 0 else 0,
        reverse=True,
    )
    ordered = [name for name, _ in ranked]

    # Append any default strategies not yet seen in journal
    for default in DEFAULT_STRATEGIES.get(service, []):
        if default not in ordered:
            ordered.append(default)
    return ordered


def failure_summary(service, hours=24):
    """Human-readable summary of recent failures for a service."""
    entries = _read_journal()
    cutoff = time.time() - (hours * 3600)
    recent = [e for e in entries
              if e.get("service") == service and e.get("ts", 0) > cutoff]
    if not recent:
        return f"No failures for {service} in last {hours}h."

    by_strategy = {}
    for e in recent:
        s = e.get("strategy", "unknown")
        by_strategy.setdefault(s, {"success": 0, "failed": 0})
        by_strategy[s][e.get("outcome", "failed")] += 1

    lines = [f"{service}: {len(recent)} healing events in last {hours}h"]
    for strat, counts in by_strategy.items():
        total = counts["success"] + counts["failed"]
        rate = (counts["success"] / total * 100) if total else 0
        lines.append(f"  {strat}: {counts['success']}/{total} ({rate:.0f}% success)")
    return "\n".join(lines)


def should_escalate_to_owner(service):
    """True if all known strategies have failed recently for this service.

    Checks last 5 events: if none succeeded, it's time to ask the owner.
    """
    entries = _read_journal()
    svc = [e for e in entries if e.get("service") == service]
    if len(svc) < 5:
        return False
    recent = svc[-5:]
    return not any(e.get("outcome") == "success" for e in recent)
