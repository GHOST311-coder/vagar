import socket

def network_recon():
    """Performs local network and connectivity reconnaissance checks via socket queries."""
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        
        # Test basic internet reachability via socket connection
        ext_reachable = False
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=2)
            s.close()
            ext_reachable = True
        except Exception:
            pass

        return {
            "status": "success", 
            "hostname": hostname,
            "local_ip": local_ip,
            "internet_reachable": ext_reachable
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    print(network_recon())
