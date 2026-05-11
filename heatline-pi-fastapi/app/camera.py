from __future__ import annotations

import io
import threading
import time
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
        self._source_name = "booting"
        self._frame_jpeg: bytes = self._placeholder_frame("booting")
        self._frame_rgb: np.ndarray | None = None
        self._picamera2 = None
        self._opencv_cap = None
        self._source_name = "placeholder"

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
            self._opencv_cap.release()
        if self._picamera2 is not None:
            try:
                self._picamera2.stop()
            except Exception:
                pass

    def get_frame(self) -> bytes:
        with self._lock:
            return self._frame_jpeg

    def get_latest_frame_rgb(self) -> np.ndarray | None:
        with self._lock:
            if self._frame_rgb is None:
                return None
            return np.array(self._frame_rgb, copy=True)

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
                image = self._capture_image_from_device() if camera_ready else None
                if image is None:
                    placeholder = self._placeholder_frame("camera unavailable")
                    with self._lock:
                        self._frame_jpeg = placeholder
                        self._frame_rgb = None
                else:
                    normalized = self._normalize_image(image)
                    rgb = np.asarray(normalized).copy()
                    decorated = self._decorate(normalized.copy())
                    encoded = self._encode_image(decorated)
                    with self._lock:
                        self._frame_jpeg = encoded
                        self._frame_rgb = rgb
            except Exception as exc:
                print(f"[camera] capture loop error: {type(exc).__name__}: {exc}", flush=True)
                with self._lock:
                    self._frame_jpeg = self._placeholder_frame(f"capture error: {type(exc).__name__}")
                    self._frame_rgb = None
            time.sleep(max(0.03, 1.0 / max(1, settings.camera_fps)))

    def _init_camera(self) -> bool:
        preferred = settings.camera_source.lower()
        if preferred in {"auto", "picamera2"} and settings.camera_use_picamera2 and Picamera2:
            try:
                self._picamera2 = Picamera2()
                config = self._picamera2.create_video_configuration(
                    main={
                        "size": (settings.camera_width, settings.camera_height),
                        "format": "RGB888",
                    }
                )
                self._picamera2.configure(config)
                self._picamera2.start()
                self._source_name = "picamera2"
                return True
            except Exception:
                self._picamera2 = None
        if preferred in {"auto", "opencv"} and cv2 is not None:
            try:
                self._opencv_cap = cv2.VideoCapture(settings.camera_device_index)
                self._opencv_cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.camera_width)
                self._opencv_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.camera_height)
                self._opencv_cap.set(cv2.CAP_PROP_FPS, settings.camera_fps)
                if self._opencv_cap.isOpened():
                    self._source_name = "opencv"
                    return True
                self._opencv_cap.release()
                self._opencv_cap = None
            except Exception:
                self._opencv_cap = None
        self._source_name = "placeholder"
        return False

    def _capture_image_from_device(self) -> Image.Image | None:
        if self._picamera2 is not None:
            array = self._picamera2.capture_array()
            if getattr(array, "ndim", 0) == 3 and array.shape[2] >= 3:
                image = Image.fromarray(np.ascontiguousarray(array[:, :, :3]), "RGB")
            else:
                image = Image.fromarray(array)
                if image.mode != "RGB":
                    image = image.convert("RGB")
            return image
        if self._opencv_cap is not None and cv2 is not None:
            ok, frame = self._opencv_cap.read()
            if not ok:
                return None
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return Image.fromarray(frame)
        return None

    def _normalize_image(self, image: Image.Image) -> Image.Image:
        if image.mode != "RGB":
            image = image.convert("RGB")
        if settings.camera_rotation:
            image = image.rotate(settings.camera_rotation, expand=True)
        if settings.camera_hflip:
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
        if settings.camera_vflip:
            image = image.transpose(Image.FLIP_TOP_BOTTOM)
        return image

    def _decorate(self, image: Image.Image) -> Image.Image:
        if settings.camera_text_overlay:
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default()
            state = runtime_state.snapshot()
            text = (
                f"{settings.device_name} | {state.get('status')} | "
                f"snow={state.get('snow_detected')} stable={state.get('stable_snow_detected')} | "
                f"heater={state.get('heater_on')} | temp={state.get('temperature')}C | "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
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
            f"snow: {state.get('snow_detected')} stable={state.get('stable_snow_detected')} score={state.get('snow_score')}",
            f"heater: {state.get('heater_on')} / mode={state.get('heater_mode')}",
            f"temp: {state.get('temperature')}C  humidity: {state.get('humidity')}%",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ]
        y = 40
        draw.rectangle((20, 20, settings.camera_width - 20, settings.camera_height - 20), outline=(90, 120, 200), width=2)
        for line in lines:
            draw.text((40, y), line, fill=(255, 255, 255), font=font)
            y += 28
        return self._encode_image(image)

    def _encode_image(self, image: Image.Image) -> bytes:
        if image.mode != "RGB":
            image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=settings.camera_jpeg_quality)
        return buffer.getvalue()


camera_service = CameraService()
