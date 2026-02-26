"""
sender.py
─────────
Sends an image/file to a known peer IP via TCP.

UPGRADED: No longer relies on UDP broadcast to find the receiver.
Instead it uses the peer IP already discovered by PeerDiscovery,
so it works even with router AP isolation.

Flow:
  1. Use peer IP from PeerDiscovery (passed in) or fallback to broadcast
  2. Open TCP server on TCP_PORT
  3. Notify receiver directly via UDP (not broadcast) OR broadcast as fallback
  4. Wait for TCP connection → send file → done
"""

import socket
import struct
import time
import threading
import os
from network_utils import get_network_status, verify_peer_subnet

TCP_PORT        = 5001
NOTIFY_PORT     = 5000       # UDP port for direct READY notification
BUFFER_SIZE     = 65536      # larger buffer for faster transfers
HOSTING_TIMEOUT = 60


def _notify_peer_directly(peer_ip: str, own_ip: str, stop_event: threading.Event):
    """Send IMAGE_READY directly to the known peer IP every second."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    msg  = f"IMAGE_READY|{own_ip}".encode()
    print(f"[SENDER] Notifying peer directly: {peer_ip}:{NOTIFY_PORT}")
    try:
        while not stop_event.is_set():
            try:
                sock.sendto(msg, (peer_ip, NOTIFY_PORT))
            except Exception:
                pass
            time.sleep(1.0)
    finally:
        sock.close()


def _notify_broadcast(own_ip: str, stop_event: threading.Event):
    """Fallback: broadcast IMAGE_READY to entire subnet."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    msg  = f"IMAGE_READY|{own_ip}".encode()
    print(f"[SENDER] Broadcasting IMAGE_READY as fallback...")
    try:
        while not stop_event.is_set():
            try:
                sock.sendto(msg, ("255.255.255.255", NOTIFY_PORT))
            except Exception:
                pass
            time.sleep(1.0)
    finally:
        sock.close()


def start_sender(image_path: str, peer_ip: str = None):
    """
    Send image_path to peer_ip (or broadcast-discover if peer_ip is None).

    Parameters
    ----------
    image_path : str
        Path to the file to send.
    peer_ip : str | None
        Known peer IP from PeerDiscovery. If None, falls back to broadcast.
    """

    # ── Network check ─────────────────────────────────────────────────────────
    net    = get_network_status()
    own_ip = net["ip"]

    if not net["ok"]:
        print(f"[SENDER] Aborted — {net['message']}")
        return

    print(f"[SENDER] My IP   : {own_ip}")
    print(f"[SENDER] File    : {image_path}")
    print(f"[SENDER] Target  : {peer_ip if peer_ip else 'auto (broadcast)'}")

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

    # ── Open TCP server ───────────────────────────────────────────────────────
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    server.bind(("", TCP_PORT))
    server.listen(1)
    server.settimeout(HOSTING_TIMEOUT)
    print(f"[SENDER] TCP server ready on port {TCP_PORT}")

    # ── Notify peer ───────────────────────────────────────────────────────────
    stop_notify = threading.Event()

    if peer_ip:
        notify_thread = threading.Thread(
            target=_notify_peer_directly, args=(peer_ip, own_ip, stop_notify), daemon=True
        )
    else:
        notify_thread = threading.Thread(
            target=_notify_broadcast, args=(own_ip, stop_notify), daemon=True
        )
    notify_thread.start()

    # ── Wait for receiver ─────────────────────────────────────────────────────
    conn = None
    receiver_ip = None
    try:
        print(f"[SENDER] Waiting for receiver (timeout: {HOSTING_TIMEOUT}s)...")
        conn, addr = server.accept()
        receiver_ip = addr[0]
        print(f"[SENDER] Receiver connected: {receiver_ip}")
    except socket.timeout:
        print("[SENDER] TIMEOUT — no receiver connected.")
        stop_notify.set()
        server.close()
        return
    finally:
        stop_notify.set()

    # ── Subnet check ──────────────────────────────────────────────────────────
    if not verify_peer_subnet(receiver_ip, own_ip):
        print("[SENDER] Receiver on different subnet — aborted.")
        conn.close()
        server.close()
        return

    # ── Send: header (filename len + filename + file size) + data ─────────────
    try:
        # Protocol: [4 bytes: filename_len][filename][8 bytes: file_size][data]
        header = (
            struct.pack("I", len(filename)) +
            filename +
            struct.pack("Q", file_size)
        )
        conn.sendall(header)
        conn.sendall(file_data)
        print(f"[SENDER] File sent successfully! ({file_size:,} bytes)")

    except Exception as e:
        print(f"[SENDER] ERROR during send: {e}")

    finally:
        conn.close()
        server.close()
        print("[SENDER] Reset complete.")