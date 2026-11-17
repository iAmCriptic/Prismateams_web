from datetime import datetime, timedelta
import pytest
from app import db
from app.models.user import User
from app.models.notification import NotificationSettings, NotificationLog
from app.utils.notifications import notify_user, get_or_create_notification_settings


@pytest.fixture
def notif_user(app):
    user = User(
        email='notif_test@example.com',
        first_name='Notif',
        last_name='Tester',
        is_active=True,
        is_admin=False,
        has_full_access=True,
        is_email_confirmed=True,
    )
    user.set_password('Password123!@#')
    db.session.add(user)
    db.session.commit()
    return user


def test_notification_settings_defaults(app, notif_user):
    settings = get_or_create_notification_settings(notif_user.id)
    assert settings.is_portal_enabled('chat') is True
    assert settings.is_push_enabled('chat') is True
    assert settings.is_portal_enabled('kanban') is True
    assert settings.is_push_enabled('kanban') is True
    assert settings.is_portal_enabled('comment') is True
    assert settings.is_push_enabled('comment') is True
    assert settings.is_portal_enabled('survey') is True
    assert settings.is_push_enabled('survey') is True
    assert settings.is_portal_enabled('room_booking') is True
    assert settings.is_push_enabled('room_booking') is True
    assert settings.is_paused() is False


def test_notify_user_portal_only(app, notif_user, monkeypatch):
    settings = get_or_create_notification_settings(notif_user.id)
    settings.chat_portal_enabled = True
    settings.chat_push_enabled = False
    db.session.commit()

    push_called = []
    def dummy_push(*args, **kwargs):
        push_called.append(True)
        return True

    monkeypatch.setattr('app.utils.notifications.send_push_notification', dummy_push)

    res = notify_user(
        notif_user.id,
        title='Chat Nachricht',
        body='Hallo Test',
        url='/chat/1',
        notification_type='chat',
        dedup_key='test_chat_1',
    )
    assert res is True
    assert len(push_called) == 0

    log = NotificationLog.query.filter_by(user_id=notif_user.id, dedup_key='test_chat_1').first()
    assert log is not None
    assert log.title == 'Chat Nachricht'


def test_notify_user_push_only(app, notif_user, monkeypatch):
    settings = get_or_create_notification_settings(notif_user.id)
    settings.chat_portal_enabled = False
    settings.chat_push_enabled = True
    db.session.commit()

    push_called = []
    def dummy_push(*args, **kwargs):
        push_called.append(True)
        return True

    monkeypatch.setattr('app.utils.notifications.send_push_notification', dummy_push)

    res = notify_user(
        notif_user.id,
        title='Chat Nachricht Push',
        body='Push Body',
        url='/chat/2',
        notification_type='chat',
        dedup_key='test_chat_2',
    )
    assert res is True
    assert len(push_called) == 1

    log = NotificationLog.query.filter_by(user_id=notif_user.id, dedup_key='test_chat_2').first()
    assert log is None


def test_notify_user_both_disabled(app, notif_user, monkeypatch):
    settings = get_or_create_notification_settings(notif_user.id)
    settings.chat_portal_enabled = False
    settings.chat_push_enabled = False
    db.session.commit()

    push_called = []
    def dummy_push(*args, **kwargs):
        push_called.append(True)
        return True

    monkeypatch.setattr('app.utils.notifications.send_push_notification', dummy_push)

    res = notify_user(
        notif_user.id,
        title='Chat Nachricht Niemand',
        body='Niemand Body',
        url='/chat/3',
        notification_type='chat',
        dedup_key='test_chat_3',
    )
    assert res is False
    assert len(push_called) == 0

    log = NotificationLog.query.filter_by(user_id=notif_user.id, dedup_key='test_chat_3').first()
    assert log is None


def test_notify_user_snooze(app, notif_user, monkeypatch):
    settings = get_or_create_notification_settings(notif_user.id)
    settings.chat_portal_enabled = True
    settings.chat_push_enabled = True
    settings.pause(60)
    db.session.commit()

    assert settings.is_paused() is True

    push_called = []
    def dummy_push(*args, **kwargs):
        push_called.append(True)
        return True

    monkeypatch.setattr('app.utils.notifications.send_push_notification', dummy_push)

    res = notify_user(
        notif_user.id,
        title='Chat Nachricht Snooze',
        body='Snooze Body',
        url='/chat/4',
        notification_type='chat',
        dedup_key='test_chat_4',
    )
    assert res is False
    assert len(push_called) == 0

    log = NotificationLog.query.filter_by(user_id=notif_user.id, dedup_key='test_chat_4').first()
    assert log is None

    # Unpause
    settings.unpause()
    db.session.commit()
    assert settings.is_paused() is False

    res2 = notify_user(
        notif_user.id,
        title='Chat Nachricht Nach Snooze',
        body='Nach Snooze Body',
        url='/chat/4',
        notification_type='chat',
        dedup_key='test_chat_4',
    )
    assert res2 is True
    assert len(push_called) == 1
    log2 = NotificationLog.query.filter_by(user_id=notif_user.id, dedup_key='test_chat_4').first()
    assert log2 is not None


def test_snooze_endpoint(client, notif_user):
    client.post('/login', data={'email': notif_user.email, 'password': 'Password123!@#'})

    # Snooze for 120 minutes
    resp = client.post(
        '/settings/notifications/snooze',
        json={'minutes': 120},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['is_paused'] is True
    assert data['paused_until'] is not None

    # Check database
    settings = get_or_create_notification_settings(notif_user.id)
    assert settings.is_paused() is True

    # Resume (minutes = 0)
    resp2 = client.post(
        '/settings/notifications/snooze',
        json={'minutes': 0},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2['success'] is True
    assert data2['is_paused'] is False
    assert data2['paused_until'] is None

    settings = get_or_create_notification_settings(notif_user.id)
    assert settings.is_paused() is False
