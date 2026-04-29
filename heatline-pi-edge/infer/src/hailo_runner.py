import time
import numpy as np


class HailoRunner:
    def __init__(self, loaded_model):
        self.loaded_model = loaded_model

    def infer(self, frame):
        """
        TODO: 여기서 실제 Hailo HEF 추론으로 교체.
        현재는 프레임 밝기/대비를 기반으로 한 자리표시자 score 를 반환한다.
        """
        started = time.perf_counter()
        if frame is None:
            raise ValueError('frame is None')

        gray_mean = float(np.mean(frame)) / 255.0
        score = max(0.0, min(1.0, 1.0 - gray_mean))
        latency_ms = (time.perf_counter() - started) * 1000.0
        return {
            'snow_probability': round(score, 4),
            'latency_ms': round(latency_ms, 2),
            'raw': {
                'placeholder_metric': round(gray_mean, 4)
            }
        }
