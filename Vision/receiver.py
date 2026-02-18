import socket
import struct
import os

DISCOVERY_PORT = 5000
SENDER_REPLY_PORT = 5002   # sender listens for replies on this port
TCP_PORT = 5001
BUFFER_SIZE = 4096
SAVE_FOLDER = "received_screenshot"

os.makedirs(SAVE_FOLDER, exist_ok=True)


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


def start_receiver():

    own_ip = get_own_ip()
    print(f"[INFO] Receiver IP: {own_ip}")

    # ---- UDP LISTEN: wait for sender broadcast ----
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_socket.bind(('', DISCOVERY_PORT))

    print("[WAITING] Listening for sender broadcast...")

    sender_ip = None
    while True:
        data, sender_addr = udp_socket.recvfrom(1024)
        incoming_ip = sender_addr[0]

        # *** KEY FIX: ignore broadcasts from ourselves ***
        if incoming_ip == own_ip or incoming_ip == "127.0.0.1":
            print(f"[SKIP] Ignoring broadcast from own IP: {incoming_ip}")
            continue

        if data == b"SENDER_AVAILABLE":
            sender_ip = incoming_ip
            print(f"[DISCOVERED] Sender at {sender_ip}")

            # Reply to sender's dedicated reply port (5002), not back to port 5000
            udp_socket.sendto(b"RECEIVER_READY", (sender_ip, SENDER_REPLY_PORT))
            break

    udp_socket.close()

    # ---- TCP RECEIVE: accept the image ----
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('', TCP_PORT))
    server_socket.listen(1)

    print("[TCP] Waiting for image connection...")
    conn, addr = server_socket.accept()
    print(f"[CONNECTED] {addr}")

    packed_size = conn.recv(8)
    image_size = struct.unpack("Q", packed_size)[0]

    data = b""
    while len(data) < image_size:
        packet = conn.recv(BUFFER_SIZE)
        if not packet:
            break
        data += packet

    file_path = os.path.join(SAVE_FOLDER, "received.png")

    with open(file_path, "wb") as f:
        f.write(data)

    print(f"[SUCCESS] Image received and saved to: {file_path}")

    conn.close()
    server_socket.close()

    os.startfile(file_path)


if __name__ == "__main__":
    start_receiver()