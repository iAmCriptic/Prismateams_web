"""Shared navigation link registry and mobile nav slot resolution."""

from flask import url_for

from app.utils.access_control import has_module_access
from app.utils.common import is_module_enabled

MOBILE_NAV_SLOT_KEYS = (
    'chat',
    'calendar',
    'files',
    'email',
    'credentials',
    'manuals',
    'inventory',
    'wiki',
    'booking',
    'music',
)

MOBILE_NAV_DEFAULT_SLOTS = {
    'left': 'chat',
    'right': 'calendar',
}

NAV_LINK_REGISTRY = {
    'files': {
        'endpoint': 'files.index',
        'icon': 'bi-folder',
        'label_key': 'layout.nav.files',
        'module': 'module_files',
        'active_prefix': 'files',
    },
    'credentials': {
        'endpoint': 'credentials.index',
        'icon': 'bi-key',
        'label_key': 'layout.nav.credentials',
        'module': 'module_credentials',
        'active_prefix': 'credentials',
    },
    'manuals': {
        'endpoint': 'manuals.index',
        'icon': 'bi-book',
        'label_key': 'layout.nav.manuals',
        'module': 'module_manuals',
        'active_prefix': 'manuals',
    },
    'chat': {
        'endpoint': 'chat.index',
        'icon': 'bi-chat-dots',
        'label_key': 'layout.nav.chats',
        'module': 'module_chat',
        'active_prefix': 'chat',
    },
    'calendar': {
        'endpoint': 'calendar.index',
        'icon': 'bi-calendar-event',
        'label_key': 'layout.nav.calendar',
        'module': 'module_calendar',
        'active_prefix': 'calendar',
    },
    'email': {
        'endpoint': 'email.index',
        'icon': 'bi-envelope',
        'label_key': 'layout.nav.email',
        'module': 'module_email',
        'active_prefix': 'email',
    },
    'inventory': {
        'endpoint': 'inventory.dashboard',
        'icon': 'bi-box-seam',
        'label_key': 'layout.nav.inventory',
        'module': 'module_inventory',
        'active_prefix': 'inventory',
    },
    'wiki': {
        'endpoint': 'wiki.index',
        'icon': 'bi-journal-text',
        'label_key': 'layout.nav.wiki',
        'module': 'module_wiki',
        'active_prefix': 'wiki',
    },
    'booking': {
        'endpoint': 'booking.requests',
        'icon': 'bi-calendar-check',
        'label_key': 'layout.nav.booking',
        'module': 'module_booking',
        'active_prefix': 'booking',
    },
    'music': {
        'endpoint': 'music.index',
        'icon': 'bi-music-note-beamed',
        'label_key': 'layout.nav.music',
        'module': 'module_music',
        'active_prefix': 'music',
    },
}


def get_mobile_nav_slots(user):
    """Return configured mobile nav slot keys for a user."""
    if user is None:
        return dict(MOBILE_NAV_DEFAULT_SLOTS)

    config = user.get_dashboard_config()
    slots = config.get('mobile_nav_slots') or {}
    left = slots.get('left', MOBILE_NAV_DEFAULT_SLOTS['left'])
    right = slots.get('right', MOBILE_NAV_DEFAULT_SLOTS['right'])

    if left not in MOBILE_NAV_SLOT_KEYS:
        left = MOBILE_NAV_DEFAULT_SLOTS['left']
    if right not in MOBILE_NAV_SLOT_KEYS:
        right = MOBILE_NAV_DEFAULT_SLOTS['right']

    return {'left': left, 'right': right}


def is_nav_link_available(key, user):
    """Check whether a nav link key is enabled and accessible."""
    if key not in NAV_LINK_REGISTRY:
        return False

    entry = NAV_LINK_REGISTRY[key]
    module = entry.get('module')
    if module and not is_module_enabled(module):
        return False
    if user is not None and module and not has_module_access(user, module):
        return False
    return True


def resolve_nav_link(key, user):
    """Resolve a nav link key to a render-ready dict, or None if unavailable."""
    if not is_nav_link_available(key, user):
        return None

    entry = NAV_LINK_REGISTRY[key]
    return {
        'key': key,
        'url': url_for(entry['endpoint']),
        'icon': entry['icon'],
        'label_key': entry['label_key'],
        'module': entry.get('module'),
        'active_prefix': entry.get('active_prefix', key),
    }


def get_available_mobile_nav_options(user):
    """Return list of available nav options for mobile nav slot dropdowns."""
    options = []
    for key in MOBILE_NAV_SLOT_KEYS:
        if is_nav_link_available(key, user):
            entry = NAV_LINK_REGISTRY[key]
            options.append({
                'key': key,
                'icon': entry['icon'],
                'label_key': entry['label_key'],
            })
    return options


def validate_mobile_nav_slot(key, user):
    """Validate and return a slot key, or None if invalid."""
    if key not in MOBILE_NAV_SLOT_KEYS:
        return None
    if not is_nav_link_available(key, user):
        return None
    return key
