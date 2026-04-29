const config = require('../config');
const { readJson, writeJson } = require('./file-store');
const { nowIso } = require('../utils/time');
const { getDefaultStreamState, refreshDerivedStreamState } = require('./stream-state');

function getDefaultState() {
  return {
    status: 'starting',
    snow_detected: false,
    snow_confidence: null,
    snow_state: 'unknown',
    heater_on: false,
    heater_mode: 'auto',
    temperature: null,
    humidity: null,
    snow_threshold: 0.8,
    ai_enabled: config.aiEnabled,
    ai_status: config.aiEnabled ? 'warming_up' : 'disabled',
    ai_last_inference_at: null,
    inference_model: config.aiModelName,
    inference_fps: 0,
    inference_latency_ms: null,
    last_seen_at: nowIso(),
    offline_mode: false,
    current_control_source: 'idle',
    stream: getDefaultStreamState(),
    updated_at: nowIso()
  };
}

async function loadState() {
  const state = await readJson(config.statusFile, getDefaultState());
  state.stream = refreshDerivedStreamState(state.stream || {});
  return state;
}

async function saveState(nextState) {
  const merged = {
    ...getDefaultState(),
    ...(nextState || {}),
    stream: refreshDerivedStreamState(nextState?.stream || {}),
    updated_at: nowIso()
  };
  await writeJson(config.statusFile, merged);
  return merged;
}

async function patchState(partial = {}) {
  const current = await loadState();
  const next = {
    ...current,
    ...partial,
    stream: refreshDerivedStreamState({ ...(current.stream || {}), ...(partial.stream || {}) }),
    last_seen_at: partial.last_seen_at || current.last_seen_at || nowIso()
  };
  return saveState(next);
}

async function getStatusResponse() {
  const state = await loadState();
  return {
    status: state.status,
    snow_detected: !!state.snow_detected,
    snow_confidence: state.snow_confidence,
    snow_state: state.snow_state,
    heater_on: !!state.heater_on,
    heater_mode: state.heater_mode,
    temperature: state.temperature,
    humidity: state.humidity,
    snow_threshold: state.snow_threshold,
    camera_url: state.stream.camera_url,
    playback_url: state.stream.playback_url,
    stream_type: state.stream.stream_type,
    playback_protocol: state.stream.stream_type,
    video_source_type: 'pi_camera',
    device_api_base: state.stream.device_api_base,
    public_base_url: state.stream.public_base_url,
    stream_health: state.stream.stream_health,
    media_status: state.stream.media_status,
    media_last_seen_at: state.stream.media_last_seen_at,
    ai_enabled: !!state.ai_enabled,
    ai_status: state.ai_status,
    ai_last_inference_at: state.ai_last_inference_at,
    inference_model: state.inference_model,
    inference_fps: state.inference_fps,
    inference_latency_ms: state.inference_latency_ms,
    last_seen_at: state.last_seen_at,
    offline_mode: !!state.offline_mode,
    current_control_source: state.current_control_source
  };
}

module.exports = { getDefaultState, loadState, saveState, patchState, getStatusResponse };
