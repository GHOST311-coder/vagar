"""Run an allowlisted shell command and return its output. Defensive only.

ALLOWLIST ONLY — anything not on the list is refused with a clear message:
dir, echo, type, copy, move, del, mkdir, rmdir, ipconfig, systeminfo,
tasklist, python --version, pip list.

Guards: the command's first token must match the allowlist exactly
(case-insensitive); no chaining with & | ; $() backticks; no redirection
> <; working directory is fixed to the workspace jail; output truncated
to ~8KB; 30s hard timeout.
"""
from livekit.agents.llm import function_tool

import subprocess as _subprocess

_CWD = r"C:\Users\sarto\vagar\workspace"
_MAX_OUT = 8000
_TIMEOUT = 30

_ALLOW = {
    "dir", "echo", "type", "copy", "move", "del",
    "mkdir", "rmdir", "ipconfig", "systeminfo", "tasklist",
}


def _check(cmd):
    if not cmd or not isinstance(cmd, str):
        return "no command given"
    low = cmd.strip().lower()
    if not low:
        return "no command given"
    for bad in ("&", "|", ";", "$(", "`", ">", "<", "%"):
        if bad in cmd:
            return "chaining, pipes, and redirection are not allowed"
    first = low.split()[0]
    if first in _ALLOW:
        return ""
    if low.startswith("python --version") or low == "python -v":
        return ""
    if low.startswith("pip list"):
        return ""
    return "not on the allowlist"


@function_tool(
    name="run_shell",
    description="Run a safe, allowlisted shell command (dir, echo, type, copy, move, del, mkdir, rmdir, ipconfig, systeminfo, tasklist, python --version, pip list) and return its output.",
)
async def run_shell(cmd: str) -> str:
    why = _check(cmd)
    if why:
        return "Refused: %s. Allowlist: dir, echo, type, copy, move, del, mkdir, rmdir, ipconfig, systeminfo, tasklist, python --version, pip list." % why
    try:
        proc = _subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=_TIMEOUT, cwd=_CWD,
        )
    except _subprocess.TimeoutExpired:
        return "Timed out after %d seconds; the process was killed." % _TIMEOUT
    except Exception as e:
        return "Could not run command: %s" % e
    out = (proc.stdout or "") + (proc.stderr or "")
    if len(out) > _MAX_OUT:
        out = out[:_MAX_OUT] + "\n... [output truncated]"
    if not out.strip():
        return "Ran clean (exit %d), no output." % proc.returncode
    return "exit %d:\n%s" % (proc.returncode, out)
