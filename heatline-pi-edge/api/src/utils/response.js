function success(res, data, meta = {}, status = 200) {
  return res.status(status).json({ success: true, data, meta });
}

function fail(res, status, message, code = 'ERROR', details = null) {
  return res.status(status).json({
    success: false,
    error: { code, message, details }
  });
}

module.exports = { success, fail };
