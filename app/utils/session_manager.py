"""
Session-Management Utility für die Verwaltung von Benutzer-Sessions.
"""
from flask import session, request
from datetime import datetime, timedelta
from app import db
from app.models.user_session import UserSession
import secrets


def generate_session_id():
    """Generiert eine eindeutige Session-ID."""
    return secrets.token_urlsafe(32)


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
    for sess in sessions:
        sess.is_current = (sess.session_id == current_session_id) if include_current else False
    
    return sessions


def get_user_sessions_with_recent(user_id, include_current=True, hours=24):
    """
    Holt alle aktiven Sessions und inaktive Sessions der letzten N Stunden eines Benutzers.
    
    Args:
        user_id: Die Benutzer-ID
        include_current: Ob die aktuelle Session markiert werden soll
        hours: Anzahl der Stunden für inaktive Sessions (Standard: 24)
    
    Returns:
        Liste aller relevanten Sessions, sortiert nach last_activity (neueste zuerst)
    """
    # Hole alle aktiven Sessions
    active_sessions = UserSession.query.filter_by(
        user_id=user_id,
        is_active=True
    ).all()
    
    # Hole inaktive Sessions der letzten N Stunden
    cutoff_time = datetime.utcnow() - timedelta(hours=hours)
    inactive_sessions = UserSession.query.filter(
        UserSession.user_id == user_id,
        UserSession.is_active == False,
        UserSession.last_activity >= cutoff_time
    ).all()
    
    # Kombiniere beide Listen
    all_sessions = active_sessions + inactive_sessions
    
    # Sortiere nach last_activity (neueste zuerst)
    all_sessions.sort(key=lambda s: s.last_activity, reverse=True)
    
    # Markiere die aktuelle Session
    current_session_id = session.get('session_id')
    for sess in all_sessions:
        sess.is_current = (sess.session_id == current_session_id) if include_current else False
    
    return all_sessions


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
