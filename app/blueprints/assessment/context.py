from flask import current_app, session, url_for

from app.models.assessment import AssessmentAppSetting
from app.utils.assessment_auth import accessible_sections, get_assessment_identity, is_assessment_user


def _load_settings():
    data = {s.setting_key: s.setting_value for s in AssessmentAppSetting.query.all()}
    data.setdefault("welcome_title", "Willkommen im Bewertungstool")
    data.setdefault("welcome_subtitle", "Bewerten, Ränge prüfen und Verwaltung – alles an einem Ort.")
    data.setdefault("module_label", "Bewertung")
    data.setdefault("ranking_active_mode", "standard")
    data.setdefault("ranking_sort_mode", "total")
    data.setdefault("logo_url", "")
    return data


def inject_assessment_context():
    user_type, user_id, roles = get_assessment_identity()
    sections = accessible_sections(roles)

    try:
        settings = _load_settings()
    except Exception:
        settings = {
            "welcome_title": "Willkommen im Bewertungstool",
            "welcome_subtitle": "Bewerten, Ränge prüfen und Verwaltung – alles an einem Ort.",
            "module_label": "Bewertung",
            "logo_url": "",
            "ranking_active_mode": "standard",
            "ranking_sort_mode": "total",
        }

    logo_url = settings.get("logo_url") or ""
    theme_mode = "light"
    if is_assessment_user():
        theme_mode = getattr(__import__("flask_login", fromlist=["current_user"]).current_user, "theme_mode", "light")
    else:
        theme_mode = session.get("user_scope_theme_mode") or theme_mode

    portal_name = None
    try:
        from app.models.settings import SystemSettings

        portal_name_setting = SystemSettings.query.filter_by(key="portal_name").first()
        if portal_name_setting and portal_name_setting.value:
            portal_name = portal_name_setting.value
    except Exception:
        portal_name = None
    portal_name = portal_name or current_app.config.get("APP_NAME", "Prismateams")

    return {
        "assessment_roles": roles,
        "assessment_user_type": user_type,
        "assessment_sections": sections,
        "assessment_is_admin": "Administrator" in (roles or []),
        "assessment_settings": settings,
        "assessment_logo_url": logo_url,
        "assessment_theme_mode": theme_mode,
        "assessment_portal_name": portal_name,
        "assessment_welcome_title": settings.get("welcome_title"),
        "assessment_welcome_subtitle": settings.get("welcome_subtitle"),
        "assessment_module_label": settings.get("module_label"),
    }
