"""Vagar flight recorder - DeepSeek-Harness-style run tracing for the local voice loop.

Every agent session gets its own JSONL file under
    <project-root>/flight-recorder/sessions\\<session_id>.jsonl
One JSON object per line: ts (ISO), session_id, event, plus event fields.

Design rules:
- stdlib only, so the offline log viewer (flightlog.py) can share it.
- record() is synchronous and guarded by a threading lock. (An asyncio lock
  was considered, but AgentSession event callbacks are synchronous and could
  never await it.)
- record() NEVER raises: all I/O is wrapped in try/except. A broken recorder
  must not take down the voice loop.
- Long text fields are truncated to ~500 chars; raw audio bytes are never logged.

Event types: session_start, stt_result (text, latency_ms), llm_response
(model, latency_ms, output_chars), tts_synth (chars, latency_ms),
tool_call (name, args_json, latency_ms, ok), error (where, message), session_end.
"""

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone

try:
    import sys as _cfg_sys
    from pathlib import Path as _cfg_Path
    _cfg_sys.path.insert(0, str(_cfg_Path(__file__).resolve().parent))
    from config import FLIGHT_RECORDER_DIR as _FRD
    DEFAULT_LOG_DIR = str(_FRD)
except Exception:  # pragma: no cover - standalone use without config.py
    DEFAULT_LOG_DIR = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "flight-recorder", "sessions")
MAX_TEXT_LEN = 500


def _safe_value(v):
    """Make a value log-safe: truncate long text, never log raw audio bytes."""
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "<%d bytes: audio/binary not logged>" % len(v)
    if isinstance(v, str) and len(v) > MAX_TEXT_LEN:
        return v[:MAX_TEXT_LEN] + "...[truncated]"
    return v


class FlightRecorder:
    """Append-only JSONL session log. Safe to call from sync or async code."""

    def __init__(self, log_dir: str = DEFAULT_LOG_DIR):
        self.log_dir = log_dir
        self._lock = threading.Lock()
        self._session_id = None
        self._path = None

    def start_session(self) -> str:
        """Begin a session; returns the session id. Records session_start."""
        sid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            self._path = os.path.join(self.log_dir, sid + ".jsonl")
            # touch the file so `flightlog list` sees the session immediately
            with open(self._path, "a", encoding="utf-8"):
                pass
        except Exception:
            self._path = None
        self._session_id = sid
        self.record("session_start")
        return sid

    @property
    def session_id(self):
        return self._session_id

    def record(self, event_type: str, **fields) -> None:
        """Append one event. Never raises, never blocks the agent."""
        try:
            if self._session_id is None or self._path is None:
                return
            line = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "session_id": self._session_id,
                "event": event_type,
            }
            for k, v in fields.items():
                try:
                    line[k] = _safe_value(v)
                except Exception:
                    line[k] = "<unserializable>"
            text = json.dumps(line, default=str, ensure_ascii=False)
            with self._lock:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(text + "\n")
        except Exception:
            pass  # the recorder must never crash the agent

    def end_session(self) -> None:
        """Record session_end and detach from the file."""
        try:
            self.record("session_end")
        finally:
            self._session_id = None
            self._path = None
