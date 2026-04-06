from __future__ import annotations

import threading
import time
from typing import Any

import requests

from .config import settings
from .db import insert_event, load_state, save_state
from .state import runtime_state


class CentralSyncService:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._session = requests.Session()

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
        self._session.close()

    def _timeout(self) -> float:
        return max(3, settings.request_timeout_ms / 1000)

    def _pairing_enabled(self) -> bool:
        return bool(getattr(settings, 'pairing_enabled', False))

    def _provision_key(self) -> str:
        return str(getattr(settings, 'provision_key', '') or '').strip()

    def _firmware_version(self) -> str | None:
        value = str(getattr(settings, 'firmware_version', '') or '').strip()
        return value or None

    def _hardware_model(self) -> str | None:
        value = str(getattr(settings, 'hardware_model', '') or '').strip()
        return value or None

    def _public_base_url(self) -> str:
        configured = str(getattr(settings, 'public_base_url', '') or '').strip().rstrip('/')
        if configured:
            return configured
        host = getattr(settings, 'public_host', '127.0.0.1')
        return f'http://{host}:{settings.pi_api_port}'

    def _stored_pairing(self) -> dict[str, Any]:
        return load_state('central_pairing', default={}) or {}

    def _current_controller_id(self) -> int:
        pairing = self._stored_pairing()
        if pairing.get('controller_id'):
            return int(pairing['controller_id'])
        configured = getattr(settings, 'central_controller_id', None)
        if configured:
            return int(configured)
        return int(getattr(settings, 'device_id', 0))

    def _current_device_token(self) -> str:
        pairing = self._stored_pairing()
        if pairing.get('device_sync_token'):
            return str(pairing['device_sync_token'])
        explicit = str(getattr(settings, 'device_sync_token', '') or '').strip()
        if explicit:
            return explicit
        legacy = str(getattr(settings, 'central_device_token', '') or '').strip()
        if legacy:
            return legacy
        shared = str(getattr(settings, 'device_shared_token', '') or '').strip()
        return shared

    def _headers(self) -> dict[str, str]:
        headers = {'Content-Type': 'application/json'}
        token = self._current_device_token()
        if token:
            headers['X-Device-Token'] = token
            headers['Authorization'] = f'Bearer {token}'
        return headers

    def _claim_payload(self) -> dict[str, Any]:
        snapshot = runtime_state.snapshot()
        return {
            'serial_no': getattr(settings, 'device_serial', ''),
            'provision_key': self._provision_key(),
            'controller_name': getattr(settings, 'device_name', None),
            'install_address': getattr(settings, 'install_address', None),
            'install_location': getattr(settings, 'install_location', None),
            'latitude': getattr(settings, 'latitude', None),
            'longitude': getattr(settings, 'longitude', None),
            'device_api_base': settings.device_api_base,
            'camera_url': snapshot.get('camera_url') or settings.stream_url,
            'public_base_url': self._public_base_url(),
            'stream_type': 'mjpeg',
            'firmware_version': self._firmware_version(),
            'hardware_model': self._hardware_model(),
        }

    def _claim_once(self) -> bool:
        if not self._pairing_enabled():
            return False

        pairing = self._stored_pairing()
        if pairing.get('controller_id') and pairing.get('device_sync_token'):
            return True

        provision_key = self._provision_key()
        if not provision_key:
            return False

        url = f"{settings.central_api_base}/api/v1/device-provision/claim"
        response = self._session.post(
            url,
            json=self._claim_payload(),
            headers={'Content-Type': 'application/json'},
            timeout=self._timeout(),
        )
        response.raise_for_status()
        body = response.json()
        data = body.get('data') or body

        pairing_info = {
            'controller_id': int(data['controller_id']),
            'device_sync_token': str(data['device_sync_token']),
            'pairing_status': data.get('pairing_status', 'claimed'),
            'claimed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }
        save_state('central_pairing', pairing_info)
        insert_event(
            event_type='CENTRAL_PROVISION_CLAIMED',
            message='Central auto provisioning claimed successfully',
            severity='info',
            payload=pairing_info,
        )
        return True

    def _push_once(self) -> None:
        controller_id = self._current_controller_id()
        token = self._current_device_token()
        if not controller_id or not token:
            raise RuntimeError('controller_id 또는 device token 이 없어 중앙 동기화를 진행할 수 없습니다.')

        snapshot = runtime_state.snapshot()
        url = f"{settings.central_api_base}/api/v1/controllers/{controller_id}/status"
        payload: dict[str, Any] = {
            'status': snapshot['status'],
            'snow_detected': snapshot['snow_detected'],
            'heater_on': snapshot['heater_on'],
            'temperature': snapshot.get('temperature'),
            'humidity': snapshot.get('humidity'),
            'camera_url': snapshot.get('camera_url') or settings.stream_url,
            'snow_threshold': snapshot.get('snow_threshold'),
            'heater_mode': snapshot.get('heater_mode'),
            'last_seen_at': snapshot.get('last_seen_at'),
            'device_api_base': settings.device_api_base,
            'public_base_url': self._public_base_url(),
            'stream_type': 'mjpeg',
            'firmware_version': self._firmware_version(),
            'hardware_model': self._hardware_model(),
        }
        self._session.put(
            url,
            json=payload,
            headers=self._headers(),
            timeout=self._timeout(),
        ).raise_for_status()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._claim_once()
                self._push_once()
            except Exception as exc:  # pragma: no cover
                insert_event(
                    event_type='CENTRAL_SYNC_FAILED',
                    message=str(exc),
                    severity='warning',
                )
            self._stop.wait(settings.sync_interval_sec)


central_sync_service = CentralSyncService()
