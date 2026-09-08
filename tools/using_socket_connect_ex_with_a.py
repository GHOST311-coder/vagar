import socket

def using_socket_connect_ex_with_a():
    open_ports = {}
    for port in range(20, 11501):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                result = sock.connect_ex(('127.0.0.1', port))
                if result == 0:  # connection successful
                    open_ports[port] = "Open"
        except Exception as e:
            print(f"Error scanning port {port}: {e}")
    return open_ports