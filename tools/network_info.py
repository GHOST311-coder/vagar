import socket

def run(**kwargs):
    # Get all network interfaces on the machine
    interfaces = socket.gethostbyname_ex(socket.gethostname())
    
    # Extract host name and local IP addresses from the tuple
    hostname = interfaces[0]
    local_ip = interfaces[2][0]
    
    # Create a dictionary with results
    result = {
        "hostname": hostname,
        "local_ip": local_ip
    }
    
    return result

if __name__ == "__main__":
    print(run())