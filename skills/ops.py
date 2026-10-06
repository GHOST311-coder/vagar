from livekit.agents.llm import function_tool
import os
import time

import sys as _cfg_sys
from pathlib import Path as _cfg_Path
_cfg_sys.path.insert(0, str(_cfg_Path(__file__).resolve().parent.parent))
from config import BOOK_DIR

# BOOK_DIR comes from config.py (VAGAR_BOOK_DIR)


@function_tool(
    name="batch_status",
    description=(
        "Check progress of the Cozy Dragons coloring-book art batch: how many "
        "of the 50 pages are rendered and whether the renderer looks active."
    ),
)
async def batch_status() -> str:
    try:
        if not os.path.isdir(BOOK_DIR):
            return "The art folder was not found."
        pngs = [f for f in os.listdir(BOOK_DIR) if f.lower().endswith(".png")]
        n = len(pngs)
        if not pngs:
            return "Cozy Dragons art: 0 of 50 pages rendered."
        latest = max(pngs, key=lambda f: os.path.getmtime(os.path.join(BOOK_DIR, f)))
        age_min = (time.time() - os.path.getmtime(os.path.join(BOOK_DIR, latest))) / 60
        state = (
            "renderer looks active (newest page %d minutes old)"
            % age_min if age_min < 90 else "renderer looks idle (newest page %d minutes old)" % age_min
        )
        return "Cozy Dragons art: %d of 50 pages done, newest is %s. %s." % (n, latest, state)
    except Exception as e:
        return "Could not check batch status: %s" % e


@function_tool(
    name="system_status",
    description="Report the laptop's free disk space, memory use, and CPU load.",
)
async def system_status() -> str:
    try:
        import shutil
        import ctypes
        import subprocess

        disk = shutil.disk_usage("C:\\")
        free_gb = disk.free / (1024 ** 3)

        class _MS(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        ms = _MS()
        ms.dwLength = ctypes.sizeof(_MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))

        cpu = "unknown"
        try:
            out = subprocess.run(
                ["wmic", "cpu", "get", "loadpercentage", "/value"],
                capture_output=True, text=True, timeout=20,
            ).stdout
            for line in out.splitlines():
                if "LoadPercentage" in line and "=" in line:
                    cpu = line.split("=", 1)[1].strip() + "%"
        except Exception:
            pass

        return (
            "Laptop status: C: drive has %.1f GB free, memory is %d%% in use "
            "(%.1f of %.1f GB available), CPU load %s."
            % (free_gb, ms.dwMemoryLoad, ms.ullAvailPhys / 2 ** 30,
               ms.ullTotalPhys / 2 ** 30, cpu)
        )
    except Exception as e:
        return "Could not read system status: %s" % e
