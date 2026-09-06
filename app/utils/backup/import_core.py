"""Backup import orchestrator."""

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


from app.utils.backup.constants import SUPPORTED_BACKUP_VERSIONS, _category_selected
from app.utils.backup.import_comms import (
    import_calendar_events,
    import_chat_members,
    import_chat_messages,
    import_chats,
    import_credentials,
    import_email_attachments,
    import_email_permissions,
    import_emails,
    import_event_participants,
    import_manuals,
)
from app.utils.backup.import_content import (
    import_comment_mentions,
    import_comments,
    import_file_versions,
    import_files,
    import_folders,
    import_public_shares,
    import_wiki_categories,
    import_wiki_page_versions,
    import_wiki_pages,
    import_wiki_tags,
)
from app.utils.backup.import_identity import (
    import_notification_settings,
    import_settings,
    import_users,
    import_whitelist,
)
from app.utils.backup.import_inventory import (
    import_borrow_transactions,
    import_inventories,
    import_inventory_items,
    import_product_documents,
    import_product_favorites,
    import_product_folders,
    import_product_set_items,
    import_product_sets,
    import_products,
    import_saved_filters,
)

def import_backup(file_path: str, categories: List[str], current_user_id: Optional[int] = None) -> Dict:
    """
    Importiert ein Backup der ausgewählten Kategorien.
    
    Args:
        file_path: Pfad zur Backup-Datei
        categories: Liste der zu importierenden Kategorien
        current_user_id: ID des aktuellen Benutzers (für Fallback wenn Benutzer nicht gefunden werden)
    
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
    if backup_data.get('version') not in SUPPORTED_BACKUP_VERSIONS:
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
        
        # user_map IMMER initialisieren (vor allen anderen Imports)
        # Wenn 'users' importiert wird, wird user_map aus import_users() erstellt
        # Wenn 'users' NICHT importiert wird, erstelle user_map aus bestehenden Benutzern in der DB
        user_map = {}  # email -> user_id
        
        # Validierung: Prüfe ob benötigte Abhängigkeiten vorhanden sind
        backup_data_dict = backup_data.get('data', {})
        
        # Warnung wenn Module importiert werden, die Benutzer benötigen, aber keine Benutzer vorhanden sind
        user_dependent_modules = [
            'emails', 'appointments', 'credentials', 'files', 'wiki', 'comments',
            'inventory', 'chats', 'contacts', 'events', 'booking', 'music',
            'media_downloader', 'assessment', 'shortlinks', 'manuals',
        ]
        needs_users = any(_category_selected(categories, cat) for cat in user_dependent_modules)
        
        if needs_users and not _category_selected(categories, 'users'):
            # Prüfe ob Benutzer in der DB existieren
            existing_users = User.query.all()
            if not existing_users and not backup_data_dict.get('users'):
                current_app.logger.warning("Module importiert, die Benutzer benötigen, aber keine Benutzer gefunden. Verwende current_user als Fallback.")
        
        # Benutzer importieren (muss zuerst sein wegen Foreign Keys)
        if _category_selected(categories, 'users'):
            if 'users' in backup_data_dict:
                user_map = import_users(backup_data['data']['users'])
                results['imported'].append('users')
            else:
                # Erstelle user_map aus bestehenden Benutzern in der DB
                existing_users = User.query.all()
                for user in existing_users:
                    user_map[user.email] = user.id
        else:
            # Erstelle user_map aus bestehenden Benutzern in der DB
            existing_users = User.query.all()
            for user in existing_users:
                user_map[user.email] = user.id
        
        # Einstellungen importieren
        if _category_selected(categories, 'settings'):
            if 'settings' in backup_data.get('data', {}):
                import_settings(backup_data['data']['settings'])
                results['imported'].append('settings')
            if 'whitelist' in backup_data.get('data', {}):
                import_whitelist(backup_data['data']['whitelist'])
                results['imported'].append('whitelist')
        
        # Notification Settings importieren (benötigt user_map)
        if _category_selected(categories, 'users'):
            if 'notification_settings' in backup_data.get('data', {}):
                import_notification_settings(backup_data['data']['notification_settings'], user_map, current_user_id)
                results['imported'].append('notification_settings')
            if 'user_module_roles' in backup_data.get('data', {}):
                import_user_module_roles(backup_data['data']['user_module_roles'], user_map, current_user_id)
                results['imported'].append('user_module_roles')
        
        # E-Mails importieren
        if _category_selected(categories, 'emails'):
            if 'emails' in backup_data.get('data', {}):
                email_map = import_emails(backup_data['data']['emails'], user_map, current_user_id)
                results['imported'].append('emails')
            else:
                email_map = {}
            
            if 'email_permissions' in backup_data.get('data', {}):
                import_email_permissions(backup_data['data']['email_permissions'], user_map, current_user_id)
                results['imported'].append('email_permissions')
            
            if 'email_attachments' in backup_data.get('data', {}):
                import_email_attachments(backup_data['data']['email_attachments'], email_map)
                results['imported'].append('email_attachments')
        
        # Termine importieren
        if _category_selected(categories, 'appointments'):
            calendar_map = {}
            if 'calendars' in backup_data.get('data', {}):
                calendar_map = import_calendars(backup_data['data']['calendars'], user_map, current_user_id)
                results['imported'].append('calendars')
            if 'calendar_sync_sources' in backup_data.get('data', {}):
                import_calendar_sync_sources(backup_data['data']['calendar_sync_sources'], user_map, current_user_id)
                results['imported'].append('calendar_sync_sources')
            if 'public_calendar_feeds' in backup_data.get('data', {}):
                import_public_calendar_feeds(backup_data['data']['public_calendar_feeds'], user_map, current_user_id)
                results['imported'].append('public_calendar_feeds')
            if 'calendar_events' in backup_data.get('data', {}):
                event_map = import_calendar_events(backup_data['data']['calendar_events'], user_map, current_user_id, calendar_map)
                results['imported'].append('calendar_events')
            else:
                event_map = {}
            
            if 'event_participants' in backup_data.get('data', {}):
                import_event_participants(backup_data['data']['event_participants'], event_map, user_map, current_user_id)
                results['imported'].append('event_participants')
        
        # Zugangsdaten importieren
        if _category_selected(categories, 'credentials'):
            if 'credentials' in backup_data.get('data', {}):
                import_credentials(backup_data['data']['credentials'], user_map, current_user_id)
                results['imported'].append('credentials')
        
        # Handbücher importieren
        if _category_selected(categories, 'manuals'):
            if 'manuals' in backup_data.get('data', {}):
                import_manuals(backup_data['data']['manuals'], user_map, current_user_id)
                results['imported'].append('manuals')
        
        # Chats importieren
        if _category_selected(categories, 'chats'):
            if 'chats' in backup_data.get('data', {}):
                chat_map = import_chats(backup_data['data']['chats'], user_map, current_user_id)
                results['imported'].append('chats')
            else:
                chat_map = {}
            
            if 'chat_members' in backup_data.get('data', {}):
                import_chat_members(backup_data['data']['chat_members'], chat_map, user_map, current_user_id)
                results['imported'].append('chat_members')
            
            if 'chat_messages' in backup_data.get('data', {}):
                import_chat_messages(backup_data['data']['chat_messages'], chat_map, user_map, current_user_id)
                results['imported'].append('chat_messages')

            if 'chat_pins' in backup_data.get('data', {}):
                import_chat_pins(backup_data['data']['chat_pins'], chat_map, user_map, current_user_id)
                results['imported'].append('chat_pins')
        
        # Dateien importieren
        if _category_selected(categories, 'files'):
            if 'folders' in backup_data.get('data', {}):
                folder_map = import_folders(backup_data['data']['folders'], user_map, current_user_id)
                results['imported'].append('folders')
            else:
                folder_map = {}
            
            if 'files' in backup_data.get('data', {}):
                import_files(backup_data['data']['files'], folder_map, user_map, current_user_id)
                results['imported'].append('files')
            
            if 'file_versions' in backup_data.get('data', {}):
                import_file_versions(backup_data['data']['file_versions'], user_map, current_user_id)
                results['imported'].append('file_versions')

            if 'public_shares' in backup_data.get('data', {}):
                import_public_shares(backup_data['data']['public_shares'], user_map, current_user_id)
                results['imported'].append('public_shares')

            if 'resource_acls' in backup_data.get('data', {}):
                import_resource_acls(backup_data['data']['resource_acls'], folder_map, user_map, current_user_id)
                results['imported'].append('resource_acls')

            if 'folder_favorites' in backup_data.get('data', {}):
                import_folder_favorites(backup_data['data']['folder_favorites'], folder_map, user_map, current_user_id)
                results['imported'].append('folder_favorites')
        
        # Wiki importieren
        if _category_selected(categories, 'wiki'):
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
                page_map = import_wiki_pages(backup_data['data']['wiki_pages'], category_map, tag_map, user_map, current_user_id)
                results['imported'].append('wiki_pages')
            else:
                page_map = {}
            
            if 'wiki_page_versions' in backup_data.get('data', {}):
                import_wiki_page_versions(backup_data['data']['wiki_page_versions'], page_map, user_map, current_user_id)
                results['imported'].append('wiki_page_versions')
        
        # Kommentare importieren
        if _category_selected(categories, 'comments'):
            if 'comments' in backup_data.get('data', {}):
                comment_map = import_comments(backup_data['data']['comments'], user_map, current_user_id)
                results['imported'].append('comments')
            else:
                comment_map = {}
            
            if 'comment_mentions' in backup_data.get('data', {}):
                import_comment_mentions(backup_data['data']['comment_mentions'], comment_map, user_map, current_user_id)
                results['imported'].append('comment_mentions')
        
        # Inventar importieren
        if _category_selected(categories, 'inventory'):
            if 'product_folders' in backup_data.get('data', {}):
                folder_map = import_product_folders(backup_data['data']['product_folders'], user_map, current_user_id)
                results['imported'].append('product_folders')
            else:
                folder_map = {}
            
            if 'products' in backup_data.get('data', {}):
                product_map = import_products(backup_data['data']['products'], folder_map, user_map, current_user_id)
                results['imported'].append('products')
            else:
                product_map = {}
            
            if 'borrow_transactions' in backup_data.get('data', {}):
                import_borrow_transactions(backup_data['data']['borrow_transactions'], product_map, user_map, current_user_id)
                results['imported'].append('borrow_transactions')
            
            if 'product_sets' in backup_data.get('data', {}):
                set_map = import_product_sets(backup_data['data']['product_sets'], user_map, current_user_id)
                results['imported'].append('product_sets')
            else:
                set_map = {}
            
            if 'product_set_items' in backup_data.get('data', {}):
                import_product_set_items(backup_data['data']['product_set_items'], set_map, product_map)
                results['imported'].append('product_set_items')
            
            if 'product_documents' in backup_data.get('data', {}):
                import_product_documents(backup_data['data']['product_documents'], product_map, user_map, current_user_id)
                results['imported'].append('product_documents')
            
            if 'saved_filters' in backup_data.get('data', {}):
                import_saved_filters(backup_data['data']['saved_filters'], user_map, current_user_id)
                results['imported'].append('saved_filters')
            
            if 'product_favorites' in backup_data.get('data', {}):
                import_product_favorites(backup_data['data']['product_favorites'], product_map, user_map, current_user_id)
                results['imported'].append('product_favorites')
            
            if 'inventories' in backup_data.get('data', {}):
                inventory_map = import_inventories(backup_data['data']['inventories'], user_map, current_user_id)
                results['imported'].append('inventories')
            else:
                inventory_map = {}
            
            if 'inventory_items' in backup_data.get('data', {}):
                import_inventory_items(backup_data['data']['inventory_items'], inventory_map, product_map, user_map, current_user_id)
                results['imported'].append('inventory_items')

        # Neue Module
        if _category_selected(categories, 'contacts') and 'contacts' in backup_data_dict:
            import_contacts(backup_data_dict['contacts'], user_map, current_user_id)
            results['imported'].append('contacts')

        if _category_selected(categories, 'events'):
            event_id_map = {}
            if 'portal_events' in backup_data_dict:
                event_id_map = import_portal_events(backup_data_dict['portal_events'], user_map, current_user_id)
                results['imported'].append('portal_events')
            if 'event_appointments' in backup_data_dict:
                import_event_appointments(backup_data_dict['event_appointments'], event_id_map)
                results['imported'].append('event_appointments')
            if 'event_assignments' in backup_data_dict:
                import_event_assignments(backup_data_dict['event_assignments'], event_id_map, user_map, current_user_id)
                results['imported'].append('event_assignments')
            if 'event_inventory_needs' in backup_data_dict:
                import_event_inventory_needs(backup_data_dict['event_inventory_needs'], event_id_map)
                results['imported'].append('event_inventory_needs')
            if 'event_contacts' in backup_data_dict:
                import_event_contacts(backup_data_dict['event_contacts'], event_id_map)
                results['imported'].append('event_contacts')
            if 'event_timeline_items' in backup_data_dict:
                import_event_timeline_items(backup_data_dict['event_timeline_items'], event_id_map)
                results['imported'].append('event_timeline_items')

        if _category_selected(categories, 'booking'):
            import_booking_bundle(backup_data_dict, user_map, current_user_id, results)

        if _category_selected(categories, 'music'):
            if 'music_settings' in backup_data_dict:
                import_music_settings(backup_data_dict['music_settings'])
                results['imported'].append('music_settings')
            if 'music_wishes' in backup_data_dict:
                import_music_wishes(backup_data_dict['music_wishes'], user_map, current_user_id)
                results['imported'].append('music_wishes')
            if 'music_queue' in backup_data_dict:
                import_music_queue(backup_data_dict['music_queue'], user_map, current_user_id)
                results['imported'].append('music_queue')

        if _category_selected(categories, 'media_downloader') and 'media_download_jobs' in backup_data_dict:
            import_media_download_jobs(backup_data_dict['media_download_jobs'], user_map, current_user_id)
            results['imported'].append('media_download_jobs')

        if _category_selected(categories, 'assessment'):
            import_assessment_bundle(backup_data_dict, results)

        if _category_selected(categories, 'shortlinks') and 'short_links' in backup_data_dict:
            import_short_links(backup_data_dict['short_links'], user_map, current_user_id)
            results['imported'].append('shortlinks')

        if _category_selected(categories, 'excalidraw'):
            room_map = {}
            if 'excalidraw_drawings' in backup_data_dict:
                room_map = import_excalidraw_drawings(backup_data_dict['excalidraw_drawings'], user_map, current_user_id)
                results['imported'].append('excalidraw_drawings')
            if 'excalidraw_drawing_versions' in backup_data_dict:
                import_excalidraw_drawing_versions(
                    backup_data_dict['excalidraw_drawing_versions'], room_map, user_map, current_user_id
                )
                results['imported'].append('excalidraw_drawing_versions')
        
        db.session.commit()

        # Hauptchat absichern (nach Commit, dedupe_main_chats committed selbst)
        if _category_selected(categories, 'chats'):
            try:
                from app.utils.chat_nav import dedupe_main_chats
                dedupe_main_chats()
            except Exception as dedupe_err:
                current_app.logger.warning(f'Hauptchat-Dedupe nach Import: {dedupe_err}')

        return results
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Fehler beim Import: {str(e)}")
        return {'success': False, 'error': f'Fehler beim Import: {str(e)}'}
