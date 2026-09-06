"""Import settings, whitelist, users, and notification settings."""

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

def import_settings(settings_data: List[Dict]):
    """Importiert System-Einstellungen."""
    for s_data in settings_data:
        # Spezielle Behandlung für portal_logo: Datei wiederherstellen
        if s_data['key'] == 'portal_logo' and s_data.get('file_content_base64'):
            try:
                import base64
                from werkzeug.utils import secure_filename
                
                # Dekodiere Base64-Daten
                file_content = base64.b64decode(s_data['file_content_base64'])
                
                # Erstelle Dateiname mit Timestamp
                original_name = s_data.get('file_original_name', s_data.get('value', 'logo.png'))
                # Extrahiere Dateierweiterung
                if '.' in original_name:
                    ext = os.path.splitext(original_name)[1]
                    base_name = os.path.splitext(original_name)[0]
                    # Entferne mögliche Timestamp-Präfixe
                    if '_' in base_name:
                        parts = base_name.split('_')
                        if len(parts) >= 3 and parts[0] == 'portal' and parts[1] == 'logo':
                            # Verwende nur den letzten Teil als Basis
                            base_name = '_'.join(parts[2:])
                else:
                    ext = '.png'
                    base_name = 'logo'
                
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                filename = f"portal_logo_{timestamp}_{secure_filename(base_name)}{ext}"
                
                # Speichere Datei im system-Verzeichnis
                project_root = os.path.dirname(current_app.root_path)
                upload_dir = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'system')
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, filename)
                
                with open(file_path, 'wb') as f:
                    f.write(file_content)
                
                # Aktualisiere Setting mit neuem Dateinamen
                existing = SystemSettings.query.filter_by(key='portal_logo').first()
                if existing:
                    # Lösche altes Logo falls vorhanden
                    old_logo = existing.value
                    if old_logo and old_logo != filename:
                        try:
                            old_path = os.path.join(upload_dir, old_logo)
                            if os.path.exists(old_path):
                                os.remove(old_path)
                        except Exception as e:
                            current_app.logger.warning(f"Konnte altes Logo nicht löschen: {str(e)}")
                    existing.value = filename
                    if 'description' in s_data:
                        existing.description = s_data.get('description')
                else:
                    setting = SystemSettings(
                        key='portal_logo',
                        value=filename,
                        description=s_data.get('description', 'Portalslogo')
                    )
                    db.session.add(setting)
                
                current_app.logger.info(f"Portal-Logo erfolgreich importiert: {filename}")
            except Exception as e:
                current_app.logger.error(f"Fehler beim Importieren des Portal-Logos: {str(e)}")
                # Fallback: Verwende nur den Dateinamen ohne Datei
                existing = SystemSettings.query.filter_by(key='portal_logo').first()
                if existing:
                    existing.value = s_data.get('value')
                else:
                    setting = SystemSettings(
                        key='portal_logo',
                        value=s_data.get('value'),
                        description=s_data.get('description', 'Portalslogo')
                    )
                    db.session.add(setting)
        else:
            # Normale Settings ohne Dateien
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
            
            # Importiere Profilbild wenn vorhanden
            if u_data.get('profile_picture_content_base64'):
                try:
                    import base64
                    from werkzeug.utils import secure_filename
                    
                    file_content = base64.b64decode(u_data['profile_picture_content_base64'])
                    original_name = u_data.get('profile_picture_original_name', u_data.get('profile_picture', 'profile.png'))
                    
                    # Erstelle Dateiname mit Timestamp
                    if '.' in original_name:
                        ext = os.path.splitext(original_name)[1]
                        base_name = os.path.splitext(original_name)[0]
                        # Entferne mögliche Timestamp-Präfixe
                        if '_' in base_name:
                            parts = base_name.split('_')
                            if len(parts) >= 2:
                                base_name = '_'.join(parts[1:])
                    else:
                        ext = '.png'
                        base_name = 'profile'
                    
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"{existing.id}_{timestamp}_{secure_filename(base_name)}{ext}"
                    
                    # Speichere Datei
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'profile_pics')
                    os.makedirs(upload_dir, exist_ok=True)
                    file_path = os.path.join(upload_dir, filename)
                    
                    with open(file_path, 'wb') as f:
                        f.write(file_content)
                    
                    existing.profile_picture = filename
                except Exception as e:
                    current_app.logger.error(f"Fehler beim Importieren des Profilbilds für {u_data['email']}: {str(e)}")
                    existing.profile_picture = u_data.get('profile_picture')
            else:
                existing.profile_picture = u_data.get('profile_picture')
            
            existing.accent_color = u_data.get('accent_color', '#0d6efd')
            existing.accent_gradient = u_data.get('accent_gradient')
            existing.dark_mode = u_data.get('dark_mode', False)
            existing.notifications_enabled = u_data.get('notifications_enabled', True)
            existing.chat_notifications = u_data.get('chat_notifications', True)
            existing.email_notifications = u_data.get('email_notifications', True)
            existing.can_borrow = u_data.get('can_borrow', True)
            if hasattr(existing, 'is_super_admin'):
                existing.is_super_admin = u_data.get('is_super_admin', existing.is_super_admin)
            if hasattr(existing, 'is_guest'):
                existing.is_guest = u_data.get('is_guest', False)
            if hasattr(existing, 'guest_username'):
                existing.guest_username = u_data.get('guest_username')
            if hasattr(existing, 'has_full_access'):
                existing.has_full_access = u_data.get('has_full_access', False)
            if hasattr(existing, 'oled_mode'):
                existing.oled_mode = u_data.get('oled_mode', False)
            if hasattr(existing, 'language'):
                existing.language = u_data.get('language', existing.language or 'de')
            if hasattr(existing, 'preferred_layout'):
                existing.preferred_layout = u_data.get('preferred_layout', existing.preferred_layout or 'auto')
            if hasattr(existing, 'must_change_password'):
                existing.must_change_password = u_data.get('must_change_password', False)
            if u_data.get('guest_expires_at') and hasattr(existing, 'guest_expires_at'):
                existing.guest_expires_at = datetime.fromisoformat(u_data['guest_expires_at'])
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
                accent_color=u_data.get('accent_color', '#0d6efd'),
                accent_gradient=u_data.get('accent_gradient'),
                dark_mode=u_data.get('dark_mode', False),
                notifications_enabled=u_data.get('notifications_enabled', True),
                chat_notifications=u_data.get('chat_notifications', True),
                email_notifications=u_data.get('email_notifications', True),
                can_borrow=u_data.get('can_borrow', True)
            )
            if hasattr(user, 'is_super_admin'):
                user.is_super_admin = u_data.get('is_super_admin', False)
            if hasattr(user, 'is_guest'):
                user.is_guest = u_data.get('is_guest', False)
            if hasattr(user, 'guest_username'):
                user.guest_username = u_data.get('guest_username')
            if hasattr(user, 'has_full_access'):
                user.has_full_access = u_data.get('has_full_access', False)
            if hasattr(user, 'oled_mode'):
                user.oled_mode = u_data.get('oled_mode', False)
            if hasattr(user, 'language'):
                user.language = u_data.get('language', 'de')
            if hasattr(user, 'preferred_layout'):
                user.preferred_layout = u_data.get('preferred_layout', 'auto')
            if hasattr(user, 'must_change_password'):
                user.must_change_password = u_data.get('must_change_password', False)
            if u_data.get('guest_expires_at') and hasattr(user, 'guest_expires_at'):
                user.guest_expires_at = datetime.fromisoformat(u_data['guest_expires_at'])
            # Falls kein Passwort-Hash vorhanden, temporäres Passwort setzen
            if not user.password_hash:
                user.set_password('TEMPORARY_PASSWORD_RESET_REQUIRED')
            db.session.add(user)
            db.session.flush()  # Um die ID zu bekommen
            
            # Importiere Profilbild wenn vorhanden
            if u_data.get('profile_picture_content_base64'):
                try:
                    import base64
                    from werkzeug.utils import secure_filename
                    
                    file_content = base64.b64decode(u_data['profile_picture_content_base64'])
                    original_name = u_data.get('profile_picture_original_name', u_data.get('profile_picture', 'profile.png'))
                    
                    # Erstelle Dateiname mit Timestamp
                    if '.' in original_name:
                        ext = os.path.splitext(original_name)[1]
                        base_name = os.path.splitext(original_name)[0]
                        # Entferne mögliche Timestamp-Präfixe
                        if '_' in base_name:
                            parts = base_name.split('_')
                            if len(parts) >= 2:
                                base_name = '_'.join(parts[1:])
                    else:
                        ext = '.png'
                        base_name = 'profile'
                    
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"{user.id}_{timestamp}_{secure_filename(base_name)}{ext}"
                    
                    # Speichere Datei
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'profile_pics')
                    os.makedirs(upload_dir, exist_ok=True)
                    file_path = os.path.join(upload_dir, filename)
                    
                    with open(file_path, 'wb') as f:
                        f.write(file_content)
                    
                    user.profile_picture = filename
                except Exception as e:
                    current_app.logger.error(f"Fehler beim Importieren des Profilbilds für {u_data['email']}: {str(e)}")
                    user.profile_picture = u_data.get('profile_picture')
            else:
                user.profile_picture = u_data.get('profile_picture')
            
            user_map[u_data['email']] = user.id
    
    return user_map


def import_notification_settings(settings_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Notification-Einstellungen."""
    for s_data in settings_data:
        user_email = s_data.get('user_email')
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
            existing.booking_notifications_enabled = s_data.get('booking_notifications_enabled', True)
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
                booking_notifications_enabled=s_data.get('booking_notifications_enabled', True),
                reminder_times=s_data.get('reminder_times')
            )
            db.session.add(setting)
