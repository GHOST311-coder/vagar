import os
import subprocess

def run(**kwargs):
    result = {
        "cpu_cores": os.cpu_count() or 1,
        "mode": "userland_process_sample"
    }

    cmd = ["ps", "-eo", "%cpu,comm"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        lines = res.stdout.strip().split("\n")
        
        total_cpu = 0.0
        active_processes = 0

        for line in lines[1:]:
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                try:
                    cpu_val = float(parts[0])
                    total_cpu += cpu_val
                    if cpu_val > 0.0:
                        active_processes += 1
                except ValueError:
                    continue

        result["termux_cpu_utilization_pct"] = f"{round(total_cpu, 1)}%"
        result["active_threads"] = active_processes

    except Exception as e:
        result["error"] = str(e)

    return result
