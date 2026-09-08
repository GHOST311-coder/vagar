import sys
import time

def run(**kwargs):
    title = kwargs.get("title", "VAGAR ALERT")
    message = kwargs.get("message", "Task completed.")
    
    # Ring terminal bell
    sys.stdout.write('\a')
    sys.stdout.flush()

    banner = (
        f"\n{'='*40}\n"
        f"  🔔 [{title}]\n"
        f"  {message}\n"
        f"{'='*40}\n"
    )
    return {
        "status": "success",
        "delivered_via": "terminal_bell_and_banner",
        "alert": banner.strip()
    }
