import os
import time
import struct
import socket

def run(**kwargs) -> dict:
    # Parse /proc/meminfo for RAM/Memory usage
    mem_info = {}
    with open('/proc/meminfo', 'r') as file:
        for line in file:
            if line.startswith('MemTotal:'):
                mem_info['total_memory'] = int(line.split()[1])
            elif line.startswith('MemFree:'):
                mem_info['free_memory'] = int(line.split()[1])
            elif line.startswith('Buffers:'):
                mem_info['buffers'] = int(line.split()[1])
            elif line.startswith('Cached:'):
                mem_info['cached'] = int(line.split()[1])
    # Calculate used memory
    total_memory = mem_info['total_memory']
    free_memory = mem_info['free_memory']
    buffers = mem_info['buffers']
    cached = mem_info['cached']
    used_memory = total_memory - (free_memory + buffers + cached)
    
    # Get uptime using time.clock_gettime(time.CLOCK_BOOTTIME)
    start_time = time.clock_gettime(time.CLOCK_BOOTTIME)
    end_time = time.clock_gettime(time.CLOCK_BOOTTIME)
    uptime = end_time - start_time
    
    # For Local IP, use standard UDP socket connection to 8.8.8.8:80
    try:
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.connect(("8.8.8.8", 80))
        response = udp_socket.recv(1024)
        udp_socket.close()
        
        # Assume the response contains the IP address of the device
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception as e:
        print(f"Error: {e}")
        local_ip = "Unknown"
    
    return {
        'total_memory': total_memory,
        'free_memory': free_memory,
        'buffers': buffers,
        'cached': cached,
        'used_memory': used_memory,
        'uptime': uptime,
        'local_ip': local_ip
    }