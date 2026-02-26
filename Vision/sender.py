"""
sender.py
─────────
Sends an image/file to a known peer IP via TCP.

UPGRADED: Connects directly to the peer's persistent TCP server.
No UDP notification needed — the receiver is always listening.

Flow:
  1. Peer IP is already known from PeerDiscovery
  2. Connect directly to peer's TCP server on TCP_PORT
  3. Send header (filename + file size) + file data
  4. Done
"""

import socket
import struct
import time
import os
from network_utils import get_network_status, verify_peer_subnet

TCP_PORT    = 5001
BUFFER_SIZE = 65536   # large buffer for faster transfers
CONNECT_TIMEOUT = 10  # seconds to wait for TCP connection


def start_sender(image_path: str, peer_ip: str = None):
    """
    Send image_path directly to peer_ip via TCP.

    Parameters
    ----------
    image_path : str
        Path to the file to send.
    peer_ip : str | None
        Known peer IP from PeerDiscovery. If None, aborts with a message.
    """

    # ── Network check ─────────────────────────────────────────────────────────
    net    = get_network_status()
    own_ip = net["ip"]

    if not net["ok"]:
        print(f"[SENDER] Aborted — {net['message']}")
        return

    if not peer_ip:
        print("[SENDER] Aborted — No peer discovered yet. Wait for a peer to appear.")
        return

    print(f"[SENDER] My IP   : {own_ip}")
    print(f"[SENDER] File    : {image_path}")
    print(f"[SENDER] Target  : {peer_ip}:{TCP_PORT}")

    # ── Subnet check ──────────────────────────────────────────────────────────
    if not verify_peer_subnet(peer_ip, own_ip):
        print("[SENDER] Peer on different subnet — aborted.")
        return

    # ── Read file ─────────────────────────────────────────────────────────────
    try:
        with open(image_path, "rb") as f:
            file_data = f.read()
    except FileNotFoundError:
        print(f"[SENDER] ERROR: File not found: {image_path}")
        return

    file_size = len(file_data)
    filename  = os.path.basename(image_path).encode("utf-8")
    print(f"[SENDER] File size: {file_size:,} bytes")

    # ── Connect directly to peer TCP server ───────────────────────────────────
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    client.settimeout(CONNECT_TIMEOUT)

    try:
        print(f"[SENDER] Connecting to {peer_ip}:{TCP_PORT}...")
        client.connect((peer_ip, TCP_PORT))
        print(f"[SENDER] Connected!")

        # ── Send: [4 bytes: filename_len][filename][8 bytes: file_size][data] ─
        header = (
            struct.pack("I", len(filename)) +
            filename +
            struct.pack("Q", file_size)
        )
        client.sendall(header)

        # Send data in chunks with progress
        sent = 0
        start_t = time.time()
        view = memoryview(file_data)
        while sent < file_size:
            chunk_end = min(sent + BUFFER_SIZE, file_size)
            client.sendall(view[sent:chunk_end])
            sent = chunk_end
            pct = int(sent / file_size * 100)
            print(f"  Progress: {pct}%  ({sent:,}/{file_size:,} bytes)",
                  end="\r", flush=True)

        print()
        elapsed = max(time.time() - start_t, 0.001)
        speed_kbps = (file_size / elapsed) / 1024
        print(f"[SENDER] ✅ File sent successfully!")
        print(f"[SENDER]    Speed: {speed_kbps:.1f} KB/s  |  Time: {elapsed:.2f}s")

    except ConnectionRefusedError:
        print(f"[SENDER] ERROR — Connection refused by {peer_ip}:{TCP_PORT}")
        print(f"[SENDER]         Make sure GestureDrop is running on the peer device.")
    except socket.timeout:
        print(f"[SENDER] ERROR — Connection to {peer_ip} timed out.")
    except Exception as e:
        print(f"[SENDER] ERROR — {e}")
    finally:
        client.close()
        print("[SENDER] Reset complete.")