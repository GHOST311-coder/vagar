import socket
import concurrent.futures

def check_host(ip, port=80, timeout=0.15):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        if s.connect_ex((ip, port)) == 0:
            return ip
    except Exception:
        pass
    finally:
        s.close()
    return None

def run(**kwargs):
    # Detect current local IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()

    if local_ip == '127.0.0.1':
        return {"error": "No active network interface detected"}

    # Determine subnet base (e.g. 192.168.1. or 100.80.100.)
    octets = local_ip.split('.')
    subnet_base = f"{octets[0]}.{octets[1]}.{octets[2]}."

    # Scan first 30 host addresses concurrently
    active_hosts = []
    targets = [f"{subnet_base}{i}" for i in range(1, 31)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(check_host, ip) for ip in targets]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                active_hosts.append(res)

    return {
        "local_ip": local_ip,
        "subnet": f"{subnet_base}0/24",
        "scanned_range": f"{subnet_base}1 - {subnet_base}30",
        "responsive_hosts": sorted(active_hosts)
    }
