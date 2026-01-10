import requests
from flask import url_for, session
from app import db
from app.models.music import MusicProviderToken, MusicSettings
from cryptography.fernet import Fernet
import os
import base64
from datetime import datetime, timedelta
import threading
import logging

logger = logging.getLogger(__name__)

# Einfaches In-Memory-Cache für Token-Status (pro Request/Thread)
# Speichert, ob ein Token kürzlich aktualisiert wurde, um unnötige DB-Abfragen zu vermeiden
_token_cache = {}
_token_cache_lock = threading.Lock()

# Cache-TTL: 5 Minuten (Token werden nur aktualisiert, wenn sie wirklich abgelaufen sind)
TOKEN_CACHE_TTL = 300  # 5 Minuten in Sekunden


def get_music_setting(key, default=None):
    """Holt eine Musik-Einstellung aus MusicSettings oder Fallback."""
    from flask import current_app
    
    # Versuche zuerst aus MusicSettings
    setting = MusicSettings.query.filter_by(key=key).first()
    if setting and setting.value:
        return setting.value
    
    # Fallback zu config oder Umgebungsvariable
    config_key = key.upper()
    return current_app.config.get(config_key) or os.environ.get(config_key) or default


def get_encryption_key():
    """Holt oder erstellt den Verschlüsselungsschlüssel."""
    # Versuche zuerst aus Umgebungsvariable zu lesen
    key = os.environ.get('MUSIC_ENCRYPTION_KEY')
    if key:
        # Wenn als String, in Bytes konvertieren
        if isinstance(key, str):
            return key.encode('utf-8')
        return key
    
    # Fallback: Versuche aus Datei zu lesen (für Migration)
    key_file = 'music_token_key.key'
    if os.path.exists(key_file):
        with open(key_file, 'rb') as f:
            return f.read()
    
    # Wenn nichts gefunden, generiere neuen Key (nur für Entwicklung)
    # In Produktion sollte der Key immer in .env gesetzt sein
    key = Fernet.generate_key()
    print("WARNUNG: MUSIC_ENCRYPTION_KEY nicht in .env gefunden! Bitte setzen Sie den Key in der .env-Datei.")
    return key


def encrypt_token(token):
    """Verschlüsselt einen Token."""
    key = get_encryption_key()
    f = Fernet(key)
    return f.encrypt(token.encode()).decode()


def decrypt_token(encrypted_token):
    """Entschlüsselt einen Token."""
    key = get_encryption_key()
    f = Fernet(key)
    return f.decrypt(encrypted_token.encode()).decode()


def get_spotify_oauth_url():
    """Generiert die Spotify OAuth URL."""
    client_id = get_music_setting('spotify_client_id')
    if not client_id:
        raise Exception("Spotify Client ID nicht konfiguriert. Bitte in den Einstellungen konfigurieren.")
    redirect_uri = url_for('music.spotify_callback', _external=True)
    scope = 'user-read-private user-read-email user-read-playback-state user-modify-playback-state user-read-currently-playing'
    state = os.urandom(16).hex()
    session['spotify_oauth_state'] = state
    
    auth_url = f"https://accounts.spotify.com/authorize?client_id={client_id}&response_type=code&redirect_uri={redirect_uri}&scope={scope}&state={state}"
    return auth_url


def get_youtube_oauth_url():
    """Generiert die YouTube OAuth URL."""
    client_id = get_music_setting('youtube_client_id')
    if not client_id:
        raise Exception("YouTube Client ID nicht konfiguriert. Bitte in den Einstellungen konfigurieren.")
    redirect_uri = url_for('music.youtube_callback', _external=True)
    scope = 'https://www.googleapis.com/auth/youtube.readonly'
    state = os.urandom(16).hex()
    session['youtube_oauth_state'] = state
    
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={client_id}&response_type=code&redirect_uri={redirect_uri}&scope={scope}&state={state}&access_type=offline&prompt=consent"
    return auth_url


def handle_spotify_callback(code, state):
    """Verarbeitet den Spotify OAuth Callback."""
    from flask import session
    from flask_login import current_user
    
    # Validiere State
    if state != session.get('spotify_oauth_state'):
        raise Exception("Ungültiger State-Parameter")
    
    client_id = get_music_setting('spotify_client_id')
    client_secret = get_music_setting('spotify_client_secret')
    if not client_id or not client_secret:
        raise Exception("Spotify Credentials nicht konfiguriert. Bitte in den Einstellungen konfigurieren.")
    redirect_uri = url_for('music.spotify_callback', _external=True)
    
    # Tausche Code gegen Token
    response = requests.post(
        'https://accounts.spotify.com/api/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'client_id': client_id,
            'client_secret': client_secret
        },
        timeout=5
    )
    response.raise_for_status()
    token_data = response.json()
    
    # Speichere Token
    expires_at = datetime.utcnow() + timedelta(seconds=token_data.get('expires_in', 3600))
    
    token_obj = MusicProviderToken.query.filter_by(user_id=current_user.id, provider='spotify').first()
    if token_obj:
        token_obj.access_token = encrypt_token(token_data['access_token'])
        token_obj.refresh_token = encrypt_token(token_data['refresh_token']) if token_data.get('refresh_token') else token_obj.refresh_token
        token_obj.token_expires_at = expires_at
        token_obj.scope = token_data.get('scope')
    else:
        token_obj = MusicProviderToken(
            user_id=current_user.id,
            provider='spotify',
            access_token=encrypt_token(token_data['access_token']),
            refresh_token=encrypt_token(token_data['refresh_token']) if token_data.get('refresh_token') else None,
            token_expires_at=expires_at,
            scope=token_data.get('scope')
        )
        db.session.add(token_obj)
    
    db.session.commit()
    return token_obj


def handle_youtube_callback(code, state):
    """Verarbeitet den YouTube OAuth Callback."""
    from flask import session
    from flask_login import current_user
    
    # Validiere State
    if state != session.get('youtube_oauth_state'):
        raise Exception("Ungültiger State-Parameter")
    
    client_id = get_music_setting('youtube_client_id')
    client_secret = get_music_setting('youtube_client_secret')
    if not client_id or not client_secret:
        raise Exception("YouTube Credentials nicht konfiguriert. Bitte in den Einstellungen konfigurieren.")
    redirect_uri = url_for('music.youtube_callback', _external=True)
    
    # Tausche Code gegen Token
    response = requests.post(
        'https://oauth2.googleapis.com/token',
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'client_id': client_id,
            'client_secret': client_secret
        },
        timeout=5
    )
    response.raise_for_status()
    token_data = response.json()
    
    # Speichere Token
    expires_at = datetime.utcnow() + timedelta(seconds=token_data.get('expires_in', 3600))
    
    token_obj = MusicProviderToken.query.filter_by(user_id=current_user.id, provider='youtube').first()
    if token_obj:
        token_obj.access_token = encrypt_token(token_data['access_token'])
        token_obj.refresh_token = encrypt_token(token_data['refresh_token']) if token_data.get('refresh_token') else token_obj.refresh_token
        token_obj.token_expires_at = expires_at
        token_obj.scope = token_data.get('scope')
    else:
        token_obj = MusicProviderToken(
            user_id=current_user.id,
            provider='youtube',
            access_token=encrypt_token(token_data['access_token']),
            refresh_token=encrypt_token(token_data['refresh_token']) if token_data.get('refresh_token') else None,
            token_expires_at=expires_at,
            scope=token_data.get('scope')
        )
        db.session.add(token_obj)
    
    db.session.commit()
    return token_obj


def _get_cache_key(token_obj):
    """Generiert einen Cache-Key für ein Token-Objekt."""
    return f"{token_obj.user_id}_{token_obj.provider}_{token_obj.id}"


def _is_token_cached(token_obj):
    """Prüft, ob ein Token kürzlich aktualisiert wurde (im Cache)."""
    cache_key = _get_cache_key(token_obj)
    with _token_cache_lock:
        if cache_key in _token_cache:
            cached_time, cached_valid = _token_cache[cache_key]
            # Prüfe ob Cache noch gültig ist
            if (datetime.utcnow() - cached_time).total_seconds() < TOKEN_CACHE_TTL:
                return cached_valid
            else:
                # Cache abgelaufen, entferne Eintrag
                del _token_cache[cache_key]
    return None


def _cache_token_status(token_obj, is_valid):
    """Speichert den Token-Status im Cache."""
    cache_key = _get_cache_key(token_obj)
    with _token_cache_lock:
        _token_cache[cache_key] = (datetime.utcnow(), is_valid)
        # Bereinige alte Cache-Einträge (einfache Bereinigung)
        if len(_token_cache) > 1000:
            # Entferne die ältesten 200 Einträge
            sorted_items = sorted(_token_cache.items(), key=lambda x: x[1][0])
            for key, _ in sorted_items[:200]:
                del _token_cache[key]


def refresh_token_if_needed(token_obj):
    """Aktualisiert ein Token falls es abgelaufen ist.
    Verwendet Caching, um unnötige DB-Abfragen und Token-Refreshes zu vermeiden."""
    
    # Prüfe Cache zuerst
    cached_valid = _is_token_cached(token_obj)
    if cached_valid is True:
        # Token wurde kürzlich als gültig markiert, keine Aktion nötig
        return
    elif cached_valid is False:
        # Token wurde kürzlich als abgelaufen markiert, aber Refresh könnte fehlgeschlagen sein
        # Prüfe nochmal, ob es wirklich abgelaufen ist
        pass
    
    # Prüfe ob Token wirklich abgelaufen ist (mit 5 Minuten Puffer für Sicherheit)
    if token_obj.token_expires_at:
        time_until_expiry = (token_obj.token_expires_at - datetime.utcnow()).total_seconds()
        # Wenn Token noch mehr als 5 Minuten gültig ist, cache es als gültig
        if time_until_expiry > 300:
            _cache_token_status(token_obj, True)
            return
    
    # Token ist abgelaufen oder läuft bald ab, prüfe nochmal genau
    if not token_obj.is_expired():
        _cache_token_status(token_obj, True)
        return
    
    # Token ist wirklich abgelaufen, aktualisiere es
    if not token_obj.refresh_token:
        _cache_token_status(token_obj, False)
        raise Exception("Kein Refresh-Token verfügbar")
    
    try:
        if token_obj.provider == 'spotify':
            client_id = get_music_setting('spotify_client_id')
            client_secret = get_music_setting('spotify_client_secret')
            if not client_id or not client_secret:
                raise Exception("Spotify Credentials nicht konfiguriert.")
            
            response = requests.post(
                'https://accounts.spotify.com/api/token',
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': decrypt_token(token_obj.refresh_token),
                    'client_id': client_id,
                    'client_secret': client_secret
                },
                timeout=5
            )
            response.raise_for_status()
            token_data = response.json()
            
            token_obj.access_token = encrypt_token(token_data['access_token'])
            if token_data.get('refresh_token'):
                token_obj.refresh_token = encrypt_token(token_data['refresh_token'])
            token_obj.token_expires_at = datetime.utcnow() + timedelta(seconds=token_data.get('expires_in', 3600))
            
        elif token_obj.provider == 'youtube':
            client_id = get_music_setting('youtube_client_id')
            client_secret = get_music_setting('youtube_client_secret')
            if not client_id or not client_secret:
                raise Exception("YouTube Credentials nicht konfiguriert.")
            
            response = requests.post(
                'https://oauth2.googleapis.com/token',
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': decrypt_token(token_obj.refresh_token),
                    'client_id': client_id,
                    'client_secret': client_secret
                },
                timeout=5
            )
            response.raise_for_status()
            token_data = response.json()
            
            token_obj.access_token = encrypt_token(token_data['access_token'])
            if token_data.get('refresh_token'):
                token_obj.refresh_token = encrypt_token(token_data['refresh_token'])
            token_obj.token_expires_at = datetime.utcnow() + timedelta(seconds=token_data.get('expires_in', 3600))
        
        db.session.commit()
        # Cache als gültig markieren nach erfolgreichem Refresh
        _cache_token_status(token_obj, True)
        logger.info(f"Token für {token_obj.provider} (User {token_obj.user_id}) erfolgreich aktualisiert")
    except Exception as e:
        _cache_token_status(token_obj, False)
        logger.error(f"Fehler beim Aktualisieren des Tokens für {token_obj.provider} (User {token_obj.user_id}): {e}")
        raise


def is_provider_connected(user_id, provider):
    """Prüft ob ein Provider verbunden ist.
    Optimiert mit Caching, um unnötige DB-Abfragen zu vermeiden."""
    token_obj = MusicProviderToken.query.filter_by(user_id=user_id, provider=provider).first()
    if not token_obj:
        return False
    
    # Prüfe Cache zuerst
    cached_valid = _is_token_cached(token_obj)
    if cached_valid is True:
        return True
    elif cached_valid is False:
        # Token wurde kürzlich als ungültig markiert
        return False
    
    # Prüfe ob Token abgelaufen ist (nur wenn nicht im Cache)
    if token_obj.is_expired():
        try:
            refresh_token_if_needed(token_obj)
        except:
            _cache_token_status(token_obj, False)
            return False
    else:
        # Token ist noch gültig, cache es
        _cache_token_status(token_obj, True)
    
    return True


def disconnect_provider(user_id, provider):
    """Trennt die Verbindung zu einem Provider."""
    token_obj = MusicProviderToken.query.filter_by(user_id=user_id, provider=provider).first()
    if token_obj:
        db.session.delete(token_obj)
        db.session.commit()



