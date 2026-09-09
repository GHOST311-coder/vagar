import subprocess
import json

def vagar_expansion(*args, **kwargs):
    """Executes advanced automation routines including log harvesting and device health checks."""
    actions = {
        "device_info": _get_device_info,
        "recent_notifications": _get_notifications
    }
    action = kwargs.get("action", "device_info")
    if args and isinstance(args[0], str):
        action = args[0]
        
    if action not in actions:
        return {"status": "error", "message": f"Unknown action. Available: {list(actions.keys())}"}
        
    try:
        return actions[action]()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def _get_device_info():
    res = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=5)
    try:
        battery = json.loads(res.stdout) if res.stdout.strip() else {}
        return {"status": "success", "battery": battery}
    except Exception:
        return {"status": "success", "raw_battery": res.stdout.strip()}

def _get_notifications():
    res = subprocess.run(["termux-notification-list"], capture_output=True, text=True, timeout=5)
    try:
        notifs = json.loads(res.stdout) if res.stdout.strip() else []
        return {"status": "success", "notifications": notifs}
    except Exception:
        return {"status": "success", "raw_notifications": res.stdout.strip()}

if __name__ == "__main__":
    print(vagar_expansion("device_info"))
