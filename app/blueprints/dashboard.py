from flask import Blueprint, render_template, redirect, url_for, session, request, flash, jsonify
from flask_login import login_required, current_user
from app.models.calendar import CalendarEvent, EventParticipant
from app.models.chat import ChatMessage, ChatMember
from app.models.email import EmailMessage, EmailPermission
from app.models.file import File
from app.models.canvas import Canvas
from app.models.wiki import WikiPage, WikiFavorite
from app.models.inventory import BorrowTransaction
from app.models.booking import BookingRequest
from app import db
from app.utils.common import is_module_enabled, check_for_updates
from datetime import datetime, date
from sqlalchemy import and_

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/dashboard')
@login_required
def index():
    """Main dashboard view."""
    
    # Sicherstelle, dass der aktuelle Benutzer E-Mail-Berechtigungen hat
    if current_user.is_admin:
        current_user.ensure_email_permissions()
    
    # Lade Dashboard-Konfiguration
    config = current_user.get_dashboard_config()
    enabled_widgets = config.get('enabled_widgets', [])
    
    # Widget-Daten nur laden, wenn Widget aktiviert ist UND Modul aktiviert ist
    upcoming_events = []
    if 'termine' in enabled_widgets and is_module_enabled('module_calendar'):
        upcoming_events = CalendarEvent.query.filter(
            CalendarEvent.start_time >= datetime.utcnow()
        ).order_by(CalendarEvent.start_time).limit(3).all()
    
    unread_messages = []
    if 'nachrichten' in enabled_widgets and is_module_enabled('module_chat'):
        user_chats = ChatMember.query.filter_by(user_id=current_user.id).all()
        for membership in user_chats:
            messages = ChatMessage.query.filter(
                and_(
                    ChatMessage.chat_id == membership.chat_id,
                    ChatMessage.created_at > membership.last_read_at,
                    ChatMessage.sender_id != current_user.id,
                    ChatMessage.is_deleted == False
                )
            ).order_by(ChatMessage.created_at.desc()).limit(5).all()
            unread_messages.extend(messages)
        # Sort by newest first and limit to 5
        unread_messages = sorted(unread_messages, key=lambda x: x.created_at, reverse=True)[:5]
    
    recent_emails = []
    if 'emails' in enabled_widgets and is_module_enabled('module_email'):
        email_perm = EmailPermission.query.filter_by(user_id=current_user.id).first()
        if email_perm and email_perm.can_read:
            recent_emails = EmailMessage.query.filter_by(
                is_sent=False,
                folder='INBOX'
            ).order_by(EmailMessage.received_at.desc()).limit(5).all()
    
    recent_files = []
    if 'dateien' in enabled_widgets and is_module_enabled('module_files'):
        recent_files = File.query.filter_by(
            uploaded_by=current_user.id
        ).order_by(File.updated_at.desc()).limit(3).all()
    
    recent_canvases = []
    if 'canvas' in enabled_widgets and is_module_enabled('module_canvas'):
        recent_canvases = Canvas.query.filter_by(
            created_by=current_user.id
        ).order_by(Canvas.updated_at.desc()).limit(3).all()
    
    # Neue Wikieinträge Widget
    recent_wiki_pages = []
    if 'neue_wikieintraege' in enabled_widgets and is_module_enabled('module_wiki'):
        recent_wiki_pages = WikiPage.query.order_by(
            WikiPage.updated_at.desc()
        ).limit(3).all()
    
    # Meine Wikis Widget (Favoriten)
    my_wiki_favorites = []
    if 'meine_wikis' in enabled_widgets and is_module_enabled('module_wiki'):
        favorites = WikiFavorite.query.filter_by(
            user_id=current_user.id
        ).order_by(WikiFavorite.created_at.desc()).limit(5).all()
        my_wiki_favorites = [fav.wiki_page for fav in favorites]
    
    # Meine Ausleihen Widget
    my_borrow_groups = []
    if 'meine_ausleihen' in enabled_widgets and is_module_enabled('module_inventory'):
        borrows = BorrowTransaction.query.filter_by(
            borrower_id=current_user.id,
            status='active'
        ).order_by(BorrowTransaction.borrow_date.desc()).all()
        
        # Gruppiere nach borrow_group_id (oder transaction_number für Einzelausleihen)
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
            
            # Aktualisiere erwartetes Rückgabedatum (spätestes Datum)
            if b.expected_return_date > grouped[group_key]['expected_return_date']:
                grouped[group_key]['expected_return_date'] = b.expected_return_date
            
            # Prüfe ob überfällig
            if b.is_overdue:
                grouped[group_key]['is_overdue'] = True
        
        # Konvertiere zu Liste und sortiere nach Ausleihdatum (neueste zuerst)
        my_borrow_groups = sorted(grouped.values(), key=lambda x: x['borrow_date'], reverse=True)
    
    # Buchungen Widget
    new_booking_requests = []
    total_pending_bookings = 0
    if 'buchungen' in enabled_widgets and is_module_enabled('module_booking'):
        new_booking_requests = BookingRequest.query.filter_by(
            status='pending'
        ).order_by(BookingRequest.created_at.desc()).limit(3).all()
        
        # Gesamtanzahl für Indikator
        total_pending_bookings = BookingRequest.query.filter_by(
            status='pending'
        ).count()
    
    # Prüfe ob Setup gerade abgeschlossen wurde
    setup_completed = session.pop('setup_completed', False)
    
    # Prüfe auf Updates (nur für Administratoren)
    update_info = None
    if current_user.is_admin and current_user.show_update_notifications:
        update_info = check_for_updates()
    
    return render_template(
        'dashboard/index.html',
        upcoming_events=upcoming_events,
        unread_messages=unread_messages,
        recent_emails=recent_emails,
        recent_files=recent_files,
        recent_canvases=recent_canvases,
        recent_wiki_pages=recent_wiki_pages,
        my_wiki_favorites=my_wiki_favorites,
        my_borrow_groups=my_borrow_groups,
        new_booking_requests=new_booking_requests,
        total_pending_bookings=total_pending_bookings,
        dashboard_config=config,
        setup_completed=setup_completed,
        update_info=update_info
    )


@dashboard_bp.route('/dashboard/edit', methods=['GET', 'POST'])
@login_required
def edit():
    """Dashboard-Bearbeitungsseite."""
    if request.method == 'POST':
        # Lade aktuelle Konfiguration
        config = current_user.get_dashboard_config()
        
        # Widgets aus Formular
        enabled_widgets = []
        available_widgets = ['termine', 'nachrichten', 'emails', 'dateien', 'canvas', 'neue_wikieintraege', 'meine_wikis', 'meine_ausleihen', 'buchungen']
        for widget in available_widgets:
            if request.form.get(f'widget_{widget}') == 'on':
                enabled_widgets.append(widget)
        
        # Schnellzugriff-Links aus Formular
        quick_access_links = []
        available_links = {
            'files': 'files',
            'credentials': 'credentials',
            'manuals': 'manuals',
            'canvas': 'canvas',
            'chat': 'chat',
            'calendar': 'calendar',
            'email': 'email',
            'inventory': 'inventory',
            'wiki': 'wiki',
            'booking': 'booking',
            'music': 'music'
        }
        for link_key, link_value in available_links.items():
            if request.form.get(f'link_{link_key}') == 'on':
                quick_access_links.append(link_value)
        
        # Speichere Konfiguration
        config['enabled_widgets'] = enabled_widgets
        config['quick_access_links'] = quick_access_links
        current_user.set_dashboard_config(config)
        
        flash('Dashboard-Konfiguration erfolgreich gespeichert!', 'success')
        return redirect(url_for('dashboard.index'))
    
    # GET: Zeige Bearbeitungsseite
    config = current_user.get_dashboard_config()
    return render_template('dashboard/edit.html', dashboard_config=config)


@dashboard_bp.route('/api/dashboard/config', methods=['GET', 'POST'])
@login_required
def api_config():
    """API-Endpunkt für Dashboard-Konfiguration."""
    if request.method == 'GET':
        config = current_user.get_dashboard_config()
        return jsonify(config)
    
    elif request.method == 'POST':
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Keine Daten übermittelt.'}), 400
        
        config = {
            'enabled_widgets': data.get('enabled_widgets', []),
            'quick_access_links': data.get('quick_access_links', [])
        }
        current_user.set_dashboard_config(config)
        return jsonify({'success': True, 'config': config})


@dashboard_bp.route('/api/dashboard/update-banner', methods=['POST'])
@login_required
def api_update_banner():
    """API-Endpunkt für Update-Banner-Aktionen."""
    if not current_user.is_admin:
        return jsonify({'error': 'Nur Administratoren haben Zugriff.'}), 403
    
    data = request.get_json()
    action = data.get('action')
    
    if action == 'dismiss':
        # Banner schließen (nur für diese Session)
        return jsonify({'success': True, 'message': 'Banner geschlossen.'})
    
    elif action == 'disable':
        # Update-Benachrichtigungen deaktivieren
        current_user.show_update_notifications = False
        db.session.commit()
        return jsonify({'success': True, 'message': 'Update-Benachrichtigungen deaktiviert.'})
    
    return jsonify({'error': 'Ungültige Aktion.'}), 400


