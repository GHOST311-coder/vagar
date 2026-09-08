import os
import sys
import time
import socket

def run(**kwargs):
    meminfo = {}
    with open('/proc/meminfo', 'r') as f:
        for line in f:
            parts = line.split(':')
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip().split()[0]
                if val.isdigit():
                    meminfo[key] = int(val)  # raw values are in kB

    total_kb = meminfo.get('MemTotal', 0)
    avail_kb = meminfo.get('MemAvailable', meminfo.get('MemFree', 0))
    used_kb = total_kb - avail_kb

    total_gb = round(total_kb / (1024 * 1024), 2)
    avail_gb = round(avail_kb / (1024 * 1024), 2)
    used_gb = round(used_kb / (1024 * 1024), 2)
    usage_pct = round((used_kb / total_kb) * 100, 1) if total_kb else 0.0

    return {
        "total_ram_gb": total_gb,
        "used_ram_gb": used_gb,
        "free_ram_gb": avail_gb,
        "memory_usage_pct": f"{usage_pct}%"
    }
