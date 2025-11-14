"""
Backup- und Restore-Funktionalität für PrismaTeams
"""
import json
import os
import shutil
import tempfile
from datetime import datetime
from typing import List, Dict, Set, Optional
from flask import current_app
from app import db
from app.models import (
    User, Chat, ChatMessage, ChatMember,
    File, FileVersion, Folder,
    CalendarEvent, EventParticipant,
    EmailMessage, EmailPermission, EmailAttachment,
    Credential, SystemSettings, WhitelistEntry,
    NotificationSettings, WikiPage, WikiPageVersion, WikiCategory, WikiTag,
    Comment, CommentMention,
    Product, BorrowTransaction, ProductFolder, ProductSet, ProductSetItem,
    ProductDocument, SavedFilter, ProductFavorite, Inventory, InventoryItem
)
from app.blueprints.credentials import get_encryption_key
from app.utils.lengths import normalize_length_input, parse_length_to_meters, format_length_from_meters


BACKUP_VERSION = "1.0"
SUPPORTED_CATEGORIES = {
    'settings': 'Einstellungen',
    'users': 'Benutzer',
    'emails': 'E-Mails',
    'chats': 'Chats',
    'appointments': 'Termine',
    'credentials': 'Zugangsdaten',
    'files': 'Dateien',
    'wiki': 'Wiki',
    'comments': 'Kommentare',
    'inventory': 'Inventar'
}


def export_backup(categories: List[str], output_path: str) -> Dict:
    """
    Erstellt ein Backup der ausgewählten Kategorien.
    
    Args:
        categories: Liste der zu exportierenden Kategorien
        output_path: Pfad zur Ausgabedatei (.prismateams)
    
    Returns:
        Dict mit Metadaten über das Backup
    """
    backup_data = {
        'version': BACKUP_VERSION,
        'created_at': datetime.utcnow().isoformat(),
        'categories': categories,
        'data': {}
    }
    
    # Einstellungen exportieren
    if 'settings' in categories or 'all' in categories:
        backup_data['data']['settings'] = export_settings()
        backup_data['data']['whitelist'] = export_whitelist()
    
    # Benutzer exportieren
    if 'users' in categories or 'all' in categories:
        backup_data['data']['users'] = export_users()
        backup_data['data']['notification_settings'] = export_notification_settings()
    
    # E-Mails exportieren
    if 'emails' in categories or 'all' in categories:
        backup_data['data']['emails'] = export_emails()
        backup_data['data']['email_permissions'] = export_email_permissions()
        backup_data['data']['email_attachments'] = export_email_attachments()
    
    # Chats exportieren
    if 'chats' in categories or 'all' in categories:
        backup_data['data']['chats'] = export_chats()
        backup_data['data']['chat_messages'] = export_chat_messages()
        backup_data['data']['chat_members'] = export_chat_members()
    
    # Termine exportieren
    if 'appointments' in categories or 'all' in categories:
        backup_data['data']['calendar_events'] = export_calendar_events()
        backup_data['data']['event_participants'] = export_event_participants()
    
    # Zugangsdaten exportieren (entschlüsselt)
    if 'credentials' in categories or 'all' in categories:
        backup_data['data']['credentials'] = export_credentials()
    
    # Dateien exportieren
    if 'files' in categories or 'all' in categories:
        backup_data['data']['folders'] = export_folders()
        backup_data['data']['files'] = export_files()
        backup_data['data']['file_versions'] = export_file_versions()
    
    # Wiki exportieren
    if 'wiki' in categories or 'all' in categories:
        backup_data['data']['wiki_categories'] = export_wiki_categories()
        backup_data['data']['wiki_tags'] = export_wiki_tags()
        backup_data['data']['wiki_pages'] = export_wiki_pages()
        backup_data['data']['wiki_page_versions'] = export_wiki_page_versions()
    
    # Kommentare exportieren
    if 'comments' in categories or 'all' in categories:
        backup_data['data']['comments'] = export_comments()
        backup_data['data']['comment_mentions'] = export_comment_mentions()
    
    # Inventar exportieren
    if 'inventory' in categories or 'all' in categories:
        backup_data['data']['product_folders'] = export_product_folders()
        backup_data['data']['products'] = export_products()
        backup_data['data']['borrow_transactions'] = export_borrow_transactions()
        backup_data['data']['product_sets'] = export_product_sets()
        backup_data['data']['product_set_items'] = export_product_set_items()
        backup_data['data']['product_documents'] = export_product_documents()
        backup_data['data']['saved_filters'] = export_saved_filters()
        backup_data['data']['product_favorites'] = export_product_favorites()
        backup_data['data']['inventories'] = export_inventories()
        backup_data['data']['inventory_items'] = export_inventory_items()
    
    # Backup-Datei schreiben
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(backup_data, f, indent=2, ensure_ascii=False, default=str)
    
    return {
        'success': True,
        'file_path': output_path,
        'categories': categories,
        'created_at': backup_data['created_at']
    }


def export_settings() -> List[Dict]:
    """Exportiert System-Einstellungen."""
    settings = SystemSettings.query.all()
    return [{
        'key': s.key,
        'value': s.value,
        'description': s.description,
        'updated_at': s.updated_at.isoformat() if s.updated_at else None
    } for s in settings]


def export_whitelist() -> List[Dict]:
    """Exportiert Whitelist-Einträge."""
    entries = WhitelistEntry.query.all()
    return [{
        'entry': e.entry,
        'entry_type': e.entry_type,
        'description': e.description,
        'is_active': e.is_active,
        'created_at': e.created_at.isoformat() if e.created_at else None
    } for e in entries]


def export_users() -> List[Dict]:
    """Exportiert Benutzer (inkl. Passwort-Hashes)."""
    users = User.query.all()
    return [{
        'email': u.email,
        'password_hash': u.password_hash,  # Passwort-Hash wird exportiert
        'first_name': u.first_name,
        'last_name': u.last_name,
        'phone': u.phone,
        'is_active': u.is_active,
        'is_admin': u.is_admin,
        'is_email_confirmed': u.is_email_confirmed,
        'profile_picture': u.profile_picture,
        'accent_color': u.accent_color,
        'accent_gradient': u.accent_gradient,
        'dark_mode': u.dark_mode,
        'notifications_enabled': u.notifications_enabled,
        'chat_notifications': u.chat_notifications,
        'email_notifications': u.email_notifications,
        'can_borrow': u.can_borrow,
        'created_at': u.created_at.isoformat() if u.created_at else None,
        'last_login': u.last_login.isoformat() if u.last_login else None
    } for u in users]


def export_notification_settings() -> List[Dict]:
    """Exportiert Notification-Einstellungen."""
    settings = NotificationSettings.query.all()
    return [{
        'user_email': User.query.get(s.user_id).email if User.query.get(s.user_id) else None,
        'chat_notifications_enabled': s.chat_notifications_enabled,
        'file_notifications_enabled': s.file_notifications_enabled,
        'file_new_notifications': s.file_new_notifications,
        'file_modified_notifications': s.file_modified_notifications,
        'email_notifications_enabled': s.email_notifications_enabled,
        'calendar_notifications_enabled': s.calendar_notifications_enabled,
        'calendar_all_events': s.calendar_all_events,
        'calendar_participating_only': s.calendar_participating_only,
        'calendar_not_participating': s.calendar_not_participating,
        'calendar_no_response': s.calendar_no_response,
        'reminder_times': s.reminder_times
    } for s in settings]


def export_emails() -> List[Dict]:
    """Exportiert E-Mails."""
    emails = EmailMessage.query.all()
    return [{
        'uid': e.uid,
        'message_id': e.message_id,
        'subject': e.subject,
        'sender': e.sender,
        'recipients': e.recipients,
        'cc': e.cc,
        'bcc': e.bcc,
        'body_text': e.body_text,
        'body_html': e.body_html,
        'is_read': e.is_read,
        'is_sent': e.is_sent,
        'has_attachments': e.has_attachments,
        'folder': e.folder,
        'sent_by_user_email': User.query.get(e.sent_by_user_id).email if e.sent_by_user_id and User.query.get(e.sent_by_user_id) else None,
        'received_at': e.received_at.isoformat() if e.received_at else None,
        'sent_at': e.sent_at.isoformat() if e.sent_at else None,
        'created_at': e.created_at.isoformat() if e.created_at else None
    } for e in emails]


def export_email_permissions() -> List[Dict]:
    """Exportiert E-Mail-Berechtigungen."""
    permissions = EmailPermission.query.all()
    return [{
        'user_email': User.query.get(p.user_id).email if User.query.get(p.user_id) else None,
        'can_read': p.can_read,
        'can_send': p.can_send
    } for p in permissions]


def export_email_attachments() -> List[Dict]:
    """Exportiert E-Mail-Anhänge."""
    attachments = EmailAttachment.query.all()
    result = []
    for att in attachments:
        att_data = {
            'email_message_id': att.email.message_id if att.email else None,
            'filename': att.filename,
            'content_type': att.content_type,
            'size': att.size,
            'is_inline': att.is_inline,
            'created_at': att.created_at.isoformat() if att.created_at else None
        }
        # Dateiinhalt nur wenn vorhanden
        if att.file_path and os.path.exists(att.file_path):
            try:
                with open(att.file_path, 'rb') as f:
                    import base64
                    att_data['content_base64'] = base64.b64encode(f.read()).decode('utf-8')
            except Exception:
                pass
        elif att.content:
            import base64
            att_data['content_base64'] = base64.b64encode(att.content).decode('utf-8')
        result.append(att_data)
    return result


def export_chats() -> List[Dict]:
    """Exportiert Chats."""
    chats = Chat.query.all()
    return [{
        'name': c.name,
        'is_main_chat': c.is_main_chat,
        'is_direct_message': c.is_direct_message,
        'created_by_email': User.query.get(c.created_by).email if c.created_by and User.query.get(c.created_by) else None,
        'created_at': c.created_at.isoformat() if c.created_at else None,
        'updated_at': c.updated_at.isoformat() if c.updated_at else None
    } for c in chats]


def export_chat_messages() -> List[Dict]:
    """Exportiert Chat-Nachrichten."""
    messages = ChatMessage.query.all()
    return [{
        'chat_name': Chat.query.get(m.chat_id).name if Chat.query.get(m.chat_id) else None,
        'sender_email': User.query.get(m.sender_id).email if User.query.get(m.sender_id) else None,
        'content': m.content,
        'message_type': m.message_type,
        'media_url': m.media_url,
        'created_at': m.created_at.isoformat() if m.created_at else None,
        'edited_at': m.edited_at.isoformat() if m.edited_at else None,
        'is_deleted': m.is_deleted
    } for m in messages]


def export_chat_members() -> List[Dict]:
    """Exportiert Chat-Mitglieder."""
    members = ChatMember.query.all()
    return [{
        'chat_name': Chat.query.get(m.chat_id).name if Chat.query.get(m.chat_id) else None,
        'user_email': User.query.get(m.user_id).email if User.query.get(m.user_id) else None,
        'joined_at': m.joined_at.isoformat() if m.joined_at else None,
        'last_read_at': m.last_read_at.isoformat() if m.last_read_at else None
    } for m in members]


def export_calendar_events() -> List[Dict]:
    """Exportiert Kalender-Termine."""
    events = CalendarEvent.query.all()
    return [{
        'title': e.title,
        'description': e.description,
        'start_time': e.start_time.isoformat() if e.start_time else None,
        'end_time': e.end_time.isoformat() if e.end_time else None,
        'location': e.location,
        'created_by_email': User.query.get(e.created_by).email if User.query.get(e.created_by) else None,
        'created_at': e.created_at.isoformat() if e.created_at else None,
        'updated_at': e.updated_at.isoformat() if e.updated_at else None
    } for e in events]


def export_event_participants() -> List[Dict]:
    """Exportiert Event-Teilnehmer."""
    participants = EventParticipant.query.all()
    return [{
        'event_title': CalendarEvent.query.get(p.event_id).title if CalendarEvent.query.get(p.event_id) else None,
        'user_email': User.query.get(p.user_id).email if User.query.get(p.user_id) else None,
        'status': p.status,
        'responded_at': p.responded_at.isoformat() if p.responded_at else None
    } for p in participants]


def export_credentials() -> List[Dict]:
    """Exportiert Zugangsdaten (entschlüsselt)."""
    credentials = Credential.query.all()
    key = get_encryption_key()
    result = []
    for cred in credentials:
        try:
            decrypted_password = cred.get_password(key)
            result.append({
                'website_url': cred.website_url,
                'website_name': cred.website_name,
                'username': cred.username,
                'password': decrypted_password,  # Entschlüsselt
                'notes': cred.notes,
                'favicon_url': cred.favicon_url,
                'created_by_email': User.query.get(cred.created_by).email if User.query.get(cred.created_by) else None,
                'created_at': cred.created_at.isoformat() if cred.created_at else None,
                'updated_at': cred.updated_at.isoformat() if cred.updated_at else None
            })
        except Exception as e:
            # Wenn Entschlüsselung fehlschlägt, überspringen
            current_app.logger.error(f"Fehler beim Entschlüsseln von Credential {cred.id}: {str(e)}")
            continue
    return result


def export_folders() -> List[Dict]:
    """Exportiert Ordner."""
    folders = Folder.query.all()
    return [{
        'name': f.name,
        'parent_name': Folder.query.get(f.parent_id).name if f.parent_id and Folder.query.get(f.parent_id) else None,
        'created_by_email': User.query.get(f.created_by).email if User.query.get(f.created_by) else None,
        'is_dropbox': f.is_dropbox,
        'share_enabled': f.share_enabled,
        'share_name': f.share_name,
        'share_expires_at': f.share_expires_at.isoformat() if f.share_expires_at else None,
        'created_at': f.created_at.isoformat() if f.created_at else None,
        'updated_at': f.updated_at.isoformat() if f.updated_at else None
    } for f in folders]


def export_files() -> List[Dict]:
    """Exportiert Dateien."""
    files = File.query.all()
    result = []
    for file in files:
        file_data = {
            'name': file.name,
            'original_name': file.original_name,
            'folder_name': Folder.query.get(file.folder_id).name if file.folder_id and Folder.query.get(file.folder_id) else None,
            'uploaded_by_email': User.query.get(file.uploaded_by).email if User.query.get(file.uploaded_by) else None,
            'file_size': file.file_size,
            'mime_type': file.mime_type,
            'version_number': file.version_number,
            'is_current': file.is_current,
            'share_enabled': file.share_enabled,
            'share_name': file.share_name,
            'share_expires_at': file.share_expires_at.isoformat() if file.share_expires_at else None,
            'created_at': file.created_at.isoformat() if file.created_at else None,
            'updated_at': file.updated_at.isoformat() if file.updated_at else None
        }
        # Dateiinhalt hinzufügen wenn vorhanden
        if file.file_path and os.path.exists(file.file_path):
            try:
                with open(file.file_path, 'rb') as f:
                    import base64
                    file_data['content_base64'] = base64.b64encode(f.read()).decode('utf-8')
                    file_data['file_path'] = file.file_path
            except Exception as e:
                current_app.logger.error(f"Fehler beim Lesen von Datei {file.file_path}: {str(e)}")
        result.append(file_data)
    return result


def export_file_versions() -> List[Dict]:
    """Exportiert Datei-Versionen."""
    versions = FileVersion.query.all()
    result = []
    for v in versions:
        version_data = {
            'file_name': File.query.get(v.file_id).name if File.query.get(v.file_id) else None,
            'version_number': v.version_number,
            'file_size': v.file_size,
            'uploaded_by_email': User.query.get(v.uploaded_by).email if User.query.get(v.uploaded_by) else None,
            'created_at': v.created_at.isoformat() if v.created_at else None
        }
        # Dateiinhalt hinzufügen wenn vorhanden
        if v.file_path and os.path.exists(v.file_path):
            try:
                with open(v.file_path, 'rb') as f:
                    import base64
                    version_data['content_base64'] = base64.b64encode(f.read()).decode('utf-8')
                    version_data['file_path'] = v.file_path
            except Exception as e:
                current_app.logger.error(f"Fehler beim Lesen von Dateiversion {v.file_path}: {str(e)}")
        result.append(version_data)
    return result


def export_wiki_categories() -> List[Dict]:
    """Exportiert Wiki-Kategorien."""
    categories = WikiCategory.query.all()
    return [{
        'name': c.name,
        'description': c.description,
        'color': c.color,
        'created_at': c.created_at.isoformat() if c.created_at else None
    } for c in categories]


def export_wiki_tags() -> List[Dict]:
    """Exportiert Wiki-Tags."""
    tags = WikiTag.query.all()
    return [{
        'name': t.name,
        'created_at': t.created_at.isoformat() if t.created_at else None
    } for t in tags]


def export_wiki_pages() -> List[Dict]:
    """Exportiert Wiki-Seiten."""
    pages = WikiPage.query.all()
    result = []
    for p in pages:
        page_data = {
            'title': p.title,
            'slug': p.slug,
            'content': p.content,
            'category_name': p.category.name if p.category else None,
            'created_by_email': User.query.get(p.created_by).email if User.query.get(p.created_by) else None,
            'version_number': p.version_number,
            'tags': [tag.name for tag in p.tags],
            'created_at': p.created_at.isoformat() if p.created_at else None,
            'updated_at': p.updated_at.isoformat() if p.updated_at else None
        }
        # Dateiinhalt hinzufügen wenn vorhanden
        if p.file_path and os.path.exists(p.file_path):
            try:
                with open(p.file_path, 'r', encoding='utf-8') as f:
                    page_data['file_content'] = f.read()
                    page_data['file_path'] = p.file_path
            except Exception as e:
                current_app.logger.error(f"Fehler beim Lesen von Wiki-Datei {p.file_path}: {str(e)}")
        result.append(page_data)
    return result


def export_wiki_page_versions() -> List[Dict]:
    """Exportiert Wiki-Seiten-Versionen."""
    versions = WikiPageVersion.query.all()
    result = []
    for v in versions:
        page = WikiPage.query.get(v.wiki_page_id)
        version_data = {
            'page_slug': page.slug if page else None,
            'version_number': v.version_number,
            'content': v.content,
            'created_by_email': User.query.get(v.created_by).email if User.query.get(v.created_by) else None,
            'created_at': v.created_at.isoformat() if v.created_at else None
        }
        # Dateiinhalt hinzufügen wenn vorhanden
        if v.file_path and os.path.exists(v.file_path):
            try:
                with open(v.file_path, 'r', encoding='utf-8') as f:
                    version_data['file_content'] = f.read()
                    version_data['file_path'] = v.file_path
            except Exception as e:
                current_app.logger.error(f"Fehler beim Lesen von Wiki-Versionsdatei {v.file_path}: {str(e)}")
        result.append(version_data)
    return result


def export_comments() -> List[Dict]:
    """Exportiert Kommentare."""
    comments = Comment.query.filter_by(is_deleted=False).all()
    result = []
    for idx, c in enumerate(comments):
        # Finde parent-Kommentar-ID für Referenzierung
        parent_content_ref = None
        if c.parent_id:
            parent_comment = Comment.query.get(c.parent_id)
            if parent_comment:
                # Erstelle eine Referenz basierend auf content_type, content_id und Index
                # Verwende Index für eindeutige Referenzierung
                parent_idx = comments.index(parent_comment) if parent_comment in comments else None
                if parent_idx is not None:
                    parent_content_ref = f"{parent_comment.content_type}:{parent_comment.content_id}:{parent_idx}"
        
        comment_data = {
            'old_id': idx,  # Index für Referenzierung beim Import
            'content_type': c.content_type,
            'content_id': c.content_id,
            'content': c.content,
            'author_email': User.query.get(c.author_id).email if User.query.get(c.author_id) else None,
            'parent_content_ref': parent_content_ref,  # Referenz zum Parent-Kommentar
            'created_at': c.created_at.isoformat() if c.created_at else None,
            'updated_at': c.updated_at.isoformat() if c.updated_at else None
        }
        
        # Füge Referenz zum Content-Objekt hinzu für bessere Zuordnung beim Import
        if c.content_type == 'file':
            file_obj = File.query.get(c.content_id)
            if file_obj:
                comment_data['content_reference'] = f"file:{file_obj.name}"
        elif c.content_type == 'wiki':
            wiki_obj = WikiPage.query.get(c.content_id)
            if wiki_obj:
                comment_data['content_reference'] = f"wiki:{wiki_obj.slug}"
        elif c.content_type == 'canvas':
            from app.models.canvas import Canvas
            canvas_obj = Canvas.query.get(c.content_id)
            if canvas_obj:
                comment_data['content_reference'] = f"canvas:{canvas_obj.id}"
        
        result.append(comment_data)
    return result


def export_comment_mentions() -> List[Dict]:
    """Exportiert Kommentar-Mentions."""
    mentions = CommentMention.query.all()
    # Hole alle Kommentare für Index-Referenzierung
    all_comments = Comment.query.filter_by(is_deleted=False).all()
    comment_to_idx = {c.id: idx for idx, c in enumerate(all_comments)}
    
    result = []
    for m in mentions:
        comment = Comment.query.get(m.comment_id)
        if not comment or comment.is_deleted:
            continue
        
        # Verwende Index für Referenzierung
        comment_idx = comment_to_idx.get(comment.id)
        if comment_idx is None:
            continue
        
        mention_data = {
            'comment_content_ref': f"{comment.content_type}:{comment.content_id}:{comment_idx}",
            'user_email': User.query.get(m.user_id).email if User.query.get(m.user_id) else None,
            'notification_sent': m.notification_sent,
            'created_at': m.created_at.isoformat() if m.created_at else None,
            'notification_sent_at': m.notification_sent_at.isoformat() if m.notification_sent_at else None
        }
        result.append(mention_data)
    return result


def export_product_folders() -> List[Dict]:
    """Exportiert Produkt-Ordner."""
    folders = ProductFolder.query.all()
    return [{
        'name': f.name,
        'description': f.description,
        'color': f.color,
        'created_by_email': User.query.get(f.created_by).email if User.query.get(f.created_by) else None,
        'created_at': f.created_at.isoformat() if f.created_at else None,
        'updated_at': f.updated_at.isoformat() if f.updated_at else None
    } for f in folders]


def export_products() -> List[Dict]:
    """Exportiert Produkte."""
    products = Product.query.all()
    return [{
        'name': p.name,
        'description': p.description,
        'category': p.category,
        'serial_number': p.serial_number,
        'condition': p.condition,
        'location': p.location,
        'length': p.length,
        'length_meters': parse_length_to_meters(p.length),
        'purchase_date': p.purchase_date.isoformat() if p.purchase_date else None,
        'status': p.status,
        'image_path': p.image_path,
        'qr_code_data': p.qr_code_data,
        'folder_name': ProductFolder.query.get(p.folder_id).name if p.folder_id and ProductFolder.query.get(p.folder_id) else None,
        'created_by_email': User.query.get(p.created_by).email if User.query.get(p.created_by) else None,
        'created_at': p.created_at.isoformat() if p.created_at else None,
        'updated_at': p.updated_at.isoformat() if p.updated_at else None
    } for p in products]


def export_borrow_transactions() -> List[Dict]:
    """Exportiert Ausleihtransaktionen."""
    transactions = BorrowTransaction.query.all()
    return [{
        'transaction_number': t.transaction_number,
        'borrow_group_id': t.borrow_group_id,
        'product_name': Product.query.get(t.product_id).name if Product.query.get(t.product_id) else None,
        'borrower_email': User.query.get(t.borrower_id).email if User.query.get(t.borrower_id) else None,
        'borrowed_by_email': User.query.get(t.borrowed_by_id).email if User.query.get(t.borrowed_by_id) else None,
        'borrow_date': t.borrow_date.isoformat() if t.borrow_date else None,
        'expected_return_date': t.expected_return_date.isoformat() if t.expected_return_date else None,
        'actual_return_date': t.actual_return_date.isoformat() if t.actual_return_date else None,
        'status': t.status,
        'qr_code_data': t.qr_code_data,
        'created_at': t.created_at.isoformat() if t.created_at else None,
        'updated_at': t.updated_at.isoformat() if t.updated_at else None
    } for t in transactions]


def export_product_sets() -> List[Dict]:
    """Exportiert Produktsets."""
    sets = ProductSet.query.all()
    return [{
        'name': s.name,
        'description': s.description,
        'created_by_email': User.query.get(s.created_by).email if User.query.get(s.created_by) else None,
        'created_at': s.created_at.isoformat() if s.created_at else None,
        'updated_at': s.updated_at.isoformat() if s.updated_at else None
    } for s in sets]


def export_product_set_items() -> List[Dict]:
    """Exportiert Produktset-Items."""
    items = ProductSetItem.query.all()
    return [{
        'set_name': ProductSet.query.get(i.set_id).name if ProductSet.query.get(i.set_id) else None,
        'product_name': Product.query.get(i.product_id).name if Product.query.get(i.product_id) else None,
        'quantity': i.quantity
    } for i in items]


def export_product_documents() -> List[Dict]:
    """Exportiert Produktdokumente."""
    documents = ProductDocument.query.all()
    result = []
    for d in documents:
        doc_data = {
            'product_name': Product.query.get(d.product_id).name if Product.query.get(d.product_id) else None,
            'file_name': d.file_name,
            'file_type': d.file_type,
            'file_size': d.file_size,
            'uploaded_by_email': User.query.get(d.uploaded_by).email if User.query.get(d.uploaded_by) else None,
            'created_at': d.created_at.isoformat() if d.created_at else None
        }
        # Dateiinhalt hinzufügen wenn vorhanden
        if d.file_path and os.path.exists(d.file_path):
            try:
                with open(d.file_path, 'rb') as f:
                    import base64
                    doc_data['content_base64'] = base64.b64encode(f.read()).decode('utf-8')
                    doc_data['file_path'] = d.file_path
            except Exception as e:
                current_app.logger.error(f"Fehler beim Lesen von Produktdokument {d.file_path}: {str(e)}")
        result.append(doc_data)
    return result


def export_saved_filters() -> List[Dict]:
    """Exportiert gespeicherte Filter."""
    filters = SavedFilter.query.all()
    return [{
        'user_email': User.query.get(f.user_id).email if User.query.get(f.user_id) else None,
        'name': f.name,
        'filter_data': f.filter_data,
        'created_at': f.created_at.isoformat() if f.created_at else None
    } for f in filters]


def export_product_favorites() -> List[Dict]:
    """Exportiert Produktfavoriten."""
    favorites = ProductFavorite.query.all()
    return [{
        'user_email': User.query.get(f.user_id).email if User.query.get(f.user_id) else None,
        'product_name': Product.query.get(f.product_id).name if Product.query.get(f.product_id) else None,
        'created_at': f.created_at.isoformat() if f.created_at else None
    } for f in favorites]


def export_inventories() -> List[Dict]:
    """Exportiert Inventuren."""
    inventories = Inventory.query.all()
    return [{
        'name': i.name,
        'description': i.description,
        'status': i.status,
        'started_by_email': User.query.get(i.started_by).email if User.query.get(i.started_by) else None,
        'started_at': i.started_at.isoformat() if i.started_at else None,
        'completed_at': i.completed_at.isoformat() if i.completed_at else None,
        'created_at': i.created_at.isoformat() if i.created_at else None,
        'updated_at': i.updated_at.isoformat() if i.updated_at else None
    } for i in inventories]


def export_inventory_items() -> List[Dict]:
    """Exportiert Inventur-Items."""
    items = InventoryItem.query.all()
    return [{
        'inventory_name': Inventory.query.get(i.inventory_id).name if Inventory.query.get(i.inventory_id) else None,
        'product_name': Product.query.get(i.product_id).name if Product.query.get(i.product_id) else None,
        'checked': i.checked,
        'notes': i.notes,
        'location_changed': i.location_changed,
        'new_location': i.new_location,
        'condition_changed': i.condition_changed,
        'new_condition': i.new_condition,
        'checked_by_email': User.query.get(i.checked_by).email if i.checked_by and User.query.get(i.checked_by) else None,
        'checked_at': i.checked_at.isoformat() if i.checked_at else None,
        'created_at': i.created_at.isoformat() if i.created_at else None,
        'updated_at': i.updated_at.isoformat() if i.updated_at else None
    } for i in items]


def import_backup(file_path: str, categories: List[str]) -> Dict:
    """
    Importiert ein Backup der ausgewählten Kategorien.
    
    Args:
        file_path: Pfad zur Backup-Datei
        categories: Liste der zu importierenden Kategorien
    
    Returns:
        Dict mit Import-Ergebnissen
    """
    # Backup-Datei laden
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)
    except Exception as e:
        return {'success': False, 'error': f'Fehler beim Lesen der Backup-Datei: {str(e)}'}
    
    # Version prüfen
    if backup_data.get('version') != BACKUP_VERSION:
        return {'success': False, 'error': f'Unsupported backup version: {backup_data.get("version")}'}
    
    try:
        # Stelle sicher, dass keine vorherige Transaktion offen ist
        if hasattr(db.session, "in_transaction") and db.session.in_transaction():
            current_app.logger.debug("Offene Transaktion vor Backup-Import gefunden – führe Rollback durch.")
            db.session.rollback()
        
        results = {
            'success': True,
            'imported': [],
            'errors': []
        }
        
        # Einstellungen importieren
        if 'settings' in categories or 'all' in categories:
            if 'settings' in backup_data.get('data', {}):
                import_settings(backup_data['data']['settings'])
                results['imported'].append('settings')
            if 'whitelist' in backup_data.get('data', {}):
                import_whitelist(backup_data['data']['whitelist'])
                results['imported'].append('whitelist')
        
        # Benutzer importieren (muss zuerst sein wegen Foreign Keys)
        if 'users' in categories or 'all' in categories:
            if 'users' in backup_data.get('data', {}):
                user_map = import_users(backup_data['data']['users'])
                results['imported'].append('users')
            else:
                user_map = {}
            
            if 'notification_settings' in backup_data.get('data', {}):
                import_notification_settings(backup_data['data']['notification_settings'], user_map)
                results['imported'].append('notification_settings')
        
        # E-Mails importieren
        if 'emails' in categories or 'all' in categories:
            if 'emails' in backup_data.get('data', {}):
                email_map = import_emails(backup_data['data']['emails'], user_map)
                results['imported'].append('emails')
            else:
                email_map = {}
            
            if 'email_permissions' in backup_data.get('data', {}):
                import_email_permissions(backup_data['data']['email_permissions'], user_map)
                results['imported'].append('email_permissions')
            
            if 'email_attachments' in backup_data.get('data', {}):
                import_email_attachments(backup_data['data']['email_attachments'], email_map)
                results['imported'].append('email_attachments')
        
        # Chats importieren
        if 'chats' in categories or 'all' in categories:
            if 'chats' in backup_data.get('data', {}):
                chat_map = import_chats(backup_data['data']['chats'], user_map)
                results['imported'].append('chats')
            else:
                chat_map = {}
            
            if 'chat_messages' in backup_data.get('data', {}):
                import_chat_messages(backup_data['data']['chat_messages'], chat_map, user_map)
                results['imported'].append('chat_messages')
            
            if 'chat_members' in backup_data.get('data', {}):
                import_chat_members(backup_data['data']['chat_members'], chat_map, user_map)
                results['imported'].append('chat_members')
        
        # Termine importieren
        if 'appointments' in categories or 'all' in categories:
            if 'calendar_events' in backup_data.get('data', {}):
                event_map = import_calendar_events(backup_data['data']['calendar_events'], user_map)
                results['imported'].append('calendar_events')
            else:
                event_map = {}
            
            if 'event_participants' in backup_data.get('data', {}):
                import_event_participants(backup_data['data']['event_participants'], event_map, user_map)
                results['imported'].append('event_participants')
        
        # Zugangsdaten importieren
        if 'credentials' in categories or 'all' in categories:
            if 'credentials' in backup_data.get('data', {}):
                import_credentials(backup_data['data']['credentials'], user_map)
                results['imported'].append('credentials')
        
        # Dateien importieren
        if 'files' in categories or 'all' in categories:
            if 'folders' in backup_data.get('data', {}):
                folder_map = import_folders(backup_data['data']['folders'], user_map)
                results['imported'].append('folders')
            else:
                folder_map = {}
            
            if 'files' in backup_data.get('data', {}):
                import_files(backup_data['data']['files'], folder_map, user_map)
                results['imported'].append('files')
            
            if 'file_versions' in backup_data.get('data', {}):
                import_file_versions(backup_data['data']['file_versions'], user_map)
                results['imported'].append('file_versions')
        
        # Wiki importieren
        if 'wiki' in categories or 'all' in categories:
            if 'wiki_categories' in backup_data.get('data', {}):
                category_map = import_wiki_categories(backup_data['data']['wiki_categories'])
                results['imported'].append('wiki_categories')
            else:
                category_map = {}
            
            if 'wiki_tags' in backup_data.get('data', {}):
                tag_map = import_wiki_tags(backup_data['data']['wiki_tags'])
                results['imported'].append('wiki_tags')
            else:
                tag_map = {}
            
            if 'wiki_pages' in backup_data.get('data', {}):
                page_map = import_wiki_pages(backup_data['data']['wiki_pages'], category_map, tag_map, user_map)
                results['imported'].append('wiki_pages')
            else:
                page_map = {}
            
            if 'wiki_page_versions' in backup_data.get('data', {}):
                import_wiki_page_versions(backup_data['data']['wiki_page_versions'], page_map, user_map)
                results['imported'].append('wiki_page_versions')
        
        # Kommentare importieren
        if 'comments' in categories or 'all' in categories:
            if 'comments' in backup_data.get('data', {}):
                comment_map = import_comments(backup_data['data']['comments'], user_map)
                results['imported'].append('comments')
            else:
                comment_map = {}
            
            if 'comment_mentions' in backup_data.get('data', {}):
                import_comment_mentions(backup_data['data']['comment_mentions'], comment_map, user_map)
                results['imported'].append('comment_mentions')
        
        # Inventar importieren
        if 'inventory' in categories or 'all' in categories:
            if 'product_folders' in backup_data.get('data', {}):
                folder_map = import_product_folders(backup_data['data']['product_folders'], user_map)
                results['imported'].append('product_folders')
            else:
                folder_map = {}
            
            if 'products' in backup_data.get('data', {}):
                product_map = import_products(backup_data['data']['products'], folder_map, user_map)
                results['imported'].append('products')
            else:
                product_map = {}
            
            if 'borrow_transactions' in backup_data.get('data', {}):
                import_borrow_transactions(backup_data['data']['borrow_transactions'], product_map, user_map)
                results['imported'].append('borrow_transactions')
            
            if 'product_sets' in backup_data.get('data', {}):
                set_map = import_product_sets(backup_data['data']['product_sets'], user_map)
                results['imported'].append('product_sets')
            else:
                set_map = {}
            
            if 'product_set_items' in backup_data.get('data', {}):
                import_product_set_items(backup_data['data']['product_set_items'], set_map, product_map)
                results['imported'].append('product_set_items')
            
            if 'product_documents' in backup_data.get('data', {}):
                import_product_documents(backup_data['data']['product_documents'], product_map, user_map)
                results['imported'].append('product_documents')
            
            if 'saved_filters' in backup_data.get('data', {}):
                import_saved_filters(backup_data['data']['saved_filters'], user_map)
                results['imported'].append('saved_filters')
            
            if 'product_favorites' in backup_data.get('data', {}):
                import_product_favorites(backup_data['data']['product_favorites'], product_map, user_map)
                results['imported'].append('product_favorites')
            
            if 'inventories' in backup_data.get('data', {}):
                inventory_map = import_inventories(backup_data['data']['inventories'], user_map)
                results['imported'].append('inventories')
            else:
                inventory_map = {}
            
            if 'inventory_items' in backup_data.get('data', {}):
                import_inventory_items(backup_data['data']['inventory_items'], inventory_map, product_map, user_map)
                results['imported'].append('inventory_items')
        
        db.session.commit()
        return results
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Fehler beim Import: {str(e)}")
        return {'success': False, 'error': f'Fehler beim Import: {str(e)}'}


def import_settings(settings_data: List[Dict]):
    """Importiert System-Einstellungen."""
    for s_data in settings_data:
        existing = SystemSettings.query.filter_by(key=s_data['key']).first()
        if existing:
            existing.value = s_data['value']
            if 'description' in s_data:
                existing.description = s_data['description']
        else:
            setting = SystemSettings(
                key=s_data['key'],
                value=s_data['value'],
                description=s_data.get('description')
            )
            db.session.add(setting)


def import_whitelist(whitelist_data: List[Dict]):
    """Importiert Whitelist-Einträge."""
    for w_data in whitelist_data:
        existing = WhitelistEntry.query.filter_by(
            entry=w_data['entry'],
            entry_type=w_data['entry_type']
        ).first()
        if not existing:
            entry = WhitelistEntry(
                entry=w_data['entry'],
                entry_type=w_data['entry_type'],
                description=w_data.get('description'),
                is_active=w_data.get('is_active', True)
            )
            db.session.add(entry)


def import_users(users_data: List[Dict]) -> Dict[str, int]:
    """
    Importiert Benutzer und gibt ein Mapping von E-Mail zu neuer ID zurück.
    IDs werden neu generiert.
    """
    user_map = {}  # email -> neue_id
    
    for u_data in users_data:
        existing = User.query.filter_by(email=u_data['email']).first()
        if existing:
            # Aktualisiere bestehenden Benutzer
            existing.first_name = u_data['first_name']
            existing.last_name = u_data['last_name']
            existing.phone = u_data.get('phone')
            existing.is_active = u_data.get('is_active', False)
            existing.is_admin = u_data.get('is_admin', False)
            existing.is_email_confirmed = u_data.get('is_email_confirmed', False)
            existing.profile_picture = u_data.get('profile_picture')
            existing.accent_color = u_data.get('accent_color', '#0d6efd')
            existing.accent_gradient = u_data.get('accent_gradient')
            existing.dark_mode = u_data.get('dark_mode', False)
            existing.notifications_enabled = u_data.get('notifications_enabled', True)
            existing.chat_notifications = u_data.get('chat_notifications', True)
            existing.email_notifications = u_data.get('email_notifications', True)
            existing.can_borrow = u_data.get('can_borrow', True)
            # Passwort-Hash aktualisieren falls vorhanden
            if u_data.get('password_hash'):
                existing.password_hash = u_data['password_hash']
            user_map[u_data['email']] = existing.id
        else:
            # Neuer Benutzer (mit Passwort-Hash aus Backup)
            user = User(
                email=u_data['email'],
                password_hash=u_data.get('password_hash'),  # Passwort-Hash wird importiert
                first_name=u_data['first_name'],
                last_name=u_data['last_name'],
                phone=u_data.get('phone'),
                is_active=u_data.get('is_active', False),
                is_admin=u_data.get('is_admin', False),
                is_email_confirmed=u_data.get('is_email_confirmed', False),
                profile_picture=u_data.get('profile_picture'),
                accent_color=u_data.get('accent_color', '#0d6efd'),
                accent_gradient=u_data.get('accent_gradient'),
                dark_mode=u_data.get('dark_mode', False),
                notifications_enabled=u_data.get('notifications_enabled', True),
                chat_notifications=u_data.get('chat_notifications', True),
                email_notifications=u_data.get('email_notifications', True),
                can_borrow=u_data.get('can_borrow', True)
            )
            # Falls kein Passwort-Hash vorhanden, temporäres Passwort setzen
            if not user.password_hash:
                user.set_password('TEMPORARY_PASSWORD_RESET_REQUIRED')
            db.session.add(user)
            db.session.flush()  # Um die ID zu bekommen
            user_map[u_data['email']] = user.id
    
    return user_map


def import_notification_settings(settings_data: List[Dict], user_map: Dict[str, int]):
    """Importiert Notification-Einstellungen."""
    for s_data in settings_data:
        user_email = s_data.get('user_email')
        if not user_email or user_email not in user_map:
            continue
        
        user_id = user_map[user_email]
        existing = NotificationSettings.query.filter_by(user_id=user_id).first()
        if existing:
            existing.chat_notifications_enabled = s_data.get('chat_notifications_enabled', True)
            existing.file_notifications_enabled = s_data.get('file_notifications_enabled', True)
            existing.file_new_notifications = s_data.get('file_new_notifications', True)
            existing.file_modified_notifications = s_data.get('file_modified_notifications', True)
            existing.email_notifications_enabled = s_data.get('email_notifications_enabled', True)
            existing.calendar_notifications_enabled = s_data.get('calendar_notifications_enabled', True)
            existing.calendar_all_events = s_data.get('calendar_all_events', False)
            existing.calendar_participating_only = s_data.get('calendar_participating_only', True)
            existing.calendar_not_participating = s_data.get('calendar_not_participating', False)
            existing.calendar_no_response = s_data.get('calendar_no_response', False)
            existing.reminder_times = s_data.get('reminder_times')
        else:
            setting = NotificationSettings(
                user_id=user_id,
                chat_notifications_enabled=s_data.get('chat_notifications_enabled', True),
                file_notifications_enabled=s_data.get('file_notifications_enabled', True),
                file_new_notifications=s_data.get('file_new_notifications', True),
                file_modified_notifications=s_data.get('file_modified_notifications', True),
                email_notifications_enabled=s_data.get('email_notifications_enabled', True),
                calendar_notifications_enabled=s_data.get('calendar_notifications_enabled', True),
                calendar_all_events=s_data.get('calendar_all_events', False),
                calendar_participating_only=s_data.get('calendar_participating_only', True),
                calendar_not_participating=s_data.get('calendar_not_participating', False),
                calendar_no_response=s_data.get('calendar_no_response', False),
                reminder_times=s_data.get('reminder_times')
            )
            db.session.add(setting)


def import_emails(emails_data: List[Dict], user_map: Dict[str, int]) -> Dict[str, int]:
    """Importiert E-Mails und gibt ein Mapping von message_id zu neuer ID zurück."""
    email_map = {}  # message_id -> neue_id
    
    for e_data in emails_data:
        sent_by_user_id = None
        if e_data.get('sent_by_user_email'):
            sent_by_user_id = user_map.get(e_data['sent_by_user_email'])
        
        existing = None
        if e_data.get('message_id'):
            existing = EmailMessage.query.filter_by(message_id=e_data['message_id']).first()
        
        if existing:
            # Aktualisiere bestehende E-Mail
            existing.subject = e_data['subject']
            existing.sender = e_data['sender']
            existing.recipients = e_data['recipients']
            existing.cc = e_data.get('cc')
            existing.bcc = e_data.get('bcc')
            existing.body_text = e_data.get('body_text')
            existing.body_html = e_data.get('body_html')
            existing.is_read = e_data.get('is_read', False)
            existing.is_sent = e_data.get('is_sent', False)
            existing.has_attachments = e_data.get('has_attachments', False)
            existing.folder = e_data.get('folder', 'INBOX')
            existing.sent_by_user_id = sent_by_user_id
            if e_data.get('received_at'):
                existing.received_at = datetime.fromisoformat(e_data['received_at'])
            if e_data.get('sent_at'):
                existing.sent_at = datetime.fromisoformat(e_data['sent_at'])
            if e_data.get('message_id'):
                email_map[e_data['message_id']] = existing.id
        else:
            # Neue E-Mail
            email = EmailMessage(
                uid=e_data.get('uid'),
                message_id=e_data.get('message_id'),
                subject=e_data['subject'],
                sender=e_data['sender'],
                recipients=e_data['recipients'],
                cc=e_data.get('cc'),
                bcc=e_data.get('bcc'),
                body_text=e_data.get('body_text'),
                body_html=e_data.get('body_html'),
                is_read=e_data.get('is_read', False),
                is_sent=e_data.get('is_sent', False),
                has_attachments=e_data.get('has_attachments', False),
                folder=e_data.get('folder', 'INBOX'),
                sent_by_user_id=sent_by_user_id
            )
            if e_data.get('received_at'):
                email.received_at = datetime.fromisoformat(e_data['received_at'])
            if e_data.get('sent_at'):
                email.sent_at = datetime.fromisoformat(e_data['sent_at'])
            db.session.add(email)
            db.session.flush()
            if email.message_id:
                email_map[email.message_id] = email.id
    
    return email_map


def import_email_permissions(permissions_data: List[Dict], user_map: Dict[str, int]):
    """Importiert E-Mail-Berechtigungen."""
    for p_data in permissions_data:
        user_email = p_data.get('user_email')
        if not user_email or user_email not in user_map:
            continue
        
        user_id = user_map[user_email]
        existing = EmailPermission.query.filter_by(user_id=user_id).first()
        if existing:
            existing.can_read = p_data.get('can_read', True)
            existing.can_send = p_data.get('can_send', True)
        else:
            permission = EmailPermission(
                user_id=user_id,
                can_read=p_data.get('can_read', True),
                can_send=p_data.get('can_send', True)
            )
            db.session.add(permission)


def import_email_attachments(attachments_data: List[Dict], email_map: Dict[str, int]):
    """Importiert E-Mail-Anhänge."""
    for att_data in attachments_data:
        message_id = att_data.get('email_message_id')
        if not message_id or message_id not in email_map:
            continue
        
        email_id = email_map[message_id]
        
        attachment = EmailAttachment(
            email_id=email_id,
            filename=att_data['filename'],
            content_type=att_data['content_type'],
            size=att_data.get('size', 0),
            is_inline=att_data.get('is_inline', False)
        )
        
        # Dateiinhalt speichern wenn vorhanden
        if att_data.get('content_base64'):
            try:
                import base64
                content = base64.b64decode(att_data['content_base64'])
                
                # Speichere Datei im Upload-Verzeichnis
                from werkzeug.utils import secure_filename
                filename = secure_filename(att_data['filename'])
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                filename = f"{timestamp}_{filename}"
                
                upload_dir = os.path.join(current_app.root_path, '..', current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'email_attachments')
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, filename)
                
                with open(file_path, 'wb') as f:
                    f.write(content)
                
                attachment.file_path = file_path
                attachment.is_large_file = True
            except Exception as e:
                current_app.logger.error(f"Fehler beim Speichern von E-Mail-Anhang {att_data['filename']}: {str(e)}")
                # Fallback: In Datenbank speichern
                attachment.content = content
        
        db.session.add(attachment)


def import_chats(chats_data: List[Dict], user_map: Dict[str, int]) -> Dict[str, int]:
    """Importiert Chats und gibt ein Mapping von Chat-Name zu neuer ID zurück."""
    chat_map = {}  # chat_name -> neue_id
    
    for c_data in chats_data:
        created_by_id = None
        if c_data.get('created_by_email'):
            created_by_id = user_map.get(c_data['created_by_email'])
        
        # Prüfe ob Chat mit gleichem Namen existiert
        existing = Chat.query.filter_by(name=c_data['name']).first()
        if existing:
            chat_map[c_data['name']] = existing.id
        else:
            chat = Chat(
                name=c_data['name'],
                is_main_chat=c_data.get('is_main_chat', False),
                is_direct_message=c_data.get('is_direct_message', False),
                created_by=created_by_id
            )
            db.session.add(chat)
            db.session.flush()
            chat_map[c_data['name']] = chat.id
    
    return chat_map


def import_chat_messages(messages_data: List[Dict], chat_map: Dict[str, int], user_map: Dict[str, int]):
    """Importiert Chat-Nachrichten."""
    for m_data in messages_data:
        chat_name = m_data.get('chat_name')
        sender_email = m_data.get('sender_email')
        
        if not chat_name or chat_name not in chat_map:
            continue
        if not sender_email or sender_email not in user_map:
            continue
        
        chat_id = chat_map[chat_name]
        sender_id = user_map[sender_email]
        
        message = ChatMessage(
            chat_id=chat_id,
            sender_id=sender_id,
            content=m_data.get('content'),
            message_type=m_data.get('message_type', 'text'),
            media_url=m_data.get('media_url'),
            is_deleted=m_data.get('is_deleted', False)
        )
        if m_data.get('created_at'):
            message.created_at = datetime.fromisoformat(m_data['created_at'])
        if m_data.get('edited_at'):
            message.edited_at = datetime.fromisoformat(m_data['edited_at'])
        db.session.add(message)


def import_chat_members(members_data: List[Dict], chat_map: Dict[str, int], user_map: Dict[str, int]):
    """Importiert Chat-Mitglieder."""
    for m_data in members_data:
        chat_name = m_data.get('chat_name')
        user_email = m_data.get('user_email')
        
        if not chat_name or chat_name not in chat_map:
            continue
        if not user_email or user_email not in user_map:
            continue
        
        chat_id = chat_map[chat_name]
        user_id = user_map[user_email]
        
        # Prüfe ob Mitgliedschaft bereits existiert
        existing = ChatMember.query.filter_by(chat_id=chat_id, user_id=user_id).first()
        if not existing:
            member = ChatMember(
                chat_id=chat_id,
                user_id=user_id
            )
            if m_data.get('joined_at'):
                member.joined_at = datetime.fromisoformat(m_data['joined_at'])
            if m_data.get('last_read_at'):
                member.last_read_at = datetime.fromisoformat(m_data['last_read_at'])
            db.session.add(member)


def import_calendar_events(events_data: List[Dict], user_map: Dict[str, int]) -> Dict[str, int]:
    """Importiert Kalender-Termine und gibt ein Mapping von Titel zu neuer ID zurück."""
    event_map = {}  # event_title -> neue_id
    
    for e_data in events_data:
        created_by_email = e_data.get('created_by_email')
        if not created_by_email or created_by_email not in user_map:
            continue
        
        created_by_id = user_map[created_by_email]
        
        event = CalendarEvent(
            title=e_data['title'],
            description=e_data.get('description'),
            start_time=datetime.fromisoformat(e_data['start_time']),
            end_time=datetime.fromisoformat(e_data['end_time']),
            location=e_data.get('location'),
            created_by=created_by_id
        )
        db.session.add(event)
        db.session.flush()
        event_map[e_data['title']] = event.id
    
    return event_map


def import_event_participants(participants_data: List[Dict], event_map: Dict[str, int], user_map: Dict[str, int]):
    """Importiert Event-Teilnehmer."""
    for p_data in participants_data:
        event_title = p_data.get('event_title')
        user_email = p_data.get('user_email')
        
        if not event_title or event_title not in event_map:
            continue
        if not user_email or user_email not in user_map:
            continue
        
        event_id = event_map[event_title]
        user_id = user_map[user_email]
        
        # Prüfe ob Teilnahme bereits existiert
        existing = EventParticipant.query.filter_by(event_id=event_id, user_id=user_id).first()
        if not existing:
            participant = EventParticipant(
                event_id=event_id,
                user_id=user_id,
                status=p_data.get('status', 'pending')
            )
            if p_data.get('responded_at'):
                participant.responded_at = datetime.fromisoformat(p_data['responded_at'])
            db.session.add(participant)


def import_credentials(credentials_data: List[Dict], user_map: Dict[str, int]):
    """Importiert Zugangsdaten (verschlüsselt neu)."""
    key = get_encryption_key()
    
    for c_data in credentials_data:
        created_by_email = c_data.get('created_by_email')
        if not created_by_email or created_by_email not in user_map:
            continue
        
        created_by_id = user_map[created_by_email]
        
        # Prüfe ob Credential bereits existiert
        existing = Credential.query.filter_by(
            website_url=c_data['website_url'],
            username=c_data['username'],
            created_by=created_by_id
        ).first()
        
        if existing:
            # Aktualisiere bestehendes Credential
            existing.website_name = c_data['website_name']
            existing.notes = c_data.get('notes')
            existing.favicon_url = c_data.get('favicon_url')
            if c_data.get('password'):
                existing.set_password(c_data['password'], key)
        else:
            # Neues Credential
            credential = Credential(
                website_url=c_data['website_url'],
                website_name=c_data['website_name'],
                username=c_data['username'],
                notes=c_data.get('notes'),
                favicon_url=c_data.get('favicon_url'),
                created_by=created_by_id
            )
            if c_data.get('password'):
                credential.set_password(c_data['password'], key)
            db.session.add(credential)


def import_folders(folders_data: List[Dict], user_map: Dict[str, int]) -> Dict[str, int]:
    """Importiert Ordner und gibt ein Mapping von Ordner-Name zu neuer ID zurück."""
    folder_map = {}  # folder_name -> neue_id
    
    # Sortiere nach Hierarchie (Root-Ordner zuerst)
    sorted_folders = sorted(folders_data, key=lambda x: (x.get('parent_name') is not None, x.get('name', '')))
    
    for f_data in sorted_folders:
        created_by_email = f_data.get('created_by_email')
        if not created_by_email or created_by_email not in user_map:
            continue
        
        created_by_id = user_map[created_by_email]
        parent_id = None
        if f_data.get('parent_name') and f_data['parent_name'] in folder_map:
            parent_id = folder_map[f_data['parent_name']]
        
        # Prüfe ob Ordner bereits existiert
        existing = Folder.query.filter_by(name=f_data['name'], created_by=created_by_id).first()
        if existing:
            folder_map[f_data['name']] = existing.id
        else:
            folder = Folder(
                name=f_data['name'],
                parent_id=parent_id,
                created_by=created_by_id,
                is_dropbox=f_data.get('is_dropbox', False),
                share_enabled=f_data.get('share_enabled', False),
                share_name=f_data.get('share_name')
            )
            if f_data.get('share_expires_at'):
                folder.share_expires_at = datetime.fromisoformat(f_data['share_expires_at'])
            db.session.add(folder)
            db.session.flush()
            folder_map[f_data['name']] = folder.id
    
    return folder_map


def import_files(files_data: List[Dict], folder_map: Dict[str, int], user_map: Dict[str, int]):
    """Importiert Dateien."""
    for f_data in files_data:
        uploaded_by_email = f_data.get('uploaded_by_email')
        if not uploaded_by_email or uploaded_by_email not in user_map:
            continue
        
        uploaded_by_id = user_map[uploaded_by_email]
        folder_id = None
        if f_data.get('folder_name') and f_data['folder_name'] in folder_map:
            folder_id = folder_map[f_data['folder_name']]
        
        # Prüfe ob Datei bereits existiert
        existing = File.query.filter_by(name=f_data['name'], uploaded_by=uploaded_by_id).first()
        
        if existing:
            # Aktualisiere bestehende Datei
            existing.original_name = f_data.get('original_name', f_data['name'])
            existing.folder_id = folder_id
            existing.file_size = f_data.get('file_size', 0)
            existing.mime_type = f_data.get('mime_type')
            existing.version_number = f_data.get('version_number', 1)
            existing.is_current = f_data.get('is_current', True)
            existing.share_enabled = f_data.get('share_enabled', False)
            existing.share_name = f_data.get('share_name')
            if f_data.get('share_expires_at'):
                existing.share_expires_at = datetime.fromisoformat(f_data['share_expires_at'])
        else:
            # Neue Datei
            file = File(
                name=f_data['name'],
                original_name=f_data.get('original_name', f_data['name']),
                folder_id=folder_id,
                uploaded_by=uploaded_by_id,
                file_size=f_data.get('file_size', 0),
                mime_type=f_data.get('mime_type'),
                version_number=f_data.get('version_number', 1),
                is_current=f_data.get('is_current', True),
                share_enabled=f_data.get('share_enabled', False),
                share_name=f_data.get('share_name')
            )
            if f_data.get('share_expires_at'):
                file.share_expires_at = datetime.fromisoformat(f_data['share_expires_at'])
            
            # Dateiinhalt speichern wenn vorhanden
            if f_data.get('content_base64'):
                try:
                    import base64
                    content = base64.b64decode(f_data['content_base64'])
                    # Speichere Datei im Upload-Verzeichnis
                    from werkzeug.utils import secure_filename
                    filename = secure_filename(file.name)
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"{timestamp}_{filename}"
                    
                    upload_dir = os.path.join(current_app.root_path, '..', current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'files')
                    os.makedirs(upload_dir, exist_ok=True)
                    file_path = os.path.join(upload_dir, filename)
                    
                    with open(file_path, 'wb') as f:
                        f.write(content)
                    
                    file.file_path = file_path
                except Exception as e:
                    current_app.logger.error(f"Fehler beim Speichern von Datei {file.name}: {str(e)}")
            
            db.session.add(file)


def import_file_versions(versions_data: List[Dict], user_map: Dict[str, int]):
    """Importiert Datei-Versionen."""
    for v_data in versions_data:
        uploaded_by_email = v_data.get('uploaded_by_email')
        if not uploaded_by_email or uploaded_by_email not in user_map:
            continue
        
        uploaded_by_id = user_map[uploaded_by_email]
        
        # Finde Datei nach Name
        file = File.query.filter_by(name=v_data.get('file_name')).first()
        if not file:
            continue
        
        # Prüfe ob Version bereits existiert
        existing = FileVersion.query.filter_by(file_id=file.id, version_number=v_data['version_number']).first()
        if existing:
            continue
        
        version = FileVersion(
            file_id=file.id,
            version_number=v_data['version_number'],
            file_size=v_data.get('file_size', 0),
            uploaded_by=uploaded_by_id
        )
        
        # Dateiinhalt speichern wenn vorhanden
        if v_data.get('content_base64'):
            try:
                import base64
                content = base64.b64decode(v_data['content_base64'])
                from werkzeug.utils import secure_filename
                filename = secure_filename(f"{file.name}_v{v_data['version_number']}")
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                filename = f"{timestamp}_{filename}"
                
                upload_dir = os.path.join(current_app.root_path, '..', current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'files')
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, filename)
                
                with open(file_path, 'wb') as f:
                    f.write(content)
                
                version.file_path = file_path
            except Exception as e:
                current_app.logger.error(f"Fehler beim Speichern von Dateiversion: {str(e)}")
        
        db.session.add(version)


def import_wiki_categories(categories_data: List[Dict]) -> Dict[str, int]:
    """Importiert Wiki-Kategorien und gibt ein Mapping von Name zu neuer ID zurück."""
    category_map = {}  # name -> neue_id
    
    for c_data in categories_data:
        existing = WikiCategory.query.filter_by(name=c_data['name']).first()
        if existing:
            # Aktualisiere bestehende Kategorie
            existing.description = c_data.get('description')
            existing.color = c_data.get('color')
            category_map[c_data['name']] = existing.id
        else:
            # Neue Kategorie
            category = WikiCategory(
                name=c_data['name'],
                description=c_data.get('description'),
                color=c_data.get('color')
            )
            db.session.add(category)
            db.session.flush()
            category_map[c_data['name']] = category.id
    
    return category_map


def import_wiki_tags(tags_data: List[Dict]) -> Dict[str, int]:
    """Importiert Wiki-Tags und gibt ein Mapping von Name zu neuer ID zurück."""
    tag_map = {}  # name -> neue_id
    
    for t_data in tags_data:
        existing = WikiTag.query.filter_by(name=t_data['name']).first()
        if existing:
            tag_map[t_data['name']] = existing.id
        else:
            # Neuer Tag
            tag = WikiTag(name=t_data['name'])
            db.session.add(tag)
            db.session.flush()
            tag_map[t_data['name']] = tag.id
    
    return tag_map


def import_wiki_pages(pages_data: List[Dict], category_map: Dict[str, int], tag_map: Dict[str, int], user_map: Dict[str, int]) -> Dict[str, int]:
    """Importiert Wiki-Seiten und gibt ein Mapping von Slug zu neuer ID zurück."""
    page_map = {}  # slug -> neue_id
    
    for p_data in pages_data:
        created_by_email = p_data.get('created_by_email')
        if not created_by_email or created_by_email not in user_map:
            continue
        
        created_by_id = user_map[created_by_email]
        category_id = None
        if p_data.get('category_name') and p_data['category_name'] in category_map:
            category_id = category_map[p_data['category_name']]
        
        # Prüfe ob Seite bereits existiert
        existing = WikiPage.query.filter_by(slug=p_data['slug']).first()
        if existing:
            # Aktualisiere bestehende Seite
            existing.title = p_data['title']
            existing.content = p_data.get('content', p_data.get('file_content', ''))
            existing.category_id = category_id
            existing.version_number = p_data.get('version_number', 1)
            if p_data.get('updated_at'):
                existing.updated_at = datetime.fromisoformat(p_data['updated_at'])
            page_map[p_data['slug']] = existing.id
        else:
            # Neue Seite
            content = p_data.get('content') or p_data.get('file_content', '')
            
            # Erstelle Datei
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{p_data['slug']}.md"
            upload_dir = os.path.join('uploads', 'wiki')
            os.makedirs(upload_dir, exist_ok=True)
            filepath = os.path.join(upload_dir, filename)
            absolute_filepath = os.path.abspath(filepath)
            
            # Speichere Markdown-Datei
            try:
                with open(absolute_filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
            except Exception as e:
                current_app.logger.error(f"Fehler beim Speichern von Wiki-Datei {absolute_filepath}: {str(e)}")
                absolute_filepath = None
            
            page = WikiPage(
                title=p_data['title'],
                slug=p_data['slug'],
                content=content,
                file_path=absolute_filepath or '',
                category_id=category_id,
                created_by=created_by_id,
                version_number=p_data.get('version_number', 1)
            )
            if p_data.get('created_at'):
                page.created_at = datetime.fromisoformat(p_data['created_at'])
            if p_data.get('updated_at'):
                page.updated_at = datetime.fromisoformat(p_data['updated_at'])
            
            db.session.add(page)
            db.session.flush()
            
            # Tags hinzufügen
            if p_data.get('tags'):
                for tag_name in p_data['tags']:
                    if tag_name in tag_map:
                        tag_id = tag_map[tag_name]
                        tag = WikiTag.query.get(tag_id)
                        if tag:
                            page.tags.append(tag)
            
            page_map[p_data['slug']] = page.id
    
    return page_map


def import_wiki_page_versions(versions_data: List[Dict], page_map: Dict[str, int], user_map: Dict[str, int]):
    """Importiert Wiki-Seiten-Versionen."""
    for v_data in versions_data:
        page_slug = v_data.get('page_slug')
        if not page_slug or page_slug not in page_map:
            continue
        
        created_by_email = v_data.get('created_by_email')
        if not created_by_email or created_by_email not in user_map:
            continue
        
        page_id = page_map[page_slug]
        created_by_id = user_map[created_by_email]
        content = v_data.get('content') or v_data.get('file_content', '')
        
        # Prüfe ob Version bereits existiert
        existing = WikiPageVersion.query.filter_by(
            wiki_page_id=page_id,
            version_number=v_data['version_number']
        ).first()
        
        if existing:
            continue
        
        # Erstelle Datei
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_v{v_data['version_number']}_{page_slug}.md"
        upload_dir = os.path.join('uploads', 'wiki')
        filepath = os.path.join(upload_dir, filename)
        absolute_filepath = os.path.abspath(filepath)
        
        # Speichere Markdown-Datei
        try:
            with open(absolute_filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            current_app.logger.error(f"Fehler beim Speichern von Wiki-Versionsdatei {absolute_filepath}: {str(e)}")
            absolute_filepath = None
        
        version = WikiPageVersion(
            wiki_page_id=page_id,
            version_number=v_data['version_number'],
            content=content,
            file_path=absolute_filepath or '',
            created_by=created_by_id
        )
        if v_data.get('created_at'):
            version.created_at = datetime.fromisoformat(v_data['created_at'])
        
        db.session.add(version)


def import_comments(comments_data: List[Dict], user_map: Dict[str, int]) -> Dict[str, int]:
    """Importiert Kommentare und gibt ein Mapping von content_ref zu neuer ID zurück."""
    comment_map = {}  # content_ref -> neue_id
    
    # Erste Runde: Importiere alle Kommentare ohne Parent-Referenzen
    for c_data in comments_data:
        author_email = c_data.get('author_email')
        if not author_email or author_email not in user_map:
            continue
        
        author_id = user_map[author_email]
        
        # Finde Content-Objekt basierend auf Referenz
        content_id = None
        content_ref = c_data.get('content_reference', '')
        
        if c_data['content_type'] == 'file' and content_ref.startswith('file:'):
            file_name = content_ref.split(':', 1)[1]
            file_obj = File.query.filter_by(name=file_name).first()
            if file_obj:
                content_id = file_obj.id
        elif c_data['content_type'] == 'wiki' and content_ref.startswith('wiki:'):
            wiki_slug = content_ref.split(':', 1)[1]
            wiki_obj = WikiPage.query.filter_by(slug=wiki_slug).first()
            if wiki_obj:
                content_id = wiki_obj.id
        elif c_data['content_type'] == 'canvas' and content_ref.startswith('canvas:'):
            canvas_id_str = content_ref.split(':', 1)[1]
            try:
                canvas_id = int(canvas_id_str)
                from app.models.canvas import Canvas
                canvas_obj = Canvas.query.get(canvas_id)
                if canvas_obj:
                    content_id = canvas_obj.id
            except ValueError:
                pass
        
        # Fallback: Verwende content_id aus Backup falls vorhanden
        if not content_id and c_data.get('content_id'):
            # Versuche direkt zu finden (kann fehlschlagen wenn IDs sich geändert haben)
            if c_data['content_type'] == 'file':
                file_obj = File.query.get(c_data['content_id'])
                if file_obj:
                    content_id = file_obj.id
            elif c_data['content_type'] == 'wiki':
                wiki_obj = WikiPage.query.get(c_data['content_id'])
                if wiki_obj:
                    content_id = wiki_obj.id
            elif c_data['content_type'] == 'canvas':
                from app.models.canvas import Canvas
                canvas_obj = Canvas.query.get(c_data['content_id'])
                if canvas_obj:
                    content_id = canvas_obj.id
        
        if not content_id:
            continue
        
        comment = Comment(
            content_type=c_data['content_type'],
            content_id=content_id,
            content=c_data['content'],
            author_id=author_id,
            parent_id=None  # Wird später gesetzt
        )
        if c_data.get('created_at'):
            comment.created_at = datetime.fromisoformat(c_data['created_at'])
        if c_data.get('updated_at'):
            comment.updated_at = datetime.fromisoformat(c_data['updated_at'])
        
        db.session.add(comment)
        db.session.flush()
        
        # Erstelle Referenz für Mapping (verwende old_id aus Backup)
        old_id = c_data.get('old_id', idx)
        content_ref_key = f"{c_data['content_type']}:{c_data.get('content_id', content_id)}:{old_id}"
        comment_map[content_ref_key] = comment.id
    
    # Zweite Runde: Setze Parent-Referenzen
    for idx, c_data in enumerate(comments_data):
        parent_content_ref = c_data.get('parent_content_ref')
        if not parent_content_ref:
            continue
        
        # Finde den Kommentar basierend auf der Referenz
        old_id = c_data.get('old_id', idx)
        content_ref_key = f"{c_data['content_type']}:{c_data.get('content_id')}:{old_id}"
        if content_ref_key not in comment_map:
            continue
        
        comment = Comment.query.get(comment_map[content_ref_key])
        if not comment:
            continue
        
        # Finde Parent-Kommentar über die Referenz
        if parent_content_ref in comment_map:
            comment.parent_id = comment_map[parent_content_ref]
    
    return comment_map


def import_comment_mentions(mentions_data: List[Dict], comment_map: Dict[str, int], user_map: Dict[str, int]):
    """Importiert Kommentar-Mentions."""
    for m_data in mentions_data:
        comment_content_ref = m_data.get('comment_content_ref')
        if not comment_content_ref or comment_content_ref not in comment_map:
            continue
        
        user_email = m_data.get('user_email')
        if not user_email or user_email not in user_map:
            continue
        
        comment_id = comment_map[comment_content_ref]
        user_id = user_map[user_email]
        
        # Prüfe ob Mention bereits existiert
        existing = CommentMention.query.filter_by(
            comment_id=comment_id,
            user_id=user_id
        ).first()
        
        if existing:
            continue
        
        mention = CommentMention(
            comment_id=comment_id,
            user_id=user_id,
            notification_sent=m_data.get('notification_sent', False)
        )
        if m_data.get('created_at'):
            mention.created_at = datetime.fromisoformat(m_data['created_at'])
        if m_data.get('notification_sent_at'):
            mention.notification_sent_at = datetime.fromisoformat(m_data['notification_sent_at'])
        
        db.session.add(mention)


def import_product_folders(folders_data: List[Dict], user_map: Dict[str, int]) -> Dict[str, int]:
    """Importiert Produkt-Ordner und gibt ein Mapping von Name zu neuer ID zurück."""
    folder_map = {}  # name -> neue_id
    
    for f_data in folders_data:
        created_by_email = f_data.get('created_by_email')
        if not created_by_email or created_by_email not in user_map:
            continue
        
        created_by_id = user_map[created_by_email]
        
        existing = ProductFolder.query.filter_by(name=f_data['name']).first()
        if existing:
            folder_map[f_data['name']] = existing.id
        else:
            folder = ProductFolder(
                name=f_data['name'],
                description=f_data.get('description'),
                color=f_data.get('color'),
                created_by=created_by_id
            )
            db.session.add(folder)
            db.session.flush()
            folder_map[f_data['name']] = folder.id
    
    return folder_map


def import_products(products_data: List[Dict], folder_map: Dict[str, int], user_map: Dict[str, int]) -> Dict[str, int]:
    """Importiert Produkte und gibt ein Mapping von Name zu neuer ID zurück."""
    product_map = {}  # name -> neue_id
    
    for p_data in products_data:
        created_by_email = p_data.get('created_by_email')
        if not created_by_email or created_by_email not in user_map:
            continue
        
        created_by_id = user_map[created_by_email]
        folder_id = None
        if p_data.get('folder_name') and p_data['folder_name'] in folder_map:
            folder_id = folder_map[p_data['folder_name']]
        
        existing = Product.query.filter_by(name=p_data['name']).first()
        if existing:
            product_map[p_data['name']] = existing.id
        else:
            normalized_length = None
            if 'length_meters' in p_data and p_data['length_meters'] not in (None, ''):
                try:
                    normalized_length = format_length_from_meters(float(p_data['length_meters']))
                except (TypeError, ValueError):
                    normalized_length = None
            if normalized_length is None:
                raw_length = p_data.get('length')
                if raw_length not in (None, ''):
                    normalized_length, _ = normalize_length_input(raw_length)
                    if normalized_length is None:
                        normalized_length = raw_length
            product = Product(
                name=p_data['name'],
                description=p_data.get('description'),
                category=p_data.get('category'),
                serial_number=p_data.get('serial_number'),
                condition=p_data.get('condition'),
                location=p_data.get('location'),
                length=normalized_length,
                purchase_date=datetime.fromisoformat(p_data['purchase_date']).date() if p_data.get('purchase_date') else None,
                status=p_data.get('status', 'available'),
                image_path=p_data.get('image_path'),
                qr_code_data=p_data.get('qr_code_data'),
                folder_id=folder_id,
                created_by=created_by_id
            )
            db.session.add(product)
            db.session.flush()
            product_map[p_data['name']] = product.id
    
    return product_map


def import_borrow_transactions(transactions_data: List[Dict], product_map: Dict[str, int], user_map: Dict[str, int]):
    """Importiert Ausleihtransaktionen."""
    for t_data in transactions_data:
        product_name = t_data.get('product_name')
        borrower_email = t_data.get('borrower_email')
        borrowed_by_email = t_data.get('borrowed_by_email')
        
        if not product_name or product_name not in product_map:
            continue
        if not borrower_email or borrower_email not in user_map:
            continue
        if not borrowed_by_email or borrowed_by_email not in user_map:
            continue
        
        product_id = product_map[product_name]
        borrower_id = user_map[borrower_email]
        borrowed_by_id = user_map[borrowed_by_email]
        
        existing = BorrowTransaction.query.filter_by(transaction_number=t_data['transaction_number']).first()
        if existing:
            continue
        
        transaction = BorrowTransaction(
            transaction_number=t_data['transaction_number'],
            borrow_group_id=t_data.get('borrow_group_id'),
            product_id=product_id,
            borrower_id=borrower_id,
            borrowed_by_id=borrowed_by_id,
            expected_return_date=datetime.fromisoformat(t_data['expected_return_date']).date() if t_data.get('expected_return_date') else None,
            actual_return_date=datetime.fromisoformat(t_data['actual_return_date']).date() if t_data.get('actual_return_date') else None,
            status=t_data.get('status', 'active'),
            qr_code_data=t_data.get('qr_code_data')
        )
        if t_data.get('borrow_date'):
            transaction.borrow_date = datetime.fromisoformat(t_data['borrow_date'])
        db.session.add(transaction)


def import_product_sets(sets_data: List[Dict], user_map: Dict[str, int]) -> Dict[str, int]:
    """Importiert Produktsets und gibt ein Mapping von Name zu neuer ID zurück."""
    set_map = {}  # name -> neue_id
    
    for s_data in sets_data:
        created_by_email = s_data.get('created_by_email')
        if not created_by_email or created_by_email not in user_map:
            continue
        
        created_by_id = user_map[created_by_email]
        
        existing = ProductSet.query.filter_by(name=s_data['name']).first()
        if existing:
            set_map[s_data['name']] = existing.id
        else:
            product_set = ProductSet(
                name=s_data['name'],
                description=s_data.get('description'),
                created_by=created_by_id
            )
            db.session.add(product_set)
            db.session.flush()
            set_map[s_data['name']] = product_set.id
    
    return set_map


def import_product_set_items(items_data: List[Dict], set_map: Dict[str, int], product_map: Dict[str, int]):
    """Importiert Produktset-Items."""
    for i_data in items_data:
        set_name = i_data.get('set_name')
        product_name = i_data.get('product_name')
        
        if not set_name or set_name not in set_map:
            continue
        if not product_name or product_name not in product_map:
            continue
        
        set_id = set_map[set_name]
        product_id = product_map[product_name]
        
        existing = ProductSetItem.query.filter_by(set_id=set_id, product_id=product_id).first()
        if existing:
            continue
        
        item = ProductSetItem(
            set_id=set_id,
            product_id=product_id,
            quantity=i_data.get('quantity', 1)
        )
        db.session.add(item)


def import_product_documents(documents_data: List[Dict], product_map: Dict[str, int], user_map: Dict[str, int]):
    """Importiert Produktdokumente."""
    for d_data in documents_data:
        product_name = d_data.get('product_name')
        uploaded_by_email = d_data.get('uploaded_by_email')
        
        if not product_name or product_name not in product_map:
            continue
        if not uploaded_by_email or uploaded_by_email not in user_map:
            continue
        
        product_id = product_map[product_name]
        uploaded_by_id = user_map[uploaded_by_email]
        
        document = ProductDocument(
            product_id=product_id,
            file_name=d_data['file_name'],
            file_type=d_data['file_type'],
            file_size=d_data.get('file_size'),
            uploaded_by=uploaded_by_id
        )
        
        # Dateiinhalt speichern wenn vorhanden
        if d_data.get('content_base64'):
            try:
                import base64
                content = base64.b64decode(d_data['content_base64'])
                
                from werkzeug.utils import secure_filename
                filename = secure_filename(d_data['file_name'])
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                filename = f"{timestamp}_{filename}"
                
                upload_dir = os.path.join(current_app.root_path, '..', current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'product_documents')
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, filename)
                
                with open(file_path, 'wb') as f:
                    f.write(content)
                
                document.file_path = file_path
            except Exception as e:
                current_app.logger.error(f"Fehler beim Speichern von Produktdokument {d_data['file_name']}: {str(e)}")
        
        db.session.add(document)


def import_saved_filters(filters_data: List[Dict], user_map: Dict[str, int]):
    """Importiert gespeicherte Filter."""
    for f_data in filters_data:
        user_email = f_data.get('user_email')
        if not user_email or user_email not in user_map:
            continue
        
        user_id = user_map[user_email]
        
        existing = SavedFilter.query.filter_by(user_id=user_id, name=f_data['name']).first()
        if existing:
            continue
        
        filter_obj = SavedFilter(
            user_id=user_id,
            name=f_data['name'],
            filter_data=f_data['filter_data']
        )
        db.session.add(filter_obj)


def import_product_favorites(favorites_data: List[Dict], product_map: Dict[str, int], user_map: Dict[str, int]):
    """Importiert Produktfavoriten."""
    for f_data in favorites_data:
        user_email = f_data.get('user_email')
        product_name = f_data.get('product_name')
        
        if not user_email or user_email not in user_map:
            continue
        if not product_name or product_name not in product_map:
            continue
        
        user_id = user_map[user_email]
        product_id = product_map[product_name]
        
        existing = ProductFavorite.query.filter_by(user_id=user_id, product_id=product_id).first()
        if existing:
            continue
        
        favorite = ProductFavorite(
            user_id=user_id,
            product_id=product_id
        )
        db.session.add(favorite)


def import_inventories(inventories_data: List[Dict], user_map: Dict[str, int]) -> Dict[str, int]:
    """Importiert Inventuren und gibt ein Mapping von Name zu neuer ID zurück."""
    inventory_map = {}  # name -> neue_id
    
    for i_data in inventories_data:
        started_by_email = i_data.get('started_by_email')
        if not started_by_email or started_by_email not in user_map:
            continue
        
        started_by_id = user_map[started_by_email]
        
        existing = Inventory.query.filter_by(name=i_data['name']).first()
        if existing:
            inventory_map[i_data['name']] = existing.id
        else:
            inventory = Inventory(
                name=i_data['name'],
                description=i_data.get('description'),
                status=i_data.get('status', 'active'),
                started_by=started_by_id
            )
            if i_data.get('started_at'):
                inventory.started_at = datetime.fromisoformat(i_data['started_at'])
            if i_data.get('completed_at'):
                inventory.completed_at = datetime.fromisoformat(i_data['completed_at'])
            db.session.add(inventory)
            db.session.flush()
            inventory_map[i_data['name']] = inventory.id
    
    return inventory_map


def import_inventory_items(items_data: List[Dict], inventory_map: Dict[str, int], product_map: Dict[str, int], user_map: Dict[str, int]):
    """Importiert Inventur-Items."""
    for i_data in items_data:
        inventory_name = i_data.get('inventory_name')
        product_name = i_data.get('product_name')
        
        if not inventory_name or inventory_name not in inventory_map:
            continue
        if not product_name or product_name not in product_map:
            continue
        
        inventory_id = inventory_map[inventory_name]
        product_id = product_map[product_name]
        
        existing = InventoryItem.query.filter_by(inventory_id=inventory_id, product_id=product_id).first()
        if existing:
            continue
        
        checked_by_id = None
        if i_data.get('checked_by_email') and i_data['checked_by_email'] in user_map:
            checked_by_id = user_map[i_data['checked_by_email']]
        
        item = InventoryItem(
            inventory_id=inventory_id,
            product_id=product_id,
            checked=i_data.get('checked', False),
            notes=i_data.get('notes'),
            location_changed=i_data.get('location_changed', False),
            new_location=i_data.get('new_location'),
            condition_changed=i_data.get('condition_changed', False),
            new_condition=i_data.get('new_condition'),
            checked_by=checked_by_id
        )
        if i_data.get('checked_at'):
            item.checked_at = datetime.fromisoformat(i_data['checked_at'])
        db.session.add(item)

