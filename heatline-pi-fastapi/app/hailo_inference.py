from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from .config import settings

try:  # pragma: no cover
    import hailo_platform  # type: ignore  # noqa: F401
except Exception:  # pragma: no cover
    hailo_platform = None  # type: ignore


@dataclass
class InferenceResult:
    ok: bool
    label: str
    confidence: float
    raw_scores: dict[str, float]
    latency_ms: float
    error: str | None = None


class HailoInferenceEngine:
    """
    1차 PR 목표:
    - Hailo 초기화/가용성 판단
    - 추론 인터페이스 고정
    - Hailo 미사용/미가용 시 graceful degradation

    실제 HEF 실행 바인딩은 현장 Hailo Python 런타임에 맞춰 _infer_with_hailo()에 연결하면 됩니다.
    """

    def __init__(self) -> None:
        self._initialized = False
        self._available = False
        self._labels = settings.hailo_label_list
        self._model_name = settings.hailo_model_name
        self._model_path = settings.hailo_model_path
        self._runtime: Any = None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def model_name(self) -> str:
        return self._model_name

    def initialize(self) -> None:
        if self._initialized:
            return

        self._initialized = True

        if not settings.hailo_enabled:
            self._available = False
            return

        if not self._model_path:
            self._available = False
            return

        if hailo_platform is None:
            self._available = False
            return

        self._runtime = object()
        self._available = True

    def _preprocess(self, frame_rgb: np.ndarray) -> np.ndarray:
        image = Image.fromarray(frame_rgb)
        image = image.resize((settings.hailo_input_width, settings.hailo_input_height))
        arr = np.asarray(image).astype("float32") / 255.0
        return arr

    def _infer_with_hailo(self, input_tensor: np.ndarray) -> dict[str, float]:
        """
        TODO:
        실제 Hailo Python runtime 추론 연결부.
        반환 형식 예:
            {"clear": 0.82, "snowing": 0.18}
        """
        raise RuntimeError("Hailo runtime binding not implemented yet")

    def infer_rgb(self, frame_rgb: np.ndarray) -> InferenceResult:
        started = time.perf_counter()

        if not self._initialized:
            self.initialize()

        if frame_rgb is None:
            return InferenceResult(
                ok=False,
                label="unknown",
                confidence=0.0,
                raw_scores={},
                latency_ms=0.0,
                error="frame is None",
            )

        if not self._available:
            return InferenceResult(
                ok=False,
                label="unavailable",
                confidence=0.0,
                raw_scores={},
                latency_ms=(time.perf_counter() - started) * 1000,
                error="hailo unavailable",
            )

        try:
            input_tensor = self._preprocess(frame_rgb)
            raw_scores = self._infer_with_hailo(input_tensor)

            if not raw_scores:
                raise RuntimeError("empty inference result")

            label = max(raw_scores, key=raw_scores.get)
            confidence = float(raw_scores[label])

            return InferenceResult(
                ok=True,
                label=label,
                confidence=confidence,
                raw_scores={k: float(v) for k, v in raw_scores.items()},
                latency_ms=(time.perf_counter() - started) * 1000,
                error=None,
            )
        except Exception as exc:
            return InferenceResult(
                ok=False,
                label="error",
                confidence=0.0,
                raw_scores={},
                latency_ms=(time.perf_counter() - started) * 1000,
                error=str(exc),
            )


hailo_inference_engine = HailoInferenceEngine()
