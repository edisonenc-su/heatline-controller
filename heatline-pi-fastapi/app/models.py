from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class RequestedBy(BaseModel):
    user_id: Optional[str] = None
    user_name: Optional[str] = "unknown"


class StatusPayload(BaseModel):
    status: Literal["online", "offline", "warning", "error"] = "online"
    snow_detected: bool = False
    snow_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    snow_state: str = "CLEAR"
    heater_on: bool = False
    heater_mode: Literal["auto", "manual", "schedule"] = "auto"
    offline_mode: bool = False
    current_control_source: str = "idle"
    active_schedule_name: Optional[str] = None
    last_schedule_sync_at: Optional[str] = None
    snow_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    camera_url: Optional[str] = None
    message: Optional[str] = None


class HeartbeatPayload(BaseModel):
    status: Optional[Literal["online", "offline", "warning", "error"]] = "online"
    message: Optional[str] = None


class EventPayload(BaseModel):
    event_type: str
    message: str
    severity: Literal["info", "warning", "critical"] = "info"
    payload: Optional[dict[str, Any]] = None


class ManualSchedulePayload(BaseModel):
    schedule_key: Optional[str] = None
    id: Optional[str | int] = None
    external_id: Optional[str | int] = None
    name: str
    schedule_type: Literal["weekly", "once"] = "weekly"
    enabled: bool = True
    days_of_week: list[int] = Field(default_factory=list)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    once_started_at: Optional[str] = None
    once_ended_at: Optional[str] = None
    preheat_minutes: int = 0
    priority: int = 50
    offline_enabled: bool = True
    min_temperature: Optional[float] = None
    max_temperature: Optional[float] = None
    source: str = "local"
    note: str = ""


class ManualScheduleSyncPayload(BaseModel):
    schedules: list[ManualSchedulePayload] = Field(default_factory=list)


class RuntimePolicyPayload(BaseModel):
    offline_fallback_enabled: bool = True
    offline_grace_sec: int = 90
    schedule_poll_interval_sec: int = 15


class CommandPayload(BaseModel):
    command_type: Literal[
        "HEATER_ON",
        "HEATER_OFF",
        "SET_MODE",
        "SET_SNOW_THRESHOLD",
        "REBOOT",
        "SYNC_MANUAL_SCHEDULES",
        "UPSERT_MANUAL_SCHEDULE",
        "DELETE_MANUAL_SCHEDULE",
        "SET_RUNTIME_POLICY",
    ]
    command_value: Optional[Any] = None
    reason: Optional[str] = ""
    expires_in_sec: Optional[int] = 120
    requested_by: Optional[RequestedBy] = None


class DeviceInfoResponse(BaseModel):
    id: int
    customer_id: str
    controller_name: str
    serial_no: str
    install_address: str
    install_location: str
    latitude: float
    longitude: float
    allow_customer_control: bool
    camera_url: str
    device_api_base: str


class DeviceStatusResponse(BaseModel):
    id: int
    customer_id: str
    controller_name: str
    serial_no: str
    status: str
    snow_detected: bool
    snow_confidence: float
    snow_state: str
    heater_on: bool
    heater_mode: str
    offline_mode: bool
    current_control_source: str
    active_schedule_key: Optional[str] = None
    active_schedule_name: Optional[str] = None
    last_schedule_sync_at: Optional[str] = None
    snow_threshold: float
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    camera_url: str
    device_api_base: str
    allow_customer_control: bool
    last_seen_at: str
    last_central_sync_at: Optional[str] = None
    last_central_sync_success_at: Optional[str] = None
    central_connected: bool = False
    local_schedule_count: int = 0
    message: str


class ApiResponse(BaseModel):
    ok: bool = True
    message: str = "ok"
    data: Optional[Any] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
