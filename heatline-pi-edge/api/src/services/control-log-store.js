const config = require('../config');
const { readJson, writeJson } = require('./file-store');
const { nowIso } = require('../utils/time');

async function listControlLogs(limit = 10) {
  const items = await readJson(config.controlLogsFile, []);
  return items.slice(0, limit);
}

async function addControlLog(log = {}) {
  const current = await readJson(config.controlLogsFile, []);
  const entry = {
    id: `ctl_${Date.now()}`,
    command_type: log.command_type,
    command_value: log.command_value ?? null,
    result: log.result || 'success',
    note: log.note || '',
    requested_by: log.requested_by || null,
    requested_at: log.requested_at || nowIso(),
    finished_at: log.finished_at || nowIso(),
    created_at: nowIso()
  };
  const next = [entry, ...current].slice(0, 200);
  await writeJson(config.controlLogsFile, next);
  return entry;
}

module.exports = { listControlLogs, addControlLog };
