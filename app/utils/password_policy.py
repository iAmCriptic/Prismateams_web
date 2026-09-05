"""Passwort-Policy Utility für die Validierung von Passwörtern."""
import re

from flask import current_app, has_app_context

# Einheitliche Portal-Policy (Register, Change, Reset, Setup, Assessment)
DEFAULT_PASSWORD_MIN_LENGTH = 12
DEFAULT_PASSWORD_REQUIRE_COMPLEXITY = True


def get_password_policy():
    """Aktuelle Policy aus Config (mit sicheren Defaults)."""
    min_length = DEFAULT_PASSWORD_MIN_LENGTH
    require_complexity = DEFAULT_PASSWORD_REQUIRE_COMPLEXITY
    if has_app_context():
        min_length = int(current_app.config.get('PASSWORD_MIN_LENGTH', min_length) or min_length)
        require_complexity = bool(
            current_app.config.get('PASSWORD_REQUIRE_COMPLEXITY', require_complexity)
        )
    return max(min_length, 8), require_complexity


def check_password_complexity(password):
    """
    Prüft die Komplexität eines Passworts.
    Gibt ein Dictionary mit Details zurück.
    """
    complexity = {
        'has_upper': bool(re.search(r'[A-Z]', password)),
        'has_lower': bool(re.search(r'[a-z]', password)),
        'has_digit': bool(re.search(r'\d', password)),
        # Beliebiges Nicht-Alphanumerisch = Sonderzeichen
        'has_special': bool(re.search(r'[^A-Za-z0-9]', password)),
        'length': len(password),
    }

    min_length, _ = get_password_policy()
    complexity['meets_requirements'] = (
        complexity['has_upper']
        and complexity['has_lower']
        and complexity['has_digit']
        and complexity['has_special']
        and complexity['length'] >= min_length
    )

    return complexity


def validate_password(password, min_length=None, require_complexity=None):
    """
    Validiert ein Passwort gegen die Policy.

    Defaults: 12 Zeichen + Komplexität (Groß/Klein/Zahl/Sonderzeichen).
    Explizite Argumente überschreiben nur wenn gesetzt (nicht None).
    """
    policy_min, policy_complexity = get_password_policy()
    if min_length is None:
        min_length = policy_min
    if require_complexity is None:
        require_complexity = policy_complexity

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

    if len(password) >= 8:
        strength += 1
    if len(password) >= 12:
        strength += 1

    complexity = check_password_complexity(password)
    if complexity['has_upper'] and complexity['has_lower']:
        strength += 1
    if complexity['has_digit']:
        strength += 1
    if complexity['has_special']:
        strength += 1

    return min(strength, 4)
