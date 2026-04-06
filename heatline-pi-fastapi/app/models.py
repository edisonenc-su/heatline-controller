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
    heater_mode: Literal["auto", "manual"] = "auto"
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


class CommandPayload(BaseModel):
    command_type: Literal[
        "HEATER_ON",
        "HEATER_OFF",
        "SET_MODE",
        "SET_SNOW_THRESHOLD",
        "REBOOT",
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
    snow_threshold: float
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    camera_url: str
    device_api_base: str
    allow_customer_control: bool
    last_seen_at: str
    message: str


class ApiResponse(BaseModel):
    ok: bool = True
    message: str = "ok"
    data: Optional[Any] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
