"""Battery monitor skill for Vagar - proactive low-battery warnings."""
import psutil

def check_battery():
    """Check battery status. Returns dict with percent, plugged in, and warning level."""
    battery = psutil.sensors_battery()
    if battery is None:
        return {"available": False, "message": "No battery detected (desktop power)."}
    
    percent = battery.percent
    plugged = battery.power_plugged
    
    if percent <= 15 and not plugged:
        level = "critical"
    elif percent <= 30 and not plugged:
        level = "low"
    else:
        level = "ok"
    
    return {
        "available": True,
        "percent": percent,
        "plugged_in": plugged,
        "level": level,
        "message": f"Battery at {percent}%{' (plugged in)' if plugged else ' (on battery)'}. Status: {level}."
    }

# Skill metadata for Vagar's skill system
SKILL_INFO = {
    "name": "battery_monitor",
    "description": "Check laptop battery level and charging status",
    "tools": ["check_battery"],
}

