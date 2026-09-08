import subprocess

def run(**kwargs):
    limit = kwargs.get("limit", 5)
    cmd = ["ps", "-eo", "pid,user,%mem,comm"]
    
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        lines = res.stdout.strip().split("\n")
        if len(lines) <= 1:
            return {"processes": [], "count": 0}

        headers = lines[0].split()
        tasks = []
        for line in lines[1:]:
            parts = line.split(maxsplit=3)
            if len(parts) == 4:
                try:
                    tasks.append({
                        "pid": int(parts[0]),
                        "user": parts[1],
                        "mem_pct": float(parts[2]),
                        "command": parts[3]
                    })
                except ValueError:
                    continue

        # Sort descending by memory consumption
        tasks.sort(key=lambda x: x["mem_pct"], reverse=True)
        top_tasks = tasks[:limit]

        return {
            "top_processes": top_tasks,
            "monitored_tasks_total": len(tasks)
        }
    except Exception as e:
        return {"error": str(e)}
