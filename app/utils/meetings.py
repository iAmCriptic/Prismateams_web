"""Meeting create/invite/access helpers."""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import Iterable, Optional

from flask import url_for
from flask_login import current_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import or_

from app import db
from app.models.chat import Chat, ChatMember, ChatMessage
from app.models.meetings import (
    MEETING_ACCESS_INVITE,
    MEETING_ACCESS_PUBLIC,
    MEETING_STATUS_ACTIVE,
    MEETING_STATUS_ENDED,
    Meeting,
    MeetingInvite,
)
from app.models.user import User
from app.utils.chat_service import persist_outgoing_message
from app.utils.common import is_module_enabled
from app.utils.i18n import translate

logger = logging.getLogger(__name__)

AVATAR_SALT = 'meetings-avatar'
AVATAR_MAX_AGE = 60 * 60 * 24
GUEST_NAME_MIN = 2
GUEST_NAME_MAX = 80


def _avatar_serializer():
    from flask import current_app
    return URLSafeTimedSerializer(current_app.secret_key, salt=AVATAR_SALT)


def sign_avatar_token(user_id: int) -> str:
    return _avatar_serializer().dumps(int(user_id))


def load_avatar_user_id(token: str) -> Optional[int]:
    try:
        value = _avatar_serializer().loads(token, max_age=AVATAR_MAX_AGE)
        return int(value)
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None


def new_room_id() -> str:
    return f'pt-{secrets.token_urlsafe(12)}'


def new_guest_token() -> str:
    return secrets.token_urlsafe(24)


def list_inviteable_users(exclude_user_id: Optional[int] = None) -> list[User]:
    from app.utils.chat_visibility import selectable_chat_user_filters

    query = User.query.filter(*selectable_chat_user_filters(include_guests=False))
    if exclude_user_id:
        query = query.filter(User.id != exclude_user_id)
    return query.order_by(User.first_name.asc(), User.last_name.asc()).all()


def visible_meetings_query(user: User, status: str):
    invited_ids = db.session.query(MeetingInvite.meeting_id).filter_by(user_id=user.id)
    return Meeting.query.filter(
        Meeting.status == status,
        or_(
            Meeting.access_mode == MEETING_ACCESS_PUBLIC,
            Meeting.created_by == user.id,
            Meeting.id.in_(invited_ids),
        ),
    ).order_by(Meeting.created_at.desc())


def user_can_view_meeting(user: Optional[User], meeting: Meeting) -> bool:
    if user is None:
        return False
    if meeting.created_by == user.id:
        return True
    if MeetingInvite.query.filter_by(meeting_id=meeting.id, user_id=user.id).first() is not None:
        return True
    if meeting.is_public:
        from app.utils.access_control import has_module_access
        return has_module_access(user, 'module_meetings')
    return False


def user_can_join_meeting(user: Optional[User], meeting: Meeting, *, guest_token: Optional[str] = None) -> bool:
    if not meeting.is_active:
        return False
    stored = meeting.guest_join_token or ''
    provided = guest_token or ''
    if provided and stored:
        try:
            token_ok = hmac.compare_digest(provided, stored)
        except (TypeError, ValueError):
            token_ok = False
        if token_ok:
            return True
    return user_can_view_meeting(user, meeting)


def user_can_end_meeting(user: User, meeting: Meeting) -> bool:
    if not meeting.is_active:
        return False
    if meeting.created_by == user.id:
        return True
    return bool(getattr(user, 'is_admin', False) or getattr(user, 'is_super_admin', False))


def add_invites(meeting: Meeting, user_ids: Iterable[int], *, host_id: int) -> list[int]:
    wanted = {int(uid) for uid in user_ids if uid}
    wanted.add(int(host_id))
    existing = {
        invite.user_id
        for invite in MeetingInvite.query.filter_by(meeting_id=meeting.id).all()
    }
    added = []
    valid_ids = {
        row.id
        for row in User.query.filter(User.id.in_(wanted), User.is_active.is_(True)).all()
    }
    for user_id in valid_ids:
        if user_id in existing:
            continue
        db.session.add(MeetingInvite(meeting_id=meeting.id, user_id=user_id))
        if user_id != host_id:
            added.append(user_id)
    return added


def create_meeting(
    *,
    title: str,
    created_by: int,
    access_mode: str,
    invite_user_ids: Optional[Iterable[int]] = None,
    chat_id: Optional[int] = None,
) -> Meeting:
    clean_title = (title or '').strip() or translate('meetings.default_title')
    mode = MEETING_ACCESS_INVITE if access_mode == MEETING_ACCESS_INVITE else MEETING_ACCESS_PUBLIC
    meeting = Meeting(
        title=clean_title[:255],
        room_id=new_room_id(),
        access_mode=mode,
        status=MEETING_STATUS_ACTIVE,
        created_by=created_by,
        chat_id=chat_id,
        guest_join_token=new_guest_token(),
    )
    db.session.add(meeting)
    db.session.flush()
    if mode == MEETING_ACCESS_INVITE:
        add_invites(meeting, invite_user_ids or [], host_id=created_by)
    else:
        add_invites(meeting, [created_by], host_id=created_by)
    db.session.commit()
    notify_meeting_invites(meeting)
    return meeting


def end_meeting(meeting: Meeting, ended_by: int) -> None:
    """Beenden = löschen. Beendete Meetings werden nicht aufbewahrt."""
    db.session.delete(meeting)
    db.session.commit()


def purge_ended_meetings() -> None:
    Meeting.query.filter_by(status=MEETING_STATUS_ENDED).delete(synchronize_session=False)
    db.session.commit()


def post_chat_meeting_card(meeting: Meeting, chat: Chat, sender_id: int) -> ChatMessage:
    metadata = {
        'meeting_id': meeting.id,
        'title': meeting.title,
        'join_url': url_for('meetings.join', meeting_id=meeting.id),
        'access_mode': meeting.access_mode,
        'status': meeting.status,
    }
    return persist_outgoing_message(
        chat=chat,
        sender_id=sender_id,
        content='',
        message_type='meeting',
        media_url=None,
        metadata=metadata,
    )


def create_meeting_from_chat(chat: Chat, user: User) -> Meeting:
    member_ids = [m.user_id for m in ChatMember.query.filter_by(chat_id=chat.id).all()]
    chat_name = (chat.name or '').strip() or translate('meetings.default_title')
    title = translate('meetings.chat_title', name=chat_name)
    meeting = create_meeting(
        title=title,
        created_by=user.id,
        access_mode=MEETING_ACCESS_INVITE,
        invite_user_ids=member_ids,
        chat_id=chat.id,
    )
    post_chat_meeting_card(meeting, chat, user.id)
    return meeting


def notify_meeting_invites(meeting: Meeting) -> None:
    from app.utils.notifications import notify_user

    if meeting.is_public or meeting.chat_id:
        return
    invitee_ids = [
        invite.user_id
        for invite in MeetingInvite.query.filter_by(meeting_id=meeting.id).all()
        if invite.user_id != meeting.created_by
    ]
    join_url = url_for('meetings.join', meeting_id=meeting.id)
    for user_id in invitee_ids:
        try:
            notify_user(
                user_id,
                title=translate('meetings.notify.title'),
                body=translate('meetings.notify.body', title=meeting.title),
                url=join_url,
                notification_type='meeting',
                dedup_key=f'meeting:{meeting.id}:{user_id}',
                source_id=meeting.id,
                data={'meeting_id': meeting.id, 'type': 'meeting'},
            )
        except Exception:
            logger.warning('Meeting-Benachrichtigung fehlgeschlagen', exc_info=True)


def meetings_runtime_ready() -> bool:
    """Modul-Flag plus erreichbare MiroTalk-Integration."""
    from app.utils.mirotalk import mirotalk_configured
    return is_module_enabled('module_meetings') and mirotalk_configured()


def meetings_module_available(user=None) -> bool:
    if not meetings_runtime_ready():
        return False
    if user is None:
        user = current_user if current_user and current_user.is_authenticated else None
    if user is None:
        return False
    from app.utils.access_control import has_module_access
    return has_module_access(user, 'module_meetings')


def sanitize_guest_name(raw: str) -> str:
    name = ' '.join((raw or '').split())
    if len(name) < GUEST_NAME_MIN:
        return ''
    return name[:GUEST_NAME_MAX]
