"""Private / Team / Public visibility for credentials, manuals, contacts, wiki, shortlinks."""

from __future__ import annotations

from flask import request

from app.models.team import Team, TeamMember
from app.utils.access_control import has_module_access
from app.utils.common import is_module_enabled
from app.utils.system_settings_cache import setting_bool as _setting_bool

VISIBILITY_PRIVATE = 'private'
VISIBILITY_TEAM = 'team'
VISIBILITY_PUBLIC = 'public'
VALID_VISIBILITIES = frozenset({VISIBILITY_PRIVATE, VISIBILITY_TEAM, VISIBILITY_PUBLIC})
VALID_SECTIONS = frozenset({'all', 'favorites', 'private', 'team', 'public'})

MODULE_KEYS = {
    'credentials': 'module_credentials',
    'manuals': 'module_manuals',
    'contacts': 'module_contacts',
    'wiki': 'module_wiki',
    'shortlinks': 'module_shortlinks',
    'excalidraw': 'module_excalidraw',
    'surveys': 'module_surveys',
    'protocols': 'module_protocols',
}

OWNER_ATTRS = {
    'credentials': 'created_by',
    'manuals': 'uploaded_by',
    'contacts': 'created_by',
    'wiki': 'created_by',
    'shortlinks': 'created_by',
    'excalidraw': 'created_by',
    'surveys': 'created_by',
    'protocols': 'created_by',
}

DEFAULT_VISIBILITY = {
    'credentials': VISIBILITY_PRIVATE,
    'manuals': VISIBILITY_PUBLIC,
    'contacts': VISIBILITY_PUBLIC,
    'wiki': VISIBILITY_PUBLIC,
    'shortlinks': VISIBILITY_PRIVATE,
    'excalidraw': VISIBILITY_PUBLIC,
    'surveys': VISIBILITY_PRIVATE,
    'protocols': VISIBILITY_PUBLIC,
}

# Modules that never support private items (team/public only).
NO_PRIVATE_MODULES = frozenset({'protocols'})


def setting_key(module: str, kind: str) -> str:
    return f'{module}_allow_{kind}'


def _fallback_visibility(module: str) -> str:
    allowed = get_allowed_visibilities(module)
    if allowed:
        return allowed[0]
    if module in NO_PRIVATE_MODULES:
        return VISIBILITY_PUBLIC
    return VISIBILITY_PRIVATE


def get_allowed_visibilities(module: str, user=None) -> list[str]:
    from app.utils.module_visibility_settings import (
        is_global_private_enabled,
        is_global_public_enabled,
        is_global_team_enabled,
    )
    from app.utils.user_content_access import filter_visibilities_for_user

    allowed = []
    allow_private = module not in NO_PRIVATE_MODULES
    if (
        allow_private
        and is_global_private_enabled()
        and _setting_bool(setting_key(module, 'private'), True)
    ):
        allowed.append(VISIBILITY_PRIVATE)
    if is_global_team_enabled() and _setting_bool(setting_key(module, 'team'), True):
        allowed.append(VISIBILITY_TEAM)
    if is_global_public_enabled() and _setting_bool(setting_key(module, 'public'), True):
        allowed.append(VISIBILITY_PUBLIC)
    if not allowed:
        if module in NO_PRIVATE_MODULES:
            allowed = [VISIBILITY_PUBLIC]
        else:
            allowed = [VISIBILITY_PRIVATE]
    if user is not None:
        allowed = filter_visibilities_for_user(allowed, user)
        if not allowed:
            # Team-only users with no team section still need a non-empty list for forms
            if is_global_team_enabled() and _setting_bool(setting_key(module, 'team'), True):
                return [VISIBILITY_TEAM]
            return []
    return allowed


def visibility_allowed(module: str, visibility: str, user=None) -> bool:
    return visibility in get_allowed_visibilities(module, user)


def user_team_ids(user) -> set[int]:
    if not user or not getattr(user, 'id', None):
        return set()
    return {m.team_id for m in TeamMember.query.filter_by(user_id=user.id).all()}


def user_visibility_teams(user, module: str):
    """Teams shown as sidebar folders (members; admins see all)."""
    from app.utils.team_module_settings import filter_teams_with_section

    if VISIBILITY_TEAM not in get_allowed_visibilities(module, user) or not user:
        return []
    if getattr(user, 'is_guest', False):
        return []
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        teams = Team.query.order_by(Team.name).all()
    else:
        team_ids = list(user_team_ids(user))
        if not team_ids:
            return []
        teams = Team.query.filter(Team.id.in_(team_ids)).order_by(Team.name).all()
    return filter_teams_with_section(teams, module)


def user_may_use_team(user, module: str, team_id) -> bool:
    if not team_id:
        return False
    try:
        team_id = int(team_id)
    except (TypeError, ValueError):
        return False
    return any(t.id == team_id for t in user_visibility_teams(user, module))


def owner_id(item, module: str):
    return getattr(item, OWNER_ATTRS[module], None)


def _item_visibility(item) -> str:
    raw = (getattr(item, 'visibility', None) or VISIBILITY_PUBLIC).strip().lower()
    return raw if raw in VALID_VISIBILITIES else VISIBILITY_PUBLIC


def can_view_item(user, item, module: str) -> bool:
    if not user or not item:
        return False
    module_key = MODULE_KEYS.get(module)
    if module_key and (not is_module_enabled(module_key) or not has_module_access(user, module_key)):
        return False
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return True

    allowed = set(get_allowed_visibilities(module, user))
    vis = _item_visibility(item)

    if owner_id(item, module) == getattr(user, 'id', None):
        # Owner bypass only for visibilities the user may access
        return vis in allowed

    if vis == VISIBILITY_PUBLIC and VISIBILITY_PUBLIC in allowed:
        return True
    if (
        vis == VISIBILITY_TEAM
        and VISIBILITY_TEAM in allowed
        and getattr(item, 'team_id', None)
        and item.team_id in user_team_ids(user)
    ):
        return True
    return False


def can_edit_item(user, item, module: str) -> bool:
    if not can_view_item(user, item, module):
        return False
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return True
    if owner_id(item, module) == getattr(user, 'id', None):
        return True
    # Credentials: nur Owner/Admin dürfen ändern (kein Public-/Team-Edit)
    if module == 'credentials':
        return False
    vis = _item_visibility(item)
    allowed = set(get_allowed_visibilities(module, user))
    if vis == VISIBILITY_TEAM and getattr(item, 'team_id', None) and item.team_id in user_team_ids(user):
        return VISIBILITY_TEAM in allowed
    if vis == VISIBILITY_PUBLIC and VISIBILITY_PUBLIC in allowed:
        return True
    return False


def accessible_query(user, model, module: str):
    """Return SQLAlchemy query of items the user can see."""
    from app import db
    from sqlalchemy import and_, or_

    q = model.query
    if getattr(user, 'is_admin', False) or getattr(user, 'has_full_access', False):
        return q

    owner_col = getattr(model, OWNER_ATTRS[module])
    vis_col = model.visibility
    team_col = model.team_id
    team_ids = list(user_team_ids(user))
    allowed = set(get_allowed_visibilities(module, user))

    clauses = []
    # Own items only for visibilities the user may access
    for vis in allowed:
        if vis == VISIBILITY_PRIVATE:
            clauses.append(and_(owner_col == user.id, vis_col == VISIBILITY_PRIVATE))
        elif vis == VISIBILITY_PUBLIC:
            clauses.append(and_(owner_col == user.id, vis_col == VISIBILITY_PUBLIC))
        elif vis == VISIBILITY_TEAM:
            clauses.append(and_(owner_col == user.id, vis_col == VISIBILITY_TEAM))

    if VISIBILITY_PUBLIC in allowed:
        clauses.append(vis_col == VISIBILITY_PUBLIC)
    if VISIBILITY_TEAM in allowed and team_ids:
        clauses.append(and_(vis_col == VISIBILITY_TEAM, team_col.in_(team_ids)))

    if not clauses:
        return q.filter(db.false())
    return q.filter(or_(*clauses))


def parse_visibility_value(raw, module: str, user=None):
    """Parse form value `private`, `public`, or `team:{id}` into (visibility, team_id)."""
    value = (raw or '').strip().lower()
    team_id = None
    visibility = DEFAULT_VISIBILITY.get(module, VISIBILITY_PUBLIC)

    if value.startswith('team:'):
        try:
            team_id = int(value.split(':', 1)[1])
        except (TypeError, ValueError, IndexError):
            team_id = None
        visibility = VISIBILITY_TEAM
    elif value in VALID_VISIBILITIES:
        visibility = value

    if not visibility_allowed(module, visibility, user):
        visibility = _fallback_visibility_for_user(module, user)
        team_id = None

    if visibility == VISIBILITY_TEAM:
        if user is not None and not user_may_use_team(user, module, team_id):
            visibility = _fallback_visibility_for_user(module, user)
            team_id = None
        elif not team_id:
            visibility = _fallback_visibility_for_user(module, user)
            team_id = None
    else:
        team_id = None

    return visibility, team_id


def _fallback_visibility_for_user(module: str, user=None) -> str:
    allowed = get_allowed_visibilities(module, user)
    if allowed:
        return allowed[0]
    return _fallback_visibility(module)


def parse_section_args(module: str, user=None):
    """Read view/section + team_id from the current request."""
    view = (request.args.get('view') or '').strip().lower()
    section = (request.args.get('section') or '').strip().lower()
    raw = view or section or 'all'
    if raw not in VALID_SECTIONS:
        raw = 'all'

    allowed = set(get_allowed_visibilities(module, user))
    if raw == 'private' and VISIBILITY_PRIVATE not in allowed:
        raw = 'all'
    if raw == 'public' and VISIBILITY_PUBLIC not in allowed:
        raw = 'all'
    if raw == 'team' and VISIBILITY_TEAM not in allowed:
        raw = 'all'

    filter_team_id = None
    if raw == 'team':
        try:
            filter_team_id = int(request.args.get('team_id') or 0) or None
        except (TypeError, ValueError):
            filter_team_id = None
        if user is not None and not user_may_use_team(user, module, filter_team_id):
            raw = 'all'
            filter_team_id = None
        elif not filter_team_id:
            raw = 'all'

    return raw, filter_team_id


def apply_section_filter(query, model, section: str, filter_team_id=None):
    if section == 'private':
        return query.filter(model.visibility == VISIBILITY_PRIVATE)
    if section == 'public':
        return query.filter(model.visibility == VISIBILITY_PUBLIC)
    if section == 'team' and filter_team_id:
        return query.filter(model.visibility == VISIBILITY_TEAM, model.team_id == filter_team_id)
    return query


def visibility_nav_context(module: str, user, section: str = 'all', filter_team_id=None):
    allowed = get_allowed_visibilities(module, user)
    teams = user_visibility_teams(user, module)
    if section == 'team' and filter_team_id:
        active_nav = f'team-{filter_team_id}'
    else:
        active_nav = section
    return {
        'allowed_visibilities': allowed,
        'visibility_teams': teams,
        'section_filter': section,
        'filter_team_id': filter_team_id,
        'active_nav': active_nav,
        'visibility_module': module,
    }


def apply_visibility_from_form(item, module: str, user, raw=None):
    raw = raw if raw is not None else request.form.get('visibility')
    vis, team_id = parse_visibility_value(raw, module, user)
    item.visibility = vis
    item.team_id = team_id
    return vis, team_id


def visibility_form_context(module: str, user, item=None, preselect_section=None, preselect_team_id=None):
    allowed = get_allowed_visibilities(module, user)
    teams = user_visibility_teams(user, module)
    selected = None
    if item is not None:
        vis = _item_visibility(item)
        if vis == VISIBILITY_TEAM and getattr(item, 'team_id', None):
            selected = f'team:{item.team_id}'
        else:
            selected = vis
    elif preselect_section == 'team' and preselect_team_id:
        selected = f'team:{preselect_team_id}'
    elif preselect_section in (VISIBILITY_PRIVATE, VISIBILITY_PUBLIC):
        selected = preselect_section
    if not selected:
        if VISIBILITY_PUBLIC in allowed:
            selected = VISIBILITY_PUBLIC
        elif VISIBILITY_PRIVATE in allowed:
            selected = VISIBILITY_PRIVATE
        elif teams:
            selected = f'team:{teams[0].id}'
        else:
            selected = allowed[0] if allowed else VISIBILITY_PRIVATE
        if module in ('shortlinks', 'credentials') and VISIBILITY_PRIVATE in allowed:
            selected = VISIBILITY_PRIVATE
    return {
        'allowed_visibilities': allowed,
        'visibility_teams': teams,
        'selected_visibility': selected,
        'visibility_module': module,
    }
