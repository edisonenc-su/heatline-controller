from __future__ import annotations

import threading
import time
from typing import Any

import requests

from .config import settings
from .db import insert_event
from .state import runtime_state


class CentralSyncService:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_success_monotonic = time.monotonic()

    def start(self) -> None:
        if not settings.central_api_base:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.central_device_token:
            headers["x-device-token"] = settings.central_device_token
        return headers

    def _push_once(self) -> None:
        snapshot = runtime_state.snapshot()
        url = f"{settings.central_api_base}/api/v1/controllers/{settings.device_id}/status"
        payload: dict[str, Any] = {
            "status": snapshot["status"],
            "snow_detected": snapshot["snow_detected"],
            "heater_on": snapshot["heater_on"],
            "temperature": snapshot.get("temperature"),
            "humidity": snapshot.get("humidity"),
            "camera_url": snapshot.get("camera_url"),
            "snow_threshold": snapshot.get("snow_threshold"),
            "heater_mode": snapshot.get("heater_mode"),
            "offline_mode": snapshot.get("offline_mode"),
            "current_control_source": snapshot.get("current_control_source"),
            "active_schedule_name": snapshot.get("active_schedule_name"),
            "last_schedule_sync_at": snapshot.get("last_schedule_sync_at"),
            "last_seen_at": snapshot.get("last_seen_at"),
            "device_api_base": settings.device_api_base,
        }
        requests.put(
            url,
            json=payload,
            headers=self._headers(),
            timeout=max(3, settings.request_timeout_ms / 1000),
        ).raise_for_status()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._push_once()
                self._last_success_monotonic = time.monotonic()
                runtime_state.set_central_connection(True, offline_mode=False, message="central sync ok")
            except Exception as exc:  # pragma: no cover
                offline_mode = False
                if settings.offline_fallback_enabled:
                    offline_mode = (time.monotonic() - self._last_success_monotonic) >= max(10, settings.offline_grace_sec)
                runtime_state.set_central_connection(False, offline_mode=offline_mode, message=str(exc))
                insert_event(
                    event_type="CENTRAL_SYNC_FAILED",
                    message=str(exc),
                    severity="warning",
                )
            self._stop.wait(settings.sync_interval_sec)


central_sync_service = CentralSyncService()
