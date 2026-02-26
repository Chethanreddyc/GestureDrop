"""
network_utils.py
────────────────
Helpers for WiFi-only enforcement in GestureDrop.

Rules enforced:
  • The machine must have a real LAN IP (not 127.x loopback).
  • Both sender and receiver must share the same /24 subnet —
    i.e. the first three octets of their IPs must match.
  • The check is intentionally lenient about /16 vs /24 because most
    home/office routers use /24 (192.168.1.x, 10.0.0.x, etc.).

Public API
──────────
  get_lan_ip()            → str  (e.g. "192.168.1.42")
  get_subnet_prefix(ip)   → str  (e.g. "192.168.1")
  is_same_subnet(ip_a, ip_b) → bool
  get_network_status()    → dict  {ok, ip, subnet, message}
"""

import socket
import ipaddress


# ── helpers ──────────────────────────────────────────────────────────────────

def get_lan_ip() -> str:
    """Return this machine's LAN IP (not 127.x loopback)."""
    try:
        # Trick: open a UDP socket toward a public address (doesn't actually send)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_subnet_prefix(ip: str) -> str:
    """Return the /24 prefix of an IP (first 3 octets)."""
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3])
    return ""


def is_same_subnet(ip_a: str, ip_b: str) -> bool:
    """
    Return True if both IPs share the same /24 subnet.
    Also returns False when either IP is a loopback address.
    """
    try:
        if ipaddress.ip_address(ip_a).is_loopback:
            return False
        if ipaddress.ip_address(ip_b).is_loopback:
            return False
        return get_subnet_prefix(ip_a) == get_subnet_prefix(ip_b)
    except ValueError:
        return False


def get_network_status() -> dict:
    """
    Check whether this machine has a valid WiFi/LAN IP.

    Returns a dict:
      {
        "ok"      : bool,   # True = safe to proceed
        "ip"      : str,    # detected LAN IP
        "subnet"  : str,    # /24 prefix  (e.g. "192.168.1")
        "message" : str,    # human-readable status line
      }
    """
    ip = get_lan_ip()

    if ip.startswith("127."):
        return {
            "ok": False,
            "ip": ip,
            "subnet": "",
            "message": "NO WIFI — Connect to a network first!",
        }

    subnet = get_subnet_prefix(ip)
    return {
        "ok": True,
        "ip": ip,
        "subnet": subnet,
        "message": f"WiFi OK  |  {ip}",
    }


def verify_peer_subnet(peer_ip: str, own_ip: str | None = None) -> bool:
    """
    Verify that *peer_ip* is on the same /24 subnet as this machine.
    Prints warnings directly so the call-site stays clean.

    Parameters
    ----------
    peer_ip : str   IP address of the remote peer
    own_ip  : str   (optional) override for this machine's IP

    Returns
    -------
    bool  True = same subnet, safe to proceed
    """
    if own_ip is None:
        own_ip = get_lan_ip()

    if is_same_subnet(own_ip, peer_ip):
        print(f"[NETWORK] ✅ Peer {peer_ip} is on the same subnet ({get_subnet_prefix(own_ip)}.x).")
        return True
    else:
        print(
            f"[NETWORK] ❌ REJECTED — Peer {peer_ip} is NOT on the same subnet as us ({own_ip})."
            f" Make sure both devices are on the same WiFi network."
        )
        return False
