"""Per-user Public / Private content access (team-only users)."""

from __future__ import annotations

VISIBILITY_PRIVATE = 'private'
VISIBILITY_TEAM = 'team'
VISIBILITY_PUBLIC = 'public'


def user_bypasses_content_restrictions(user) -> bool:
    if not user:
        return False
    return bool(getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False))


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
        return True
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


def user_may_access_private(user) -> bool:
    return user_may_access_visibility(user, VISIBILITY_PRIVATE)
