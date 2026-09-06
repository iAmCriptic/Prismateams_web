"""Import emails, calendar events, manuals, chats, and credentials."""

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
from app.utils.backup_lookups import lookup_team_name, lookup_user_email, objects_by_name
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

from app.utils.backup.helpers import _ensure_local_main_chat, _message_fingerprint

def import_emails(emails_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None) -> Dict[str, int]:
    """Importiert E-Mails und gibt ein Mapping von message_id zu neuer ID zurück."""
    email_map = {}  # message_id -> neue_id
    
    for e_data in emails_data:
        sent_by_user_id = None
        if e_data.get('sent_by_user_email'):
            sent_by_user_id = user_map.get(e_data['sent_by_user_email'])
            # Fallback: Wenn Benutzer nicht gefunden wird, verwende current_user
            if sent_by_user_id is None and current_user_id:
                sent_by_user_id = current_user_id
        
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


def import_email_permissions(permissions_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert E-Mail-Berechtigungen."""
    for p_data in permissions_data:
        user_email = p_data.get('user_email')
        if not user_email:
            continue
        
        # Fallback: Wenn Benutzer nicht gefunden wird, verwende current_user
        if user_email not in user_map:
            if current_user_id:
                user_id = current_user_id
            else:
                continue
        else:
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


def import_calendar_events(events_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None, calendar_map: Optional[Dict[int, int]] = None) -> Dict[str, int]:
    """Importiert Kalender-Termine und gibt ein Mapping von Titel zu neuer ID zurück."""
    event_map = {}  # event_title -> neue_id
    calendar_map = calendar_map or {}
    
    for e_data in events_data:
        created_by_email = e_data.get('created_by_email')
        if not created_by_email:
            if current_user_id:
                created_by_id = current_user_id
            else:
                continue
        elif created_by_email not in user_map:
            # Fallback: Wenn Benutzer nicht gefunden wird, verwende current_user
            if current_user_id:
                created_by_id = current_user_id
            else:
                continue
        else:
            created_by_id = user_map[created_by_email]
        
        # Prüfe ob Event bereits existiert (nach Titel, Startzeit und Ersteller)
        existing = CalendarEvent.query.filter_by(
            title=e_data['title'],
            start_time=datetime.fromisoformat(e_data['start_time']),
            created_by=created_by_id
        ).first()
        
        if existing:
            event_map[e_data['title']] = existing.id
            if e_data.get('calendar_export_id') is not None and calendar_map.get(e_data['calendar_export_id']):
                existing.calendar_id = calendar_map[e_data['calendar_export_id']]
        else:
            event = CalendarEvent(
                title=e_data['title'],
                description=e_data.get('description'),
                start_time=datetime.fromisoformat(e_data['start_time']),
                end_time=datetime.fromisoformat(e_data['end_time']),
                location=e_data.get('location'),
                created_by=created_by_id
            )
            if e_data.get('event_color'):
                event.event_color = e_data['event_color']
            if e_data.get('recurrence_type'):
                event.recurrence_type = e_data['recurrence_type']
            if e_data.get('recurrence_interval') is not None:
                event.recurrence_interval = e_data['recurrence_interval']
            if e_data.get('recurrence_days'):
                event.recurrence_days = e_data['recurrence_days']
            if e_data.get('recurrence_end_date'):
                event.recurrence_end_date = datetime.fromisoformat(e_data['recurrence_end_date'])
            if e_data.get('is_public') is not None:
                event.is_public = bool(e_data['is_public'])
            if e_data.get('calendar_export_id') is not None and calendar_map.get(e_data['calendar_export_id']):
                event.calendar_id = calendar_map[e_data['calendar_export_id']]
            db.session.add(event)
            db.session.flush()
            event_map[e_data['title']] = event.id
    
    return event_map


def import_event_participants(participants_data: List[Dict], event_map: Dict[str, int], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Event-Teilnehmer."""
    for p_data in participants_data:
        event_title = p_data.get('event_title')
        user_email = p_data.get('user_email')
        
        if not event_title or event_title not in event_map:
            continue
        if not user_email:
            continue
        
        event_id = event_map[event_title]
        
        # Fallback: Wenn Benutzer nicht gefunden wird, verwende current_user
        if user_email not in user_map:
            if current_user_id:
                user_id = current_user_id
            else:
                continue
        else:
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


def import_manuals(manuals_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Handbücher (inkl. PDF-Dateien)."""
    for m_data in manuals_data:
        uploaded_by_email = m_data.get('uploaded_by_email')
        if not uploaded_by_email:
            if current_user_id:
                uploaded_by_id = current_user_id
            else:
                continue
        elif uploaded_by_email not in user_map:
            # Fallback: Wenn Benutzer nicht gefunden wird, verwende current_user
            if current_user_id:
                uploaded_by_id = current_user_id
            else:
                continue
        else:
            uploaded_by_id = user_map[uploaded_by_email]
        
        # Prüfe ob Manual bereits existiert (nach Titel und Uploader)
        existing = Manual.query.filter_by(
            title=m_data.get('title'),
            uploaded_by=uploaded_by_id
        ).first()
        
        if existing:
            # Aktualisiere bestehendes Manual
            existing.filename = m_data.get('filename', existing.filename)
            existing.file_size = m_data.get('file_size', existing.file_size)
            if m_data.get('visibility'):
                existing.visibility = m_data['visibility']
            if 'team_id' in m_data:
                existing.team_id = m_data.get('team_id')
        else:
            # Neues Manual
            manual = Manual(
                title=m_data['title'],
                filename=m_data.get('filename', m_data['title'] + '.pdf'),
                file_size=m_data.get('file_size', 0),
                uploaded_by=uploaded_by_id,
                visibility=m_data.get('visibility') or 'public',
                team_id=m_data.get('team_id'),
            )
            
            # Importiere PDF-Datei wenn vorhanden
            if m_data.get('file_content_base64'):
                try:
                    import base64
                    from werkzeug.utils import secure_filename
                    
                    file_content = base64.b64decode(m_data['file_content_base64'])
                    original_name = m_data.get('file_original_name', m_data.get('filename', 'manual.pdf'))
                    
                    # Erstelle Dateiname mit Timestamp
                    if '.' in original_name:
                        ext = os.path.splitext(original_name)[1]
                        base_name = os.path.splitext(original_name)[0]
                    else:
                        ext = '.pdf'
                        base_name = 'manual'
                    
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"{timestamp}_{secure_filename(base_name)}{ext}"
                    
                    # Speichere Datei
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'manuals')
                    os.makedirs(upload_dir, exist_ok=True)
                    file_path = os.path.join(upload_dir, filename)
                    
                    with open(file_path, 'wb') as f:
                        f.write(file_content)
                    
                    manual.file_path = file_path
                    manual.filename = filename
                    manual.file_size = len(file_content)
                except Exception as e:
                    current_app.logger.error(f"Fehler beim Importieren des Handbuchs {m_data['title']}: {str(e)}")
                    # Erstelle trotzdem Manual-Eintrag ohne Datei
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'manuals')
                    os.makedirs(upload_dir, exist_ok=True)
                    manual.file_path = os.path.join(upload_dir, m_data.get('filename', 'manual.pdf'))
            else:
                # Keine Datei vorhanden, erstelle trotzdem Eintrag
                project_root = os.path.dirname(current_app.root_path)
                upload_dir = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'manuals')
                os.makedirs(upload_dir, exist_ok=True)
                manual.file_path = os.path.join(upload_dir, m_data.get('filename', 'manual.pdf'))
            
            if m_data.get('uploaded_at'):
                manual.uploaded_at = datetime.fromisoformat(m_data['uploaded_at'])
            
            db.session.add(manual)


def import_chats(chats_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None) -> Dict[str, int]:
    """Importiert Chats. Hauptchat aus Backup wird IMMER auf den lokalen Hauptchat gemappt."""
    chat_map = {}  # chat_name (backup) -> lokale id
    local_main = _ensure_local_main_chat(current_user_id)
    chats_by_name = {}
    chats_by_key = {}
    for chat in Chat.query.all():
        chats_by_name.setdefault(chat.name, chat)
        chats_by_key[(chat.name, bool(chat.is_direct_message))] = chat
    
    for c_data in chats_data:
        name = c_data.get('name')
        if not name:
            continue

        # Kritisch: jeder Main-Chat aus dem Backup landet im bestehenden Hauptchat
        if c_data.get('is_main_chat'):
            chat_map[name] = local_main.id
            if c_data.get('description') and not local_main.description:
                local_main.description = c_data.get('description')
            continue

        # DMs / Gruppen: nicht mit dem Hauptchat-Namen kollidieren
        if name == local_main.name or name in {'Haupt-Chat', 'Team Chat', 'Team-Chat'}:
            # Namenskollision ohne Main-Flag → unter anderem Namen anlegen
            name_key = name
            existing = chats_by_key.get((name, bool(c_data.get('is_direct_message', False))))
            if existing and existing.id != local_main.id:
                chat_map[name_key] = existing.id
                continue
            # Fallback: Unique-Suffix
            created_by_email = c_data.get('created_by_email')
            created_by_id = user_map.get(created_by_email, current_user_id) if created_by_email else current_user_id
            if not created_by_id:
                continue
            chat = Chat(
                name=f"{name} (Import)",
                description=c_data.get('description'),
                is_main_chat=False,
                is_direct_message=c_data.get('is_direct_message', False),
                created_by=created_by_id,
            )
            db.session.add(chat)
            db.session.flush()
            chat_map[name_key] = chat.id
            continue

        created_by_email = c_data.get('created_by_email')
        if not created_by_email:
            created_by_id = current_user_id
        elif created_by_email not in user_map:
            if current_user_id:
                created_by_id = current_user_id
            else:
                continue
        else:
            created_by_id = user_map[created_by_email]
        
        existing = chats_by_name.get(name)
        if existing:
            # Nie auf den Hauptchat mappen, wenn Backup-Chat kein Main ist
            if existing.is_main_chat and not c_data.get('is_main_chat'):
                created_by_id = created_by_id or current_user_id
                if not created_by_id:
                    continue
                chat = Chat(
                    name=f"{name} (Import)",
                    description=c_data.get('description'),
                    is_main_chat=False,
                    is_direct_message=c_data.get('is_direct_message', False),
                    created_by=created_by_id,
                )
                db.session.add(chat)
                db.session.flush()
                chat_map[name] = chat.id
            else:
                chat_map[name] = existing.id
        else:
            chat = Chat(
                name=name,
                description=c_data.get('description'),
                is_main_chat=False,
                is_direct_message=c_data.get('is_direct_message', False),
                created_by=created_by_id
            )
            
            if c_data.get('group_avatar_content_base64'):
                try:
                    import base64
                    from werkzeug.utils import secure_filename
                    
                    file_content = base64.b64decode(c_data['group_avatar_content_base64'])
                    original_name = c_data.get('group_avatar_original_name', 'avatar.png')
                    
                    if '.' in original_name:
                        ext = os.path.splitext(original_name)[1]
                        base_name = os.path.splitext(original_name)[0]
                    else:
                        ext = '.png'
                        base_name = 'avatar'
                    
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"{timestamp}_{secure_filename(base_name)}{ext}"
                    
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'chat_avatars')
                    os.makedirs(upload_dir, exist_ok=True)
                    file_path = os.path.join(upload_dir, filename)
                    
                    with open(file_path, 'wb') as f:
                        f.write(file_content)
                    
                    chat.group_avatar = filename
                except Exception as e:
                    current_app.logger.error(f"Fehler beim Importieren des Chat-Avatars für {c_data['name']}: {str(e)}")
            
            if c_data.get('created_at'):
                chat.created_at = datetime.fromisoformat(c_data['created_at'])
            if c_data.get('updated_at'):
                chat.updated_at = datetime.fromisoformat(c_data['updated_at'])
            
            db.session.add(chat)
            db.session.flush()
            chat_map[name] = chat.id

    from app.models.team import Team
    for c_data in chats_data:
        team_name = c_data.get('team_name')
        chat_name = c_data.get('name')
        if not team_name or not chat_name or chat_name not in chat_map:
            continue
        team = Team.query.filter_by(name=team_name).first()
        if not team:
            continue
        chat = Chat.query.get(chat_map[chat_name])
        if chat and not chat.is_main_chat and not chat.team_id:
            existing_bound = Chat.query.filter_by(team_id=team.id).first()
            if existing_bound:
                continue
            chat.team_id = team.id
    
    return chat_map


def import_chat_members(members_data: List[Dict], chat_map: Dict[str, int], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Chat-Mitglieder."""
    for m_data in members_data:
        chat_name = m_data.get('chat_name')
        user_email = m_data.get('user_email')
        
        if not chat_name or chat_name not in chat_map:
            continue
        if not user_email:
            continue
        
        chat_id = chat_map[chat_name]
        
        # Fallback: Wenn Benutzer nicht gefunden wird, verwende current_user
        if user_email not in user_map:
            if current_user_id:
                user_id = current_user_id
            else:
                continue
        else:
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


def import_chat_messages(messages_data: List[Dict], chat_map: Dict[str, int], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Chat-Nachrichten (inkl. Media); skippt Duplikate per Fingerprint."""
    # Vorhandene Fingerprints pro Chat vorladen
    existing_fps: Dict[int, Set[str]] = {}

    for msg_data in messages_data:
        chat_name = msg_data.get('chat_name')
        sender_email = msg_data.get('sender_email')
        
        if not chat_name or chat_name not in chat_map:
            continue
        if not sender_email:
            continue
        
        chat_id = chat_map[chat_name]
        
        if sender_email not in user_map:
            if current_user_id:
                sender_id = current_user_id
            else:
                continue
        else:
            sender_id = user_map[sender_email]

        created_at = None
        if msg_data.get('created_at'):
            try:
                created_at = datetime.fromisoformat(msg_data['created_at'])
            except ValueError:
                created_at = None

        media_name = msg_data.get('media_original_name') or msg_data.get('media_url')
        fp = _message_fingerprint(sender_id, msg_data.get('content'), created_at, media_name)

        if chat_id not in existing_fps:
            fps = set()
            for existing_msg in ChatMessage.query.filter_by(chat_id=chat_id).all():
                fps.add(_message_fingerprint(
                    existing_msg.sender_id,
                    existing_msg.content,
                    existing_msg.created_at,
                    existing_msg.media_url,
                ))
            existing_fps[chat_id] = fps

        if fp in existing_fps[chat_id]:
            continue
        
        message = ChatMessage(
            chat_id=chat_id,
            sender_id=sender_id,
            content=msg_data.get('content'),
            message_type=msg_data.get('message_type', 'text'),
            is_deleted=msg_data.get('is_deleted', False)
        )
        
        if msg_data.get('media_content_base64'):
            try:
                import base64
                from werkzeug.utils import secure_filename
                
                file_content = base64.b64decode(msg_data['media_content_base64'])
                original_name = msg_data.get('media_original_name', 'media')
                
                if '.' in original_name:
                    ext = os.path.splitext(original_name)[1]
                    base_name = os.path.splitext(original_name)[0]
                else:
                    ext = ''
                    base_name = 'media'
                
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                filename = f"{timestamp}_{secure_filename(base_name)}{ext}"
                
                project_root = os.path.dirname(current_app.root_path)
                upload_dir = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'chat_media')
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, filename)
                
                with open(file_path, 'wb') as f:
                    f.write(file_content)
                
                message.media_url = filename
            except Exception as e:
                current_app.logger.error(f"Fehler beim Importieren der Media-Datei für Nachricht: {str(e)}")
                message.media_url = msg_data.get('media_url')
        else:
            message.media_url = msg_data.get('media_url')
        
        if created_at:
            message.created_at = created_at
        if msg_data.get('edited_at'):
            message.edited_at = datetime.fromisoformat(msg_data['edited_at'])
        
        db.session.add(message)
        existing_fps[chat_id].add(fp)


def import_credentials(credentials_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Zugangsdaten (verschlüsselt neu)."""
    key = get_encryption_key()
    
    for c_data in credentials_data:
        created_by_email = c_data.get('created_by_email')
        if not created_by_email:
            if current_user_id:
                created_by_id = current_user_id
            else:
                continue
        elif created_by_email not in user_map:
            # Fallback: Wenn Benutzer nicht gefunden wird, verwende current_user
            if current_user_id:
                created_by_id = current_user_id
            else:
                continue
        else:
            created_by_id = user_map[created_by_email]
        
        # Prüfe ob Credential bereits existiert (nach URL, Username und Ersteller)
        existing = Credential.query.filter_by(
            website_url=c_data.get('website_url'),
            username=c_data.get('username'),
            created_by=created_by_id
        ).first()
        
        if existing:
            # Aktualisiere bestehendes Credential
            existing.website_name = c_data['website_name']
            existing.notes = c_data.get('notes')
            existing.favicon_url = c_data.get('favicon_url')
            if c_data.get('visibility'):
                existing.visibility = c_data['visibility']
            if 'team_id' in c_data:
                existing.team_id = c_data.get('team_id')
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
                created_by=created_by_id,
                visibility=c_data.get('visibility') or 'public',
                team_id=c_data.get('team_id'),
            )
            if c_data.get('password'):
                credential.set_password(c_data['password'], key)
            db.session.add(credential)
