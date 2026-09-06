"""
Utility functions for the Team Portal application.
"""

from datetime import datetime, date
from flask import current_app
import pytz
import requests
import os

AVAILABLE_MODULES = [
    'module_chat',
    'module_files',
    'module_calendar',
    'module_events',
    'module_email',
    'module_contacts',
    'module_credentials',
    'module_manuals',
    'module_inventory',
    'module_wiki',
    'module_booking',
    'module_music',
    'module_media_downloader',
    'module_file_converter',
    'module_assessment',
    'module_shortlinks',
    'module_kanban',
    'module_excalidraw',
    'module_surveys',
    'module_protocols',
]

DEFAULT_TIMEZONE = 'Europe/Berlin'
SUPPORTED_TIMEZONES = (
    'Europe/Berlin',
    'Europe/Zurich',
    'Europe/Vienna',
    'UTC',
    'Europe/London',
    'America/New_York',
    'America/Los_Angeles',
    'Asia/Tokyo',
)


def get_timezone_choices():
    """Zeitzonenliste für Auswahlfelder in den Admin-Einstellungen."""
    return [(tz, tz) for tz in SUPPORTED_TIMEZONES]


def get_system_timezone():
    """Liefert die im Portal konfigurierte Zeitzone (mit Fallback)."""
    timezone_name = current_app.config.get('PORTAL_TIMEZONE', DEFAULT_TIMEZONE)
    try:
        from app.models.settings import SystemSettings
        timezone_setting = SystemSettings.query.filter_by(key='portal_timezone').first()
        if timezone_setting and timezone_setting.value:
            timezone_name = timezone_setting.value.strip()
    except Exception:
        # Während Setup/Migrationen ggf. keine Settings-Tabelle verfügbar
        pass

    if timezone_name not in SUPPORTED_TIMEZONES:
        timezone_name = DEFAULT_TIMEZONE
    return timezone_name


def _portal_timezone():
    """pytz-Zeitzone des Portals (mit Fallback bei unbekannten Zonen)."""
    try:
        return pytz.timezone(get_system_timezone())
    except pytz.exceptions.UnknownTimeZoneError:
        return pytz.timezone(DEFAULT_TIMEZONE)


def get_local_time(utc_datetime):
    """
    Konvertiert ein UTC-Datum in die konfigurierte Portal-Zeitzone.

    Args:
        utc_datetime: datetime-Objekt (naiv = UTC aus der DB, sonst timezone-aware)
                      date-Objekte werden unverändert belassen (keine Uhrzeit).

    Returns:
        timezone-aware datetime in der Portal-Zeitzone (oder date unverändert)
    """
    if utc_datetime is None:
        return None

    # Reine Datumsangaben (ohne Uhrzeit) nicht als UTC interpretieren
    if type(utc_datetime) is date:
        return utc_datetime

    tz = _portal_timezone()

    # Naive Datumswerte aus DB werden als UTC interpretiert.
    if utc_datetime.tzinfo is None:
        utc_aware = pytz.utc.localize(utc_datetime)
    else:
        utc_aware = utc_datetime.astimezone(pytz.utc)
    return utc_aware.astimezone(tz)


def now_in_portal_timezone():
    """Aktuelle Uhrzeit in der konfigurierten Portal-Zeitzone."""
    return datetime.now(_portal_timezone())


def portal_now_naive():
    """Aktuelle Portal-Zeit als naives datetime (für Vergleiche mit Wandzeiten in der DB)."""
    return now_in_portal_timezone().replace(tzinfo=None)


def as_portal_wall_time(dt):
    """
    Wandzeit in der Portal-Zeitzone als naives datetime.

    - timezone-aware Werte werden in die Portal-Zone konvertiert
    - naive Werte gelten bereits als Portal-Wandzeit (Formular/Floating) und bleiben unverändert
    """
    if dt is None:
        return None
    if getattr(dt, 'tzinfo', None) is not None:
        return get_local_time(dt).replace(tzinfo=None)
    return dt


def format_datetime(dt, format_string='%d.%m.%Y %H:%M'):
    """
    Format a datetime object with local timezone.
    
    Args:
        dt: datetime object
        format_string: strftime format string
        
    Returns:
        Formatted datetime string
    """
    if dt is None:
        return ''

    local_dt = get_local_time(dt)
    if local_dt is None:
        return ''
    return local_dt.strftime(format_string)


def format_time(dt, format_string='%H:%M'):
    """
    Format a datetime object to time only with local timezone.
    
    Args:
        dt: datetime object
        format_string: strftime format string for time
        
    Returns:
        Formatted time string
    """
    if dt is None:
        return ''

    local_dt = get_local_time(dt)
    if local_dt is None or type(local_dt) is date:
        return ''
    return local_dt.strftime(format_string)


def is_module_enabled(module_key):
    """
    Prüft ob ein Modul aktiviert ist.
    
    Args:
        module_key: Der Schlüssel des Moduls (z.B. 'module_chat', 'module_files')
        
    Returns:
        True wenn das Modul aktiviert ist, False sonst. Standardmäßig True wenn nicht gesetzt.
    """
    try:
        from app.utils.system_settings_cache import get_setting

        value = get_setting(module_key)
        if value is None:
            # Standardmäßig aktiviert wenn nicht gesetzt (für Rückwärtskompatibilität)
            return True
        return str(value).lower() == 'true'
    except Exception:
        # Bei Fehlern (z.B. während Setup) standardmäßig aktiviert
        return True


def get_current_commit_hash():
    """
    Ermittelt den aktuellen Commit-Hash der installierten Version.
    
    Returns:
        String mit dem Commit-Hash oder None wenn nicht ermittelbar
    """
    try:
        # Versuche .git/HEAD zu lesen (wenn Git-Repository vorhanden)
        git_dir = os.path.join(current_app.root_path, '..', '.git')
        head_file = os.path.join(git_dir, 'HEAD')
        
        if os.path.exists(head_file):
            with open(head_file, 'r') as f:
                ref = f.read().strip()
            
            # Wenn es ein Branch-Reference ist
            if ref.startswith('ref: '):
                ref_path = ref[5:]  # Entferne 'ref: '
                ref_file = os.path.join(git_dir, ref_path)
                if os.path.exists(ref_file):
                    with open(ref_file, 'r') as f:
                        return f.read().strip()
            else:
                # Direkter Commit-Hash
                return ref
        
        # Fallback: Versuche aus instance/current_commit.txt zu lesen
        instance_dir = os.path.join(current_app.root_path, '..', 'instance')
        commit_file = os.path.join(instance_dir, 'current_commit.txt')
        if os.path.exists(commit_file):
            with open(commit_file, 'r') as f:
                return f.read().strip()
    except Exception as e:
        current_app.logger.error(f"Fehler beim Ermitteln des aktuellen Commit-Hash: {e}")
    
    return None


# Background-Cache für GitHub-Update-Check (nie synchron im Request-Pfad blockieren).
_UPDATE_CHECK_CACHE = {'data': None, 'checked_at': 0.0, 'refreshing': False}
_UPDATE_CHECK_LOCK = None
_UPDATE_CHECK_TTL_SECONDS = 6 * 3600


def _update_check_lock():
    global _UPDATE_CHECK_LOCK
    if _UPDATE_CHECK_LOCK is None:
        import threading
        _UPDATE_CHECK_LOCK = threading.Lock()
    return _UPDATE_CHECK_LOCK


def _fetch_github_update_info():
    """Synchroner GitHub-API-Call (nur aus Background-Thread)."""
    github_repo = "iAmCriptic/Prismateams_web"
    github_api_url = f"https://api.github.com/repos/{github_repo}/commits/main"
    response = requests.get(github_api_url, timeout=5)

    if response.status_code != 200:
        current_app.logger.warning(f"GitHub API Fehler: {response.status_code}")
        return None

    commit_data = response.json()
    latest_commit_hash = commit_data.get('sha', '')[:7]
    latest_commit_date = commit_data.get('commit', {}).get('author', {}).get('date', '')
    current_commit = get_current_commit_hash()

    if not current_commit:
        return {
            'update_available': False,
            'latest_commit': latest_commit_hash,
            'latest_commit_date': latest_commit_date,
        }

    return {
        'update_available': current_commit[:7] != latest_commit_hash,
        'latest_commit': latest_commit_hash,
        'latest_commit_date': latest_commit_date,
        'current_commit': current_commit[:7],
    }


def _refresh_update_cache_async(app):
    """Aktualisiert den Update-Cache im Hintergrund."""
    import time

    try:
        with app.app_context():
            info = _fetch_github_update_info()
            with _update_check_lock():
                if info is not None:
                    _UPDATE_CHECK_CACHE['data'] = info
                    _UPDATE_CHECK_CACHE['checked_at'] = time.time()
    except requests.exceptions.Timeout:
        app.logger.warning("Timeout beim Abrufen von GitHub Updates")
    except Exception as e:
        app.logger.error(f"Fehler beim Prüfen auf Updates: {e}")
    finally:
        with _update_check_lock():
            _UPDATE_CHECK_CACHE['refreshing'] = False


def check_for_updates():
    """
    Liefert Update-Info aus Cache (TTL 6h). Refresh läuft im Background —
    der Request-Pfad wartet nie auf GitHub.
    """
    import time
    import threading

    now = time.time()
    with _update_check_lock():
        cached = _UPDATE_CHECK_CACHE['data']
        age = now - float(_UPDATE_CHECK_CACHE['checked_at'] or 0)
        stale = cached is None or age >= _UPDATE_CHECK_TTL_SECONDS
        if stale and not _UPDATE_CHECK_CACHE['refreshing']:
            _UPDATE_CHECK_CACHE['refreshing'] = True
            app = current_app._get_current_object()
            threading.Thread(
                target=_refresh_update_cache_async,
                args=(app,),
                daemon=True,
                name='github-update-check',
            ).start()
        return cached