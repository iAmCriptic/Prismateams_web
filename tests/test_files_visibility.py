import pytest
from app import db
from app.models.settings import SystemSettings
from app.models.user import User
from app.utils.private_files import (
    is_private_folders_enabled,
    is_team_folders_enabled,
    is_public_folders_enabled,
    normalize_view,
)
from app.utils.system_settings_cache import invalidate_system_settings_cache


def test_files_visibility_defaults_all_enabled(app):
    """When all global visibility variants are on (default), files spaces are enabled."""
    invalidate_system_settings_cache()
    assert is_private_folders_enabled() is True
    assert is_team_folders_enabled() is True
    assert is_public_folders_enabled() is True

    user = User(email='test@example.com', first_name='Test', last_name='User', password_hash='hash')
    user.is_admin = True
    assert normalize_view(None, user=user) == 'ablage'
    assert normalize_view('ablage', user=user) == 'ablage'
    assert normalize_view('team', user=user) == 'team'
    assert normalize_view('public', user=user) == 'public'
    assert normalize_view('freigaben', user=user) == 'freigaben'
    assert normalize_view('trash', user=user) == 'trash'


def test_files_visibility_respects_global_toggles(app):
    """When global visibility toggles are modified, files module reacts accordingly."""
    invalidate_system_settings_cache()

    # Disable private
    s_priv = SystemSettings(key='modules_allow_private', value='false')
    db.session.add(s_priv)
    db.session.commit()
    invalidate_system_settings_cache()

    assert is_private_folders_enabled() is False
    assert is_team_folders_enabled() is True
    assert is_public_folders_enabled() is True

    user = User(email='test@example.com', first_name='Test', last_name='User', password_hash='hash')
    user.is_admin = True
    # Without private, default falls back to team
    assert normalize_view(None, user=user) == 'team'
    # Requesting ablage falls back to team
    assert normalize_view('ablage', user=user) == 'team'

    # Disable team
    s_team = SystemSettings(key='modules_allow_team', value='false')
    db.session.add(s_team)
    db.session.commit()
    invalidate_system_settings_cache()

    assert is_private_folders_enabled() is False
    assert is_team_folders_enabled() is False
    assert is_public_folders_enabled() is True

    # Without private and team, default falls back to public
    assert normalize_view(None, user=user) == 'public'
    assert normalize_view('team', user=user) == 'public'

    # Disable public
    s_pub = SystemSettings(key='modules_allow_public', value='false')
    db.session.add(s_pub)
    db.session.commit()
    invalidate_system_settings_cache()

    assert is_public_folders_enabled() is False
    # All disabled -> falls back to trash
    assert normalize_view(None, user=user) == 'trash'
    assert normalize_view('public', user=user) == 'trash'


def test_verified_user_access_to_public_and_team_files(app):
    """A verified user can view and edit public and team files/folders even if created by another user."""
    from app.models.file import File, Folder
    from app.models.team import Team, TeamMember
    from app.utils.private_files import (
        can_view_file,
        can_view_folder,
        can_edit_file,
        can_edit_folder,
    )

    invalidate_system_settings_cache()

    # User A (existing user / uploader)
    user_a = User(
        email='creator@test.com',
        first_name='Creator',
        last_name='User',
        password_hash='hash',
        is_admin=False,
    )
    # User B (newly registered / verified user)
    user_b = User(
        email='newuser@test.com',
        first_name='New',
        last_name='User',
        password_hash='hash',
        is_admin=False,
        is_active=True,
        is_email_confirmed=True,
        can_access_public=True,
        can_access_team=True,
        can_access_private=True,
    )
    # User C (team-only user without public access)
    user_c = User(
        email='teamonly@test.com',
        first_name='Team',
        last_name='Only',
        password_hash='hash',
        is_admin=False,
        can_access_public=False,
        can_access_team=True,
        can_access_private=True,
    )
    db.session.add_all([user_a, user_b, user_c])
    db.session.commit()

    # Public folder & file created by user_a
    pub_folder = Folder(name='TestFolder', parent_id=None, created_by=user_a.id, space='public')
    db.session.add(pub_folder)
    db.session.commit()

    pub_file = File(
        name='Abirechner.xlsx',
        original_name='Abirechner.xlsx',
        folder_id=pub_folder.id,
        uploaded_by=user_a.id,
        file_path='/tmp/fake.xlsx',
        file_size=1024,
        mime_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        space='public',
    )
    db.session.add(pub_file)
    db.session.commit()

    # User B should be able to view and edit the public folder and file
    assert can_view_folder(pub_folder, user_b) is True
    assert can_edit_folder(pub_folder, user_b) is True
    assert can_view_file(pub_file, user_b) is True
    assert can_edit_file(pub_file, user_b) is True

    # User C (no public access) should NOT have access
    assert can_view_folder(pub_folder, user_c) is False
    assert can_edit_folder(pub_folder, user_c) is False
    assert can_view_file(pub_file, user_c) is False
    assert can_edit_file(pub_file, user_c) is False

    # Team folder & file
    team = Team(name='Technik', leader_id=user_a.id)
    db.session.add(team)
    db.session.commit()

    team_folder = Folder(
        name='Technik Shared',
        parent_id=None,
        created_by=user_a.id,
        space='team',
        team_id=team.id,
        is_team_root=True,
    )
    db.session.add(team_folder)
    db.session.commit()

    team_file = File(
        name='Plan.docx',
        original_name='Plan.docx',
        folder_id=team_folder.id,
        uploaded_by=user_a.id,
        file_path='/tmp/plan.docx',
        file_size=2048,
        mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        space='team',
        team_id=team.id,
    )
    db.session.add(team_file)
    db.session.commit()

    # User B is not yet a member of Team -> no access
    assert can_view_folder(team_folder, user_b) is False
    assert can_edit_folder(team_folder, user_b) is False
    assert can_view_file(team_file, user_b) is False
    assert can_edit_file(team_file, user_b) is False

    # Add User B and User C to Team
    member_b = TeamMember(user_id=user_b.id, team_id=team.id)
    member_c = TeamMember(user_id=user_c.id, team_id=team.id)
    db.session.add_all([member_b, member_c])
    db.session.commit()

    # Now User B and User C have access to team files
    assert can_view_folder(team_folder, user_b) is True
    assert can_edit_folder(team_folder, user_b) is True
    assert can_view_file(team_file, user_b) is True
    assert can_edit_file(team_file, user_b) is True

    assert can_view_folder(team_folder, user_c) is True
    assert can_edit_folder(team_folder, user_c) is True
    assert can_view_file(team_file, user_c) is True
    assert can_edit_file(team_file, user_c) is True
