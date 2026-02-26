"""
receiver.py
───────────
Receives an image/file from a sender peer via TCP.

UPGRADED: Now accepts both:
  • Direct IP notification  (IMAGE_READY|<sender_ip>) → connects directly
  • Legacy broadcast        (IMAGE_READY) → uses source IP from UDP packet

Works even with router AP isolation because the sender now sends
direct UDP notifications to known peer IPs.
"""

import socket
import struct
import os
import time
from network_utils import get_network_status, verify_peer_subnet

NOTIFY_PORT    = 5000
TCP_PORT       = 5001
BUFFER_SIZE    = 65536      # larger buffer for faster transfers
SEARCH_TIMEOUT = 30         # seconds to wait for a sender notification
SAVE_FOLDER    = "received_files"

os.makedirs(SAVE_FOLDER, exist_ok=True)


def start_receiver():
    """
    Flow:
      1. Listen on NOTIFY_PORT for IMAGE_READY (direct or broadcast)
      2. Extract sender IP from notification or UDP source address
      3. Verify same subnet
      4. Connect to sender's TCP server
      5. Receive file header (filename + size) → receive data → save
    """

    # ── Network check ─────────────────────────────────────────────────────────
    net    = get_network_status()
    own_ip = net["ip"]

    if not net["ok"]:
        print(f"[RECEIVER] Aborted — {net['message']}")
        return

    print(f"[RECEIVER] My IP : {own_ip}")
    print(f"[RECEIVER] Waiting for sender notification (UDP {NOTIFY_PORT})...")

    # ── Listen for notification ───────────────────────────────────────────────
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    udp.bind(("", NOTIFY_PORT))
    udp.settimeout(SEARCH_TIMEOUT)

    sender_ip = None
    try:
        while True:
            data, addr = udp.recvfrom(256)
            incoming_ip = addr[0]

            # Skip own packets
            if incoming_ip == own_ip or incoming_ip.startswith("127.") or incoming_ip.startswith("169.254."):
                continue

            msg = data.decode("utf-8", errors="replace").strip()

            # New format: "IMAGE_READY|<sender_ip>"
            if msg.startswith("IMAGE_READY|"):
                sender_ip = msg.split("|", 1)[1].strip()
                print(f"[RECEIVER] Direct notification from {sender_ip}")
                break

            # Legacy format: "IMAGE_READY"
            elif msg == "IMAGE_READY":
                sender_ip = incoming_ip
                print(f"[RECEIVER] Broadcast notification from {sender_ip}")
                break

    except socket.timeout:
        print(f"[RECEIVER] TIMEOUT — No sender found in {SEARCH_TIMEOUT}s.")
        udp.close()
        return
    finally:
        udp.close()

    if not sender_ip:
        print("[RECEIVER] Could not determine sender IP. Aborting.")
        return

    # ── Subnet check ──────────────────────────────────────────────────────────
    if not verify_peer_subnet(sender_ip, own_ip):
        print("[RECEIVER] Sender on different subnet — aborted.")
        return

    # ── Connect to sender TCP server ──────────────────────────────────────────
    print(f"[RECEIVER] Connecting to {sender_ip}:{TCP_PORT}...")
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    client.settimeout(15)

    try:
        client.connect((sender_ip, TCP_PORT))
        print("[RECEIVER] Connected to sender.")

        # ── Read header: [4 bytes filename_len][filename][8 bytes file_size] ──
        def recv_exact(n: int) -> bytes:
            buf = b""
            while len(buf) < n:
                chunk = client.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError("Connection dropped mid-transfer.")
                buf += chunk
            return buf

        fn_len_raw = recv_exact(4)
        fn_len     = struct.unpack("I", fn_len_raw)[0]
        filename   = recv_exact(fn_len).decode("utf-8", errors="replace")
        size_raw   = recv_exact(8)
        file_size  = struct.unpack("Q", size_raw)[0]

        print(f"[RECEIVER] Receiving '{filename}' ({file_size:,} bytes)...")

        # ── Receive data ──────────────────────────────────────────────────────
        data     = b""
        received = 0
        start_t  = time.time()

        while received < file_size:
            chunk = client.recv(min(BUFFER_SIZE, file_size - received))
            if not chunk:
                break
            data     += chunk
            received += len(chunk)
            pct = int(received / file_size * 100)
            print(f"  Progress: {pct}%  ({received:,}/{file_size:,} bytes)",
                  end="\r", flush=True)

        print()
        elapsed = max(time.time() - start_t, 0.001)

        if received == file_size:
            # Save with timestamp prefix to avoid overwrites
            timestamp = int(time.time())
            save_name = f"{timestamp}_{filename}"
            save_path = os.path.join(SAVE_FOLDER, save_name)

            with open(save_path, "wb") as f:
                f.write(data)

            speed_kbps = (received / elapsed) / 1024
            print(f"[RECEIVER] Saved: {save_path}")
            print(f"[RECEIVER] Speed: {speed_kbps:.1f} KB/s  |  Time: {elapsed:.2f}s")

            # Open the file automatically
            try:
                os.startfile(save_path)
            except Exception:
                pass   # Linux/macOS don't have startfile

        else:
            print(f"[RECEIVER] Incomplete: got {received}/{file_size} bytes.")

    except socket.timeout:
        print("[RECEIVER] ERROR — Connection to sender timed out.")
    except ConnectionError as e:
        print(f"[RECEIVER] ERROR — {e}")
    except Exception as e:
        print(f"[RECEIVER] ERROR — {e}")
    finally:
        client.close()
        print("[RECEIVER] Reset complete.")


if __name__ == "__main__":
    start_receiver()