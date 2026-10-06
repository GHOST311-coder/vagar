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
            if self._failures >= self.threshold and self._tripped_at == 0:
                self._tripped_at = time.time()
                _log.warning("selfheal: breaker '%s' TRIPPED after %d failures",
                             self.name, self._failures)

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
