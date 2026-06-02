"""
Utility functions for the Team Portal application.
"""

from datetime import datetime
from flask import current_app
import pytz
import requests
import os

AVAILABLE_MODULES = [
    'module_chat',
    'module_files',
    'module_calendar',
    'module_email',
    'module_contacts',
    'module_credentials',
    'module_manuals',
    'module_inventory',
    'module_wiki',
    'module_booking',
    'module_music',
    'module_media_downloader',
    'module_assessment',
    'module_shortlinks',
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

    Returns:
        timezone-aware datetime in der Portal-Zeitzone
    """
    if utc_datetime is None:
        return None

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
        from app.models.settings import SystemSettings
        setting = SystemSettings.query.filter_by(key=module_key).first()
        enabled = False
        if setting:
            # Prüfe ob der Wert 'true' ist (case-insensitive)
            enabled = str(setting.value).lower() == 'true'
        else:
            # Standardmäßig aktiviert wenn nicht gesetzt (für Rückwärtskompatibilität)
            enabled = True
        
        return enabled
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


def check_for_updates():
    """
    Prüft ob ein Update verfügbar ist, indem der neueste Commit vom Main-Branch auf GitHub abgerufen wird.
    
    Returns:
        Dict mit 'update_available' (bool), 'latest_commit' (str), 'latest_commit_date' (str) oder None bei Fehler
    """
    try:
        github_repo = "iAmCriptic/Prismateams_web"
        github_api_url = f"https://api.github.com/repos/{github_repo}/commits/main"
        
        # Timeout von 5 Sekunden, um nicht zu lange zu warten
        response = requests.get(github_api_url, timeout=5)
        
        if response.status_code == 200:
            commit_data = response.json()
            latest_commit_hash = commit_data.get('sha', '')[:7]  # Erste 7 Zeichen
            latest_commit_date = commit_data.get('commit', {}).get('author', {}).get('date', '')
            
            current_commit = get_current_commit_hash()
            
            # Wenn aktueller Commit nicht ermittelbar, zeige Update-Banner nicht an
            if not current_commit:
                return {
                    'update_available': False,
                    'latest_commit': latest_commit_hash,
                    'latest_commit_date': latest_commit_date
                }
            
            # Vergleiche Commits (nur erste 7 Zeichen für Vergleich)
            update_available = current_commit[:7] != latest_commit_hash
            
            return {
                'update_available': update_available,
                'latest_commit': latest_commit_hash,
                'latest_commit_date': latest_commit_date,
                'current_commit': current_commit[:7] if current_commit else None
            }
        else:
            current_app.logger.warning(f"GitHub API Fehler: {response.status_code}")
            return None
    except requests.exceptions.Timeout:
        current_app.logger.warning("Timeout beim Abrufen von GitHub Updates")
        return None
    except Exception as e:
        current_app.logger.error(f"Fehler beim Prüfen auf Updates: {e}")
        return None