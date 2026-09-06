"""Import files, wiki, and comments."""

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

def import_folders(folders_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None) -> Dict[str, int]:
    """Importiert Ordner und gibt ein Mapping von Ordner-Name zu neuer ID zurück."""
    folder_map = {}  # folder_name -> neue_id
    
    # Sortiere nach Hierarchie (Root-Ordner zuerst)
    sorted_folders = sorted(folders_data, key=lambda x: (x.get('parent_name') is not None, x.get('name', '')))
    
    for f_data in sorted_folders:
        created_by_email = f_data.get('created_by_email')
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
        parent_id = None
        if f_data.get('parent_name') and f_data['parent_name'] in folder_map:
            parent_id = folder_map[f_data['parent_name']]
        
        # Prüfe ob Ordner bereits existiert (nach Name, Parent und Ersteller)
        existing = Folder.query.filter_by(
            name=f_data.get('name'),
            parent_id=parent_id,
            created_by=created_by_id
        ).first()
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
            if hasattr(folder, 'space'):
                folder.space = f_data.get('space') or 'public'
            if hasattr(folder, 'is_personal_root'):
                folder.is_personal_root = bool(f_data.get('is_personal_root'))
            if hasattr(folder, 'color') and f_data.get('color'):
                folder.color = f_data['color']
            db.session.add(folder)
            db.session.flush()
            folder_map[f_data['name']] = folder.id
        if existing:
            if hasattr(existing, 'space') and f_data.get('space'):
                existing.space = f_data['space']
            if hasattr(existing, 'is_personal_root') and f_data.get('is_personal_root') is not None:
                existing.is_personal_root = bool(f_data.get('is_personal_root'))
    
    return folder_map


def import_public_shares(shares_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert öffentliche Freigabe-Links."""
    from app.models.public_share import PublicShare
    from app.utils.public_share import sync_legacy_share_flags

    for s_data in shares_data:
        resource_type = s_data.get('resource_type')
        resource = None
        if resource_type == 'file' and s_data.get('file_name'):
            folder_id = None
            if s_data.get('folder_name'):
                folder = Folder.query.filter_by(name=s_data['folder_name']).first()
                folder_id = folder.id if folder else None
            resource = File.query.filter_by(name=s_data['file_name'], folder_id=folder_id, is_current=True).first()
        elif resource_type == 'folder' and s_data.get('folder_name'):
            resource = Folder.query.filter_by(name=s_data['folder_name']).first()

        if not resource:
            continue

        created_by_email = s_data.get('created_by_email')
        created_by_id = user_map.get(created_by_email) if created_by_email else current_user_id
        if not created_by_id:
            continue

        share = PublicShare.query.filter_by(
            resource_type=resource_type,
            resource_id=resource.id,
            mode=s_data.get('mode', 'edit'),
        ).first()
        if not share:
            share = PublicShare(
                resource_type=resource_type,
                resource_id=resource.id,
                mode=s_data.get('mode', 'edit'),
                token=s_data.get('token') or secrets.token_urlsafe(32),
                created_by=created_by_id,
            )
            db.session.add(share)

        share.enabled = s_data.get('enabled', True)
        share.password_hash = s_data.get('password_hash')
        if s_data.get('expires_at'):
            share.expires_at = datetime.fromisoformat(s_data['expires_at'])
        sync_legacy_share_flags(resource_type, resource)


def import_files(files_data: List[Dict], folder_map: Dict[str, int], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Dateien."""
    for f_data in files_data:
        uploaded_by_email = f_data.get('uploaded_by_email')
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
        folder_id = None
        if f_data.get('folder_name') and f_data['folder_name'] in folder_map:
            folder_id = folder_map[f_data['folder_name']]
        
        # Prüfe ob Datei bereits existiert (nach Name, Ordner und Uploader)
        existing = File.query.filter_by(
            name=f_data.get('name'),
            folder_id=folder_id,
            uploaded_by=uploaded_by_id
        ).first()
        
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


def import_file_versions(versions_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Datei-Versionen."""
    for v_data in versions_data:
        uploaded_by_email = v_data.get('uploaded_by_email')
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
    existing_by_name = objects_by_name(WikiCategory)

    for c_data in categories_data:
        existing = existing_by_name.get(c_data['name'])
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
            existing_by_name[c_data['name']] = category
            category_map[c_data['name']] = category.id
    
    return category_map


def import_wiki_tags(tags_data: List[Dict]) -> Dict[str, int]:
    """Importiert Wiki-Tags und gibt ein Mapping von Name zu neuer ID zurück."""
    tag_map = {}  # name -> neue_id
    existing_by_name = objects_by_name(WikiTag)

    for t_data in tags_data:
        existing = existing_by_name.get(t_data['name'])
        if existing:
            tag_map[t_data['name']] = existing.id
        else:
            # Neuer Tag
            tag = WikiTag(name=t_data['name'])
            db.session.add(tag)
            db.session.flush()
            existing_by_name[t_data['name']] = tag
            tag_map[t_data['name']] = tag.id
    
    return tag_map


def import_wiki_pages(pages_data: List[Dict], category_map: Dict[str, int], tag_map: Dict[str, int], user_map: Dict[str, int], current_user_id: Optional[int] = None) -> Dict[str, int]:
    """Importiert Wiki-Seiten und gibt ein Mapping von Slug zu neuer ID zurück."""
    page_map = {}  # slug -> neue_id
    
    for p_data in pages_data:
        created_by_email = p_data.get('created_by_email')
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
            if p_data.get('visibility'):
                existing.visibility = p_data['visibility']
            if 'team_id' in p_data:
                existing.team_id = p_data.get('team_id')
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
                version_number=p_data.get('version_number', 1),
                visibility=p_data.get('visibility') or 'public',
                team_id=p_data.get('team_id'),
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


def import_wiki_page_versions(versions_data: List[Dict], page_map: Dict[str, int], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Wiki-Seiten-Versionen."""
    for v_data in versions_data:
        page_slug = v_data.get('page_slug')
        if not page_slug or page_slug not in page_map:
            continue
        
        created_by_email = v_data.get('created_by_email')
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
        
        page_id = page_map[page_slug]
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


def import_comments(comments_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None) -> Dict[str, int]:
    """Importiert Kommentare und gibt ein Mapping von content_ref zu neuer ID zurück."""
    comment_map = {}  # content_ref -> neue_id
    
    # Erste Runde: Importiere alle Kommentare ohne Parent-Referenzen
    for c_data in comments_data:
        author_email = c_data.get('author_email')
        if not author_email:
            if current_user_id:
                author_id = current_user_id
            else:
                continue
        elif author_email not in user_map:
            # Fallback: Wenn Benutzer nicht gefunden wird, verwende current_user
            if current_user_id:
                author_id = current_user_id
            else:
                continue
        else:
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


def import_comment_mentions(mentions_data: List[Dict], comment_map: Dict[str, int], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Kommentar-Mentions."""
    for m_data in mentions_data:
        comment_content_ref = m_data.get('comment_content_ref')
        if not comment_content_ref or comment_content_ref not in comment_map:
            continue
        
        user_email = m_data.get('user_email')
        if not user_email:
            continue
        
        comment_id = comment_map[comment_content_ref]
        
        # Fallback: Wenn Benutzer nicht gefunden wird, verwende current_user
        if user_email not in user_map:
            if current_user_id:
                user_id = current_user_id
            else:
                continue
        else:
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
