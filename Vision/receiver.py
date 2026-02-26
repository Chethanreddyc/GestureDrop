import socket
import struct
import os
import time
from network_utils import get_lan_ip, get_network_status, verify_peer_subnet

BROADCAST_PORT  = 5000      # listen for sender's broadcast on this port
TCP_PORT        = 5001      # connect to sender's TCP server on this port
BUFFER_SIZE     = 4096
SEARCH_TIMEOUT  = 15        # seconds to search for a sender before giving up
SAVE_FOLDER     = "received_screenshot"

os.makedirs(SAVE_FOLDER, exist_ok=True)


def start_receiver():
    """
    Flow:
      0. Verify this machine is on a real WiFi/LAN network
      1. Listen for sender's IMAGE_READY broadcast
      2. Ignore own broadcasts (self-loopback fix)
      3. Verify sender is on the same /24 subnet
      4. Connect to sender's TCP server
      5. Pull image → save → open → reset
    """

    # ── 0. Network check ──────────────────────────────────────
    net = get_network_status()
    own_ip = net["ip"]

    if not net["ok"]:
        print(f"[RECEIVER] ❌ Aborted — {net['message']}")
        return

    print(f"[RECEIVER] My IP  : {own_ip}  (subnet {net['subnet']}.x)")
    print(f"[RECEIVER] Searching for sender broadcast on port {BROADCAST_PORT}...")

    # ── UDP: search for sender broadcast ─────────────────────
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_socket.bind(('', BROADCAST_PORT))
    udp_socket.settimeout(SEARCH_TIMEOUT)

    sender_ip = None
    try:
        while True:
            data, sender_addr = udp_socket.recvfrom(1024)
            incoming_ip = sender_addr[0]

            # ── Self-loopback fix: ignore own broadcasts ──────
            if incoming_ip == own_ip or incoming_ip == "127.0.0.1":
                print(f"[RECEIVER] Ignoring own broadcast from {incoming_ip}")
                continue

            if data == b"IMAGE_READY":
                # ── Subnet validation ─────────────────────────
                if not verify_peer_subnet(incoming_ip, own_ip):
                    print(
                        f"[RECEIVER] ⚠️  Ignoring sender {incoming_ip} — "
                        f"different network. Make sure both devices are on the same WiFi."
                    )
                    continue   # keep listening in case a same-subnet sender appears

                sender_ip = incoming_ip
                print(f"[RECEIVER] ✅ Found sender at {sender_ip}")
                break

    except socket.timeout:
        print(f"[RECEIVER] TIMEOUT — No sender found within {SEARCH_TIMEOUT}s. Resetting.")
        udp_socket.close()
        return  # ← reset

    udp_socket.close()

    # ── TCP: connect to sender and pull image ─────────────────
    print(f"[RECEIVER] Connecting to sender {sender_ip}:{TCP_PORT}...")

    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.settimeout(10)

    try:
        client_socket.connect((sender_ip, TCP_PORT))
        print("[RECEIVER] Connected to sender.")

        # Receive image size header (8 bytes)
        packed_size = b""
        while len(packed_size) < 8:
            chunk = client_socket.recv(8 - len(packed_size))
            if not chunk:
                raise ConnectionError("Connection closed before size received.")
            packed_size += chunk

        image_size = struct.unpack("Q", packed_size)[0]
        print(f"[RECEIVER] Expecting {image_size} bytes...")

        # Receive image data
        data = b""
        while len(data) < image_size:
            packet = client_socket.recv(BUFFER_SIZE)
            if not packet:
                break
            data += packet

        if len(data) == image_size:
            # Save with timestamp so files don't overwrite each other
            timestamp = int(time.time())
            file_path = os.path.join(SAVE_FOLDER, f"received_{timestamp}.png")

            with open(file_path, "wb") as f:
                f.write(data)

            print(f"[RECEIVER] ✅ Image saved to: {file_path}")
            os.startfile(file_path)

        else:
            print(f"[RECEIVER] ⚠️ Incomplete image: got {len(data)}/{image_size} bytes.")

    except socket.timeout:
        print("[RECEIVER] ERROR — Connection to sender timed out.")

    except ConnectionError as e:
        print(f"[RECEIVER] ERROR — {e}")

    except Exception as e:
        print(f"[RECEIVER] ERROR — Unexpected error: {e}")

    finally:
        client_socket.close()
        print("[RECEIVER] Reset complete — ready for next gesture.")


if __name__ == "__main__":
    start_receiver()