"""Import inventory products, sets, documents, and sessions."""

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

def import_product_folders(folders_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None) -> Dict[str, int]:
    """Importiert Produkt-Ordner und gibt ein Mapping von Name zu neuer ID zurück."""
    folder_map = {}  # name -> neue_id
    
    if not folders_data:
        current_app.logger.debug("Keine Produkt-Ordner zum Importieren vorhanden.")
        return folder_map

    existing_by_name = objects_by_name(ProductFolder)
    
    for f_data in folders_data:
        if not f_data.get('name'):
            current_app.logger.warning("Ordner ohne Namen übersprungen beim Import.")
            continue
        
        folder_name = f_data['name'].strip()
        if not folder_name:
            continue
        
        created_by_email = f_data.get('created_by_email')
        if not created_by_email:
            if current_user_id:
                created_by_id = current_user_id
            else:
                current_app.logger.warning(f"Ordner '{folder_name}' ohne created_by_email und ohne current_user_id übersprungen.")
                continue
        elif created_by_email not in user_map:
            # Fallback: Wenn Benutzer nicht gefunden wird, verwende current_user
            if current_user_id:
                created_by_id = current_user_id
            else:
                current_app.logger.warning(f"Ordner '{folder_name}' - Benutzer '{created_by_email}' nicht gefunden und kein current_user_id verfügbar.")
                continue
        else:
            created_by_id = user_map[created_by_email]
        
        existing = existing_by_name.get(folder_name)
        if existing:
            folder_map[folder_name] = existing.id
            current_app.logger.debug(f"Ordner '{folder_name}' bereits vorhanden (ID: {existing.id})")
        else:
            folder = ProductFolder(
                name=folder_name,
                description=f_data.get('description'),
                color=f_data.get('color'),
                created_by=created_by_id
            )
            db.session.add(folder)
            db.session.flush()
            existing_by_name[folder_name] = folder
            folder_map[folder_name] = folder.id
            current_app.logger.debug(f"Ordner '{folder_name}' importiert (ID: {folder.id})")
    
    # Commit nach allen Ordnern
    db.session.commit()
    current_app.logger.info(f"{len(folder_map)} Produkt-Ordner importiert/gefunden.")
    
    return folder_map


def import_products(products_data: List[Dict], folder_map: Dict[str, int], user_map: Dict[str, int], current_user_id: Optional[int] = None) -> Dict[str, int]:
    """Importiert Produkte und gibt ein Mapping von Name zu neuer ID zurück."""
    product_map = {}  # name -> neue_id
    existing_products = objects_by_name(Product)
    existing_folders = objects_by_name(ProductFolder)
    
    for p_data in products_data:
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
        folder_id = None
        folder_name = p_data.get('folder_name')
        if folder_name:
            folder_name = folder_name.strip()
            if folder_name in folder_map:
                folder_id = folder_map[folder_name]
                current_app.logger.debug(f"Produkt '{p_data['name']}' wird Ordner '{folder_name}' (ID: {folder_id}) zugeordnet.")
            else:
                current_app.logger.warning(f"Produkt '{p_data['name']}' - Ordner '{folder_name}' nicht im folder_map gefunden. Ordner wird nicht zugeordnet.")
                # Versuche Ordner in der DB zu finden (falls er bereits existiert)
                existing_folder = existing_folders.get(folder_name)
                if existing_folder:
                    folder_id = existing_folder.id
                    folder_map[folder_name] = folder_id  # Aktualisiere folder_map für zukünftige Produkte
                    current_app.logger.info(f"Ordner '{folder_name}' in DB gefunden (ID: {folder_id}) und folder_map aktualisiert.")
        
        existing = existing_products.get(p_data['name'])
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
                qr_code_data=p_data.get('qr_code_data'),
                folder_id=folder_id,
                created_by=created_by_id
            )
            
            # Importiere Produktbild wenn vorhanden
            if p_data.get('image_content_base64'):
                try:
                    import base64
                    from werkzeug.utils import secure_filename
                    
                    file_content = base64.b64decode(p_data['image_content_base64'])
                    original_name = p_data.get('image_original_name', p_data.get('image_path', 'product.png'))
                    
                    # Erstelle Dateiname mit Timestamp
                    if '.' in original_name:
                        ext = os.path.splitext(original_name)[1]
                        base_name = os.path.splitext(original_name)[0]
                    else:
                        ext = '.png'
                        base_name = 'product'
                    
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"{timestamp}_{secure_filename(base_name)}{ext}"
                    
                    # Speichere Datei
                    project_root = os.path.dirname(current_app.root_path)
                    upload_dir = os.path.join(project_root, current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'inventory', 'product_images')
                    os.makedirs(upload_dir, exist_ok=True)
                    file_path = os.path.join(upload_dir, filename)
                    
                    with open(file_path, 'wb') as f:
                        f.write(file_content)
                    
                    product.image_path = filename
                except Exception as e:
                    current_app.logger.error(f"Fehler beim Importieren des Produktbilds für {p_data['name']}: {str(e)}")
                    product.image_path = p_data.get('image_path')
            else:
                product.image_path = p_data.get('image_path')
            
            db.session.add(product)
            db.session.flush()
            existing_products[p_data['name']] = product
            product_map[p_data['name']] = product.id
    
    return product_map


def import_borrow_transactions(transactions_data: List[Dict], product_map: Dict[str, int], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Ausleihtransaktionen."""
    for t_data in transactions_data:
        product_name = t_data.get('product_name')
        borrower_email = t_data.get('borrower_email')
        borrowed_by_email = t_data.get('borrowed_by_email')
        
        if not product_name or product_name not in product_map:
            continue
        
        # Fallback für borrower_email
        if not borrower_email:
            if current_user_id:
                borrower_id = current_user_id
            else:
                continue
        elif borrower_email not in user_map:
            if current_user_id:
                borrower_id = current_user_id
            else:
                continue
        else:
            borrower_id = user_map[borrower_email]
        
        # Fallback für borrowed_by_email
        if not borrowed_by_email:
            if current_user_id:
                borrowed_by_id = current_user_id
            else:
                continue
        elif borrowed_by_email not in user_map:
            if current_user_id:
                borrowed_by_id = current_user_id
            else:
                continue
        else:
            borrowed_by_id = user_map[borrowed_by_email]
        
        product_id = product_map[product_name]
        
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


def import_product_sets(sets_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None) -> Dict[str, int]:
    """Importiert Produktsets und gibt ein Mapping von Name zu neuer ID zurück."""
    set_map = {}  # name -> neue_id
    existing_by_name = objects_by_name(ProductSet)
    
    for s_data in sets_data:
        created_by_email = s_data.get('created_by_email')
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
        
        existing = existing_by_name.get(s_data['name'])
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
            existing_by_name[s_data['name']] = product_set
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


def import_product_documents(documents_data: List[Dict], product_map: Dict[str, int], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Produktdokumente (Datei und/oder Manual-Verknüpfung)."""
    from app.models.manual import Manual

    for d_data in documents_data:
        product_name = d_data.get('product_name')
        uploaded_by_email = d_data.get('uploaded_by_email')
        
        if not product_name or product_name not in product_map:
            continue
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
        
        product_id = product_map[product_name]
        has_content = bool(d_data.get('content_base64'))
        file_name = d_data.get('file_name')

        manual_id = d_data.get('manual_id')
        if manual_id and not Manual.query.get(manual_id):
            # Fallback: per Titel suchen
            manual_title = (d_data.get('manual_title') or '').strip()
            if manual_title:
                found = Manual.query.filter_by(title=manual_title).first()
                manual_id = found.id if found else None
            else:
                manual_id = None

        if not has_content and not manual_id:
            continue
        
        document = ProductDocument(
            product_id=product_id,
            file_name=file_name,
            file_type=d_data.get('file_type') or 'other',
            file_size=d_data.get('file_size'),
            manual_id=manual_id,
            uploaded_by=uploaded_by_id
        )
        
        # Dateiinhalt speichern wenn vorhanden
        if has_content:
            try:
                import base64
                content = base64.b64decode(d_data['content_base64'])
                
                from werkzeug.utils import secure_filename
                filename = secure_filename(file_name or 'document')
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                filename = f"{timestamp}_{filename}"
                
                upload_dir = os.path.join(
                    current_app.config.get('UPLOAD_FOLDER', 'uploads'),
                    'inventory',
                    'product_documents',
                )
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, filename)
                
                with open(file_path, 'wb') as f:
                    f.write(content)
                
                document.file_path = os.path.abspath(file_path)
                document.file_size = len(content)
                if not document.file_name:
                    document.file_name = file_name or filename
            except Exception as e:
                current_app.logger.error(f"Fehler beim Speichern von Produktdokument {file_name}: {str(e)}")
                if not manual_id:
                    continue
        
        db.session.add(document)


def import_saved_filters(filters_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert gespeicherte Filter."""
    for f_data in filters_data:
        user_email = f_data.get('user_email')
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
        
        existing = SavedFilter.query.filter_by(user_id=user_id, name=f_data['name']).first()
        if existing:
            continue
        
        filter_obj = SavedFilter(
            user_id=user_id,
            name=f_data['name'],
            filter_data=f_data['filter_data']
        )
        db.session.add(filter_obj)


def import_product_favorites(favorites_data: List[Dict], product_map: Dict[str, int], user_map: Dict[str, int], current_user_id: Optional[int] = None):
    """Importiert Produktfavoriten."""
    for f_data in favorites_data:
        user_email = f_data.get('user_email')
        product_name = f_data.get('product_name')
        
        if not product_name or product_name not in product_map:
            continue
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
        
        product_id = product_map[product_name]
        
        existing = ProductFavorite.query.filter_by(user_id=user_id, product_id=product_id).first()
        if existing:
            continue
        
        favorite = ProductFavorite(
            user_id=user_id,
            product_id=product_id
        )
        db.session.add(favorite)


def import_inventories(inventories_data: List[Dict], user_map: Dict[str, int], current_user_id: Optional[int] = None) -> Dict[str, int]:
    """Importiert Inventuren und gibt ein Mapping von Name zu neuer ID zurück."""
    inventory_map = {}  # name -> neue_id
    
    for i_data in inventories_data:
        started_by_email = i_data.get('started_by_email')
        if not started_by_email:
            if current_user_id:
                started_by_id = current_user_id
            else:
                continue
        elif started_by_email not in user_map:
            # Fallback: Wenn Benutzer nicht gefunden wird, verwende current_user
            if current_user_id:
                started_by_id = current_user_id
            else:
                continue
        else:
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


def import_inventory_items(items_data: List[Dict], inventory_map: Dict[str, int], product_map: Dict[str, int], user_map: Dict[str, int], current_user_id: Optional[int] = None):
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
        checked_by_email = i_data.get('checked_by_email')
        if checked_by_email:
            if checked_by_email in user_map:
                checked_by_id = user_map[checked_by_email]
            elif current_user_id:
                # Fallback: Wenn Benutzer nicht gefunden wird, verwende current_user
                checked_by_id = current_user_id
        
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
