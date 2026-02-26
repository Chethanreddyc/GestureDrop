"""
peer_discovery.py
─────────────────
Automatic LAN peer discovery for GestureDrop.

How it works
────────────
Uses a TWO-LAYER approach so it works even when the router has
AP isolation (blocks device-to-device UDP broadcasts):

  Layer 1  — UDP broadcast heartbeat (instant, works on most routers)
  Layer 2  — Direct subnet probe scan (fallback, always works)

Every device:
  • Broadcasts GESTUREDROP_HELLO every HEARTBEAT_INTERVAL seconds
  • Listens for broadcasts from other peers
  • Runs a background direct-probe scan every PROBE_INTERVAL seconds
    to catch peers that broadcasts can't reach (AP isolation)
  • Responds to probe requests from other scanners

Public API
──────────
  PeerDiscovery
    .start()          → begin all background threads (non-blocking)
    .stop()           → clean shutdown
    .get_peers()      → list of active peer dicts
    .best_peer()      → the most recently seen peer, or None
    .peer_count       → int property
    .on_peer_joined   → callable(peer_dict) — set this for join callbacks
    .on_peer_left     → callable(ip: str)  — set this for leave callbacks

Peer dict shape
───────────────
  {
    "ip"       : "192.168.1.55",
    "hostname" : "DESKTOP-ABC",
    "last_seen": <epoch float>,
    "via"      : "broadcast" | "direct",
  }
"""

import socket
import threading
import time

# ── Config ────────────────────────────────────────────────────────────────────
DISCOVERY_PORT     = 5005        # UDP port for heartbeat & probe
HEARTBEAT_INTERVAL = 2.0         # seconds between broadcasts
PEER_TIMEOUT       = 10.0        # seconds before a peer is considered gone
PROBE_INTERVAL     = 12.0        # seconds between full subnet probe scans
PROBE_TIMEOUT      = 0.4         # seconds per IP during probing
PROBE_BATCH        = 40          # parallel threads per probe batch
HELLO_HEADER       = b"GESTUREDROP_HELLO"
PROBE_MSG          = b"GESTUREDROP_PROBE"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_own_ip() -> str:
    """Get real LAN IP, skipping VMware/APIPA virtual adapters."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        # Reject APIPA (VMware/VPN virtual adapters) and loopback
        if not ip.startswith("169.254.") and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    # Fallback
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("169.254.") and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


def _get_hostname() -> str:
    return socket.gethostname()


def _build_hello(hostname: str, ip: str) -> bytes:
    return HELLO_HEADER + b"|" + hostname.encode() + b"|" + ip.encode()


def _parse_hello(data: bytes):
    """Returns (hostname, ip) or (None, None)."""
    try:
        if not data.startswith(HELLO_HEADER + b"|"):
            return None, None
        parts = data[len(HELLO_HEADER) + 1:].decode().split("|")
        if len(parts) >= 2:
            return parts[0], parts[1]
    except Exception:
        pass
    return None, None


# ── Main class ────────────────────────────────────────────────────────────────

class PeerDiscovery:
    """
    Runs four daemon threads:
      1. broadcaster       — UDP broadcast hello every HEARTBEAT_INTERVAL s
      2. listener          — receives broadcasts + probe requests
      3. probe_scanner     — direct subnet scan every PROBE_INTERVAL s
      4. cleanup_monitor   — evicts stale peers, fires callbacks
    """

    def __init__(self):
        self._own_ip       = _get_own_ip()
        self._own_hostname = _get_hostname()
        self._peers: dict  = {}          # ip → {hostname, last_seen, via}
        self._lock         = threading.Lock()
        self._stop_event   = threading.Event()
        self._last_peer_set: set = set()

        # Optional callbacks — set these before .start()
        self.on_peer_joined = None   # callable(peer_dict)
        self.on_peer_left   = None   # callable(ip: str)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        """Start all background threads (non-blocking)."""
        if self._own_ip.startswith("127."):
            print("[DISCOVERY] No real network — peer discovery disabled.")
            return

        print(f"\n{'─'*55}")
        print(f"  GestureDrop  |  peer discovery starting")
        print(f"  This device  :  {self._own_hostname}  ({self._own_ip})")
        print(f"  Mode         :  broadcast + direct-probe (AP-isolation safe)")
        print(f"{'─'*55}\n")

        for target in (
            self._broadcaster,
            self._listener,
            self._probe_scanner,
            self._cleanup_monitor,
        ):
            threading.Thread(target=target, daemon=True).start()

    def stop(self):
        """Signal all threads to stop."""
        self._stop_event.set()

    def get_peers(self) -> list:
        """Return a snapshot list of currently active peers."""
        now = time.time()
        with self._lock:
            return [
                {"ip": ip, **info}
                for ip, info in self._peers.items()
                if now - info["last_seen"] < PEER_TIMEOUT
            ]

    def best_peer(self) -> dict | None:
        """Return the most recently seen peer, or None if no peers."""
        peers = self.get_peers()
        if not peers:
            return None
        return max(peers, key=lambda p: p["last_seen"])

    @property
    def peer_count(self) -> int:
        return len(self.get_peers())

    # ── Thread 1: Broadcast heartbeat ─────────────────────────────────────────

    def _broadcaster(self):
        packet = _build_hello(self._own_hostname, self._own_ip)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            while not self._stop_event.is_set():
                try:
                    sock.sendto(packet, ("255.255.255.255", DISCOVERY_PORT))
                except Exception:
                    pass
                self._stop_event.wait(HEARTBEAT_INTERVAL)
        finally:
            sock.close()

    # ── Thread 2: Listener (broadcast + probe responder) ──────────────────────

    def _listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        try:
            sock.bind(("", DISCOVERY_PORT))
        except OSError as e:
            print(f"[DISCOVERY] Cannot bind listener: {e}")
            return

        hello_pkt = _build_hello(self._own_hostname, self._own_ip)

        try:
            while not self._stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(512)
                except socket.timeout:
                    continue

                sender_ip = addr[0]

                # Skip self, loopback, APIPA
                if (sender_ip == self._own_ip
                        or sender_ip.startswith("127.")
                        or sender_ip.startswith("169.254.")):
                    continue

                if data == PROBE_MSG:
                    # Respond to direct probe with our hello packet
                    try:
                        sock.sendto(hello_pkt, addr)
                    except Exception:
                        pass

                else:
                    hostname, ip = _parse_hello(data)
                    if hostname:
                        self._upsert_peer(sender_ip, hostname, "broadcast")
        finally:
            sock.close()

    # ── Thread 3: Direct probe scanner (AP-isolation bypass) ──────────────────

    def _probe_scanner(self):
        """Every PROBE_INTERVAL seconds, probe all 254 IPs in own /24 subnet."""
        # Wait a moment before first scan to let broadcast catch easy peers
        self._stop_event.wait(5)

        while not self._stop_event.is_set():
            subnet = ".".join(self._own_ip.split(".")[:3])
            all_ips = [f"{subnet}.{i}" for i in range(1, 255)]
            lock = threading.Lock()

            def probe(target_ip):
                if self._stop_event.is_set() or target_ip == self._own_ip:
                    return
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(PROBE_TIMEOUT)
                try:
                    s.sendto(PROBE_MSG, (target_ip, DISCOVERY_PORT))
                    data, addr = s.recvfrom(512)
                    hostname, ip = _parse_hello(data)
                    if hostname:
                        self._upsert_peer(addr[0], hostname, "direct")
                except (socket.timeout, OSError):
                    pass
                finally:
                    s.close()

            for i in range(0, len(all_ips), PROBE_BATCH):
                if self._stop_event.is_set():
                    break
                batch = all_ips[i:i + PROBE_BATCH]
                threads = [threading.Thread(target=probe, args=(ip,), daemon=True)
                           for ip in batch]
                for t in threads: t.start()
                for t in threads: t.join(timeout=PROBE_TIMEOUT + 0.3)

            # Wait before next scan
            self._stop_event.wait(PROBE_INTERVAL)

    # ── Thread 4: Cleanup + callbacks ─────────────────────────────────────────

    def _cleanup_monitor(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(1.0)
            now = time.time()

            with self._lock:
                stale = [ip for ip, info in self._peers.items()
                         if now - info["last_seen"] >= PEER_TIMEOUT]
                for ip in stale:
                    del self._peers[ip]
                    print(f"[DISCOVERY] Peer left: {ip}")
                    if self.on_peer_left:
                        try:
                            self.on_peer_left(ip)
                        except Exception:
                            pass

            # Fire on_peer_joined for new entries
            current_ips = {p["ip"] for p in self.get_peers()}
            new_ips = current_ips - self._last_peer_set
            if new_ips or current_ips != self._last_peer_set:
                self._last_peer_set = current_ips
                self._print_peer_list()

    def _upsert_peer(self, ip: str, hostname: str, via: str):
        """Insert or refresh a peer. Fires on_peer_joined for new entries."""
        is_new = False
        with self._lock:
            is_new = ip not in self._peers
            self._peers[ip] = {
                "hostname":  hostname,
                "last_seen": time.time(),
                "via":       via,
            }
        if is_new:
            print(f"[DISCOVERY] New peer: {hostname} ({ip}) via {via}")
            if self.on_peer_joined:
                try:
                    peer = {"ip": ip, "hostname": hostname,
                            "last_seen": time.time(), "via": via}
                    self.on_peer_joined(peer)
                except Exception:
                    pass

    def _print_peer_list(self):
        peers = self.get_peers()
        width = 55
        print(f"\n{'─'*width}")
        if not peers:
            print("  No GestureDrop peers found yet.")
            print("  (Waiting for other devices to run GestureDrop...)")
        else:
            print(f"  {len(peers)} GestureDrop peer(s) online:\n")
            for i, peer in enumerate(peers, 1):
                via = peer.get("via", "?")
                print(f"    {i}.  {peer['hostname']:<25}  [{peer['ip']}]  via {via}")
        print(f"\n  This device  :  {self._own_hostname}  ({self._own_ip})")
        print(f"{'─'*width}\n")
