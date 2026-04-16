import hashlib
import uuid
from datetime import datetime

from flask import current_app, request

from app.models.assessment import AssessmentAppSetting
from app.utils.assessment_auth import get_assessment_identity


def current_actor():
    user_type, user_id, roles = get_assessment_identity()
    return {"user_type": user_type, "user_id": user_id, "roles": roles}


def get_setting(key, default_value=None):
    entry = AssessmentAppSetting.query.filter_by(setting_key=key).first()
    if not entry or entry.setting_value is None:
        return default_value
    return entry.setting_value


def set_setting(key, value):
    entry = AssessmentAppSetting.query.filter_by(setting_key=key).first()
    if not entry:
        entry = AssessmentAppSetting(setting_key=key, setting_value=str(value))
    else:
        entry.setting_value = str(value)
    return entry


def create_visitor_token():
    token = request.cookies.get("assessment_visitor_id")
    if token:
        return token, False
    return str(uuid.uuid4()), True


def hash_visitor_token(raw_token):
    secret = current_app.config.get("SECRET_KEY", "assessment-default-secret")
    return hashlib.sha256(f"{secret}|{raw_token}".encode("utf-8")).hexdigest()


def utcnow():
    return datetime.utcnow()
