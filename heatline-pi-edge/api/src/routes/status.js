const express = require('express');
const { getStatusResponse, patchState } = require('../services/device-state');
const { success } = require('../utils/response');
const { requireDeviceAdmin } = require('../services/auth');

const router = express.Router();

router.get('/', async (req, res, next) => {
  try {
    return success(res, await getStatusResponse());
  } catch (error) {
    next(error);
  }
});

router.put('/', requireDeviceAdmin, async (req, res, next) => {
  try {
    const updated = await patchState({ ...(req.body || {}) });
    return success(res, updated);
  } catch (error) {
    next(error);
  }
});

module.exports = router;
