"""Backup export orchestrator and category exporters."""

import json
import os
import secrets
import shutil
import tempfile
from datetime import datetime
from typing import List, Dict, Set, Optional
from flask import current_app
from app import db
from app.models import (
    User,
    File, FileVersion, Folder, ResourceACL, FolderFavorite,
    Calendar, CalendarEvent, EventParticipant, PublicCalendarFeed, CalendarSyncSource,
    EmailMessage, EmailPermission, EmailAttachment,
    Credential, SystemSettings, WhitelistEntry,
    NotificationSettings, WikiPage, WikiPageVersion, WikiCategory, WikiTag,
    Comment, CommentMention,
    Product, BorrowTransaction, ProductFolder, ProductSet, ProductSetItem,
    ProductDocument, SavedFilter, ProductFavorite, Inventory, InventoryItem,
    Manual, Chat, ChatMessage, ChatMember, ChatPin,
    Contact, ShortLink,
    Event, EventAppointment, EventAssignment, EventInventoryNeed, EventContact, EventTimelineItem,
    MusicProviderToken, MusicWish, MusicQueue, MusicSettings,
    MediaDownloadJob,
    AssessmentUser, AssessmentRole, AssessmentUserRole, AssessmentStandType,
    AssessmentList, AssessmentListSubject, AssessmentRoom, AssessmentStand,
    AssessmentCriterion, AssessmentEvaluation, AssessmentEvaluationScore,
    AssessmentVisitorEvaluation, AssessmentVisitorEvaluationScore,
    AssessmentWarning, AssessmentRoomInspection, AssessmentAppSetting,
)
from app.models.role import UserModuleRole
from app.models.public_share import PublicShare
from app.models.booking import (
    BookingForm, BookingFormField, BookingFormImage, BookingRequest, BookingRequestField,
    BookingRequestFile, BookingFormRole, BookingFormRoleUser, BookingRequestApproval,
)
from app.blueprints.credentials import get_encryption_key
from app.utils.backup_lookups import (
    lookup_entity,
    lookup_entity_name,
    lookup_team_name,
    lookup_user_email,
    objects_by_name,
)
from app.utils.lengths import normalize_length_input, parse_length_to_meters, format_length_from_meters
from app.utils.backup_extensions import (
    export_user_module_roles, import_user_module_roles,
    export_chat_pins, import_chat_pins,
    export_calendars, import_calendars,
    export_calendar_sync_sources, import_calendar_sync_sources,
    export_public_calendar_feeds, import_public_calendar_feeds,
    export_resource_acls, import_resource_acls,
    export_folder_favorites, import_folder_favorites,
    export_contacts, import_contacts,
    export_portal_events, import_portal_events,
    export_event_appointments, import_event_appointments,
    export_event_assignments, import_event_assignments,
    export_event_inventory_needs, import_event_inventory_needs,
    export_event_contacts, import_event_contacts,
    export_event_timeline_items, import_event_timeline_items,
    export_booking_forms, export_booking_form_fields, export_booking_form_images,
    export_booking_form_roles, export_booking_form_role_users,
    export_booking_requests, export_booking_request_fields, export_booking_request_approvals,
    import_booking_bundle,
    export_music_settings, import_music_settings,
    export_music_wishes, import_music_wishes,
    export_music_queue, import_music_queue,
    export_media_download_jobs, import_media_download_jobs,
    export_assessment_bundle, import_assessment_bundle,
    export_short_links, import_short_links,
    export_excalidraw_drawings, import_excalidraw_drawings,
    export_excalidraw_drawing_versions, import_excalidraw_drawing_versions,
)

from app.utils.backup.constants import BACKUP_VERSION, _category_selected

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

    from app.utils.backup_lookups import prime_backup_lookups
    prime_backup_lookups()
    
    # Einstellungen exportieren
    if _category_selected(categories, 'settings'):
        backup_data['data']['settings'] = export_settings()
        backup_data['data']['whitelist'] = export_whitelist()
    
    # Benutzer exportieren
    if _category_selected(categories, 'users'):
        backup_data['data']['users'] = export_users()
        backup_data['data']['notification_settings'] = export_notification_settings()
        backup_data['data']['user_module_roles'] = export_user_module_roles()
    
    # E-Mails exportieren
    if _category_selected(categories, 'emails'):
        backup_data['data']['emails'] = export_emails()
        backup_data['data']['email_permissions'] = export_email_permissions()
        backup_data['data']['email_attachments'] = export_email_attachments()
    
    # Termine exportieren
    if _category_selected(categories, 'appointments'):
        backup_data['data']['calendars'] = export_calendars()
        backup_data['data']['calendar_sync_sources'] = export_calendar_sync_sources()
        backup_data['data']['public_calendar_feeds'] = export_public_calendar_feeds()
        backup_data['data']['calendar_events'] = export_calendar_events()
        backup_data['data']['event_participants'] = export_event_participants()
    
    # Zugangsdaten exportieren (entschlüsselt)
    if _category_selected(categories, 'credentials'):
        backup_data['data']['credentials'] = export_credentials()
    
    # Handbücher exportieren
    if _category_selected(categories, 'manuals'):
        backup_data['data']['manuals'] = export_manuals()
    
    # Chats exportieren
    if _category_selected(categories, 'chats'):
        backup_data['data']['chats'] = export_chats()
        backup_data['data']['chat_members'] = export_chat_members()
        backup_data['data']['chat_messages'] = export_chat_messages()
        backup_data['data']['chat_pins'] = export_chat_pins()
    
    # Dateien exportieren
    if _category_selected(categories, 'files'):
        backup_data['data']['folders'] = export_folders()
        backup_data['data']['files'] = export_files()
        backup_data['data']['file_versions'] = export_file_versions()
        backup_data['data']['public_shares'] = export_public_shares()
        backup_data['data']['resource_acls'] = export_resource_acls()
        backup_data['data']['folder_favorites'] = export_folder_favorites()
    
    # Wiki exportieren
    if _category_selected(categories, 'wiki'):
        backup_data['data']['wiki_categories'] = export_wiki_categories()
        backup_data['data']['wiki_tags'] = export_wiki_tags()
        backup_data['data']['wiki_pages'] = export_wiki_pages()
        backup_data['data']['wiki_page_versions'] = export_wiki_page_versions()
    
    # Kommentare exportieren
    if _category_selected(categories, 'comments'):
        backup_data['data']['comments'] = export_comments()
        backup_data['data']['comment_mentions'] = export_comment_mentions()
    
    # Inventar exportieren
    if _category_selected(categories, 'inventory'):
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

    # Neue Module
    if _category_selected(categories, 'contacts'):
        backup_data['data']['contacts'] = export_contacts()
    if _category_selected(categories, 'events'):
        backup_data['data']['portal_events'] = export_portal_events()
        backup_data['data']['event_appointments'] = export_event_appointments()
        backup_data['data']['event_assignments'] = export_event_assignments()
        backup_data['data']['event_inventory_needs'] = export_event_inventory_needs()
        backup_data['data']['event_contacts'] = export_event_contacts()
        backup_data['data']['event_timeline_items'] = export_event_timeline_items()
    if _category_selected(categories, 'booking'):
        backup_data['data']['booking_forms'] = export_booking_forms()
        backup_data['data']['booking_form_fields'] = export_booking_form_fields()
        backup_data['data']['booking_form_images'] = export_booking_form_images()
        backup_data['data']['booking_form_roles'] = export_booking_form_roles()
        backup_data['data']['booking_form_role_users'] = export_booking_form_role_users()
        backup_data['data']['booking_requests'] = export_booking_requests()
        backup_data['data']['booking_request_fields'] = export_booking_request_fields()
        backup_data['data']['booking_request_approvals'] = export_booking_request_approvals()
    if _category_selected(categories, 'music'):
        backup_data['data']['music_settings'] = export_music_settings()
        backup_data['data']['music_wishes'] = export_music_wishes()
        backup_data['data']['music_queue'] = export_music_queue()
    if _category_selected(categories, 'media_downloader'):
        backup_data['data']['media_download_jobs'] = export_media_download_jobs()
    if _category_selected(categories, 'assessment'):
        backup_data['data'].update(export_assessment_bundle())
    if _category_selected(categories, 'shortlinks'):
        backup_data['data']['short_links'] = export_short_links()
    if _category_selected(categories, 'excalidraw'):
        backup_data['data']['excalidraw_drawings'] = export_excalidraw_drawings()
        backup_data['data']['excalidraw_drawing_versions'] = export_excalidraw_drawing_versions()
    
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
    result = []
    
    for s in settings:
        setting_data = {
            'key': s.key,
            'value': s.value,
            'description': s.description,
            'updated_at': s.updated_at.isoformat() if s.updated_at else None
        }
        
        # Wenn es sich um portal_logo handelt, exportiere die Datei als Base64
        if s.key == 'portal_logo' and s.value:
            try:
                project_root = os.path.dirname(current_app.root_path)
                logo_path = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'system', s.value)
                if os.path.exists(logo_path):
                    with open(logo_path, 'rb') as f:
                        import base64
                        logo_data = f.read()
                        setting_data['file_content_base64'] = base64.b64encode(logo_data).decode('utf-8')
                        setting_data['file_original_name'] = s.value
            except Exception as e:
                current_app.logger.error(f"Fehler beim Exportieren des Portal-Logos: {str(e)}")
        
        result.append(setting_data)
    
    return result


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
    result = []
    
    for u in users:
        user_data = {
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
            'is_super_admin': getattr(u, 'is_super_admin', False),
            'is_guest': getattr(u, 'is_guest', False),
            'guest_expires_at': u.guest_expires_at.isoformat() if getattr(u, 'guest_expires_at', None) else None,
            'guest_username': getattr(u, 'guest_username', None),
            'has_full_access': getattr(u, 'has_full_access', False),
            'oled_mode': getattr(u, 'oled_mode', False),
            'language': getattr(u, 'language', 'de'),
            'preferred_layout': getattr(u, 'preferred_layout', 'auto'),
            'must_change_password': getattr(u, 'must_change_password', False),
            'totp_enabled': getattr(u, 'totp_enabled', False),
            'created_at': u.created_at.isoformat() if u.created_at else None,
            'last_login': u.last_login.isoformat() if u.last_login else None
        }
        
        # Exportiere Profilbild als Base64 wenn vorhanden
        if u.profile_picture:
            try:
                project_root = os.path.dirname(current_app.root_path)
                pic_path = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'profile_pics', u.profile_picture)
                if os.path.exists(pic_path):
                    with open(pic_path, 'rb') as f:
                        import base64
                        pic_data = f.read()
                        user_data['profile_picture_content_base64'] = base64.b64encode(pic_data).decode('utf-8')
                        user_data['profile_picture_original_name'] = u.profile_picture
            except Exception as e:
                current_app.logger.error(f"Fehler beim Exportieren des Profilbilds für {u.email}: {str(e)}")
        
        result.append(user_data)
    
    return result


def export_notification_settings() -> List[Dict]:
    """Exportiert Notification-Einstellungen."""
    settings = NotificationSettings.query.all()
    return [{
        'user_email': lookup_user_email(s.user_id),
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
        'booking_notifications_enabled': getattr(s, 'booking_notifications_enabled', True),
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
        'sent_by_user_email': lookup_user_email(e.sent_by_user_id),
        'received_at': e.received_at.isoformat() if e.received_at else None,
        'sent_at': e.sent_at.isoformat() if e.sent_at else None,
        'created_at': e.created_at.isoformat() if e.created_at else None
    } for e in emails]


def export_email_permissions() -> List[Dict]:
    """Exportiert E-Mail-Berechtigungen."""
    permissions = EmailPermission.query.all()
    return [{
        'user_email': lookup_user_email(p.user_id),
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


def export_calendar_events() -> List[Dict]:
    """Exportiert Kalender-Termine."""
    events = CalendarEvent.query.all()
    return [{
        'title': e.title,
        'description': e.description,
        'start_time': e.start_time.isoformat() if e.start_time else None,
        'end_time': e.end_time.isoformat() if e.end_time else None,
        'location': e.location,
        'event_color': getattr(e, 'event_color', None),
        'calendar_export_id': getattr(e, 'calendar_id', None),
        'recurrence_type': getattr(e, 'recurrence_type', 'none'),
        'recurrence_end_date': e.recurrence_end_date.isoformat() if getattr(e, 'recurrence_end_date', None) else None,
        'recurrence_interval': getattr(e, 'recurrence_interval', 1),
        'recurrence_days': getattr(e, 'recurrence_days', None),
        'is_public': getattr(e, 'is_public', False),
        'created_by_email': lookup_user_email(e.created_by),
        'created_at': e.created_at.isoformat() if e.created_at else None,
        'updated_at': e.updated_at.isoformat() if e.updated_at else None
    } for e in events]


def export_event_participants() -> List[Dict]:
    """Exportiert Event-Teilnehmer."""
    participants = EventParticipant.query.all()
    return [{
        'event_title': lookup_entity_name('calendar_event', p.event_id),
        'user_email': lookup_user_email(p.user_id),
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
                'visibility': getattr(cred, 'visibility', 'public'),
                'team_id': getattr(cred, 'team_id', None),
                'created_by_email': lookup_user_email(cred.created_by),
                'created_at': cred.created_at.isoformat() if cred.created_at else None,
                'updated_at': cred.updated_at.isoformat() if cred.updated_at else None
            })
        except Exception as e:
            # Wenn Entschlüsselung fehlschlägt, überspringen
            current_app.logger.error(f"Fehler beim Entschlüsseln von Credential {cred.id}: {str(e)}")
            continue
    return result


def export_manuals() -> List[Dict]:
    """Exportiert Handbücher (inkl. PDF-Dateien als Base64)."""
    manuals = Manual.query.all()
    result = []
    for m in manuals:
        manual_data = {
            'title': m.title,
            'filename': m.filename,
            'file_size': m.file_size,
            'visibility': getattr(m, 'visibility', 'public'),
            'team_id': getattr(m, 'team_id', None),
            'uploaded_by_email': lookup_user_email(m.uploaded_by),
            'uploaded_at': m.uploaded_at.isoformat() if m.uploaded_at else None
        }
        
        # Exportiere PDF-Datei als Base64 wenn vorhanden
        if m.file_path and os.path.exists(m.file_path):
            try:
                with open(m.file_path, 'rb') as f:
                    import base64
                    file_data = f.read()
                    manual_data['file_content_base64'] = base64.b64encode(file_data).decode('utf-8')
                    manual_data['file_original_name'] = m.filename
            except Exception as e:
                current_app.logger.error(f"Fehler beim Exportieren des Handbuchs {m.title}: {str(e)}")
        elif m.file_path:
            # Versuche relativen Pfad
            try:
                project_root = os.path.dirname(current_app.root_path)
                manual_path = os.path.join(project_root, m.file_path)
                if os.path.exists(manual_path):
                    with open(manual_path, 'rb') as f:
                        import base64
                        file_data = f.read()
                        manual_data['file_content_base64'] = base64.b64encode(file_data).decode('utf-8')
                        manual_data['file_original_name'] = m.filename
            except Exception as e:
                current_app.logger.error(f"Fehler beim Exportieren des Handbuchs {m.title} (relativer Pfad): {str(e)}")
        
        result.append(manual_data)
    
    return result


def export_chats() -> List[Dict]:
    """Exportiert Chats."""
    chats = Chat.query.all()
    result = []
    for c in chats:
        chat_data = {
            'name': c.name,
            'description': c.description,
            'is_main_chat': c.is_main_chat,
            'is_direct_message': c.is_direct_message,
            'team_name': None,
            'created_by_email': lookup_user_email(c.created_by),
            'created_at': c.created_at.isoformat() if c.created_at else None,
            'updated_at': c.updated_at.isoformat() if c.updated_at else None
        }
        if getattr(c, 'team_id', None):
            chat_data['team_name'] = lookup_team_name(c.team_id)
        
        # Exportiere Gruppenbild als Base64 wenn vorhanden
        if c.group_avatar:
            try:
                project_root = os.path.dirname(current_app.root_path)
                avatar_path = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'chat_avatars', c.group_avatar)
                if os.path.exists(avatar_path):
                    with open(avatar_path, 'rb') as f:
                        import base64
                        avatar_data = f.read()
                        chat_data['group_avatar_content_base64'] = base64.b64encode(avatar_data).decode('utf-8')
                        chat_data['group_avatar_original_name'] = c.group_avatar
            except Exception as e:
                current_app.logger.error(f"Fehler beim Exportieren des Chat-Avatars für {c.name}: {str(e)}")
        
        result.append(chat_data)
    
    return result


def export_chat_members() -> List[Dict]:
    """Exportiert Chat-Mitglieder."""
    members = ChatMember.query.all()
    return [{
        'chat_name': lookup_entity_name('chat', m.chat_id),
        'user_email': lookup_user_email(m.user_id),
        'joined_at': m.joined_at.isoformat() if m.joined_at else None,
        'last_read_at': m.last_read_at.isoformat() if m.last_read_at else None
    } for m in members]


def export_chat_messages() -> List[Dict]:
    """Exportiert Chat-Nachrichten (inkl. Media-Dateien als Base64)."""
    messages = ChatMessage.query.all()
    result = []
    for msg in messages:
        message_data = {
            'chat_name': lookup_entity_name('chat', msg.chat_id),
            'sender_email': lookup_user_email(msg.sender_id),
            'content': msg.content,
            'message_type': msg.message_type,
            'created_at': msg.created_at.isoformat() if msg.created_at else None,
            'edited_at': msg.edited_at.isoformat() if msg.edited_at else None,
            'is_deleted': msg.is_deleted
        }
        
        # Exportiere Media-Datei als Base64 wenn vorhanden
        if msg.media_url:
            try:
                project_root = os.path.dirname(current_app.root_path)
                # Versuche verschiedene mögliche Pfade
                media_paths = [
                    os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'chat_media', msg.media_url),
                    os.path.join(project_root, msg.media_url),
                    msg.media_url
                ]
                
                media_data = None
                for media_path in media_paths:
                    if os.path.exists(media_path):
                        with open(media_path, 'rb') as f:
                            import base64
                            media_data = base64.b64encode(f.read()).decode('utf-8')
                            message_data['media_content_base64'] = media_data
                            message_data['media_original_name'] = os.path.basename(msg.media_url)
                            break
                
                if not media_data:
                    # Falls Datei nicht gefunden, speichere URL
                    message_data['media_url'] = msg.media_url
            except Exception as e:
                current_app.logger.error(f"Fehler beim Exportieren der Media-Datei für Nachricht {msg.id}: {str(e)}")
                message_data['media_url'] = msg.media_url
        else:
            message_data['media_url'] = None
        
        result.append(message_data)
    
    return result


def export_folders() -> List[Dict]:
    """Exportiert Ordner."""
    folders = Folder.query.all()
    return [{
        'name': f.name,
        'parent_name': lookup_entity_name('folder', f.parent_id) if f.parent_id else None,
        'created_by_email': lookup_user_email(f.created_by),
        'is_dropbox': f.is_dropbox,
        'share_enabled': f.share_enabled,
        'share_name': f.share_name,
        'share_expires_at': f.share_expires_at.isoformat() if f.share_expires_at else None,
        'space': getattr(f, 'space', 'public'),
        'is_personal_root': getattr(f, 'is_personal_root', False),
        'color': getattr(f, 'color', None),
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
            'folder_name': lookup_entity_name('folder', file.folder_id) if file.folder_id else None,
            'uploaded_by_email': lookup_user_email(file.uploaded_by),
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
            'file_name': lookup_entity_name('file', v.file_id),
            'version_number': v.version_number,
            'file_size': v.file_size,
            'uploaded_by_email': lookup_user_email(v.uploaded_by),
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


def export_public_shares() -> List[Dict]:
    """Exportiert öffentliche Freigabe-Links."""
    from app.models.public_share import PublicShare

    result = []
    for share in PublicShare.query.all():
        entry = {
            'resource_type': share.resource_type,
            'mode': share.mode,
            'token': share.token,
            'enabled': share.enabled,
            'password_hash': share.password_hash,
            'expires_at': share.expires_at.isoformat() if share.expires_at else None,
            'created_by_email': lookup_user_email(share.created_by),
        }
        if share.resource_type == 'file':
            file_obj = lookup_entity('file', share.resource_id)
            if file_obj:
                entry['file_name'] = file_obj.name
                if file_obj.folder_id:
                    entry['folder_name'] = lookup_entity_name('folder', file_obj.folder_id)
        else:
            entry['folder_name'] = lookup_entity_name('folder', share.resource_id)
        result.append(entry)
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
            'created_by_email': lookup_user_email(p.created_by),
            'version_number': p.version_number,
            'visibility': getattr(p, 'visibility', 'public'),
            'team_id': getattr(p, 'team_id', None),
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
        version_data = {
            'page_slug': lookup_entity_name('wiki_page_slug', v.wiki_page_id),
            'version_number': v.version_number,
            'content': v.content,
            'created_by_email': lookup_user_email(v.created_by),
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
    comment_id_to_idx = {c.id: idx for idx, c in enumerate(comments)}
    result = []
    for idx, c in enumerate(comments):
        parent_content_ref = None
        parent_idx = comment_id_to_idx.get(c.parent_id) if c.parent_id else None
        if parent_idx is not None:
            parent_comment = comments[parent_idx]
            parent_content_ref = f"{parent_comment.content_type}:{parent_comment.content_id}:{parent_idx}"

        comment_data = {
            'old_id': idx,  # Index für Referenzierung beim Import
            'content_type': c.content_type,
            'content_id': c.content_id,
            'content': c.content,
            'author_email': lookup_user_email(c.author_id),
            'parent_content_ref': parent_content_ref,  # Referenz zum Parent-Kommentar
            'created_at': c.created_at.isoformat() if c.created_at else None,
            'updated_at': c.updated_at.isoformat() if c.updated_at else None
        }

        if c.content_type == 'file':
            file_name = lookup_entity_name('file', c.content_id)
            if file_name:
                comment_data['content_reference'] = f"file:{file_name}"
        elif c.content_type == 'wiki':
            wiki_slug = lookup_entity_name('wiki_page_slug', c.content_id)
            if wiki_slug:
                comment_data['content_reference'] = f"wiki:{wiki_slug}"

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
        comment_idx = comment_to_idx.get(m.comment_id)
        if comment_idx is None:
            continue
        comment = all_comments[comment_idx]
        mention_data = {
            'comment_content_ref': f"{comment.content_type}:{comment.content_id}:{comment_idx}",
            'user_email': lookup_user_email(m.user_id),
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
        'created_by_email': lookup_user_email(f.created_by),
        'created_at': f.created_at.isoformat() if f.created_at else None,
        'updated_at': f.updated_at.isoformat() if f.updated_at else None
    } for f in folders]


def export_products() -> List[Dict]:
    """Exportiert Produkte."""
    products = Product.query.all()
    result = []
    
    for p in products:
        product_data = {
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
            'folder_name': lookup_entity_name('product_folder', p.folder_id) if p.folder_id else None,
            'created_by_email': lookup_user_email(p.created_by),
            'created_at': p.created_at.isoformat() if p.created_at else None,
            'updated_at': p.updated_at.isoformat() if p.updated_at else None
        }
        
        # Exportiere Produktbild als Base64 wenn vorhanden
        if p.image_path:
            try:
                project_root = os.path.dirname(current_app.root_path)
                img_path = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'inventory', 'product_images', p.image_path)
                if os.path.exists(img_path):
                    with open(img_path, 'rb') as f:
                        import base64
                        img_data = f.read()
                        product_data['image_content_base64'] = base64.b64encode(img_data).decode('utf-8')
                        product_data['image_original_name'] = p.image_path
            except Exception as e:
                current_app.logger.error(f"Fehler beim Exportieren des Produktbilds für {p.name}: {str(e)}")
        
        result.append(product_data)
    
    return result


def export_borrow_transactions() -> List[Dict]:
    """Exportiert Ausleihtransaktionen."""
    transactions = BorrowTransaction.query.all()
    return [{
        'transaction_number': t.transaction_number,
        'borrow_group_id': t.borrow_group_id,
        'product_name': lookup_entity_name('product', t.product_id),
        'borrower_email': lookup_user_email(t.borrower_id),
        'borrowed_by_email': lookup_user_email(t.borrowed_by_id),
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
        'created_by_email': lookup_user_email(s.created_by),
        'created_at': s.created_at.isoformat() if s.created_at else None,
        'updated_at': s.updated_at.isoformat() if s.updated_at else None
    } for s in sets]


def export_product_set_items() -> List[Dict]:
    """Exportiert Produktset-Items."""
    items = ProductSetItem.query.all()
    return [{
        'set_name': lookup_entity_name('product_set', i.set_id),
        'product_name': lookup_entity_name('product', i.product_id),
        'quantity': i.quantity
    } for i in items]


def export_product_documents() -> List[Dict]:
    """Exportiert Produktdokumente."""
    documents = ProductDocument.query.all()
    result = []
    for d in documents:
        doc_data = {
            'product_name': lookup_entity_name('product', d.product_id),
            'file_name': d.file_name,
            'file_type': d.file_type,
            'file_size': d.file_size,
            'manual_id': d.manual_id,
            'manual_title': lookup_entity_name('manual', d.manual_id) if d.manual_id else None,
            'uploaded_by_email': lookup_user_email(d.uploaded_by),
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
        'user_email': lookup_user_email(f.user_id),
        'name': f.name,
        'filter_data': f.filter_data,
        'created_at': f.created_at.isoformat() if f.created_at else None
    } for f in filters]


def export_product_favorites() -> List[Dict]:
    """Exportiert Produktfavoriten."""
    favorites = ProductFavorite.query.all()
    return [{
        'user_email': lookup_user_email(f.user_id),
        'product_name': lookup_entity_name('product', f.product_id),
        'created_at': f.created_at.isoformat() if f.created_at else None
    } for f in favorites]


def export_inventories() -> List[Dict]:
    """Exportiert Inventuren."""
    inventories = Inventory.query.all()
    return [{
        'name': i.name,
        'description': i.description,
        'status': i.status,
        'started_by_email': lookup_user_email(i.started_by),
        'started_at': i.started_at.isoformat() if i.started_at else None,
        'completed_at': i.completed_at.isoformat() if i.completed_at else None,
        'created_at': i.created_at.isoformat() if i.created_at else None,
        'updated_at': i.updated_at.isoformat() if i.updated_at else None
    } for i in inventories]


def export_inventory_items() -> List[Dict]:
    """Exportiert Inventur-Items."""
    items = InventoryItem.query.all()
    return [{
        'inventory_name': lookup_entity_name('inventory', i.inventory_id),
        'product_name': lookup_entity_name('product', i.product_id),
        'checked': i.checked,
        'notes': i.notes,
        'location_changed': i.location_changed,
        'new_location': i.new_location,
        'condition_changed': i.condition_changed,
        'new_condition': i.new_condition,
        'checked_by_email': lookup_user_email(i.checked_by),
        'checked_at': i.checked_at.isoformat() if i.checked_at else None,
        'created_at': i.created_at.isoformat() if i.created_at else None,
        'updated_at': i.updated_at.isoformat() if i.updated_at else None
    } for i in items]
