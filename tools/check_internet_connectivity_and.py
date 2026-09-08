import os
import time

def run(**kwargs) -> dict:
    data = {
        'internet_connected': False,
        'ping_latency': None
    }

    try:
        # Check internet connectivity
        import urllib.request
        response = urllib.request.urlopen('http://www.google.com', timeout=1)
        if response.getcode() == 200:
            data['internet_connected'] = True

        # Ping latency (not a standard termux command, but can be calculated here)
        start_time = time.clock_gettime(time.CLOCK_BOOTTIME)
        ping_command = 'ping -c 4 www.google.com'
        os.system(ping_command)
        end_time = time.clock_gettime(time.CLOCK_BOOTTIME)
        ping_latency = round(end_time - start_time, 2) * 1000  # Convert to milliseconds

        data['ping_latency'] = ping_latency
    except Exception as e:
        print(f"Error: {e}")
    finally:
        pass
    return data

if __name__ == '__main__':
    run()