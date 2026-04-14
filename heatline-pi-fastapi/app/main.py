from __future__ import annotations

import os
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from .auth import verify_device_token, verify_internal_token
from .camera import camera_service
from .central_sync import central_sync_service
from .config import settings
from .db import (
    delete_manual_schedule,
    init_db,
    insert_control_log,
    insert_event,
    list_control_logs,
    list_events,
    list_manual_schedules,
    load_state,
    replace_central_manual_schedules,
    save_state,
    summarize_manual_schedules,
    upsert_manual_schedule,
    utc_now,
)
from .gpio_relay import heater_relay_controller
from .local_schedule import local_schedule_service
from .models import (
    ApiResponse,
    CommandPayload,
    DeviceInfoResponse,
    DeviceStatusResponse,
    EventPayload,
    HeartbeatPayload,
    ManualSchedulePayload,
    ManualScheduleSyncPayload,
    RuntimePolicyPayload,
    StatusPayload,
)
from .state import runtime_state


GPIO_SYNC_INTERVAL_SEC = max(0.2, float(os.getenv("HEATER_RELAY_SYNC_INTERVAL_SEC", "1.0")))
_gpio_sync_stop = threading.Event()
_gpio_sync_thread: threading.Thread | None = None
STATIC_DIR = Path(__file__).resolve().parent / "static"
CONTROL_PAGE = STATIC_DIR / "device-control.html"


def runtime_policy() -> dict:
    return load_state(
        "runtime_policy",
        default={
            "offline_fallback_enabled": settings.offline_fallback_enabled,
            "offline_grace_sec": settings.offline_grace_sec,
            "schedule_poll_interval_sec": settings.schedule_poll_interval_sec,
        },
    )



def _requester_values(payload: CommandPayload) -> tuple[str | None, str | None]:
    requester = payload.requested_by or None
    return (
        requester.user_id if requester else None,
        requester.user_name if requester else None,
    )



def _write_command_log(payload: CommandPayload, result: str, note: str) -> None:
    user_id, user_name = _requester_values(payload)
    insert_control_log(
        command_type=payload.command_type,
        command_value=payload.command_value,
        result=result,
        note=note,
        requested_by_user_id=user_id,
        requested_by_user_name=user_name,
    )



def _sync_relay_from_runtime(*, force: bool = False, source: str = "runtime") -> dict:
    snapshot = runtime_state.snapshot()
    relay_status = heater_relay_controller.sync_from_runtime(snapshot, force=force)
    snapshot_after = runtime_state.apply_status(
        {
            "status": "online",
            "message": f"relay sync ok ({source})",
        }
    )
    return {
        "runtime": snapshot_after,
        "relay": relay_status,
    }



def _mark_relay_error(exc: Exception, *, source: str) -> dict:
    relay_status = heater_relay_controller.fail(exc)
    runtime = runtime_state.apply_status(
        {
            "status": "error",
            "message": f"GPIO relay error ({source}): {exc}",
        }
    )
    return {
        "runtime": runtime,
        "relay": relay_status,
    }



def _restore_runtime_snapshot(previous: dict, message: str) -> dict:
    return runtime_state.apply_status(
        {
            "status": previous.get("status", "online"),
            "heater_on": bool(previous.get("heater_on", False)),
            "heater_mode": previous.get("heater_mode", "auto"),
            "offline_mode": bool(previous.get("offline_mode", False)),
            "current_control_source": previous.get("current_control_source", "idle"),
            "active_schedule_name": previous.get("active_schedule_name"),
            "last_schedule_sync_at": previous.get("last_schedule_sync_at"),
            "snow_threshold": previous.get("snow_threshold", settings.snow_threshold),
            "temperature": previous.get("temperature"),
            "humidity": previous.get("humidity"),
            "camera_url": previous.get("camera_url"),
            "message": message,
        }
    )



def _maybe_request_reboot(payload: CommandPayload) -> None:
    if payload.command_type != "REBOOT":
        return

    def _worker() -> None:
        time.sleep(1.0)
        try:
            subprocess.Popen(["sudo", "reboot"])
        except Exception as exc:  # pragma: no cover - depends on host OS
            insert_event(
                event_type="REBOOT_FAILED",
                message=f"reboot command failed: {exc}",
                severity="critical",
                payload={"command_type": payload.command_type},
            )

    threading.Thread(target=_worker, daemon=True).start()



def _gpio_sync_loop() -> None:
    last_desired: bool | None = None
    last_error: str | None = None

    while not _gpio_sync_stop.wait(GPIO_SYNC_INTERVAL_SEC):
        snapshot = runtime_state.snapshot()
        desired = bool(snapshot.get("heater_on"))
        try:
            if last_desired is None or desired != last_desired:
                heater_relay_controller.sync_from_runtime(snapshot, force=(last_desired is None))
                last_desired = desired
                last_error = None
        except Exception as exc:  # pragma: no cover - hardware dependent
            message = str(exc)
            _mark_relay_error(exc, source="background-sync")
            if message != last_error:
                insert_event(
                    event_type="GPIO_SYNC_ERROR",
                    message=f"GPIO relay sync failed: {message}",
                    severity="critical",
                    payload={
                        "desired_heater_on": desired,
                        "source": "background-sync",
                    },
                )
                last_error = message



def _start_gpio_sync_thread() -> None:
    global _gpio_sync_thread
    if _gpio_sync_thread and _gpio_sync_thread.is_alive():
        return
    _gpio_sync_stop.clear()
    _gpio_sync_thread = threading.Thread(target=_gpio_sync_loop, daemon=True)
    _gpio_sync_thread.start()



def _stop_gpio_sync_thread() -> None:
    _gpio_sync_stop.set()
    if _gpio_sync_thread and _gpio_sync_thread.is_alive():
        _gpio_sync_thread.join(timeout=2)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    try:
        heater_relay_controller.initialize()
        heater_relay_controller.sync_from_runtime(runtime_state.snapshot(), force=True)
        insert_event(
            event_type="GPIO_READY",
            message="GPIO relay controller initialized",
            severity="info",
            payload=heater_relay_controller.status(),
        )
    except Exception as exc:
        _mark_relay_error(exc, source="startup")
        insert_event(
            event_type="GPIO_INIT_FAILED",
            message=f"GPIO relay controller init failed: {exc}",
            severity="critical",
            payload=heater_relay_controller.status(),
        )

    _start_gpio_sync_thread()
    camera_service.start()
    central_sync_service.start()
    local_schedule_service.start()
    yield
    _stop_gpio_sync_thread()
    local_schedule_service.stop()
    central_sync_service.stop()
    camera_service.stop()
    heater_relay_controller.close()


app = FastAPI(
    title="Heatline Raspberry Pi Backend",
    version="1.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
@app.get("/ui", include_in_schema=False)
def device_control_page():
    return FileResponse(CONTROL_PAGE)


@app.get("/health")
def health_check():
    snapshot = runtime_state.snapshot()
    return {
        "ok": True,
        "service": "heatline-pi-fastapi",
        "camera_source": camera_service.get_source_name(),
        "device_id": settings.device_id,
        "status": snapshot["status"],
        "heater_mode": snapshot["heater_mode"],
        "heater_on": snapshot["heater_on"],
        "offline_mode": snapshot["offline_mode"],
        "active_schedule_name": snapshot.get("active_schedule_name"),
        "relay": heater_relay_controller.status(),
    }


@app.get("/api/v1/gpio/relay", response_model=ApiResponse)
def get_gpio_relay_status():
    return ApiResponse(data=heater_relay_controller.status())


@app.get("/api/v1/device/info", response_model=DeviceInfoResponse)
def get_device_info():
    return DeviceInfoResponse(
        id=settings.device_id,
        customer_id=settings.customer_id,
        controller_name=settings.device_name,
        serial_no=settings.device_serial,
        install_address=settings.install_address,
        install_location=settings.install_location,
        latitude=settings.latitude,
        longitude=settings.longitude,
        allow_customer_control=settings.allow_customer_control,
        camera_url=settings.stream_url,
        device_api_base=settings.device_api_base,
    )


@app.get("/api/v1/status", response_model=DeviceStatusResponse)
def get_status():
    return DeviceStatusResponse(**runtime_state.snapshot())


@app.get("/api/v1/provision/status", response_model=ApiResponse)
def get_provision_status():
    pairing = load_state("central_pairing", default={}) or {}
    return ApiResponse(
        data={
            "pairing_enabled": settings.pairing_enabled,
            "provision_key_configured": bool(settings.provision_key),
            "controller_id": pairing.get("controller_id") or settings.central_controller_id or None,
            "device_sync_token_issued": bool(pairing.get("device_sync_token") or settings.device_sync_token or settings.central_device_token),
            "pairing_status": pairing.get("pairing_status", "pending"),
            "claimed_at": pairing.get("claimed_at"),
            "central_api_base": settings.central_api_base,
            "public_base_url": settings.public_base_url or settings.stream_url,
        }
    )


@app.post("/api/v1/status", response_model=ApiResponse)
def update_status(
    payload: StatusPayload,
    _: str = Depends(verify_device_token),
):
    state = runtime_state.apply_status(payload)
    try:
        relay = heater_relay_controller.sync_from_runtime(state)
    except Exception as exc:  # pragma: no cover - hardware dependent
        relay_state = _mark_relay_error(exc, source="status-update")
        return ApiResponse(message="status updated but relay sync failed", data=relay_state)
    return ApiResponse(message="status updated", data={"runtime": state, "relay": relay})


@app.post("/api/v1/internal/status", response_model=ApiResponse)
def update_internal_status(
    payload: StatusPayload,
    _: str = Depends(verify_internal_token),
):
    state = runtime_state.apply_status(payload)
    if payload.message:
        insert_event(
            event_type="STATUS_UPDATE",
            message=payload.message,
            severity="info",
            payload=payload.model_dump(),
        )
    try:
        relay = heater_relay_controller.sync_from_runtime(state)
    except Exception as exc:  # pragma: no cover - hardware dependent
        relay_state = _mark_relay_error(exc, source="internal-status")
        return ApiResponse(message="internal status updated but relay sync failed", data=relay_state)
    return ApiResponse(message="internal status updated", data={"runtime": state, "relay": relay})


@app.post("/api/v1/heartbeat", response_model=ApiResponse)
def heartbeat(payload: HeartbeatPayload):
    state = runtime_state.apply_heartbeat(payload.status, payload.message)
    return ApiResponse(message="heartbeat accepted", data=state)


@app.get("/api/v1/events", response_model=ApiResponse)
def get_events(limit: int = Query(default=20, ge=1, le=200)):
    return ApiResponse(data={"items": list_events(limit=limit)})


@app.post("/api/v1/events", response_model=ApiResponse)
def create_event(payload: EventPayload):
    insert_event(
        event_type=payload.event_type,
        message=payload.message,
        severity=payload.severity,
        payload=payload.payload,
    )
    return ApiResponse(message="event saved", data=payload.model_dump())


@app.get("/api/v1/control-logs", response_model=ApiResponse)
def get_control_logs(limit: int = Query(default=20, ge=1, le=200)):
    return ApiResponse(data={"items": list_control_logs(limit=limit)})


@app.get("/api/v1/manual-schedules", response_model=ApiResponse)
def get_manual_schedules():
    return ApiResponse(data={"items": list_manual_schedules()})


@app.get("/api/v1/manual-schedules/summary", response_model=ApiResponse)
def get_manual_schedules_summary():
    summary = summarize_manual_schedules()
    summary.update(
        {
            "runtime": runtime_state.snapshot(),
            "policy": runtime_policy(),
            "relay": heater_relay_controller.status(),
        }
    )
    return ApiResponse(data=summary)


@app.post("/api/v1/manual-schedules", response_model=ApiResponse)
def create_manual_schedule(payload: ManualSchedulePayload):
    item = upsert_manual_schedule(payload.model_dump(), source="local")
    runtime_state.update_schedule_inventory(summarize_manual_schedules()["total"])
    return ApiResponse(message="manual schedule saved", data=item)


@app.put("/api/v1/manual-schedules/{schedule_key}", response_model=ApiResponse)
def update_manual_schedule(schedule_key: str, payload: ManualSchedulePayload):
    item = upsert_manual_schedule(payload.model_dump(), source=str(payload.source or "local"), schedule_key=schedule_key)
    runtime_state.update_schedule_inventory(summarize_manual_schedules()["total"])
    return ApiResponse(message="manual schedule updated", data=item)


@app.delete("/api/v1/manual-schedules/{schedule_key}", response_model=ApiResponse)
def remove_manual_schedule(schedule_key: str):
    deleted = delete_manual_schedule(schedule_key)
    runtime_state.update_schedule_inventory(summarize_manual_schedules()["total"])
    return ApiResponse(message="manual schedule deleted", data={"schedule_key": schedule_key, "deleted": deleted})


@app.post("/api/v1/manual-schedules/sync", response_model=ApiResponse)
def sync_manual_schedules(payload: ManualScheduleSyncPayload):
    items = replace_central_manual_schedules([item.model_dump() for item in payload.schedules])
    snapshot = runtime_state.update_schedule_inventory(summarize_manual_schedules()["total"], last_sync_at=utc_now())
    return ApiResponse(message="central schedules synchronized", data={"items": items, "runtime": snapshot})


@app.get("/api/v1/runtime-policy", response_model=ApiResponse)
def get_runtime_policy():
    return ApiResponse(data=runtime_policy())


@app.put("/api/v1/runtime-policy", response_model=ApiResponse)
def put_runtime_policy(payload: RuntimePolicyPayload):
    value = payload.model_dump()
    save_state("runtime_policy", value)
    return ApiResponse(message="runtime policy updated", data=value)


@app.post("/api/v1/commands", response_model=ApiResponse)
def send_command(
    payload: CommandPayload,
    _: str = Depends(verify_device_token),
):
    before_snapshot = runtime_state.snapshot()

    if payload.command_type in {"HEATER_ON", "HEATER_OFF"} and str(before_snapshot.get("heater_mode") or "").lower() != "manual":
        raise HTTPException(status_code=409, detail="수동 모드에서만 열선 ON/OFF 명령이 가능합니다.")

    if payload.command_type == "SYNC_MANUAL_SCHEDULES":
        schedules = (payload.command_value or {}).get("schedules", []) if isinstance(payload.command_value, dict) else []
        replace_central_manual_schedules(schedules)
        runtime_state.update_schedule_inventory(summarize_manual_schedules()["total"], last_sync_at=utc_now())
    elif payload.command_type == "UPSERT_MANUAL_SCHEDULE" and isinstance(payload.command_value, dict):
        upsert_manual_schedule(payload.command_value, source=str(payload.command_value.get("source") or "central"))
        runtime_state.update_schedule_inventory(summarize_manual_schedules()["total"])
    elif payload.command_type == "DELETE_MANUAL_SCHEDULE":
        schedule_key = str(payload.command_value or "")
        if schedule_key:
            delete_manual_schedule(schedule_key)
        runtime_state.update_schedule_inventory(summarize_manual_schedules()["total"])
    elif payload.command_type == "SET_RUNTIME_POLICY" and isinstance(payload.command_value, dict):
        current = runtime_policy()
        current.update(payload.command_value)
        save_state("runtime_policy", current)

    result = runtime_state.apply_command(payload)

    try:
        if payload.command_type in {"HEATER_ON", "HEATER_OFF"}:
            relay_bundle = _sync_relay_from_runtime(force=True, source=payload.command_type)
            result["relay"] = relay_bundle["relay"]
            result["state"] = relay_bundle["runtime"]
        else:
            result["relay"] = heater_relay_controller.status()
    except Exception as exc:  # pragma: no cover - hardware dependent
        restored = _restore_runtime_snapshot(before_snapshot, f"GPIO relay command failed: {exc}")
        relay_state = _mark_relay_error(exc, source=f"command:{payload.command_type}")
        _write_command_log(payload, "failed", str(exc))
        insert_event(
            event_type="GPIO_COMMAND_FAILED",
            message=f"{payload.command_type} failed: {exc}",
            severity="critical",
            payload={
                "command": payload.model_dump(),
                "restored_state": restored,
                "relay": relay_state["relay"],
            },
        )
        raise HTTPException(status_code=500, detail=f"GPIO relay command failed: {exc}")

    _write_command_log(payload, "accepted", result["note"])
    insert_event(
        event_type="COMMAND_ACCEPTED",
        message=result["note"],
        severity="info",
        payload={
            **payload.model_dump(),
            "relay": result.get("relay"),
        },
    )
    _maybe_request_reboot(payload)
    return ApiResponse(message="command accepted", data=result)


@app.get(settings.stream_path)
def stream_mjpeg():
    return StreamingResponse(
        camera_service.mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/snapshot.jpg")
def snapshot_jpg():
    return Response(content=camera_service.get_frame(), media_type="image/jpeg")


@app.exception_handler(Exception)
async def unhandled_exception_handler(_, exc: Exception):  # pragma: no cover
    return JSONResponse(status_code=500, content={"ok": False, "message": str(exc)})
