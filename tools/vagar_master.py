import socket
import subprocess
import os
import json

def vagar_master(skill_name, *args, **kwargs):
    """Unified master dispatcher combining system diagnostics, security tools, and phone API integrations."""
    skills = {
        "process_monitor": _process_monitor,
        "clipboard_manager": _clipboard_manager,
        "network_recon": _network_recon,
        "sec_toolkit": _sec_toolkit,
        "phone_sms": _phone_sms,
        "phone_calls": _phone_calls,
        "phone_contacts": _phone_contacts
    }
    
    if skill_name not in skills:
        return {"status": "error", "message": f"Skill '{skill_name}' not registered."}
        
    try:
        return skills[skill_name](*args, **kwargs)
    except Exception as e:
        return {"status": "error", "message": str(e)}

def _process_monitor(*args, **kwargs):
    res = subprocess.run(["ps", "-ef"], capture_output=True, text=True, timeout=5)
    if res.returncode == 0:
        return {"status": "success", "processes": res.stdout.strip().split("\n")[:15]}
    return {"status": "error", "message": "Failed to list processes"}

def _clipboard_manager(*args, **kwargs):
    action = kwargs.get("action", "get")
    text = kwargs.get("text", "")
    if action == "set" and text:
        subprocess.run(["termux-clipboard-set", text], capture_output=True, text=True, timeout=3)
        return {"status": "success", "message": "Clipboard updated"}
    else:
        res = subprocess.run(["termux-clipboard-get"], capture_output=True, text=True, timeout=3)
        return {"status": "success", "clipboard": res.stdout.strip()}

def _network_recon(*args, **kwargs):
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
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

def _sec_toolkit(*args, **kwargs):
    target = kwargs.get("target", "127.0.0.1")
    ports_str = kwargs.get("ports", "21,22,80,443,8080")
    if args and isinstance(args[0], str):
        target = args[0]
    results = {"target": target, "open_ports": [], "banners": {}}
    try:
        port_list = [int(p.strip()) for p in ports_str.split(",")]
    except Exception:
        port_list = [21, 22, 80, 443, 8080]
    for port in port_list:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            if s.connect_ex((target, port)) == 0:
                results["open_ports"].append(port)
                try:
                    s.sendall(b"HEAD / HTTP/1.0\r\n\r\n")
                    banner = s.recv(1024).decode('utf-8', errors='ignore').split('\n')[0]
                    results["banners"][port] = banner.strip()
                except Exception:
                    results["banners"][port] = "Open"
            s.close()
        except Exception:
            pass
    return {"status": "success", "recon": results}

def _phone_sms(*args, **kwargs):
    action = kwargs.get("action", "list")
    if action == "send":
        number = kwargs.get("number", "")
        message = kwargs.get("message", "")
        res = subprocess.run(["termux-sms-send", "-n", number, message], capture_output=True, text=True, timeout=5)
        return {"status": "success", "output": res.stdout.strip()}
    else:
        res = subprocess.run(["termux-sms-list", "-l", "5"], capture_output=True, text=True, timeout=5)
        try:
            data = json.loads(res.stdout) if res.stdout.strip() else []
            return {"status": "success", "sms": data}
        except Exception:
            return {"status": "success", "raw": res.stdout.strip()}

def _phone_calls(*args, **kwargs):
    res = subprocess.run(["termux-call-log", "-l", "5"], capture_output=True, text=True, timeout=5)
    try:
        data = json.loads(res.stdout) if res.stdout.strip() else []
        return {"status": "success", "call_log": data}
    except Exception:
        return {"status": "success", "raw": res.stdout.strip()}

def _phone_contacts(*args, **kwargs):
    res = subprocess.run(["termux-contact-list"], capture_output=True, text=True, timeout=5)
    try:
        data = json.loads(res.stdout) if res.stdout.strip() else []
        return {"status": "success", "contacts": data}
    except Exception:
        return {"status": "success", "raw": res.stdout.strip()}

if __name__ == "__main__":
    print(vagar_master("network_recon"))
