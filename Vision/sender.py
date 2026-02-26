import socket
import struct
import time
import threading
from network_utils import get_lan_ip, get_network_status, verify_peer_subnet

BROADCAST_PORT = 5000       # sender broadcasts on this port
TCP_PORT       = 5001       # sender hosts image on this port
BUFFER_SIZE    = 4096
BROADCAST_INTERVAL = 1.0    # seconds between each broadcast
HOSTING_TIMEOUT    = 60     # seconds to wait for a receiver before giving up


def start_sender(image_path):
    """
    Flow:
      0. Verify this machine is on a real WiFi/LAN network
      1. Take screenshot (already done by main.py before calling this)
      2. Open a TCP server to host the image
      3. Broadcast IMAGE_READY repeatedly until a receiver connects
      4. Verify receiver is on the same /24 subnet
      5. Send image → close → reset
    """

    # ── 0. Network check ──────────────────────────────────────
    net = get_network_status()
    own_ip = net["ip"]

    if not net["ok"]:
        print(f"[SENDER] ❌ Aborted — {net['message']}")
        return

    print(f"[SENDER] My IP  : {own_ip}  (subnet {net['subnet']}.x)")
    print(f"[SENDER] Hosting: {image_path}")

    # ── Read image into memory once ───────────────────────────
    try:
        with open(image_path, "rb") as f:
            image_data = f.read()
    except FileNotFoundError:
        print(f"[SENDER] ERROR: Image file not found: {image_path}")
        return

    image_size = len(image_data)
    print(f"[SENDER] Image size: {image_size} bytes")

    # ── Open TCP server ───────────────────────────────────────
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('', TCP_PORT))
    server_socket.listen(1)
    server_socket.settimeout(HOSTING_TIMEOUT)

    print(f"[SENDER] TCP server ready on port {TCP_PORT}")

    # ── Broadcast IMAGE_READY in background thread ────────────
    stop_broadcast = threading.Event()

    def broadcast_loop():
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while not stop_broadcast.is_set():
            udp.sendto(b"IMAGE_READY", ('255.255.255.255', BROADCAST_PORT))
            print("[SENDER] Broadcasting IMAGE_READY...")
            time.sleep(BROADCAST_INTERVAL)
        udp.close()

    broadcast_thread = threading.Thread(target=broadcast_loop, daemon=True)
    broadcast_thread.start()

    # ── Wait for receiver to connect ──────────────────────────
    conn = None
    receiver_ip = None
    try:
        print(f"[SENDER] Waiting for receiver to connect (timeout: {HOSTING_TIMEOUT}s)...")
        conn, addr = server_socket.accept()
        receiver_ip = addr[0]
        print(f"[SENDER] Receiver connected from {receiver_ip}")

    except socket.timeout:
        print("[SENDER] TIMEOUT — No receiver connected within 60 seconds. Resetting.")
        stop_broadcast.set()
        server_socket.close()
        return  # ← reset: main.py action_lock will be cleared

    finally:
        stop_broadcast.set()  # always stop broadcasting once someone connects or times out

    # ── Subnet validation ─────────────────────────────────────
    if not verify_peer_subnet(receiver_ip, own_ip):
        print("[SENDER] ❌ Receiver is on a DIFFERENT network. Transfer aborted for security.")
        conn.close()
        server_socket.close()
        return

    # ── Send image ────────────────────────────────────────────
    try:
        conn.sendall(struct.pack("Q", image_size))
        conn.sendall(image_data)
        print("✅ [SENDER] Image sent successfully!")

    except Exception as e:
        print(f"[SENDER] ERROR sending image: {e}")

    finally:
        conn.close()
        server_socket.close()
        print("[SENDER] Reset complete — ready for next gesture.")