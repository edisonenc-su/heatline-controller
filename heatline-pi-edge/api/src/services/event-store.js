const config = require('../config');
const { readJson, writeJson } = require('./file-store');
const { nowIso } = require('../utils/time');

async function listEvents(limit = 10) {
  const items = await readJson(config.eventsFile, []);
  return items.slice(0, limit);
}

async function addEvent({ event_type, message = '', severity = 'info', payload = null } = {}) {
  const current = await readJson(config.eventsFile, []);
  const event = {
    id: `evt_${Date.now()}`,
    event_type,
    message,
    severity,
    payload_json: payload,
    created_at: nowIso()
  };
  const next = [event, ...current].slice(0, 200);
  await writeJson(config.eventsFile, next);
  return event;
}

module.exports = { listEvents, addEvent };
