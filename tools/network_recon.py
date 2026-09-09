import subprocess

def network_recon():
    """Performs local network and connectivity reconnaissance checks."""
    try:
        res = subprocess.run(["ip", "addr"], capture_output=True, text=True, timeout=3)
        return {"status": "success", "network_interfaces": res.stdout.strip()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    print(network_recon())
