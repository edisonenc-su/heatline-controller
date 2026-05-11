from __future__ import annotations

import io
import os
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
        self._consecutive_failures = 0
        self._last_connect_error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="camera-capture")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._release_sources()

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
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(delay)

    def _capture_loop(self) -> None:
        while not self._stop.is_set():
            if not self._ensure_camera_ready():
                self._publish_placeholder(self._last_connect_error or "camera unavailable")
                self._stop.wait(max(0.5, settings.camera_reconnect_interval_sec))
                continue

            try:
                image = self._capture_image_from_device()
                if image is None:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= max(3, settings.camera_failure_limit):
                        self._last_connect_error = "capture timeout or stream disconnected"
                        self._release_sources()
                    self._publish_placeholder("camera frame unavailable")
                else:
                    self._consecutive_failures = 0
                    normalized = self._normalize_image(image)
                    rgb = np.asarray(normalized).copy()
                    decorated = self._decorate(normalized.copy())
                    encoded = self._encode_image(decorated)
                    with self._lock:
                        self._frame_jpeg = encoded
                        self._frame_rgb = rgb
                self._stop.wait(max(0.01, 1.0 / max(1, settings.camera_fps)))
            except Exception as exc:
                self._last_connect_error = f"{type(exc).__name__}: {exc}"
                print(f"[camera] capture loop error: {self._last_connect_error}", flush=True)
                self._release_sources()
                self._publish_placeholder(f"capture error: {type(exc).__name__}")
                self._stop.wait(max(0.5, settings.camera_reconnect_interval_sec))

    def _ensure_camera_ready(self) -> bool:
        if self._picamera2 is not None:
            return True
        if self._opencv_cap is not None and cv2 is not None and self._opencv_cap.isOpened():
            return True
        return self._init_camera()

    def _init_camera(self) -> bool:
        preferred = settings.camera_source.lower().strip()

        if preferred in {"rtsp", "auto"} and settings.camera_capture_url and cv2 is not None:
            if self._init_rtsp_camera():
                return True

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
                self._last_connect_error = None
                return True
            except Exception as exc:
                self._last_connect_error = f"picamera2 init failed: {exc}"
                self._picamera2 = None

        if preferred in {"auto", "opencv"} and cv2 is not None:
            try:
                self._opencv_cap = cv2.VideoCapture(settings.camera_device_index)
                self._opencv_cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.camera_width)
                self._opencv_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.camera_height)
                self._opencv_cap.set(cv2.CAP_PROP_FPS, settings.camera_fps)
                if self._opencv_cap.isOpened():
                    self._source_name = "opencv"
                    self._last_connect_error = None
                    return True
                self._release_opencv_cap()
                self._last_connect_error = "opencv camera open failed"
            except Exception as exc:
                self._release_opencv_cap()
                self._last_connect_error = f"opencv init failed: {exc}"

        self._source_name = "placeholder"
        return False

    def _init_rtsp_camera(self) -> bool:
        if cv2 is None:
            self._last_connect_error = "opencv is not installed"
            return False

        self._release_opencv_cap()
        timeout_us = max(1, int(settings.camera_connect_timeout_sec * 1_000_000))
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            f"rtsp_transport;{settings.camera_rtsp_transport}|stimeout;{timeout_us}|buffer_size;1024000"
        )

        try:
            cap = cv2.VideoCapture(settings.camera_capture_url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.camera_width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.camera_height)
            cap.set(cv2.CAP_PROP_FPS, settings.camera_fps)

            if not cap.isOpened():
                cap.release()
                self._last_connect_error = "RTSP open failed"
                return False

            ok, frame = cap.read()
            if not ok or frame is None:
                cap.release()
                self._last_connect_error = "RTSP handshake failed"
                return False

            self._opencv_cap = cap
            self._source_name = "rtsp"
            self._last_connect_error = None
            self._consecutive_failures = 0
            return True
        except Exception as exc:
            self._last_connect_error = f"RTSP init failed: {exc}"
            self._release_opencv_cap()
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
            if not ok or frame is None:
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
        if image.width != settings.camera_width or image.height != settings.camera_height:
            image = image.resize((settings.camera_width, settings.camera_height))
        return image

    def _decorate(self, image: Image.Image) -> Image.Image:
        if settings.camera_text_overlay:
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default()
            state = runtime_state.snapshot()
            text = (
                f"{settings.device_name} | src={self._source_name} | "
                f"snow={state.get('snow_detected')} stable={state.get('stable_snow_detected')} | "
                f"heater={state.get('heater_on')} | temp={state.get('temperature')}C | "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            draw.rectangle((0, 0, image.width, 24), fill=(0, 0, 0))
            draw.text((8, 6), text, fill=(255, 255, 255), font=font)
        return image

    def _publish_placeholder(self, reason: str) -> None:
        if not settings.placeholder_stream:
            return
        with self._lock:
            self._frame_jpeg = self._placeholder_frame(reason)
            self._frame_rgb = None

    def _placeholder_frame(self, reason: str) -> bytes:
        image = Image.new("RGB", (settings.camera_width, settings.camera_height), (17, 24, 39))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        state = runtime_state.snapshot()
        lines = [
            settings.device_name,
            f"serial: {settings.device_serial}",
            f"camera source: {self._source_name}",
            f"rtsp url: {settings.camera_rtsp_url or '-'}",
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

    def _release_opencv_cap(self) -> None:
        if self._opencv_cap is not None:
            try:
                self._opencv_cap.release()
            except Exception:
                pass
            self._opencv_cap = None

    def _release_sources(self) -> None:
        self._release_opencv_cap()
        if self._picamera2 is not None:
            try:
                self._picamera2.stop()
            except Exception:
                pass
            self._picamera2 = None
        self._source_name = "placeholder"


camera_service = CameraService()
