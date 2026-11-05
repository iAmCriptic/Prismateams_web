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
