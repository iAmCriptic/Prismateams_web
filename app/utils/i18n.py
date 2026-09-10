"""Portal-i18n: eine Registrierung, ein Katalog-Cache, kein volles Dict im Template-Context."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, Optional, Tuple

from flask import current_app, g, has_app_context, has_request_context, request
from flask_login import current_user

DEFAULT_LANGUAGE = "de"
FALLBACK_LANGUAGE = "en"
BASE_SUPPORTED_LANGUAGES = ["de", "en", "pt", "es", "ru"]

TRANSLATION_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "translations")
)
TRANSLATIONS_DIR = TRANSLATION_DIR

_TRANSLATION_FILE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def ensure_translation_dir() -> None:
    os.makedirs(TRANSLATION_DIR, exist_ok=True)


def _translation_path(language: str) -> str:
    return os.path.join(TRANSLATION_DIR, f"{language}.json")


def _safe_logger_warning(message: str) -> None:
    logger = getattr(current_app, "logger", None) if has_app_context() else None
    if logger:
        logger.warning(message)


def _load_translations(language: str) -> Dict[str, Any]:
    """Lädt die JSON-Datei einer Sprache (mtime-Cache, geteilte Referenz)."""
    ensure_translation_dir()
    file_path = _translation_path(language)

    if not os.path.exists(file_path):
        _TRANSLATION_FILE_CACHE.pop(language, None)
        return {}

    try:
        mtime = os.path.getmtime(file_path)
    except OSError:
        _TRANSLATION_FILE_CACHE.pop(language, None)
        return {}

    cached = _TRANSLATION_FILE_CACHE.get(language)
    if cached and cached[0] >= mtime:
        return cached[1]

    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                _TRANSLATION_FILE_CACHE[language] = (mtime, data)
                return data
    except Exception as exc:
        _safe_logger_warning(f"Übersetzungen für '{language}' konnten nicht geladen werden: {exc}")

    _TRANSLATION_FILE_CACHE.pop(language, None)
    return {}


def _load_language(language: str) -> Dict[str, Any]:
    return _load_translations(language)


def clear_translation_cache(language: Optional[str] = None) -> None:
    if language:
        _TRANSLATION_FILE_CACHE.pop(language, None)
    else:
        _TRANSLATION_FILE_CACHE.clear()


def clear_cache() -> None:
    clear_translation_cache()


def _portal_display_name() -> str:
    if has_request_context():
        cached_name = getattr(g, "_portal_display_name", None)
        if cached_name:
            return str(cached_name)

    app_name = current_app.config.get("APP_NAME", "Prismateams") if has_app_context() else "Prismateams"
    portal_name = str(app_name or "Prismateams").strip() or "Prismateams"

    try:
        from app.models.settings import SystemSettings

        portal_name_setting = SystemSettings.query.filter_by(key="portal_name").first()
        if portal_name_setting and portal_name_setting.value and portal_name_setting.value.strip():
            portal_name = portal_name_setting.value.strip()
        else:
            organization_name_setting = SystemSettings.query.filter_by(key="organization_name").first()
            if (
                organization_name_setting
                and organization_name_setting.value
                and organization_name_setting.value.strip()
            ):
                portal_name = organization_name_setting.value.strip()
    except Exception:
        pass

    if has_request_context():
        g._portal_display_name = portal_name
    return portal_name


def _replace_legacy_portal_name(text: str) -> str:
    portal_name = _portal_display_name()
    replacements = (
        "Team Portal",
        "Team portal",
        "team portal",
        "Teamportal",
        "teamportal",
    )
    for old_value in replacements:
        text = text.replace(old_value, portal_name)
    return text


def get_available_languages() -> Iterable[str]:
    try:
        from app.models.settings import SystemSettings

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

            filtered = [code for code in codes if code in BASE_SUPPORTED_LANGUAGES]
            if filtered:
                return filtered
    except Exception:
        pass

    return list(BASE_SUPPORTED_LANGUAGES)


def available_languages() -> Iterable[str]:
    return get_available_languages()


def _get_system_language(setting_key: str, default: str) -> str:
    try:
        from app.models.settings import SystemSettings

        setting = SystemSettings.query.filter_by(key=setting_key).first()
        if setting and setting.value:
            value = setting.value.strip()
            if value in BASE_SUPPORTED_LANGUAGES:
                return value
    except Exception:
        pass
    return default


def determine_language() -> str:
    if has_request_context():
        lang = request.args.get("lang")
        if lang and lang in BASE_SUPPORTED_LANGUAGES:
            return lang

        try:
            if current_user.is_authenticated:
                user_lang = getattr(current_user, "language", None)
                if user_lang in BASE_SUPPORTED_LANGUAGES:
                    return user_lang
        except Exception:
            pass

    lang = _get_system_language("default_language", DEFAULT_LANGUAGE)
    if lang in BASE_SUPPORTED_LANGUAGES:
        return lang

    return DEFAULT_LANGUAGE


def resolve_language(explicit_language: Optional[str] = None) -> str:
    if explicit_language:
        return explicit_language
    return determine_language()


def get_current_language() -> str:
    if has_request_context() and hasattr(g, "current_language"):
        return g.current_language
    lang = determine_language()
    if has_request_context():
        g.current_language = lang
    return lang


def get_translations(language: Optional[str] = None) -> Dict[str, Any]:
    lang = language or get_current_language()
    translations = _load_translations(lang)

    if not translations and lang != DEFAULT_LANGUAGE:
        translations = _load_translations(DEFAULT_LANGUAGE)
    if not translations and FALLBACK_LANGUAGE not in (lang, DEFAULT_LANGUAGE):
        translations = _load_translations(FALLBACK_LANGUAGE)

    return translations or {}


def _resolve_key(translations: Dict[str, Any], key: str) -> Optional[Any]:
    value: Any = translations
    for part in key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def i18n_ns(*path: str) -> Any:
    """Nur den benötigten Teilbaum — nicht den ganzen Katalog."""
    data: Any = get_translations()
    for part in path:
        if not isinstance(data, dict):
            return {}
        data = data.get(part)
        if data is None:
            return {}
    return data


def translate(key: str, language: Optional[str] = None, **kwargs: Any) -> str:
    lang = language or get_current_language()
    text = _resolve_key(get_translations(lang), key)

    if text is None and lang != FALLBACK_LANGUAGE:
        text = _resolve_key(get_translations(FALLBACK_LANGUAGE), key)
    if text is None and DEFAULT_LANGUAGE not in (lang, FALLBACK_LANGUAGE):
        text = _resolve_key(get_translations(DEFAULT_LANGUAGE), key)
    if text is None:
        text = key

    if isinstance(text, dict):
        text = key

    if kwargs:
        try:
            text = str(text).format(**kwargs)
        except Exception:
            pass

    return _replace_legacy_portal_name(str(text))


def _(key: str, **kwargs: Any) -> str:
    return translate(key, **kwargs)


def register_i18n(app) -> None:
    """Einmal: before_request + Context ohne volles Translations-Dict."""
    if app.extensions.get("prismateams_i18n"):
        return
    app.extensions["prismateams_i18n"] = True

    ensure_translation_dir()
    app.config.setdefault("AVAILABLE_LANGUAGES", list(BASE_SUPPORTED_LANGUAGES))

    @app.before_request
    def set_language_context() -> None:
        g.current_language = determine_language()

    @app.context_processor
    def inject_i18n_helpers() -> Dict[str, Any]:
        lang = get_current_language()
        return {
            "_": translate,
            "translate": translate,
            "current_language": lang,
            "available_languages": list(get_available_languages()),
            "i18n_ns": i18n_ns,
        }

    @app.template_filter("translate")
    def translate_filter(key: str, **kwargs: Any) -> str:
        return translate(key, **kwargs)

    app.jinja_env.globals["_"] = translate
    app.jinja_env.globals["translate"] = translate
    app.jinja_env.globals["i18n_ns"] = i18n_ns
    app.jinja_env.filters["translate"] = lambda value, **kwargs: translate(value, **kwargs)


def init_i18n(app) -> None:
    """Alias — nicht zusätzlich zu register_i18n aufrufen."""
    register_i18n(app)


__all__ = [
    "init_i18n",
    "register_i18n",
    "translate",
    "_",
    "i18n_ns",
    "resolve_language",
    "determine_language",
    "available_languages",
    "get_available_languages",
    "get_current_language",
    "get_translations",
    "clear_cache",
    "clear_translation_cache",
]
