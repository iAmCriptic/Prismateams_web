"""Tests für Unternehmens-E-Mail-Authentifizierung und Postfach-Kopplung."""

import os
os.environ['PRISMATEAMS_SKIP_BACKGROUND_JOBS'] = '1'
os.environ['PRISMATEAMS_SKIP_SCHEMA_INIT'] = '1'
os.environ['PRISMATEAMS_RUNNING_MIGRATIONS'] = '1'
os.environ['FLASK_ENV'] = 'testing'

import imaplib
import pytest
from unittest.mock import MagicMock, patch

from app import create_app, db
from app.models.user import User
from app.models.email import Mailbox
from app.models.settings import SystemSettings
from app.models.whitelist import WhitelistEntry
from app.services.company_mail_auth import (
    is_company_email,
    get_configured_company_domains,
    verify_mailbox_credentials,
    provision_user_company_mailbox,
    sync_credentials_if_needed,
)
from app.utils.multi_mailboxes import decrypt_password


@pytest.fixture(scope='session')
def app_instance():
    app = create_app('testing')
    app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'RATELIMIT_ENABLED': False,
    })
    return app


@pytest.fixture
def app(app_instance):
    with app_instance.app_context():
        db.create_all()
        yield app_instance
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _set_setting(key, value):
    s = SystemSettings.query.filter_by(key=key).first()
    if s:
        s.value = str(value)
    else:
        db.session.add(SystemSettings(key=key, value=str(value)))
    db.session.commit()


# ====================================================================
# 1. Domain-Erkennung und Parsing Tests
# ====================================================================

def test_domain_parsing_and_matching(app):
    with app.app_context():
        # Mehrere Domains mit Kommas und Leerzeichen
        _set_setting('company_email_domains', 'firma.de, @holding.com; tochter.eu')
        domains = get_configured_company_domains()
        
        assert '@firma.de' in domains
        assert '@holding.com' in domains
        assert '@tochter.eu' in domains

        assert is_company_email('max.mustermann@firma.de') is True
        assert is_company_email('erika@HOLDING.COM') is True
        assert is_company_email('dev@tochter.eu') is True
        assert is_company_email('attacker@gmail.com') is False
        assert is_company_email('spammer@web.de') is False
        assert is_company_email('') is False
        assert is_company_email(None) is False


def test_domain_fallback_to_whitelist(app):
    with app.app_context():
        _set_setting('company_email_domains', '')
        # Domain über Whitelist hinterlegen
        wl = WhitelistEntry(entry='@partner.org', entry_type='domain', is_active=True)
        db.session.add(wl)
        db.session.commit()

        assert is_company_email('ceo@partner.org') is True
        assert is_company_email('user@other.org') is False


# ====================================================================
# 2. Live-Prüfung gegen IMAP-Server
# ====================================================================

def test_verify_mailbox_credentials_success(app):
    with app.app_context():
        _set_setting('company_mail_imap_server', 'imap.firma.de')
        _set_setting('company_mail_imap_port', '993')
        _set_setting('company_mail_imap_ssl', 'True')

        mock_conn = MagicMock()
        mock_conn.login.return_value = ('OK', [b'Logged in'])
        mock_conn.select.return_value = ('OK', [b'1'])

        with patch('imaplib.IMAP4_SSL', return_value=mock_conn):
            ok, status, details = verify_mailbox_credentials('test@firma.de', 'geheim123!')
            assert ok is True
            assert status == 'OK'
            mock_conn.login.assert_called_once_with('test@firma.de', 'geheim123!')
            mock_conn.select.assert_called_once_with('INBOX', readonly=True)


def test_verify_mailbox_credentials_auth_fail(app):
    with app.app_context():
        _set_setting('company_mail_imap_server', 'imap.firma.de')

        mock_conn = MagicMock()
        mock_conn.login.side_effect = imaplib.IMAP4.error("Invalid credentials")

        with patch('imaplib.IMAP4_SSL', return_value=mock_conn):
            ok, status, details = verify_mailbox_credentials('test@firma.de', 'falsch')
            assert ok is False
            assert status == 'AUTH_FAILED'


def test_verify_mailbox_credentials_server_down(app):
    with app.app_context():
        _set_setting('company_mail_imap_server', 'imap.firma.de')

        with patch('imaplib.IMAP4_SSL', side_effect=TimeoutError("Connection timed out")):
            ok, status, details = verify_mailbox_credentials('test@firma.de', 'geheim123!')
            assert ok is False
            assert status == 'CONNECTION_ERROR'


# ====================================================================
# 3. Registrierungs-Ablauf Tests
# ====================================================================

def _ensure_admin():
    admin = User.query.filter_by(is_admin=True).first()
    if not admin:
        admin = User(
            email='admin.root@firma.de',
            first_name='Super',
            last_name='Admin',
            is_active=True,
            is_admin=True,
            is_email_confirmed=True,
        )
        admin.set_password('AdminMasterPass123!')
        db.session.add(admin)
        db.session.commit()
    return admin


def test_register_blocked_when_foreign_domain(client, app):
    with app.app_context():
        _ensure_admin()
        _set_setting('company_email_register_only', 'True')
        _set_setting('company_email_domains', '@firma.de')

        resp = client.post('/register', data={
            'email': 'fremd@gmail.com',
            'first_name': 'Max',
            'last_name': 'Mustermann',
            'password': 'Password1234!',
            'password_confirm': 'Password1234!',
        }, follow_redirects=True)

        assert resp.status_code == 200
        # Sicherstellen: Kein Benutzer angelegt
        assert User.query.filter_by(email='fremd@gmail.com').first() is None


def test_register_fails_and_creates_no_user_on_bad_mailbox_login(client, app):
    with app.app_context():
        _ensure_admin()
        _set_setting('company_email_register_only', 'True')
        _set_setting('company_email_domains', '@firma.de')
        _set_setting('company_mail_imap_server', 'imap.firma.de')

        mock_conn = MagicMock()
        mock_conn.login.side_effect = imaplib.IMAP4.error("Authentication failed")

        with patch('imaplib.IMAP4_SSL', return_value=mock_conn):
            resp = client.post('/register', data={
                'email': 'mitarbeiter@firma.de',
                'first_name': 'Anna',
                'last_name': 'Mitarbeiter',
                'password': 'Password1234!',
                'password_confirm': 'Password1234!',
            }, follow_redirects=True)

            assert resp.status_code == 200
            # KRITISCHE ANFORDERUNG: Wenn Postfach-Login fehlschlägt, wird KEIN User angelegt!
            user = User.query.filter_by(email='mitarbeiter@firma.de').first()
            assert user is None
            assert Mailbox.query.filter_by(display_name='mitarbeiter@firma.de').first() is None


def test_register_succeeds_activates_user_and_provisions_mailbox(client, app):
    with app.app_context():
        _ensure_admin()
        _set_setting('company_email_register_only', 'True')
        _set_setting('company_email_domains', '@firma.de')
        _set_setting('company_mail_imap_server', 'imap.firma.de')
        _set_setting('company_mail_smtp_server', 'smtp.firma.de')

        mock_conn = MagicMock()
        mock_conn.login.return_value = ('OK', [b'Logged in'])
        mock_conn.select.return_value = ('OK', [b'1'])

        with patch('imaplib.IMAP4_SSL', return_value=mock_conn):
            resp = client.post('/register', data={
                'email': 'anna@firma.de',
                'first_name': 'Anna',
                'last_name': 'Schmidt',
                'password': 'SecurePass1234!',
                'password_confirm': 'SecurePass1234!',
            }, follow_redirects=True)

            assert resp.status_code == 200
            user = User.query.filter_by(email='anna@firma.de').first()
            assert user is not None
            # Automatisch freigeschaltet und bestätigt:
            assert user.is_active is True
            assert user.is_email_confirmed is True

            # Persönliches Postfach automatisch mitgenommen:
            mb = Mailbox.query.filter_by(owner_id=user.id, mailbox_type='private').first()
            assert mb is not None
            assert mb.imap_username == 'anna@firma.de'
            assert decrypt_password(mb.imap_password_enc) == 'SecurePass1234!'
            assert mb.is_active is True


# ====================================================================
# 4. Login-Ablauf & Live-Abgleich Tests
# ====================================================================

def test_login_blocked_when_mailserver_rejects(client, app):
    with app.app_context():
        _set_setting('company_email_auth_enabled', 'True')
        _set_setting('company_email_domains', '@firma.de')
        _set_setting('company_mail_imap_server', 'imap.firma.de')

        user = User(
            email='anna@firma.de',
            first_name='Anna',
            last_name='Schmidt',
            is_active=True,
            is_email_confirmed=True,
        )
        user.set_password('Password1234!')
        db.session.add(user)
        db.session.commit()

        # Mailserver lehnt ab (z. B. Postfach gesperrt oder Passwort geändert)
        mock_conn = MagicMock()
        mock_conn.login.side_effect = imaplib.IMAP4.error("Account disabled")

        with patch('imaplib.IMAP4_SSL', return_value=mock_conn):
            resp = client.post('/login', data={
                'email': 'anna@firma.de',
                'password': 'Password1234!',
            }, follow_redirects=True)

            assert resp.status_code == 200
            # Login muss scheitern, session nicht authentifiziert
            with client.session_transaction() as sess:
                assert '_user_id' not in sess


def test_login_server_outage_admin_vs_user(client, app):
    with app.app_context():
        _set_setting('company_email_auth_enabled', 'True')
        _set_setting('company_email_domains', '@firma.de')
        _set_setting('company_email_allow_user_offline_login', 'False')
        _set_setting('company_mail_imap_server', 'imap.firma.de')

        # Regulärer Benutzer
        user = User(
            email='user@firma.de',
            first_name='Regulaer',
            last_name='User',
            is_active=True,
            is_admin=False,
            is_email_confirmed=True,
        )
        user.set_password('Secret12345!')
        db.session.add(user)

        # Admin
        admin = User(
            email='admin@firma.de',
            first_name='Super',
            last_name='Admin',
            is_active=True,
            is_admin=True,
            is_email_confirmed=True,
        )
        admin.set_password('AdminPass1234!')
        db.session.add(admin)
        db.session.commit()

        # Mailserver wirft Timeout
        with patch('imaplib.IMAP4_SSL', side_effect=TimeoutError("Timeout")):
            # 1. Normaler User wird geblockt (da offline_login=False)
            resp_user = client.post('/login', data={
                'email': 'user@firma.de',
                'password': 'Secret12345!',
            }, follow_redirects=True)
            with client.session_transaction() as sess:
                assert '_user_id' not in sess

            # 2. Admin darf sich immer mit lokalem Passwort einloggen!
            resp_admin = client.post('/login', data={
                'email': 'admin@firma.de',
                'password': 'AdminPass1234!',
            }, follow_redirects=True)
            with client.session_transaction() as sess:
                assert sess.get('_user_id') == str(admin.id)


def test_login_server_outage_user_allowed_when_toggle_on(client, app):
    with app.app_context():
        _set_setting('company_email_auth_enabled', 'True')
        _set_setting('company_email_domains', '@firma.de')
        _set_setting('company_email_allow_user_offline_login', 'True')  # Toggle AKTIV
        _set_setting('company_mail_imap_server', 'imap.firma.de')

        user = User(
            email='user@firma.de',
            first_name='Regulaer',
            last_name='User',
            is_active=True,
            is_admin=False,
            is_email_confirmed=True,
        )
        user.set_password('Secret12345!')
        db.session.add(user)
        db.session.commit()

        with patch('imaplib.IMAP4_SSL', side_effect=TimeoutError("Timeout")):
            resp = client.post('/login', data={
                'email': 'user@firma.de',
                'password': 'Secret12345!',
            }, follow_redirects=True)

            # Wenn Schalter aktiv ist, gelingt auch dem regulären Nutzer der Login
            with client.session_transaction() as sess:
                assert sess.get('_user_id') == str(user.id)


def test_login_password_auto_sync_when_changed_on_mailserver(client, app):
    with app.app_context():
        _set_setting('company_email_auth_enabled', 'True')
        _set_setting('company_email_domains', '@firma.de')
        _set_setting('company_mail_imap_server', 'imap.firma.de')

        user = User(
            email='user@firma.de',
            first_name='User',
            last_name='Firma',
            is_active=True,
            is_email_confirmed=True,
        )
        user.set_password('AltesPasswort123!')
        db.session.add(user)
        db.session.flush()

        mb = provision_user_company_mailbox(user, 'AltesPasswort123!')

        # Der Nutzer hat sein Passwort auf dem IMAP-Server auf 'NeuesPasswort123!' geändert
        mock_conn = MagicMock()
        mock_conn.login.return_value = ('OK', [b'Logged in'])
        mock_conn.select.return_value = ('OK', [b'1'])

        with patch('imaplib.IMAP4_SSL', return_value=mock_conn):
            resp = client.post('/login', data={
                'email': 'user@firma.de',
                'password': 'NeuesPasswort123!',
            }, follow_redirects=True)

            with client.session_transaction() as sess:
                assert sess.get('_user_id') == str(user.id)

            # Passwort-Hash und verschlüsseltes Mailbox-Passwort müssen aktualisiert worden sein:
            assert user.check_password('NeuesPasswort123!') is True
            db.session.refresh(mb)
            assert decrypt_password(mb.imap_password_enc) == 'NeuesPasswort123!'
