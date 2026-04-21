import uuid

from flask import jsonify


def api_error(code, message, status=400, details=None):
    trace_id = str(uuid.uuid4())
    payload = {
        "code": code,
        "message": message,
        "trace_id": trace_id,
    }
    if details is not None:
        payload["details"] = details
    return jsonify(payload), status


def api_ok(data=None, status=200):
    payload = {"ok": True}
    if data:
        payload.update(data)
    return jsonify(payload), status
