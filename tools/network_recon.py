import socket
import os

def network_recon():
    """Performs local network and connectivity reconnaissance checks using pure Python."""
    try:
        interfaces = {}
        if os.path.exists('/sys/class/net/'):
            for iface in os.listdir('/sys/class/net/'):
                try:
                    with open(f'/sys/class/net/{iface}/operstate', 'r') as f:
                        state = f.read().strip()
                    interfaces[iface] = {"state": state}
                except Exception:
                    pass
        
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        
        return {
            "status": "success", 
            "hostname": hostname,
            "local_ip": local_ip,
            "interfaces": interfaces
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    print(network_recon())
