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
        self._state = self._normalize_state(persisted)
        self._save()

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
            "offline_mode": False,
            "current_control_source": "idle",
            "active_schedule_key": None,
            "active_schedule_name": None,
            "last_schedule_sync_at": None,
            "snow_threshold": settings.snow_threshold,
            "temperature": settings.temperature_default,
            "humidity": settings.humidity_default,
            "camera_url": settings.stream_url,
            "device_api_base": settings.device_api_base,
            "allow_customer_control": settings.allow_customer_control,
            "last_seen_at": utc_now(),
            "last_central_sync_at": None,
            "last_central_sync_success_at": None,
            "central_connected": False,
            "local_schedule_count": 0,
            "message": "ready",
        }

    def _normalize_state(self, state: dict[str, Any] | None) -> dict[str, Any]:
        normalized = self._default_state()
        if isinstance(state, dict):
            normalized.update(state)

        normalized["id"] = settings.device_id
        normalized["customer_id"] = settings.customer_id
        normalized["controller_name"] = settings.device_name
        normalized["serial_no"] = settings.device_serial
        normalized["camera_url"] = settings.stream_url
        normalized["device_api_base"] = settings.device_api_base
        normalized["allow_customer_control"] = settings.allow_customer_control
        normalized["snow_threshold"] = float(normalized.get("snow_threshold", settings.snow_threshold))

        mode = str(normalized.get("heater_mode") or settings.heater_mode).lower()
        normalized["heater_mode"] = mode if mode in {"auto", "manual", "schedule"} else "auto"

        if normalized.get("current_control_source") in {None, ""}:
            normalized["current_control_source"] = "offline_idle" if normalized.get("offline_mode") else "idle"

        normalized["last_seen_at"] = normalized.get("last_seen_at") or utc_now()
        normalized["message"] = normalized.get("message") or "Pi backend booted"
        return normalized

    def _save(self) -> None:
        self._state = self._normalize_state(self._state)
        save_state("device_status", self._state)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._state = self._normalize_state(self._state)
            return dict(self._state)

    def apply_status(self, payload: StatusPayload | dict[str, Any]) -> dict[str, Any]:
        data = payload.model_dump() if isinstance(payload, StatusPayload) else dict(payload)
        with self._lock:
            self._state.update({k: v for k, v in data.items() if v is not None})
            self._state["last_seen_at"] = utc_now()
            self._state = self._normalize_state(self._state)
            self._save()
            return dict(self._state)

    def apply_heartbeat(self, status: str | None = None, message: str | None = None) -> dict[str, Any]:
        with self._lock:
            if status:
                self._state["status"] = status
            if message is not None:
                self._state["message"] = message
            self._state["last_seen_at"] = utc_now()
            self._state = self._normalize_state(self._state)
            self._save()
            return dict(self._state)

    def update_schedule_inventory(self, count: int, last_sync_at: str | None = None) -> dict[str, Any]:
        with self._lock:
            self._state["local_schedule_count"] = max(0, int(count))
            if last_sync_at is not None:
                self._state["last_schedule_sync_at"] = last_sync_at
            self._state["last_seen_at"] = utc_now()
            self._state = self._normalize_state(self._state)
            self._save()
            return dict(self._state)

    def set_central_connection(self, connected: bool, *, offline_mode: bool | None = None, message: str | None = None) -> dict[str, Any]:
        with self._lock:
            self._state["central_connected"] = bool(connected)
            self._state["last_central_sync_at"] = utc_now()
            if connected:
                self._state["last_central_sync_success_at"] = self._state["last_central_sync_at"]
            if offline_mode is not None:
                self._state["offline_mode"] = bool(offline_mode)
            if message is not None:
                self._state["message"] = message
            self._state = self._normalize_state(self._state)
            self._save()
            return dict(self._state)

    def apply_schedule_runtime(self, active_schedule: dict[str, Any] | None, *, heater_on: bool, note: str) -> dict[str, Any]:
        with self._lock:
            current_source = self._state.get("current_control_source")
            if current_source == "manual_command" and active_schedule is None:
                self._state["message"] = note
                self._state["last_seen_at"] = utc_now()
                self._state = self._normalize_state(self._state)
                self._save()
                return dict(self._state)

            if active_schedule:
                self._state["heater_on"] = bool(heater_on)
                self._state["current_control_source"] = "manual_schedule"
                self._state["active_schedule_key"] = active_schedule.get("schedule_key")
                self._state["active_schedule_name"] = active_schedule.get("name")
            else:
                if self._state.get("current_control_source") == "manual_schedule":
                    self._state["heater_on"] = False
                if self._state.get("current_control_source") != "manual_command":
                    self._state["current_control_source"] = "offline_idle" if self._state.get("offline_mode") else "idle"
                self._state["active_schedule_key"] = None
                self._state["active_schedule_name"] = None

            self._state["message"] = note
            self._state["last_seen_at"] = utc_now()
            self._state = self._normalize_state(self._state)
            self._save()
            return dict(self._state)

    def apply_command(self, payload: CommandPayload) -> dict[str, Any]:
        with self._lock:
            if payload.command_type == "HEATER_ON":
                self._state["heater_on"] = True
                self._state["current_control_source"] = "manual_command"
                note = "Heater turned on"
            elif payload.command_type == "HEATER_OFF":
                self._state["heater_on"] = False
                self._state["current_control_source"] = "manual_command"
                note = "Heater turned off"
            elif payload.command_type == "SET_MODE":
                mode = str(payload.command_value or "auto").lower()
                self._state["heater_mode"] = mode if mode in {"auto", "manual", "schedule"} else "auto"
                if self._state["heater_mode"] != "schedule" and self._state.get("current_control_source") == "manual_schedule":
                    self._state["current_control_source"] = "idle"
                    self._state["active_schedule_key"] = None
                    self._state["active_schedule_name"] = None
                note = f"Mode changed to {self._state['heater_mode']}"
            elif payload.command_type == "SET_SNOW_THRESHOLD":
                try:
                    threshold = float(payload.command_value)
                except (TypeError, ValueError):
                    threshold = self._state.get("snow_threshold", settings.snow_threshold)
                self._state["snow_threshold"] = max(0.0, min(1.0, threshold))
                note = f"Snow threshold set to {self._state['snow_threshold']:.2f}"
            elif payload.command_type == "SYNC_MANUAL_SCHEDULES":
                note = "Manual schedules synchronized"
            elif payload.command_type == "UPSERT_MANUAL_SCHEDULE":
                note = "Manual schedule upserted"
            elif payload.command_type == "DELETE_MANUAL_SCHEDULE":
                note = "Manual schedule deleted"
            elif payload.command_type == "SET_RUNTIME_POLICY":
                note = "Runtime policy updated"
            elif payload.command_type == "REBOOT":
                note = "Reboot requested"
            else:
                note = "Command accepted"

            self._state["last_seen_at"] = utc_now()
            self._state["message"] = payload.reason or note
            self._state = self._normalize_state(self._state)
            self._save()
            return {"state": dict(self._state), "note": note}


runtime_state = DeviceRuntimeState()
