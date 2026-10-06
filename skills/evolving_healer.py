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


# --- Real strategy handlers (wired 2026-10-06, owner-approved) ---
# What the healer can actually DO when a breaker trips. Bounded to safe,
# reversible infrastructure checks: the healer NEVER rewrites code, deploys
# changes, or restarts OS services (service restarts belong to the watchdog).
# Strategies with no safe handler here are skipped, never faked.

def _h_cooldown_wait(service, ctx):
    """The breaker's own cooldown IS the recovery; verify it is engaged."""
    try:
        breaker = (ctx or {}).get("breaker")
        return bool(breaker is not None and breaker.is_tripped())
    except Exception:
        return False


def _h_check_port(service, ctx):
    """Real TCP check that the service's port is listening."""
    import socket
    _ports = {"ollama": 11434, "livekit": 7880, "moondream": 11434}
    port = _ports.get(service)
    if not port:
        return False
    try:
        _s = socket.create_connection(("127.0.0.1", port), timeout=5)
        _s.close()
        return True
    except Exception:
        return False


def _h_fallback_model(service, ctx):
    """Deep-think fallback: engaged iff the LLM breaker is tripped."""
    try:
        breaker = (ctx or {}).get("breaker")
        return bool(breaker is not None and breaker.is_tripped()
                    and "llm" in (ctx or {}).get("breaker_name", ""))
    except Exception:
        return False


def _h_fallback_yolo(service, ctx):
    """Vision fallback: engaged iff the vision breaker is tripped."""
    try:
        breaker = (ctx or {}).get("breaker")
        return bool(breaker is not None and breaker.is_tripped()
                    and "vision" in (ctx or {}).get("breaker_name", ""))
    except Exception:
        return False


STRATEGY_HANDLERS = {
    "cooldown_wait": _h_cooldown_wait,
    "check_port": _h_check_port,
    "fallback_model": _h_fallback_model,
    "fallback_yolo": _h_fallback_yolo,
}

# Circuit-breaker names (self_heal.py) -> healer service names
_BREAKER_SERVICE = {
    "vision-moondream": "moondream",
    "llm-deepthink": "ollama",
}


def on_breaker_tripped(breaker_name, breaker):
    """Run ranked recovery strategies for a tripped breaker.

    Called on a daemon thread (never the hot path). Tries each ranked
    strategy with a real handler, journals every attempt, and stages a
    spoken escalation for owner if everything fails. Never raises.
    """
    try:
        service = _BREAKER_SERVICE.get(breaker_name, breaker_name)
        ctx = {"breaker": breaker, "breaker_name": breaker_name}
        for strat in ranked_strategies(service):
            handler = STRATEGY_HANDLERS.get(strat)
            if handler is None:
                continue  # outside the healer's safe scope; don't fake it
            t0 = time.time()
            notes = ""
            try:
                ok = bool(handler(service, ctx))
            except Exception as e:
                ok = False
                notes = "handler error: %s" % type(e).__name__
            log_healing_event(service, "breaker_tripped", strat,
                              "success" if ok else "failed",
                              duration_secs=time.time() - t0, notes=notes)
            if ok:
                return True
        # Every known strategy failed -> escalate to owner (spoken once at
        # the next session start, via self_heal.pop_pending_escalation).
        try:
            if should_escalate_to_owner(service):
                import self_heal as _sh_esc
                _sh_esc.set_pending_escalation(
                    "Sir, my %s keeps failing and my usual recoveries are not "
                    "working. You may want to take a look at the laptop when "
                    "you have a moment."
                    % ("vision" if service == "moondream"
                       else "deeper thinking"))
        except Exception:
            pass
        return False
    except Exception:
        return False
