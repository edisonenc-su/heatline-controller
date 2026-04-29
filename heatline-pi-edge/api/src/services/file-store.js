const fs = require('fs/promises');
const path = require('path');

async function ensureJsonFile(filePath, defaultValue) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  try {
    await fs.access(filePath);
  } catch (_) {
    await fs.writeFile(filePath, JSON.stringify(defaultValue, null, 2));
  }
}

async function readJson(filePath, defaultValue) {
  await ensureJsonFile(filePath, defaultValue);
  try {
    const raw = await fs.readFile(filePath, 'utf8');
    return raw ? JSON.parse(raw) : defaultValue;
  } catch (_) {
    return defaultValue;
  }
}

async function writeJson(filePath, value) {
  await ensureJsonFile(filePath, value);
  await fs.writeFile(filePath, JSON.stringify(value, null, 2));
}

module.exports = { ensureJsonFile, readJson, writeJson };
