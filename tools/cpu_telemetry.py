import os

def run(**kwargs):
    result = {}
    
    # Read load averages (1m, 5m, 15m)
    try:
        with open("/proc/loadavg", "r") as f:
            parts = f.read().strip().split()
            result["load_1m"] = float(parts[0])
            result["load_5m"] = float(parts[1])
            result["load_15m"] = float(parts[2])
            result["active_threads"] = parts[3]
    except Exception as e:
        result["loadavg_error"] = str(e)

    # Detect active online CPU core count
    try:
        cores = os.cpu_count() or 1
        result["cpu_cores"] = cores
        if "load_1m" in result:
            result["load_per_core_1m"] = round(result["load_1m"] / cores, 2)
    except Exception as e:
        result["cores_error"] = str(e)

    return result
