"""
Session-Management Utility für die Verwaltung von Benutzer-Sessions.
"""
from flask import session, request
from datetime import datetime, timedelta
from app import db
from app.models.user_session import UserSession
import secrets
import re

# Short-TTL cache in Flask-Session: skip DB lookup on most requests
_PORTAL_SESS_OK_AT = '_portal_sess_ok_at'
_PORTAL_SESS_OK_SID = '_portal_sess_ok_sid'
_PORTAL_SESS_LAST_ACTIVITY = '_portal_sess_last_activity'
_PORTAL_SESS_DIRTY = '_portal_sess_dirty_activity'
PORTAL_SESSION_CACHE_TTL = timedelta(seconds=60)
PORTAL_SESSION_ACTIVITY_INTERVAL = timedelta(minutes=1)
PORTAL_SESSION_INACTIVITY_LIMIT = timedelta(days=30)


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


def rotate_session_on_login(preserve_keys=None):
    """
    Leert die Flask-Session vor dem Setzen von Auth-Keys (Session-Fixation-Schutz).

    Erhält ausgewählte Keys (Sprache, Cookie-Consent, OAuth-Zwischenstände).
    """
    if preserve_keys is None:
        preserve_keys = (
            'language',
            'cookie_consent',
            'cookie_consent_v',
            'google_oauth_state',
            'google_oauth_next',
            'google_register_prefill',
        )
    preserved = {key: session[key] for key in preserve_keys if key in session}
    session.clear()
    session.update(preserved)


def _parse_session_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def start_assessment_session():
    """
    Markiert eine Assessment-Session (kein Portal-user_sessions wegen FK auf users).

    Tracking läuft über Flask-Session-Timestamps + kürzere Lifetime.
    """
    now = datetime.utcnow().isoformat()
    session['user_scope'] = 'assessment'
    session['assessment_session_started'] = now
    session['assessment_last_activity'] = now
    session.permanent = True


def touch_assessment_session():
    """Aktualisiert die letzte Assessment-Aktivität."""
    session['assessment_last_activity'] = datetime.utcnow().isoformat()


def assessment_session_is_expired(max_hours, inactivity_hours):
    """
    Prüft Absolute- und Inaktivitäts-Timeout für Assessment-Sessions.

    Returns:
        (expired: bool, reason: str|None)
    """
    started = _parse_session_iso(session.get('assessment_session_started'))
    last_activity = _parse_session_iso(session.get('assessment_last_activity')) or started
    if not started or not last_activity:
        return True, 'missing_tracking'

    now = datetime.utcnow()
    try:
        max_hours = float(max_hours)
    except (TypeError, ValueError):
        max_hours = 12
    try:
        inactivity_hours = float(inactivity_hours)
    except (TypeError, ValueError):
        inactivity_hours = 8

    if max_hours > 0 and (now - started).total_seconds() >= max_hours * 3600:
        return True, 'max_lifetime'
    if inactivity_hours > 0 and (now - last_activity).total_seconds() >= inactivity_hours * 3600:
        return True, 'inactivity'
    return False, None


def create_session(user_id):
    """Erstellt eine neue Session für einen Benutzer."""
    session_id = generate_session_id()
    
    # Hole IP-Adresse: ProxyFix setzt remote_addr bereits korrekt; als
    # zusätzlicher Fallback prüfen wir X-Forwarded-For direkt.
    ip_address = (
        request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        or request.headers.get('X-Real-IP', '').strip()
        or request.remote_addr
    )
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
    # Nur wenn noch KEINE session_id existiert, darf eine neue Session angelegt werden.
    # Bei vorhandener, aber nicht mehr aktiver session_id (z.B. widerrufen) wird
    # bewusst NICHT automatisch neu erzeugt.
    if include_current:
        current_exists = bool(current_session_id) and any(
            sess.session_id == current_session_id for sess in sessions
        )

        if not current_exists:
            if not current_session_id:
                created_session = create_session(user_id)
                current_session_id = created_session.session_id
                sessions = query.all()

    for sess in sessions:
        sess.is_current = (sess.session_id == current_session_id) if include_current else False
        sess.device_label = format_device_label(sess.user_agent)
    
    return sessions


def clear_portal_session_cache():
    """Drop short-TTL portal session validation cache from the Flask session."""
    for key in (
        _PORTAL_SESS_OK_AT,
        _PORTAL_SESS_OK_SID,
        _PORTAL_SESS_LAST_ACTIVITY,
        _PORTAL_SESS_DIRTY,
    ):
        session.pop(key, None)


def _store_portal_session_cache(session_id: str, last_activity: datetime | None):
    now = datetime.utcnow()
    session[_PORTAL_SESS_OK_AT] = now.isoformat()
    session[_PORTAL_SESS_OK_SID] = session_id
    session[_PORTAL_SESS_LAST_ACTIVITY] = (last_activity or now).isoformat()
    session.pop(_PORTAL_SESS_DIRTY, None)


def touch_portal_session_cached(user_id):
    """
    Validate portal UserSession with a short Flask-session TTL.

    Returns:
        ('ok', None) — session valid (DB skipped or refreshed)
        ('invalid', error_code) — logout caller
        ('error', None) — unexpected failure; caller may log and continue
    """
    current_session_id = session.get('session_id')
    if not current_session_id:
        clear_portal_session_cache()
        return 'invalid', 'missing_session_id'

    now = datetime.utcnow()
    cache_sid = session.get(_PORTAL_SESS_OK_SID)
    cache_ok_at = _parse_session_iso(session.get(_PORTAL_SESS_OK_AT))
    cache_last = _parse_session_iso(session.get(_PORTAL_SESS_LAST_ACTIVITY))
    cache_fresh = (
        cache_sid == current_session_id
        and cache_ok_at is not None
        and cache_last is not None
        and (now - cache_ok_at) < PORTAL_SESSION_CACHE_TTL
    )

    if cache_fresh:
        if (now - cache_last) >= PORTAL_SESSION_INACTIVITY_LIMIT:
            clear_portal_session_cache()
            return 'invalid', 'inactivity'
        # Mark activity dirty in cookie; flush to DB on next cache miss / TTL expiry
        if (now - cache_last) >= PORTAL_SESSION_ACTIVITY_INTERVAL:
            session[_PORTAL_SESS_LAST_ACTIVITY] = now.isoformat()
            session[_PORTAL_SESS_DIRTY] = True
        return 'ok', None

    try:
        current_session = get_current_session(user_id)
        if current_session is None:
            clear_portal_session_cache()
            return 'invalid', 'revoked'

        last_seen = current_session.last_activity or current_session.created_at
        if last_seen and (now - last_seen) >= PORTAL_SESSION_INACTIVITY_LIMIT:
            revoke_session(user_id, current_session_id)
            db.session.commit()
            clear_portal_session_cache()
            return 'invalid', 'inactivity'

        needs_activity_write = (
            session.pop(_PORTAL_SESS_DIRTY, None)
            or not current_session.last_activity
            or (now - current_session.last_activity) >= PORTAL_SESSION_ACTIVITY_INTERVAL
        )
        if needs_activity_write:
            current_session.last_activity = now
            db.session.commit()
            last_seen = now

        _store_portal_session_cache(current_session_id, last_seen)
        return 'ok', None
    except Exception:
        clear_portal_session_cache()
        raise


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
        if session.get('session_id') == session_id:
            clear_portal_session_cache()
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
        if session.get('session_id') == session_id:
            clear_portal_session_cache()
        return True
    
    return False
