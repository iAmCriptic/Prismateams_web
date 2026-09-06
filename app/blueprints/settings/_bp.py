"""Shared Flask blueprint and helpers for the settings module."""

import json

from flask import Blueprint, flash, jsonify, redirect, request, url_for

from app.models.chat import Chat

settings_bp = Blueprint("settings", "app.blueprints.settings")


@settings_bp.context_processor
def inject_settings_search_catalog():
    """JSON catalog for settings sidebar search + kanban import targets."""
    from flask_login import current_user
    if not current_user.is_authenticated:
        return {}
    if not request.endpoint or not str(request.endpoint).startswith('settings.'):
        return {}
    from app.utils.settings_catalog import build_settings_catalog
    catalog = build_settings_catalog(current_user)
    ctx = {'settings_search_catalog_json': json.dumps(catalog, ensure_ascii=False)}
    try:
        from app.utils.common import is_module_enabled
        from app.utils.kanban_access import allowed_import_board_targets
        if is_module_enabled('module_kanban'):
            ctx['kanban_import_targets'] = allowed_import_board_targets(current_user)
        else:
            ctx['kanban_import_targets'] = []
    except Exception:
        ctx['kanban_import_targets'] = []
    return ctx


def _settings_redirect(endpoint, **values):
    """Redirect unter Beibehaltung von embed=1 (Setup-Modal)."""
    if request.args.get('embed') or request.form.get('embed'):
        values.setdefault('embed', 1)
    return redirect(url_for(endpoint, **values))


def _wants_json_response() -> bool:
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    best = request.accept_mimetypes.best_match(['application/json', 'text/html'])
    return best == 'application/json'


def _settings_save_response(ok: bool, message: str, redirect_endpoint: str | None = None, status: int = 200, redirect_kwargs: dict | None = None, **extra):
    """JSON for autosave clients, otherwise flash + redirect."""
    if _wants_json_response():
        payload = {'ok': ok, 'message': message}
        payload.update(extra)
        return jsonify(payload), (status if not ok else 200)
    flash(message, 'success' if ok else 'danger')
    if redirect_endpoint:
        return _settings_redirect(redirect_endpoint, **(redirect_kwargs or {}))
    return redirect(request.url)


def _guest_account_form_options():
    """Module, Freigaben und Chats für Gast-Erstellung/-Bearbeitung."""
    guest_modules = [
        ('module_calendar', 'Kalender'),
        ('module_events', 'Veranstaltungen'),
        ('module_contacts', 'Kontakte'),
        ('module_manuals', 'Anleitungen'),
        ('module_inventory', 'Lagerverwaltung'),
        ('module_wiki', 'Wiki'),
        ('module_music', 'Musik'),
        ('module_media_downloader', 'Media Downloader'),
        ('module_file_converter', 'Dateikonverter'),
        ('module_assessment', 'Bewertung'),
        ('module_shortlinks', 'Kurzlinks'),
        ('module_kanban', 'Kanban'),
        ('module_excalidraw', 'Excalidraw'),
        ('module_surveys', 'Umfragen'),
        ('module_meetings', 'Meetings'),
    ]
    from app.utils.mirotalk import mirotalk_configured
    if not mirotalk_configured():
        guest_modules = [item for item in guest_modules if item[0] != 'module_meetings']
    from app.utils.public_share import get_assignable_public_shares
    assignable_shares = get_assignable_public_shares()

    all_chats_list = Chat.query.order_by(Chat.created_at).all()
    all_chats = []
    main_chat_added = False
    for chat in all_chats_list:
        if chat.is_main_chat and not main_chat_added:
            all_chats.append(chat)
            main_chat_added = True
        elif not chat.is_main_chat:
            all_chats.append(chat)

    return guest_modules, assignable_shares, all_chats


LANGUAGE_FALLBACK_NAMES = {
    'de': 'Deutsch',
    'en': 'English',
    'pt': 'Português',
    'es': 'Español',
    'ru': 'Русский'
}

# Übersetzungabdeckung relativ zu Deutsch (alle Keys vorhanden = 100)
LANGUAGE_COMPLETENESS = {
    'de': 100,
    'en': 100,
    'es': 11,
    'pt': 11,
    'ru': 11,
}


def _language_badge_grade(percent):
    """Farbstufe für Übersetzungs-Badge (low → full)."""
    if percent is None:
        return None
    if percent >= 100:
        return 'full'
    if percent >= 70:
        return 'high'
    if percent >= 40:
        return 'mid'
    return 'low'
