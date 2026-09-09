import subprocess
import socket

def sec_toolkit(target="127.0.0.1", ports="21,22,80,443,8080"):
    """Performs lightweight security auditing, port scanning, and banner grabbing."""
    results = {"target": target, "open_ports": [], "banners": {}}
    port_list = [int(p.strip()) for p in ports.split(",")]
    
    for port in port_list:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex((target, port))
            if result == 0:
                results["open_ports"].append(port)
                try:
                    s.sendall(b"HEAD / HTTP/1.0\r\n\r\n")
                    banner = s.recv(1024).decode('utf-8', errors='ignore').split('\n')[0]
                    results["banners"][port] = banner.strip()
                except Exception:
                    results["banners"][port] = "Open (No Banner)"
            s.close()
        except Exception:
            pass
            
    return {"status": "success", "recon": results}

if __name__ == "__main__":
    print(sec_toolkit())
