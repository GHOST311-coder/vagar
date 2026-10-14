#!/usr/bin/env python3
"""Vagar self-healing watchdog.

Runs every 5 minutes via the "Vagar Watchdog" scheduled task (as <user>).
Checks each local service and restarts whatever is unhealthy:

  - LiveKit server   : TCP 127.0.0.1:7880            -> schtasks \\Vagar LiveKit Server
  - Ollama           : HTTP localhost:11434/api/tags -> taskkill + WMI relaunch
  - Vagar worker     : heartbeat.txt freshness + process -> schtasks \\Vagar Worker
  - Avatar server    : HTTP localhost:8099/avatar.png -> schtasks \\Vagar Avatar Server
  - Token server     : TCP <tailnet>:7999            -> kill token_server.py
                                                     (token_run.bat loop restarts it)
                                                     or schtasks \\Vagar Token Server
                                                     if the bat itself is dead
  - Paperclip        : TCP <tailnet>:3100 (only if tailnet itself is up)
                                                     -> schtasks \\Paperclip
  - Access path      : Tailscale + sshd Windows services -> Start-Service
                       tailscale connectivity            -> tailscale up

Self-healing guarantees (added 2026-10-14 after a stuck watchdog left the
system dead â€” 267009 "task already running" blocked every later run):
  - PID-file lock: a new run exits if a live watchdog started <10 min ago.
    If the recorded PID is dead or older than 10 min, the stale run is
    killed and this run proceeds. A hung watchdog can never block healing.
  - Worker/token restarts prefer killing the crashed process and letting
    the batch-file loop restart it; schtasks /run is only used when the
    batch loop itself is dead.
  - Writes watchdog_status.json every pass so the phone app / health
    endpoint can show real state instead of a cryptic timeout.

Restart cooldown: at most one restart per service per 15 minutes, to avoid
restart loops when the underlying cause (e.g. Tailscale down) persists.

Logs to <VAGAR_HOME>/watchdog.log
"""

import datetime
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

VAGAR = os.environ.get("VAGAR_HOME", os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(VAGAR, "watchdog.log")
HEARTBEAT = os.path.join(VAGAR, "heartbeat.txt")
STATE = os.path.join(VAGAR, "watchdog_state.json")
PIDFILE = os.path.join(VAGAR, "watchdog.pid")
STATUSFILE = os.path.join(VAGAR, "watchdog_status.json")
TAILNET_IP = os.environ.get("VAGAR_TAILNET_IP", "127.0.0.1")  # set to your Tailscale IP if the token server binds to the tailnet interface
COOLDOWN_S = 15 * 60
HEARTBEAT_MAX_AGE_S = 180
WATCHDOG_STALE_S = 10 * 60  # a watchdog run older than this is hung; kill it


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "%s [watchdog] %s" % (ts, msg)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(s, f)
    except Exception:
        pass


def pid_alive(pid):
    """True if the given PID exists (Windows tasklist)."""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "PID eq %d" % pid],
            capture_output=True, text=True, timeout=15,
        )
        return str(pid) in (r.stdout or "")
    except Exception:
        return False


def acquire_lock():
    """PID-file guard against a stuck watchdog blocking all future runs.

    Returns True if this run may proceed (no live watchdog, or the stale
    one was killed). Returns False if another live watchdog started less
    than WATCHDOG_STALE_S ago â€” this run exits cleanly so the scheduler's
    next tick can try again. A hung watchdog can never wedge the system:
    after 10 minutes the next run kills it and takes over.
    """
    now = time.time()
    try:
        with open(PIDFILE, encoding="utf-8") as f:
            old_pid, old_ts = f.read().strip().split()
            old_pid, old_ts = int(old_pid), float(old_ts)
    except Exception:
        old_pid, old_ts = None, 0
    if old_pid and pid_alive(old_pid):
        age = now - old_ts
        if age < WATCHDOG_STALE_S:
            log("watchdog already running (pid %d, %.0fs old); exiting" % (old_pid, age))
            return False
        log("stale watchdog pid %d (%.0fs old) â€” killing and taking over" % (old_pid, age))
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(old_pid)],
                           capture_output=True, timeout=15)
        except Exception as e:
            log("kill stale watchdog failed: %s" % e)
        time.sleep(1)
    try:
        with open(PIDFILE, "w", encoding="utf-8") as f:
            f.write("%d %f" % (os.getpid(), now))
    except Exception:
        pass
    return True


def write_status(statuses, restarts):
    """Write a machine-readable health snapshot for the /status endpoint."""
    try:
        with open(STATUSFILE, "w", encoding="utf-8") as f:
            json.dump({
                "last_run": time.time(),
                "last_run_iso": datetime.datetime.now().isoformat(),
                "services": statuses,
                "restarts_this_pass": restarts,
            }, f)
    except Exception:
        pass


def bat_alive(fragment):
    """True if a cmd.exe process is running a batch file matching fragment."""
    ps = ("Get-CimInstance Win32_Process -Filter \"name='cmd.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "Select-Object -ExpandProperty ProcessId" % fragment)
    try:
        r = subprocess.run(["powershell", "-noprofile", "-c", ps],
                           capture_output=True, text=True, timeout=30)
        return any(x.strip().isdigit() for x in r.stdout.split())
    except Exception:
        return False


def kill_procs(fragment):
    """Force-kill all python.exe processes whose command line contains fragment."""
    for pid in ps_query(fragment):
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=15)
        except Exception:
            pass


def tcp_ok(host, port, timeout=5):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def http_ok(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def ps_query(fragment):
    """Return list of PIDs for python.exe processes whose command line contains fragment."""
    ps = (
        "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*%s*' } | "
        "Select-Object -ExpandProperty ProcessId" % fragment
    )
    try:
        r = subprocess.run(
            ["powershell", "-noprofile", "-c", ps],
            capture_output=True, text=True, timeout=30,
        )
        return [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    except Exception:
        return []


def any_proc(name, fragment=None):
    """True if a process with the given exe name (and optional cmdline fragment) exists."""
    filt = "name='%s'" % name
    ps = "Get-CimInstance Win32_Process -Filter \"%s\" | Select-Object -ExpandProperty ProcessId" % filt
    try:
        r = subprocess.run(
            ["powershell", "-noprofile", "-c", ps],
            capture_output=True, text=True, timeout=30,
        )
        pids = [x for x in r.stdout.split() if x.strip().isdigit()]
        if not pids or not fragment:
            return bool(pids)
        # filter by command line
        ps2 = (
            "Get-CimInstance Win32_Process -Filter \"%s\" | "
            "Where-Object { $_.CommandLine -like '*%s*' } | "
            "Select-Object -ExpandProperty ProcessId" % (filt, fragment)
        )
        r2 = subprocess.run(
            ["powershell", "-noprofile", "-c", ps2],
            capture_output=True, text=True, timeout=30,
        )
        return any(x.strip().isdigit() for x in r2.stdout.split())
    except Exception:
        return False


def restart_task(task_name, verify=None, verify_timeout=30):
    """Restart a scheduled task and verify the service actually came back.

    schtasks /run alone is not enough: with MultipleInstancesPolicy=IgnoreNew
    it silently no-ops on an already-"Running" task. So: /end first, then
    /run, then poll the verify() callable until it reports healthy or the
    timeout expires. Returns True only if verification passed.
    """
    # Strip leading backslash: schtasks /tn "\Vagar Worker" fails with
    # "Access is denied" / "file not found", but "Vagar Worker" works.
    task_name = task_name.lstrip("\\")
    log("restarting scheduled task %s" % task_name)
    try:
        subprocess.run(["schtasks", "/end", "/tn", task_name],
                       capture_output=True, text=True, timeout=30)
    except Exception:
        pass
    time.sleep(2)
    try:
        r = subprocess.run(["schtasks", "/run", "/tn", task_name],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            log("schtasks /run %s -> FAILED: %s" % (task_name, r.stderr.strip()[-120:]))
            return False
    except Exception as e:
        log("schtasks /run %s failed: %s" % (task_name, e))
        return False
    if verify is None:
        return True
    deadline = time.time() + verify_timeout
    while time.time() < deadline:
        try:
            if verify():
                log("restart %s verified healthy" % task_name)
                return True
        except Exception:
            pass
        time.sleep(5)
    log("restart %s NOT verified healthy after %ds" % (task_name, verify_timeout))
    return False


def restart_worker():
    """Restart the Vagar worker (agent.py).

    Preferred path: kill agent.py and let worker_run.bat's loop restart it
    in seconds â€” no task juggling, no orphaned children. Fallback: if the
    batch loop itself is dead, restart the scheduled task (verified).
    """
    if bat_alive("worker_run.bat"):
        log("worker: batch loop alive; killing agent.py so it restarts")
        kill_procs("agent.py")
        time.sleep(15)
        if ps_query("agent.py"):
            log("worker: agent.py back after bat-loop restart")
            return True
        log("worker: agent.py NOT back after bat-loop restart; falling through to task restart")
    return restart_task("\\Vagar Worker",
                        verify=lambda: bool(ps_query("agent.py")),
                        verify_timeout=90)


def restart_token():
    """Restart the token server (phone app auth).

    Preferred path: kill token_server.py and let token_run.bat's loop
    restart it. Fallback: restart the scheduled task (verified).
    """
    if bat_alive("token_run.bat"):
        log("token_server: batch loop alive; killing token_server.py so it restarts")
        kill_procs("token_server.py")
        time.sleep(15)
        if tcp_ok(TAILNET_IP, 7999):
            log("token_server: back after bat-loop restart")
            return True
        log("token_server: NOT back after bat-loop restart; falling through to task restart")
    return restart_task("\\Vagar Token Server",
                        verify=lambda: tcp_ok(TAILNET_IP, 7999),
                        verify_timeout=60)


def svc_running(svc_name):
    """True if the named Windows service is in the Running state."""
    ps = ("try { (Get-Service -Name '%s' -ErrorAction Stop).Status "
          "-eq 'Running' } catch { $false }" % svc_name)
    try:
        r = subprocess.run(
            ["powershell", "-noprofile", "-c", ps],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip().lower() == "true"
    except Exception:
        return False


def start_service(svc_name):
    """Start a Windows service by name. Returns True if the start command succeeded."""
    log("starting windows service %s" % svc_name)
    ps = ("try { Start-Service -Name '%s' -ErrorAction Stop; 'SVC_OK' } "
          "catch { 'SVC_FAIL:' + $_.Exception.Message }" % svc_name)
    try:
        r = subprocess.run(
            ["powershell", "-noprofile", "-c", ps],
            capture_output=True, text=True, timeout=60,
        )
        ok = "SVC_OK" in (r.stdout or "")
        log("start-service %s -> %s" % (svc_name, "OK" if ok else (r.stdout or "").strip()[-120:]))
        return ok
    except Exception as e:
        log("start-service %s failed: %s" % (svc_name, e))
        return False


def _tailscale_exe():
    return os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                        "Tailscale", "tailscale.exe")


def tailscale_connected():
    """True if tailscale reports this node as connected (has a tailnet address)."""
    try:
        r = subprocess.run(
            [_tailscale_exe(), "status", "--self=false"],
            capture_output=True, text=True, timeout=30,
        )
        out = r.stdout or ""
        return ("100." in out or "fd7a:" in out) and "Logged out" not in out
    except Exception:
        return False


def tailscale_up():
    """Bring tailscale back up using existing auth (never triggers a re-auth flow)."""
    log("tailscale: attempting 'tailscale up' with existing auth")
    try:
        r = subprocess.run(
            [_tailscale_exe(), "up"],
            capture_output=True, text=True, timeout=90,
        )
        ok = (r.returncode == 0)
        log("tailscale up -> %s" % ("OK" if ok else (r.stderr or r.stdout or "").strip()[-160:]))
        return ok
    except Exception as e:
        log("tailscale up failed: %s" % e)
        return False


def restart_ollama():
    log("ollama unhealthy; killing and relaunching via WMI")
    try:
        subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"],
                       capture_output=True, timeout=30)
    except Exception as e:
        log("taskkill ollama: %s" % e)
    time.sleep(3)
    # NOTE (2026-10-06): launch via ollama_wmi.bat, NOT ollama.exe directly.
    # The bat sets OLLAMA_MODELS (model dir) and OLLAMA_NUM_GPU=0.
    # Session-0 WMI launches hang the model runner during GPU probing
    # without OLLAMA_NUM_GPU=0 (found live: /api/tags OK, generations wedged).
    _ollama_bat = os.path.join(VAGAR, "text_chat", "ollama_wmi.bat")
    _ollama_dir = os.path.join(VAGAR, "text_chat")
    ps = (
        "$p = ([wmiclass]'Win32_Process').Create("
        "'cmd /c %s', " % _ollama_bat +
        "'%s'); " % _ollama_dir +
        "if ($p.ReturnValue -eq 0) { 'WMI_OK:' + $p.ProcessId } "
        "else { 'WMI_FAIL:' + $p.ReturnValue }"
    )
    try:
        r = subprocess.run(["powershell", "-noprofile", "-c", ps],
                           capture_output=True, text=True, timeout=60)
        out = (r.stdout or "").strip()
        log("ollama WMI relaunch: %s" % out[-100:])
        return "WMI_OK" in out
    except Exception as e:
        log("ollama WMI relaunch failed: %s" % e)
        return False


def main():
    state = load_state()
    last_restart = state.get("last_restart", {})
    now = time.time()
    restarts = 0
    statuses = {}

    def cooled(name):
        return (now - last_restart.get(name, 0)) >= COOLDOWN_S

    def mark(name):
        last_restart[name] = time.time()
        state["last_restart"] = last_restart
        save_state(state)

    # ---- 0. Access path self-heal (Tailscale + SSH) ----
    # Rumi's only way in. Heal the foundation before checking dependents.
    for _svc in ("Tailscale", "sshd"):
        if svc_running(_svc):
            log("access: %s service Running" % _svc)
        elif cooled("svc_" + _svc):
            log("access: %s service NOT running; starting" % _svc)
            if start_service(_svc):
                mark("svc_" + _svc)
                restarts += 1
        else:
            log("access: %s down but in cooldown; skipping" % _svc)
    if tailscale_connected():
        log("access: tailscale connected")
    elif cooled("tailscale_up"):
        log("access: tailscale NOT connected; attempting repair")
        if tailscale_up():
            mark("tailscale_up")
            restarts += 1
    else:
        log("access: tailscale down but in cooldown; skipping")

    # ---- 1. LiveKit server ----
    if tcp_ok("127.0.0.1", 7880):
        log("livekit: OK (port 7880)")
        statuses["livekit"] = "ok"
    elif cooled("livekit"):
        log("livekit: DOWN on 127.0.0.1:7880")
        statuses["livekit"] = "down"
        if restart_task("\\Vagar LiveKit Server"):
            mark("livekit")
            restarts += 1
    else:
        log("livekit: DOWN but in cooldown; skipping restart")
        statuses["livekit"] = "down-cooldown"

    # ---- 2. Ollama (brain + vision) ----
    if http_ok("http://localhost:11434/api/tags", timeout=10):
        log("ollama: OK (/api/tags)")
        statuses["ollama"] = "ok"
    elif cooled("ollama"):
        log("ollama: DOWN (no /api/tags response)")
        statuses["ollama"] = "down"
        if restart_ollama():
            mark("ollama")
            restarts += 1
    else:
        log("ollama: DOWN but in cooldown; skipping restart")
        statuses["ollama"] = "down-cooldown"

    # ---- 3. Vagar worker (heartbeat + process) ----
    hb_age = None
    try:
        hb_age = now - float(open(HEARTBEAT, encoding="utf-8").read().strip().split()[0])
    except Exception:
        hb_age = None
    worker_procs = ps_query("agent.py")
    if hb_age is not None and hb_age < HEARTBEAT_MAX_AGE_S:
        log("worker: OK (heartbeat %.0fs ago, %d proc)" % (hb_age, len(worker_procs)))
        statuses["worker"] = "ok"
    elif not worker_procs:
        statuses["worker"] = "down"
        if cooled("worker"):
            log("worker: NO agent.py process; restarting")
            if restart_worker():
                mark("worker")
                restarts += 1
        else:
            log("worker: no process but in cooldown; skipping")
    elif hb_age is None:
        # Process alive but no heartbeat yet (pre-patch worker or just starting):
        # warn only, do not kill â€” the heartbeat patch lands on next worker start.
        log("worker: WARN no heartbeat.txt yet but %d proc alive; skipping restart" % len(worker_procs))
        statuses["worker"] = "starting"
    elif cooled("worker"):
        log("worker: HUNG (heartbeat %.0fs stale, %d proc); killing + restarting" % (hb_age, len(worker_procs)))
        statuses["worker"] = "hung"
        if restart_worker():
            mark("worker")
            restarts += 1
    else:
        log("worker: heartbeat stale but in cooldown; skipping restart")
        statuses["worker"] = "stale-cooldown"

    # ---- 4. Avatar server (APK + avatar assets) ----
    if http_ok("http://localhost:8099/avatar.png", timeout=10):
        log("avatar_server: OK (port 8099)")
        statuses["avatar_server"] = "ok"
    elif cooled("avatar_server"):
        log("avatar_server: DOWN on :8099")
        statuses["avatar_server"] = "down"
        if restart_task("\\Vagar Avatar Server"):
            mark("avatar_server")
            restarts += 1
    else:
        log("avatar_server: DOWN but in cooldown; skipping restart")
        statuses["avatar_server"] = "down-cooldown"

    # ---- 5. Token server (phone app auth) ----
    # NOTE: token_server binds to the TAILNET interface (see VAGAR_TAILNET_IP),
    # NOT loopback. Checking 127.0.0.1:7999 always reported DOWN â€” that
    # wrong-address check is what made the old watchdog spam restarts.
    if tcp_ok(TAILNET_IP, 7999):
        log("token_server: OK (%s:7999)" % TAILNET_IP)
        statuses["token_server"] = "ok"
    elif cooled("token_server"):
        log("token_server: DOWN on %s:7999" % TAILNET_IP)
        statuses["token_server"] = "down"
        if restart_token():
            mark("token_server")
            restarts += 1
    else:
        log("token_server: DOWN but in cooldown; skipping restart")
        statuses["token_server"] = "down-cooldown"

    # ---- 6. Paperclip (only restart if the tailnet itself is up) ----
    if tcp_ok(TAILNET_IP, 3100, timeout=8):
        log("paperclip: OK (%s:3100)" % TAILNET_IP)
        statuses["paperclip"] = "ok"
    else:
        tailnet_up = tcp_ok(TAILNET_IP, 22, timeout=8)  # SSH is the known-good signal
        if not tailnet_up:
            log("paperclip: UNREACHABLE and tailnet looks down; skipping (nothing to heal)")
            statuses["paperclip"] = "tailnet-down"
        elif cooled("paperclip"):
            log("paperclip: DOWN but tailnet is up; restarting task")
            statuses["paperclip"] = "down"
            if restart_task("\\Paperclip"):
                mark("paperclip")
                restarts += 1
        else:
            log("paperclip: DOWN but in cooldown; skipping restart")
            statuses["paperclip"] = "down-cooldown"

    # ---- 7. Disk space (alert only, no auto-fix) ----
    try:
        import shutil as _sh
        _du = _sh.disk_usage("C:\\")
        _free_gb = _du.free / (1024 ** 3)
        _pct_free = 100.0 * _du.free / _du.total
        if _free_gb < 10 or _pct_free < 10:
            log("disk: WARNING only %.1f GB (%.0f%%) free on C: - cleanup needed" % (_free_gb, _pct_free))
        else:
            log("disk: OK (%.1f GB free)" % _free_gb)
    except Exception as e:
        log("disk: check failed: %s" % e)

    # ---- 8. Ollama model health (alert only) ----
    try:
        _req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(_req, timeout=10) as _resp:
            _tags = json.load(_resp).get("models", [])
        _have = set()
        for _m in _tags:
            _n = _m.get("name", "")
            # normalize "qwen2.5:0.5b" etc; also match "moondream:latest"
            _have.add(_n.split(":")[0])
            _have.add(_n)
        _need = {"qwen2.5:0.5b": "fast brain", "qwen2.5:3b": "deep brain",
                 "moondream": "vision"}
        _missing = [k for k in _need if k not in _have and k.split(":")[0] not in _have]
        if _missing:
            log("models: WARNING missing: %s" % ", ".join(
                "%s (%s)" % (m, _need[m]) for m in _missing))
        else:
            log("models: OK (0.5b, 3b, moondream present)")
    except Exception as e:
        log("models: check failed (ollama down?): %s" % e)

    log("watchdog pass complete, %d restart(s)" % restarts)
    write_status(statuses, restarts)


if __name__ == "__main__":
    try:
        if not acquire_lock():
            sys.exit(0)
        main()
    except Exception as e:
        log("FATAL: %s" % e)
        sys.exit(1)


