import subprocess
import json
import shutil
import os

def system_telemetry():
    """Gathers device hardware metrics, battery status, and storage usage."""
    try:
        # Storage usage
        total, used, free = shutil.disk_usage("/")
        storage_info = {
            "total_gb": round(total / (2**30), 2),
            "used_gb": round(used / (2**30), 2),
            "free_gb": round(free / (2**30), 2)
        }
        
        # Battery status via Termux API if available
        battery_data = {}
        try:
            res = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                battery_data = json.loads(res.stdout.strip())
        except Exception:
            battery_data = {"status": "Unavailable (termux-api not configured)"}
            
        # Memory info via /proc/meminfo
        mem_info = {}
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
                for line in lines[:3]:
                    parts = line.split(":")
                    if len(parts) == 2:
                        mem_info[parts[0].strip()] = parts[1].strip()
                        
        return {
            "status": "success",
            "storage": storage_info,
            "battery": battery_data,
            "memory": mem_info
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
