import time
import cv2


class FrameSource:
    def __init__(self, url: str, sample_fps: float = 2.0):
        self.url = url
        self.sample_fps = sample_fps
        self.capture = None
        self.sample_interval = 1.0 / max(sample_fps, 0.1)
        self.last_frame_time = 0.0

    def open(self):
        self.capture = cv2.VideoCapture(self.url)
        return self.capture.isOpened()

    def read(self):
        if self.capture is None:
            raise RuntimeError('capture not opened')

        now = time.time()
        if now - self.last_frame_time < self.sample_interval:
            time.sleep(self.sample_interval - (now - self.last_frame_time))

        ok, frame = self.capture.read()
        self.last_frame_time = time.time()
        return ok, frame

    def close(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None
