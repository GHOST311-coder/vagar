import subprocess
import socket

def network_recon(target_ip: str = "127.0.0.1"):
    """Performs network interface inspection and basic connectivity checks."""
    results = {}
    try:
        # Get active network interfaces
        ifconfig_res = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5)
        results["interfaces"] = ifconfig_res.stdout if ifconfig_res.returncode == 0 else "ifconfig unavailable"
        
        # Check target reachability on common ports
        open_ports = []
        ports_to_check = [21, 22, 80, 443, 4713, 8080, 11434]
        for port in ports_to_check:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2)
            if s.connect_ex((target_ip, port)) == 0:
                open_ports.append(port)
            s.close()
        results["target_open_ports"] = open_ports
        
        return {"status": "success", "recon": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}
