import subprocess
import re

def run(**kwargs):
    try:
        proc = subprocess.run(
            ["ping", "-c", "4", "www.google.com"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8
        )
        output = proc.stdout
        connected = (proc.returncode == 0)
        
        avg_latency_ms = None
        match = re.search(r"rtt min/avg/max/mdev =\s*[\d\.]+/([\d\.]+)/", output)
        if match:
            avg_latency_ms = float(match.group(1))

        return {
            "internet_connected": connected,
            "avg_latency_ms": avg_latency_ms,
            "packets_transmitted": 4,
            "packet_loss_pct": 0.0 if connected else 100.0
        }
    except Exception as e:
        return {
            "internet_connected": False,
            "avg_latency_ms": None,
            "error": str(e)
        }
