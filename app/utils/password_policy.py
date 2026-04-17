"""
Passwort-Policy Utility für die Validierung von Passwörtern.
"""
import re
from flask import current_app


def check_password_complexity(password):
    """
    Prüft die Komplexität eines Passworts.
    Gibt ein Dictionary mit Details zurück.
    """
    complexity = {
        'has_upper': bool(re.search(r'[A-Z]', password)),
        'has_lower': bool(re.search(r'[a-z]', password)),
        'has_digit': bool(re.search(r'\d', password)),
        'has_special': bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', password)),
        'length': len(password)
    }
    
    complexity['meets_requirements'] = (
        complexity['has_upper'] and
        complexity['has_lower'] and
        complexity['has_digit'] and
        complexity['has_special'] and
        complexity['length'] >= 8
    )
    
    return complexity


def validate_password(password, min_length=8, require_complexity=False):
    """
    Validiert ein Passwort gegen die Policy.
    
    Args:
        password: Das zu validierende Passwort
        min_length: Mindestlänge (Standard: 8)
        require_complexity: Ob Komplexität erforderlich ist (Standard: False)
    
    Returns:
        Tuple (is_valid, error_message)
    """
    if not password:
        return False, "Passwort darf nicht leer sein."
    
    if len(password) < min_length:
        return False, f"Passwort muss mindestens {min_length} Zeichen lang sein."
    
    if require_complexity:
        complexity = check_password_complexity(password)
        
        if not complexity['has_upper']:
            return False, "Passwort muss mindestens einen Großbuchstaben enthalten."
        
        if not complexity['has_lower']:
            return False, "Passwort muss mindestens einen Kleinbuchstaben enthalten."
        
        if not complexity['has_digit']:
            return False, "Passwort muss mindestens eine Zahl enthalten."
        
        if not complexity['has_special']:
            return False, "Passwort muss mindestens ein Sonderzeichen enthalten."
    
    return True, None


def get_password_strength(password):
    """
    Bewertet die Stärke eines Passworts.
    Gibt einen Wert zwischen 0 (sehr schwach) und 4 (sehr stark) zurück.
    """
    if not password:
        return 0
    
    strength = 0
    
    # Länge
    if len(password) >= 8:
        strength += 1
    if len(password) >= 12:
        strength += 1
    
    # Komplexität
    complexity = check_password_complexity(password)
    if complexity['has_upper'] and complexity['has_lower']:
        strength += 1
    if complexity['has_digit']:
        strength += 1
    if complexity['has_special']:
        strength += 1
    
    # Begrenze auf 4 (sehr stark)
    return min(strength, 4)
