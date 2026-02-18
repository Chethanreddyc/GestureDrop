import socket
import struct
import time

DISCOVERY_PORT = 5000
TCP_PORT = 5001
BUFFER_SIZE = 4096


def get_own_ip():
    """Get this machine's LAN IP address (not loopback)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # doesn't actually send data
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def start_sender(image_path):

    own_ip = get_own_ip()
    print(f"[INFO] Sender IP: {own_ip}")

    # ---- UDP BROADCAST: discover receiver ----
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Bind to a specific reply port so we receive unicast replies
    udp_socket.bind(('', 5002))

    udp_socket.sendto(b"SENDER_AVAILABLE", ('255.255.255.255', DISCOVERY_PORT))
    print("[BROADCAST] Searching for receiver...")

    udp_socket.settimeout(30)

    receiver_ip = None
    try:
        while True:
            data, receiver_addr = udp_socket.recvfrom(1024)
            reply_ip = receiver_addr[0]

            # *** KEY FIX: ignore replies from ourselves ***
            if reply_ip == own_ip or reply_ip == "127.0.0.1":
                print(f"[SKIP] Ignoring reply from own IP: {reply_ip}")
                continue

            if data == b"RECEIVER_READY":
                receiver_ip = reply_ip
                print(f"[FOUND] Receiver at {receiver_ip}")
                break
    except socket.timeout:
        print("[ERROR] No receiver found. Make sure receiver.py is running on the target machine.")
        udp_socket.close()
        return

    udp_socket.close()

    time.sleep(0.5)

    # ---- TCP SEND: transfer the image ----
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.connect((receiver_ip, TCP_PORT))

    with open(image_path, "rb") as f:
        image_data = f.read()

    image_size = len(image_data)

    client_socket.sendall(struct.pack("Q", image_size))
    client_socket.sendall(image_data)

    print("[SUCCESS] Image sent successfully!")

    client_socket.close()


if __name__ == "__main__":
    start_sender("screenshot/screenshot.png")