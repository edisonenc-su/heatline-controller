const express = require('express');
const cors = require('cors');
const config = require('./config');
const { fail } = require('./utils/response');
const { ensureJsonFile } = require('./services/file-store');
const { getDefaultState } = require('./services/device-state');
const { startCentralSyncLoop } = require('./services/central-sync');

const statusRouter = require('./routes/status');
const eventsRouter = require('./routes/events');
const controlLogsRouter = require('./routes/control-logs');
const commandsRouter = require('./routes/commands');
const healthRouter = require('./routes/health');
const adminRouter = require('./routes/admin');

async function bootstrap() {
  await ensureJsonFile(config.statusFile, getDefaultState());
  await ensureJsonFile(config.eventsFile, []);
  await ensureJsonFile(config.controlLogsFile, []);

  const app = express();
  app.use(cors());
  app.use(express.json({ limit: '1mb' }));

  app.get('/', (req, res) => {
    res.json({
      service: 'heatline-pi-edge-api',
      ok: true,
      device_api_base: config.deviceApiBaseUrl,
      camera_url: config.cameraUrl
    });
  });

  app.use('/api/v1/status', statusRouter);
  app.use('/api/v1/events', eventsRouter);
  app.use('/api/v1/control-logs', controlLogsRouter);
  app.use('/api/v1/commands', commandsRouter);
  app.use('/api/v1/health', healthRouter);
  app.use('/api/v1/admin', adminRouter);

  app.use((err, req, res, next) => {
    console.error(err);
    return fail(res, err.status || 500, err.message || '장비 API 오류', err.code || 'INTERNAL_ERROR');
  });

  app.listen(config.port, () => {
    console.log(`[heatline-pi-edge-api] listening on :${config.port}`);
  });

  startCentralSyncLoop(console);
}

bootstrap().catch((error) => {
  console.error('[bootstrap] failed:', error);
  process.exit(1);
});
