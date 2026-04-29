import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATUS_FILE = Path(os.getenv('STATUS_FILE', ROOT / 'shared/state/device-status.json'))
EVENTS_FILE = Path(os.getenv('EVENTS_FILE', ROOT / 'shared/state/events.json'))
SNAPSHOT_DIR = Path(ROOT / 'shared/snapshots')
SOURCE_RTSP_URL = os.getenv('SOURCE_RTSP_URL', 'rtsp://camera-ip/live/0/MAIN')
STREAM_INPUT_URL = os.getenv('STREAM_INPUT_URL', SOURCE_RTSP_URL)
AI_MODEL_NAME = os.getenv('AI_MODEL_NAME', 'snow-binary-v1.hef')
AI_SAMPLE_FPS = float(os.getenv('AI_SAMPLE_FPS', '2'))
AI_POSITIVE_THRESHOLD = float(os.getenv('AI_POSITIVE_THRESHOLD', '0.75'))
AI_NEGATIVE_THRESHOLD = float(os.getenv('AI_NEGATIVE_THRESHOLD', '0.35'))
AI_REQUIRED_POSITIVE_STREAK = int(os.getenv('AI_REQUIRED_POSITIVE_STREAK', '5'))
AI_REQUIRED_NEGATIVE_STREAK = int(os.getenv('AI_REQUIRED_NEGATIVE_STREAK', '5'))
CAMERA_URL = os.getenv('CAMERA_URL', 'https://pi-tunnel.example.com/live/main/index.m3u8')
DEVICE_API_BASE_URL = os.getenv('DEVICE_API_BASE_URL', 'https://pi-tunnel.example.com/api/v1')
PUBLIC_BASE_URL = os.getenv('PI_PUBLIC_BASE_URL', 'https://pi-tunnel.example.com')
STREAM_TYPE = os.getenv('STREAM_TYPE', 'hls')
