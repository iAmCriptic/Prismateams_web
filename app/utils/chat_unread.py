"""Aggregated chat unread helpers (avoid N×M COUNT queries)."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import and_, func, or_

from app import db
from app.models.chat import ChatMember, ChatMessage


def total_unread_counts_for_users(user_ids: Iterable[int]) -> dict[int, int]:
    """
    Total unread chat messages per user across all memberships.

    One grouped query instead of per-membership COUNTs.
    """
    ids = sorted({int(uid) for uid in user_ids if uid is not None})
    if not ids:
        return {}

    unread_join = and_(
        ChatMessage.chat_id == ChatMember.chat_id,
        ChatMessage.is_deleted.is_(False),
        ChatMessage.sender_id != ChatMember.user_id,
        or_(
            ChatMember.last_read_at.is_(None),
            ChatMessage.created_at > ChatMember.last_read_at,
        ),
    )
    rows = (
        db.session.query(ChatMember.user_id, func.count(ChatMessage.id))
        .outerjoin(ChatMessage, unread_join)
        .filter(ChatMember.user_id.in_(ids))
        .group_by(ChatMember.user_id)
        .all()
    )
    counts = {uid: 0 for uid in ids}
    for uid, count in rows:
        counts[int(uid)] = int(count or 0)
    return counts


def total_unread_count_for_user(user_id: int) -> int:
    """Unread total for a single user."""
    if user_id is None:
        return 0
    return total_unread_counts_for_users([user_id]).get(int(user_id), 0)


def unread_counts_by_chat_for_user(user_id: int, chat_ids: Iterable[int] | None = None) -> dict[int, int]:
    """
    Unread message counts per chat for one user (one GROUP BY query).

    If chat_ids is given, only those chats are returned (others default to 0).
    """
    if user_id is None:
        return {}

    uid = int(user_id)
    ids = None
    if chat_ids is not None:
        ids = sorted({int(cid) for cid in chat_ids if cid is not None})
        if not ids:
            return {}

    unread_join = and_(
        ChatMessage.chat_id == ChatMember.chat_id,
        ChatMessage.is_deleted.is_(False),
        ChatMessage.sender_id != ChatMember.user_id,
        or_(
            ChatMember.last_read_at.is_(None),
            ChatMessage.created_at > ChatMember.last_read_at,
        ),
    )
    query = (
        db.session.query(ChatMember.chat_id, func.count(ChatMessage.id))
        .outerjoin(ChatMessage, unread_join)
        .filter(ChatMember.user_id == uid)
    )
    if ids is not None:
        query = query.filter(ChatMember.chat_id.in_(ids))

    rows = query.group_by(ChatMember.chat_id).all()
    counts = {cid: 0 for cid in (ids or [])}
    for chat_id, count in rows:
        counts[int(chat_id)] = int(count or 0)
    return counts
