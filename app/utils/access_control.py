"""
Zugriffskontroll-Utilities für modulbasierte Rollen.
"""
from functools import wraps
from flask import abort, redirect, url_for, flash
from flask_login import current_user
from app.utils.common import is_module_enabled
from app.models.role import UserModuleRole


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
    
    # Hauptadministrator und Administrator haben immer Zugriff
    if user.is_super_admin or user.is_admin:
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
    if user.is_super_admin or user.is_admin:
        all_modules = [
            'module_chat', 'module_files', 'module_calendar', 'module_email',
            'module_contacts', 'module_credentials', 'module_manuals',
            'module_inventory', 'module_wiki', 'module_booking'
        ]
        return [m for m in all_modules if is_module_enabled(m)]
    
    # Gast-Accounts haben nie Vollzugriff und keinen Zugriff auf E-Mail und Credentials
    is_guest = hasattr(user, 'is_guest') and user.is_guest
    
    # Vollzugriff-Benutzer haben Zugriff auf alle aktivierten Module (außer Gäste)
    try:
        has_full_access = getattr(user, 'has_full_access', False)
    except:
        # Falls Spalte noch nicht existiert, Standard: Vollzugriff (Rückwärtskompatibilität)
        has_full_access = True
    
    if has_full_access and not is_guest:
        all_modules = [
            'module_chat', 'module_files', 'module_calendar', 'module_email',
            'module_contacts', 'module_credentials', 'module_manuals',
            'module_inventory', 'module_wiki', 'module_booking'
        ]
        return [m for m in all_modules if is_module_enabled(m)]
    
    # Prüfe modulspezifische Rollen
    accessible_modules = []
    # Gast-Accounts haben keinen Zugriff auf E-Mail und Credentials
    if is_guest:
        all_modules = [
            'module_chat', 'module_files', 'module_calendar',
            'module_manuals', 'module_inventory', 'module_wiki', 'module_music'
        ]
    else:
        all_modules = [
            'module_chat', 'module_files', 'module_calendar', 'module_email',
            'module_contacts', 'module_credentials', 'module_manuals',
            'module_inventory', 'module_wiki', 'module_booking'
        ]
    
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
    
    access = GuestShareAccess.query.filter_by(
        user_id=user.id,
        share_token=share_token,
        share_type=share_type
    ).first()
    
    return access is not None


def guest_has_file_access(user, file):
    """
    Prüft ob ein Gast-Account Zugriff auf eine Datei hat.
    Berücksichtigt sowohl direkte Datei-Freigaben als auch Dateien in freigegebenen Ordnern.
    
    Args:
        user: User-Objekt (muss Gast-Account sein)
        file: File-Objekt
        
    Returns:
        True wenn Zugriff vorhanden, False sonst
    """
    if not hasattr(user, 'is_guest') or not user.is_guest:
        return False
    
    from app.models.file import Folder
    
    # Prüfe direkte Datei-Freigabe
    if file.share_token and file.share_enabled:
        if has_guest_share_access(user, file.share_token, 'file'):
            return True
    
    # Prüfe ob Datei in einem freigegebenen Ordner ist
    if file.folder_id:
        folder = Folder.query.get(file.folder_id)
        if folder and folder.share_token and folder.share_enabled:
            if has_guest_share_access(user, folder.share_token, 'folder'):
                return True
        
        # Prüfe rekursiv alle übergeordneten Ordner
        current_folder = folder
        while current_folder and current_folder.parent_id:
            current_folder = Folder.query.get(current_folder.parent_id)
            if current_folder and current_folder.share_token and current_folder.share_enabled:
                if has_guest_share_access(user, current_folder.share_token, 'folder'):
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
        if access.share_type == 'file':
            file_item = File.query.filter_by(share_token=access.share_token, share_enabled=True).first()
            if file_item and file_item not in files:
                files.append(file_item)
        elif access.share_type == 'folder':
            folder_item = Folder.query.filter_by(share_token=access.share_token, share_enabled=True).first()
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

