"""YOLO real-time object detection for Vagar's Jarvis vision.

Runs YOLOv8n on camera frames in background threads, maintaining a live
inventory of visible objects per source (phone, laptop). The agent reads
this state to answer "what do you see?" instantly, without waiting for
Moondream. Moondream remains the fallback for rich descriptions.

Thread-safe. Never crashes the worker. Local only, no network.
"""
import os
import threading
import time
import logging

_log = logging.getLogger("vagar.yolo")

# Per-source live inventory:
# {"phone": {"objects": {...}, "ts": 0.0, ...}, "laptop": {...}}
_sources = {}
_lock = threading.Lock()
_model = None
_runners = {}

try:
    import sys as _cfg_sys
    from pathlib import Path as _cfg_Path
    _cfg_sys.path.insert(0, str(_cfg_Path(__file__).resolve().parent))
    from config import YOLO_MODEL_PATH as _YMP
    MODEL_PATH = str(_YMP)
except Exception:  # pragma: no cover - standalone use without config.py
    MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "models", "yolov8n.pt")
SCAN_INTERVAL = 1.0   # seconds between scans (plenty for "what's in the room")
IMG_SIZE = 416        # balance of speed vs small-object recall
CONF = 0.45           # confidence threshold


def _load():
    global _model
    if _model is not None:
        return _model
    from ultralytics import YOLO
    _model = YOLO(MODEL_PATH)
    _log.info("yolo: model loaded")
    return _model


def _blank_state():
    return {"objects": {}, "ts": 0.0, "frame_ts": 0.0, "fps": 0.0, "errors": 0}


def _watch_loop(name, frame_bucket, interval):
    _log.info("yolo: watcher starting for %s", name)
    try:
        model = _load()
    except Exception as e:
        _log.error("yolo: model load failed: %s: %s", type(e).__name__, e)
        return
    import numpy as np
    last = 0.0
    with _lock:
        _sources[name] = _blank_state()
    while _runners.get(name):
        try:
            now = time.time()
            if now - last < interval:
                time.sleep(0.2)
                continue
            last = now
            raw, w, h, ts = frame_bucket.get()
            if raw is None or (now - ts) > 10:
                continue  # no fresh frame
            t0 = time.time()
            img = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3)
            res = model(img, verbose=False, imgsz=IMG_SIZE, conf=CONF)[0]
            counts = {}
            if res.boxes is not None:
                for c in res.boxes.cls:
                    cname = model.names[int(c)]
                    counts[cname] = counts.get(cname, 0) + 1
            dt = time.time() - t0
            with _lock:
                st = _sources.get(name, _blank_state())
                st["objects"] = counts
                st["ts"] = now
                st["frame_ts"] = ts
                st["fps"] = 1.0 / dt if dt > 0 else 0.0
                st["errors"] = 0
                _sources[name] = st
        except Exception as e:
            with _lock:
                st = _sources.get(name, _blank_state())
                st["errors"] += 1
                _sources[name] = st
            _log.warning("yolo: %s scan failed: %s: %s",
                         name, type(e).__name__, e)
            time.sleep(2.0)
    _log.info("yolo: watcher stopped for %s", name)


def start(frame_bucket, name="phone", interval=SCAN_INTERVAL):
    """Start a background watcher for a frame source. Idempotent per name."""
    if _runners.get(name):
        return
    _runners[name] = True
    t = threading.Thread(target=_watch_loop, args=(name, frame_bucket, interval),
                         daemon=True, name=f"yolo-watch-{name}")
    t.start()
    _log.info("yolo: watcher thread started for %s", name)


def stop(name=None):
    if name:
        _runners[name] = False
    else:
        for k in list(_runners):
            _runners[k] = False


def get_state(name="phone"):
    with _lock:
        return dict(_sources.get(name, _blank_state()))


def _summarize(objects):
    parts = []
    for cname, n in sorted(objects.items(), key=lambda kv: -kv[1]):
        parts.append(f"{n} {cname}s" if n > 1 else f"a {cname}")
    if len(parts) == 1:
        return f"I see {parts[0]}"
    return "I see " + ", ".join(parts[:-1]) + f", and {parts[-1]}"


def get_visible_summary(max_age=8.0, prefer="phone"):
    """Human-readable summary of what's currently visible.

    Prefers the phone camera; falls back to the laptop webcam.
    Returns (summary, source) or (None, None) if nothing fresh.
    """
    with _lock:
        snap = {k: dict(v) for k, v in _sources.items()}
    now = time.time()
    order = [prefer] + [k for k in snap if k != prefer]
    for name in order:
        st = snap.get(name)
        if not st:
            continue
        if now - st["ts"] > max_age or not st["objects"]:
            continue
        return _summarize(st["objects"]), name
    return None, None
