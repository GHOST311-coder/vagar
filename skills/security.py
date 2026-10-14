"""Vagar security skill — DEFENSIVE ONLY.
Voice tools + automatic background monitoring.
Wires in: tool_anomaly, vuln_scanner, inject_hardening, tripwire.

Guards (why it's safe):
- Read-only scans. Nothing is modified, no network calls except the
  tailnet-local `tailscale status` for the device allowlist check.
- Tripwire alerts are logged + optionally spoken. Nothing auto-remediates.
- The anomaly monitor only observes tool-call patterns; it never blocks.
- The tool-call hook patches one LiveKit choke point inside try/except;
  if the patch or the monitoring throws, the tool still runs.
"""
from livekit.agents.llm import function_tool

import json
import os
import sys
import threading
import time

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
SEC_DIR = os.path.join(os.path.dirname(SKILL_DIR), "vagar-security")
if SEC_DIR not in sys.path:
    sys.path.insert(0, SEC_DIR)

from tool_anomaly import AnomalyMonitor
from vuln_scanner import scan as vuln_scan
from tripwire import Tripwire

_speak = None
anomaly_mon = AnomalyMonitor(speak_alert=lambda m: _speak(m) if _speak else None)
tripwire = Tripwire(speak_alert=lambda m: _speak(m) if _speak else None)

_tripwire_thread = None
_tripwire_stop = threading.Event()


def set_speak(fn):
    global _speak
    _speak = fn


def _tripwire_loop(interval_s=300):
    while not _tripwire_stop.wait(interval_s):
        try:
            for a in tripwire.check() or []:
                tripwire._log(a)
        except Exception:
            pass


def _ensure_background():
    global _tripwire_thread
    if _tripwire_thread and _tripwire_thread.is_alive():
        return
    _tripwire_stop.clear()
    _tripwire_thread = threading.Thread(target=_tripwire_loop, daemon=True)
    _tripwire_thread.start()


_ensure_background()


# --- per-tool-call anomaly hook -------------------------------------
# Patches livekit's _BaseFunctionTool.__call__ — the single choke point
# every tool executes through. The patch only OBSERVES: it records the
# tool name + success/failure in the anomaly monitor, then calls the
# original. If anything in the monitoring throws, the tool still runs.
def _install_tool_hook():
    try:
        from livekit.agents.llm.tool_context import _BaseFunctionTool
        _orig_call = _BaseFunctionTool.__call__

        def _hooked_call(self, *args, **kwargs):
            tool_name = getattr(self, "id", "unknown")
            try:
                result = _orig_call(self, *args, **kwargs)
            except Exception:
                try:
                    anomaly_mon.record(tool_name, ok=False)
                except Exception:
                    pass
                raise
            try:
                anomaly_mon.record(tool_name, ok=True)
            except Exception:
                pass
            return result

        _BaseFunctionTool.__call__ = _hooked_call
    except Exception:
        pass


_install_tool_hook()


@function_tool(
    name="security_scan",
    description="Run a defensive self-scan of Vagar's own services: checks listening ports, firewall rules, and unexpected exposure. Read-only.",
)
async def security_scan() -> str:
    findings = vuln_scan()
    return json.dumps(findings, indent=2)


@function_tool(
    name="security_status",
    description="Report the current defensive-security state: recent tool-call anomaly alerts and tripwire log location.",
)
async def security_status() -> str:
    recent = []
    try:
        with open(os.path.join(SEC_DIR, "anomaly_log.jsonl")) as f:
            recent = [json.loads(l) for l in f.readlines()[-5:]]
    except (OSError, ValueError):
        pass
    return json.dumps({
        "tools_seen": len(anomaly_mon.baseline),
        "recent_anomaly_alerts": recent,
        "tripwire_log": os.path.join(SEC_DIR, "tripwire_log.jsonl"),
    }, indent=2)
