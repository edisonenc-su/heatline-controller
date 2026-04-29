const express = require('express');
const { listControlLogs } = require('../services/control-log-store');
const { success } = require('../utils/response');

const router = express.Router();

router.get('/', async (req, res, next) => {
  try {
    const limit = Math.min(Number(req.query.limit || 10), 100);
    return success(res, { items: await listControlLogs(limit) });
  } catch (error) {
    next(error);
  }
});

module.exports = router;
