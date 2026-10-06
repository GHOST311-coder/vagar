"""flightlog - offline viewer for Vagar flight-recorder sessions.

Reads <project-root>/flight-recorder/sessions/*.jsonl (stdlib only).

Usage:
    py -3.10 flightlog.py list              # sessions, newest first
    py -3.10 flightlog.py show <session_id> # pretty timeline (prefix match ok)
    py -3.10 flightlog.py tail              # follow the latest session live
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

try:
    import sys as _cfg_sys
    from pathlib import Path as _cfg_Path
    _cfg_sys.path.insert(0, str(_cfg_Path(__file__).resolve().parent))
    from config import FLIGHT_RECORDER_DIR as _FRD
    LOG_DIR = str(_FRD)
except Exception:  # pragma: no cover - standalone use without config.py
    LOG_DIR = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "flight-recorder", "sessions")


def _sessions():
    if not os.path.isdir(LOG_DIR):
        return []
    out = []
    for name in os.listdir(LOG_DIR):
        if not name.endswith(".jsonl"):
            continue
        p = os.path.join(LOG_DIR, name)
        try:
            st = os.stat(p)
            with open(p, encoding="utf-8") as f:
                n = sum(1 for _ in f)
        except OSError:
            continue
        out.append(
            {"id": name[:-len(".jsonl")], "path": p,
             "mtime": st.st_mtime, "events": n, "bytes": st.st_size}
        )
    out.sort(key=lambda s: s["mtime"], reverse=True)
    return out


def cmd_list(_args):
    ss = _sessions()
    if not ss:
        print("no sessions yet in " + LOG_DIR)
        return
    for s in ss:
        when = datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
        print("%s  %s  %4d events  %d KB" % (s["id"], when, s["events"], s["bytes"] // 1024))


def _find(prefix):
    matches = [s for s in _sessions() if s["id"].startswith(prefix)]
    if not matches:
        print("no session matching %r" % prefix)
        sys.exit(1)
    if len(matches) > 1:
        print("ambiguous prefix, matches:")
        for m in matches:
            print("  " + m["id"])
        sys.exit(1)
    return matches[0]


def _fmt_ts(ts):
    try:
        return datetime.fromisoformat(ts).astimezone().strftime("%H:%M:%S.%f")[:-3]
    except Exception:
        return str(ts)[:12]


def _fmt_line(obj):
    parts = []
    for k in ("text", "name", "model", "where", "message", "source"):
        v = obj.get(k)
        if v not in (None, ""):
            parts.append("%s=%s" % (k, str(v)[:80]))
    for k in ("latency_ms", "chars", "input_chars", "output_chars", "ok"):
        v = obj.get(k)
        if v is not None:
            parts.append("%s=%s" % (k, v))
    return "[%s] %-14s %s" % (_fmt_ts(obj.get("ts", "")), obj.get("event", "?"), "  ".join(parts))


def cmd_show(args):
    s = _find(args.session_id)
    print("== %s ==" % s["id"])
    with open(s["path"], encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                print(_fmt_line(json.loads(line)))
            except Exception:
                print("  <unparseable line>")


def cmd_tail(_args):
    ss = _sessions()
    if not ss:
        print("no sessions yet in " + LOG_DIR)
        return
    s = ss[0]
    print("following %s  (Ctrl+C to stop)" % s["id"])
    try:
        with open(s["path"], encoding="utf-8") as f:
            f.seek(0, 2)  # start at end; only new lines
            while True:
                line = f.readline()
                if line:
                    try:
                        print(_fmt_line(json.loads(line.strip())), flush=True)
                    except Exception:
                        pass
                else:
                    time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nstopped")


def main():
    ap = argparse.ArgumentParser(description="View Vagar flight-recorder sessions")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list sessions, newest first")
    p_show = sub.add_parser("show", help="pretty-print one session timeline")
    p_show.add_argument("session_id", help="full id or unique prefix")
    sub.add_parser("tail", help="follow the latest session live")
    args = ap.parse_args()
    {"list": cmd_list, "show": cmd_show, "tail": cmd_tail}[args.cmd](args)


if __name__ == "__main__":
    main()
