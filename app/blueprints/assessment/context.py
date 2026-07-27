from datetime import datetime

from flask import request, url_for

from app.models.assessment import AssessmentAppSetting
from app.utils.assessment_auth import accessible_sections, get_assessment_identity


def _load_settings():
    data = {s.setting_key: s.setting_value for s in AssessmentAppSetting.query.all()}
    data.setdefault("welcome_title", "Willkommen im Bewertungstool")
    data.setdefault("welcome_subtitle", "Bewerten, Ranglisten und Verwaltung.")
    data.setdefault("ranking_active_mode", "standard")
    data.setdefault("ranking_sort_mode", "total")
    return data


def _print_url_for_endpoint(endpoint):
    """Kontextabhängige PDF-URL je Tab."""
    try:
        if endpoint == "assessment.evaluations.evaluate_page":
            return url_for("assessment.evaluations.pdf_blank")
        if endpoint == "assessment.evaluations.view_my_evaluations_page":
            return url_for("assessment.evaluations.pdf_blank")
        if endpoint == "assessment.ranking.view_ranking":
            return url_for("assessment.ranking.pdf_ranking")
        if endpoint == "assessment.inspections.room_inspections_page":
            return url_for("assessment.inspections.pdf_inspections")
        if endpoint == "assessment.warnings.warnings_page":
            return url_for("assessment.warnings.pdf_warnings")
        return url_for("assessment.evaluations.pdf_blank")
    except Exception:
        return "/assessment/pdf/blank"


def inject_assessment_context():
    user_type, user_id, roles = get_assessment_identity()
    sections = accessible_sections(roles)

    try:
        settings = _load_settings()
    except Exception:
        settings = {
            "welcome_title": "Willkommen im Bewertungstool",
            "welcome_subtitle": "Bewerten, Ranglisten und Verwaltung.",
            "ranking_active_mode": "standard",
            "ranking_sort_mode": "total",
        }

    endpoint = request.endpoint if request else None
    return {
        "assessment_roles": roles,
        "assessment_user_type": user_type,
        "assessment_sections": sections,
        "assessment_is_admin": "Administrator" in (roles or []),
        "assessment_settings": settings,
        "assessment_welcome_title": settings.get("welcome_title"),
        "assessment_welcome_subtitle": settings.get("welcome_subtitle"),
        "assessment_print_created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "assessment_print_url": _print_url_for_endpoint(endpoint),
    }
