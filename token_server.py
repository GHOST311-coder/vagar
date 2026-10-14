#!/usr/bin/env python3
"""Vagar token server â€” tailnet only.

Mints short-lived LiveKit access tokens so the phone app can join the
"vagar" room on the local LiveKit server. Binds ONLY to the configured
interface (default localhost; set VAGAR_TOKEN_BIND to your Tailscale IP
for tailnet-only access).

Endpoints:
    GET /health -> "ok"
    GET /token  -> {"token": <jwt>, "url": "ws://<bind>:7880", "room": "vagar"}
    GET /status -> {"token_server": "ok", "livekit": ..., "ollama": ...,
                    "worker": ..., "avatar": ..., "watchdog_last_run": ...}
                    Live per-service health so the phone app can show
                    "Vagar is starting, please wait..." instead of a
                    cryptic timeout, and retry automatically.

Run: py -3.10 token_server.py
"""

import json
import socket
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt  # pyjwt, already installed for the laptop py3.10 env

BIND = os.environ.get("VAGAR_TOKEN_BIND", "127.0.0.1")  # bind interface -- set to your Tailscale IP for tailnet-only access, never 0.0.0.0
PORT = 7999
ROOM = "vagar"
API_KEY = os.environ.get("LIVEKIT_API_KEY", "your-livekit-api-key")        # matches livekit-server --dev --keys "devkey: ..."
SECRET_PATH = os.environ.get("VAGAR_LKSECRET", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".lksecret"))
TOKEN_TTL_S = 3600


def _secret() -> str:
    with open(SECRET_PATH, "r", encoding="utf-8") as f:
        return f.read().strip()


def make_token(identity: str) -> str:
    now = int(time.time())
    payload = {
        "iss": API_KEY,
        "sub": identity,
        "iat": now,
        "nbf": now,
        "exp": now + TOKEN_TTL_S,
        "video": {
            "roomJoin": True,
            "room": ROOM,
            "canPublish": True,
            "canSubscribe": True,
        },
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def _tcp_ok(host, port, timeout=3):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def _http_ok(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def system_status():
    """Live per-service health for the phone app and /status consumers."""
    import os
    status = {"token_server": "ok", "timestamp": int(time.time())}
    status["livekit"] = "ok" if _tcp_ok("127.0.0.1", 7880) else "down"
    status["ollama"] = "ok" if _http_ok("http://localhost:11434/api/tags") else "down"
    status["avatar"] = "ok" if _http_ok("http://localhost:8099/avatar.png") else "down"
    # Worker: heartbeat freshness. Stale/missing heartbeat + no process = down;
    # fresh heartbeat = ok; no heartbeat file yet = starting.
    try:
        hb = float(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "heartbeat.txt"), encoding="utf-8").read().strip().split()[0])
        age = time.time() - hb
        status["worker"] = "ok" if age < 180 else "stale"
        status["worker_heartbeat_age_s"] = round(age, 1)
    except Exception:
        status["worker"] = "starting"
    # Watchdog: when did it last run a pass?
    try:
        wd = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchdog_status.json"), encoding="utf-8"))
        status["watchdog_last_run"] = wd.get("last_run_iso")
        status["watchdog_services"] = wd.get("services", {})
    except Exception:
        status["watchdog_last_run"] = None
    # Overall: ok only if the phone-call path is fully live.
    status["overall"] = "ok" if (
        status["livekit"] == "ok" and status["worker"] == "ok"
    ) else "starting"
    return status


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            body = b"ok"
            self.send_response(200)
        elif self.path == "/status":
            body = json.dumps(system_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif self.path.startswith("/token"):
            body = json.dumps(
                {
                    "token": make_token("vagar-phone"),
                    "url": "ws://%s:7880" % BIND,
                    "room": ROOM,
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            self.send_response(404)
            body = b"not found"
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # phone disconnected mid-response; not fatal

    def log_message(self, *args):  # quiet
        pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    Server((BIND, PORT), Handler).serve_forever()

