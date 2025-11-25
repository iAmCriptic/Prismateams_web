import json
import os
from typing import Any, Dict, Iterable, Optional, Tuple

from flask import current_app, g
from flask_login import current_user

DEFAULT_LANGUAGE = "de"
TRANSLATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "translations")


def _ensure_translations_dir() -> None:
    """Stellt sicher, dass das Übersetzungsverzeichnis existiert."""
    os.makedirs(TRANSLATIONS_DIR, exist_ok=True)


def _translation_path(language: str) -> str:
    return os.path.join(TRANSLATIONS_DIR, f"{language}.json")


_TRANSLATION_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _load_language(language: str) -> Dict[str, Any]:
    """Lädt eine Sprachdatei aus dem JSON-Verzeichnis, erkennt Änderungen automatisch."""
    _ensure_translations_dir()
    path = _translation_path(language)
    if not os.path.exists(path):
        _TRANSLATION_CACHE.pop(language, None)
        return {}

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _TRANSLATION_CACHE.pop(language, None)
        return {}

    cached = _TRANSLATION_CACHE.get(language)
    if cached and cached[0] >= mtime:
        return cached[1]

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                _TRANSLATION_CACHE[language] = (mtime, data)
                return data
    except Exception as exc:  # pragma: no cover - nur Log, kein Test
        if current_app:
            current_app.logger.warning("Konnte Sprachdatei %s nicht laden: %s", path, exc)

    _TRANSLATION_CACHE.pop(language, None)
    return {}


def clear_cache() -> None:
    """Leert den Sprachcache (z.B. nach Updates)."""
    _TRANSLATION_CACHE.clear()


def _walk_translation(data: Dict[str, Any], parts: Iterable[str]) -> Optional[str]:
    """Navigiert durch das Dict gemäß Punkt-Notation."""
    current: Any = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    if isinstance(current, str):
        return current
    return None


def _get_system_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Hilfsfunktion, um SystemSettings abzufragen."""
    try:
        from app.models.settings import SystemSettings

        setting = SystemSettings.query.filter_by(key=key).first()
        if setting and setting.value:
            return setting.value
    except Exception as exc:  # pragma: no cover - nur Log
        if current_app:
            current_app.logger.debug("SystemSetting %s nicht verfügbar: %s", key, exc)
    return default


def resolve_language(explicit_language: Optional[str] = None) -> str:
    """Bestimmt die aktuell zu verwendende Sprache."""
    if explicit_language:
        return explicit_language

    try:
        if current_user and getattr(current_user, "is_authenticated", False):
            user_language = getattr(current_user, "language", None)
            if user_language:
                return user_language
    except Exception:
        pass

    system_language = _get_system_setting("default_language", None)
    if system_language:
        return system_language

    return DEFAULT_LANGUAGE


def available_languages() -> Iterable[str]:
    """Liefert alle vorhandenen Sprachcodes."""
    _ensure_translations_dir()
    try:
        files = os.listdir(TRANSLATIONS_DIR)
    except FileNotFoundError:
        return [DEFAULT_LANGUAGE]

    languages = sorted(
        {os.path.splitext(filename)[0] for filename in files if filename.endswith(".json")}
    )
    return languages or [DEFAULT_LANGUAGE]


def translate(key: str, language: Optional[str] = None, **kwargs: Any) -> str:
    """Übersetzt einen Schlüssel in die gewünschte Sprache."""
    language_code = language or getattr(g, "language", None) or resolve_language()

    parts = key.split(".")
    text = _walk_translation(_load_language(language_code), parts)

    fallback_language = None
    if text is None:
        fallback_language = _get_system_setting("default_language", DEFAULT_LANGUAGE)
        if fallback_language and fallback_language != language_code:
            text = _walk_translation(_load_language(fallback_language), parts)

    if text is None and DEFAULT_LANGUAGE not in (language_code, fallback_language or ""):
        text = _walk_translation(_load_language(DEFAULT_LANGUAGE), parts)

    if text is None:
        text = key

    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            current_app.logger.debug("Formatierung für Schlüssel '%s' fehlgeschlagen", key)
    return text


def init_i18n(app) -> None:
    """Initialisiert i18n im Flask-Context."""

    @app.before_request
    def _set_language_context():
        language_code = resolve_language()
        g.language = language_code
        g.translations = _load_language(language_code)

    @app.context_processor
    def _inject_translations():
        return {
            "current_language": getattr(g, "language", resolve_language()),
            "available_languages": list(available_languages()),
            "_": translate,
            "translate": translate,
            "current_translations": getattr(g, "translations", {}),
        }

    app.jinja_env.globals["_"] = translate
    app.jinja_env.globals["translate"] = translate
    app.jinja_env.filters["translate"] = lambda value, **kwargs: translate(value, **kwargs)


__all__ = [
    "init_i18n",
    "translate",
    "resolve_language",
    "available_languages",
    "clear_cache",
]
import json
import os
from copy import deepcopy
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional

from flask import current_app, g, request
from flask_login import current_user

TRANSLATION_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "translations")
)

DEFAULT_LANGUAGE = "de"
FALLBACK_LANGUAGE = "en"
BASE_SUPPORTED_LANGUAGES = ["de", "en", "pt", "es", "ru"]


def ensure_translation_dir() -> None:
    """Stellt sicher, dass der Übersetzungsordner existiert."""
    os.makedirs(TRANSLATION_DIR, exist_ok=True)


def _safe_logger_warning(message: str) -> None:
    logger = getattr(current_app, "logger", None)
    if logger:
        logger.warning(message)


@lru_cache(maxsize=None)
def _load_translations(language: str) -> Dict[str, Any]:
    """Lädt die Übersetzungen für eine Sprache aus der JSON-Datei."""
    ensure_translation_dir()
    file_path = os.path.join(TRANSLATION_DIR, f"{language}.json")

    if not os.path.exists(file_path):
        return {}

    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except Exception as exc:  # pylint: disable=broad-except
        _safe_logger_warning(f"Übersetzungen für '{language}' konnten nicht geladen werden: {exc}")
        return {}


def clear_translation_cache(language: Optional[str] = None) -> None:
    """Leert den Cache für Übersetzungen (z. B. nach Updates durch die Community)."""
    if language:
        cache = _load_translations.cache_info()  # type: ignore[attr-defined]
        if cache.hits or cache.misses:  # pragma: no branch - informative usage
            _load_translations.cache_clear()  # type: ignore[attr-defined]
    else:
        _load_translations.cache_clear()  # type: ignore[attr-defined]


def _resolve_key(translations: Dict[str, Any], key: str) -> Optional[Any]:
    """Ermittelt den verschachtelten Wert für einen Punkt-Notation-Key."""
    value: Any = translations
    for part in key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def get_available_languages() -> Iterable[str]:
    """Gibt die verfügbaren Sprachen zurück (System-Setting oder Basisliste)."""
    try:
        from app.models.settings import SystemSettings  # lokale Imports vermeiden Zirkularität

        setting = SystemSettings.query.filter_by(key="available_languages").first()
        if setting and setting.value:
            try:
                parsed = json.loads(setting.value)
                if isinstance(parsed, list):
                    codes = [
                        code.strip()
                        for code in parsed
                        if isinstance(code, str) and code.strip()
                    ]
                else:
                    codes = []
            except json.JSONDecodeError:
                codes = [code.strip() for code in setting.value.split(",")]

            filtered = [
                code for code in codes if code in BASE_SUPPORTED_LANGUAGES
            ]
            if filtered:
                return filtered
    except Exception:  # pylint: disable=broad-except
        pass

    return deepcopy(BASE_SUPPORTED_LANGUAGES)


def _get_system_language(setting_key: str, default: str) -> str:
    """Liest eine Sprache aus den SystemSettings mit Fallback."""
    try:
        from app.models.settings import SystemSettings

        setting = SystemSettings.query.filter_by(key=setting_key).first()
        if setting and setting.value:
            value = setting.value.strip()
            if value in BASE_SUPPORTED_LANGUAGES:
                return value
    except Exception:  # pylint: disable=broad-except
        pass
    return default


def determine_language() -> str:
    """Bestimmt die aktuelle Sprache für den Request."""
    lang = request.args.get("lang")
    if lang and lang in BASE_SUPPORTED_LANGUAGES:
        return lang

    try:
        if current_user.is_authenticated:
            user_lang = getattr(current_user, "language", None)
            if user_lang in BASE_SUPPORTED_LANGUAGES:
                return user_lang
    except Exception:  # pylint: disable=broad-except
        pass

    lang = _get_system_language("default_language", DEFAULT_LANGUAGE)
    if lang in BASE_SUPPORTED_LANGUAGES:
        return lang

    return DEFAULT_LANGUAGE


def get_current_language() -> str:
    """Gibt die aktuelle Sprache des Requests zurück (inkl. Caching auf g)."""
    if hasattr(g, "current_language"):
        return g.current_language  # type: ignore[return-value]

    lang = determine_language()
    g.current_language = lang  # type: ignore[attr-defined]
    return lang


def get_translations(language: Optional[str] = None) -> Dict[str, Any]:
    """Liefert die Übersetzungsdaten für eine Sprache (inkl. Fallback)."""
    lang = language or get_current_language()
    translations = _load_translations(lang)

    if not translations and lang != DEFAULT_LANGUAGE:
        translations = _load_translations(DEFAULT_LANGUAGE)
    if not translations and FALLBACK_LANGUAGE not in (lang, DEFAULT_LANGUAGE):
        translations = _load_translations(FALLBACK_LANGUAGE)

    return translations or {}


def translate(key: str, language: Optional[str] = None, **kwargs: Any) -> str:
    """Übersetzt einen Schlüssel und formatiert Platzhalter."""
    lang = language or get_current_language()
    text = _resolve_key(get_translations(lang), key)

    if text is None and lang != FALLBACK_LANGUAGE:
        text = _resolve_key(get_translations(FALLBACK_LANGUAGE), key)
    if text is None:
        text = key  # fallback zeigt Schlüssel an

    if isinstance(text, dict):
        text = key

    if kwargs:
        try:
            text = str(text).format(**kwargs)
        except Exception:  # pylint: disable=broad-except
            pass

    return str(text)


def register_i18n(app) -> None:
    """Registriert Helper, Filter und Hooks beim Flask-App-Objekt."""
    ensure_translation_dir()
    app.config.setdefault("AVAILABLE_LANGUAGES", list(BASE_SUPPORTED_LANGUAGES))

    @app.before_request
    def set_language_context() -> None:
        g.current_language = determine_language()  # type: ignore[attr-defined]

    @app.context_processor
    def inject_i18n_helpers() -> Dict[str, Any]:
        lang = get_current_language()
        return {
            "_": translate,
            "translate": translate,
            "current_language": lang,
            "available_languages": list(get_available_languages()),
            "current_translations": get_translations(lang),
        }

    @app.template_filter("translate")
    def translate_filter(key: str, **kwargs: Any) -> str:
        return translate(key, **kwargs)

    app.jinja_env.globals["_"] = translate


def _(key: str, **kwargs: Any) -> str:
    """Kurzalias für translate – wird in Templates & Python genutzt."""
    return translate(key, **kwargs)


