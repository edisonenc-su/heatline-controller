from __future__ import annotations

import threading
from datetime import datetime, timedelta

from .config import settings
from .db import list_manual_schedules
from .state import runtime_state


class LocalScheduleService:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _combine_weekly_window(self, now: datetime, item: dict) -> tuple[datetime, datetime] | None:
        start_time = item.get("start_time")
        end_time = item.get("end_time")
        if not start_time or not end_time:
            return None
        try:
            start_hour, start_min = map(int, str(start_time).split(":"))
            end_hour, end_min = map(int, str(end_time).split(":"))
        except ValueError:
            return None
        start_at = now.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
        end_at = now.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)
        if end_at <= start_at:
            end_at += timedelta(days=1)
        return start_at, end_at

    def _parse_iso_dt(self, value: str | None) -> datetime | None:
        if not value:
            return None
        text = str(value).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed

    def _evaluate(self, item: dict, now: datetime, temperature: float | None, offline_mode: bool) -> tuple[bool, bool]:
        if not item.get("enabled"):
            return False, False
        if offline_mode and not item.get("offline_enabled"):
            return False, False
        min_temp = item.get("min_temperature")
        max_temp = item.get("max_temperature")
        if temperature is not None and min_temp is not None and float(temperature) > float(min_temp):
            return False, False
        if temperature is not None and max_temp is not None and float(temperature) > float(max_temp):
            return False, False

        preheat = max(0, int(item.get("preheat_minutes") or 0))
        schedule_type = item.get("schedule_type") or "weekly"

        if schedule_type == "once":
            start_at = self._parse_iso_dt(item.get("once_started_at"))
            end_at = self._parse_iso_dt(item.get("once_ended_at"))
            if not start_at or not end_at or end_at <= start_at:
                return False, False
            preheat_start = start_at - timedelta(minutes=preheat)
            if preheat and preheat_start <= now < start_at:
                return True, True
            return (start_at <= now < end_at), False

        days_of_week = item.get("days_of_week") or []
        weekday_code = (now.weekday() + 1) % 7
        if days_of_week and weekday_code not in days_of_week:
            return False, False
        window = self._combine_weekly_window(now, item)
        if not window:
            return False, False
        start_at, end_at = window
        preheat_start = start_at - timedelta(minutes=preheat)
        if preheat and preheat_start <= now < start_at:
            return True, True
        return (start_at <= now < end_at), False

    def _select_active(self, items: list[dict], snapshot: dict) -> tuple[dict | None, bool]:
        now = datetime.now()
        temperature = snapshot.get("temperature")
        offline_mode = bool(snapshot.get("offline_mode"))
        candidates: list[tuple[int, bool, dict]] = []
        for item in items:
            active, preheat = self._evaluate(item, now, temperature, offline_mode)
            if active:
                candidates.append((int(item.get("priority") or 0), preheat, item))
        if not candidates:
            return None, False
        candidates.sort(key=lambda value: (value[0], 0 if value[1] else 1), reverse=True)
        _, preheat, selected = candidates[0]
        return selected, preheat

    def _loop(self) -> None:
        while not self._stop.is_set():
            snapshot = runtime_state.snapshot()
            items = list_manual_schedules()
            runtime_state.update_schedule_inventory(len(items))
            if snapshot.get("heater_mode") != "schedule":
                if snapshot.get("current_control_source") == "manual_schedule":
                    runtime_state.apply_schedule_runtime(None, heater_on=False, note="schedule mode disabled")
                self._stop.wait(settings.schedule_poll_interval_sec)
                continue
            active, preheat = self._select_active(items, snapshot)
            if active:
                label = active.get("name") or "manual schedule"
                note = f"manual schedule active: {label}"
                if preheat:
                    note = f"manual schedule preheat: {label}"
                runtime_state.apply_schedule_runtime(active, heater_on=True, note=note)
            else:
                runtime_state.apply_schedule_runtime(None, heater_on=False, note="no active manual schedule")
            self._stop.wait(settings.schedule_poll_interval_sec)


local_schedule_service = LocalScheduleService()
