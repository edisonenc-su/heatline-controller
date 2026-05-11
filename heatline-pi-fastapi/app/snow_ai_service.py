from __future__ import annotations

import threading
from collections import deque
from typing import Deque

import numpy as np

from .camera import camera_service
from .config import settings
from .db import insert_event, utc_now
from .hailo_inference import InferenceResult, hailo_inference_engine
from .state import runtime_state


class SnowAIService:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._window: Deque[bool] = deque(maxlen=max(1, settings.ai_window_size))
        self._stable_snow = False
        self._last_reason = "booting"
        self._last_error_logged: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="snow-ai-loop")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def status(self) -> dict:
        snapshot = runtime_state.snapshot()
        return {
            "ai_enabled": snapshot.get("ai_enabled"),
            "ai_available": snapshot.get("ai_available"),
            "ai_model_name": snapshot.get("ai_model_name"),
            "ai_last_inference_at": snapshot.get("ai_last_inference_at"),
            "snow_score": snapshot.get("snow_score"),
            "stable_snow_detected": snapshot.get("stable_snow_detected"),
            "control_policy_state": snapshot.get("control_policy_state"),
        }

    def _crop_roi(self, frame_rgb: np.ndarray) -> np.ndarray:
        height, width = frame_rgb.shape[:2]
        top = int(max(0.0, min(1.0, settings.ai_roi_top_ratio)) * height)
        bottom = int(max(0.0, min(1.0, settings.ai_roi_bottom_ratio)) * height)
        left = int(max(0.0, min(1.0, settings.ai_roi_left_ratio)) * width)
        right = int(max(0.0, min(1.0, settings.ai_roi_right_ratio)) * width)

        if bottom <= top:
            top, bottom = 0, height
        if right <= left:
            left, right = 0, width

        roi = frame_rgb[top:bottom, left:right]
        return roi if roi.size else frame_rgb

    def _snow_score(self, result: InferenceResult) -> float:
        if result.raw_scores:
            snow_like = [
                float(score)
                for label, score in result.raw_scores.items()
                if "snow" in str(label).strip().lower()
            ]
            if snow_like:
                return max(0.0, min(1.0, max(snow_like)))

        label = str(result.label or "").strip().lower()
        if "snow" in label:
            return max(0.0, min(1.0, float(result.confidence)))
        return max(0.0, min(1.0, 1.0 - float(result.confidence))) if label == "clear" else max(0.0, min(1.0, float(result.confidence)))

    def _update_stable_state(self, instantaneous_positive: bool, snow_score: float) -> bool:
        if snow_score >= settings.ai_snow_on_threshold:
            self._window.append(True)
        elif snow_score <= settings.ai_snow_off_threshold:
            self._window.append(False)
        else:
            self._window.append(self._stable_snow)

        positives = sum(1 for item in self._window if item)
        negatives = len(self._window) - positives
        required = min(max(1, settings.ai_required_positive_count), len(self._window))

        if positives >= required:
            self._stable_snow = True
        elif negatives >= required:
            self._stable_snow = False
        elif instantaneous_positive and len(self._window) < required:
            self._stable_snow = self._stable_snow

        return self._stable_snow

    def _apply_disabled_state(self, reason: str) -> None:
        runtime_state.apply_ai_status(
            ai_available=False,
            ai_enabled=False,
            ai_model_name=settings.hailo_model_name,
            stable_snow_detected=False,
            snow_detected=False,
            snow_confidence=0.0,
            snow_score=0.0,
            snow_state="AI_DISABLED",
            ai_last_inference_at=None,
            ai_decision_reason=reason,
            control_policy_state="disabled",
            message=reason,
        )

    def _apply_camera_waiting(self, reason: str) -> None:
        runtime_state.apply_ai_status(
            ai_available=hailo_inference_engine.available,
            ai_enabled=settings.hailo_enabled,
            ai_model_name=settings.hailo_model_name,
            snow_detected=False,
            stable_snow_detected=self._stable_snow,
            snow_confidence=0.0,
            snow_score=0.0,
            snow_state="WAITING_CAMERA",
            ai_last_inference_at=utc_now(),
            ai_decision_reason=reason,
            control_policy_state="camera_wait",
            message=reason,
        )

    def _loop(self) -> None:
        if not settings.hailo_enabled:
            self._apply_disabled_state("Hailo AI disabled by configuration")
            insert_event(
                event_type="AI_DISABLED",
                message="Hailo AI disabled by configuration",
                severity="info",
                payload={"model": settings.hailo_model_name},
            )
            while not self._stop.wait(max(1.0, settings.ai_loop_interval_sec)):
                pass
            return

        hailo_inference_engine.initialize()
        runtime_state.apply_ai_status(
            ai_available=hailo_inference_engine.available,
            ai_enabled=True,
            ai_model_name=hailo_inference_engine.model_name,
            ai_decision_reason="AI service started",
            control_policy_state="starting",
            message="AI service started",
        )
        insert_event(
            event_type="AI_SERVICE_STARTED",
            message="Snow AI service started",
            severity="info",
            payload={
                "model": hailo_inference_engine.model_name,
                "available": hailo_inference_engine.available,
            },
        )

        while not self._stop.wait(max(0.2, settings.ai_loop_interval_sec)):
            frame_rgb = camera_service.get_latest_frame_rgb()
            if frame_rgb is None:
                self._apply_camera_waiting("AI waiting for live camera frame")
                continue

            roi = self._crop_roi(frame_rgb)
            result = hailo_inference_engine.infer_rgb(roi)
            now = utc_now()

            if not result.ok:
                error_message = result.error or "unknown inference error"
                runtime_state.apply_ai_status(
                    ai_available=hailo_inference_engine.available,
                    ai_enabled=settings.hailo_enabled,
                    ai_model_name=hailo_inference_engine.model_name,
                    snow_detected=False,
                    stable_snow_detected=self._stable_snow,
                    snow_confidence=0.0,
                    snow_score=0.0,
                    snow_state="AI_ERROR",
                    ai_last_inference_at=now,
                    ai_decision_reason=error_message,
                    control_policy_state="error",
                    message=f"AI inference failed: {error_message}",
                )
                if error_message != self._last_error_logged:
                    insert_event(
                        event_type="AI_INFERENCE_ERROR",
                        message=error_message,
                        severity="warning",
                        payload={"model": hailo_inference_engine.model_name},
                    )
                    self._last_error_logged = error_message
                continue

            self._last_error_logged = None
            snow_score = self._snow_score(result)
            instantaneous_positive = snow_score >= settings.ai_snow_on_threshold
            stable = self._update_stable_state(instantaneous_positive, snow_score)
            positives = sum(1 for item in self._window if item)

            if stable:
                snow_state = "SNOW_CONFIRMED"
                policy_state = "snow_stable"
            elif instantaneous_positive:
                snow_state = "SNOW_CANDIDATE"
                policy_state = "confirming"
            elif snow_score <= settings.ai_snow_off_threshold:
                snow_state = "CLEAR"
                policy_state = "monitoring"
            else:
                snow_state = "UNCERTAIN"
                policy_state = "monitoring"

            reason = (
                f"label={result.label}, confidence={result.confidence:.3f}, snow_score={snow_score:.3f}, "
                f"stable={stable}, positive_window={positives}/{len(self._window)}, latency_ms={result.latency_ms:.1f}"
            )
            self._last_reason = reason
            runtime_state.apply_ai_status(
                ai_available=True,
                ai_enabled=True,
                ai_model_name=hailo_inference_engine.model_name,
                snow_detected=instantaneous_positive,
                stable_snow_detected=stable,
                snow_confidence=result.confidence,
                snow_score=snow_score,
                snow_state=snow_state,
                ai_last_inference_at=now,
                ai_decision_reason=reason,
                control_policy_state=policy_state,
                message="AI snow status updated",
            )

        insert_event(
            event_type="AI_SERVICE_STOPPED",
            message="Snow AI service stopped",
            severity="info",
            payload={"last_reason": self._last_reason},
        )


snow_ai_service = SnowAIService()
