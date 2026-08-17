"""Shared navigation link registry, desktop launcher, and mobile nav slots."""

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
    'excalidraw',
    'booking',
    'music',
    'kanban',
)

MOBILE_NAV_DEFAULT_SLOTS = {
    'left': 'chat',
    'right': 'calendar',
}

NAV_FAVORITES_CONFIG_KEY = 'desktop_nav_favorites'

DESKTOP_NAV_ORDER = (
    'dashboard',
    'chat',
    'files',
    'calendar',
    'events',
    'email',
    'contacts',
    'credentials',
    'manuals',
    'inventory',
    'wiki',
    'shortlinks',
    'kanban',
    'excalidraw',
    'booking',
    'music',
    'media_downloader',
    'assessment',
)

NAV_LINK_REGISTRY = {
    'dashboard': {
        'endpoint': 'dashboard.index',
        'icon': 'bi-house-door',
        'label_key': 'layout.nav.dashboard',
        'module': None,
        'active_prefix': 'dashboard',
        'in_launcher': True,
    },
    'files': {
        'endpoint': 'files.index',
        'icon': 'bi-folder',
        'label_key': 'layout.nav.files',
        'module': 'module_files',
        'active_prefix': 'files',
        'in_launcher': True,
    },
    'credentials': {
        'endpoint': 'credentials.index',
        'icon': 'bi-key',
        'label_key': 'layout.nav.credentials',
        'module': 'module_credentials',
        'active_prefix': 'credentials',
        'in_launcher': True,
    },
    'manuals': {
        'endpoint': 'manuals.index',
        'icon': 'bi-book',
        'label_key': 'layout.nav.manuals',
        'module': 'module_manuals',
        'active_prefix': 'manuals',
        'in_launcher': True,
    },
    'chat': {
        'endpoint': 'chat.index',
        'icon': 'bi-chat-dots',
        'label_key': 'layout.nav.chats',
        'module': 'module_chat',
        'active_prefix': 'chat',
        'in_launcher': True,
    },
    'calendar': {
        'endpoint': 'calendar.index',
        'icon': 'bi-calendar-event',
        'label_key': 'layout.nav.calendar',
        'module': 'module_calendar',
        'active_prefix': 'calendar',
        'in_launcher': True,
    },
    'events': {
        'endpoint': 'events.index',
        'icon': 'bi-calendar2-week',
        'label_key': 'layout.nav.events',
        'module': 'module_calendar',
        'active_prefix': 'events',
        'in_launcher': True,
    },
    'email': {
        'endpoint': 'email.index',
        'icon': 'bi-envelope',
        'label_key': 'layout.nav.email',
        'module': 'module_email',
        'active_prefix': 'email',
        'in_launcher': True,
    },
    'contacts': {
        'endpoint': 'contacts.index',
        'icon': 'bi-person-lines-fill',
        'label_key': 'layout.nav.contacts',
        'module': 'module_contacts',
        'active_prefix': 'contacts',
        'in_launcher': True,
    },
    'inventory': {
        'endpoint': 'inventory.dashboard',
        'icon': 'bi-box-seam',
        'label_key': 'layout.nav.inventory',
        'module': 'module_inventory',
        'active_prefix': 'inventory',
        'in_launcher': True,
    },
    'wiki': {
        'endpoint': 'wiki.index',
        'icon': 'bi-journal-text',
        'label_key': 'layout.nav.wiki',
        'module': 'module_wiki',
        'active_prefix': 'wiki',
        'in_launcher': True,
    },
    'shortlinks': {
        'endpoint': 'shortlinks.index',
        'icon': 'bi-link-45deg',
        'label_key': 'layout.nav.shortlinks',
        'module': 'module_shortlinks',
        'active_prefix': 'shortlinks',
        'in_launcher': True,
    },
    'booking': {
        'endpoint': 'booking.requests',
        'icon': 'bi-calendar-check',
        'label_key': 'layout.nav.booking',
        'module': 'module_booking',
        'active_prefix': 'booking',
        'in_launcher': True,
        'exclude_contains': ('settings',),
    },
    'music': {
        'endpoint': 'music.index',
        'icon': 'bi-music-note-beamed',
        'label_key': 'layout.nav.music',
        'module': 'module_music',
        'active_prefix': 'music',
        'in_launcher': True,
        'exclude_contains': ('settings',),
    },
    'kanban': {
        'endpoint': 'kanban.index',
        'icon': 'bi-kanban',
        'label_key': 'layout.nav.kanban',
        'module': 'module_kanban',
        'active_prefix': 'kanban',
        'in_launcher': True,
    },
    'excalidraw': {
        'endpoint': 'excalidraw.index',
        'icon': 'bi-pencil-square',
        'label_key': 'layout.nav.excalidraw',
        'module': 'module_excalidraw',
        'active_prefix': 'excalidraw',
        'in_launcher': True,
    },
    'media_downloader': {
        'endpoint': 'media_downloader.index',
        'icon': 'bi-download',
        'label_key': 'layout.nav.media_downloader',
        'module': 'module_media_downloader',
        'active_prefix': 'media_downloader',
        'in_launcher': True,
    },
    'assessment': {
        'endpoint': 'assessment.general.home',
        'icon': 'bi-clipboard2-check',
        'label_key': 'layout.nav.assessment',
        'module': 'module_assessment',
        'active_prefix': 'assessment',
        'in_launcher': True,
    },
    'settings': {
        'endpoint': 'settings.index',
        'icon': 'bi-gear',
        'label_key': 'layout.nav.settings',
        'module': None,
        'active_prefix': 'settings',
        'in_launcher': False,
    },
}


def get_mobile_nav_slots(user):
    """Return configured mobile nav slot keys for a user."""
    if user is None:
        return dict(MOBILE_NAV_DEFAULT_SLOTS)

    # Assessment-User haben kein Portal-Dashboard / keine Mobile-Slot-Config.
    if user.__class__.__name__ == 'AssessmentUser' or not hasattr(user, 'get_dashboard_config'):
        return dict(MOBILE_NAV_DEFAULT_SLOTS)

    config = user.get_dashboard_config() or {}
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


def _nav_url(endpoint):
    try:
        return url_for(endpoint)
    except Exception:
        return None


def resolve_nav_link(key, user):
    """Resolve a nav link key to a render-ready dict, or None if unavailable."""
    if not is_nav_link_available(key, user):
        return None

    entry = NAV_LINK_REGISTRY[key]
    url = _nav_url(entry['endpoint'])
    if not url:
        return None

    return {
        'key': key,
        'url': url,
        'icon': entry['icon'],
        'label_key': entry['label_key'],
        'module': entry.get('module'),
        'active_prefix': entry.get('active_prefix', key),
        'in_launcher': bool(entry.get('in_launcher', True)),
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


def _endpoint_matches(endpoint, entry):
    if not endpoint:
        return False
    for token in entry.get('exclude_contains') or ():
        if token in endpoint:
            return False
    prefix = entry.get('active_prefix') or ''
    target = entry.get('endpoint') or ''
    if endpoint == target:
        return True
    if prefix and (endpoint.startswith(prefix + '.') or endpoint.startswith(prefix + '_')):
        return True
    return False


def get_desktop_nav_modules(user):
    """Launcher modules the user may open, in display order."""
    modules = []
    for key in DESKTOP_NAV_ORDER:
        entry = NAV_LINK_REGISTRY.get(key)
        if not entry or not entry.get('in_launcher', True):
            continue
        resolved = resolve_nav_link(key, user)
        if resolved:
            modules.append(resolved)
    return modules


def get_current_nav_module(endpoint, user=None):
    """Best matching nav entry for the current request endpoint."""
    if not endpoint:
        return None

    matches = []
    for key, entry in NAV_LINK_REGISTRY.items():
        if not _endpoint_matches(endpoint, entry):
            continue
        prefix = entry.get('active_prefix') or key
        matches.append((len(prefix), key))

    if not matches:
        return None

    matches.sort(reverse=True)
    key = matches[0][1]
    resolved = resolve_nav_link(key, user)
    if resolved:
        return resolved

    entry = NAV_LINK_REGISTRY[key]
    url = _nav_url(entry['endpoint']) or '#'
    return {
        'key': key,
        'url': url,
        'icon': entry['icon'],
        'label_key': entry['label_key'],
        'module': entry.get('module'),
        'active_prefix': entry.get('active_prefix', key),
        'in_launcher': bool(entry.get('in_launcher', True)),
    }


def normalize_nav_favorite_keys(keys, user=None):
    """Return unique, available launcher keys (order preserved)."""
    if not isinstance(keys, list):
        return []

    seen = set()
    normalized = []
    for raw in keys:
        if not isinstance(raw, str):
            continue
        key = raw.strip()
        if not key or key in seen:
            continue
        entry = NAV_LINK_REGISTRY.get(key)
        if not entry or not entry.get('in_launcher', True):
            continue
        if user is not None and not is_nav_link_available(key, user):
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


def get_nav_favorite_keys(user):
    """Stored favorite keys for a user (not yet availability-filtered)."""
    if user is None or not hasattr(user, 'get_dashboard_config'):
        return []
    config = user.get_dashboard_config() or {}
    keys = config.get(NAV_FAVORITES_CONFIG_KEY)
    return normalize_nav_favorite_keys(keys if isinstance(keys, list) else [])


def get_nav_favorites(user):
    """Resolved favorite modules for the launcher."""
    favorites = []
    for key in get_nav_favorite_keys(user):
        resolved = resolve_nav_link(key, user)
        if resolved and resolved.get('in_launcher'):
            favorites.append(resolved)
    return favorites
