"""Laptop webcam capture for Vagar's Jarvis vision.

Second set of eyes: when the phone camera is off (the user at their laptop),
Vagar can still see through the built-in webcam. Captures at low FPS into
laptop_frame_bucket; the YOLO watcher scans it the same as phone frames.

Thread-safe. Never crashes the worker. Local only.
"""
import threading
import time
import logging

_log = logging.getLogger("vagar.laptopcam")


class _FrameBucket:
    def __init__(self):
        self._lock = threading.Lock()
        self._buf = None
        self._w = 0
        self._h = 0
        self._ts = 0.0

    def put(self, buf: bytes, w: int, h: int):
        with self._lock:
            self._buf, self._w, self._h, self._ts = buf, w, h, time.time()

    def get(self):
        with self._lock:
            return self._buf, self._w, self._h, self._ts


laptop_frame_bucket = _FrameBucket()
_running = False
CAPTURE_INTERVAL = 2.0  # seconds between captures (secondary source)


def _capture_loop():
    global _running
    _log.info("laptopcam: starting")
    try:
        import cv2
    except Exception as e:
        _log.error("laptopcam: no opencv: %s", e)
        return
    cap = None
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            _log.warning("laptopcam: no webcam found")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        _log.info("laptopcam: webcam open")
        while _running:
            try:
                ok, frame = cap.read()
                if ok and frame is not None:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w = rgb.shape[:2]
                    laptop_frame_bucket.put(rgb.tobytes(), w, h)
                time.sleep(CAPTURE_INTERVAL)
            except Exception as e:
                _log.warning("laptopcam: capture failed: %s: %s",
                             type(e).__name__, e)
                time.sleep(2.0)
    finally:
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass
        _log.info("laptopcam: stopped")


def start():
    """Start webcam capture. Idempotent."""
    global _running
    if _running:
        return
    _running = True
    t = threading.Thread(target=_capture_loop, daemon=True, name="laptop-cam")
    t.start()


def stop():
    global _running
    _running = False


def get_frame():
    return laptop_frame_bucket.get()
