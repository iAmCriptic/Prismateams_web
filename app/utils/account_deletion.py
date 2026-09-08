"""Self-service and admin account erasure helpers (GDPR Art. 17)."""

from __future__ import annotations

import os
from flask import current_app, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import db

DELETE_TOKEN_SALT = 'prismateams-account-deletion'
DELETE_TOKEN_MAX_AGE = 3600  # 1 hour
PASSKEY_SESSION_KEY = 'account_deletion_passkey_verified'
PASSKEY_SESSION_TS_KEY = 'account_deletion_passkey_verified_ts'
PASSKEY_SESSION_TTL = 600  # 10 minutes


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt=DELETE_TOKEN_SALT)


def generate_deletion_token(user_id: int) -> str:
    return _serializer().dumps({'uid': int(user_id), 'purpose': 'account_deletion'})


def verify_deletion_token(token: str, expected_user_id: int | None = None) -> int | None:
    try:
        data = _serializer().loads(token, max_age=DELETE_TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get('purpose') != 'account_deletion':
        return None
    try:
        uid = int(data.get('uid'))
    except (TypeError, ValueError):
        return None
    if expected_user_id is not None and uid != int(expected_user_id):
        return None
    return uid


def user_requires_second_factor(user) -> bool:
    if bool(getattr(user, 'totp_enabled', False)):
        return True
    try:
        from app.models.passkey import UserPasskey
        return UserPasskey.query.filter_by(user_id=user.id).count() > 0
    except Exception:
        return False


def mark_passkey_verified(session) -> None:
    import time
    session[PASSKEY_SESSION_KEY] = True
    session[PASSKEY_SESSION_TS_KEY] = int(time.time())


def clear_passkey_verified(session) -> None:
    session.pop(PASSKEY_SESSION_KEY, None)
    session.pop(PASSKEY_SESSION_TS_KEY, None)


def passkey_recently_verified(session) -> bool:
    import time
    if not session.get(PASSKEY_SESSION_KEY):
        return False
    ts = session.get(PASSKEY_SESSION_TS_KEY) or 0
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return False
    return (time.time() - ts) <= PASSKEY_SESSION_TTL


def second_factor_ok(user, *, totp_code: str | None, session) -> bool:
    """True when no 2FA is required, or TOTP/passkey proof is present."""
    if not user_requires_second_factor(user):
        return True
    if getattr(user, 'totp_enabled', False) and totp_code:
        from app.utils.totp import verify_totp
        if verify_totp(user.totp_secret, totp_code.strip()):
            return True
    if passkey_recently_verified(session):
        return True
    return False


def can_self_delete(user) -> tuple[bool, str | None]:
    """Return (allowed, reason_key_suffix). reason is i18n suffix under settings.profile.delete.*"""
    if getattr(user, 'is_super_admin', False):
        return False, 'blocked_super_admin'
    if getattr(user, 'is_guest', False):
        return True, None
    return True, None


def send_account_deletion_email(user, token: str) -> bool:
    from app.utils.email_sender import render_and_send_portal_email, _mail_configured, _portal_name

    if not _mail_configured():
        current_app.logger.warning(
            'Account deletion email not sent (mail not configured) for user_id=%s',
            user.id,
        )
        return False

    try:
        confirm_url = url_for('settings.profile_delete_confirm', token=token, _external=True)
    except Exception:
        confirm_url = None

    portal_name = _portal_name()
    plain = (
        f'Konto-Löschung bestätigen\n\n'
        + (f'Link: {confirm_url}\n\n' if confirm_url else f'Token: {token}\n\n')
        + 'Der Link ist 1 Stunde gültig. Wenn Sie diese Anfrage nicht gestellt haben, ignorieren Sie diese E-Mail.'
    )
    try:
        return bool(
            render_and_send_portal_email(
                subject=f'Konto löschen bestätigen - {portal_name}',
                recipients=[user.email],
                template_name='emails/account_deletion.html',
                body_text=plain,
                user=user,
                confirm_url=confirm_url,
                token=token,
            )
        )
    except Exception as exc:
        from app.utils.log_privacy import mask_email
        current_app.logger.error(
            'Failed to send account deletion email to %s: %s',
            mask_email(user.email),
            exc,
        )
        return False


def _fallback_owner_id(user_id: int):
    """Prefer another admin, else any other user, for NOT NULL ownership FKs."""
    from app.models.user import User

    other_admin = (
        User.query.filter(User.id != user_id, User.is_admin.is_(True))
        .order_by(User.is_super_admin.desc(), User.id.asc())
        .first()
    )
    if other_admin:
        return other_admin.id
    other = (
        User.query.filter(User.id != user_id)
        .order_by(User.id.asc())
        .first()
    )
    return other.id if other else None


def _anonymize_share_access_logs(user) -> None:
    """Scrub IP/UA/guest_name that can identify the deleted person."""
    from app.models.public_share import PublicShare, ShareAccessLog

    names = set()
    for value in (
        getattr(user, 'guest_username', None),
        getattr(user, 'first_name', None),
        getattr(user, 'last_name', None),
        (f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}").strip(),
        getattr(user, 'email', None),
    ):
        if value and str(value).strip():
            names.add(str(value).strip().lower())

    if names:
        for log in ShareAccessLog.query.filter(ShareAccessLog.guest_name.isnot(None)).all():
            if (log.guest_name or '').strip().lower() in names:
                log.ip_address = None
                log.user_agent = None
                log.guest_name = '[gelöscht]'

    share_ids = [row.id for row in PublicShare.query.filter_by(created_by=user.id).all()]
    if share_ids:
        # IP/UA on shares created by the user often relate to their own tests;
        # keep third-party guest_name unless it matched the deleted user above.
        ShareAccessLog.query.filter(ShareAccessLog.public_share_id.in_(share_ids)).update(
            {
                'ip_address': None,
                'user_agent': None,
            },
            synchronize_session=False,
        )


def _erase_chat_data(user_id: int) -> None:
    from app.models.chat import Chat, ChatMember, ChatMessage, ChatPin

    ChatPin.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ChatMember.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    Chat.query.filter_by(created_by=user_id).update({'created_by': None}, synchronize_session=False)

    messages = ChatMessage.query.filter_by(sender_id=user_id).all()
    for msg in messages:
        msg.content = '[gelöscht]'
        msg.media_url = None
        msg.metadata_json = None
        msg.is_deleted = True
        msg.sender_id = None


def _erase_survey_data(user) -> None:
    from app.models.survey import Survey, SurveyResponse

    owner_id = _fallback_owner_id(user.id)
    if owner_id:
        Survey.query.filter_by(created_by=user.id).update(
            {'created_by': owner_id}, synchronize_session=False
        )
    else:
        # Last user — drop owned surveys (cascade responses/answers)
        for survey in Survey.query.filter_by(created_by=user.id).all():
            db.session.delete(survey)

    clauses = [SurveyResponse.user_id == user.id]
    if user.email:
        clauses.append(SurveyResponse.respondent_email == user.email)
    responses = SurveyResponse.query.filter(db.or_(*clauses)).all()
    for resp in responses:
        db.session.delete(resp)


def _erase_email_data(user_id: int) -> None:
    from app.models.email import (
        EmailMessage,
        EmailPermission,
        Mailbox,
        MailboxMembership,
        MailboxUserPref,
    )

    EmailPermission.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    MailboxMembership.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    MailboxUserPref.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    EmailMessage.query.filter_by(sent_by_user_id=user_id).update(
        {'sent_by_user_id': None}, synchronize_session=False
    )

    # Private mailboxes owned by the user: delete (messages cascade)
    for mailbox in Mailbox.query.filter_by(owner_id=user_id, mailbox_type='private').all():
        db.session.delete(mailbox)

    # Shared/team mailboxes: drop ownership link only
    Mailbox.query.filter(
        Mailbox.owner_id == user_id,
        Mailbox.mailbox_type != 'private',
    ).update({'owner_id': None}, synchronize_session=False)


def erase_user_account(user) -> None:
    """Permanently remove a user and dependent rows. Caller commits."""
    user_id = user.id
    owner_id = _fallback_owner_id(user_id)

    # Profile picture on disk
    if user.profile_picture:
        try:
            project_root = os.path.dirname(current_app.root_path)
            upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'profile_pics')
            old_path = os.path.join(upload_dir, user.profile_picture)
            if os.path.exists(old_path):
                os.remove(old_path)
        except OSError:
            pass

    from app.models.guest import GuestShareAccess
    GuestShareAccess.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    from app.models.role import UserModuleRole
    UserModuleRole.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    from app.models.notification import (
        NotificationSettings,
        ChatNotificationSettings,
        PushSubscription,
        NotificationLog,
    )
    NotificationSettings.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ChatNotificationSettings.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    PushSubscription.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    NotificationLog.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    from app.models.api_token import ApiToken
    ApiToken.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    from app.models.user_session import UserSession
    UserSession.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    from app.models.inventory import ProductFavorite, SavedFilter
    ProductFavorite.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    SavedFilter.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    from app.models.wiki import WikiFavorite
    WikiFavorite.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    from app.models.credential import CredentialFavorite
    CredentialFavorite.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    from app.models.comment import CommentMention
    CommentMention.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    from app.models.music import MusicProviderToken
    MusicProviderToken.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    from app.models.booking import BookingFormRoleUser
    BookingFormRoleUser.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    from app.models.passkey import UserPasskey
    UserPasskey.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    try:
        from app.models.cookie_consent import CookieConsentLog
        CookieConsentLog.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    except Exception:
        current_app.logger.exception('Cookie-consent cleanup failed for user %s', user_id)

    try:
        from app.models.cloud_import import CloudImportConnection, CloudImportJob
        CloudImportJob.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        CloudImportConnection.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    except Exception:
        current_app.logger.exception('Cloud-import cleanup failed for user %s', user_id)

    try:
        from app.models.file_converter import ConversionJob
        ConversionJob.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    except Exception:
        current_app.logger.exception('Conversion-job cleanup failed for user %s', user_id)

    try:
        from app.models.file import FileStorageException, FolderFavorite, ResourceACL
        FileStorageException.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        FolderFavorite.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        ResourceACL.query.filter_by(grantee_user_id=user_id).delete(synchronize_session=False)
    except Exception:
        current_app.logger.exception('File ACL/favorite cleanup failed for user %s', user_id)

    try:
        from app.models.calendar import EventParticipant
        EventParticipant.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    except Exception:
        current_app.logger.exception('Calendar participant cleanup failed for user %s', user_id)

    try:
        from app.models.meetings import MeetingInvite
        MeetingInvite.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    except Exception:
        current_app.logger.exception('Meeting invite cleanup failed for user %s', user_id)

    try:
        _erase_chat_data(user_id)
    except Exception:
        current_app.logger.exception('Chat erasure failed for user %s', user_id)

    try:
        _erase_email_data(user_id)
    except Exception:
        current_app.logger.exception('Email erasure failed for user %s', user_id)

    try:
        _erase_survey_data(user)
    except Exception:
        current_app.logger.exception('Survey erasure failed for user %s', user_id)

    try:
        _anonymize_share_access_logs(user)
    except Exception:
        current_app.logger.exception('ShareAccessLog anonymization failed for user %s', user_id)

    from app.models.contact import ContactFavorite, Contact
    ContactFavorite.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    if owner_id:
        Contact.query.filter_by(created_by=user_id).update(
            {'created_by': owner_id}, synchronize_session=False
        )
    else:
        Contact.query.filter_by(created_by=user_id).delete(synchronize_session=False)

    # Ownership FKs that must remain valid
    if owner_id:
        try:
            from app.models.file import File, Folder, FileVersion, ResourceACL
            Folder.query.filter_by(created_by=user_id).update(
                {'created_by': owner_id}, synchronize_session=False
            )
            Folder.query.filter_by(deleted_by=user_id).update(
                {'deleted_by': None}, synchronize_session=False
            )
            File.query.filter_by(uploaded_by=user_id).update(
                {'uploaded_by': owner_id}, synchronize_session=False
            )
            File.query.filter_by(deleted_by=user_id).update(
                {'deleted_by': None}, synchronize_session=False
            )
            FileVersion.query.filter_by(uploaded_by=user_id).update(
                {'uploaded_by': owner_id}, synchronize_session=False
            )
            ResourceACL.query.filter_by(created_by=user_id).update(
                {'created_by': owner_id}, synchronize_session=False
            )
        except Exception:
            current_app.logger.exception('File ownership reassignment failed for user %s', user_id)

        try:
            from app.models.public_share import PublicShare
            PublicShare.query.filter_by(created_by=user_id).update(
                {'created_by': owner_id}, synchronize_session=False
            )
        except Exception:
            current_app.logger.exception('PublicShare reassignment failed for user %s', user_id)

        try:
            from app.models.inventory import Checkout
            Checkout.query.filter_by(created_by=user_id).update(
                {'created_by': owner_id}, synchronize_session=False
            )
        except Exception:
            current_app.logger.exception('Checkout creator reassignment failed for user %s', user_id)

    from app.models.team import Team, TeamMember
    from app.utils.team_chat import sync_team_chat_members
    Team.query.filter_by(leader_id=user_id).update({'leader_id': None}, synchronize_session=False)
    former_team_ids = [m.team_id for m in TeamMember.query.filter_by(user_id=user_id).all()]
    TeamMember.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    for tid in former_team_ids:
        team = Team.query.get(tid)
        if team:
            sync_team_chat_members(team)

    # Soft-anonymize checkout / booking rows that reference the person by name/email
    try:
        from app.models.inventory import Checkout
        Checkout.query.filter(Checkout.borrower_id == user_id).update({
            'borrower_id': None,
            'borrower_name': '[gelöscht]',
            'contact_email': None,
        }, synchronize_session=False)
    except Exception:
        current_app.logger.exception('Checkout anonymization failed for user %s', user_id)

    try:
        from app.models.booking import BookingRequest
        if user.email:
            BookingRequest.query.filter_by(email=user.email).update({
                'applicant_name': '[gelöscht]',
                'email': f'deleted+{user_id}@invalid.local',
            }, synchronize_session=False)
    except Exception:
        current_app.logger.exception('Booking anonymization failed for user %s', user_id)

    db.session.delete(user)
