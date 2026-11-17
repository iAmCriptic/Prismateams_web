"""Tests for automatic mailbox server discovery and wizard provider UI."""

import os

os.environ['PRISMATEAMS_SKIP_BACKGROUND_JOBS'] = '1'
os.environ['PRISMATEAMS_SKIP_SCHEMA_INIT'] = '1'
os.environ['PRISMATEAMS_RUNNING_MIGRATIONS'] = '1'
os.environ['FLASK_ENV'] = 'testing'

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app import create_app, db
from app.models.settings import SystemSettings
from app.models.user import User
from app.utils.mailbox_autodiscover import (
    autodiscover_and_verify,
    discover_mail_candidates,
)


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


def _create_user(email='alice@example.com'):
    u = User(
        email=email,
        first_name='Alice',
        last_name='Test',
        is_active=True,
        is_admin=True,
        is_email_confirmed=True,
    )
    u.set_password('Secret123!')
    db.session.add(u)
    db.session.commit()
    return u


def _enable_multi_mailboxes():
    db.session.add(SystemSettings(key='email_multi_enabled', value='true'))
    db.session.commit()
    from app.utils.system_settings_cache import invalidate_system_settings_cache
    invalidate_system_settings_cache()


def test_discover_known_domain_preset():
    with (
        patch('app.utils.mailbox_autodiscover._fetch_autoconfig_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover._fetch_srv_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover._fetch_mx_candidates', return_value=([], [])),
    ):
        imap_cands, smtp_cands = discover_mail_candidates('max@infomaniak.com')

    assert imap_cands[0].server == 'mail.infomaniak.com'
    assert imap_cands[0].port == 993
    assert imap_cands[0].use_ssl is True
    assert smtp_cands[0].server == 'mail.infomaniak.com'
    assert smtp_cands[0].port == 587
    assert smtp_cands[0].use_tls is True


def test_discover_thunderbird_autoconfig_xml():
    xml_body = """<?xml version="1.0" encoding="UTF-8"?>
    <clientConfig version="1.1">
      <emailProvider id="example.org">
        <incomingServer type="imap">
          <hostname>imap.example.org</hostname>
          <port>993</port>
          <socketType>SSL</socketType>
          <username>%EMAILADDRESS%</username>
        </incomingServer>
        <outgoingServer type="smtp">
          <hostname>smtp.example.org</hostname>
          <port>465</port>
          <socketType>SSL</socketType>
          <username>%EMAILLOCALPART%</username>
        </outgoingServer>
      </emailProvider>
    </clientConfig>"""
    mock_resp = MagicMock(status_code=200, text=xml_body)
    with (
        patch('app.utils.mailbox_autodiscover.requests.get', return_value=mock_resp),
        patch('app.utils.mailbox_autodiscover._fetch_srv_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover._fetch_mx_candidates', return_value=([], [])),
    ):
        imap_cands, smtp_cands = discover_mail_candidates('info@example.org')

    assert imap_cands[0].server == 'imap.example.org'
    assert imap_cands[0].username == 'info@example.org'
    assert smtp_cands[0].server == 'smtp.example.org'
    assert smtp_cands[0].port == 465
    assert smtp_cands[0].use_ssl is True
    assert smtp_cands[0].username == 'info'


def test_discover_mx_inference():
    mx_record = SimpleNamespace(preference=10, exchange='example-com.mail.protection.outlook.com.')
    mock_resolver = MagicMock()
    mock_resolver.resolve.return_value = [mx_record]
    with (
        patch('app.utils.mailbox_autodiscover._fetch_autoconfig_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover._fetch_srv_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover._dns_resolver', return_value=mock_resolver),
    ):
        imap_cands, smtp_cands = discover_mail_candidates('team@custom-corp.de')

    assert imap_cands[0].server == 'outlook.office365.com'
    assert smtp_cands[0].server == 'smtp.office365.com'


def test_discover_mx_cross_domain_hosting():
    mx_record = SimpleNamespace(preference=10, exchange='mx01.mellowpark.de.')
    mock_resolver = MagicMock()
    mock_resolver.resolve.return_value = [mx_record]
    with (
        patch('app.utils.mailbox_autodiscover._fetch_autoconfig_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover._fetch_srv_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover._dns_resolver', return_value=mock_resolver),
    ):
        imap_cands, smtp_cands = discover_mail_candidates('info@alleins.de')

    imap_hosts = [c.server for c in imap_cands]
    smtp_hosts = [c.server for c in smtp_cands]
    assert 'mx01.mellowpark.de' in imap_hosts
    assert 'imap.mellowpark.de' in imap_hosts
    assert 'mail.mellowpark.de' in imap_hosts
    assert 'mellowpark.de' in imap_hosts
    assert 'mx01.mellowpark.de' in smtp_hosts
    assert 'smtp.mellowpark.de' in smtp_hosts
    assert 'mail.mellowpark.de' in smtp_hosts


def test_autodiscover_and_verify_success():
    with (
        patch('app.utils.mailbox_autodiscover._fetch_autoconfig_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover._fetch_srv_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover._fetch_mx_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover.test_imap_connection', return_value=(True, False, '')),
        patch('app.utils.mailbox_autodiscover.test_smtp_connection', return_value=(True, False, '')),
    ):
        res = autodiscover_and_verify('user@gmx.de', 'pw123')

    assert res['success'] is True
    assert res['imap_ok'] is True
    assert res['smtp_ok'] is True
    assert res['imap']['server'] == 'imap.gmx.net'
    assert res['smtp']['server'] == 'mail.gmx.net'


def test_autodiscover_and_verify_auth_error_returns_detected_servers():
    with (
        patch('app.utils.mailbox_autodiscover._fetch_autoconfig_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover._fetch_srv_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover._fetch_mx_candidates', return_value=([], [])),
        patch('app.utils.mailbox_autodiscover.test_imap_connection', return_value=(False, True, 'Auth failed')),
        patch('app.utils.mailbox_autodiscover.test_smtp_connection', return_value=(False, True, 'Auth failed')),
    ):
        res = autodiscover_and_verify('user@gmx.de', 'wrongpw')

    assert res['success'] is False
    assert res['auth_error'] is True
    assert res['imap']['server'] == 'imap.gmx.net'
    assert res['smtp']['server'] == 'mail.gmx.net'


def test_autodiscover_route_and_wizard_cards(app, client):
    _enable_multi_mailboxes()
    user = _create_user()
    login_resp = client.post('/login', data={'email': user.email, 'password': 'Secret123!'})
    assert login_resp.status_code in (200, 302)

    page = client.get('/settings/my-mailboxes/new')
    assert page.status_code == 200, page.headers.get('Location')
    html = page.get_data(as_text=True)
    assert 'data-provider="google"' in html
    assert 'data-provider="microsoft"' in html
    assert 'data-provider="custom"' in html
    assert 'data-provider="infomaniak"' not in html
    assert 'data-provider="ionos"' not in html
    assert 'data-autodiscover-url="/settings/mailboxes/autodiscover"' in html

    with patch(
        'app.utils.mailbox_autodiscover.autodiscover_and_verify',
        return_value={
            'success': True,
            'imap_ok': True,
            'smtp_ok': True,
            'auth_error': False,
            'imap': {'server': 'imap.gmx.net', 'port': 993, 'use_ssl': True, 'username': 'u@gmx.de', 'source': 'preset'},
            'smtp': {'server': 'mail.gmx.net', 'port': 587, 'use_tls': True, 'use_ssl': False, 'username': 'u@gmx.de', 'source': 'preset'},
            'error': '',
        },
    ):
        resp = client.post('/settings/mailboxes/autodiscover', json={'email': 'u@gmx.de', 'password': 'pw'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['imap']['server'] == 'imap.gmx.net'
