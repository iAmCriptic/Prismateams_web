from flask import Blueprint, render_template, redirect, url_for, session, request, jsonify
from flask_login import login_required, current_user
from app.models.calendar import CalendarEvent, Calendar
from app.models.chat import ChatMessage, ChatMember
from app.models.email import EmailMessage, EmailPermission
from app.models.file import File
from app.models.credential import Credential, CredentialFavorite
from app.models.wiki import WikiPage, WikiFavorite
from app.models.inventory import BorrowTransaction
from app.models.booking import BookingRequest
from app.models.contact import Contact
from app.models.kanban import KanbanActivity, KanbanBoard
from app.models.user import User
from app import db
from app.utils.common import is_module_enabled, check_for_updates, portal_now_naive
from app.utils.i18n import translate
from app.utils.module_visibility import accessible_query, can_view_item
from app.utils.kanban_access import accessible_boards_query, can_view_board
from app.utils.multi_mailboxes import get_accessible_mailboxes
from app.utils.navigation import (
    get_dashboard_modules,
    normalize_dashboard_module_order,
    DASHBOARD_MODULE_ORDER_KEY,
)
from config import ABOUT_RELEASE_VERSION
from app.utils.multi_calendars import (
    events_query_for_calendars,
    list_sidebar_calendars,
    calendar_to_dict,
    is_calendar_multi_enabled,
)
from datetime import datetime
from sqlalchemy import and_, or_
import json
import logging

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard', __name__)

# Bei jedem Release erhöhen, damit alle Nutzer What's New einmalig erneut sehen.
# Führendes „v“ entfernen, Zusätze wie „DEVELOPMENT“ bleiben erhalten.
WHATS_NEW_VERSION = str(ABOUT_RELEASE_VERSION or '').strip().lstrip('vV') or '3.1.0'

WIDGET_MODULE_MAP = {
    'termine': 'module_calendar',
    'nachrichten': 'module_chat',
    'emails': 'module_email',
    'dateien': 'module_files',
    'passwoerter': 'module_credentials',
    'neue_wikieintraege': 'module_wiki',
    'meine_wikis': 'module_wiki',
    'meine_ausleihen': 'module_inventory',
    'buchungen': 'module_booking',
    'kontakte': 'module_contacts',
    'kanban_aenderungen': 'module_kanban',
}

AVAILABLE_LINK_KEYS = [
    'files', 'credentials', 'manuals', 'chat', 'calendar', 'events', 'email',
    'contacts', 'inventory', 'inventory_stock', 'inventory_quick_scan',
    'inventory_checkout', 'inventory_borrows', 'inventory_sets',
    'inventory_tool', 'inventory_print_qr', 'inventory_statistics',
    'wiki', 'shortlinks', 'kanban', 'excalidraw', 'booking', 'music', 'media_downloader', 'file_converter',
    'assessment', 'assessment_evaluate', 'assessment_my_evaluations',
    'assessment_ranking', 'assessment_inspections', 'assessment_warnings',
    'settings', 'profile', 'logout',
]

SIMPLE_WIDGET_TYPES = [
    'nachrichten', 'emails', 'dateien', 'passwoerter',
    'neue_wikieintraege', 'meine_wikis', 'meine_ausleihen', 'buchungen',
    'kanban_aenderungen',
]

ALL_WIDGET_TYPES = [
    'termine', 'kontakte', 'nachrichten', 'emails', 'dateien', 'passwoerter',
    'neue_wikieintraege', 'meine_wikis', 'meine_ausleihen', 'buchungen',
    'kanban_aenderungen',
]

DASHBOARD_GRID_COLS = 4
DASHBOARD_WIDGET_LIST_LIMIT = 12


def _rects_overlap(a, b):
    return (
        a['x'] < b['x'] + b['w']
        and a['x'] + a['w'] > b['x']
        and a['y'] < b['y'] + b['h']
        and a['y'] + a['h'] > b['y']
    )


def _normalize_dashboard_widgets(widgets, cols=DASHBOARD_GRID_COLS):
    """Ensure w/h/x/y on the 5.5rem grid (grid_v=2); pack missing positions."""
    occupied = []
    result = []

    def fits(x, y, w, h, skip_id=None):
        if x < 1 or y < 1 or w < 1 or h < 1 or x + w - 1 > cols:
            return False
        rect = {'x': x, 'y': y, 'w': w, 'h': h}
        for other in occupied:
            if skip_id and other.get('id') == skip_id:
                continue
            if _rects_overlap(rect, other):
                return False
        return True

    def first_fit(w, h):
        y = 1
        while y < 500:
            for x in range(1, cols - w + 2):
                if fits(x, y, w, h):
                    return x, y
            y += 1
        return 1, y

    for raw in widgets or []:
        item = dict(raw)
        try:
            w = int(item.get('w') or 1)
        except (TypeError, ValueError):
            w = 1
        try:
            h = int(item.get('h') or 1)
        except (TypeError, ValueError):
            h = 1
        try:
            grid_v = int(item.get('grid_v') or 1)
        except (TypeError, ValueError):
            grid_v = 1
        if grid_v < 2:
            h = h * 2
        w = max(1, min(cols, w))
        h = max(1, min(6, h))

        x = item.get('x')
        y = item.get('y')
        try:
            x = int(x) if x is not None else None
            y = int(y) if y is not None else None
        except (TypeError, ValueError):
            x, y = None, None

        if x is None or y is None or not fits(x, y, w, h):
            x, y = first_fit(w, h)

        item.update({'w': w, 'h': h, 'x': x, 'y': y, 'grid_v': 2})
        occupied.append({'id': item.get('id'), 'x': x, 'y': y, 'w': w, 'h': h})
        result.append(item)

    result.sort(key=lambda w: (int(w.get('y') or 1), int(w.get('x') or 1)))
    return result


_KANBAN_ACTIVITY_LABELS = {
    'board_created': 'Board erstellt',
    'board_closed': 'Board geschlossen',
    'board_reopened': 'Board wieder geöffnet',
    'list_created': 'Liste erstellt',
    'list_updated': 'Liste aktualisiert',
    'list_deleted': 'Liste gelöscht',
    'card_created': 'Karte erstellt',
    'card_updated': 'Karte aktualisiert',
    'card_moved': 'Karte verschoben',
    'card_archived': 'Karte archiviert',
    'card_restored': 'Karte wiederhergestellt',
    'member_added': 'Mitglied hinzugefügt',
    'attachment_added': 'Anhang hinzugefügt',
}


def _kanban_activity_label(action: str) -> str:
    return _KANBAN_ACTIVITY_LABELS.get(action or '', action or '')


def _visibility_label(visibility: str) -> str:
    key = {
        'private': 'visibility.nav.private',
        'team': 'visibility.nav.team',
        'public': 'visibility.nav.public',
    }.get(visibility or '')
    return translate(key) if key else (visibility or '')


def _flatten_sidebar_calendars(user):
    groups = list_sidebar_calendars(user)
    cals = []
    seen = set()
    for key in ('personals', 'teams', 'publics', 'events', 'others', 'personal', 'public'):
        item = groups.get(key)
        rows = item if isinstance(item, list) else ([item] if item is not None else [])
        for cal in rows:
            if cal.id in seen:
                continue
            seen.add(cal.id)
            cals.append(calendar_to_dict(cal, user))
    return cals


def _load_termine_for_widget(user, calendar_ids):
    try:
        base_filters = [CalendarEvent.start_time >= portal_now_naive()]
        if calendar_ids:
            if is_calendar_multi_enabled():
                q = events_query_for_calendars(user, calendar_ids, base_filters=base_filters)
            else:
                q = CalendarEvent.query.filter(
                    *base_filters,
                    CalendarEvent.calendar_id.in_(calendar_ids),
                )
        elif is_calendar_multi_enabled():
            q = events_query_for_calendars(user, None, base_filters=base_filters)
        else:
            q = CalendarEvent.query.filter(*base_filters)
        events = q.order_by(CalendarEvent.start_time).limit(DASHBOARD_WIDGET_LIST_LIMIT).all()
        calendars_meta = []
        if calendar_ids:
            for cid in calendar_ids:
                cal = Calendar.query.get(cid)
                if cal:
                    calendars_meta.append(calendar_to_dict(cal, user))
        return {'events': events, 'calendars': calendars_meta}
    except Exception as e:
        logger.warning(f"Fehler beim Laden der Termine: {e}")
        return {'events': [], 'calendars': []}


def _load_emails_for_widget(user, mailbox_id):
    """mailbox_id None = alle zugänglichen Postfächer; sonst nur das gewählte."""
    try:
        email_perm = EmailPermission.query.filter_by(user_id=user.id).first()
        if not email_perm or not email_perm.can_read:
            return []
        q = EmailMessage.query.filter_by(is_sent=False, folder='INBOX')
        accessible = {mb.id for mb in get_accessible_mailboxes(user, 'read')}
        if mailbox_id is None:
            # Hauptpostfach (NULL) + alle zugänglichen Multi-Postfächer
            if accessible:
                q = q.filter(
                    or_(
                        EmailMessage.mailbox_id.is_(None),
                        EmailMessage.mailbox_id.in_(accessible),
                    )
                )
            else:
                q = q.filter(EmailMessage.mailbox_id.is_(None))
        else:
            if mailbox_id not in accessible:
                return []
            q = q.filter(EmailMessage.mailbox_id == mailbox_id)
        return q.order_by(EmailMessage.received_at.desc()).limit(DASHBOARD_WIDGET_LIST_LIMIT).all()
    except Exception as e:
        logger.warning(f"Fehler beim Laden der E-Mails: {e}")
        return []


def _load_credentials_for_widget(user, credential_ids):
    try:
        ids = list(credential_ids or [])
        if not ids:
            ids = [
                row.credential_id
                for row in CredentialFavorite.query.filter_by(user_id=user.id).all()
            ]
        if not ids:
            return []
        found = (
            accessible_query(user, Credential, 'credentials')
            .filter(Credential.id.in_(ids))
            .all()
        )
        by_id = {c.id: c for c in found}
        ordered = [by_id[i] for i in ids if i in by_id]
        return ordered[:DASHBOARD_WIDGET_LIST_LIMIT]
    except Exception as e:
        logger.warning(f"Fehler beim Laden der Passwörter: {e}")
        return []


def _load_kanban_activity_for_widget(user, board_ids):
    try:
        accessible = accessible_boards_query(user, include_closed=False).all()
        accessible_ids = {b.id for b in accessible}
        if board_ids:
            target_ids = [bid for bid in board_ids if bid in accessible_ids]
        else:
            target_ids = list(accessible_ids)
        if not target_ids:
            return []
        rows = (
            KanbanActivity.query
            .filter(KanbanActivity.board_id.in_(target_ids))
            .order_by(KanbanActivity.created_at.desc())
            .limit(DASHBOARD_WIDGET_LIST_LIMIT)
            .all()
        )
        board_by_id = {b.id: b for b in accessible if b.id in target_ids}
        activities = []
        for a in rows:
            board = board_by_id.get(a.board_id) or KanbanBoard.query.get(a.board_id)
            if board and not can_view_board(user, board):
                continue
            activities.append({
                'id': a.id,
                'action': a.action,
                'action_label': _kanban_activity_label(a.action),
                'detail': a.detail,
                'card_id': a.card_id,
                'board_id': a.board_id,
                'board_title': board.title if board else '',
                'board_visibility': getattr(board, 'visibility', None) if board else None,
                'user_name': a.user.full_name if a.user else '',
                'created_at': a.created_at,
            })
        return activities[:DASHBOARD_WIDGET_LIST_LIMIT]
    except Exception as e:
        logger.warning(f"Fehler beim Laden der Kanban-Änderungen: {e}")
        return []


def _load_widget_payload(user, widgets):
    """Lädt Daten pro Widget-Instanz. Rückgabe: dict id -> payload."""
    enabled_types = {w['type'] for w in widgets}
    payload = {}

    unread_messages = []
    if 'nachrichten' in enabled_types and is_module_enabled('module_chat'):
        try:
            user_chats = ChatMember.query.filter_by(user_id=user.id).all()
            for membership in user_chats:
                messages = ChatMessage.query.filter(
                    and_(
                        ChatMessage.chat_id == membership.chat_id,
                        ChatMessage.created_at > membership.last_read_at,
                        ChatMessage.sender_id != user.id,
                        ChatMessage.is_deleted == False
                    )
                ).order_by(ChatMessage.created_at.desc()).limit(DASHBOARD_WIDGET_LIST_LIMIT).all()
                unread_messages.extend(messages)
            unread_messages = sorted(unread_messages, key=lambda x: x.created_at, reverse=True)[:DASHBOARD_WIDGET_LIST_LIMIT]
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Nachrichten: {e}")

    recent_files = []
    if 'dateien' in enabled_types and is_module_enabled('module_files'):
        try:
            recent_files = File.query.filter_by(
                uploaded_by=user.id
            ).order_by(File.updated_at.desc()).limit(DASHBOARD_WIDGET_LIST_LIMIT).all()
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Dateien: {e}")

    recent_wiki_pages = []
    if 'neue_wikieintraege' in enabled_types and is_module_enabled('module_wiki'):
        try:
            recent_wiki_pages = (
                accessible_query(user, WikiPage, 'wiki')
                .order_by(WikiPage.updated_at.desc())
                .limit(DASHBOARD_WIDGET_LIST_LIMIT)
                .all()
            )
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Wiki-Seiten: {e}")

    my_wiki_favorites = []
    if 'meine_wikis' in enabled_types and is_module_enabled('module_wiki'):
        try:
            favorites = WikiFavorite.query.filter_by(
                user_id=user.id
            ).order_by(WikiFavorite.created_at.desc()).limit(DASHBOARD_WIDGET_LIST_LIMIT).all()
            my_wiki_favorites = [
                fav.wiki_page
                for fav in favorites
                if fav.wiki_page and can_view_item(user, fav.wiki_page, 'wiki')
            ]
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Wiki-Favoriten: {e}")

    my_borrow_groups = []
    if 'meine_ausleihen' in enabled_types and is_module_enabled('module_inventory') and not getattr(user, 'is_guest', False):
        try:
            borrows = BorrowTransaction.query.filter_by(
                borrower_id=user.id, status='active'
            ).order_by(BorrowTransaction.borrow_date.desc()).all()
            grouped = {}
            for b in borrows:
                group_key = b.borrow_group_id if b.borrow_group_id else b.transaction_number
                if group_key not in grouped:
                    grouped[group_key] = {
                        'borrow_group_id': b.borrow_group_id,
                        'borrow_date': b.borrow_date,
                        'expected_return_date': b.expected_return_date,
                        'transactions': [],
                        'product_count': 0,
                        'is_overdue': False
                    }
                grouped[group_key]['transactions'].append(b)
                grouped[group_key]['product_count'] += 1
                if b.expected_return_date and grouped[group_key]['expected_return_date']:
                    if b.expected_return_date > grouped[group_key]['expected_return_date']:
                        grouped[group_key]['expected_return_date'] = b.expected_return_date
                if b.is_overdue:
                    grouped[group_key]['is_overdue'] = True
            my_borrow_groups = sorted(grouped.values(), key=lambda x: x['borrow_date'], reverse=True)[:DASHBOARD_WIDGET_LIST_LIMIT]
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Ausleihen: {e}")

    new_booking_requests = []
    total_pending_bookings = 0
    if 'buchungen' in enabled_types and is_module_enabled('module_booking') and not getattr(user, 'is_guest', False):
        try:
            new_booking_requests = BookingRequest.query.filter_by(
                status='pending'
            ).order_by(BookingRequest.created_at.desc()).limit(DASHBOARD_WIDGET_LIST_LIMIT).all()
            total_pending_bookings = BookingRequest.query.filter_by(status='pending').count()
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Buchungen: {e}")

    for w in widgets:
        wid = w['id']
        wtype = w['type']
        if wtype == 'termine' and is_module_enabled('module_calendar'):
            payload[wid] = _load_termine_for_widget(user, w.get('calendar_ids') or [])
        elif wtype == 'kontakte' and is_module_enabled('module_contacts'):
            contact_ids = w.get('contact_ids') or []
            contacts = []
            if contact_ids:
                found = (
                    accessible_query(user, Contact, 'contacts')
                    .filter(Contact.id.in_(contact_ids))
                    .all()
                )
                by_id = {c.id: c for c in found}
                contacts = [by_id[i] for i in contact_ids if i in by_id]
            payload[wid] = {'contacts': contacts}
        elif wtype == 'nachrichten':
            payload[wid] = {'messages': unread_messages}
        elif wtype == 'emails':
            emails = []
            if is_module_enabled('module_email') and not getattr(user, 'is_guest', False):
                emails = _load_emails_for_widget(user, w.get('mailbox_id', None))
            payload[wid] = {
                'emails': emails,
                'mailbox_id': w.get('mailbox_id', None),
            }
        elif wtype == 'dateien':
            payload[wid] = {'files': recent_files}
        elif wtype == 'passwoerter':
            creds = []
            if is_module_enabled('module_credentials'):
                creds = _load_credentials_for_widget(user, w.get('credential_ids') or [])
            payload[wid] = {'credentials': creds}
        elif wtype == 'neue_wikieintraege':
            payload[wid] = {'pages': recent_wiki_pages}
        elif wtype == 'meine_wikis':
            payload[wid] = {'pages': my_wiki_favorites}
        elif wtype == 'meine_ausleihen':
            payload[wid] = {'groups': my_borrow_groups}
        elif wtype == 'buchungen':
            payload[wid] = {
                'requests': new_booking_requests,
                'total_pending': total_pending_bookings,
            }
        elif wtype == 'kanban_aenderungen' and is_module_enabled('module_kanban'):
            payload[wid] = {
                'activities': _load_kanban_activity_for_widget(user, w.get('board_ids') or []),
            }
    return payload


def _build_widget_options(user):
    """Picker-Daten für Live-Widget-Einstellungen."""
    options = {
        'calendars': [],
        'mailboxes': [],
        'credentials': [],
        'boards': [],
        'widget_types': [],
    }

    for wtype in ALL_WIDGET_TYPES:
        module = WIDGET_MODULE_MAP.get(wtype)
        if module and not is_module_enabled(module):
            continue
        options['widget_types'].append({
            'type': wtype,
            'label': translate(f'dashboard.edit.widgets.items.{wtype}.label'),
            'description': translate(f'dashboard.edit.widgets.items.{wtype}.description'),
            'configurable': wtype in (
                'termine', 'kontakte', 'emails', 'passwoerter', 'kanban_aenderungen'
            ),
            'once': wtype in SIMPLE_WIDGET_TYPES,
        })

    if is_module_enabled('module_calendar'):
        options['calendars'] = _flatten_sidebar_calendars(user)

    if is_module_enabled('module_email') and not getattr(user, 'is_guest', False):
        options['mailboxes'] = [
            {
                'id': None,
                'name': translate('dashboard.widgets.email.all_mailboxes'),
                'type': 'main',
            }
        ]
        for mb in get_accessible_mailboxes(user, 'read'):
            options['mailboxes'].append({
                'id': mb.id,
                'name': mb.display_name or mb.name,
                'type': mb.mailbox_type,
            })

    if is_module_enabled('module_credentials'):
        try:
            creds = (
                accessible_query(user, Credential, 'credentials')
                .order_by(Credential.website_name.asc())
                .limit(200)
                .all()
            )
            options['credentials'] = [
                {
                    'id': c.id,
                    'name': c.website_name,
                    'visibility': c.visibility,
                    'visibility_label': _visibility_label(c.visibility),
                }
                for c in creds
            ]
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Credential-Optionen: {e}")

    if is_module_enabled('module_kanban'):
        try:
            boards = (
                accessible_boards_query(user, include_closed=False)
                .order_by(KanbanBoard.updated_at.desc())
                .limit(100)
                .all()
            )
            options['boards'] = [
                {
                    'id': b.id,
                    'title': b.title,
                    'visibility': b.visibility,
                    'visibility_label': _visibility_label(b.visibility),
                }
                for b in boards
            ]
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Board-Optionen: {e}")

    return options


@dashboard_bp.route('/dashboard')
@login_required
def index():
    """Main dashboard view."""
    if current_user.is_admin and not session.get('email_permissions_ensured'):
        try:
            current_user.ensure_email_permissions()
            session['email_permissions_ensured'] = True
        except Exception as e:
            logger.warning(f"Fehler beim Sicherstellen der E-Mail-Berechtigungen: {e}")

    config = current_user.get_dashboard_config()
    widgets = list(config.get('widgets') or [])

    if getattr(current_user, 'is_guest', False):
        from app.utils.access_control import get_accessible_modules
        accessible_modules = get_accessible_modules(current_user)
        widgets = [
            w for w in widgets
            if WIDGET_MODULE_MAP.get(w['type']) in accessible_modules
        ]
        widgets = []

    visible_widgets = []
    for w in widgets:
        module = WIDGET_MODULE_MAP.get(w['type'])
        if module and not is_module_enabled(module):
            continue
        visible_widgets.append(w)

    visible_widgets = _normalize_dashboard_widgets(visible_widgets)

    widget_data = _load_widget_payload(current_user, visible_widgets) if not getattr(current_user, 'is_guest', False) else {}
    widget_options = _build_widget_options(current_user) if not getattr(current_user, 'is_guest', False) else {}
    dashboard_modules = get_dashboard_modules(current_user)

    from app.blueprints.setup import is_setup_needed
    if is_setup_needed():
        return redirect(url_for('setup.setup'))

    update_info = None
    if current_user.is_admin and current_user.show_update_notifications:
        try:
            update_info = check_for_updates()
        except Exception as e:
            logger.warning(f"Fehler beim Prüfen auf Updates: {e}")

    guest_has_chat_access = False
    guest_has_file_access = False
    guest_accessible_modules = []
    if getattr(current_user, 'is_guest', False):
        from app.utils.access_control import get_accessible_modules, get_guest_accessible_items
        guest_accessible_modules = get_accessible_modules(current_user)
        if 'module_chat' in guest_accessible_modules:
            guest_has_chat_access = ChatMember.query.filter_by(user_id=current_user.id).count() > 0
        if 'module_files' in guest_accessible_modules:
            accessible_files, accessible_folders = get_guest_accessible_items(current_user)
            guest_has_file_access = len(accessible_files) > 0 or len(accessible_folders) > 0

    hour = datetime.now().hour
    if hour < 12:
        greeting_key = 'dashboard.greeting.morning'
    elif hour < 18:
        greeting_key = 'dashboard.greeting.afternoon'
    else:
        greeting_key = 'dashboard.greeting.evening'

    is_guest = getattr(current_user, 'is_guest', False)
    show_portal_onboarding = (not is_guest) and not getattr(current_user, 'portal_onboarding_completed', False)
    seen_version = getattr(current_user, 'whats_new_seen_version', None)
    show_whats_new = (not is_guest) and (not show_portal_onboarding) and (seen_version != WHATS_NEW_VERSION)
    if show_whats_new:
        try:
            current_user.whats_new_seen_version = WHATS_NEW_VERSION
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.warning(f"What's New gesehen-Status konnte nicht gespeichert werden: {e}")

    return render_template(
        'dashboard/index.html',
        dashboard_widgets=visible_widgets,
        widget_data=widget_data,
        widget_options=widget_options,
        dashboard_modules=dashboard_modules,
        dashboard_config=config,
        update_info=update_info,
        guest_has_chat_access=guest_has_chat_access,
        guest_has_file_access=guest_has_file_access,
        guest_accessible_modules=guest_accessible_modules,
        greeting_key=greeting_key,
        whats_new_version=WHATS_NEW_VERSION,
        show_whats_new=show_whats_new,
        show_portal_onboarding=show_portal_onboarding,
    )


@dashboard_bp.route('/api/dashboard/whats-new/seen', methods=['POST'])
@login_required
def api_whats_new_seen():
    """Markiert What's New für die aktuelle Release-Version als gesehen."""
    if getattr(current_user, 'is_guest', False):
        return jsonify({'success': True, 'version': WHATS_NEW_VERSION, 'skipped': True})
    current_user.whats_new_seen_version = WHATS_NEW_VERSION
    db.session.commit()
    return jsonify({'success': True, 'version': WHATS_NEW_VERSION})


@dashboard_bp.route('/api/dashboard/onboarding/complete', methods=['POST'])
@login_required
def api_onboarding_complete():
    """Markiert die Portal-Onboarding-Tour als abgeschlossen."""
    if getattr(current_user, 'is_guest', False):
        return jsonify({'success': True, 'skipped': True})
    current_user.portal_onboarding_completed = True
    db.session.commit()
    return jsonify({'success': True})


@dashboard_bp.route('/dashboard/edit', methods=['GET', 'POST'])
@login_required
def edit():
    """Legacy-Edit-Seite → Live-Bearbeitung auf dem Dashboard."""
    return redirect(url_for('dashboard.index'))


@dashboard_bp.route('/api/dashboard/config', methods=['GET', 'POST'])
@login_required
def api_config():
    """API-Endpunkt für Dashboard-Konfiguration."""
    if getattr(current_user, 'is_guest', False) and request.method == 'POST':
        return jsonify({'error': translate('dashboard.errors.guests_cannot_edit')}), 403

    if request.method == 'GET':
        return jsonify(current_user.get_dashboard_config())

    data = request.get_json()
    if not data:
        return jsonify({'error': translate('dashboard.errors.no_data_submitted')}), 400

    existing = current_user.get_dashboard_config()
    if 'widgets' in data:
        existing['widgets'] = _normalize_dashboard_widgets(data.get('widgets') or [])
    elif 'enabled_widgets' in data:
        types = data.get('enabled_widgets') or []
        existing['widgets'] = _normalize_dashboard_widgets([
            {'id': User._new_widget_instance_id(), 'type': t} for t in types
        ])
    if 'remove_widget_id' in data:
        rid = data.get('remove_widget_id')
        existing['widgets'] = _normalize_dashboard_widgets(
            [w for w in existing.get('widgets', []) if w.get('id') != rid]
        )
    if 'quick_access_links' in data:
        existing['quick_access_links'] = data.get('quick_access_links') or []
    if 'mobile_nav_slots' in data and isinstance(data.get('mobile_nav_slots'), dict):
        existing['mobile_nav_slots'] = data['mobile_nav_slots']
    if DASHBOARD_MODULE_ORDER_KEY in data:
        existing[DASHBOARD_MODULE_ORDER_KEY] = normalize_dashboard_module_order(
            data.get(DASHBOARD_MODULE_ORDER_KEY) or [],
            current_user,
        )

    current_user.set_dashboard_config(existing)
    return jsonify({'success': True, 'config': current_user.get_dashboard_config()})


@dashboard_bp.route('/api/dashboard/options', methods=['GET'])
@login_required
def api_options():
    """Picker-Optionen für Live-Widget-Einstellungen."""
    if getattr(current_user, 'is_guest', False):
        return jsonify({})
    return jsonify(_build_widget_options(current_user))


@dashboard_bp.route('/api/dashboard/update-banner', methods=['POST'])
@login_required
def api_update_banner():
    """API-Endpunkt für Update-Banner-Aktionen."""
    if not current_user.is_admin:
        return jsonify({'error': translate('dashboard.errors.admin_only')}), 403

    data = request.get_json() or {}
    action = data.get('action')

    if action == 'dismiss':
        return jsonify({'success': True, 'message': translate('dashboard.messages.banner_dismissed')})

    if action == 'disable':
        current_user.show_update_notifications = False
        db.session.commit()
        return jsonify({'success': True, 'message': translate('dashboard.messages.update_notifications_disabled')})

    return jsonify({'error': translate('dashboard.errors.invalid_action')}), 400
