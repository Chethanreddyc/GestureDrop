"""
peer_discovery.py
─────────────────
Automatic LAN peer discovery for GestureDrop.

How it works
────────────
Every device running GestureDrop broadcasts a small UDP packet
("GESTUREDROP_HELLO|<hostname>|<ip>") every HEARTBEAT_INTERVAL seconds on
DISCOVERY_PORT.  Every device also listens on that port and records any
peer it hears from.  If a peer hasn't been heard from in PEER_TIMEOUT
seconds it is removed from the list.

Public API
──────────
  PeerDiscovery               ← main class
    .start()                  ← begin broadcasting + listening (non-blocking)
    .stop()                   ← clean shutdown
    .get_peers()              ← returns list of peer dicts
    .peer_count               ← int property

Peer dict shape
───────────────
  {
    "ip"       : "192.168.1.55",
    "hostname" : "DESKTOP-ABC123",
    "last_seen": <epoch float>,
  }
"""

import socket
import threading
import time
import os

# ── Config ────────────────────────────────────────────────────────────────────
DISCOVERY_PORT     = 5005          # dedicated UDP port for peer heartbeats
HEARTBEAT_INTERVAL = 2.0           # seconds between each broadcast
PEER_TIMEOUT       = 8.0           # seconds before a peer is considered gone
HEADER             = b"GESTUREDROP_HELLO"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_own_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _get_hostname() -> str:
    return socket.gethostname()


def _build_packet(hostname: str, ip: str) -> bytes:
    return HEADER + b"|" + hostname.encode() + b"|" + ip.encode()


def _parse_packet(data: bytes):
    """
    Parse incoming packet.  Returns (hostname, ip) or (None, None) if invalid.
    """
    try:
        if not data.startswith(HEADER + b"|"):
            return None, None
        parts = data[len(HEADER) + 1:].decode().split("|")
        if len(parts) == 2:
            return parts[0], parts[1]
    except Exception:
        pass
    return None, None


# ── Main class ────────────────────────────────────────────────────────────────

class PeerDiscovery:
    """
    Runs two daemon threads:
      • broadcaster  — sends heartbeat UDP broadcast every HEARTBEAT_INTERVAL s
      • listener     — receives heartbeats and updates peer table
    A third cleanup thread evicts stale peers and prints the peer list to
    the terminal whenever it changes.
    """

    def __init__(self):
        self._own_ip       = _get_own_ip()
        self._own_hostname = _get_hostname()
        self._peers: dict  = {}          # ip → {hostname, last_seen}
        self._lock         = threading.Lock()
        self._stop_event   = threading.Event()
        self._last_printed : set = set() # track what we last printed to avoid spam

    # ── Public ───────────────────────────────────────────────

    def start(self):
        """Start all background threads (non-blocking)."""
        if self._own_ip.startswith("127."):
            print("[DISCOVERY] ⚠️  No real network detected — peer discovery disabled.")
            return

        print(f"\n{'─'*55}")
        print(f"  GestureDrop  |  peer discovery starting up")
        print(f"  This device  :  {self._own_hostname}  ({self._own_ip})")
        print(f"{'─'*55}\n")

        for target in (self._broadcaster, self._listener, self._cleanup_and_print):
            t = threading.Thread(target=target, daemon=True)
            t.start()

    def stop(self):
        """Signal all threads to stop."""
        self._stop_event.set()

    def get_peers(self) -> list:
        """Return a snapshot list of currently active peers (excludes self)."""
        now = time.time()
        with self._lock:
            return [
                {"ip": ip, **info}
                for ip, info in self._peers.items()
                if now - info["last_seen"] < PEER_TIMEOUT
            ]

    @property
    def peer_count(self) -> int:
        return len(self.get_peers())

    # ── Background threads ────────────────────────────────────

    def _broadcaster(self):
        """Send a heartbeat UDP broadcast repeatedly."""
        packet = _build_packet(self._own_hostname, self._own_ip)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            while not self._stop_event.is_set():
                sock.sendto(packet, ("255.255.255.255", DISCOVERY_PORT))
                time.sleep(HEARTBEAT_INTERVAL)
        finally:
            sock.close()

    def _listener(self):
        """Listen for heartbeats from other GestureDrop peers."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", DISCOVERY_PORT))
        sock.settimeout(1.0)
        try:
            while not self._stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(512)
                except socket.timeout:
                    continue

                sender_ip = addr[0]

                # Ignore our own broadcasts
                if sender_ip == self._own_ip or sender_ip == "127.0.0.1":
                    continue

                hostname, ip = _parse_packet(data)
                if hostname is None:
                    continue

                with self._lock:
                    self._peers[sender_ip] = {
                        "hostname"  : hostname,
                        "last_seen" : time.time(),
                    }
        finally:
            sock.close()

    def _cleanup_and_print(self):
        """
        Periodically evict stale peers and reprint the peer list to the
        terminal whenever the set of alive peers changes.
        """
        while not self._stop_event.is_set():
            time.sleep(1.0)
            now = time.time()

            # Evict stale peers
            with self._lock:
                stale = [ip for ip, info in self._peers.items()
                         if now - info["last_seen"] >= PEER_TIMEOUT]
                for ip in stale:
                    del self._peers[ip]
                    print(f"\n[DISCOVERY] 🔴 Peer left: {ip}")

            # Check if list changed
            current_ips = {p["ip"] for p in self.get_peers()}
            if current_ips != self._last_printed:
                self._last_printed = current_ips
                self._print_peer_list()

    def _print_peer_list(self):
        """Pretty-print the current peer list to the terminal."""
        peers = self.get_peers()
        count = len(peers)
        width = 55

        print(f"\n{'─'*width}")
        if count == 0:
            print("  🔍  No other GestureDrop peers found on this network.")
            print(f"     (Waiting for other devices to run GestureDrop...)")
        else:
            print(f"  ✅  {count} GestureDrop peer{'s' if count > 1 else ''} connected on this WiFi:\n")
            for i, peer in enumerate(peers, 1):
                hostname = peer["hostname"]
                ip       = peer["ip"]
                print(f"    {i}.  {hostname:<25}  [{ip}]")

        print(f"\n  This device  :  {self._own_hostname}  ({self._own_ip})")
        print(f"{'─'*width}\n")
