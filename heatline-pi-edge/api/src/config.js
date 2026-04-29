const path = require('path');

function asBool(value, fallback = false) {
  if (value === undefined || value === null || value === '') return fallback;
  return ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase());
}

function asNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

const rootDir = path.resolve(__dirname, '..', '..');
const sharedDir = path.resolve(rootDir, 'shared');

module.exports = {
  nodeEnv: process.env.NODE_ENV || 'development',
  port: asNumber(process.env.PORT, 8000),
  piPublicBaseUrl: process.env.PI_PUBLIC_BASE_URL || '',
  deviceApiBaseUrl: process.env.DEVICE_API_BASE_URL || '',
  cameraUrl: process.env.CAMERA_URL || '',
  streamType: process.env.STREAM_TYPE || 'hls',
  streamInputUrl: process.env.STREAM_INPUT_URL || process.env.SOURCE_RTSP_URL || '',
  sourceRtspUrl: process.env.SOURCE_RTSP_URL || '',
  streamPathName: process.env.STREAM_PATH_NAME || 'main',
  streamHealthTimeoutMs: asNumber(process.env.STREAM_HEALTH_TIMEOUT_MS, 15000),
  deviceAdminToken: process.env.DEVICE_ADMIN_TOKEN || '',
  centralSyncEnabled: asBool(process.env.CENTRAL_SYNC_ENABLED, true),
  centralSyncIntervalMs: asNumber(process.env.CENTRAL_SYNC_INTERVAL_MS, 15000),
  heartbeatEnabled: asBool(process.env.HEARTBEAT_ENABLED, true),
  heartbeatIntervalMs: asNumber(process.env.HEARTBEAT_INTERVAL_MS, 10000),
  heatlineRegistryApiBase: process.env.HEATLINE_REGISTRY_API_BASE || '',
  heatlineControllerId: asNumber(process.env.HEATLINE_CONTROLLER_ID, 0),
  heatlineDeviceToken: process.env.HEATLINE_DEVICE_TOKEN || '',
  aiEnabled: asBool(process.env.AI_ENABLED, true),
  aiModelName: process.env.AI_MODEL_NAME || 'snow-binary-v1.hef',
  aiSampleFps: asNumber(process.env.AI_SAMPLE_FPS, 2),
  statusFile: path.resolve(rootDir, process.env.STATUS_FILE || './shared/state/device-status.json'),
  eventsFile: path.resolve(rootDir, process.env.EVENTS_FILE || './shared/state/events.json'),
  controlLogsFile: path.resolve(rootDir, process.env.CONTROL_LOGS_FILE || './shared/state/control-logs.json'),
  sharedDir
};
