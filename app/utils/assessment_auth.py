from functools import wraps

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user

from app.models.assessment import AssessmentUser
from app.utils.access_control import has_module_access


SECTION_ROLE_MAP = {
    "home": {"Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"},
    "evaluate": {"Administrator", "Bewerter"},
    "my_evaluations": {"Administrator", "Bewerter", "Betrachter"},
    "print_blank": {"Administrator", "Bewerter", "Betrachter"},
    "ranking": {"Administrator", "Bewerter", "Betrachter"},
    "map_view": {"Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"},
    "inspections": {"Administrator", "Inspektor"},
    "warnings": {"Administrator", "Verwarner"},
    "admin": {"Administrator"},
}


def is_assessment_user():
    return isinstance(current_user, AssessmentUser)


def get_assessment_identity():
    if not current_user.is_authenticated:
        return None, None, []

    if is_assessment_user():
        return "ass", current_user.id, current_user.role_names

    if has_module_access(current_user, "module_assessment"):
        # Teamportal-Freischaltung fuer das Bewertungsmodul bedeutet immer Vollzugriff.
        # Dadurch ist kein separates Assessment-Passwort/-Rollenset notwendig.
        return "portal", current_user.id, ["Administrator"]

    return None, None, []


def has_section_access(section, roles=None):
    if roles is None:
        _, _, roles = get_assessment_identity()
    if not roles:
        return False
    if "Administrator" in roles:
        return True
    return bool(SECTION_ROLE_MAP.get(section, set()) & set(roles))


def accessible_sections(roles=None):
    if roles is None:
        _, _, roles = get_assessment_identity()
    return [section for section in SECTION_ROLE_MAP if has_section_access(section, roles)]


def assessment_role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            user_type, user_id, roles = get_assessment_identity()
            if not user_id:
                if request.path.startswith("/assessment/api/"):
                    abort(401)
                flash("Sie haben keinen Zugriff auf das Bewertungsmodul.", "warning")
                return redirect(url_for("auth.login"))

            if "Administrator" in roles:
                return f(*args, **kwargs)

            if any(role in roles for role in allowed_roles):
                return f(*args, **kwargs)

            if request.path.startswith("/assessment/api/"):
                abort(403)

            flash("Zugriff verweigert: Rolle nicht ausreichend.", "danger")
            return redirect(url_for("assessment.general.home"))

        return wrapped

    return decorator
