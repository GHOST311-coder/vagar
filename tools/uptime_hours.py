import time
import os
import shutil

def run(**kwargs):
    uptime_seconds = time.monotonic() / 3600  # Use monotonic for system uptime on Android
    storage_usage = shutil.disk_usage('/data/data/com.termux/files/home')
    
    return {
        'uptime_hours': uptime_seconds,
        'storage_used_gb': storage_usage.used / (1024**3)  # Convert bytes to GB
    }