import os
import json

def run(limit=2, **kwargs):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_file = os.path.join(project_root, "reports", "diagnostics.log")
    
    if not os.path.exists(log_file):
        return {"status": "error", "message": "reports/diagnostics.log not found"}

    try:
        limit = int(limit)
    except (ValueError, TypeError):
        limit = 2

    entries = []
    with open(log_file, "r") as f:
        lines = [line.strip() for line in f if line.strip()]
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return {
        "status": "success",
        "count": len(entries),
        "recent_snapshots": entries
    }
