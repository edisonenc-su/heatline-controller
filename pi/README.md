# Heatline Raspberry Pi FastAPI Backend

라즈베리파이에 배포하는 장비별 독립 백엔드입니다.

## 포함 기능
- MJPEG 비디오 스트리밍: `/stream.mjpg`
- 현재 프레임 스냅샷: `/snapshot.jpg`
- 상태 조회/갱신 API: `/api/v1/status`, `/api/v1/internal/status`, `/api/v1/heartbeat`
- 이벤트/제어 로그 API: `/api/v1/events`, `/api/v1/control-logs`
- 원격 명령 API: `/api/v1/commands`
- 중앙 백엔드 동기화 옵션: `CENTRAL_API_BASE`
- SQLite 로컬 저장
- Picamera2/OpenCV 카메라 우선 사용, 미연결 시 플레이스홀더 스트림 자동 제공

## 빠른 실행
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

브라우저 확인:
- API 문서: `http://<pi-ip>:9000/docs`
- 스트림: `http://<pi-ip>:9000/stream.mjpg`
- 상태: `http://<pi-ip>:9000/api/v1/status`

## snow_live.py 연동 방식
센서/추론 루프에서 아래 로컬 API만 호출하면 됩니다.

```python
import requests

requests.post(
    "http://127.0.0.1:9000/api/v1/internal/status",
    headers={"x-internal-token": "change-this-internal-token"},
    json={
        "status": "online",
        "snow_detected": True,
        "snow_confidence": 0.93,
        "snow_state": "SNOW",
        "heater_on": True,
        "heater_mode": "auto",
        "snow_threshold": 0.80,
        "temperature": -3.1,
        "humidity": 72.5,
        "message": "Hailo inference update"
    },
    timeout=3,
)
```

## 주요 엔드포인트
- `GET /health`
- `GET /api/v1/device/info`
- `GET /api/v1/status`
- `POST /api/v1/internal/status`
- `POST /api/v1/heartbeat`
- `GET /api/v1/events?limit=20`
- `POST /api/v1/events`
- `GET /api/v1/control-logs?limit=20`
- `POST /api/v1/commands`
- `GET /stream.mjpg`
- `GET /snapshot.jpg`

## systemd 예시
```ini
[Unit]
Description=Heatline Raspberry Pi FastAPI Backend
After=network.target

[Service]
WorkingDirectory=/home/pi/heatline-pi-fastapi
EnvironmentFile=/home/pi/heatline-pi-fastapi/.env
ExecStart=/home/pi/heatline-pi-fastapi/.venv/bin/python run.py
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```
