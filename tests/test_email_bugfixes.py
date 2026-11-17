"""Tests for email notification deduplication/filtering and INBOX.* folder tree loading."""

import os
os.environ['PRISMATEAMS_SKIP_BACKGROUND_JOBS'] = '1'
os.environ['PRISMATEAMS_SKIP_SCHEMA_INIT'] = '1'
os.environ['PRISMATEAMS_RUNNING_MIGRATIONS'] = '1'
os.environ['FLASK_ENV'] = 'testing'

from datetime import datetime
from unittest.mock import patch

import pytest

from app import create_app, db
from app.blueprints.email.folder_sync import (
    _empty_stats,
    _is_inbox_folder,
    sync_emails_from_folder,
)
from app.blueprints.email.imap_client import is_standard_mail_folder, strip_inbox_prefix
from app.blueprints.email.mailbox import _build_folder_tree
from app.models.email import EmailFolder, EmailMessage
from app.models.notification import NotificationSettings
from app.models.user import User
from app.utils.notifications import send_email_notification


@pytest.fixture(scope='module')
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
def db_ctx(app_instance):
    with app_instance.app_context():
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()


def test_inbox_prefixed_standard_folders_and_display_names():
    assert strip_inbox_prefix('INBOX.Drafts') == 'Drafts'
    assert strip_inbox_prefix('INBOX/Trash') == 'Trash'
    assert strip_inbox_prefix('Drafts') == 'Drafts'

    for name in ('INBOX', 'INBOX.Drafts', 'INBOX.Sent', 'INBOX.Trash', 'INBOX.Spam', 'INBOX/Archive'):
        assert is_standard_mail_folder(name) is True

    assert is_standard_mail_folder('INBOX.Kunden') is False

    assert EmailFolder.get_folder_display_name('INBOX') == 'Posteingang'
    assert EmailFolder.get_folder_display_name('INBOX.Drafts') == 'Entwürfe'
    assert EmailFolder.get_folder_display_name('INBOX.Sent') == 'Gesendet'
    assert EmailFolder.get_folder_display_name('INBOX.Trash') == 'Papierkorb'
    assert EmailFolder.get_folder_display_name('INBOX.Spam') == 'Spam'


def test_build_folder_tree_includes_inbox_children_and_standard_order(db_ctx):
    folders = [
        EmailFolder(name='INBOX', display_name='Posteingang', folder_type='standard', is_system=True, separator='.'),
        EmailFolder(name='INBOX.Spam', display_name='Spam', folder_type='standard', is_system=True, parent_folder='INBOX', separator='.'),
        EmailFolder(name='INBOX.Trash', display_name='Papierkorb', folder_type='standard', is_system=True, parent_folder='INBOX', separator='.'),
        EmailFolder(name='INBOX.Sent', display_name='Gesendet', folder_type='standard', is_system=True, parent_folder='INBOX', separator='.'),
        EmailFolder(name='INBOX.Drafts', display_name='Entwürfe', folder_type='standard', is_system=True, parent_folder='INBOX', separator='.'),
        EmailFolder(name='INBOX.Kunden', display_name='Kunden', folder_type='custom', is_system=False, parent_folder='INBOX', separator='.'),
        EmailFolder(name='INBOX.Kunden.VIP', display_name='VIP', folder_type='custom', is_system=False, parent_folder='INBOX.Kunden', separator='.'),
    ]
    tree = _build_folder_tree(folders)
    names = [entry['folder'].name for entry in tree]
    assert names == [
        'INBOX',
        'INBOX.Drafts',
        'INBOX.Sent',
        'INBOX.Trash',
        'INBOX.Spam',
        'INBOX.Kunden',
        'INBOX.Kunden.VIP',
    ]
    depths = {entry['folder'].name: entry['depth'] for entry in tree}
    assert depths['INBOX.Kunden'] == 0
    assert depths['INBOX.Kunden.VIP'] == 1


def test_send_email_notification_ignores_read_sent_deleted_and_non_inbox(db_ctx):
    user = User(
        first_name='Mail',
        last_name='User',
        email='mailuser@example.com',
        is_active=True,
        is_admin=True,
        is_email_confirmed=True,
        notifications_enabled=True,
        email_notifications=True,
    )
    user.set_password('Secret123!')
    db_ctx.session.add(user)
    db_ctx.session.flush()
    db_ctx.session.add(NotificationSettings(
        user_id=user.id,
        email_notifications_enabled=True,
        email_portal_enabled=True,
        email_push_enabled=False,
    ))

    # Even with an existing unread email in INBOX, notifying for a read/spam/sent/deleted email must return 0.
    unread_inbox = EmailMessage(
        message_id='<unread-inbox@example.com>',
        sender='a@example.com',
        subject='Unread',
        recipients='mailuser@example.com',
        folder='INBOX',
        is_read=False,
        is_sent=False,
        is_deleted_imap=False,
        received_at=datetime.utcnow(),
    )
    read_inbox = EmailMessage(
        message_id='<read-inbox@example.com>',
        sender='a@example.com',
        subject='Read',
        recipients='mailuser@example.com',
        folder='INBOX',
        is_read=True,
        is_sent=False,
        is_deleted_imap=False,
        received_at=datetime.utcnow(),
    )
    spam_unread = EmailMessage(
        message_id='<spam@example.com>',
        sender='spam@example.com',
        subject='Spam',
        recipients='mailuser@example.com',
        folder='INBOX.Spam',
        is_read=False,
        is_sent=False,
        is_deleted_imap=False,
        received_at=datetime.utcnow(),
    )
    deleted_unread = EmailMessage(
        message_id='<deleted@example.com>',
        sender='a@example.com',
        subject='Deleted',
        recipients='mailuser@example.com',
        folder='INBOX',
        is_read=False,
        is_sent=False,
        is_deleted_imap=True,
        received_at=datetime.utcnow(),
    )
    db_ctx.session.add_all([unread_inbox, read_inbox, spam_unread, deleted_unread])
    db_ctx.session.commit()

    with patch('app.utils.notifications.notify_user', return_value=True) as mock_notify:
        assert send_email_notification(read_inbox.id) == 0
        assert send_email_notification(spam_unread.id) == 0
        assert send_email_notification(deleted_unread.id) == 0
        mock_notify.assert_not_called()

        assert send_email_notification(unread_inbox.id) == 1
        mock_notify.assert_called_once()


def test_sync_emails_from_folder_only_notifies_on_new_unread_inbox(db_ctx):
    assert _is_inbox_folder('INBOX') is True
    assert _is_inbox_folder('INBOX.Trash') is False
    assert 'new_unread_inbox_ids' in _empty_stats()

    def _fake_upsert_no_unread(_conn, folder_name, _mb_id, _fetched, stats):
        stats['new_emails'] += 1  # e.g. already-read or non-INBOX email

    with (
        patch('app.blueprints.email.folder_sync.connect_folder_for_sync', return_value=(True, None, (object(), False, None))),
        patch('app.blueprints.email.folder_sync.fetch_folder_messages', return_value=(True, None, object())),
        patch('app.blueprints.email.folder_sync.apply_folder_flags'),
        patch('app.blueprints.email.folder_sync.upsert_folder_emails', side_effect=_fake_upsert_no_unread),
        patch('app.blueprints.email.folder_sync.send_email_notification') as mock_send,
    ):
        ok, _ = sync_emails_from_folder('INBOX.Trash')
        assert ok is True
        mock_send.assert_not_called()

    def _fake_upsert_unread(_conn, folder_name, _mb_id, _fetched, stats):
        stats['new_emails'] += 1
        stats['new_unread_inbox_ids'].append(999)

    with (
        patch('app.blueprints.email.folder_sync.connect_folder_for_sync', return_value=(True, None, (object(), False, None))),
        patch('app.blueprints.email.folder_sync.fetch_folder_messages', return_value=(True, None, object())),
        patch('app.blueprints.email.folder_sync.apply_folder_flags'),
        patch('app.blueprints.email.folder_sync.upsert_folder_emails', side_effect=_fake_upsert_unread),
        patch('app.blueprints.email.folder_sync.send_email_notification') as mock_send,
    ):
        ok, _ = sync_emails_from_folder('INBOX')
        assert ok is True
        mock_send.assert_called_once_with(999)
