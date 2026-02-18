import socket
import struct
import os

DISCOVERY_PORT = 5000
TCP_PORT = 5001
BUFFER_SIZE = 4096
SAVE_FOLDER = "received_screenshot"

os.makedirs(SAVE_FOLDER, exist_ok=True)


def start_receiver():

    # ---- UDP LISTEN: wait for sender broadcast ----
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.bind(('', DISCOVERY_PORT))

    print("[WAITING] Listening for sender broadcast...")

    data, sender_addr = udp_socket.recvfrom(1024)

    if data == b"SENDER_AVAILABLE":
        sender_ip = sender_addr[0]
        print(f"[DISCOVERED] Sender at {sender_ip}")

        udp_socket.sendto(b"RECEIVER_READY", sender_addr)   # FIX: was b"RECEIVE_READY"

    udp_socket.close()

    # ---- TCP RECEIVE: accept the image ----
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(('', TCP_PORT))
    server_socket.listen(1)

    print("[TCP] Waiting for image connection...")
    conn, addr = server_socket.accept()
    print(f"[CONNECTED] {addr}")

    packed_size = conn.recv(8)
    image_size = struct.unpack("Q", packed_size)[0]

    data = b""
    while len(data) < image_size:
        packet = conn.recv(BUFFER_SIZE)   # FIX: was recvfrom() which returns a tuple
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