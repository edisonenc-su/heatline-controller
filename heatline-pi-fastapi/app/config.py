import os
from dataclasses import dataclass
from pathlib import Path


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    pi_api_host: str = os.getenv("PI_API_HOST", "0.0.0.0")
    pi_api_port: int = int(os.getenv("PI_API_PORT", "9000"))
    pi_api_reload: bool = _to_bool(os.getenv("PI_API_RELOAD"), False)

    device_id: int = int(os.getenv("DEVICE_ID", "101"))
    device_serial: str = os.getenv("DEVICE_SERIAL", "KW-PI5-101")
    device_name: str = os.getenv("DEVICE_NAME", "영동고속도로 1호 구간")
    customer_id: str = os.getenv("CUSTOMER_ID", "1")
    install_address: str = os.getenv("INSTALL_ADDRESS", "강원도 영동군 영동로 101")
    install_location: str = os.getenv("INSTALL_LOCATION", "터널 입구")
    latitude: float = float(os.getenv("LATITUDE", "37.123456"))
    longitude: float = float(os.getenv("LONGITUDE", "128.123456"))
    allow_customer_control: bool = _to_bool(os.getenv("ALLOW_CUSTOMER_CONTROL"), True)

    internal_token: str = os.getenv("INTERNAL_TOKEN", "change-this-internal-token")
    device_shared_token: str = os.getenv("DEVICE_SHARED_TOKEN", "change-this-device-token")
    request_timeout_ms: int = int(os.getenv("REQUEST_TIMEOUT_MS", "5000"))

    stream_host: str = os.getenv("STREAM_HOST", "0.0.0.0")
    stream_port: int = int(os.getenv("STREAM_PORT", "8000"))
    stream_path: str = os.getenv("STREAM_PATH", "/stream.mjpg")
    camera_source: str = os.getenv("CAMERA_SOURCE", "auto")
    camera_device_index: int = int(os.getenv("CAMERA_DEVICE_INDEX", "0"))
    camera_width: int = int(os.getenv("CAMERA_WIDTH", "640"))
    camera_height: int = int(os.getenv("CAMERA_HEIGHT", "480"))
    camera_fps: int = int(os.getenv("CAMERA_FPS", "15"))
    camera_rotation: int = int(os.getenv("CAMERA_ROTATION", "0"))
    camera_hflip: bool = _to_bool(os.getenv("CAMERA_HFLIP"), False)
    camera_vflip: bool = _to_bool(os.getenv("CAMERA_VFLIP"), False)
    camera_use_picamera2: bool = _to_bool(os.getenv("CAMERA_USE_PICAMERA2"), True)
    camera_jpeg_quality: int = int(os.getenv("CAMERA_JPEG_QUALITY", "85"))
    camera_text_overlay: bool = _to_bool(os.getenv("CAMERA_TEXT_OVERLAY"), True)
    placeholder_stream: bool = _to_bool(os.getenv("PLACEHOLDER_STREAM"), True)

    sensor_simulation: bool = _to_bool(os.getenv("SENSOR_SIMULATION"), True)
    temperature_default: float = float(os.getenv("TEMPERATURE_DEFAULT", "-2.5"))
    humidity_default: float = float(os.getenv("HUMIDITY_DEFAULT", "68.0"))
    snow_threshold: float = float(os.getenv("SNOW_THRESHOLD", "0.80"))
    heater_mode: str = os.getenv("HEATER_MODE", "auto")

    central_api_base: str = os.getenv("CENTRAL_API_BASE", "").rstrip("/")
    central_device_token: str = os.getenv("CENTRAL_DEVICE_TOKEN", "")
    device_sync_token: str = os.getenv("DEVICE_SYNC_TOKEN", "")
    pairing_enabled: bool = _to_bool(os.getenv("PAIRING_ENABLED"), True)
    provision_key: str = os.getenv("PROVISION_KEY", "")
    central_controller_id: int = int(os.getenv("CENTRAL_CONTROLLER_ID", "0"))
    firmware_version: str = os.getenv("FIRMWARE_VERSION", "")
    hardware_model: str = os.getenv("HARDWARE_MODEL", "")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    pi_public_host: str = os.getenv("PI_PUBLIC_HOST", "").strip()
    sync_interval_sec: int = int(os.getenv("SYNC_INTERVAL_SEC", "15"))

    schedule_poll_interval_sec: int = int(os.getenv("SCHEDULE_POLL_INTERVAL_SEC", "15"))
    offline_fallback_enabled: bool = _to_bool(os.getenv("OFFLINE_FALLBACK_ENABLED"), True)
    offline_grace_sec: int = int(os.getenv("OFFLINE_GRACE_SEC", "90"))

    data_dir: Path = Path(os.getenv("DATA_DIR", "./data"))
    sqlite_path: Path = Path(os.getenv("SQLITE_PATH", "./data/pi_device.db"))

    @property
    def public_host(self) -> str:
        return self.pi_public_host or "127.0.0.1"

    @property
    def stream_url(self) -> str:
        path = self.stream_path if self.stream_path.startswith("/") else f"/{self.stream_path}"
        return f"http://{self.public_host}:{self.pi_api_port}{path}"

    @property
    def device_api_base(self) -> str:
        return f"http://{self.public_host}:{self.pi_api_port}/api/v1"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
