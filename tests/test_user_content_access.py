import pytest
from app import db
from app.models.user import User
from app.models.team import Team, TeamMember
from app.utils.user_content_access import (
    user_bypasses_content_restrictions,
    user_may_access_visibility,
    user_may_access_public,
    user_may_access_team,
    user_may_access_private,
    user_has_any_content_scope,
    filter_visibilities_for_user,
    VISIBILITY_PUBLIC,
    VISIBILITY_TEAM,
    VISIBILITY_PRIVATE,
)
from app.utils.access_control import has_module_access, apply_default_roles_to_user, load_default_module_roles
from app.utils.system_settings_cache import invalidate_system_settings_cache


def test_user_bypasses_content_restrictions():
    """Only admins and superadmins bypass content restrictions, not has_full_access."""
    admin = User(email='admin@test.com', first_name='Admin', last_name='User', password_hash='h', is_admin=True)
    super_admin = User(email='super@test.com', first_name='Super', last_name='Admin', password_hash='h', is_super_admin=True)
    full_user = User(email='full@test.com', first_name='Full', last_name='User', password_hash='h', has_full_access=True, is_admin=False)
    normal_user = User(email='normal@test.com', first_name='Normal', last_name='User', password_hash='h', has_full_access=False, is_admin=False)

    assert user_bypasses_content_restrictions(admin) is True
    assert user_bypasses_content_restrictions(super_admin) is True
    assert user_bypasses_content_restrictions(full_user) is False
    assert user_bypasses_content_restrictions(normal_user) is False


def test_user_may_access_visibility_and_flags():
    """Individual flags for public, team, and private are respected for non-admins."""
    user = User(
        email='u@test.com',
        first_name='U',
        last_name='S',
        password_hash='h',
        is_admin=False,
        has_full_access=True,
        can_access_public=False,
        can_access_team=True,
        can_access_private=True,
    )

    assert user_may_access_public(user) is False
    assert user_may_access_team(user) is True
    assert user_may_access_private(user) is True

    allowed = filter_visibilities_for_user([VISIBILITY_PUBLIC, VISIBILITY_TEAM, VISIBILITY_PRIVATE], user)
    assert allowed == [VISIBILITY_TEAM, VISIBILITY_PRIVATE]

    # Exclude team as well
    user.can_access_team = False
    assert user_may_access_team(user) is False
    allowed2 = filter_visibilities_for_user([VISIBILITY_PUBLIC, VISIBILITY_TEAM, VISIBILITY_PRIVATE], user)
    assert allowed2 == [VISIBILITY_PRIVATE]


def test_user_has_any_content_scope_and_module_hiding(app):
    """When a user has no access to any scope of a module, the module is hidden."""
    invalidate_system_settings_cache()

    user = User(
        email='noscope@test.com',
        first_name='No',
        last_name='Scope',
        password_hash='h',
        is_admin=False,
        has_full_access=True,
        can_access_public=False,
        can_access_team=False,
        can_access_private=False,
    )
    db.session.add(user)
    db.session.commit()

    # Scope-based modules should return False for user_has_any_content_scope
    assert user_has_any_content_scope(user, 'module_files') is False
    assert user_has_any_content_scope(user, 'module_calendar') is False
    assert user_has_any_content_scope(user, 'module_wiki') is False
    assert user_has_any_content_scope(user, 'module_contacts') is False

    # Consequently, has_module_access returns False (hiding the module from nav & routes)
    assert has_module_access(user, 'module_files') is False
    assert has_module_access(user, 'module_calendar') is False
    assert has_module_access(user, 'module_wiki') is False

    # Non-scope modules like chat remain accessible based on module role
    assert has_module_access(user, 'module_chat') is True


def test_team_only_user_with_and_without_team(app):
    """Team-only users need at least one team membership to have a team scope."""
    invalidate_system_settings_cache()

    user = User(
        email='teamuser@test.com',
        first_name='Team',
        last_name='User',
        password_hash='h',
        is_admin=False,
        has_full_access=True,
        can_access_public=False,
        can_access_team=True,
        can_access_private=False,
    )
    db.session.add(user)
    db.session.commit()

    # Without team membership, user has no accessible scope
    assert user_has_any_content_scope(user, 'module_files') is False
    assert has_module_access(user, 'module_files') is False

    # Add team membership
    team = Team(name='Test Team Alpha')
    db.session.add(team)
    db.session.commit()

    member = TeamMember(team_id=team.id, user_id=user.id)
    db.session.add(member)
    db.session.commit()

    # Now team scope is available!
    assert user_has_any_content_scope(user, 'module_files') is True
    assert has_module_access(user, 'module_files') is True


def test_default_roles_include_content_scopes(app):
    """Standard roles loader and applicator includes content scopes."""
    roles = load_default_module_roles()
    assert 'can_access_public' in roles
    assert 'can_access_team' in roles
    assert 'can_access_private' in roles

    new_user = User(
        email='newcomer@test.com',
        first_name='New',
        last_name='Comer',
        password_hash='h',
        is_guest=False,
    )
    db.session.add(new_user)
    db.session.flush()

    apply_default_roles_to_user(new_user)
    assert new_user.can_access_public is True
    assert new_user.can_access_team is True
    assert new_user.can_access_private is True
