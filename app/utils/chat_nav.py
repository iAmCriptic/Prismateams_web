"""Helpers for the chat navigation list (sidebar / mobile index)."""

from datetime import datetime

from sqlalchemy import func

from app import db
from app.models.chat import Chat, ChatMember, ChatMessage, ChatPin

CHAT_PINS_MAX = 6


def wants_desktop_chat_layout(user, request):
    """Decide whether /chat/ should redirect to the main chat (desktop shell)."""
    preferred = (getattr(user, 'preferred_layout', None) or 'auto').strip().lower()
    if preferred == 'desktop':
        return True
    if preferred == 'mobile':
        return False
    ua = (request.headers.get('User-Agent') or '').lower()
    return not any(x in ua for x in ('iphone', 'ipod', 'android', 'mobile', 'ipad'))


def _unread_count_for_membership(membership, user_id):
    if not membership or not membership.last_read_at:
        return ChatMessage.query.filter(
            ChatMessage.chat_id == membership.chat_id,
            ChatMessage.sender_id != user_id,
            ChatMessage.is_deleted == False,  # noqa: E712
        ).count()
    return ChatMessage.query.filter(
        ChatMessage.chat_id == membership.chat_id,
        ChatMessage.created_at > membership.last_read_at,
        ChatMessage.sender_id != user_id,
        ChatMessage.is_deleted == False,  # noqa: E712
    ).count()


def _last_message_times(chat_ids):
    if not chat_ids:
        return {}
    rows = (
        db.session.query(ChatMessage.chat_id, func.max(ChatMessage.created_at))
        .filter(
            ChatMessage.chat_id.in_(chat_ids),
            ChatMessage.is_deleted == False,  # noqa: E712
        )
        .group_by(ChatMessage.chat_id)
        .all()
    )
    return {chat_id: created_at for chat_id, created_at in rows}


def build_chat_nav_items(user):
    """
    Build sorted chat nav items for the current user.

    Order: main chat → pinned (by pin created_at) → rest by last message desc.
    """
    memberships = ChatMember.query.filter_by(user_id=user.id).all()
    if not memberships:
        return []

    membership_by_chat = {m.chat_id: m for m in memberships}
    chats = [m.chat for m in memberships if m.chat is not None]
    chat_ids = [c.id for c in chats]

    pins = (
        ChatPin.query.filter_by(user_id=user.id)
        .filter(ChatPin.chat_id.in_(chat_ids))
        .order_by(ChatPin.created_at.asc())
        .all()
    )
    pin_order = {p.chat_id: (idx, p.created_at) for idx, p in enumerate(pins)}
    pinned_ids = set(pin_order.keys())

    last_times = _last_message_times(chat_ids)
    epoch = datetime.min

    main = [c for c in chats if c.is_main_chat]
    pinned = sorted(
        [c for c in chats if not c.is_main_chat and c.id in pinned_ids],
        key=lambda c: pin_order[c.id][0],
    )
    rest = sorted(
        [c for c in chats if not c.is_main_chat and c.id not in pinned_ids],
        key=lambda c: last_times.get(c.id) or epoch,
        reverse=True,
    )
    ordered = main + pinned + rest

    items = []
    for chat in ordered:
        membership = membership_by_chat.get(chat.id)
        items.append({
            'chat': chat,
            'nav_id': 1 if chat.is_main_chat else chat.id,
            'member_count': len(chat.members) if chat.members is not None else 0,
            'unread_count': _unread_count_for_membership(membership, user.id) if membership else 0,
            'is_pinned': chat.id in pinned_ids and not chat.is_main_chat,
            'can_pin': not chat.is_main_chat,
        })
    return items


def toggle_chat_pin(user, chat_id):
    """
    Toggle pin. Returns (ok, pinned, error_message, pins_count).
    Main chat cannot be pinned. Max CHAT_PINS_MAX.
    """
    if not user or getattr(user, 'is_guest', False):
        return False, False, 'Keine Berechtigung.', 0

    chat = Chat.query.get(chat_id)
    if not chat:
        return False, False, 'Chat nicht gefunden.', 0
    if chat.is_main_chat:
        return False, False, 'Der Haupt-Chat kann nicht angepinnt werden.', 0

    membership = ChatMember.query.filter_by(chat_id=chat.id, user_id=user.id).first()
    if not membership:
        return False, False, 'Sie sind kein Mitglied dieses Chats.', 0

    existing = ChatPin.query.filter_by(user_id=user.id, chat_id=chat.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        count = ChatPin.query.filter_by(user_id=user.id).count()
        return True, False, None, count

    count = ChatPin.query.filter_by(user_id=user.id).count()
    if count >= CHAT_PINS_MAX:
        return False, False, f'Maximal {CHAT_PINS_MAX} Chats anpinnen.', count

    db.session.add(ChatPin(user_id=user.id, chat_id=chat.id))
    db.session.commit()
    return True, True, None, count + 1
