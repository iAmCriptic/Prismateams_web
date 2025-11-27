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
            'module_credentials', 'module_manuals', 'module_canvas',
            'module_inventory', 'module_wiki', 'module_booking'
        ]
        return [m for m in all_modules if is_module_enabled(m)]
    
    # Vollzugriff-Benutzer haben Zugriff auf alle aktivierten Module
    try:
        has_full_access = getattr(user, 'has_full_access', False)
    except:
        # Falls Spalte noch nicht existiert, Standard: Vollzugriff (Rückwärtskompatibilität)
        has_full_access = True
    
    if has_full_access:
        all_modules = [
            'module_chat', 'module_files', 'module_calendar', 'module_email',
            'module_credentials', 'module_manuals', 'module_canvas',
            'module_inventory', 'module_wiki', 'module_booking'
        ]
        return [m for m in all_modules if is_module_enabled(m)]
    
    # Prüfe modulspezifische Rollen
    accessible_modules = []
    all_modules = [
        'module_chat', 'module_files', 'module_calendar', 'module_email',
        'module_credentials', 'module_manuals', 'module_canvas',
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

