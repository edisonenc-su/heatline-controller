import json
import time
from datetime import datetime, timezone
from pathlib import Path

from config import (
    STATUS_FILE,
    EVENTS_FILE,
    SNAPSHOT_DIR,
    STREAM_INPUT_URL,
    AI_MODEL_NAME,
    AI_SAMPLE_FPS,
    AI_POSITIVE_THRESHOLD,
    AI_NEGATIVE_THRESHOLD,
    AI_REQUIRED_POSITIVE_STREAK,
    AI_REQUIRED_NEGATIVE_STREAK,
    CAMERA_URL,
    DEVICE_API_BASE_URL,
    PUBLIC_BASE_URL,
    STREAM_TYPE,
)
from state_writer import read_json, write_json, patch_status, now_iso
from frame_source import FrameSource
from model_loader import load_model
from hailo_runner import HailoRunner
from decision_smoother import DecisionSmoother
from rules import should_emit_transition, build_transition_event


DEFAULT_STATUS = {
    'status': 'starting',
    'snow_detected': False,
    'snow_confidence': None,
    'snow_state': 'unknown',
    'heater_on': False,
    'heater_mode': 'auto',
    'temperature': None,
    'humidity': None,
    'snow_threshold': 0.8,
    'ai_enabled': True,
    'ai_status': 'warming_up',
    'ai_last_inference_at': None,
    'inference_model': AI_MODEL_NAME,
    'inference_fps': 0,
    'inference_latency_ms': None,
    'last_seen_at': now_iso(),
    'stream': {
        'camera_url': CAMERA_URL,
        'playback_url': CAMERA_URL,
        'device_api_base': DEVICE_API_BASE_URL,
        'public_base_url': PUBLIC_BASE_URL,
        'stream_type': STREAM_TYPE,
        'stream_health': 'starting',
        'stream_input_url': STREAM_INPUT_URL,
        'media_status': 'starting',
        'media_last_seen_at': None,
    },
}


def append_event(event):
    items = read_json(EVENTS_FILE, [])
    payload = {
        'id': f"evt_{int(time.time() * 1000)}",
        **event,
        'created_at': now_iso(),
    }
    items.insert(0, payload)
    write_json(EVENTS_FILE, items[:200])


def main():
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(STATUS_FILE, {**DEFAULT_STATUS, 'updated_at': now_iso()})
    write_json(EVENTS_FILE, read_json(EVENTS_FILE, []))

    loaded_model = load_model(AI_MODEL_NAME)
    runner = HailoRunner(loaded_model)
    smoother = DecisionSmoother(
        AI_POSITIVE_THRESHOLD,
        AI_NEGATIVE_THRESHOLD,
        AI_REQUIRED_POSITIVE_STREAK,
        AI_REQUIRED_NEGATIVE_STREAK,
    )

    previous_state = 'unknown'
    frames = 0
    started_window = time.time()

    while True:
        source = FrameSource(STREAM_INPUT_URL, AI_SAMPLE_FPS)
        opened = source.open()
        if not opened:
            patch_status(STATUS_FILE, {
                'status': 'offline',
                'ai_status': 'error',
                'last_seen_at': now_iso(),
                'stream': {
                    **DEFAULT_STATUS['stream'],
                    'stream_health': 'offline',
                    'media_status': 'offline',
                }
            })
            time.sleep(5)
            continue

        patch_status(STATUS_FILE, {
            'status': 'online',
            'ai_status': 'running',
            'stream': {
                **DEFAULT_STATUS['stream'],
                'stream_health': 'connected',
                'media_status': 'ready',
                'media_last_seen_at': now_iso(),
            }
        })

        try:
            while True:
                ok, frame = source.read()
                if not ok:
                    patch_status(STATUS_FILE, {
                        'status': 'warning',
                        'ai_status': 'degraded',
                        'stream': {
                            **DEFAULT_STATUS['stream'],
                            'stream_health': 'reconnecting',
                            'media_status': 'reconnecting',
                        }
                    })
                    break

                result = runner.infer(frame)
                decision = smoother.update(float(result['snow_probability']))
                frames += 1
                elapsed = max(time.time() - started_window, 0.001)
                fps = round(frames / elapsed, 2)

                patch_status(STATUS_FILE, {
                    'status': 'online',
                    'snow_detected': decision['snow_detected'],
                    'snow_confidence': decision['snow_confidence'],
                    'snow_state': decision['snow_state'],
                    'ai_status': 'running',
                    'ai_last_inference_at': now_iso(),
                    'inference_model': loaded_model.name,
                    'inference_fps': fps,
                    'inference_latency_ms': result['latency_ms'],
                    'last_seen_at': now_iso(),
                    'stream': {
                        **DEFAULT_STATUS['stream'],
                        'stream_health': 'connected',
                        'media_status': 'ready',
                        'media_last_seen_at': now_iso(),
                    }
                })

                if should_emit_transition(previous_state, decision['snow_state']):
                    append_event(build_transition_event(decision['snow_state']))
                previous_state = decision['snow_state']
        except Exception as exc:
            patch_status(STATUS_FILE, {
                'status': 'warning',
                'ai_status': 'error',
                'last_seen_at': now_iso(),
                'stream': {
                    **DEFAULT_STATUS['stream'],
                    'stream_health': 'reconnecting',
                    'media_status': 'warning',
                }
            })
            append_event({
                'event_type': 'inference_error',
                'severity': 'warning',
                'message': f'추론 루프 오류: {exc}'
            })
            time.sleep(3)
        finally:
            source.close()


if __name__ == '__main__':
    main()
