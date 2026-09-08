import socket

def run(**kwargs):
    target_host = kwargs.get("host", "127.0.0.1")
    # Ports common in Termux/Android environments: SSH, HTTP, dev servers, Ollama
    candidate_ports = [22, 53, 80, 443, 8000, 8080, 8888, 9000, 11434]
    open_ports = []

    for port in candidate_ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        try:
            result = s.connect_ex((target_host, port))
            if result == 0:
                open_ports.append(port)
        except Exception:
            pass
        finally:
            s.close()

    return {
        "host": target_host,
        "scanned_ports": len(candidate_ports),
        "open_ports": open_ports,
        "ollama_online": 11434 in open_ports
    }
