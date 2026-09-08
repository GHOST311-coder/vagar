import os
import sys

def run(**kwargs):
    sys.path.insert(0, os.path.dirname(__file__))
    report = {}

    try:
        import cpu_telemetry
        report["cpu"] = cpu_telemetry.run()
    except Exception as e:
        report["cpu"] = {"error": str(e)}

    try:
        import system_memory_usage
        report["memory"] = system_memory_usage.run()
    except Exception as e:
        report["memory"] = {"error": str(e)}

    try:
        import uptime_hours
        report["uptime"] = uptime_hours.run()
    except Exception as e:
        report["uptime"] = {"error": str(e)}

    try:
        import port_scanner
        report["ports"] = port_scanner.run()
    except Exception as e:
        report["ports"] = {"error": str(e)}

    return report
