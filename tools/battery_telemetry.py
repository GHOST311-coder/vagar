import subprocess
import json

def battery_telemetry():
    """Retrieves device battery percentage, health, and charging status."""
    try:
        res = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            return {"status": "success", "battery": data}
        return {"status": "error", "message": "Failed to fetch battery status"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    print(battery_telemetry())
