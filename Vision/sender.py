import socket
import struct
import time

DISCOVERY_PORT = 5000
TCP_PORT = 5001
BUFFER_SIZE = 4096


def start_sender(image_path):

    # ---- UDP BROADCAST: discover receiver ----
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # FIX: was SOCK_STREAM
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    udp_socket.sendto(b"SENDER_AVAILABLE", ('255.255.255.255', DISCOVERY_PORT))
    print("[BROADCAST] Searching for receiver...")

    udp_socket.settimeout(30)

    receiver_ip = None
    try:
        data, receiver_addr = udp_socket.recvfrom(1024)
        if data == b"RECEIVER_READY":           # FIX: matched to what receiver actually sends
            receiver_ip = receiver_addr[0]
            print(f"[FOUND] Receiver at {receiver_ip}")
    except socket.timeout:
        print("[ERROR] No receiver found. Make sure receiver.py is running on the target machine.")
        udp_socket.close()
        return

    udp_socket.close()

    time.sleep(1)

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