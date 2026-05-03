"""
Session-Management Utility für die Verwaltung von Benutzer-Sessions.
"""
from flask import session, request
from datetime import datetime
from app import db
from app.models.user_session import UserSession
import secrets
import re


def generate_session_id():
    """Generiert eine eindeutige Session-ID."""
    return secrets.token_urlsafe(32)


def _detect_platform(user_agent):
    """Erkennt das Betriebssystem aus dem User-Agent-String."""
    ua = (user_agent or "").lower()

    if "android" in ua:
        return "Android"
    if any(token in ua for token in ["iphone", "ipad", "ipod"]):
        return "iOS"
    if "windows" in ua:
        return "Windows"
    if any(token in ua for token in ["mac os x", "macintosh"]):
        return "macOS"
    if "linux" in ua:
        return "Linux"

    return "Unbekanntes OS"


def _detect_browser(user_agent):
    """Erkennt den Browser aus dem User-Agent-String."""
    ua = user_agent or ""
    ua_lower = ua.lower()

    # Reihenfolge wichtig: Edge/Opera enthalten teils auch "Chrome"
    if "edg/" in ua_lower:
        return "Edge"
    if "opr/" in ua_lower or "opera" in ua_lower:
        return "Opera"
    if "firefox/" in ua_lower:
        return "Firefox"
    if "safari/" in ua_lower and "chrome/" not in ua_lower and "chromium/" not in ua_lower:
        return "Safari"
    if "chrome/" in ua_lower or "chromium/" in ua_lower:
        return "Chrome"

    return "Unbekannter Browser"


def format_device_label(user_agent):
    """Formatiert einen lesbaren Gerätenamen aus dem User-Agent."""
    if not user_agent:
        return "Unbekanntes Gerät"

    platform = _detect_platform(user_agent)
    browser = _detect_browser(user_agent)

    # Fallback: falls beides unbekannt ist, rohen UA gekürzt anzeigen
    if platform == "Unbekanntes OS" and browser == "Unbekannter Browser":
        sanitized = re.sub(r"\s+", " ", user_agent).strip()
        return sanitized[:80] if sanitized else "Unbekanntes Gerät"

    return f"{platform} · {browser}"


def create_session(user_id):
    """Erstellt eine neue Session für einen Benutzer."""
    session_id = generate_session_id()
    
    # Hole IP-Adresse und User-Agent
    ip_address = request.remote_addr
    user_agent = request.headers.get('User-Agent', '')[:500]  # Max 500 Zeichen
    
    # Erstelle Session-Eintrag in der Datenbank
    user_session = UserSession(
        user_id=user_id,
        session_id=session_id,
        ip_address=ip_address,
        user_agent=user_agent,
        is_active=True
    )
    
    db.session.add(user_session)
    db.session.commit()
    
    # Speichere Session-ID in Flask-Session
    session['session_id'] = session_id
    
    return user_session


def get_user_sessions(user_id, include_current=True):
    """Holt alle aktiven Sessions eines Benutzers."""
    query = UserSession.query.filter_by(
        user_id=user_id,
        is_active=True
    ).order_by(UserSession.last_activity.desc())
    
    sessions = query.all()
    
    # Markiere die aktuelle Session
    current_session_id = session.get('session_id')

    # Defensive Reparatur:
    # Wenn die aktuelle Browser-Session noch keinen DB-Eintrag hat (oder der Eintrag
    # inaktiv/gelöscht wurde), legen wir eine neue aktive Session an, damit die
    # Geräteübersicht nie fälschlich "keine Sitzungen" zeigt.
    if include_current:
        current_exists = bool(current_session_id) and any(
            sess.session_id == current_session_id for sess in sessions
        )

        if not current_exists:
            created_session = create_session(user_id)
            current_session_id = created_session.session_id
            sessions = query.all()

    for sess in sessions:
        sess.is_current = (sess.session_id == current_session_id) if include_current else False
        sess.device_label = format_device_label(sess.user_agent)
    
    return sessions


def get_current_session(user_id):
    """Holt die aktuelle Session eines Benutzers."""
    current_session_id = session.get('session_id')
    if not current_session_id:
        return None
    
    return UserSession.query.filter_by(
        user_id=user_id,
        session_id=current_session_id,
        is_active=True
    ).first()


def update_session_activity(user_id):
    """Aktualisiert die Aktivität der aktuellen Session."""
    current_session = get_current_session(user_id)
    if current_session:
        current_session.update_activity()


def revoke_session(user_id, session_id):
    """Meldet eine spezifische Session ab."""
    user_session = UserSession.query.filter_by(
        user_id=user_id,
        session_id=session_id,
        is_active=True
    ).first()
    
    if user_session:
        user_session.revoke()
        return True
    
    return False


def revoke_all_sessions(user_id, exclude_current=True):
    """Meldet alle Sessions eines Benutzers ab (außer der aktuellen)."""
    current_session_id = session.get('session_id') if exclude_current else None
    
    sessions = UserSession.query.filter_by(
        user_id=user_id,
        is_active=True
    ).all()
    
    revoked_count = 0
    for sess in sessions:
        if exclude_current and sess.session_id == current_session_id:
            continue
        sess.revoke()
        revoked_count += 1
    
    return revoked_count


def revoke_session_by_id(session_id):
    """Meldet eine Session anhand ihrer ID ab (für Logout)."""
    user_session = UserSession.query.filter_by(
        session_id=session_id,
        is_active=True
    ).first()
    
    if user_session:
        user_session.revoke()
        return True
    
    return False
