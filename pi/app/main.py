from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .auth import verify_device_token, verify_internal_token
from .camera import camera_service
from .central_sync import central_sync_service
from .config import settings
from .db import init_db, insert_control_log, insert_event, list_control_logs, list_events, load_state
from .models import (
    ApiResponse,
    CommandPayload,
    DeviceInfoResponse,
    DeviceStatusResponse,
    EventPayload,
    HeartbeatPayload,
    StatusPayload,
)
from .state import runtime_state


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    camera_service.start()
    central_sync_service.start()
    yield
    central_sync_service.stop()
    camera_service.stop()


app = FastAPI(
    title="Heatline Raspberry Pi Backend",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    snapshot = runtime_state.snapshot()
    return {
        "ok": True,
        "service": "heatline-pi-fastapi",
        "camera_source": camera_service.get_source_name(),
        "device_id": settings.device_id,
        "status": snapshot["status"],
    }


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
    return ApiResponse(message="status updated", data=state)


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
    return ApiResponse(message="internal status updated", data=state)


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


@app.post("/api/v1/commands", response_model=ApiResponse)
def send_command(payload: CommandPayload):
    result = runtime_state.apply_command(payload)
    requester = payload.requested_by or None
    insert_control_log(
        command_type=payload.command_type,
        command_value=payload.command_value,
        result="accepted",
        note=result["note"],
        requested_by_user_id=requester.user_id if requester else None,
        requested_by_user_name=requester.user_name if requester else None,
    )
    insert_event(
        event_type="COMMAND_ACCEPTED",
        message=result["note"],
        severity="info",
        payload=payload.model_dump(),
    )
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
