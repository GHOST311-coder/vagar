"""Skill manager for Vagar: loads approved local skills fresh each session.

Approved skill modules live in skills/. Each defines @function_tool-decorated
async functions; load_skill_tools() imports them fresh at every session start
so newly approved skills work without restarting the worker.

Generated skills awaiting approval live in skills/staging/ and are NEVER
imported automatically.
"""
import importlib
import re
import sys
from pathlib import Path

from config import SKILLS_DIR

STAGING_DIR = SKILLS_DIR / "staging"

# Ensure the project root is importable for skill modules.
_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _is_function_tool(obj) -> bool:
    """Detect a livekit @function_tool-decorated callable."""
    if not callable(obj):
        return False
    tname = type(obj).__name__
    if tname in ("FunctionTool", "RawFunctionTool"):
        return True
    # Fallback: livekit attaches tool metadata to the wrapper.
    return any(
        hasattr(obj, attr)
        for attr in ("_function_tool_info", "description", "name")
    ) and getattr(obj, "__module__", "") not in ("builtins",)


def load_skill_tools(directory: Path = None):
    """Import every skill module in `directory` and collect its tools.

    Modules are re-imported from source each call so newly approved skills
    take effect without a worker restart. A broken skill module is skipped
    (logged to stderr) rather than crashing the session.
    """
    import traceback

    directory = Path(directory) if directory else SKILLS_DIR
    tools = []
    if not directory.is_dir():
        return tools
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"skills.{path.stem}"
        try:
            if mod_name in sys.modules:
                mod = importlib.reload(sys.modules[mod_name])
            else:
                mod = importlib.import_module(mod_name)
        except Exception:
            print(f"[skill_manager] skipping broken skill {path.name}", file=sys.stderr)
            traceback.print_exc()
            continue
        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            obj = getattr(mod, attr_name)
            if _is_function_tool(obj) and getattr(obj, "__module__", "") == mod_name:
                tools.append(obj)
    return tools


def list_live_skills():
    """Names of currently live skill modules."""
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(
        p.stem for p in SKILLS_DIR.glob("*.py") if not p.name.startswith("_")
    )


def list_staged_skills():
    """Names of skill modules awaiting approval in staging/."""
    if not STAGING_DIR.is_dir():
        return []
    return sorted(
        p.stem for p in STAGING_DIR.glob("*.py") if not p.name.startswith("_")
    )


def sanitize_name(name: str) -> str:
    """Make a string safe for use as a Python module name."""
    name = re.sub(r"[^a-z0-9_]", "_", (name or "").lower())
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "skill"


def validate_skill_code(code: str):
    """Syntax-check skill source. Returns (ok, error_message)."""
    try:
        compile(code, "<skill>", "exec")
        return True, ""
    except SyntaxError as e:
        return False, f"{e.msg} (line {e.lineno})"


def stage_skill(name: str, code: str) -> str:
    """Write skill source to staging/ for user review. Never auto-approves."""
    safe = sanitize_name(name)
    ok, err = validate_skill_code(code)
    if not ok:
        return f"Skill failed validation: {err}"
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    (STAGING_DIR / f"{safe}.py").write_text(code, encoding="utf-8")
    return f"Staged '{safe}' for your approval. It is NOT live yet."


def approve_skill_file(name: str) -> str:
    """Move a staged skill into skills/ (user-approved only)."""
    safe = sanitize_name(name)
    src = STAGING_DIR / f"{safe}.py"
    dst = SKILLS_DIR / f"{safe}.py"
    if not src.exists():
        return f"No staged skill named '{safe}'."
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    src.unlink()
    return f"Approved '{safe}'. It loads at the next session start."


def reject_skill_file(name: str) -> str:
    """Delete a staged skill without activating it."""
    safe = sanitize_name(name)
    src = STAGING_DIR / f"{safe}.py"
    if not src.exists():
        return f"No staged skill named '{safe}'."
    src.unlink()
    return f"Rejected and removed staged skill '{safe}'."


def draft_skill_code(description: str) -> str:
    """Draft skill source from a description (requires a local LLM).

    This minimal build does not bundle the drafting LLM loop; it returns a
    template the user can fill in. Wire your preferred local model here.
    """
    safe = sanitize_name(description[:40])
    return (
        f'"""TODO: {description}"""\n'
        "from livekit.agents.llm import function_tool\n\n\n"
        "@function_tool(\n"
        f'    name="{safe}",\n'
        '    description="TODO: describe when to use this tool.",\n'
        ")\n"
        f"async def {safe}() -> str:\n"
        '    return "TODO: implement."\n'
    )
