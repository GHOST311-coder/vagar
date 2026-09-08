import subprocess
import socket

def network_recon():
    """Performs basic network recon including internet connectivity and local port check."""
    results = {}
    
    # Check internet connectivity via ping
    try:
        res = subprocess.run(["ping", "-c", "1", "8.8.8.8"], capture_output=True, text=True, timeout=3)
        results["internet_ping"] = "success" if res.returncode == 0 else "failed"
    except Exception as e:
        results["internet_ping"] = {"error": str(e)}
        
    # Check local port status (e.g., localhost port 80 or similar)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex(('127.0.0.1', 80))
        results["local_port_80"] = "open" if result == 0 else "closed"
        s.close()
    except Exception as e:
        results["local_port_80"] = {"error": str(e)}
        
    return {"status": "success", "network_recon": results}

if __name__ == "__main__":
    print(network_recon())
