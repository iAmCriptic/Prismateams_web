"""Tests für die browserbasierte Haupt-E-Mail-Konfiguration und .env-Migration."""

from unittest.mock import patch

from app import db
from app.models.settings import SystemSettings
from app.models.user import User
from app.utils.main_mail_config import (
    KEY_ENV_MIGRATED,
    KEY_SMTP_PASSWORD_ENC,
    get_formatted_main_sender,
    get_main_mail_config,
    is_main_mail_configured,
    migrate_main_mail_from_env_if_needed,
    save_main_mail_config,
)
from app.utils.multi_mailboxes import get_main_imap_config, get_main_smtp_config
from app.utils.system_settings_cache import invalidate_system_settings_cache


def test_save_and_load_main_mail_config_keeps_password_on_placeholder(app):
    invalidate_system_settings_cache()
    save_main_mail_config({
        'provider': 'infomaniak',
        'smtp_server': 'mail.infomaniak.com',
        'smtp_port': 587,
        'smtp_use_tls': True,
        'smtp_use_ssl': False,
        'smtp_username': 'team@example.org',
        'smtp_password': 'super-secret-password',
        'imap_server': 'mail.infomaniak.com',
        'imap_port': 993,
        'imap_use_ssl': True,
        'default_sender': 'noreply@example.org',
        'sender_name': 'Prismateams Test',
    })

    cfg = get_main_mail_config()
    assert cfg['source'] == 'db'
    assert cfg['provider'] == 'infomaniak'
    assert cfg['smtp_server'] == 'mail.infomaniak.com'
    assert cfg['smtp_password'] == 'super-secret-password'
    assert cfg['has_smtp_password'] is True
    assert is_main_mail_configured() is True
    assert get_formatted_main_sender() == 'Prismateams Test <noreply@example.org>'

    # Passwort in DB ist verschlüsselt, nicht Klartext
    raw_row = SystemSettings.query.filter_by(key=KEY_SMTP_PASSWORD_ENC).first()
    assert raw_row is not None
    assert raw_row.value != 'super-secret-password'

    # Bearbeiten mit Platzhalter behält Passwort bei
    save_main_mail_config({
        'provider': 'infomaniak',
        'smtp_server': 'mail.infomaniak.com',
        'smtp_port': 465,
        'smtp_use_tls': False,
        'smtp_use_ssl': True,
        'smtp_username': 'team@example.org',
        'smtp_password': '••••••••',
        'imap_server': 'mail.infomaniak.com',
        'imap_port': 993,
        'imap_use_ssl': True,
        'default_sender': 'noreply@example.org',
        'sender_name': 'Neu',
    })

    updated = get_main_mail_config()
    assert updated['smtp_password'] == 'super-secret-password'
    assert updated['smtp_port'] == 465
    assert updated['smtp_use_ssl'] is True
    assert get_main_smtp_config()['port'] == 465
    assert get_main_imap_config()['server'] == 'mail.infomaniak.com'


def test_env_migration_is_idempotent(app):
    invalidate_system_settings_cache()
    app.config.update({
        'MAIL_SERVER': 'smtp.legacy.test',
        'MAIL_PORT': 587,
        'MAIL_USE_TLS': True,
        'MAIL_USE_SSL': False,
        'MAIL_USERNAME': 'legacy@example.com',
        'MAIL_PASSWORD': 'legacy-password',
        'MAIL_DEFAULT_SENDER': 'legacy@example.com',
        'MAIL_SENDER_NAME': 'Legacy Portal',
        'IMAP_SERVER': 'imap.legacy.test',
        'IMAP_PORT': 993,
        'IMAP_USE_SSL': True,
    })

    migrated = migrate_main_mail_from_env_if_needed()
    assert migrated is True

    cfg = get_main_mail_config()
    assert cfg['source'] == 'db'
    assert cfg['smtp_server'] == 'smtp.legacy.test'
    assert cfg['smtp_password'] == 'legacy-password'
    assert cfg['imap_server'] == 'imap.legacy.test'

    # DB-Änderung darf durch erneuten Migrations-Aufruf nicht überschrieben werden
    save_main_mail_config({
        'smtp_server': 'smtp.browser.test',
        'smtp_port': 587,
        'smtp_use_tls': True,
        'smtp_use_ssl': False,
        'smtp_username': 'browser@example.com',
        'smtp_password': 'browser-password',
    })
    assert migrate_main_mail_from_env_if_needed() is False
    assert get_main_mail_config()['smtp_server'] == 'smtp.browser.test'
    assert SystemSettings.query.filter_by(key=KEY_ENV_MIGRATED).first().value == 'true'


def test_setup_step4_email_and_autodiscover(app, client):
    invalidate_system_settings_cache()
    db.session.add(SystemSettings(key='portal_name', value='TestPortal'))
    db.session.add(SystemSettings(key='setup_completed', value='false'))
    admin = User(
        email='admin@example.com',
        first_name='Admin',
        last_name='User',
        is_active=True,
        is_admin=True,
        is_super_admin=True,
        is_email_confirmed=True,
    )
    admin.set_password('StrongPass123!')
    db.session.add(admin)
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['setup_reg_completed'] = True

    resp = client.get('/setup/step4')
    assert resp.status_code == 200

    with patch('app.utils.mailbox_autodiscover.autodiscover_and_verify') as mock_auto:
        mock_auto.return_value = {
            'success': True,
            'imap_ok': True,
            'smtp_ok': True,
            'auth_error': False,
            'imap': {'server': 'imap.example.com', 'port': 993, 'use_ssl': True, 'username': 'mail@example.com'},
            'smtp': {'server': 'smtp.example.com', 'port': 587, 'use_tls': True, 'use_ssl': False, 'username': 'mail@example.com'},
        }
        auto_resp = client.post('/setup/mail/autodiscover', json={
            'email': 'mail@example.com',
            'password': 'secret',
        })
        assert auto_resp.status_code == 200
        assert auto_resp.get_json()['success'] is True

    post_resp = client.post('/setup/step4', data={
        'action': 'save',
        'provider': 'custom',
        'smtp_username': 'mail@example.com',
        'smtp_password': 'secret',
        'smtp_server': 'smtp.example.com',
        'smtp_port': '587',
        'smtp_security': 'tls',
        'imap_server': 'imap.example.com',
        'imap_port': '993',
        'imap_use_ssl': 'true',
    }, follow_redirects=False)
    assert post_resp.status_code == 302
    assert '/setup/step5' in post_resp.location
    assert get_main_mail_config()['smtp_server'] == 'smtp.example.com'


def test_admin_main_mailbox_requires_admin_and_saves(app, client):
    invalidate_system_settings_cache()
    db.session.add(SystemSettings(key='setup_completed', value='true'))
    user = User(
        email='user@example.com',
        first_name='Normal',
        last_name='User',
        is_active=True,
        is_admin=False,
        is_email_confirmed=True,
    )
    user.set_password('StrongPass123!')
    admin = User(
        email='admin@example.com',
        first_name='Admin',
        last_name='User',
        is_active=True,
        is_admin=True,
        is_email_confirmed=True,
    )
    admin.set_password('StrongPass123!')
    db.session.add_all([user, admin])
    db.session.commit()

    from app.utils.session_manager import create_session

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['user_scope'] = 'portal'
    with app.test_request_context():
        pass
    resp_user = client.get('/settings/admin/main-mailbox', follow_redirects=False)
    assert resp_user.status_code == 302

    # Admin sauber über Login einloggen, damit Portal-Session-Tracking aktiv ist
    login_resp = client.post('/login', data={
        'email': 'admin@example.com',
        'password': 'StrongPass123!',
    }, follow_redirects=False)
    assert login_resp.status_code in (200, 302)
    resp_admin = client.get('/settings/admin/main-mailbox')
    assert resp_admin.status_code == 200

    save_resp = client.post('/settings/admin/main-mailbox', data={
        'provider': 'ionos',
        'smtp_username': 'info@firma.de',
        'smtp_password': 'pw123',
        'smtp_server': 'smtp.ionos.de',
        'smtp_port': '587',
        'smtp_security': 'tls',
        'imap_server': 'imap.ionos.de',
        'imap_port': '993',
        'imap_use_ssl': 'true',
        'sender_name': 'Firma',
    }, follow_redirects=False)
    assert save_resp.status_code == 302
    assert get_main_mail_config()['smtp_server'] == 'smtp.ionos.de'
    assert get_formatted_main_sender() == 'Firma <info@firma.de>'
