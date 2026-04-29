const config = require('../config');
const { nowIso } = require('../utils/time');

function getDefaultStreamState() {
  return {
    camera_url: config.cameraUrl,
    playback_url: config.cameraUrl,
    device_api_base: config.deviceApiBaseUrl,
    public_base_url: config.piPublicBaseUrl,
    stream_type: config.streamType,
    stream_health: 'starting',
    stream_input_url: config.streamInputUrl,
    source_rtsp_url: config.sourceRtspUrl,
    media_status: 'starting',
    media_last_seen_at: null,
    updated_at: nowIso()
  };
}

function refreshDerivedStreamState(current = {}) {
  return {
    ...getDefaultStreamState(),
    ...current,
    playback_url: current.playback_url || current.camera_url || config.cameraUrl,
    updated_at: nowIso()
  };
}

module.exports = { getDefaultStreamState, refreshDerivedStreamState };
