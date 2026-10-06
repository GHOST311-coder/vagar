"""Vagar self-healing layer 2: circuit breakers + graceful degradation.

Layer 1 (watchdog) restarts dead processes. This layer handles *degraded*
components without restarts:
- Vision breaker: if Moondream fails 3x in a row, trip for 5 min. While
  tripped, describe_camera_frame uses YOLO object labels only (instant,
  no LLM wait) instead of hammering a broken model.
- LLM breaker: if the deep-think model times out 3x, fall back to the
  fast model for 5 min.
- Supervisor: watches the YOLO + laptop-cam threads; restarts any whose
  state goes stale (>30s). Threads are cheap to restart, no worker
  restart needed.

Nothing here rewrites code or deploys changes. It degrades gracefully,
recovers automatically, and logs everything. Code fixes still go
through the owner's approval gate, per his standing rule.

Thread-safe. Never crashes the worker.
"""
import os
import sys
import threading
import time
import logging

_log = logging.getLogger("vagar.selfheal")


class CircuitBreaker:
    """Trips after N consecutive failures, auto-resets after cooldown."""

    def __init__(self, name, threshold=3, cooldown=300):
        self.name = name
        self.threshold = threshold
        self.cooldown = cooldown
        self._lock = threading.Lock()
        self._failures = 0
        self._tripped_at = 0.0

    def is_tripped(self):
        with self._lock:
            if self._tripped_at == 0:
                return False
            if time.time() - self._tripped_at >= self.cooldown:
                _log.info("selfheal: breaker '%s' cooldown over, resetting",
                          self.name)
                self._tripped_at = 0.0
                self._failures = 0
                return False
            return True

    def record_success(self):
        with self._lock:
            self._failures = 0

    def record_failure(self):
        with self._lock:
            self._failures += 1
            tripped_now = False
            if self._failures >= self.threshold and self._tripped_at == 0:
                self._tripped_at = time.time()
                tripped_now = True
                _log.warning("selfheal: breaker '%s' TRIPPED after %d failures",
                             self.name, self._failures)
        # Hand the trip to the evolving healer off the hot path: it runs
        # ranked recovery strategies, journals outcomes, and stages an
        # escalation for owner if everything fails. Never blocks here.
        if tripped_now:
            _notify_healer_of_trip(self)

    def status(self):
        with self._lock:
            return {"name": self.name, "failures": self._failures,
                    "tripped": self._tripped_at != 0,
                    "tripped_at": self._tripped_at}


# Global breakers
vision_breaker = CircuitBreaker("vision-moondream", threshold=3, cooldown=300)
llm_breaker = CircuitBreaker("llm-deepthink", threshold=3, cooldown=300)

_supervisor_running = False


def _supervisor_loop():
    """Restart stale watcher threads without a worker restart."""
    global _supervisor_running
    _log.info("selfheal: supervisor starting")
    while _supervisor_running:
        try:
            time.sleep(30)
            # YOLO watchers
            try:
                import yolo_watch as _yw
                now = time.time()
                for src in ("phone", "laptop"):
                    st = _yw.get_state(src)
                    # Only supervise sources that were started (have a runner)
                    if _yw._runners.get(src) and now - st["ts"] > 45 and st["ts"] > 0:
                        _log.warning("selfheal: yolo-%s stale, restarting", src)
                        _yw.stop(src)
                        time.sleep(1)
                        # Re-resolve the bucket
                        if src == "phone":
                            import __main__ as _m
                            bucket = getattr(_m, "frame_bucket", None)
                        else:
                            import laptop_cam as _lc
                            bucket = _lc.laptop_frame_bucket
                        if bucket is not None:
                            _yw.start(bucket, name=src,
                                      interval=1.0 if src == "phone" else 2.0)
                            _journal_restart("yolo_watch",
                                             "yolo-%s stale >45s, restarted" % src)
            except Exception as e:
                _log.warning("selfheal: yolo supervise failed: %s", e)
            # Laptop cam
            try:
                import laptop_cam as _lc2
                if _lc2._running:
                    _, _, _, ts = _lc2.get_frame()
                    # If never produced a frame in 90s, restart
                    if ts == 0 and time.time() - _supervisor_start > 90:
                        _log.warning("selfheal: laptopcam never produced, restarting")
                        _lc2.stop()
                        time.sleep(1)
                        _lc2.start()
                        _journal_restart("laptop_cam",
                                         "laptopcam never produced a frame, restarted")
            except Exception as e:
                _log.warning("selfheal: laptopcam supervise failed: %s", e)
        except Exception as e:
            _log.warning("selfheal: supervisor loop error: %s", e)
    _log.info("selfheal: supervisor stopped")


_supervisor_start = time.time()


def start_supervisor():
    global _supervisor_running, _supervisor_start
    if _supervisor_running:
        return
    _supervisor_running = True
    _supervisor_start = time.time()
    t = threading.Thread(target=_supervisor_loop, daemon=True,
                         name="selfheal-supervisor")
    t.start()


def stop_supervisor():
    global _supervisor_running
    _supervisor_running = False


def breaker_status():
    return {"vision": vision_breaker.status(), "llm": llm_breaker.status()}


_escalation_lock = threading.Lock()
_pending_escalation = None


def set_pending_escalation(msg):
    """Stage a spoken alert for owner; delivered once at next session start."""
    global _pending_escalation
    try:
        with _escalation_lock:
            if _pending_escalation is None:
                _pending_escalation = msg
    except Exception:
        pass


def pop_pending_escalation():
    """Return and clear the staged escalation message, if any."""
    global _pending_escalation
    try:
        with _escalation_lock:
            msg = _pending_escalation
            _pending_escalation = None
            return msg
    except Exception:
        return None


def _ensure_healer_importable():
    """Make evolving_healer (lives in skills/) importable."""
    try:
        skills_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "skills")
        if skills_dir not in sys.path:
            sys.path.insert(0, skills_dir)
    except Exception:
        pass


def _notify_healer_of_trip(breaker):
    """Run the evolving healer's trip handler on a daemon thread."""
    def _run():
        try:
            _ensure_healer_importable()
            import evolving_healer as _eh
            _eh.on_breaker_tripped(breaker.name, breaker)
        except Exception as e:
            _log.warning("selfheal: healer trip hook failed: %s", e)
    try:
        t = threading.Thread(target=_run, daemon=True, name="healer-trip")
        t.start()
    except Exception:
        pass


def _journal_restart(service, detail):
    """Journal a supervisor thread restart as a healing event."""
    try:
        _ensure_healer_importable()
        import evolving_healer as _eh2
        _eh2.log_healing_event(service, "stale_thread", "restart_thread",
                               "success", notes=detail[:200])
    except Exception:
        pass
