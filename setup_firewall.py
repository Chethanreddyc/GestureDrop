"""
GestureDrop - Firewall Setup Script
====================================
Run this ONCE on every machine that will use GestureDrop.
It adds Windows Firewall rules to allow UDP/TCP traffic on the required ports.

Must be run as Administrator.
"""

import subprocess
import sys
import ctypes
import os


# ── Ports used by GestureDrop ──────────────────────────────────────────────
RULES = [
    {
        "name":     "GestureDrop-UDP-Discovery-IN",
        "protocol": "UDP",
        "port":     "5000",
        "dir":      "in",
        "desc":     "Receiver listens for sender broadcast"
    },
    {
        "name":     "GestureDrop-UDP-Reply-IN",
        "protocol": "UDP",
        "port":     "5002",
        "dir":      "in",
        "desc":     "Sender listens for receiver reply"
    },
    {
        "name":     "GestureDrop-TCP-Transfer-IN",
        "protocol": "TCP",
        "port":     "5001",
        "dir":      "in",
        "desc":     "Image file transfer (TCP)"
    },
    {
        "name":     "GestureDrop-UDP-Discovery-OUT",
        "protocol": "UDP",
        "port":     "5000",
        "dir":      "out",
        "desc":     "Sender broadcasts discovery"
    },
    {
        "name":     "GestureDrop-UDP-Reply-OUT",
        "protocol": "UDP",
        "port":     "5002",
        "dir":      "out",
        "desc":     "Receiver sends reply to sender"
    },
    {
        "name":     "GestureDrop-TCP-Transfer-OUT",
        "protocol": "TCP",
        "port":     "5001",
        "dir":      "out",
        "desc":     "Image file transfer outbound"
    },
]


def is_admin():
    """Check if the script is running with Administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def elevate_and_rerun():
    """Re-launch this script with Administrator privileges."""
    print("[INFO] Requesting Administrator privileges...")
    script = os.path.abspath(__file__)
    # ShellExecute with 'runas' triggers the UAC prompt
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}"', None, 1
    )
    sys.exit(0)


def rule_exists(rule_name):
    """Check if a firewall rule with this name already exists."""
    result = subprocess.run(
        ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule_name}"],
        capture_output=True, text=True
    )
    return "No rules match" not in result.stdout


def add_rule(rule):
    """Add a single firewall rule using netsh."""
    cmd = [
        "netsh", "advfirewall", "firewall", "add", "rule",
        f"name={rule['name']}",
        f"dir={rule['dir']}",
        "action=allow",
        f"protocol={rule['protocol']}",
        f"localport={rule['port']}",
        "profile=private,domain",   # only on trusted networks, not public WiFi
        "enable=yes"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def delete_existing_rules():
    """Remove all existing GestureDrop firewall rules (for clean reinstall)."""
    for rule in RULES:
        if rule_exists(rule["name"]):
            subprocess.run(
                ["netsh", "advfirewall", "firewall", "delete", "rule",
                 f"name={rule['name']}"],
                capture_output=True
            )


def main():
    print("=" * 55)
    print("   GestureDrop — Firewall Setup")
    print("=" * 55)
    print()

    # ── Admin check ───────────────────────────────────────────
    if not is_admin():
        print("[WARNING] This script needs Administrator privileges.")
        print()
        choice = input("Auto-elevate with UAC prompt? (y/n): ").strip().lower()
        if choice == 'y':
            elevate_and_rerun()
        else:
            print()
            print("[MANUAL] Run this script from an Administrator terminal:")
            print(f"   python \"{os.path.abspath(__file__)}\"")
            input("\nPress Enter to exit...")
            sys.exit(1)

    print("[OK] Running as Administrator.\n")

    # ── Remove old rules first (clean slate) ──────────────────
    print("[STEP 1] Removing any existing GestureDrop firewall rules...")
    delete_existing_rules()
    print("         Done.\n")

    # ── Add all rules ─────────────────────────────────────────
    print("[STEP 2] Adding firewall rules...\n")
    all_ok = True
    for rule in RULES:
        success = add_rule(rule)
        status = "✓ ADDED" if success else "✗ FAILED"
        direction = "IN " if rule["dir"] == "in" else "OUT"
        print(f"   [{status}]  {rule['protocol']} {direction}  port {rule['port']:>4}  —  {rule['desc']}")
        if not success:
            all_ok = False

    print()

    # ── Result ────────────────────────────────────────────────
    if all_ok:
        print("=" * 55)
        print("   ✅  All firewall rules added successfully!")
        print("   GestureDrop is ready to use on this machine.")
        print("=" * 55)
    else:
        print("=" * 55)
        print("   ⚠️  Some rules failed. Try running manually:")
        print("   Right-click setup_firewall.py → Run as administrator")
        print("=" * 55)

    print()
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
