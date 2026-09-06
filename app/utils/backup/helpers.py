"""Shared helpers for backup import/export."""

from typing import Optional

from app import db
from app.models import Chat, User

def _ensure_local_main_chat(current_user_id: Optional[int] = None) -> Chat:
    """Liefert den lokalen Hauptchat; legt ihn bei Bedarf an."""
    main = Chat.query.filter_by(is_main_chat=True).order_by(Chat.id.asc()).first()
    if main:
        return main
    creator_id = current_user_id
    if not creator_id:
        admin = User.query.filter_by(is_admin=True).order_by(User.id.asc()).first()
        creator_id = admin.id if admin else None
    if not creator_id:
        first_user = User.query.order_by(User.id.asc()).first()
        creator_id = first_user.id if first_user else None
    if not creator_id:
        raise RuntimeError('Kein Benutzer für Hauptchat vorhanden')
    main = Chat(
        name='Haupt-Chat',
        description='Hauptchat für alle Benutzer',
        is_main_chat=True,
        is_direct_message=False,
        created_by=creator_id,
    )
    db.session.add(main)
    db.session.flush()
    return main


def _message_fingerprint(sender_id: int, content: Optional[str], created_at, media_name: Optional[str] = None) -> str:
    import hashlib
    created = created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at or '')
    raw = f"{sender_id}|{created}|{(content or '')}|{(media_name or '')}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
