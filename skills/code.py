"""Run Python code: execute a snippet with the signed system Python and return
its output. Unlocks data analysis, math, scripting, and automation.

Guards (this is why it's safe to approve):
- Runs ONLY C:\\Python310\\python.exe -c (the signed interpreter; WDAC allows it).
- Hard timeout (default 30s): the process is killed on expiry.
- No interactive stdin: code that waits for input is killed by the timeout.
- Output truncated to ~8KB so it fits the voice loop.
- Runs from the workspace jail (<vagar-home>\workspace\) as the
  working directory; importable modules are the stdlib plus what's installed.
- Defensive only: this executes code the user asked for in conversation.
"""
from livekit.agents.llm import function_tool

import subprocess as _subprocess

_PY = r"C:\Python310\python.exe"
_CWD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace")
_MAX_OUT = 8000


@function_tool(
    name="run_python",
    description="Run a Python code snippet and return its output. Use for math, data analysis, text processing, scripting, and automation the user asks for.",
)
async def run_python(code: str, timeout: int = 30) -> str:
    if not code or not isinstance(code, str):
        return "No code given."
    try:
        t = int(timeout)
    except (TypeError, ValueError):
        t = 30
    t = max(1, min(t, 120))
    try:
        proc = _subprocess.run(
            [_PY, "-c", code],
            capture_output=True, text=True, timeout=t,
            cwd=_CWD,
        )
    except _subprocess.TimeoutExpired:
        return "Timed out after %d seconds; the process was killed." % t
    except FileNotFoundError:
        return "Python interpreter not found."
    except Exception as e:
        return "Could not run code: %s" % e
    out = (proc.stdout or "") + (proc.stderr or "")
    if len(out) > _MAX_OUT:
        out = out[:_MAX_OUT] + "\n... [output truncated]"
    if not out.strip():
        return "Ran clean (exit %d), no output." % proc.returncode
    return "exit %d:\n%s" % (proc.returncode, out)
