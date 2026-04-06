from __future__ import annotations

import io
import threading
import time
import traceback
from datetime import datetime
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import settings
from .state import runtime_state

try:  # pragma: no cover
    from picamera2 import Picamera2  # type: ignore
except Exception:  # pragma: no cover
    Picamera2 = None

try:  # pragma: no cover
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None


class CameraService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._picamera2 = None
        self._opencv_cap = None
        self._source_name = "booting"
        self._frame_jpeg: bytes = self._placeholder_frame("booting")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

        if self._opencv_cap is not None:
            try:
                self._opencv_cap.release()
            except Exception:
                pass
            self._opencv_cap = None

        if self._picamera2 is not None:
            try:
                self._picamera2.stop()
            except Exception:
                pass
            self._picamera2 = None

    def get_frame(self) -> bytes:
        with self._lock:
            return self._frame_jpeg

    def get_source_name(self) -> str:
        return self._source_name

    def mjpeg_generator(self):
        delay = max(0.03, 1.0 / max(1, settings.camera_fps))
        while not self._stop.is_set():
            frame = self.get_frame()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
            time.sleep(delay)

    def _capture_loop(self) -> None:
        camera_ready = self._init_camera()
        if not camera_ready and not settings.placeholder_stream:
            self._source_name = "unavailable"

        while not self._stop.is_set():
            try:
                frame = self._capture_from_device() if camera_ready else None
                if frame is None:
                    frame = self._placeholder_frame("camera unavailable")
                with self._lock:
                    self._frame_jpeg = frame
            except Exception as e:
                print("[camera] capture error:", repr(e), flush=True)
                traceback.print_exc()
                with self._lock:
                    self._frame_jpeg = self._placeholder_frame("capture error")

            time.sleep(max(0.03, 1.0 / max(1, settings.camera_fps)))

    def _init_camera(self) -> bool:
        preferred = settings.camera_source.lower()

        if preferred in {"auto", "picamera2"} and settings.camera_use_picamera2 and Picamera2:
            try:
                self._picamera2 = Picamera2()
                config = self._picamera2.create_video_configuration(
                    main={"size": (settings.camera_width, settings.camera_height)}
                )
                self._picamera2.configure(config)
                self._picamera2.start()
                time.sleep(0.5)
                self._source_name = "picamera2"
                print("[camera] picamera2 initialized", flush=True)
                return True
            except Exception as e:
                print("[camera] picamera2 init failed:", repr(e), flush=True)
                traceback.print_exc()
                self._picamera2 = None

        if preferred in {"auto", "opencv"} and cv2 is not None:
            try:
                self._opencv_cap = cv2.VideoCapture(settings.camera_device_index)
                self._opencv_cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.camera_width)
                self._opencv_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.camera_height)
                self._opencv_cap.set(cv2.CAP_PROP_FPS, settings.camera_fps)

                if self._opencv_cap.isOpened():
                    self._source_name = "opencv"
                    print("[camera] opencv initialized", flush=True)
                    return True

                self._opencv_cap.release()
                self._opencv_cap = None
            except Exception as e:
                print("[camera] opencv init failed:", repr(e), flush=True)
                traceback.print_exc()
                self._opencv_cap = None

        self._source_name = "placeholder"
        return False

    def _capture_from_device(self) -> bytes | None:
        if self._picamera2 is not None:
            array = self._picamera2.capture_array()
            image = self._image_from_array(array)
            return self._encode_image(self._decorate(image))

        if self._opencv_cap is not None and cv2 is not None:
            ok, frame = self._opencv_cap.read()
            if not ok:
                return None
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(frame)
            return self._encode_image(self._decorate(image))

        return None

    def _image_from_array(self, array) -> Image.Image:
        arr = np.asarray(array)

        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)

        if arr.ndim == 2:
            return Image.fromarray(arr).convert("RGB")

        if arr.ndim == 3:
            channels = arr.shape[2]

            if channels == 4:
                arr = arr[:, :, :3]
                return Image.fromarray(arr, "RGB")

            if channels == 3:
                return Image.fromarray(arr, "RGB")

            if channels == 1:
                return Image.fromarray(arr[:, :, 0]).convert("RGB")

        raise ValueError(f"Unsupported camera frame shape: {getattr(arr, 'shape', None)}")

    def _decorate(self, image: Image.Image) -> Image.Image:
        if settings.camera_rotation:
            image = image.rotate(settings.camera_rotation, expand=True)
        if settings.camera_hflip:
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
        if settings.camera_vflip:
            image = image.transpose(Image.FLIP_TOP_BOTTOM)

        if settings.camera_text_overlay:
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default()
            state = runtime_state.snapshot()
            text = (
                f"{settings.device_name} | {state.get('status')} | "
                f"snow={state.get('snow_detected')} | heater={state.get('heater_on')} | "
                f"temp={state.get('temperature')}C | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            draw.rectangle((0, 0, image.width, 24), fill=(0, 0, 0))
            draw.text((8, 6), text, fill=(255, 255, 255), font=font)

        return image

    def _placeholder_frame(self, reason: str) -> bytes:
        image = Image.new("RGB", (settings.camera_width, settings.camera_height), (17, 24, 39))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        state = runtime_state.snapshot()

        lines = [
            settings.device_name,
            f"serial: {settings.device_serial}",
            f"camera: {getattr(self, '_source_name', 'booting')}",
            f"reason: {reason}",
            f"status: {state.get('status')}",
            f"snow: {state.get('snow_detected')} ({state.get('snow_confidence')})",
            f"heater: {state.get('heater_on')} / mode={state.get('heater_mode')}",
            f"temp: {state.get('temperature')}C  humidity: {state.get('humidity')}%",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ]

        y = 40
        draw.rectangle(
            (20, 20, settings.camera_width - 20, settings.camera_height - 20),
            outline=(90, 120, 200),
            width=2,
        )
        for line in lines:
            draw.text((40, y), line, fill=(255, 255, 255), font=font)
            y += 28

        return self._encode_image(image)

    def _encode_image(self, image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=settings.camera_jpeg_quality)
        return buffer.getvalue()


camera_service = CameraService()
