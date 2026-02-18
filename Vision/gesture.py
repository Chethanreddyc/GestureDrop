import cv2
import mediapipe as mp
import time


class GestureDetector:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.7
        )
        self.mp_draw = mp.solutions.drawing_utils

        # Transition tracking
        self.previous_state = None
        self.last_trigger_time = 0
        self.cooldown = 3  # seconds

        # Stabilization variables
        self.candidate_state = None
        self.stable_frame_count = 0
        self.stable_frames_required = 8  # adjust if needed

    def process_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.hands.process(rgb)

        confirmed_state = None

        if result.multi_hand_landmarks:
            for hand_landmarks in result.multi_hand_landmarks:
                self.mp_draw.draw_landmarks(
                    frame,
                    hand_landmarks,
                    self.mp_hands.HAND_CONNECTIONS
                )

                raw_state = self.detect_raw_state(hand_landmarks)
                confirmed_state = self.stabilize_state(raw_state)
        else:
            self.candidate_state = None
            self.stable_frame_count = 0

        action = None
        if confirmed_state:
            action = self.get_action(confirmed_state)

            cv2.putText(frame, f"STATE: {confirmed_state}",
                        (10, 40), cv2.FONT_HERSHEY_SIMPLEX,
                        1, (0, 255, 0), 2)

        if action:
            cv2.putText(frame, f"ACTION: {action}",
                        (10, 80), cv2.FONT_HERSHEY_SIMPLEX,
                        1, (0, 0, 255), 2)

        return frame, action

    def detect_raw_state(self, hand_landmarks):
        lm = hand_landmarks.landmark

        fingers = []

        finger_tips = [8, 12, 16, 20]
        finger_pips = [6, 10, 14, 18]

        for tip, pip in zip(finger_tips, finger_pips):
            if lm[tip].y < lm[pip].y:
                fingers.append(1)
            else:
                fingers.append(0)

        # Thumb
        if lm[4].x < lm[3].x:
            fingers.append(1)
        else:
            fingers.append(0)

        if sum(fingers) >= 4:
            return "OPEN"
        elif sum(fingers) <= 1:
            return "FIST"
        else:
            return "UNKNOWN"

    def stabilize_state(self, raw_state):
        """
        Confirms gesture only after consistent detection
        across multiple frames.
        """

        if raw_state != self.candidate_state:
            self.candidate_state = raw_state
            self.stable_frame_count = 1
        else:
            self.stable_frame_count += 1

        if self.stable_frame_count >= self.stable_frames_required:
            return self.candidate_state

        return None

    def get_action(self, confirmed_state):
        if confirmed_state is None:
            return None

        current_time = time.time()

        if current_time - self.last_trigger_time < self.cooldown:
            return None

        action = None

        if self.previous_state == "OPEN" and confirmed_state == "FIST":
            action = "SEND"

        elif self.previous_state == "FIST" and confirmed_state == "OPEN":
            action = "RECEIVE"

        if action:
            self.last_trigger_time = current_time

            # 🔥 FULL RESET AFTER TRIGGER
            self.previous_state = None
            self.candidate_state = None
            self.stable_frame_count = 0

            return action

        # Only update previous_state if no action triggered
        self.previous_state = confirmed_state
        return None

    def run(self):
        cap = cv2.VideoCapture(0)

        while True:
            success, frame = cap.read()
            if not success:
                break

            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = self.hands.process(rgb)

            confirmed_state = None

            if result.multi_hand_landmarks:
                for hand_landmarks in result.multi_hand_landmarks:
                    self.mp_draw.draw_landmarks(
                        frame,
                        hand_landmarks,
                        self.mp_hands.HAND_CONNECTIONS
                    )

                    raw_state = self.detect_raw_state(hand_landmarks)
                    confirmed_state = self.stabilize_state(raw_state)

            else:
                # Reset if no hand visible
                self.candidate_state = None
                self.stable_frame_count = 0

            if confirmed_state:
                action = self.get_action(confirmed_state)

                cv2.putText(frame, f"STATE: {confirmed_state}",
                            (10, 40), cv2.FONT_HERSHEY_SIMPLEX,
                            1, (0, 255, 0), 2)

                if action:
                    cv2.putText(frame, f"ACTION: {action}",
                                (10, 80), cv2.FONT_HERSHEY_SIMPLEX,
                                1, (0, 0, 255), 2)
                    print("Triggered:", action)

            cv2.imshow("GestureDrop Camera", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()
