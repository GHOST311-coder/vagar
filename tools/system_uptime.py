import subprocess

def system_uptime():
    """Retrieves system uptime and boot statistics."""
    try:
        res = subprocess.run(["uptime"], capture_output=True, text=True, timeout=3)
        return {"status": "success", "uptime": res.stdout.strip()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    print(system_uptime())
