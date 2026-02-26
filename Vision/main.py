import cv2
import threading
from gesture import GestureDetector
from receiver import start_receiver
from sender import start_sender
from screenshot import ScreenShotManager
from network_utils import get_network_status


# ── Shared state ──────────────────────────────────────────────────────────────
# Tracks whether a send/receive operation is currently in progress.
# Prevents triggering a new gesture while one is still running.
operation_active = False
operation_status = ""       # shown on camera feed
operation_lock   = threading.Lock()


def run_sender(image_path):
    """Wrapper: runs start_sender and resets state when done."""
    global operation_active, operation_status
    try:
        start_sender(image_path)
        with operation_lock:
            operation_status = "SEND DONE"
    except Exception as e:
        print(f"[MAIN] Sender error: {e}")
        with operation_lock:
            operation_status = "SEND FAILED"
    finally:
        with operation_lock:
            operation_active = False   # ← RESET


def run_receiver():
    """Wrapper: runs start_receiver and resets state when done."""
    global operation_active, operation_status
    try:
        start_receiver()
        with operation_lock:
            operation_status = "RECEIVE DONE"
    except Exception as e:
        print(f"[MAIN] Receiver error: {e}")
        with operation_lock:
            operation_status = "RECEIVE FAILED"
    finally:
        with operation_lock:
            operation_active = False   # ← RESET


def draw_status(frame, status_text):
    """Draw a status banner at the bottom of the camera frame."""
    if not status_text:
        return frame

    h, w = frame.shape[:2]

    # Choose colour based on status
    if "DONE" in status_text:
        colour = (0, 200, 0)        # green
    elif "FAILED" in status_text or "ERROR" in status_text:
        colour = (0, 0, 220)        # red
    else:
        colour = (0, 165, 255)      # orange = in progress

    # Semi-transparent banner
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h - 50), (w, h), (30, 30, 30), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    cv2.putText(frame, status_text,
                (12, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8, colour, 2)
    return frame


def draw_network_badge(frame, net_status: dict):
    """
    Draw a small WiFi/network badge in the top-right corner of the frame.

    Green  = connected to a LAN/WiFi network  (safe to use gestures)
    Red    = no network / loopback only        (gestures are blocked)
    """
    h, w = frame.shape[:2]

    ok      = net_status["ok"]
    label   = net_status["message"]
    colour  = (0, 200, 0) if ok else (0, 0, 220)   # green / red (BGR)
    bg      = (20, 60, 20) if ok else (20, 20, 80)

    # Badge background
    badge_h = 28
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, badge_h), bg, -1)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)

    # WiFi icon text prefix
    prefix = "[WiFi OK]" if ok else "[NO WIFI]"
    text   = f"{prefix}  {label}"

    cv2.putText(frame, text,
                (10, badge_h - 7),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55, colour, 1, cv2.LINE_AA)
    return frame


def main():
    global operation_active, operation_status

    cap = cv2.VideoCapture(0)
    detector = GestureDetector()
    screenshot_manager = ScreenShotManager()

    # Refresh network status every 5 seconds so the badge stays current
    net_status = get_network_status()
    net_check_counter = 0
    NET_CHECK_INTERVAL = 150   # ~5 s at 30 fps

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
            if not net_status["ok"]:
                print(f"[MAIN] ⚠️  Network lost — {net_status['message']}")

        with operation_lock:
            active = operation_active
            status = operation_status

        # ── Handle gesture actions ────────────────────────────
        if action and not active:

            # Block gestures when there is no network
            if not net_status["ok"]:
                print("[MAIN] ⚠️  Gesture blocked — not connected to a WiFi / LAN network.")
                with operation_lock:
                    operation_status = "NO WIFI — Connect first!"
            elif action == "SEND":
                # Step 1: take screenshot immediately
                file_path = screenshot_manager.capture_and_save()
                print(f"[MAIN] SEND triggered — screenshot: {file_path}")

                # Step 2: start hosting + broadcasting in background
                with operation_lock:
                    operation_active = True
                    operation_status = "HOSTING — waiting for receiver..."

                threading.Thread(
                    target=run_sender,
                    args=(file_path,),
                    daemon=True
                ).start()

            elif action == "RECEIVE":
                print("[MAIN] RECEIVE triggered — searching for sender...")

                with operation_lock:
                    operation_active = True
                    operation_status = "SEARCHING for sender..."

                threading.Thread(
                    target=run_receiver,
                    daemon=True
                ).start()

        elif action and active:
            print(f"[MAIN] Gesture '{action}' ignored — operation already in progress.")

        # ── Draw overlays on frame ────────────────────────────
        frame = draw_network_badge(frame, net_status)
        frame = draw_status(frame, status)

        cv2.imshow("GestureDrop", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
