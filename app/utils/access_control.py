"""
Zugriffskontroll-Utilities für modulbasierte Rollen.
"""
from datetime import datetime
from functools import wraps
from flask import abort, redirect, url_for, flash
from flask_login import current_user
from app.utils.common import AVAILABLE_MODULES, is_module_enabled
from app.models.role import UserModuleRole
import json
import logging
import re

logger = logging.getLogger(__name__)

# Share-Modes für Gast-Schreibzugriff (Upload) bzw. Bearbeiten bestehender Dateien
GUEST_WRITE_MODES = frozenset({'edit', 'dropbox'})
GUEST_EDIT_MODES = frozenset({'edit'})


def _legacy_share_is_expired(resource) -> bool:
    """True wenn File/Folder.share_expires_at in der Vergangenheit liegt."""
    from app.utils.public_share import legacy_share_resource_is_expired
    return legacy_share_resource_is_expired(resource)


def _share_mode_allowed(mode, allowed_modes) -> bool:
    """None = alle Modes; sonst nur Modes aus dem frozenset."""
    if allowed_modes is None:
        return True
    from app.utils.public_share import normalize_share_mode
    return normalize_share_mode(mode) in allowed_modes


def _public_share_is_usable(share, allowed_modes=None) -> bool:
    """Enabled, nicht abgelaufen, optional Mode-Filter."""
    if share is None or not share.enabled:
        return False
    from app.utils.public_share import share_is_expired
    if share_is_expired(share):
        return False
    return _share_mode_allowed(share.mode, allowed_modes)


def _roles_flag_enabled(value):
    """Robust truthiness for stored default-role flags (bool/int/str)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def load_default_module_roles():
    """
    Lädt Standardrollen aus SystemSettings.
    Fehlt die Einstellung oder ist sie ungültig → Vollzugriff als Default.
    """
    from app.models.settings import SystemSettings

    setting = SystemSettings.query.filter_by(key='default_module_roles').first()
    if not setting or not setting.value:
        return {'full_access': True}

    try:
        data = json.loads(setting.value)
        # Doppelkodierung abfangen
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, dict):
            return {'full_access': True}
        return data
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning('default_module_roles ungültig, Fallback Vollzugriff: %s', exc)
        return {'full_access': True}


def apply_default_roles_to_user(user):
    """
    Weist einem neuen (Nicht-Gast-)Benutzer die konfigurierten Standardrollen zu.
    Muss vor dem Commit aufgerufen werden (user.id nach flush vorhanden).
    """
    if user is None or getattr(user, 'is_guest', False):
        return

    roles = load_default_module_roles()

    if _roles_flag_enabled(roles.get('full_access', True)):
        user.has_full_access = True
        return

    user.has_full_access = False
    for module_key in AVAILABLE_MODULES:
        if not _roles_flag_enabled(roles.get(module_key, False)):
            continue
        if not is_module_enabled(module_key):
            continue
        existing = UserModuleRole.query.filter_by(
            user_id=user.id,
            module_key=module_key,
        ).first()
        if existing:
            existing.has_access = True
        else:
            from app import db
            db.session.add(UserModuleRole(
                user_id=user.id,
                module_key=module_key,
                has_access=True,
            ))


def user_lacks_module_access(user):
    """True wenn Benutzer weder Vollzugriff noch Modulrollen hat."""
    if user is None or getattr(user, 'is_guest', False):
        return False
    if getattr(user, 'is_super_admin', False) or getattr(user, 'is_admin', False):
        return False
    if getattr(user, 'has_full_access', False):
        return False
    return not UserModuleRole.query.filter_by(
        user_id=user.id,
        has_access=True,
    ).first()


def has_module_access(user, module_key):
    """
    Prüft ob ein Benutzer Zugriff auf ein Modul hat.
    
    Args:
        user: User-Objekt
        module_key: Modul-Schlüssel (z.B. 'module_chat', 'module_files')
        
    Returns:
        True wenn Zugriff vorhanden, False sonst
    """
    # Gast-Accounts haben keinen Zugriff auf E-Mail und Credentials
    if hasattr(user, 'is_guest') and user.is_guest:
        if module_key in ['module_email', 'module_credentials']:
            return False

    # Assessment-Accounts dürfen ausschließlich auf ihr Modul zugreifen.
    if user.__class__.__name__ == 'AssessmentUser':
        return module_key == 'module_assessment'
    
    # Hauptadministrator und Administrator haben immer Zugriff
    if getattr(user, 'is_super_admin', False) or getattr(user, 'is_admin', False):
        return True
    
    # Prüfe ob Modul überhaupt aktiviert ist
    if not is_module_enabled(module_key):
        return False
    
    # Prüfe ob has_full_access Spalte existiert (für Rückwärtskompatibilität)
    try:
        has_full_access = getattr(user, 'has_full_access', False)
    except:
        # Falls Spalte noch nicht existiert, Standard: Vollzugriff (Rückwärtskompatibilität)
        has_full_access = True
    
    # Gast-Accounts haben nie Vollzugriff
    if hasattr(user, 'is_guest') and user.is_guest:
        has_full_access = False
    
    # Vollzugriff-Benutzer haben Zugriff auf alle Module
    if has_full_access:
        return True
    
    # Prüfe modulspezifische Rolle
    # Wenn keine Rolle existiert, Standard: Kein Zugriff (False)
    role = UserModuleRole.query.filter_by(
        user_id=user.id, 
        module_key=module_key
    ).first()
    
    return role.has_access if role else False


def check_module_access(module_key):
    """
    Decorator für Route-Zugriffskontrolle.
    Prüft ob der aktuelle Benutzer Zugriff auf das Modul hat.
    
    Args:
        module_key: Modul-Schlüssel (z.B. 'module_chat', 'module_files')
        
    Returns:
        Decorator-Funktion
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            
            if not has_module_access(current_user, module_key):
                flash('Sie haben keinen Zugriff auf dieses Modul.', 'warning')
                return redirect(url_for('dashboard.index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def get_accessible_modules(user):
    """
    Gibt eine Liste aller Module zurück, auf die der Benutzer Zugriff hat.
    
    Args:
        user: User-Objekt
        
    Returns:
        Liste von Modul-Schlüsseln (z.B. ['module_chat', 'module_files'])
    """
    # Hauptadministrator und Administrator haben Zugriff auf alle aktivierten Module
    if getattr(user, 'is_super_admin', False) or getattr(user, 'is_admin', False):
        from app.utils.common import AVAILABLE_MODULES
        return [m for m in AVAILABLE_MODULES if is_module_enabled(m)]
    
    # Gast-Accounts haben nie Vollzugriff und keinen Zugriff auf E-Mail und Credentials
    is_guest = hasattr(user, 'is_guest') and user.is_guest
    
    # Vollzugriff-Benutzer haben Zugriff auf alle aktivierten Module (außer Gäste)
    try:
        has_full_access = getattr(user, 'has_full_access', False)
    except:
        # Falls Spalte noch nicht existiert, Standard: Vollzugriff (Rückwärtskompatibilität)
        has_full_access = True
    
    if has_full_access and not is_guest:
        from app.utils.common import AVAILABLE_MODULES
        return [m for m in AVAILABLE_MODULES if is_module_enabled(m)]
    
    # Prüfe modulspezifische Rollen
    accessible_modules = []
    # Gast-Accounts haben keinen Zugriff auf E-Mail und Credentials
    if is_guest:
        all_modules = [
            'module_chat', 'module_files', 'module_calendar', 'module_events',
            'module_manuals', 'module_inventory', 'module_wiki', 'module_music',
            'module_media_downloader', 'module_file_converter', 'module_assessment', 'module_shortlinks',
            'module_kanban',
            'module_excalidraw',
        ]
    else:
        from app.utils.common import AVAILABLE_MODULES
        all_modules = list(AVAILABLE_MODULES)
    
    for module_key in all_modules:
        if is_module_enabled(module_key):
            role = UserModuleRole.query.filter_by(
                user_id=user.id,
                module_key=module_key
            ).first()
            
            if role and role.has_access:
                accessible_modules.append(module_key)
    
    return accessible_modules


def has_guest_share_access(user, share_token, share_type):
    """
    Prüft ob ein Gast-Account Zugriff auf einen Freigabelink hat.
    
    Args:
        user: User-Objekt (muss Gast-Account sein)
        share_token: Share-Token des Freigabelinks
        share_type: 'file' oder 'folder'
        
    Returns:
        True wenn Zugriff vorhanden, False sonst
    """
    if not hasattr(user, 'is_guest') or not user.is_guest:
        return False
    
    from app.models.guest import GuestShareAccess

    normalized_token = _normalize_guest_share_token(share_token)
    normalized_type = (share_type or '').strip().lower()
    if not normalized_token or not normalized_type:
        return False

    # Schneller Pfad für sauber gespeicherte Werte
    access = GuestShareAccess.query.filter_by(
        user_id=user.id,
        share_token=normalized_token,
        share_type=normalized_type
    ).first()
    if access is not None:
        return True

    # Fallback für Legacy-/inkonsistente Daten (z.B. gespeicherte Share-URL statt Token)
    candidate_accesses = GuestShareAccess.query.filter_by(
        user_id=user.id,
        share_type=normalized_type
    ).all()

    for candidate in candidate_accesses:
        if _normalize_guest_share_token(candidate.share_token) == normalized_token:
            return True

    return False


def guest_has_folder_access(user, folder, *, modes=None):
    """
    Prüft ob ein Gast Zugriff auf einen Ordner hat (direkt oder über Ancestor-Share).

    modes: optional frozenset erlaubter Share-Modes (z.B. GUEST_WRITE_MODES).
           None = jeder Mode (Lesen).
    """
    if not hasattr(user, 'is_guest') or not user.is_guest or folder is None:
        return False

    from app.models.file import Folder
    from app.models.public_share import PublicShare
    from app.models.guest import GuestShareAccess

    chain = []
    current = folder
    while current:
        chain.append(current)
        current = Folder.query.get(current.parent_id) if current.parent_id else None
    chain_ids = {f.id for f in chain}

    for access in GuestShareAccess.query.filter_by(user_id=user.id).all():
        token = _normalize_guest_share_token(access.share_token)
        if not token:
            continue
        share = PublicShare.query.filter_by(token=token, enabled=True).first()
        if not _public_share_is_usable(share, modes):
            continue
        if share.resource_type == 'folder' and share.resource_id in chain_ids:
            return True

    for ancestor in chain:
        if not (ancestor.share_token and ancestor.share_enabled):
            continue
        if _legacy_share_is_expired(ancestor):
            continue
        if not _share_mode_allowed(getattr(ancestor, 'share_mode', 'edit'), modes):
            continue
        if has_guest_share_access(user, ancestor.share_token, 'folder'):
            return True

    return False


def guest_has_file_access(user, file, *, modes=None):
    """
    Prüft ob ein Gast-Account Zugriff auf eine Datei hat.
    Berücksichtigt direkte Datei-Freigaben und Dateien in freigegebenen Ordnern.

    modes: optional frozenset erlaubter Share-Modes.
           None = jeder Mode (Lesen); GUEST_EDIT_MODES für Bearbeiten.
    """
    if not hasattr(user, 'is_guest') or not user.is_guest:
        return False
    
    from app.models.file import Folder
    from app.models.public_share import PublicShare
    from app.models.guest import GuestShareAccess

    for access in GuestShareAccess.query.filter_by(user_id=user.id).all():
        token = _normalize_guest_share_token(access.share_token)
        if not token:
            continue
        share = PublicShare.query.filter_by(token=token, enabled=True).first()
        if not _public_share_is_usable(share, modes):
            continue
        if share.resource_type == 'file' and share.resource_id == file.id:
            return True
        if share.resource_type == 'folder' and file.folder_id:
            folder = Folder.query.get(file.folder_id)
            while folder:
                if folder.id == share.resource_id:
                    return True
                folder = Folder.query.get(folder.parent_id) if folder.parent_id else None

    if file.share_token and file.share_enabled and not _legacy_share_is_expired(file):
        if _share_mode_allowed(getattr(file, 'share_mode', 'edit'), modes):
            if has_guest_share_access(user, file.share_token, 'file'):
                return True

    if file.folder_id:
        folder = Folder.query.get(file.folder_id)
        if folder and guest_has_folder_access(user, folder, modes=modes):
            return True

    return False


def get_guest_accessible_items(user):
    """
    Gibt alle für einen Gast-Account zugänglichen Dateien und Ordner zurück.
    Inkludiert auch alle Dateien und Unterordner in freigegebenen Ordnern.
    
    Args:
        user: User-Objekt (muss Gast-Account sein)
        
    Returns:
        Tuple (files, folders) mit Listen von File- und Folder-Objekten
    """
    if not hasattr(user, 'is_guest') or not user.is_guest:
        return [], []
    
    from app.models.guest import GuestShareAccess
    from app.models.file import File, Folder
    from app.models.public_share import PublicShare
    from app.utils.public_share import resolve_resource, share_is_expired
    
    # Hole alle Share-Tokens für diesen Gast
    guest_accesses = GuestShareAccess.query.filter_by(user_id=user.id).all()
    
    files = []
    folders = []
    processed_folder_ids = set()
    
    def get_all_subfolders(folder_id):
        """Rekursiv alle Unterordner eines Ordners holen."""
        subfolders = Folder.query.filter_by(parent_id=folder_id).all()
        result = list(subfolders)
        for subfolder in subfolders:
            result.extend(get_all_subfolders(subfolder.id))
        return result
    
    def get_all_files_in_folder(folder_id):
        """Alle Dateien in einem Ordner und seinen Unterordnern holen."""
        files_in_folder = File.query.filter_by(folder_id=folder_id, is_current=True).all()
        result = list(files_in_folder)
        subfolders = Folder.query.filter_by(parent_id=folder_id).all()
        for subfolder in subfolders:
            result.extend(get_all_files_in_folder(subfolder.id))
        return result
    
    for access in guest_accesses:
        normalized_type = (access.share_type or '').strip().lower()
        normalized_token = _normalize_guest_share_token(access.share_token)
        if not normalized_token:
            continue

        file_item = None
        folder_item = None

        share = PublicShare.query.filter_by(token=normalized_token, enabled=True).first()
        if share and not share_is_expired(share):
            resolved = resolve_resource(share)
            if share.resource_type == 'file' and resolved:
                file_item = resolved
            elif share.resource_type == 'folder' and resolved:
                folder_item = resolved
        elif normalized_type == 'file':
            file_item = File.query.filter_by(share_token=normalized_token, share_enabled=True).first()
            if file_item and _legacy_share_is_expired(file_item):
                file_item = None
            if not file_item:
                folder_item = Folder.query.filter_by(share_token=normalized_token, share_enabled=True).first()
                if folder_item and _legacy_share_is_expired(folder_item):
                    folder_item = None
        elif normalized_type == 'folder':
            folder_item = Folder.query.filter_by(share_token=normalized_token, share_enabled=True).first()
            if folder_item and _legacy_share_is_expired(folder_item):
                folder_item = None
            if not folder_item:
                file_item = File.query.filter_by(share_token=normalized_token, share_enabled=True).first()
                if file_item and _legacy_share_is_expired(file_item):
                    file_item = None
        else:
            file_item = File.query.filter_by(share_token=normalized_token, share_enabled=True).first()
            if file_item and _legacy_share_is_expired(file_item):
                file_item = None
            if not file_item:
                folder_item = Folder.query.filter_by(share_token=normalized_token, share_enabled=True).first()
                if folder_item and _legacy_share_is_expired(folder_item):
                    folder_item = None

        if file_item and file_item not in files:
            files.append(file_item)

        if folder_item:
            if folder_item.id not in processed_folder_ids:
                folders.append(folder_item)
                processed_folder_ids.add(folder_item.id)

                # Füge alle Unterordner hinzu
                subfolders = get_all_subfolders(folder_item.id)
                for subfolder in subfolders:
                    if subfolder.id not in processed_folder_ids:
                        folders.append(subfolder)
                        processed_folder_ids.add(subfolder.id)

                # Füge alle Dateien im Ordner und seinen Unterordnern hinzu
                files_in_folder = get_all_files_in_folder(folder_item.id)
                for file_in_folder in files_in_folder:
                    if file_in_folder not in files:
                        files.append(file_in_folder)
    
    return files, folders


def get_guest_directly_shared_folders(user):
    """
    Gibt ausschließlich die direkt für den Gast freigegebenen Ordner zurück.

    Das sind nur Ordner, für die ein expliziter Folder-Share beim Gast hinterlegt ist
    (nicht rekursiv geerbte Unterordner).
    """
    if not hasattr(user, 'is_guest') or not user.is_guest:
        return []

    from app.models.guest import GuestShareAccess
    from app.models.file import Folder
    from app.models.public_share import PublicShare
    from app.utils.public_share import resolve_resource, share_is_expired

    guest_accesses = GuestShareAccess.query.filter_by(user_id=user.id).all()
    directly_shared_folders = []
    processed_folder_ids = set()

    for access in guest_accesses:
        normalized_token = _normalize_guest_share_token(access.share_token)
        if not normalized_token:
            continue

        folder = None
        share = PublicShare.query.filter_by(token=normalized_token, enabled=True).first()
        if share and share.resource_type == 'folder' and not share_is_expired(share):
            folder = resolve_resource(share)
        if not folder:
            folder = Folder.query.filter_by(share_token=normalized_token, share_enabled=True).first()
            if folder and _legacy_share_is_expired(folder):
                folder = None
        if folder and folder.id not in processed_folder_ids:
            directly_shared_folders.append(folder)
            processed_folder_ids.add(folder.id)

    return directly_shared_folders


def _normalize_guest_share_token(raw_token):
    """
    Normalisiert gespeicherte Share-Referenzen auf den reinen Token.

    Unterstützt:
    - reinen Token (z.B. abc123)
    - relative URL (z.B. /files/share/abc123)
    - absolute URL (z.B. https://example.com/files/share/abc123?x=1)
    """
    if not raw_token:
        return None

    token = str(raw_token).strip()
    if not token:
        return None

    match = re.search(r"/share/([^/?#]+)", token)
    if match:
        return match.group(1)

    return token


def is_guest_allowed_module(guest_user, module_key):
    """
    Prüft ob ein Gast-Account Zugriff auf ein Modul hat.
    
    Args:
        guest_user: User-Objekt (muss Gast-Account sein)
        module_key: Modul-Schlüssel
        
    Returns:
        True wenn Zugriff vorhanden, False sonst
    """
    if not hasattr(guest_user, 'is_guest') or not guest_user.is_guest:
        return False
    
    # Gast-Accounts haben nie Zugriff auf E-Mail und Credentials
    if module_key in ['module_email', 'module_credentials']:
        return False
    
    # Verwende die normale Modul-Zugriffsprüfung
    return has_module_access(guest_user, module_key)

