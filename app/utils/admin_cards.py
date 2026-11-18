"""Helpers and catalog for limited admin access to individual settings cards."""

from __future__ import annotations

from flask_login import AnonymousUserMixin


ADMIN_CARD_SECTIONS = [
    {
        'key': 'users',
        'title_key': 'settings.admin.sections.users.title',
        'cards': [
            {'key': 'admin_users', 'title_key': 'settings.admin.cards.user_management.title', 'module_key': None},
            {'key': 'admin_teams', 'title_key': 'settings.admin.cards.teams.title', 'module_key': None},
            {'key': 'admin_whitelist', 'title_key': 'settings.admin.cards.whitelist.title', 'module_key': None},
        ],
    },
    {
        'key': 'system',
        'title_key': 'settings.admin.sections.system.title',
        'cards': [
            {'key': 'admin_system', 'title_key': 'settings.admin.cards.system_settings.title', 'module_key': None},
            {'key': 'admin_legal', 'title_key': 'settings.admin.cards.legal.title', 'module_key': None},
            {'key': 'admin_modules', 'title_key': 'settings.admin.cards.modules.title', 'module_key': None},
            {'key': 'admin_integrations', 'title_key': 'settings.integrations.heading', 'module_key': None},
            {'key': 'admin_backup', 'title_key': 'settings.admin.cards.backup.title', 'module_key': None},
            {'key': 'admin_registration', 'title_key': 'settings.admin.cards.registration_options.title', 'module_key': None},
        ],
    },
    {
        'key': 'modules',
        'title_key': 'settings.sidebar.sections.modules',
        'cards': [
            {'key': 'admin_booking', 'title_key': 'layout.nav.booking', 'module_key': 'module_booking'},
            {'key': 'admin_music', 'title_key': 'booking.admin.cards.music_module.title', 'module_key': 'module_music'},
            {'key': 'admin_email', 'title_key': 'settings.sidebar.email_module', 'module_key': 'module_email'},
            {'key': 'admin_inventory', 'title_key': 'settings.sidebar.inventory', 'module_key': 'module_inventory'},
            {'key': 'admin_calendar', 'title_key': 'settings.admin.cards.calendar_settings.title', 'module_key': 'module_calendar'},
            {'key': 'admin_events', 'title_key': None, 'fallback_title': 'Veranstaltungen', 'module_key': 'module_events'},
            {'key': 'admin_helpers', 'title_key': 'helpers.heading', 'module_key': 'module_helpers'},
            {'key': 'admin_files', 'title_key': 'settings.admin.cards.file_settings.title', 'module_key': None},
        ],
    },
]

ALL_ADMIN_CARD_KEYS: tuple[str, ...] = tuple(
    card['key']
    for section in ADMIN_CARD_SECTIONS
    for card in section['cards']
)

_ADMIN_CARD_KEY_SET: frozenset[str] = frozenset(ALL_ADMIN_CARD_KEYS)


def _is_eligible_user(user) -> bool:
    if not user or isinstance(user, AnonymousUserMixin):
        return False
    if not getattr(user, 'is_authenticated', False):
        return False
    if not getattr(user, 'is_active', False):
        return False
    return True


def get_user_admin_cards(user) -> list[str]:
    """Return all admin card keys the user is allowed to access."""
    if not _is_eligible_user(user):
        return []
    if getattr(user, 'is_admin', False):
        return list(ALL_ADMIN_CARD_KEYS)
    if getattr(user, 'is_guest', False):
        return []
    perms = getattr(user, 'admin_card_permissions', None)
    if perms is None:
        return []
    return [p.card_key for p in perms if p.card_key in _ADMIN_CARD_KEY_SET]


def has_admin_card_access(user, card_key: str) -> bool:
    """Return True if user is full admin or holds limited admin access to card_key."""
    if not _is_eligible_user(user):
        return False
    if getattr(user, 'is_admin', False):
        return True
    if getattr(user, 'is_guest', False):
        return False
    if card_key not in _ADMIN_CARD_KEY_SET:
        return False
    perms = getattr(user, 'admin_card_permissions', None)
    if perms is None:
        return False
    return any(p.card_key == card_key for p in perms)


def has_any_admin_card_access(user) -> bool:
    """Return True if user is full admin or holds at least one limited admin card."""
    if not _is_eligible_user(user):
        return False
    if getattr(user, 'is_admin', False):
        return True
    if getattr(user, 'is_guest', False):
        return False
    return bool(get_user_admin_cards(user))


def get_admin_card_catalog_for_ui() -> list[dict]:
    """Build localized section/card list for the user-roles management UI."""
    from app.utils.i18n import translate
    from app.utils.common import is_module_enabled

    sections_out = []
    for section in ADMIN_CARD_SECTIONS:
        cards_out = []
        for card in section['cards']:
            module_key = card.get('module_key')
            if module_key and not is_module_enabled(module_key):
                continue
            title = (
                translate(card['title_key'])
                if card.get('title_key')
                else card.get('fallback_title', card['key'])
            )
            cards_out.append({
                'key': card['key'],
                'title': title,
            })
        if cards_out:
            sections_out.append({
                'key': section['key'],
                'title': translate(section['title_key']),
                'cards': cards_out,
            })
    return sections_out
