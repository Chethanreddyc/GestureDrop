"""
receiver.py
───────────
Receives an image/file from a sender peer via TCP.

UPGRADED: Now runs as a persistent background TCP server.
No more gesture timing dependency — the receiver is always
listening, so the sender can connect any time it knows the peer IP.

Flow:
  1. Background TCP server starts on TCP_PORT at app launch (via start_background_receiver)
  2. When sender connects, receives file → saves → opens it
  3. Server stays alive for the entire session (handles multiple transfers)
"""

import socket
import struct
import os
import time
import threading
from network_utils import get_network_status, verify_peer_subnet

TCP_PORT    = 5001
BUFFER_SIZE = 65536
SAVE_FOLDER = "received_files"

os.makedirs(SAVE_FOLDER, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Background persistent receiver (used by main.py at startup)
# ─────────────────────────────────────────────────────────────────────────────

_receiver_thread  = None
_receiver_running = False


def start_background_receiver():
    """
    Spin up a persistent TCP server in a daemon thread.
    Call this once at app startup — it listens forever.
    """
    global _receiver_thread, _receiver_running
    if _receiver_running:
        return  # already running

    _receiver_running = True
    _receiver_thread = threading.Thread(
        target=_persistent_server, daemon=True
    )
    _receiver_thread.start()
    print(f"[RECEIVER] Background server started on TCP port {TCP_PORT}")


def _persistent_server():
    """Internal: accept incoming connections forever."""
    net = get_network_status()
    if not net["ok"]:
        print(f"[RECEIVER] No network — background server not started.")
        return

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("", TCP_PORT))
    except OSError as e:
        print(f"[RECEIVER] Cannot bind TCP server on port {TCP_PORT}: {e}")
        return

    server.listen(5)
    server.settimeout(1.0)  # so we can check _receiver_running periodically
    print(f"[RECEIVER] Listening on {net['ip']}:{TCP_PORT}")

    while _receiver_running:
        try:
            conn, addr = server.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        # Handle each incoming connection in its own thread
        threading.Thread(
            target=_handle_connection,
            args=(conn, addr[0]),
            daemon=True
        ).start()

    server.close()
    print("[RECEIVER] Background server stopped.")


def stop_background_receiver():
    """Call at app shutdown."""
    global _receiver_running
    _receiver_running = False


# ─────────────────────────────────────────────────────────────────────────────
# Connection handler (called per incoming transfer)
# ─────────────────────────────────────────────────────────────────────────────

def _handle_connection(conn: socket.socket, sender_ip: str):
    own_ip = get_network_status()["ip"]

    # Subnet guard
    if not verify_peer_subnet(sender_ip, own_ip):
        print(f"[RECEIVER] Rejected {sender_ip} — different subnet.")
        conn.close()
        return

    conn.settimeout(30)
    print(f"\n[RECEIVER] Incoming transfer from {sender_ip}")

    try:
        def recv_exact(n: int) -> bytes:
            buf = b""
            while len(buf) < n:
                chunk = conn.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError("Connection dropped mid-transfer.")
                buf += chunk
            return buf

        # Header: [4 bytes: filename_len][filename][8 bytes: file_size]
        fn_len   = struct.unpack("I", recv_exact(4))[0]
        filename = recv_exact(fn_len).decode("utf-8", errors="replace")
        filesize = struct.unpack("Q", recv_exact(8))[0]

        print(f"[RECEIVER] Receiving '{filename}'  ({filesize:,} bytes)...")

        data     = b""
        received = 0
        start_t  = time.time()

        while received < filesize:
            chunk = conn.recv(min(BUFFER_SIZE, filesize - received))
            if not chunk:
                break
            data     += chunk
            received += len(chunk)
            pct = int(received / filesize * 100)
            print(f"  Progress: {pct}%  ({received:,}/{filesize:,} bytes)",
                  end="\r", flush=True)

        print()
        elapsed = max(time.time() - start_t, 0.001)

        if received == filesize:
            timestamp = int(time.time())
            save_name = f"{timestamp}_{filename}"
            save_path = os.path.join(SAVE_FOLDER, save_name)
            with open(save_path, "wb") as f:
                f.write(data)

            speed_kbps = (received / elapsed) / 1024
            print(f"[RECEIVER] ✅ Saved: {save_path}")
            print(f"[RECEIVER]    Speed: {speed_kbps:.1f} KB/s  |  Time: {elapsed:.2f}s")

            try:
                os.startfile(save_path)
            except Exception:
                pass  # Non-Windows platforms

        else:
            print(f"[RECEIVER] ⚠️  Incomplete: got {received}/{filesize} bytes.")

    except socket.timeout:
        print("[RECEIVER] ERROR — Transfer timed out.")
    except ConnectionError as e:
        print(f"[RECEIVER] ERROR — {e}")
    except Exception as e:
        print(f"[RECEIVER] ERROR — {e}")
    finally:
        conn.close()
        print("[RECEIVER] Connection closed.\n")


# ─────────────────────────────────────────────────────────────────────────────
# Legacy one-shot receiver (kept for backward compatibility / standalone use)
# ─────────────────────────────────────────────────────────────────────────────

def start_receiver():
    """
    Legacy gesture-triggered receiver.
    Still usable but superseded by start_background_receiver().
    Waits for exactly one incoming TCP connection, then returns.
    """
    net    = get_network_status()
    own_ip = net["ip"]

    if not net["ok"]:
        print(f"[RECEIVER] Aborted — {net['message']}")
        return

    print(f"[RECEIVER] My IP : {own_ip}")
    print(f"[RECEIVER] Waiting for one incoming transfer on TCP {TCP_PORT}…")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("", TCP_PORT))
    except OSError as e:
        print(f"[RECEIVER] Cannot bind: {e}  (background server may already be running)")
        return

    server.listen(1)
    server.settimeout(60)

    try:
        conn, addr = server.accept()
        _handle_connection(conn, addr[0])
    except socket.timeout:
        print("[RECEIVER] TIMEOUT — No sender connected in 60s.")
    finally:
        server.close()


if __name__ == "__main__":
    start_receiver()