from flask import current_app

from app.models.assessment import AssessmentAppSetting
from app.utils.assessment_auth import accessible_sections, get_assessment_identity


def _load_settings():
    data = {s.setting_key: s.setting_value for s in AssessmentAppSetting.query.all()}
    data.setdefault("welcome_title", "Bewertung")
    data.setdefault("welcome_subtitle", "Bewerten, Ranglisten und Verwaltung.")
    data.setdefault("ranking_active_mode", "standard")
    data.setdefault("ranking_sort_mode", "total")
    return data


def inject_assessment_context():
    user_type, user_id, roles = get_assessment_identity()
    sections = accessible_sections(roles)

    try:
        settings = _load_settings()
    except Exception:
        settings = {
            "welcome_title": "Bewertung",
            "welcome_subtitle": "Bewerten, Ranglisten und Verwaltung.",
            "ranking_active_mode": "standard",
            "ranking_sort_mode": "total",
        }

    return {
        "assessment_roles": roles,
        "assessment_user_type": user_type,
        "assessment_sections": sections,
        "assessment_is_admin": "Administrator" in (roles or []),
        "assessment_settings": settings,
        "assessment_welcome_title": settings.get("welcome_title"),
        "assessment_welcome_subtitle": settings.get("welcome_subtitle"),
    }
