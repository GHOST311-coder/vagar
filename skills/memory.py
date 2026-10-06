from livekit.agents.llm import function_tool
import os
import datetime

import sys as _cfg_sys
from pathlib import Path as _cfg_Path
_cfg_sys.path.insert(0, str(_cfg_Path(__file__).resolve().parent.parent))
from config import MEMORY_PATH

# MEMORY_PATH comes from config.py


@function_tool(
    name="recall_memory",
    description=(
        "Read Vagar's long-term memory: everything known about the user and "
        "your shared work. Call this at the start of every session."
    ),
)
async def recall_memory() -> str:
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return content if content else "Memory file is empty."
    except FileNotFoundError:
        return "No memory file exists yet."
    except Exception as e:
        return "Could not read memory: %s" % e


@function_tool(
    name="remember_fact",
    description=(
        "Save a fact about the user, their preferences, or your work together "
        "long-term memory. Use for anything worth remembering across calls."
    ),
)
async def remember_fact(fact: str) -> str:
    try:
        fact = (fact or "").strip()
        if not fact:
            return "Nothing to save."
        stamp = datetime.datetime.now().strftime("%Y-%m-%d")
        with open(MEMORY_PATH, "a", encoding="utf-8") as f:
            f.write("\n- [%s] %s\n" % (stamp, fact))
        return "Saved to memory."
    except Exception as e:
        return "Could not save: %s" % e
