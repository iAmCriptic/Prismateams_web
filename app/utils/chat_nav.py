"""Helpers for the chat navigation list (sidebar / mobile index)."""

from datetime import datetime

from sqlalchemy import func

from app import db
from app.models.chat import Chat, ChatMember, ChatMessage, ChatPin

CHAT_PINS_MAX = 6


def _team_chat_visible(team_id) -> bool:
    from app.utils.team_module_settings import is_team_section_enabled
    return is_team_section_enabled(team_id, 'chat')


def wants_desktop_chat_layout(user, request):
    """Decide whether /chat/ should redirect to the main chat (desktop shell)."""
    preferred = (getattr(user, 'preferred_layout', None) or 'auto').strip().lower()
    if preferred == 'desktop':
        return True
    if preferred == 'mobile':
        return False

    # Chromium Client Hints are more reliable than UA when DevTools spoofs size
    ch_mobile = (request.headers.get('Sec-CH-UA-Mobile') or '').strip()
    if ch_mobile == '?0':
        return True
    if ch_mobile == '?1':
        return False

    ua = (request.headers.get('User-Agent') or '').lower()
    # Phones only — keep large tablets / desktop UA on the shell layout
    phone_markers = ('iphone', 'ipod', 'android', 'mobile')
    if any(x in ua for x in phone_markers) and 'ipad' not in ua:
        # Android tablets often include "android" without "mobile"
        if 'android' in ua and 'mobile' not in ua:
            return True
        return False
    return True


def get_main_chat():
    return Chat.query.filter_by(is_main_chat=True).order_by(Chat.id.asc()).first()


def dedupe_main_chats():
    """
    Ensure only one chat has is_main_chat=True.
    Keeps the oldest main chat, demotes extras, merges missing memberships.
    Empty duplicate main chats are removed so they vanish from the nav.
    """
    mains = Chat.query.filter_by(is_main_chat=True).order_by(Chat.id.asc()).all()
    if len(mains) <= 1:
        return mains[0] if mains else None

    keeper = mains[0]
    if (keeper.name or '').strip().lower() in {'team chat', 'team-chat', ''}:
        keeper.name = 'Haupt-Chat'

    keeper_member_ids = {
        m.user_id for m in ChatMember.query.filter_by(chat_id=keeper.id).all()
    }

    for extra in mains[1:]:
        for membership in ChatMember.query.filter_by(chat_id=extra.id).all():
            if membership.user_id not in keeper_member_ids:
                db.session.add(ChatMember(chat_id=keeper.id, user_id=membership.user_id))
                keeper_member_ids.add(membership.user_id)

        has_messages = ChatMessage.query.filter_by(chat_id=extra.id, is_deleted=False).count() > 0
        if not has_messages:
            # Pure setup duplicate — drop it completely
            ChatMember.query.filter_by(chat_id=extra.id).delete()
            ChatPin.query.filter_by(chat_id=extra.id).delete()
            db.session.delete(extra)
        else:
            extra.is_main_chat = False
            if (extra.name or '').strip().lower() in {'haupt-chat', 'team chat', 'team-chat'}:
                extra.name = f'{extra.name or "Chat"} ({extra.id})'

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return Chat.query.filter_by(is_main_chat=True).order_by(Chat.id.asc()).first()
    return keeper


def user_is_chat_member(user, chat_id):
    if not user or not chat_id:
        return False
    return ChatMember.query.filter_by(chat_id=chat_id, user_id=user.id).first() is not None


def ensure_user_in_main_chat(user):
    """
    Self-heal: active users opening the chat module should be in the Haupt-Chat.
    Fixes fresh installs where the main chat was created before the admin existed.
    Returns the membership or None.
    """
    if not user or getattr(user, 'is_guest', False) or not getattr(user, 'is_active', True):
        return None

    main_chat = dedupe_main_chats() or get_main_chat()
    if not main_chat:
        return None

    existing = ChatMember.query.filter_by(chat_id=main_chat.id, user_id=user.id).first()
    if existing:
        return existing

    membership = ChatMember(chat_id=main_chat.id, user_id=user.id)
    db.session.add(membership)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return ChatMember.query.filter_by(chat_id=main_chat.id, user_id=user.id).first()
    return membership


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

    main = [c for c in chats if c.is_main_chat][:1]  # only one Haupt-Chat in the nav
    team_chats = sorted(
        [
            c for c in chats
            if not c.is_main_chat and c.team_id
            and _team_chat_visible(c.team_id)
        ],
        key=lambda c: (c.name or '').lower(),
    )
    team_ids = {c.id for c in team_chats}
    pinned = sorted(
        [c for c in chats if not c.is_main_chat and c.id not in team_ids and c.id in pinned_ids],
        key=lambda c: pin_order[c.id][0],
    )
    rest = sorted(
        [c for c in chats if not c.is_main_chat and c.id not in team_ids and c.id not in pinned_ids],
        key=lambda c: last_times.get(c.id) or epoch,
        reverse=True,
    )
    ordered = main + team_chats + pinned + rest

    items = []
    for chat in ordered:
        membership = membership_by_chat.get(chat.id)
        is_team = bool(chat.team_id)
        items.append({
            'chat': chat,
            'nav_id': 1 if chat.is_main_chat else chat.id,
            'member_count': len(chat.members) if chat.members is not None else 0,
            'unread_count': _unread_count_for_membership(membership, user.id) if membership else 0,
            'is_pinned': chat.id in pinned_ids and not chat.is_main_chat and not is_team,
            'can_pin': not chat.is_main_chat and not is_team,
            'is_team_chat': is_team,
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
    if chat.team_id:
        return False, False, 'Team-Chats können nicht angepinnt werden.', 0

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
