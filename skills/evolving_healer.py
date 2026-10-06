"""Vagar evolving self-healer: learns which recovery strategies work.

Layer on top of self_heal.py circuit breakers. Instead of fixed rules,
this module:
1. Journals every healing event (failure, strategy tried, outcome)
2. Ranks strategies by historical success rate per service
3. Escalates adaptively: tries best-known strategy first, falls through
   to alternatives, alerts the owner only when all known strategies fail
4. Proposes new strategies via skill_manager when patterns emerge

Drafts code fixes as unified diffs into staging/healer_patches/ for
the owner's approval (mirrors the skill_manager draft->stage->approve
pattern). Nothing is ever applied without an explicit approval call.

Never applies code changes autonomously. New strategies and patches
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
        # Every known strategy failed -> draft a fix for the owner, then
        # escalate (spoken once at the next session start, via
        # self_heal.pop_pending_escalation).
        try:
            if should_escalate_to_owner(service):
                _patch = _maybe_draft_patch(service)
                import self_heal as _sh_esc
                _label = ("vision" if service == "moondream"
                          else "deeper thinking")
                if _patch:
                    _sh_esc.set_pending_escalation(
                        "Sir, my %s keeps failing and my usual recoveries are "
                        "not working. I have drafted a fix and staged it for "
                        "your approval - say 'list pending patches' to "
                        "review it." % _label)
                else:
                    _sh_esc.set_pending_escalation(
                        "Sir, my %s keeps failing and my usual recoveries are "
                        "not working. You may want to take a look at the "
                        "laptop when you have a moment." % _label)
        except Exception:
            pass
        return False
    except Exception:
        return False


# =====================================================================
# Healer-drafted code patches (owner-approved 2026-10-06)
#
# When every ranked recovery strategy fails for a service, the healer
# asks the deep model to DRAFT a fix as a unified diff and stages it
# under skills/staging/healer_patches/ for the owner's approval.
# Nothing is ever applied without an explicit approve_healer_patch call.
# Mirrors the skill_manager draft -> stage -> approve pattern.
# =====================================================================

import py_compile as _pycompile
import re as _re2
import shutil as _shutil2
import tempfile as _tempfile2
import urllib.request as _urlrequest

try:
    from livekit.agents.llm import function_tool as _ft
    _HAVE_TOOL = True
except Exception:
    _HAVE_TOOL = False

_HEALER_FILE = os.path.realpath(os.path.abspath(__file__))
_HEALER_DIR = os.path.dirname(_HEALER_FILE)
_VAGAR_ROOT = os.path.dirname(_HEALER_DIR)
_AGENT_PY = os.path.realpath(os.path.join(os.path.dirname(_VAGAR_ROOT), "agent.py"))
_SELF_HEAL_PY = os.path.realpath(os.path.join(_VAGAR_ROOT, "self_heal.py"))
_PATCH_STAGE_DIR = os.path.join(_HEALER_DIR, "staging", "healer_patches")
_PATCH_APPLIED_DIR = os.path.join(_PATCH_STAGE_DIR, "applied")

_DRAFT_MODEL = "qwen2.5:3b"
_OLLAMA_API = "http://localhost:11434/api/generate"

# service -> file the healer may propose fixes for. The healer improves
# its own recovery logic (this module) and the breaker layer; agent.py
# stays allowlisted for model-identified root causes there.
_SERVICE_PATCH_TARGET = {
    "moondream": _HEALER_FILE,
    "ollama": _HEALER_FILE,
    "livekit": _SELF_HEAL_PY,
    "yolo_watch": _HEALER_FILE,
    "laptop_cam": _HEALER_FILE,
}

_SECRET_RES = [
    _re2.compile(r"sk-[A-Za-z0-9]{8,}"),
    _re2.compile(r"ghp_[A-Za-z0-9]{8,}"),
    _re2.compile(r"(?i)(api_key|apikey|password|passwd|secret|bearer|token)\s*[:=]\s*['\"][^'\"]{3,}['\"]"),
]

_patch_lock = threading.Lock()


def _sanitize_patch_name(name):
    return _re2.sub(r"[^a-zA-Z0-9_-]", "", (name or "").strip().lower())[:64]


def _is_patchable_target(path):
    """True iff path is an allowlisted patch target (canonical compare)."""
    try:
        real = os.path.realpath(os.path.abspath(path))
    except Exception:
        return False
    if not real.lower().endswith(".py"):
        return False
    if real in (_AGENT_PY, _SELF_HEAL_PY, _HEALER_FILE):
        return True
    skills = os.path.realpath(_HEALER_DIR)
    return os.path.dirname(real) == skills


def _extract_diff(text):
    m = _re2.search(r"```diff(.*?)```", text, _re2.S)
    if m:
        return m.group(1).strip()
    m = _re2.search(r"```(.*?)```", text, _re2.S)
    if m:
        return m.group(1).strip()
    # salvage: bare diff with no fence - start at first ---/+++/@@ line
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("--- ") or s.startswith("+++ ") or s.startswith("@@ "):
            start = i
            break
    if start is not None:
        return "\n".join(lines[start:]).strip()
    return ""


def _scan_for_secrets(diff_text):
    return any(rx.search(diff_text) for rx in _SECRET_RES)


def _apply_unified_diff(original, diff_text):
    """Apply a unified diff to original text. Raises ValueError on mismatch."""
    hunks = []
    cur = None
    for line in diff_text.splitlines():
        m = _re2.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            cur = (int(m.group(1)), [])
            hunks.append(cur)
            continue
        if cur is None:
            continue  # skip ---/+++/diff headers
        if line.startswith("\\"):
            continue  # "\ No newline at end of file"
        cur[1].append(line)
    if not hunks:
        raise ValueError("no hunks found in diff")
    src = original.splitlines()
    out = []
    pos = 0
    for start, hunk in hunks:
        idx = start - 1
        if idx < 0 or idx < pos:
            raise ValueError("bad hunk offset")
        out.extend(src[pos:idx])
        pos = idx
        for hl in hunk:
            if hl.startswith(" ") or hl == "":
                want = hl[1:] if hl.startswith(" ") else ""
                if pos >= len(src) or src[pos] != want:
                    raise ValueError("context mismatch at line %d" % (pos + 1))
                out.append(src[pos])
                pos += 1
            elif hl.startswith("-"):
                if pos >= len(src) or src[pos] != hl[1:]:
                    raise ValueError("removal mismatch at line %d" % (pos + 1))
                pos += 1
            elif hl.startswith("+"):
                out.append(hl[1:])
            else:
                raise ValueError("bad hunk line: %r" % hl[:40])
    out.extend(src[pos:])
    text = "\n".join(out)
    if original.endswith("\n"):
        text += "\n"
    return text


def _validate_patch(target_path, diff_text):
    """Sandbox gate: headers sane, no secrets, applies cleanly, compiles."""
    base = os.path.basename(target_path)
    for line in diff_text.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            p = line[4:].strip().split()[0]
            if p == "/dev/null":
                continue
            q = p[2:] if p.startswith(("a/", "b/")) else p
            if os.path.basename(q) != base:
                return False, "diff touches unexpected file: %s" % p
    if _scan_for_secrets(diff_text):
        return False, "diff failed secret scan"
    tmpd = _tempfile2.mkdtemp(prefix="healer_patch_")
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            original = f.read()
        try:
            patched = _apply_unified_diff(original, diff_text)
        except ValueError as e:
            return False, "diff does not apply: %s" % e
        trial = os.path.join(tmpd, base)
        with open(trial, "w", encoding="utf-8") as f:
            f.write(patched)
        _pycompile.compile(trial, doraise=True)
        return True, ""
    except Exception as e:
        return False, "validation error: %s: %s" % (type(e).__name__, e)
    finally:
        try:
            _shutil2.rmtree(tmpd, ignore_errors=True)
        except Exception:
            pass


def _draft_prompt(service, target_path):
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return None
    if len(content) > 12000:
        content = content[:12000] + "\n...[truncated]...\n"
    lines = [
        "The self-healer tried every known recovery strategy for service '%s' and all failed." % service,
        "",
        "Recent healing journal:",
        failure_summary(service),
    ]
    for e in [x for x in _read_journal() if x.get("service") == service][-8:]:
        lines.append("  - %s | %s | %s | %s" % (
            e.get("strategy"), e.get("outcome"), e.get("failure_type"),
            (e.get("notes") or "")[:80]))
    lines += [
        "",
        "Target file to fix: %s" % os.path.basename(target_path),
        "Current content:",
        "```python",
        content,
        "```",
        "",
        "Draft a MINIMAL, targeted fix as a unified diff. Rules:",
        "- Address the likely root cause shown in the journal; keep the change small.",
        "- Modify ONLY the target file. No new files, no new dependencies.",
        "- Wrap risky code in try/except; the module must never crash on import.",
        "- Never include credentials, tokens, keys, or passwords.",
        "- Copy context lines EXACTLY as shown, including leading spaces and indentation.",
        "- Output ONLY the diff inside a ```diff fenced block. No explanations.",
        "  Example of the required output format:",
        "  ```diff",
        "  --- a/example.py",
        "  +++ b/example.py",
        "  @@ -1,3 +1,3 @@",
        "   line1",
        "  -old line",
        "  +new line",
        "   line3",
        "  ```",
    ]
    return "\n".join(lines)


def _draft_patch_via_llm(service, target_path):
    """Ask the deep model for a fix diff. Returns (diff, error). Never raises."""
    try:
        prompt = _draft_prompt(service, target_path)
        if not prompt:
            return None, "could not build draft prompt"
        body = json.dumps({
            "model": _DRAFT_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 2000},
        }).encode()
        req = _urlrequest.Request(_OLLAMA_API, data=body,
                                  headers={"Content-Type": "application/json"})
        with _urlrequest.urlopen(req, timeout=300) as r:
            text = json.loads(r.read())["response"]
        diff = _extract_diff(text)
        if not diff:
            return None, "model did not return a diff"
        return diff, ""
    except Exception as e:
        return None, "draft model call failed: %s: %s" % (type(e).__name__, e)


def _service_has_staged_patch(service):
    if not os.path.isdir(_PATCH_STAGE_DIR):
        return False
    for f in os.listdir(_PATCH_STAGE_DIR):
        if f.endswith(".json"):
            try:
                with open(os.path.join(_PATCH_STAGE_DIR, f), "r", encoding="utf-8") as fh:
                    if json.load(fh).get("service") == service:
                        return True
            except Exception:
                pass
    return False


def _maybe_draft_patch(service):
    """Draft, validate and stage a fix. Returns patch name or None. Never raises."""
    try:
        if _service_has_staged_patch(service):
            return None  # one staged patch per service at a time
        target = _SERVICE_PATCH_TARGET.get(service, _HEALER_FILE)
        if not _is_patchable_target(target):
            return None
        # Bounded retries: the small draft model is nondeterministic;
        # a fresh sample often produces a clean, applicable diff.
        diff = None
        for _attempt in range(3):
            _d, _err = _draft_patch_via_llm(service, target)
            if not _d:
                log_healing_event(service, "patch_draft", "draft", "failed",
                                  notes="attempt %d: %s" % (_attempt + 1, _err[:150]))
                continue
            _ok, _msg = _validate_patch(target, _d)
            if _ok:
                diff = _d
                break
            log_healing_event(service, "patch_draft", "validate", "failed",
                              notes="attempt %d: %s" % (_attempt + 1, _msg[:150]))
        if not diff:
            return None
        with _patch_lock:
            if _service_has_staged_patch(service):
                return None
            name = "%s-%s" % (_sanitize_patch_name(service) or "patch",
                              time.strftime("%Y%m%d-%H%M%S"))
            os.makedirs(_PATCH_STAGE_DIR, exist_ok=True)
            with open(os.path.join(_PATCH_STAGE_DIR, name + ".patch"),
                      "w", encoding="utf-8") as f:
                f.write(diff if diff.endswith("\n") else diff + "\n")
            sidecar = {
                "name": name,
                "ts": time.time(),
                "service": service,
                "target_file": target,
                "draft_model": _DRAFT_MODEL,
                "journal_summary": failure_summary(service)[:2000],
            }
            with open(os.path.join(_PATCH_STAGE_DIR, name + ".json"),
                      "w", encoding="utf-8") as f:
                json.dump(sidecar, f, indent=2)
        log_healing_event(service, "patch_draft", "stage", "success", notes=name)
        return name
    except Exception:
        return None


def _load_sidecar(name):
    with open(os.path.join(_PATCH_STAGE_DIR, name + ".json"),
              "r", encoding="utf-8") as f:
        return json.load(f)


async def _impl_list_pending_patches() -> str:
    try:
        if not os.path.isdir(_PATCH_STAGE_DIR):
            return "There are no staged patches."
        names = sorted(f[:-6] for f in os.listdir(_PATCH_STAGE_DIR)
                       if f.endswith(".patch"))
        if not names:
            return "There are no staged patches."
        lines = []
        for n in names:
            try:
                sc = _load_sidecar(n)
                first = (sc.get("journal_summary", "") or "").splitlines()
                lines.append("%s: service '%s', target %s, drafted %s. %s" % (
                    n, sc.get("service"), os.path.basename(sc.get("target_file", "?")),
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(sc.get("ts", 0))),
                    first[0][:120] if first else ""))
            except Exception:
                lines.append("%s: (unreadable sidecar)" % n)
        return "Staged healer patches:\n" + "\n".join(lines)
    except Exception as e:
        return "Could not list patches: %s" % e


async def _impl_approve_healer_patch(name: str) -> str:
    clean = _sanitize_patch_name(name)
    if not clean:
        return "That patch name is not valid."
    try:
        with _patch_lock:
            try:
                sc = _load_sidecar(clean)
            except FileNotFoundError:
                return "There is no staged patch named '%s'." % clean
            target = sc.get("target_file", "")
            if not _is_patchable_target(target):
                return "Patch '%s' targets a file outside the allowlist; refused." % clean
            patch_path = os.path.join(_PATCH_STAGE_DIR, clean + ".patch")
            with open(patch_path, "r", encoding="utf-8") as f:
                diff = f.read()
            if _scan_for_secrets(diff):
                return "Patch '%s' failed the secret scan; refused." % clean
            with open(target, "r", encoding="utf-8") as f:
                original = f.read()
            try:
                patched = _apply_unified_diff(original, diff)
            except ValueError as e:
                return ("Patch '%s' no longer applies cleanly: %s. Discard it and "
                        "let the healer draft a fresh one." % (clean, e))
            bak = "%s.bak-%s-healerpatch" % (target, time.strftime("%Y%m%d-%H%M%S"))
            _shutil2.copy2(target, bak)
            try:
                with open(target, "w", encoding="utf-8") as f:
                    f.write(patched)
                _pycompile.compile(target, doraise=True)
            except Exception as e:
                _shutil2.copy2(bak, target)  # roll back
                return ("Applying patch '%s' failed (%s: %s); the original was "
                        "restored from backup." % (clean, type(e).__name__, e))
            os.makedirs(_PATCH_APPLIED_DIR, exist_ok=True)
            _shutil2.move(patch_path, os.path.join(_PATCH_APPLIED_DIR, clean + ".patch"))
            _shutil2.move(os.path.join(_PATCH_STAGE_DIR, clean + ".json"),
                          os.path.join(_PATCH_APPLIED_DIR, clean + ".json"))
            return ("Patch '%s' applied to %s (backup: %s). It takes effect after "
                    "the worker restarts." % (clean, os.path.basename(target),
                                              os.path.basename(bak)))
    except Exception as e:
        return "approve_healer_patch failed: %s: %s" % (type(e).__name__, e)


async def _impl_reject_healer_patch(name: str) -> str:
    clean = _sanitize_patch_name(name)
    if not clean:
        return "That patch name is not valid."
    try:
        with _patch_lock:
            pp = os.path.join(_PATCH_STAGE_DIR, clean + ".patch")
            pj = os.path.join(_PATCH_STAGE_DIR, clean + ".json")
            if not os.path.isfile(pp):
                return "There is no staged patch named '%s'." % clean
            os.remove(pp)
            if os.path.isfile(pj):
                os.remove(pj)
            return "Staged patch '%s' discarded." % clean
    except Exception as e:
        return "reject_healer_patch failed: %s: %s" % (type(e).__name__, e)


if _HAVE_TOOL:
    list_pending_patches = _ft(
        name="list_pending_patches",
        description=("List healer-drafted code patches staged for the owner's approval. "
                     "Call when the user asks what patches are pending review."),
    )(_impl_list_pending_patches)
    approve_healer_patch = _ft(
        name="approve_healer_patch",
        description=("Apply a staged healer-drafted patch to its target file, with an "
                     "automatic timestamped backup. ONLY the user may approve patches - "
                     "never call this on your own initiative. Only call it when the user "
                     "explicitly names a patch to approve."),
    )(_impl_approve_healer_patch)
    reject_healer_patch = _ft(
        name="reject_healer_patch",
        description=("Discard a staged healer-drafted patch without applying it. "
                     "Use when the user declines a drafted fix."),
    )(_impl_reject_healer_patch)
