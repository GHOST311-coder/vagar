import subprocess
import re
import socket
import time

def run(host="8.8.8.8", port=53, **kwargs):
    # Strategy 1: Fast ICMP ping (2 count, 3s timeout)
    try:
        proc = subprocess.run(
            ["ping", "-c", "2", "-W", "2", host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4
        )
        if proc.returncode == 0:
            match = re.search(r"rtt min/avg/max/mdev =\s*[\d\.]+/([\d\.]+)/", proc.stdout)
            if match:
                return {
                    "internet_connected": True,
                    "mode": "icmp",
                    "target": host,
                    "avg_latency_ms": round(float(match.group(1)), 2),
                    "packet_loss_pct": 0.0
                }
    except Exception:
        pass

    # Strategy 2: TCP Handshake probe (works reliably over carrier/VPN connections)
    try:
        start = time.perf_counter()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        sock.connect((host, port))
        sock.close()
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        return {
            "internet_connected": True,
            "mode": "tcp_handshake",
            "target": f"{host}:{port}",
            "avg_latency_ms": round(elapsed_ms, 2),
            "packet_loss_pct": 0.0
        }
    except Exception as e:
        return {
            "internet_connected": False,
            "avg_latency_ms": None,
            "error": str(e)
        }
