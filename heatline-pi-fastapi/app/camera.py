from __future__ import annotations

import io
import os
import threading
import time
from datetime import datetime
from typing import Optional, Tuple

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
        self._frame_jpeg: bytes = b""
        self._frame_rgb: Optional[np.ndarray] = None

        self._picamera2 = None
        self._opencv_cap = None

        self._rtsp_reader_stop = threading.Event()
        self._rtsp_reader_thread: Optional[threading.Thread] = None
        self._rtsp_frame_lock = threading.Lock()
        self._rtsp_latest_bgr: Optional[np.ndarray] = None
        self._rtsp_frame_seq = 0
        self._rtsp_last_frame_ts = 0.0
        self._rtsp_last_consumed_seq = -1

        self._consecutive_failures = 0
        self._last_connect_error: Optional[str] = None

        self._frame_jpeg = self._placeholder_frame("booting")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="camera-capture",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._release_sources()

    def get_frame(self) -> bytes:
        with self._lock:
            return self._frame_jpeg

    def get_latest_frame_rgb(self) -> Optional[np.ndarray]:
        with self._lock:
            if self._frame_rgb is None:
                return None
            return np.array(self._frame_rgb, copy=True)

    def get_source_name(self) -> str:
        return self._source_name

    def mjpeg_generator(self):
        delay = max(0.03, 1.0 / max(1, int(settings.camera_fps)))
        while not self._stop.is_set():
            frame = self.get_frame()
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(delay)

    def _capture_loop(self) -> None:
        while not self._stop.is_set():
            if not self._ensure_camera_ready():
                self._publish_placeholder(self._last_connect_error or "camera unavailable")
                self._stop.wait(max(0.5, float(settings.camera_reconnect_interval_sec)))
                continue

            try:
                image = self._capture_image_from_device()
                if image is None:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= max(3, int(settings.camera_failure_limit)):
                        self._last_connect_error = self._last_connect_error or "capture timeout or stream disconnected"
                        print(f"[camera] reconnecting after failures: {self._last_connect_error}", flush=True)
                        self._release_sources()
                    else:
                        self._publish_placeholder(self._last_connect_error or "camera frame unavailable")
                else:
                    self._consecutive_failures = 0
                    normalized = self._normalize_image(image)
                    rgb = np.asarray(normalized).copy()
                    decorated = self._decorate(normalized.copy())
                    encoded = self._encode_image(decorated)
                    with self._lock:
                        self._frame_jpeg = encoded
                        self._frame_rgb = rgb

                self._stop.wait(max(0.01, 1.0 / max(1, int(settings.camera_fps))))
            except Exception as exc:
                self._last_connect_error = f"{type(exc).__name__}: {exc}"
                print(f"[camera] capture loop error: {self._last_connect_error}", flush=True)
                self._release_sources()
                self._publish_placeholder(f"capture error: {type(exc).__name__}")
                self._stop.wait(max(0.5, float(settings.camera_reconnect_interval_sec)))

    def _ensure_camera_ready(self) -> bool:
        if self._picamera2 is not None:
            return True
        if self._opencv_cap is not None and cv2 is not None and self._opencv_cap.isOpened():
            return True
        return self._init_camera()

    def _init_camera(self) -> bool:
        preferred = str(getattr(settings, "camera_source", "auto")).lower().strip()
        self._last_connect_error = None

        if preferred in {"rtsp", "auto"} and self._camera_capture_url and cv2 is not None:
            if self._init_rtsp_camera():
                return True

        if preferred in {"auto", "picamera2"} and getattr(settings, "camera_use_picamera2", False) and Picamera2:
            try:
                self._picamera2 = Picamera2()
                config = self._picamera2.create_video_configuration(
                    main={
                        "size": (int(settings.camera_width), int(settings.camera_height)),
                        "format": "RGB888",
                    }
                )
                self._picamera2.configure(config)
                self._picamera2.start()
                self._source_name = "picamera2"
                self._last_connect_error = None
                print("[camera] picamera2 initialized", flush=True)
                return True
            except Exception as exc:
                self._last_connect_error = f"picamera2 init failed: {exc}"
                self._picamera2 = None
                print(f"[camera] {self._last_connect_error}", flush=True)

        if preferred in {"auto", "opencv"} and cv2 is not None:
            try:
                cap = cv2.VideoCapture(int(getattr(settings, "camera_device_index", 0)))
                self._apply_common_opencv_options(cap)
                if cap.isOpened():
                    self._opencv_cap = cap
                    self._source_name = "opencv"
                    self._last_connect_error = None
                    print("[camera] opencv camera initialized", flush=True)
                    return True
                cap.release()
                self._last_connect_error = "opencv camera open failed"
            except Exception as exc:
                self._last_connect_error = f"opencv init failed: {exc}"
                print(f"[camera] {self._last_connect_error}", flush=True)

        self._source_name = "placeholder"
        return False

    @property
    def _camera_capture_url(self) -> str:
        url = getattr(settings, "camera_capture_url", "") or getattr(settings, "camera_rtsp_url", "")
        return str(url or "").strip()

    def _build_ffmpeg_options(self) -> str:
        transport = str(getattr(settings, "camera_rtsp_transport", "tcp")).strip() or "tcp"
        timeout_us = max(1, int(float(getattr(settings, "camera_connect_timeout_sec", 5)) * 1_000_000))
        return (
            f"rtsp_transport;{transport}"
            f"|fflags;nobuffer"
            f"|flags;low_delay"
            f"|max_delay;0"
            f"|reorder_queue_size;0"
            f"|probesize;32768"
            f"|analyzeduration;0"
            f"|buffer_size;32768"
            f"|stimeout;{timeout_us}"
        )

    def _apply_common_opencv_options(self, cap) -> None:
        if cv2 is None or cap is None:
            return
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        try:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(settings.camera_width))
        except Exception:
            pass
        try:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(settings.camera_height))
        except Exception:
            pass
        try:
            cap.set(cv2.CAP_PROP_FPS, float(settings.camera_fps))
        except Exception:
            pass
        try:
            if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(float(settings.camera_connect_timeout_sec) * 1000))
        except Exception:
            pass
        try:
            if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(float(settings.camera_connect_timeout_sec) * 1000))
        except Exception:
            pass

    def _init_rtsp_camera(self) -> bool:
        if cv2 is None:
            self._last_connect_error = "opencv is not installed"
            return False

        self._release_opencv_cap()
        self._stop_rtsp_reader()

        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = self._build_ffmpeg_options()
        url = self._camera_capture_url

        cap = self._open_opencv_capture(url)
        if cap is None:
            self._last_connect_error = "RTSP open failed"
            print(f"[camera] {self._last_connect_error}: {url}", flush=True)
            return False

        ok, frame = self._prime_capture(cap)
        if not ok or frame is None:
            try:
                cap.release()
            except Exception:
                pass
            self._last_connect_error = "RTSP handshake failed"
            print(f"[camera] {self._last_connect_error}: {url}", flush=True)
            return False

        self._opencv_cap = cap
        self._source_name = "rtsp"
        self._last_connect_error = None
        self._consecutive_failures = 0

        with self._rtsp_frame_lock:
            self._rtsp_latest_bgr = frame
            self._rtsp_frame_seq = 1
            self._rtsp_last_frame_ts = time.monotonic()
            self._rtsp_last_consumed_seq = -1

        self._start_rtsp_reader()
        print(f"[camera] RTSP initialized: {url}", flush=True)
        return True

    def _open_opencv_capture(self, url: str):
        if cv2 is None:
            return None

        cap = None
        try:
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            self._apply_common_opencv_options(cap)
            if cap.isOpened():
                return cap
            cap.release()
        except Exception:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

        try:
            cap = cv2.VideoCapture(url)
            self._apply_common_opencv_options(cap)
            if cap.isOpened():
                return cap
            cap.release()
        except Exception:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
        return None

    def _prime_capture(self, cap) -> Tuple[bool, Optional[np.ndarray]]:
        if cv2 is None:
            return False, None

        deadline = time.monotonic() + max(2.0, float(getattr(settings, "camera_connect_timeout_sec", 5)))
        last_frame = None

        while time.monotonic() < deadline:
            ok, frame = cap.read()
            if ok and frame is not None:
                last_frame = frame
                for _ in range(3):
                    if not cap.grab():
                        break
                    ok2, frame2 = cap.retrieve()
                    if ok2 and frame2 is not None:
                        last_frame = frame2
                return True, last_frame
            time.sleep(0.05)

        return False, last_frame

    def _start_rtsp_reader(self) -> None:
        self._stop_rtsp_reader()
        if self._opencv_cap is None:
            return
        self._rtsp_reader_stop.clear()
        self._rtsp_reader_thread = threading.Thread(
            target=self._rtsp_reader_loop,
            daemon=True,
            name="rtsp-reader",
        )
        self._rtsp_reader_thread.start()

    def _stop_rtsp_reader(self) -> None:
        self._rtsp_reader_stop.set()
        if self._rtsp_reader_thread and self._rtsp_reader_thread.is_alive():
            self._rtsp_reader_thread.join(timeout=1.5)
        self._rtsp_reader_thread = None
        with self._rtsp_frame_lock:
            self._rtsp_latest_bgr = None
            self._rtsp_frame_seq = 0
            self._rtsp_last_frame_ts = 0.0
            self._rtsp_last_consumed_seq = -1

    def _rtsp_reader_loop(self) -> None:
        cap = self._opencv_cap
        if cap is None or cv2 is None:
            return

        idle_sleep = 0.001
        fail_count = 0
        max_failures = max(20, int(getattr(settings, "camera_failure_limit", 8)))

        while not self._stop.is_set() and not self._rtsp_reader_stop.is_set():
            try:
                ok = cap.grab()
                if not ok:
                    fail_count += 1
                    if fail_count >= max_failures:
                        self._last_connect_error = "RTSP reader grab failed"
                        print(f"[camera] {self._last_connect_error}", flush=True)
                        break
                    time.sleep(0.02)
                    continue

                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    fail_count += 1
                    if fail_count >= max_failures:
                        self._last_connect_error = "RTSP reader retrieve failed"
                        print(f"[camera] {self._last_connect_error}", flush=True)
                        break
                    time.sleep(0.01)
                    continue

                fail_count = 0
                now = time.monotonic()
                with self._rtsp_frame_lock:
                    self._rtsp_latest_bgr = frame
                    self._rtsp_frame_seq += 1
                    self._rtsp_last_frame_ts = now

                time.sleep(idle_sleep)
            except Exception as exc:
                self._last_connect_error = f"RTSP reader error: {type(exc).__name__}: {exc}"
                print(f"[camera] {self._last_connect_error}", flush=True)
                break

    def _capture_image_from_device(self) -> Optional[Image.Image]:
        if self._source_name == "rtsp":
            return self._capture_rtsp_image()

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
                self._last_connect_error = "opencv frame read failed"
                return None
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return Image.fromarray(frame)

        self._last_connect_error = "camera backend unavailable"
        return None

    def _capture_rtsp_image(self) -> Optional[Image.Image]:
        if cv2 is None:
            self._last_connect_error = "opencv unavailable for RTSP"
            return None

        with self._rtsp_frame_lock:
            frame = None if self._rtsp_latest_bgr is None else self._rtsp_latest_bgr.copy()
            seq = self._rtsp_frame_seq
            last_ts = self._rtsp_last_frame_ts

        if frame is None:
            self._last_connect_error = "RTSP frame cache empty"
            return None

        age = time.monotonic() - last_ts
        stale_limit = max(0.8, (2.5 / max(1.0, float(settings.camera_fps))))
        if age > stale_limit:
            self._last_connect_error = f"RTSP frame stale ({age:.2f}s)"
            return None

        if seq == self._rtsp_last_consumed_seq:
            self._last_connect_error = "RTSP no fresh frame yet"
            return None

        self._rtsp_last_consumed_seq = seq
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame)

    def _normalize_image(self, image: Image.Image) -> Image.Image:
        if image.mode != "RGB":
            image = image.convert("RGB")

        rotation = int(getattr(settings, "camera_rotation", 0) or 0)
        if rotation:
            image = image.rotate(rotation, expand=True)

        if bool(getattr(settings, "camera_hflip", False)):
            image = image.transpose(Image.FLIP_LEFT_RIGHT)

        if bool(getattr(settings, "camera_vflip", False)):
            image = image.transpose(Image.FLIP_TOP_BOTTOM)

        target_w = int(getattr(settings, "camera_width", image.width))
        target_h = int(getattr(settings, "camera_height", image.height))
        if image.width != target_w or image.height != target_h:
            image = image.resize((target_w, target_h), Image.BILINEAR)

        return image

    def _decorate(self, image: Image.Image) -> Image.Image:
        if not bool(getattr(settings, "camera_text_overlay", True)):
            return image

        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        state = runtime_state.snapshot()

        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = (
            f"{getattr(settings, 'device_name', 'heatline-device')} | "
            f"src={self._source_name} | "
            f"snow={state.get('snow_detected')} "
            f"stable={state.get('stable_snow_detected')} | "
            f"heater={state.get('heater_on')} | "
            f"temp={state.get('temperature')}C | "
            f"{now_text}"
        )

        bar_h = 24
        draw.rectangle((0, 0, image.width, bar_h), fill=(0, 0, 0))
        draw.text((8, 6), text, fill=(255, 255, 255), font=font)
        return image

    def _publish_placeholder(self, reason: str) -> None:
        if not bool(getattr(settings, "placeholder_stream", True)):
            return
        with self._lock:
            self._frame_jpeg = self._placeholder_frame(reason)
            self._frame_rgb = None

    def _placeholder_frame(self, reason: str) -> bytes:
        width = int(getattr(settings, "camera_width", 640))
        height = int(getattr(settings, "camera_height", 360))

        image = Image.new("RGB", (width, height), (17, 24, 39))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        state = runtime_state.snapshot()

        lines = [
            str(getattr(settings, "device_name", "heatline-device")),
            f"serial: {getattr(settings, 'device_serial', '-')}",
            f"camera source: {self._source_name}",
            f"rtsp url: {getattr(settings, 'camera_rtsp_url', '') or '-'}",
            f"reason: {reason}",
            f"status: {state.get('status')}",
            f"snow: {state.get('snow_detected')} stable={state.get('stable_snow_detected')} score={state.get('snow_score')}",
            f"heater: {state.get('heater_on')} / mode={state.get('heater_mode')}",
            f"temp: {state.get('temperature')}C  humidity: {state.get('humidity')}%",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ]

        draw.rectangle((20, 20, width - 20, height - 20), outline=(90, 120, 200), width=2)

        y = 36
        for line in lines:
            draw.text((36, y), line, fill=(255, 255, 255), font=font)
            y += 24

        return self._encode_image(image)

    def _encode_image(self, image: Image.Image) -> bytes:
        if image.mode != "RGB":
            image = image.convert("RGB")
        buf = io.BytesIO()
        image.save(
            buf,
            format="JPEG",
            quality=int(getattr(settings, "camera_jpeg_quality", 55)),
            optimize=False,
        )
        return buf.getvalue()

    def _release_opencv_cap(self) -> None:
        self._stop_rtsp_reader()
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
