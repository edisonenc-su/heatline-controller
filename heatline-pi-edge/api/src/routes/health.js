const express = require('express');
const { getStatusResponse } = require('../services/device-state');
const { success } = require('../utils/response');

const router = express.Router();

router.get('/', async (req, res, next) => {
  try {
    const status = await getStatusResponse();
    return success(res, {
      ok: true,
      stream_process: status.stream_health === 'connected' ? 'running' : 'degraded',
      inference_process: status.ai_status,
      camera_source: status.media_status,
      last_inference_at: status.ai_last_inference_at,
      last_seen_at: status.last_seen_at
    });
  } catch (error) {
    next(error);
  }
});

module.exports = router;
