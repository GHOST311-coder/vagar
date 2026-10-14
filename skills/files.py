"""Workspace file tools: read, write, append, and list files inside Vagar's workspace.

JAILED: every path is confined to <vagar-home>\workspace\.
Any path that normalizes outside the jail is refused. This is the only
place Vagar can read or write files â€” never the rest of the machine.
"""
from livekit.agents.llm import function_tool

import os as _os

_JAIL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace")
_MAX_BYTES = 200_000


def _jail(path):
    """Resolve `path` inside the jail. Returns (abs_path, error)."""
    if not path or not isinstance(path, str):
        return None, "no path given"
    p = path.replace("/", "\\")
    # Disallow drive letters, UNC, and absolute escapes outright.
    if len(p) >= 2 and p[1] == ":":
        return None, "absolute paths are not allowed"
    if p.startswith("\\\\"):
        return None, "network paths are not allowed"
    if "~" in p.split("\\"):
        return None, "home-directory shortcuts are not allowed"
    abs_p = _os.path.normpath(_os.path.join(_JAIL, p))
    jail = _os.path.normpath(_JAIL)
    if abs_p != jail and not abs_p.startswith(jail + "\\"):
        return None, "path escapes the workspace jail"
    return abs_p, ""


@function_tool(
    name="read_file",
    description="Read a text file from Vagar's workspace (path relative to workspace). Use to inspect notes, data, or generated files.",
)
async def read_file(path: str) -> str:
    abs_p, err = _jail(path)
    if err:
        return "Refused: %s." % err
    if not _os.path.isfile(abs_p):
        return "File not found: %s." % path
    try:
        size = _os.path.getsize(abs_p)
        if size > _MAX_BYTES:
            return "File too large (%d bytes, limit %d)." % (size, _MAX_BYTES)
        with open(abs_p, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        return "Could not read file: %s" % e


@function_tool(
    name="write_file",
    description="Write text to a file in Vagar's workspace (path relative to workspace). Creates parent folders. Overwrites existing files.",
)
async def write_file(path: str, content: str) -> str:
    abs_p, err = _jail(path)
    if err:
        return "Refused: %s." % err
    try:
        data = content if isinstance(content, str) else str(content)
        if len(data.encode("utf-8")) > _MAX_BYTES:
            return "Content too large (limit %d bytes)." % _MAX_BYTES
        parent = _os.path.dirname(abs_p)
        if parent:
            _os.makedirs(parent, exist_ok=True)
        with open(abs_p, "w", encoding="utf-8") as f:
            f.write(data)
        return "Wrote %d characters to %s." % (len(data), path)
    except Exception as e:
        return "Could not write file: %s" % e


@function_tool(
    name="append_file",
    description="Append text to the end of a file in Vagar's workspace (path relative to workspace). Creates the file if missing.",
)
async def append_file(path: str, content: str) -> str:
    abs_p, err = _jail(path)
    if err:
        return "Refused: %s." % err
    try:
        data = content if isinstance(content, str) else str(content)
        if len(data.encode("utf-8")) > _MAX_BYTES:
            return "Content too large (limit %d bytes)." % _MAX_BYTES
        parent = _os.path.dirname(abs_p)
        if parent:
            _os.makedirs(parent, exist_ok=True)
        with open(abs_p, "a", encoding="utf-8") as f:
            f.write(data)
        return "Appended %d characters to %s." % (len(data), path)
    except Exception as e:
        return "Could not append to file: %s" % e


@function_tool(
    name="list_dir",
    description="List files and folders inside Vagar's workspace (path relative to workspace, blank for the top level).",
)
async def list_dir(path: str = "") -> str:
    abs_p, err = _jail(path or ".")
    if err:
        return "Refused: %s." % err
    try:
        if not _os.path.isdir(abs_p):
            return "Not a directory: %s." % (path or ".")
        entries = sorted(_os.listdir(abs_p))
        if not entries:
            return "Directory %s is empty." % (path or "workspace")
        lines = []
        for e in entries[:200]:
            full = _os.path.join(abs_p, e)
            lines.append(("[dir] " if _os.path.isdir(full) else "") + e)
        out = "\n".join(lines)
        if len(entries) > 200:
            out += "\n... and %d more" % (len(entries) - 200)
        return out
    except Exception as e:
        return "Could not list directory: %s" % e
