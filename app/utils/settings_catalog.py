"""Searchable catalog of settings pages for the settings sidebar search."""

from __future__ import annotations

from flask import url_for
from flask_login import AnonymousUserMixin

from app.utils.common import is_module_enabled
from app.utils.i18n import translate
from app.utils.multi_mailboxes import is_email_multi_enabled, user_is_team_leader


def _entry(title: str, endpoint: str, role: str, keywords: str = '', anchor: str = '', **url_kwargs):
    return {
        'title': title,
        'url': url_for(endpoint, **url_kwargs) + (f'#{anchor}' if anchor else ''),
        'role': role,
        'keywords': keywords.lower(),
    }


def build_settings_catalog(user) -> list[dict]:
    if not user or isinstance(user, AnonymousUserMixin) or not user.is_authenticated:
        return []

    catalog: list[dict] = []

    catalog.append(_entry(
        translate('settings.sidebar.start'),
        'settings.index',
        'user',
        'start übersicht home dashboard',
    ))
    catalog.append(_entry(
        translate('settings.index.cards.profile.title'),
        'settings.profile',
        'user',
        'profil name email telefon bild avatar',
    ))
    catalog.append(_entry(
        translate('settings.index.cards.appearance.title'),
        'settings.appearance',
        'user',
        'darstellung theme dark mode sprache akzentfarbe layout',
    ))
    catalog.append(_entry(
        translate('settings.index.cards.notifications.title'),
        'settings.notifications',
        'user',
        'benachrichtigungen push chat email kalender',
    ))
    catalog.append(_entry(
        translate('settings.index.cards.security.title'),
        'settings.security',
        'user',
        'sicherheit passwort 2fa zwei faktor geräte session google login',
    ))
    catalog.append(_entry(
        translate('settings.index.cards.about.title'),
        'settings.about',
        'user',
        'über about version prismateams',
    ))

    if is_module_enabled('module_files'):
        catalog.append(_entry(
            translate('settings.cloud_import.title'),
            'settings.cloud_import',
            'user',
            'cloud import nextcloud google drive umzug sync dateien transfer',
        ))

    if is_module_enabled('module_email') and is_email_multi_enabled():
        catalog.append(_entry(
            translate('settings.index.cards.my_mailboxes.title'),
            'settings.my_mailboxes',
            'user',
            'postfach mailbox email privat',
        ))

    is_leader = user_is_team_leader(user)
    if is_leader and not user.is_admin:
        catalog.append(_entry(
            translate('settings.admin.cards.teams.title'),
            'settings.admin_teams',
            'leader',
            'teams mitglieder teamleitung',
        ))
        catalog.append(_entry(
            translate('settings.team_settings.title'),
            'settings.team_settings',
            'leader',
            'team module teameinstellungen aktivieren deaktivieren',
        ))

    if not user.is_admin:
        return catalog

    catalog.append(_entry(
        translate('settings.admin.cards.user_management.title'),
        'settings.admin_users',
        'admin',
        'benutzer nutzer user rollen gast admin',
    ))
    catalog.append(_entry(
        translate('settings.admin.cards.teams.title'),
        'settings.admin_teams',
        'admin',
        'teams mitglieder teamleitung',
    ))
    catalog.append(_entry(
        translate('settings.admin.cards.whitelist.title'),
        'settings.admin_whitelist',
        'admin',
        'whitelist freigabe email domain',
    ))
    catalog.append(_entry(
        translate('settings.admin.cards.system_settings.title'),
        'settings.admin_system',
        'admin',
        'system portal logo name zeitzone suche indexing',
    ))
    catalog.append(_entry(
        translate('settings.admin.cards.legal.title'),
        'settings.admin_legal',
        'admin',
        'rechtliches datenschutz impressum nutzungsbedingungen terms privacy',
    ))
    catalog.append(_entry(
        translate('settings.admin.cards.modules.title'),
        'settings.admin_modules',
        'admin',
        'module aktivieren deaktivieren private team public sichtbarkeit',
    ))
    catalog.append(_entry(
        translate('settings.integrations.heading'),
        'settings.admin_integrations',
        'admin',
        'verknüpfungen integration google microsoft oauth spotify deezer youtube',
    ))
    catalog.append(_entry(
        'Spotify',
        'settings.admin_integrations',
        'admin',
        'spotify musik oauth client connect',
        anchor='spotify',
    ))
    catalog.append(_entry(
        'Deezer',
        'settings.admin_integrations',
        'admin',
        'deezer musik app id',
        anchor='deezer',
    ))
    catalog.append(_entry(
        'YouTube',
        'settings.admin_integrations',
        'admin',
        'youtube musik google oauth',
        anchor='youtube',
    ))
    catalog.append(_entry(
        translate('settings.admin.cards.backup.title'),
        'settings.admin_backup',
        'admin',
        'backup import export sicherung',
    ))
    catalog.append(_entry(
        translate('settings.admin.cards.registration_options.title'),
        'settings.admin_registration',
        'admin',
        'registrierung bot schutz captcha recaptcha turnstile',
    ))

    if is_module_enabled('module_booking'):
        catalog.append(_entry(
            translate('booking.admin.cards.booking_forms.title'),
            'settings.booking_forms',
            'admin',
            'booking buchung formulare',
        ))
    if is_module_enabled('module_music'):
        catalog.append(_entry(
            translate('booking.admin.cards.music_module.title'),
            'settings.admin_music',
            'admin',
            'musik provider musicbrainz reihenfolge',
        ))
    if is_module_enabled('module_email'):
        catalog.append(_entry(
            translate('settings.sidebar.email_module'),
            'settings.admin_email_module',
            'admin',
            'email postfach footer smtp',
        ))
    if is_module_enabled('module_inventory'):
        catalog.append(_entry(
            translate('settings.sidebar.inventory'),
            'settings.admin_inventory_settings',
            'admin',
            'inventar lager qr ownership',
        ))
    if is_module_enabled('module_calendar'):
        catalog.append(_entry(
            translate('settings.admin.cards.calendar_settings.title'),
            'settings.admin_calendar_settings',
            'admin',
            'kalender export import ical',
        ))
    catalog.append(_entry(
        translate('settings.admin.cards.file_settings.title'),
        'settings.admin_file_settings',
        'admin',
        'dateien speicher sharing dropbox onlyoffice format',
    ))

    return catalog
