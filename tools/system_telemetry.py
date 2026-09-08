import subprocess
import json
import os

def run():
    """Gathers system telemetry including battery and storage metrics."""
    telemetry = {}
    
    # Battery status via Termux API
    try:
        res = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            telemetry["battery"] = json.loads(res.stdout)
    except Exception as e:
        telemetry["battery"] = {"error": str(e)}
        
    # Storage usage
    try:
        st = os.statvfs("/")
        free = st.f_bavail * st.f_frsize
        total = st.f_blocks * st.f_frsize
        used = total - free
        telemetry["storage"] = {
            "total_gb": round(total / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "used_percent": round((used / total) * 100, 1)
        }
    except Exception as e:
        telemetry["storage"] = {"error": str(e)}
        
    return {"status": "success", "telemetry": telemetry}

if __name__ == "__main__":
    print(run())
