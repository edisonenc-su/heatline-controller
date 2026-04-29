#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/shared/state" "$ROOT/shared/snapshots"
cat > "$ROOT/shared/state/device-status.json" <<JSON
{
  "status": "starting",
  "snow_detected": false,
  "snow_confidence": null,
  "snow_state": "unknown",
  "heater_on": false,
  "heater_mode": "auto",
  "stream": {
    "camera_url": "",
    "playback_url": "",
    "device_api_base": "",
    "public_base_url": "",
    "stream_type": "hls",
    "stream_health": "starting",
    "media_status": "starting",
    "media_last_seen_at": null
  }
}
JSON
cat > "$ROOT/shared/state/events.json" <<JSON
[]
JSON
cat > "$ROOT/shared/state/control-logs.json" <<JSON
[]
JSON
