"""Backup version and category metadata."""

from typing import List

BACKUP_VERSION = "1.1"
SUPPORTED_BACKUP_VERSIONS = {"1.0", "1.1"}

# Strukturierte Kategorien für UI + Orchestration (key, icon, i18n keys)
CATEGORY_DEFINITIONS = [
    {'key': 'settings', 'icon': 'bi-gear', 'label_key': 'settings.admin.backup.categories.settings', 'help_key': 'settings.admin.backup.helps.settings'},
    {'key': 'users', 'icon': 'bi-people', 'label_key': 'settings.admin.backup.categories.users', 'help_key': 'settings.admin.backup.helps.users'},
    {'key': 'emails', 'icon': 'bi-envelope', 'label_key': 'settings.admin.backup.categories.emails', 'help_key': 'settings.admin.backup.helps.emails'},
    {'key': 'appointments', 'icon': 'bi-calendar-event', 'label_key': 'settings.admin.backup.categories.appointments', 'help_key': 'settings.admin.backup.helps.appointments'},
    {'key': 'credentials', 'icon': 'bi-key', 'label_key': 'settings.admin.backup.categories.credentials', 'help_key': 'settings.admin.backup.helps.credentials'},
    {'key': 'files', 'icon': 'bi-folder', 'label_key': 'settings.admin.backup.categories.files', 'help_key': 'settings.admin.backup.helps.files'},
    {'key': 'wiki', 'icon': 'bi-journal-text', 'label_key': 'settings.admin.backup.categories.wiki', 'help_key': 'settings.admin.backup.helps.wiki'},
    {'key': 'comments', 'icon': 'bi-chat-left-text', 'label_key': 'settings.admin.backup.categories.comments', 'help_key': 'settings.admin.backup.helps.comments'},
    {'key': 'inventory', 'icon': 'bi-box-seam', 'label_key': 'settings.admin.backup.categories.inventory', 'help_key': 'settings.admin.backup.helps.inventory'},
    {'key': 'manuals', 'icon': 'bi-book', 'label_key': 'settings.admin.backup.categories.manuals', 'help_key': 'settings.admin.backup.helps.manuals'},
    {'key': 'chats', 'icon': 'bi-chat-dots', 'label_key': 'settings.admin.backup.categories.chats', 'help_key': 'settings.admin.backup.helps.chats'},
    {'key': 'contacts', 'icon': 'bi-person-lines-fill', 'label_key': 'settings.admin.backup.categories.contacts', 'help_key': 'settings.admin.backup.helps.contacts'},
    {'key': 'events', 'icon': 'bi-calendar2-week', 'label_key': 'settings.admin.backup.categories.events', 'help_key': 'settings.admin.backup.helps.events'},
    {'key': 'booking', 'icon': 'bi-calendar-check', 'label_key': 'settings.admin.backup.categories.booking', 'help_key': 'settings.admin.backup.helps.booking'},
    {'key': 'music', 'icon': 'bi-music-note-beamed', 'label_key': 'settings.admin.backup.categories.music', 'help_key': 'settings.admin.backup.helps.music'},
    {'key': 'media_downloader', 'icon': 'bi-download', 'label_key': 'settings.admin.backup.categories.media_downloader', 'help_key': 'settings.admin.backup.helps.media_downloader'},
    {'key': 'assessment', 'icon': 'bi-clipboard2-check', 'label_key': 'settings.admin.backup.categories.assessment', 'help_key': 'settings.admin.backup.helps.assessment'},
    {'key': 'shortlinks', 'icon': 'bi-link-45deg', 'label_key': 'settings.admin.backup.categories.shortlinks', 'help_key': 'settings.admin.backup.helps.shortlinks'},
    {'key': 'excalidraw', 'icon': 'bi-pencil-square', 'label_key': 'settings.admin.backup.categories.excalidraw', 'help_key': 'settings.admin.backup.helps.excalidraw'},
]

# Rückwärtskompatibel: key -> DE-Label (Fallback wenn i18n fehlt)
SUPPORTED_CATEGORIES = {
    'settings': 'Einstellungen',
    'users': 'Benutzer',
    'emails': 'E-Mails',
    'appointments': 'Termine',
    'credentials': 'Zugangsdaten',
    'files': 'Dateien',
    'wiki': 'Wiki',
    'comments': 'Kommentare',
    'inventory': 'Inventar',
    'manuals': 'Handbücher',
    'chats': 'Chats',
    'contacts': 'Kontakte',
    'events': 'Veranstaltungen',
    'booking': 'Buchungen',
    'music': 'Musik',
    'media_downloader': 'Media Downloader',
    'assessment': 'Bewertung',
    'shortlinks': 'Kurzlinks',
    'excalidraw': 'Excalidraw',
}


def _category_selected(categories: List[str], key: str) -> bool:
    return key in categories or 'all' in categories
