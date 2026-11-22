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


def test_send_file_notification_creates_in_app_log(app, notif_user, monkeypatch):
    from app.models.file import File
    from app.utils.notifications import send_file_notification

    uploader = User(
        email='uploader_test@example.com',
        first_name='Up',
        last_name='Loader',
        is_active=True,
        is_admin=False,
        has_full_access=True,
        is_email_confirmed=True,
    )
    uploader.set_password('Password123!@#')
    db.session.add(uploader)
    db.session.commit()

    uploader_settings = get_or_create_notification_settings(uploader.id)
    uploader_settings.file_notifications_enabled = True
    uploader_settings.file_portal_enabled = True
    uploader_settings.file_push_enabled = False

    recipient_settings = get_or_create_notification_settings(notif_user.id)
    recipient_settings.file_notifications_enabled = True
    recipient_settings.file_portal_enabled = True
    recipient_settings.file_push_enabled = False
    recipient_settings.file_new_notifications = True

    test_file = File(
        name='bericht.pdf',
        original_name='bericht.pdf',
        uploaded_by=uploader.id,
        file_path='/tmp/bericht.pdf',
        file_size=1234,
    )
    db.session.add(test_file)
    db.session.commit()

    monkeypatch.setattr('app.utils.notifications.send_push_notification', lambda *a, **kw: False)

    sent = send_file_notification(test_file.id, 'new')
    assert sent == 1

    recipient_log = NotificationLog.query.filter_by(
        user_id=notif_user.id,
        notification_type='file',
        source_id=test_file.id,
    ).first()
    assert recipient_log is not None

    uploader_log = NotificationLog.query.filter_by(
        user_id=uploader.id,
        notification_type='file',
        source_id=test_file.id,
    ).first()
    assert uploader_log is None


def test_booking_request_and_message_notifications(app, notif_user, monkeypatch):
    from app.models.booking import BookingForm, BookingRequest, BookingRequestMessage
    from app.utils.notifications import (
        send_booking_request_notification,
        send_booking_message_notification,
    )

    form = BookingForm(
        title='Test Buchungsformular',
        created_by=notif_user.id,
        is_active=True,
    )
    db.session.add(form)
    db.session.flush()

    req = BookingRequest(
        form_id=form.id,
        event_name='Sommerfest',
        applicant_name='Max Mustermann',
        email='max@example.com',
        token='tok-booking-notif-1',
    )
    db.session.add(req)
    db.session.flush()

    msg = BookingRequestMessage(
        request_id=req.id,
        direction='inbound',
        subject='Rückfrage',
        body_text='Können wir früher aufbauen?',
        from_email='max@example.com',
        is_read=False,
    )
    db.session.add(msg)
    db.session.commit()

    settings = get_or_create_notification_settings(notif_user.id)
    settings.booking_portal_enabled = True
    settings.booking_push_enabled = True
    settings.booking_notifications_enabled = True
    settings.booking_message_notifications_enabled = True
    db.session.commit()

    push_calls = []
    def fake_push(user_id, title, body, **kwargs):
        push_calls.append((user_id, title, body, kwargs.get('url')))
        return True

    monkeypatch.setattr('app.utils.notifications.send_push_notification', fake_push)

    # 1. Neue Buchungsanfrage -> In-App + Push
    sent_req = send_booking_request_notification(req)
    assert sent_req == 1
    assert len(push_calls) == 1
    assert push_calls[0][0] == notif_user.id

    req_log = NotificationLog.query.filter_by(
        user_id=notif_user.id,
        notification_type='booking',
        source_id=req.id,
    ).first()
    assert req_log is not None
    assert 'Sommerfest' in req_log.body

    # 2. Neue Nachricht -> In-App + Push
    sent_msg = send_booking_message_notification(req, msg)
    assert sent_msg == 1
    assert len(push_calls) == 2

    msg_log = NotificationLog.query.filter_by(
        user_id=notif_user.id,
        notification_type='booking',
        dedup_key=f'booking_message:{req.id}:{msg.id}:{notif_user.id}',
    ).first()
    assert msg_log is not None
    assert 'Können wir früher aufbauen?' in msg_log.body

    # 3. Deaktivierte Sub-Toggles -> weder In-App noch Push
    settings.booking_notifications_enabled = False
    settings.booking_message_notifications_enabled = False
    db.session.commit()

    assert send_booking_request_notification(req) == 0
    assert send_booking_message_notification(req, msg) == 0
    assert len(push_calls) == 2


def test_survey_new_and_response_notifications(app, notif_user, monkeypatch):
    from app.models.survey import Survey
    from app.utils.notifications import send_survey_notification

    creator = User(
        email='survey_creator@example.com',
        first_name='Survey',
        last_name='Creator',
        is_active=True,
        is_admin=False,
        has_full_access=True,
        is_email_confirmed=True,
    )
    creator.set_password('Password123!@#')
    db.session.add(creator)
    db.session.commit()

    creator_settings = get_or_create_notification_settings(creator.id)
    creator_settings.survey_portal_enabled = True
    creator_settings.survey_push_enabled = True
    creator_settings.survey_response_notifications = True

    recipient_settings = get_or_create_notification_settings(notif_user.id)
    recipient_settings.survey_portal_enabled = True
    recipient_settings.survey_push_enabled = True
    recipient_settings.survey_new_notifications = True
    db.session.commit()

    survey = Survey(
        title='Team-Feedback 2026',
        created_by=creator.id,
        visibility='public',
        public_token='survey-tok-123',
    )
    db.session.add(survey)
    db.session.commit()

    push_calls = []
    def fake_push(user_id, title, body, **kwargs):
        push_calls.append((user_id, title, body, kwargs.get('url')))
        return True

    monkeypatch.setattr('app.utils.notifications.send_push_notification', fake_push)

    # 1. Neue Umfrage -> an andere aktive Nutzer, nicht an Ersteller
    sent_new = send_survey_notification(survey, event_kind='new')
    assert sent_new == 1
    assert any(c[0] == notif_user.id and c[3] == '/surveys/fill/survey-tok-123' for c in push_calls)
    assert not any(c[0] == creator.id for c in push_calls)

    new_log = NotificationLog.query.filter_by(
        user_id=notif_user.id,
        notification_type='survey',
        source_id=survey.id,
    ).first()
    assert new_log is not None
    assert new_log.url == '/surveys/fill/survey-tok-123'

    # 2. Neue Antwort -> an Umfrage-Ersteller mit /results-URL
    sent_resp = send_survey_notification(survey, event_kind='response')
    assert sent_resp == 1
    assert any(c[0] == creator.id and c[3] == f'/surveys/{survey.id}/results' for c in push_calls)

    resp_log = NotificationLog.query.filter_by(
        user_id=creator.id,
        notification_type='survey',
        source_id=survey.id,
    ).first()
    assert resp_log is not None
    assert resp_log.url == f'/surveys/{survey.id}/results'

    # 3. Deaktivierte Sub-Toggles -> keine Benachrichtigungen
    recipient_settings.survey_new_notifications = False
    creator_settings.survey_response_notifications = False
    db.session.commit()
    count_before = len(push_calls)
    assert send_survey_notification(survey, event_kind='new') == 0
    assert send_survey_notification(survey, event_kind='response') == 0
    assert len(push_calls) == count_before


def test_inventory_dguv_due_notification_and_settings_save(app, client, notif_user, monkeypatch):
    from datetime import date, timedelta
    from app.models.inventory import Product
    from app.utils.notifications import send_inventory_dguv_due_notification

    today = date.today()
    due_p1 = Product(name='Kabeltrommel 1', dguv_next_check=today, status='available', created_by=notif_user.id)
    due_p2 = Product(name='Bohrmaschine 2', dguv_next_check=today - timedelta(days=5), status='borrowed', created_by=notif_user.id)
    retired_due = Product(name='Altgerät', dguv_next_check=today - timedelta(days=10), status='retired', created_by=notif_user.id)
    future_p = Product(name='Neugerät', dguv_next_check=today + timedelta(days=30), status='available', created_by=notif_user.id)
    db.session.add_all([due_p1, due_p2, retired_due, future_p])
    db.session.commit()

    settings = get_or_create_notification_settings(notif_user.id)
    settings.inventory_portal_enabled = True
    settings.inventory_push_enabled = True
    settings.inventory_dguv_notifications = True
    db.session.commit()

    push_calls = []
    def fake_push(user_id, title, body, **kwargs):
        push_calls.append((user_id, title, body, kwargs.get('url')))
        return True

    monkeypatch.setattr('app.utils.notifications.send_push_notification', fake_push)

    sent = send_inventory_dguv_due_notification()
    assert sent == 1
    assert len(push_calls) == 1
    assert '2' in push_calls[0][2]

    log = NotificationLog.query.filter_by(
        user_id=notif_user.id,
        notification_type='inventory',
        dedup_key=f'inventory_dguv_due:{today.isoformat()}:{notif_user.id}',
    ).first()
    assert log is not None
    assert '2' in log.body
    assert log.url == '/inventory/dashboard'

    # Sub-Toggle aus -> keine Benachrichtigung
    settings.inventory_dguv_notifications = False
    db.session.commit()
    assert send_inventory_dguv_due_notification() == 0

    # Settings-Formular darf inventory_notifications_enabled=False nicht überschreiben
    client.post('/login', data={'email': notif_user.email, 'password': 'Password123!@#'})

    resp = client.post(
        '/settings/notifications',
        data={
            'has_master_switch': '1',
            'master_notifications_enabled': 'on',
            'inventory_portal_enabled': 'on',
            'inventory_push_enabled': 'on',
            'inventory_dguv_notifications': 'on',
            # inventory_notifications_enabled bewusst ausgelassen!
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.refresh(settings)
    assert settings.inventory_notifications_enabled is False
    assert settings.inventory_dguv_notifications is True
