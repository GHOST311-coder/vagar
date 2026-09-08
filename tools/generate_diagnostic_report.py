import os
import sys
import json
import time

def run(**kwargs):
    sys.path.insert(0, os.path.dirname(__file__))
    import full_health_check

    data = full_health_check.run()
    data["timestamp"] = int(time.time())

    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
    os.makedirs(report_dir, exist_ok=True)
    report_file = os.path.join(report_dir, "diagnostics.log")

    with open(report_file, "a") as f:
        f.write(json.dumps(data) + "\n")

    return {
        "status": "logged",
        "file": report_file,
        "entry_timestamp": data["timestamp"]
    }
