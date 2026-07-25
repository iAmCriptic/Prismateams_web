from flask import Blueprint, render_template, redirect, url_for, session, request, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.models.calendar import CalendarEvent, Calendar
from app.models.chat import ChatMessage, ChatMember
from app.models.email import EmailMessage, EmailPermission
from app.models.file import File
from app.models.credential import Credential
from app.models.wiki import WikiPage, WikiFavorite
from app.models.inventory import BorrowTransaction
from app.models.booking import BookingRequest
from app.models.contact import Contact
from app.models.user import User
from app import db
from app.utils.common import is_module_enabled, check_for_updates, portal_now_naive
from app.utils.i18n import translate
from app.utils.multi_calendars import (
    events_query_for_calendars,
    list_sidebar_calendars,
    calendar_to_dict,
    is_calendar_multi_enabled,
)
from datetime import datetime
from sqlalchemy import and_
import json
import logging

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard', __name__)

# Bei jedem Release erhöhen, damit alle Nutzer What's New einmalig erneut sehen.
WHATS_NEW_VERSION = '3.0.0'

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
}

AVAILABLE_LINK_KEYS = [
    'files', 'credentials', 'manuals', 'chat', 'calendar', 'events', 'email',
    'contacts', 'inventory', 'wiki', 'shortlinks', 'booking', 'music',
    'media_downloader', 'assessment', 'settings', 'profile', 'logout',
]

SIMPLE_WIDGET_TYPES = [
    'nachrichten', 'emails', 'dateien', 'passwoerter',
    'neue_wikieintraege', 'meine_wikis', 'meine_ausleihen', 'buchungen',
]


def _flatten_sidebar_calendars(user):
    groups = list_sidebar_calendars(user)
    cals = []
    for key in ('personal', 'public', 'others'):
        item = groups.get(key)
        if key == 'others':
            for cal in (item or []):
                cals.append(calendar_to_dict(cal, user))
        elif item is not None:
            cals.append(calendar_to_dict(item, user))
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
        events = q.order_by(CalendarEvent.start_time).limit(3).all()
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


def _load_widget_payload(user, widgets):
    """Lädt Daten pro Widget-Instanz. Rückgabe: dict id -> payload."""
    enabled_types = {w['type'] for w in widgets}
    payload = {}

    # Shared simple-widget caches (loaded once if any instance needs them)
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
                ).order_by(ChatMessage.created_at.desc()).limit(5).all()
                unread_messages.extend(messages)
            unread_messages = sorted(unread_messages, key=lambda x: x.created_at, reverse=True)[:5]
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Nachrichten: {e}")

    recent_emails = []
    if 'emails' in enabled_types and is_module_enabled('module_email') and not getattr(user, 'is_guest', False):
        try:
            email_perm = EmailPermission.query.filter_by(user_id=user.id).first()
            if email_perm and email_perm.can_read:
                recent_emails = EmailMessage.query.filter_by(
                    is_sent=False, folder='INBOX'
                ).order_by(EmailMessage.received_at.desc()).limit(5).all()
        except Exception as e:
            logger.warning(f"Fehler beim Laden der E-Mails: {e}")

    recent_files = []
    if 'dateien' in enabled_types and is_module_enabled('module_files'):
        try:
            recent_files = File.query.filter_by(
                uploaded_by=user.id
            ).order_by(File.updated_at.desc()).limit(3).all()
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Dateien: {e}")

    favorite_credentials = []
    if 'passwoerter' in enabled_types and is_module_enabled('module_credentials'):
        try:
            favorite_credentials = Credential.query.filter_by(
                is_favorite=True
            ).order_by(Credential.updated_at.desc()).limit(2).all()
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Passwort-Favoriten: {e}")

    recent_wiki_pages = []
    if 'neue_wikieintraege' in enabled_types and is_module_enabled('module_wiki'):
        try:
            recent_wiki_pages = WikiPage.query.order_by(WikiPage.updated_at.desc()).limit(3).all()
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Wiki-Seiten: {e}")

    my_wiki_favorites = []
    if 'meine_wikis' in enabled_types and is_module_enabled('module_wiki'):
        try:
            favorites = WikiFavorite.query.filter_by(
                user_id=user.id
            ).order_by(WikiFavorite.created_at.desc()).limit(5).all()
            my_wiki_favorites = [fav.wiki_page for fav in favorites if fav.wiki_page]
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
            my_borrow_groups = sorted(grouped.values(), key=lambda x: x['borrow_date'], reverse=True)
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Ausleihen: {e}")

    new_booking_requests = []
    total_pending_bookings = 0
    if 'buchungen' in enabled_types and is_module_enabled('module_booking') and not getattr(user, 'is_guest', False):
        try:
            new_booking_requests = BookingRequest.query.filter_by(
                status='pending'
            ).order_by(BookingRequest.created_at.desc()).limit(3).all()
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
                found = Contact.query.filter(Contact.id.in_(contact_ids)).all()
                by_id = {c.id: c for c in found}
                contacts = [by_id[i] for i in contact_ids if i in by_id]
            payload[wid] = {'contacts': contacts}
        elif wtype == 'nachrichten':
            payload[wid] = {'messages': unread_messages}
        elif wtype == 'emails':
            payload[wid] = {'emails': recent_emails}
        elif wtype == 'dateien':
            payload[wid] = {'files': recent_files}
        elif wtype == 'passwoerter':
            payload[wid] = {'credentials': favorite_credentials}
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
    return payload


def _parse_widgets_from_form():
    """Parst Widget-Instanzen aus dem Edit-Formular (widgets_json oder Felder)."""
    raw = request.form.get('widgets_json')
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return User.normalize_dashboard_config({'widgets': data})['widgets']
        except Exception:
            pass

    widgets = []
    ids = request.form.getlist('widget_id')
    types = request.form.getlist('widget_type')
    for i, wid in enumerate(ids):
        wtype = types[i] if i < len(types) else None
        if not wtype:
            continue
        entry = {'id': wid or User._new_widget_instance_id(), 'type': wtype}
        if wtype == 'termine':
            entry['calendar_ids'] = [
                int(x) for x in request.form.getlist(f'calendar_ids_{wid}')
                if str(x).isdigit()
            ]
        elif wtype == 'kontakte':
            entry['contact_ids'] = [
                int(x) for x in request.form.getlist(f'contact_ids_{wid}')
                if str(x).isdigit()
            ][:3]
        widgets.append(entry)
    return widgets


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
        # Gäste sehen keine Widgets im Template ohnehin — Config bleibt gefiltert
        widgets = []

    visible_widgets = []
    for w in widgets:
        module = WIDGET_MODULE_MAP.get(w['type'])
        if module and not is_module_enabled(module):
            continue
        visible_widgets.append(w)

    widget_data = _load_widget_payload(current_user, visible_widgets) if not getattr(current_user, 'is_guest', False) else {}

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

    return render_template(
        'dashboard/index.html',
        dashboard_widgets=visible_widgets,
        widget_data=widget_data,
        dashboard_config=config,
        update_info=update_info,
        guest_has_chat_access=guest_has_chat_access,
        guest_has_file_access=guest_has_file_access,
        guest_accessible_modules=guest_accessible_modules,
        greeting_key=greeting_key,
        whats_new_version=WHATS_NEW_VERSION,
        show_whats_new=getattr(current_user, 'whats_new_seen_version', None) != WHATS_NEW_VERSION,
    )


@dashboard_bp.route('/api/dashboard/whats-new/seen', methods=['POST'])
@login_required
def api_whats_new_seen():
    """Markiert What's New für die aktuelle Release-Version als gesehen."""
    current_user.whats_new_seen_version = WHATS_NEW_VERSION
    db.session.commit()
    return jsonify({'success': True, 'version': WHATS_NEW_VERSION})


@dashboard_bp.route('/dashboard/edit', methods=['GET', 'POST'])
@login_required
def edit():
    """Dashboard-Bearbeitungsseite."""
    if getattr(current_user, 'is_guest', False):
        flash(translate('dashboard.flash.guests_cannot_edit'), 'danger')
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        config = current_user.get_dashboard_config()
        widgets = _parse_widgets_from_form()

        quick_access_links = []
        for link_key in AVAILABLE_LINK_KEYS:
            if request.form.get(f'link_{link_key}') == 'on':
                quick_access_links.append(link_key)

        config['widgets'] = widgets
        config['quick_access_links'] = quick_access_links
        current_user.set_dashboard_config(config)

        flash(translate('dashboard.flash.saved'), 'success')
        return redirect(url_for('dashboard.index'))

    config = current_user.get_dashboard_config()
    available_calendars = []
    if is_module_enabled('module_calendar'):
        available_calendars = _flatten_sidebar_calendars(current_user)

    selected_contact_ids = []
    for w in config.get('widgets') or []:
        if w.get('type') == 'kontakte':
            selected_contact_ids.extend(w.get('contact_ids') or [])
    selected_contacts = []
    if selected_contact_ids:
        found = Contact.query.filter(Contact.id.in_(selected_contact_ids)).all()
        by_id = {c.id: c for c in found}
        selected_contacts = list(by_id.values())

    return render_template(
        'dashboard/edit.html',
        dashboard_config=config,
        available_calendars=available_calendars,
        selected_contacts=selected_contacts,
        simple_widget_types=SIMPLE_WIDGET_TYPES,
        calendar_multi_enabled=is_calendar_multi_enabled(),
    )


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
        existing['widgets'] = data.get('widgets') or []
    elif 'enabled_widgets' in data:
        # Legacy: remove by type or keep types list
        types = data.get('enabled_widgets') or []
        existing['widgets'] = [
            {'id': User._new_widget_instance_id(), 'type': t} for t in types
        ]
    if 'remove_widget_id' in data:
        rid = data.get('remove_widget_id')
        existing['widgets'] = [w for w in existing.get('widgets', []) if w.get('id') != rid]
    if 'quick_access_links' in data:
        existing['quick_access_links'] = data.get('quick_access_links') or []
    if 'mobile_nav_slots' in data and isinstance(data.get('mobile_nav_slots'), dict):
        existing['mobile_nav_slots'] = data['mobile_nav_slots']

    current_user.set_dashboard_config(existing)
    return jsonify({'success': True, 'config': current_user.get_dashboard_config()})


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
