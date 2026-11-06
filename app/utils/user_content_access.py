"""Per-user Public / Team / Private content access (team-only users)."""

from __future__ import annotations

VISIBILITY_PRIVATE = 'private'
VISIBILITY_TEAM = 'team'
VISIBILITY_PUBLIC = 'public'


def user_bypasses_content_restrictions(user) -> bool:
    if not user:
        return False
    return bool(getattr(user, 'is_super_admin', False) or getattr(user, 'is_admin', False))


def user_may_access_visibility(user, visibility: str) -> bool:
    """Whether the user may use/see a content visibility (public/private/team)."""
    if not user:
        return False
    if user_bypasses_content_restrictions(user):
        return True
    vis = (visibility or '').strip().lower()
    if vis == VISIBILITY_PUBLIC:
        return bool(getattr(user, 'can_access_public', True))
    if vis == VISIBILITY_PRIVATE:
        return bool(getattr(user, 'can_access_private', True))
    if vis == VISIBILITY_TEAM:
        return bool(getattr(user, 'can_access_team', True))
    # Files/calendar aliases
    if vis == 'personal':
        return bool(getattr(user, 'can_access_private', True))
    return True


def filter_visibilities_for_user(allowed, user) -> list:
    """Intersect system-allowed visibilities with per-user flags."""
    if not allowed:
        return []
    if not user or user_bypasses_content_restrictions(user):
        return list(allowed)
    return [v for v in allowed if user_may_access_visibility(user, v)]


def user_may_access_public(user) -> bool:
    return user_may_access_visibility(user, VISIBILITY_PUBLIC)


def user_may_access_team(user) -> bool:
    return user_may_access_visibility(user, VISIBILITY_TEAM)


def user_may_access_private(user) -> bool:
    return user_may_access_visibility(user, VISIBILITY_PRIVATE)


def user_has_any_content_scope(user, module_key: str) -> bool:
    """
    Checks whether a user has access to at least one content space
    (Public, Team, Private) for a scope-based module.
    If a user has no access to any scope, the module is effectively inaccessible.
    """
    if not user:
        return False
    if user_bypasses_content_restrictions(user):
        return True

    mod = (module_key or '').lower()
    if mod.startswith('module_'):
        mod_short = mod[7:]
    else:
        mod_short = mod

    # Scope-based modules
    from app.utils.module_visibility_settings import (
        is_global_public_enabled,
        is_global_team_enabled,
        is_global_private_enabled,
    )
    from app.utils.system_settings_cache import setting_bool

    # Helper to check if user belongs to at least one team
    def _user_has_teams() -> bool:
        user_id = getattr(user, 'id', None)
        if not user_id:
            return False
        from app.models.team import TeamMember
        return TeamMember.query.filter_by(user_id=user_id).first() is not None

    if mod_short == 'files':
        from app.utils.private_files import (
            is_public_folders_enabled,
            is_team_folders_enabled,
            is_private_folders_enabled,
        )
        pub_ok = is_public_folders_enabled() and user_may_access_public(user)
        team_ok = is_team_folders_enabled() and user_may_access_team(user) and _user_has_teams()
        priv_ok = is_private_folders_enabled() and user_may_access_private(user)
        return pub_ok or team_ok or priv_ok

    if mod_short == 'calendar':
        from app.utils.multi_calendars import (
            is_calendar_multi_enabled,
            is_calendar_team_enabled,
            is_calendar_personal_enabled,
        )
        pub_ok = is_calendar_multi_enabled() and user_may_access_public(user)
        team_ok = is_calendar_team_enabled() and user_may_access_team(user) and _user_has_teams()
        priv_ok = is_calendar_personal_enabled() and user_may_access_private(user)
        return pub_ok or team_ok or priv_ok

    if mod_short == 'kanban':
        from app.utils.kanban_access import get_allowed_visibilities as get_kanban_vis
        allowed = get_kanban_vis(user)
        if not allowed:
            return False
        if allowed == [VISIBILITY_TEAM] and not _user_has_teams():
            return False
        return True

    if mod_short == 'duty_roster':
        from app.blueprints.duty_roster import _allowed_sections
        sections = _allowed_sections(user)
        if not sections:
            return False
        if sections == ['team'] and not _user_has_teams():
            return False
        return True

    # Generic scope modules: credentials, manuals, contacts, wiki, shortlinks, excalidraw, surveys, protocols
    from app.utils.module_visibility import MODULE_KEYS, NO_PRIVATE_MODULES
    if mod_short in MODULE_KEYS or mod_short in MODULE_KEYS.values():
        key_name = mod_short if mod_short in MODULE_KEYS else [k for k, v in MODULE_KEYS.items() if v == mod_short][0]
        pub_ok = is_global_public_enabled() and setting_bool(f'{key_name}_allow_public', True) and user_may_access_public(user)
        team_ok = is_global_team_enabled() and setting_bool(f'{key_name}_allow_team', True) and user_may_access_team(user) and _user_has_teams()
        priv_ok = (key_name not in NO_PRIVATE_MODULES) and is_global_private_enabled() and setting_bool(f'{key_name}_allow_private', True) and user_may_access_private(user)
        return pub_ok or team_ok or priv_ok

    # Non-scope modules (chat, email, inventory, etc.) are governed solely by module roles
    return True
