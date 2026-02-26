import cv2
import threading
from gesture import GestureDetector
from receiver import start_background_receiver, stop_background_receiver
from sender import start_sender
from screenshot import ScreenShotManager
from network_utils import get_network_status
from peer_discovery import PeerDiscovery


# ── Shared state ──────────────────────────────────────────────────────────────
operation_active = False
operation_status = ""
operation_lock   = threading.Lock()


def run_sender(image_path, peer_ip=None):
    """Wrapper: runs start_sender with known peer IP and resets state when done."""
    global operation_active, operation_status
    try:
        start_sender(image_path, peer_ip=peer_ip)
        with operation_lock:
            operation_status = "SEND DONE"
    except Exception as e:
        print(f"[MAIN] Sender error: {e}")
        with operation_lock:
            operation_status = "SEND FAILED"
    finally:
        with operation_lock:
            operation_active = False


# ── Frame overlay helpers ─────────────────────────────────────────────────────

def draw_status(frame, status_text):
    """Draw a status banner at the bottom of the camera frame."""
    if not status_text:
        return frame

    h, w = frame.shape[:2]

    if "DONE" in status_text:
        colour = (0, 200, 0)
    elif "FAILED" in status_text or "ERROR" in status_text or "NO WIFI" in status_text:
        colour = (0, 0, 220)
    else:
        colour = (0, 165, 255)

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h - 50), (w, h), (30, 30, 30), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    cv2.putText(frame, status_text, (12, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, colour, 2)
    return frame


def draw_network_badge(frame, net_status: dict, peer_count: int):
    """
    Top banner showing:
      • WiFi status  (green = connected, red = no network)
      • Number of GestureDrop peers currently discovered on the LAN
    """
    h, w = frame.shape[:2]
    ok     = net_status["ok"]
    colour = (0, 220, 0) if ok else (0, 0, 220)
    bg     = (20, 60, 20) if ok else (20, 20, 80)

    badge_h = 32
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, badge_h), bg, -1)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)

    wifi_tag  = "[WiFi OK]" if ok else "[NO WIFI]"
    peer_tag  = f"| Peers: {peer_count}" if ok else ""
    ip_tag    = f"| {net_status['ip']}" if ok else ""
    text      = f"{wifi_tag}  {ip_tag}  {peer_tag}"

    cv2.putText(frame, text, (10, badge_h - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 1, cv2.LINE_AA)
    return frame


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global operation_active, operation_status

    # ── Start peer discovery + background receiver ──────────────
    discovery = PeerDiscovery()
    discovery.start()
    start_background_receiver()   # always-on TCP server, no gesture needed

    cap = cv2.VideoCapture(0)
    detector = GestureDetector()
    screenshot_manager = ScreenShotManager()

    # Network status — refresh every ~5 s (150 frames @ ~30 fps)
    net_status        = get_network_status()
    net_check_counter = 0
    NET_CHECK_INTERVAL = 150

    print(f"[MAIN] Network: {net_status['message']}")

    while True:
        success, frame = cap.read()
        if not success:
            break

        frame = cv2.flip(frame, 1)
        frame, action = detector.process_frame(frame)

        # ── Periodic network refresh ──────────────────────────
        net_check_counter += 1
        if net_check_counter >= NET_CHECK_INTERVAL:
            net_status = get_network_status()
            net_check_counter = 0

        with operation_lock:
            active = operation_active
            status = operation_status

        # ── Handle gesture actions ────────────────────────────
        if action and not active:

            if not net_status["ok"]:
                print("[MAIN] ⚠️  Gesture blocked — not connected to a WiFi / LAN network.")
                with operation_lock:
                    operation_status = "NO WIFI — Connect first!"

            elif action == "SEND":
                best = discovery.best_peer()
                if not best:
                    print("[MAIN] SEND gesture — no peer discovered yet, ignoring.")
                    with operation_lock:
                        operation_status = "NO PEER — wait for discovery..."
                else:
                    peer_ip   = best["ip"]
                    peer_name = best["hostname"]
                    file_path = screenshot_manager.capture_and_save()
                    print(f"[MAIN] SEND triggered -> {peer_ip} ({peer_name})")
                    with operation_lock:
                        operation_active = True
                        operation_status = f"SENDING to {peer_name}..."
                    threading.Thread(
                        target=run_sender, args=(file_path, peer_ip), daemon=True
                    ).start()

        elif action and active:
            print(f"[MAIN] Gesture '{action}' ignored — operation already in progress.")

        # ── Draw overlays ─────────────────────────────────────
        peer_count = discovery.peer_count
        frame = draw_network_badge(frame, net_status, peer_count)
        frame = draw_status(frame, status)

        cv2.imshow("GestureDrop", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # ── Cleanup ───────────────────────────────────────────────
    discovery.stop()
    stop_background_receiver()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
