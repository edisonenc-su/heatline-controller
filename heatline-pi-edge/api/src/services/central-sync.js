const config = require('../config');
const { loadState, getStatusResponse } = require('./device-state');

function getCentralSyncPayload(status) {
  return {
    status: status.status || 'online',
    snow_detected: !!status.snow_detected,
    heater_on: !!status.heater_on,
    temperature: status.temperature,
    humidity: status.humidity,
    heater_mode: status.heater_mode || 'auto',
    snow_threshold: status.snow_threshold ?? 0.8,
    last_seen_at: status.last_seen_at,
    camera_url: status.camera_url,
    playback_url: status.playback_url,
    device_api_base: status.device_api_base,
    public_base_url: status.public_base_url,
    stream_type: status.stream_type,
    firmware_version: null,
    hardware_model: 'rpi5-hailo'
  };
}

async function syncToCentral() {
  if (!config.centralSyncEnabled) return { skipped: true, reason: 'CENTRAL_SYNC_DISABLED' };
  if (!config.heatlineRegistryApiBase || !config.heatlineControllerId || !config.heatlineDeviceToken) {
    return { skipped: true, reason: 'CENTRAL_SYNC_CONFIG_MISSING' };
  }

  const status = await getStatusResponse(await loadState());
  const url = `${config.heatlineRegistryApiBase}/controllers/${config.heatlineControllerId}/status`;
  const response = await fetch(url, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${config.heatlineDeviceToken}`
    },
    body: JSON.stringify(getCentralSyncPayload(status))
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) {
    throw new Error(data?.error?.message || data?.message || `중앙 동기화 실패 (${response.status})`);
  }

  return { skipped: false, url, data };
}

function startCentralSyncLoop(logger = console) {
  if (!config.centralSyncEnabled) return null;
  const run = async () => {
    try {
      const result = await syncToCentral();
      if (!result.skipped) logger.log('[central-sync] synced');
    } catch (error) {
      logger.error('[central-sync] failed:', error.message);
    }
  };
  run();
  return setInterval(run, config.centralSyncIntervalMs);
}

module.exports = { getCentralSyncPayload, syncToCentral, startCentralSyncLoop };
