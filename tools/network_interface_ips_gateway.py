import socket
import time

def run(**kwargs) -> dict:
    # Get local IP address using standard socket techniques
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    local_ip = s.getsockname()[0]
    s.close()
    
    # Calculate uptime (in seconds)
    start_time = time.clock_gettime(time.CLOCK_BOOTTIME)
    while True:
        current_time = time.clock_gettime(time.CLOCK_BOOTTIME)
        uptime_seconds = current_time - start_time
        break
    
    return {
        "local_ip": local_ip,
        "uptime_seconds": uptime_seconds
    }