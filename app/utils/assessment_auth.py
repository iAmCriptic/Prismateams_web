from functools import wraps

from flask import abort, current_app, flash, redirect, request, url_for
from flask_login import current_user

from app.models.assessment import AssessmentUser
from app.utils.access_control import has_module_access


SECTION_ROLE_MAP = {
    "home": {"Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"},
    "evaluate": {"Administrator", "Bewerter"},
    "my_evaluations": {"Administrator", "Bewerter", "Betrachter"},
    "print_blank": {"Administrator", "Bewerter", "Betrachter"},
    "ranking": {"Administrator", "Bewerter", "Betrachter"},
    "inspections": {"Administrator", "Inspektor"},
    "warnings": {"Administrator", "Verwarner"},
    "admin": {"Administrator"},
}

VALID_ASSESSMENT_ROLES = frozenset(
    {"Administrator", "Bewerter", "Betrachter", "Inspektor", "Verwarner"}
)
# Non-admin portal users may never escalate to Assessment-Administrator via config.
PORTAL_NON_ADMIN_ALLOWED_ROLES = VALID_ASSESSMENT_ROLES - {"Administrator"}
DEFAULT_PORTAL_NON_ADMIN_ROLES = ["Bewerter"]


def is_assessment_user():
    return isinstance(current_user, AssessmentUser)


def _parse_role_list(raw_value):
    """Parse comma/semicolon/whitespace-separated role names."""
    if raw_value is None:
        return []
    if isinstance(raw_value, (list, tuple, set)):
        parts = list(raw_value)
    else:
        text = str(raw_value).replace(";", ",").replace("|", ",")
        parts = [p.strip() for p in text.split(",")]
    roles = []
    for part in parts:
        if part in VALID_ASSESSMENT_ROLES and part not in roles:
            roles.append(part)
    return roles


def get_portal_assessment_roles(user):
    """
    Assessment roles for a Teamportal user with module_assessment access.

    Least privilege:
    - Portal admins / super-admins → Administrator
    - Other portal users → ASSESSMENT_PORTAL_DEFAULT_ROLES (default: Bewerter),
      never Administrator (cannot be escalated via env/setting)
    """
    if getattr(user, "is_super_admin", False) or getattr(user, "is_admin", False):
        return ["Administrator"]

    raw = current_app.config.get("ASSESSMENT_PORTAL_DEFAULT_ROLES")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        try:
            from app.blueprints.assessment.helpers import get_setting

            raw = get_setting("portal_default_roles", "Bewerter")
        except Exception:
            raw = "Bewerter"

    roles = [
        role
        for role in _parse_role_list(raw)
        if role in PORTAL_NON_ADMIN_ALLOWED_ROLES
    ]
    return roles or list(DEFAULT_PORTAL_NON_ADMIN_ROLES)


def get_assessment_identity():
    if not current_user.is_authenticated:
        return None, None, []

    if is_assessment_user():
        return "ass", current_user.id, current_user.role_names

    if has_module_access(current_user, "module_assessment"):
        return "portal", current_user.id, get_portal_assessment_roles(current_user)

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
