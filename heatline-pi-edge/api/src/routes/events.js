const express = require('express');
const { listEvents, addEvent } = require('../services/event-store');
const { success } = require('../utils/response');
const { requireDeviceAdmin } = require('../services/auth');

const router = express.Router();

router.get('/', async (req, res, next) => {
  try {
    const limit = Math.min(Number(req.query.limit || 10), 100);
    return success(res, { items: await listEvents(limit) });
  } catch (error) {
    next(error);
  }
});

router.post('/', requireDeviceAdmin, async (req, res, next) => {
  try {
    return success(res, await addEvent(req.body || {}), {}, 201);
  } catch (error) {
    next(error);
  }
});

module.exports = router;
