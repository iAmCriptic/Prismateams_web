"""Per-team toggles for team-scoped module sections (team leader settings)."""

from __future__ import annotations

from app.models.settings import SystemSettings
from app.models.team import TeamModuleSetting
from app.utils.common import is_module_enabled
from app.utils.module_visibility_settings import is_global_team_enabled

TEAM_SECTION_MODULES = {
    'wiki': 'module_wiki',
    'credentials': 'module_credentials',
    'manuals': 'module_manuals',
    'contacts': 'module_contacts',
    'shortlinks': 'module_shortlinks',
    'excalidraw': 'module_excalidraw',
    'surveys': 'module_surveys',
    'protocols': 'module_protocols',
    'kanban': 'module_kanban',
    'calendar': 'module_calendar',
    'files': 'module_files',
    'email': 'module_email',
    'chat': 'module_chat',
}


def _module_globally_active(module_key: str) -> bool:
    mod = TEAM_SECTION_MODULES.get(module_key)
    if not mod:
        return False
    return is_module_enabled(mod)


def is_team_section_enabled(team_id: int, module_key: str) -> bool:
    """Team section visible when globally allowed and not disabled for this team."""
    if not team_id or module_key not in TEAM_SECTION_MODULES:
        return False
    if not is_global_team_enabled():
        return False
    if not _module_globally_active(module_key):
        return False
    row = TeamModuleSetting.query.filter_by(team_id=team_id, module_key=module_key).first()
    if row is None:
        return True
    return bool(row.team_section_enabled)


def get_team_section_states(team_id: int) -> dict[str, bool]:
    states = {}
    for key in TEAM_SECTION_MODULES:
        states[key] = is_team_section_enabled(team_id, key)
    return states


def set_team_section_enabled(team_id: int, module_key: str, enabled: bool) -> None:
    if module_key not in TEAM_SECTION_MODULES:
        raise ValueError(f'Unknown team module key: {module_key}')
    row = TeamModuleSetting.query.filter_by(team_id=team_id, module_key=module_key).first()
    if row:
        row.team_section_enabled = enabled
    else:
        from app import db
        db.session.add(TeamModuleSetting(
            team_id=team_id,
            module_key=module_key,
            team_section_enabled=enabled,
        ))


def filter_teams_with_section(teams, module_key: str):
    """Filter team list to those with team section enabled for module_key."""
    return [t for t in teams if is_team_section_enabled(t.id, module_key)]
