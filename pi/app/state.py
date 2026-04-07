from __future__ import annotations

from threading import Lock
from typing import Any

from .config import settings
from .db import load_state, save_state, utc_now
from .models import CommandPayload, StatusPayload


class DeviceRuntimeState:
    def __init__(self) -> None:
        self._lock = Lock()
        persisted = load_state("device_status", default=None)
        self._state = persisted or self._default_state()
        self._state.setdefault("camera_url", settings.stream_url)
        self._state.setdefault("device_api_base", settings.device_api_base)
        self._state.setdefault("allow_customer_control", settings.allow_customer_control)
        self._state.setdefault("last_seen_at", utc_now())
        self._state.setdefault("message", "Pi backend booted")
        save_state("device_status", self._state)

    def _default_state(self) -> dict[str, Any]:
        return {
            "id": settings.device_id,
            "customer_id": settings.customer_id,
            "controller_name": settings.device_name,
            "serial_no": settings.device_serial,
            "status": "online",
            "snow_detected": False,
            "snow_confidence": 0.0,
            "snow_state": "CLEAR",
            "heater_on": False,
            "heater_mode": settings.heater_mode,
            "snow_threshold": settings.snow_threshold,
            "temperature": settings.temperature_default,
            "humidity": settings.humidity_default,
            "camera_url": settings.stream_url,
            "device_api_base": settings.device_api_base,
            "allow_customer_control": settings.allow_customer_control,
            "last_seen_at": utc_now(),
            "message": "ready",
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def apply_status(self, payload: StatusPayload | dict[str, Any]) -> dict[str, Any]:
        data = payload.model_dump() if isinstance(payload, StatusPayload) else dict(payload)
        with self._lock:
            self._state.update({k: v for k, v in data.items() if v is not None})
            self._state["camera_url"] = self._state.get("camera_url") or settings.stream_url
            self._state["device_api_base"] = settings.device_api_base
            self._state["allow_customer_control"] = settings.allow_customer_control
            self._state["last_seen_at"] = utc_now()
            save_state("device_status", self._state)
            return dict(self._state)

    def apply_heartbeat(self, status: str | None = None, message: str | None = None) -> dict[str, Any]:
        with self._lock:
            if status:
                self._state["status"] = status
            if message is not None:
                self._state["message"] = message
            self._state["last_seen_at"] = utc_now()
            save_state("device_status", self._state)
            return dict(self._state)

    def apply_command(self, payload: CommandPayload) -> dict[str, Any]:
        with self._lock:
            if payload.command_type == "HEATER_ON":
                self._state["heater_on"] = True
                note = "Heater turned on"
            elif payload.command_type == "HEATER_OFF":
                self._state["heater_on"] = False
                note = "Heater turned off"
            elif payload.command_type == "SET_MODE":
                mode = str(payload.command_value or "auto").lower()
                self._state["heater_mode"] = "manual" if mode == "manual" else "auto"
                note = f"Mode changed to {self._state['heater_mode']}"
            elif payload.command_type == "SET_SNOW_THRESHOLD":
                try:
                    threshold = float(payload.command_value)
                except (TypeError, ValueError):
                    threshold = self._state.get("snow_threshold", settings.snow_threshold)
                self._state["snow_threshold"] = max(0.0, min(1.0, threshold))
                note = f"Snow threshold set to {self._state['snow_threshold']:.2f}"
            elif payload.command_type == "REBOOT":
                note = "Reboot requested"
            else:
                note = "Command accepted"

            self._state["last_seen_at"] = utc_now()
            self._state["message"] = payload.reason or note
            save_state("device_status", self._state)
            return {"state": dict(self._state), "note": note}


runtime_state = DeviceRuntimeState()
