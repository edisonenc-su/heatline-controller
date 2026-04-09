import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional
from uuid import uuid4

from .config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                message TEXT,
                severity TEXT DEFAULT 'info',
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS control_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command_type TEXT NOT NULL,
                command_value TEXT,
                result TEXT,
                note TEXT,
                requested_by_user_id TEXT,
                requested_by_user_name TEXT,
                requested_at TEXT,
                finished_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_state (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manual_schedules (
                schedule_key TEXT PRIMARY KEY,
                external_id TEXT,
                source TEXT NOT NULL DEFAULT 'local',
                name TEXT NOT NULL,
                schedule_type TEXT NOT NULL DEFAULT 'weekly',
                enabled INTEGER NOT NULL DEFAULT 1,
                days_of_week_json TEXT,
                start_time TEXT,
                end_time TEXT,
                once_started_at TEXT,
                once_ended_at TEXT,
                preheat_minutes INTEGER NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 50,
                offline_enabled INTEGER NOT NULL DEFAULT 1,
                min_temperature REAL,
                max_temperature REAL,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def save_state(key: str, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO kv_state (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value_json = excluded.value_json,
              updated_at = excluded.updated_at
            """,
            (key, payload, utc_now()),
        )


def load_state(key: str, default: Optional[Any] = None) -> Any:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value_json FROM kv_state WHERE key = ? LIMIT 1", (key,)
        ).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value_json"])
    except json.JSONDecodeError:
        return default


def insert_event(
    event_type: str,
    message: str,
    severity: str = "info",
    payload: Optional[dict] = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO event_logs (event_type, message, severity, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event_type,
                message,
                severity,
                json.dumps(payload or {}, ensure_ascii=False),
                utc_now(),
            ),
        )


def insert_control_log(
    command_type: str,
    command_value: Any,
    result: str,
    note: str,
    requested_by_user_id: Optional[str],
    requested_by_user_name: Optional[str],
) -> None:
    now = utc_now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO control_logs (
                command_type, command_value, result, note,
                requested_by_user_id, requested_by_user_name,
                requested_at, finished_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                command_type,
                None if command_value is None else json.dumps(command_value, ensure_ascii=False) if isinstance(command_value, (dict, list)) else str(command_value),
                result,
                note,
                None if requested_by_user_id is None else str(requested_by_user_id),
                requested_by_user_name,
                now,
                now,
                now,
            ),
        )


def list_events(limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM event_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    result: list[dict] = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        except json.JSONDecodeError:
            item["payload"] = {}
        result.append(item)
    return result


def list_control_logs(limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM control_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def _normalize_schedule_payload(payload: dict[str, Any], source: str | None = None, schedule_key: str | None = None) -> dict[str, Any]:
    raw_source = source or str(payload.get("source") or "local").strip().lower()
    external_id = payload.get("external_id") or payload.get("id")
    normalized_key = schedule_key
    if not normalized_key:
        if raw_source == "central" and external_id is not None:
            normalized_key = f"central:{external_id}"
        else:
            normalized_key = str(payload.get("schedule_key") or payload.get("id") or f"local:{uuid4().hex[:12]}")
    days_of_week = payload.get("days_of_week") or []
    return {
        "schedule_key": str(normalized_key),
        "external_id": None if external_id is None else str(external_id),
        "source": raw_source,
        "name": str(payload.get("name") or "현장 수동 스케줄").strip(),
        "schedule_type": str(payload.get("schedule_type") or "weekly").strip().lower(),
        "enabled": 0 if payload.get("enabled") is False else 1,
        "days_of_week_json": json.dumps(days_of_week, ensure_ascii=False),
        "start_time": payload.get("start_time"),
        "end_time": payload.get("end_time"),
        "once_started_at": payload.get("once_started_at"),
        "once_ended_at": payload.get("once_ended_at"),
        "preheat_minutes": max(0, int(payload.get("preheat_minutes") or 0)),
        "priority": max(0, int(payload.get("priority") or 50)),
        "offline_enabled": 0 if payload.get("offline_enabled") is False else 1,
        "min_temperature": payload.get("min_temperature"),
        "max_temperature": payload.get("max_temperature"),
        "note": str(payload.get("note") or "").strip(),
    }


def _row_to_schedule(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    item = dict(row)
    try:
        item["days_of_week"] = json.loads(item.pop("days_of_week_json") or "[]")
    except json.JSONDecodeError:
        item["days_of_week"] = []
    item["enabled"] = bool(item.get("enabled"))
    item["offline_enabled"] = bool(item.get("offline_enabled"))
    return item


def list_manual_schedules(source: str | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if source:
            rows = conn.execute(
                "SELECT * FROM manual_schedules WHERE source = ? ORDER BY priority DESC, updated_at DESC",
                (source,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM manual_schedules ORDER BY priority DESC, updated_at DESC"
            ).fetchall()
    return [_row_to_schedule(row) for row in rows]


def get_manual_schedule(schedule_key: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM manual_schedules WHERE schedule_key = ? LIMIT 1", (schedule_key,)
        ).fetchone()
    return _row_to_schedule(row)


def upsert_manual_schedule(payload: dict[str, Any], source: str | None = None, schedule_key: str | None = None) -> dict[str, Any]:
    item = _normalize_schedule_payload(payload, source=source, schedule_key=schedule_key)
    now = utc_now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO manual_schedules (
                schedule_key, external_id, source, name, schedule_type, enabled,
                days_of_week_json, start_time, end_time, once_started_at, once_ended_at,
                preheat_minutes, priority, offline_enabled,
                min_temperature, max_temperature, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(schedule_key) DO UPDATE SET
                external_id = excluded.external_id,
                source = excluded.source,
                name = excluded.name,
                schedule_type = excluded.schedule_type,
                enabled = excluded.enabled,
                days_of_week_json = excluded.days_of_week_json,
                start_time = excluded.start_time,
                end_time = excluded.end_time,
                once_started_at = excluded.once_started_at,
                once_ended_at = excluded.once_ended_at,
                preheat_minutes = excluded.preheat_minutes,
                priority = excluded.priority,
                offline_enabled = excluded.offline_enabled,
                min_temperature = excluded.min_temperature,
                max_temperature = excluded.max_temperature,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (
                item["schedule_key"],
                item["external_id"],
                item["source"],
                item["name"],
                item["schedule_type"],
                item["enabled"],
                item["days_of_week_json"],
                item["start_time"],
                item["end_time"],
                item["once_started_at"],
                item["once_ended_at"],
                item["preheat_minutes"],
                item["priority"],
                item["offline_enabled"],
                item["min_temperature"],
                item["max_temperature"],
                item["note"],
                now,
                now,
            ),
        )
    return get_manual_schedule(item["schedule_key"]) or item


def replace_central_manual_schedules(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with get_conn() as conn:
        conn.execute("DELETE FROM manual_schedules WHERE source = 'central'")
    replaced = [upsert_manual_schedule(item, source="central") for item in items]
    return replaced


def delete_manual_schedule(schedule_key: str) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM manual_schedules WHERE schedule_key = ?", (schedule_key,)
        )
    return cursor.rowcount > 0


def summarize_manual_schedules() -> dict[str, Any]:
    items = list_manual_schedules()
    return {
        "total": len(items),
        "enabled": len([item for item in items if item.get("enabled")]),
        "offline_enabled": len([item for item in items if item.get("enabled") and item.get("offline_enabled")]),
        "items": items,
    }
