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
            'module_credentials', 'module_manuals',
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
            'module_credentials', 'module_manuals',
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
            'module_credentials', 'module_manuals',
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


def get_guest_accessible_items(user):
    """
    Gibt alle für einen Gast-Account zugänglichen Dateien und Ordner zurück.
    
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
    
    for access in guest_accesses:
        if access.share_type == 'file':
            file_item = File.query.filter_by(share_token=access.share_token, share_enabled=True).first()
            if file_item:
                files.append(file_item)
        elif access.share_type == 'folder':
            folder_item = Folder.query.filter_by(share_token=access.share_token, share_enabled=True).first()
            if folder_item:
                folders.append(folder_item)
    
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

