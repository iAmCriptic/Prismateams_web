"""Shared chat send helpers used by web and API routes."""

from __future__ import annotations

import logging

from flask import current_app

from app import db
from app.models.chat import ChatMember, ChatMessage
from app.utils.chat_unread import total_unread_counts_for_users
from app.utils.dashboard_events import emit_dashboard_update
from app.utils.notifications import enqueue_chat_notification

logger = logging.getLogger(__name__)


def resolve_message_type(filename, mimetype):
    ext = filename.rsplit(".", 1)[1].lower()
    mimetype = (mimetype or "").lower()
    if ext in {"png", "jpg", "jpeg", "gif", "webp"} or mimetype.startswith("image/"):
        return "image"
    if ext in {"mp4", "mov", "avi"} or mimetype.startswith("video/"):
        return "video"
    if ext in {"mp3", "wav", "m4a", "aac", "ogg"} or mimetype.startswith("audio/") or filename.startswith("voice_message"):
        return "voice"
    if ext == "webm":
        return "voice" if mimetype.startswith("audio/") or filename.startswith("voice_message") else "video"
    return "file"


def has_structured_message_content(message_type, metadata):
    if not isinstance(metadata, dict):
        return False
    if message_type == "folder_link":
        folder_id = metadata.get("folder_id")
        folder_name = (metadata.get("folder_name") or "").strip()
        try:
            has_folder_id = int(folder_id) > 0
        except (TypeError, ValueError):
            has_folder_id = False
        return has_folder_id or bool(folder_name)
    if message_type == "calendar_event":
        return bool((metadata.get("title") or "").strip())
    if message_type == "poll":
        question = (metadata.get("question") or "").strip()
        options = metadata.get("options") if isinstance(metadata.get("options"), list) else []
        valid_options = [
            option for option in options
            if isinstance(option, dict) and (option.get("text") or "").strip()
        ]
        return bool(question and len(valid_options) >= 2)
    if message_type == "meeting":
        try:
            meeting_id = int(metadata.get("meeting_id"))
        except (TypeError, ValueError):
            meeting_id = 0
        return meeting_id > 0 or bool((metadata.get("join_url") or "").strip())
    return False


def persist_outgoing_message(*, chat, sender_id, content, message_type, media_url, metadata):
    """Insert a chat message, enqueue push, emit dashboard unread updates."""
    message = ChatMessage(
        chat_id=chat.id,
        sender_id=sender_id,
        content=content,
        message_type=message_type,
        media_url=media_url,
    )
    if isinstance(metadata, dict):
        message.set_metadata(metadata)
    db.session.add(message)
    db.session.commit()

    try:
        enqueue_chat_notification(
            chat_id=chat.id,
            sender_id=sender_id,
            message_content=content or f"[{message_type}]",
            chat_name=chat.name,
            message_id=message.id,
        )
    except Exception:
        logger.warning("Chat-Push-Benachrichtigung fehlgeschlagen", exc_info=True)

    try:
        chat_members = ChatMember.query.filter_by(chat_id=chat.id).all()
        member_ids = [member.user_id for member in chat_members if member.user_id != sender_id]
        if member_ids:
            unread_by_user = total_unread_counts_for_users(member_ids)
            for user_id in member_ids:
                emit_dashboard_update(
                    user_id,
                    "chat_update",
                    {"count": unread_by_user.get(user_id, 0)},
                )
    except Exception as exc:
        current_app.logger.error("Fehler beim Senden der Dashboard-Updates für Chat: %s", exc)

    return message
