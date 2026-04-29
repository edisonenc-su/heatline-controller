const express = require('express');
const { executeCommand } = require('../services/command-executor');
const { success } = require('../utils/response');

const router = express.Router();

router.post('/', async (req, res, next) => {
  try {
    const requested_by = {
      user_id: req.header('x-user-id') || null,
      user_name: req.header('x-user-name') || null,
      role: req.header('x-user-role') || 'guest'
    };
    const result = await executeCommand({ ...(req.body || {}), requested_by });
    return success(res, result, { message: '명령을 수락했습니다.' }, 201);
  } catch (error) {
    next(error);
  }
});

module.exports = router;
