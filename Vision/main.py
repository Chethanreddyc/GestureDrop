import cv2
import threading
from gesture import GestureDetector       # FIX: was "from Vision.gesture import ..."
from receiver import start_receiver
from sender import start_sender
from screenshot import ScreenShotManager


def main():

    cap = cv2.VideoCapture(0)

    detector = GestureDetector()
    screenshot_manager = ScreenShotManager()

    action_lock = False  # prevents repeated triggering within the same gesture hold

    while True:
        success, frame = cap.read()
        if not success:
            break

        frame = cv2.flip(frame, 1)
        frame, action = detector.process_frame(frame)

        if action and not action_lock:

            action_lock = True

            if action == "SEND":
                file_path = screenshot_manager.capture_and_save()

                threading.Thread(
                    target=start_sender,
                    args=(file_path,),
                    daemon=True
                ).start()

                print("[MAIN] SEND triggered — screenshot captured and sender started.")

            elif action == "RECEIVE":
                threading.Thread(
                    target=start_receiver,
                    daemon=True
                ).start()

                print("[MAIN] RECEIVE triggered — receiver started.")

        # Reset lock when no action is returned (gesture has ended / cooldown active)
        if action is None:
            action_lock = False

        cv2.imshow("GestureDrop Camera", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
