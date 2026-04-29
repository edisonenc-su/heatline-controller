const config = require('../config');
const { fail } = require('../utils/response');

function requireDeviceAdmin(req, res, next) {
  if (!config.deviceAdminToken) return next();
  const token = req.header('x-device-admin-token') || req.query.admin_token;
  if (token !== config.deviceAdminToken) {
    return fail(res, 401, '로컬 장비 관리자 토큰이 필요합니다.', 'UNAUTHORIZED');
  }
  next();
}

module.exports = { requireDeviceAdmin };
