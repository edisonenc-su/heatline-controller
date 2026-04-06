import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

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
                None if command_value is None else str(command_value),
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
