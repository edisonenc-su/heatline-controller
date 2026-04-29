const { patchState } = require('./device-state');
const { addControlLog } = require('./control-log-store');

async function executeCommand({ command_type, command_value = null, reason = '', requested_by = null } = {}) {
  if (!command_type) throw new Error('command_type 이 필요합니다.');

  if (command_type === 'HEATER_ON') {
    await patchState({ heater_on: true, current_control_source: 'remote' });
  } else if (command_type === 'HEATER_OFF') {
    await patchState({ heater_on: false, current_control_source: 'remote' });
  } else if (command_type === 'SET_MODE') {
    await patchState({ heater_mode: String(command_value || 'auto'), current_control_source: 'remote' });
  } else if (command_type === 'SET_SNOW_THRESHOLD') {
    await patchState({ snow_threshold: Number(command_value), current_control_source: 'remote' });
  } else if (command_type === 'REBOOT') {
    await patchState({ status: 'rebooting', current_control_source: 'remote' });
  }

  const log = await addControlLog({
    command_type,
    command_value,
    result: 'success',
    note: reason || 'Pi local command skeleton',
    requested_by
  });

  return {
    ok: true,
    accepted: true,
    log
  };
}

module.exports = { executeCommand };
