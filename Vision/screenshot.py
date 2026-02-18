import pyautogui
import time
import os


class ScreenShotManager:

    def __init__(self, save_directory="screenshot"):
        self.capture_delay = 0.5
        self.save_directory = save_directory

        if not os.path.exists(self.save_directory):
            os.makedirs(self.save_directory)

    def capture_and_save(self):
        time.sleep(self.capture_delay)

        screenshot = pyautogui.screenshot()

        filename = f"screenshot_{int(time.time())}.png"
        file_path = os.path.join(self.save_directory, filename)

        screenshot.save(file_path)

        print(f"[SCREENSHOT] Saved to: {file_path}")
        return file_path