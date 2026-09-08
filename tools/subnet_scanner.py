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

    octets = local_ip.split('.')
    subnet_base = f"{octets[0]}.{octets[1]}.{octets[2]}."

    is_cgnat = local_ip.startswith("100.")
    network_type = "Cellular CGNAT (client-isolated)" if is_cgnat else "Local Wi-Fi / Ethernet LAN"

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
        "network_type": network_type,
        "subnet": f"{subnet_base}0/24",
        "scanned_range": f"{subnet_base}1 - {subnet_base}30",
        "responsive_hosts": sorted(active_hosts),
        "note": "Carrier isolation drops peer sweeps on mobile data." if is_cgnat else "LAN discovery active."
    }
