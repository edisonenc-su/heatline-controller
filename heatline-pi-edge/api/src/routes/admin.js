const express = require('express');
const { patchState, getStatusResponse } = require('../services/device-state');
const { syncToCentral } = require('../services/central-sync');
const { requireDeviceAdmin } = require('../services/auth');
const { success } = require('../utils/response');

const router = express.Router();
router.use(requireDeviceAdmin);

router.post('/stream/reconnected', async (req, res, next) => {
  try {
    const state = await patchState({
      status: 'online',
      stream: {
        stream_health: 'connected',
        media_status: 'ready',
        media_last_seen_at: new Date().toISOString()
      }
    });
    return success(res, state, { message: '스트림 상태를 connected 로 갱신했습니다.' });
  } catch (error) {
    next(error);
  }
});

router.post('/sync-central', async (req, res, next) => {
  try {
    return success(res, await syncToCentral());
  } catch (error) {
    next(error);
  }
});

router.get('/snapshot', async (req, res, next) => {
  try {
    return success(res, await getStatusResponse());
  } catch (error) {
    next(error);
  }
});

module.exports = router;
