"""Activity broadcast sink for Vagar's live phone feed.

agent.py sets the sink to its LiveKit data-channel broadcaster at startup.
Skills and tools call emit() — safe to call from anywhere, never raises,
never blocks.
"""
_sink = None


def set_sink(fn):
    global _sink
    _sink = fn


def emit(text):
    try:
        if _sink is not None and text:
            _sink(str(text))
    except Exception:
        pass
