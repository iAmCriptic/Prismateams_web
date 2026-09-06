from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app, session, send_from_directory
from flask_login import login_required, current_user
from app import db
from app.utils.i18n import _, translate
from app.models.inventory import Product, Checkout, CheckoutItem, ProductFolder, ProductSet, ProductSetItem, ProductDocument, SavedFilter, ProductFavorite, Inventory, InventoryItem
from app.models.api_token import ApiToken
from app.models.user import User
from app.models.settings import SystemSettings
from app.utils.access_control import check_module_access
import json
from urllib.parse import unquote
from app.utils.qr_code import (
    generate_product_qr_code, generate_borrow_qr_code, generate_set_qr_code,
    parse_qr_code, generate_qr_code_bytes
)
from app.utils.pdf_generator import generate_borrow_receipt_pdf, generate_qr_code_sheet_pdf
from app.utils.pdf_generator_color_table import generate_color_code_table_pdf
from app.utils.lengths import normalize_length_input, parse_length_to_meters
from app.utils.dates import compute_dguv_next
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload, selectinload
import os
import secrets
import string
from io import BytesIO
import re

from app.blueprints.inventory._bp import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    CART_QTY_META_KEY,
    CART_SET_META_KEY,
    DEFAULT_DGUV_INTERVAL_MONTHS,
    DOCUMENT_FILE_TYPES,
    RETIRED_FOLDER_NAME,
    inventory_bp,
)

from app.blueprints.inventory.helpers import *  # noqa: F401,F403
from app.blueprints.inventory.helpers import (  # noqa: F401
    _product_extra_fields,
    _serialize_product_api,
)

@login_required
def api_products():
    """API: Liste aller Produkte mit Such- und Filteroptionen (lazy: offset/limit)."""
    try:
        search = request.args.get('search', '').strip()
        category = request.args.get('category', '').strip()
        status = request.args.get('status', '').strip()
        sort_by_param = request.args.get('sort_by', 'name')
        sort_dir_param = request.args.get('sort_dir', 'asc')
        offset = max(0, request.args.get('offset', 0, type=int) or 0)
        # Default-Limit für Lazy Loading; ?limit=0 oder sehr groß = alles (Legacy)
        limit_raw = request.args.get('limit', default=48, type=int)
        if limit_raw is None:
            limit_raw = 48
        unlimited = limit_raw <= 0
        limit = 5000 if unlimited else min(max(1, limit_raw), 200)
        
        sort_by = (sort_by_param or 'name').strip().lower()
        sort_dir = (sort_dir_param or 'asc').strip().lower()
        if sort_by not in {'name', 'category', 'status', 'condition', 'folder', 'created_at', 'length'}:
            sort_by = 'name'
        if sort_dir not in {'asc', 'desc'}:
            sort_dir = 'asc'
        descending = sort_dir == 'desc'
        
        query = Product.query
        
        if search:
            query = query.filter(
                or_(
                    Product.name.ilike(f'%{search}%'),
                    Product.serial_number.ilike(f'%{search}%'),
                    Product.description.ilike(f'%{search}%')
                )
            )
        
        if category:
            query = query.filter_by(category=category)
        
        if status:
            query = query.filter_by(status=status)
        
        try:
            sort_field_map = {
                'name': Product.name,
                'category': Product.category,
                'status': Product.status,
                'condition': Product.condition,
                'folder': Product.folder_id,
                'created_at': Product.created_at,
            }
            
            products_query = query.options(joinedload(Product.folder))
            
            if sort_by != 'length':
                sort_column = sort_field_map.get(sort_by, Product.name)
                order_clause = sort_column.desc() if descending else sort_column.asc()
                products_query = products_query.order_by(order_clause)
            else:
                products_query = products_query.order_by(Product.name.asc())
            
            if sort_by == 'length':
                products = products_query.all()

                def length_sort_key(prod):
                    meters = parse_length_to_meters(getattr(prod, 'length', None))
                    if meters is None:
                        return (1, 0.0)
                    return (0, -meters if descending else meters)

                products.sort(key=length_sort_key)
                if unlimited:
                    page_products = products
                    has_more = False
                    next_offset = len(products)
                else:
                    page_products = products[offset:offset + limit]
                    has_more = (offset + limit) < len(products)
                    next_offset = offset + len(page_products)
                products = page_products
            elif unlimited:
                products = products_query.offset(offset).all()
                has_more = False
                next_offset = offset + len(products)
            else:
                batch = products_query.offset(offset).limit(limit + 1).all()
                has_more = len(batch) > limit
                products = batch[:limit]
                next_offset = offset + len(products)
        except Exception as e:
            current_app.logger.warning(f"joinedload fehlgeschlagen, verwende Standard-Query: {e}")
            products = query.order_by(Product.name).offset(offset).limit(limit + (0 if unlimited else 1)).all()
            if unlimited:
                has_more = False
            else:
                has_more = len(products) > limit
                products = products[:limit]
            next_offset = offset + len(products)
        
        result = []
        for p in products:
            try:
                folder_id = getattr(p, 'folder_id', None)
                folder_name = None
                if folder_id and p.folder:
                    folder_name = p.folder.name
                elif hasattr(p, 'folder') and p.folder:
                    folder_name = p.folder.name
                
                location = getattr(p, 'location', None)
                length = getattr(p, 'length', None)
                
                location_value = location if (location and str(location).strip()) else None
                length_value = length if (length and str(length).strip()) else None
                
                image_path_value = None
                if p.image_path:
                    if os.path.isabs(p.image_path):
                        image_path_value = os.path.basename(p.image_path)
                    else:
                        image_path_value = p.image_path
                
                result.append({
                    'id': p.id,
                    'name': p.name,
                    'description': p.description,
                    'category': p.category,
                    'serial_number': p.serial_number,
                    'condition': p.condition,
                    'location': location_value,
                    'length': length_value,
                    'length_meters': parse_length_to_meters(length_value),
                    'folder_id': folder_id,
                    'folder_name': folder_name,
                    'purchase_date': p.purchase_date.isoformat() if p.purchase_date else None,
                    'status': p.status,
                    'item_type': p.item_type,
                    'on_hand': p.total_on_hand,
                    'available': p.total_available,
                    'image_path': image_path_value,
                    'qr_code_data': p.qr_code_data,
                    'created_at': p.created_at.isoformat(),
                    'created_by': p.created_by,
                    **_product_extra_fields(p),
                })
            except Exception as e:
                current_app.logger.error(f"Fehler beim Serialisieren von Produkt {p.id}: {e}", exc_info=True)
                image_path_value = None
                image_path_raw = getattr(p, 'image_path', None)
                if image_path_raw:
                    if os.path.isabs(image_path_raw):
                        image_path_value = os.path.basename(image_path_raw)
                    else:
                        image_path_value = image_path_raw
                result.append({
                    'id': p.id,
                    'name': p.name,
                    'description': getattr(p, 'description', None),
                    'category': p.category,
                    'serial_number': p.serial_number,
                    'condition': getattr(p, 'condition', None),
                    'location': getattr(p, 'location', None),
                    'length': getattr(p, 'length', None),
                    'length_meters': parse_length_to_meters(getattr(p, 'length', None)),
                    'folder_id': None,
                    'folder_name': None,
                    'purchase_date': p.purchase_date.isoformat() if p.purchase_date else None,
                    'status': p.status,
                    'item_type': getattr(p, 'item_type', 'asset'),
                    'on_hand': getattr(p, 'total_on_hand', 0),
                    'available': getattr(p, 'total_available', 0),
                    'image_path': image_path_value,
                    'qr_code_data': getattr(p, 'qr_code_data', None),
                    'created_at': p.created_at.isoformat(),
                    'created_by': p.created_by
                })
        
        return jsonify({
            'products': result,
            'has_more': bool(has_more),
            'next_offset': next_offset,
            'offset': offset,
            'limit': None if unlimited else limit,
        })
    except Exception as e:
        current_app.logger.error(f"Kritischer Fehler in api_products: {e}", exc_info=True)
        return jsonify({'error': f'Server-Fehler: {str(e)}'}), 500


@login_required
def api_product_get(product_id):
    """API: Einzelnes Produkt abrufen."""
    product = Product.query.options(joinedload(Product.folder)).get_or_404(product_id)
    return jsonify(_serialize_product_api(product))


@login_required
def api_product_create():
    """API: Neues Produkt erstellen."""
    # Gast-Accounts können keine Produkte erstellen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({'error': translate('inventory.errors.guests_cannot_create')}), 403
    
    data = request.get_json()
    
    if not data or not data.get('name'):
        return jsonify({'error': translate('inventory.errors.product_name_required')}), 400

    length_raw = data.get('length')
    normalized_length = None
    if length_raw not in (None, ''):
        normalized_length, _unused = normalize_length_input(str(length_raw))
        if normalized_length is None:
            return jsonify({'error': translate('inventory.errors.invalid_length_format')}), 400

    external_barcode = _normalize_external_barcode(data.get('external_barcode'))
    if external_barcode and _external_barcode_taken(external_barcode):
        return jsonify({'error': translate('inventory.flash.external_barcode_taken', code=external_barcode)}), 400
    
    product = Product(
        name=data['name'],
        description=data.get('description'),
        category=data.get('category'),
        serial_number=data.get('serial_number'),
        condition=data.get('condition'),
        location=data.get('location'),
        length=normalized_length,
        purchase_date=datetime.strptime(data['purchase_date'], '%Y-%m-%d').date() if data.get('purchase_date') else None,
        status='available',
        external_barcode=external_barcode,
        created_by=current_user.id
    )

    db.session.add(product)
    db.session.flush()  # ID nötig für QR-URL

    product.qr_code_data = generate_product_qr_code(product.id)
    db.session.commit()
    
    return jsonify({
        'id': product.id,
        'name': product.name,
        'qr_code_data': product.qr_code_data
    }), 201


@login_required
def api_product_update(product_id):
    """API: Produkt aktualisieren."""
    # Gast-Accounts können keine Produkte aktualisieren
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({'error': translate('inventory.errors.guests_cannot_update')}), 403
    
    product = Product.query.get_or_404(product_id)
    data = request.get_json()
    
    if not data:
        return jsonify({'error': translate('inventory.errors.no_data_submitted')}), 400
    
    if 'name' in data:
        product.name = data['name']
    if 'description' in data:
        product.description = data.get('description')
    if 'category' in data:
        product.category = data.get('category')
    if 'serial_number' in data:
        product.serial_number = data.get('serial_number')
    if 'external_barcode' in data:
        external_barcode = _normalize_external_barcode(data.get('external_barcode'))
        if external_barcode and _external_barcode_taken(external_barcode, exclude_product_id=product.id):
            return jsonify({'error': translate('inventory.flash.external_barcode_taken', code=external_barcode)}), 400
        product.external_barcode = external_barcode
    if 'condition' in data:
        product.condition = data.get('condition')
    if 'location' in data:
        product.location = data.get('location')
    if 'length' in data:
        length_raw = data.get('length')
        if length_raw in (None, ''):
            product.length = None
        else:
            normalized_length, _unused = normalize_length_input(str(length_raw))
            if normalized_length is None:
                return jsonify({'error': translate('inventory.errors.invalid_length_format')}), 400
            product.length = normalized_length
    if 'purchase_date' in data:
        if data['purchase_date']:
            product.purchase_date = datetime.strptime(data['purchase_date'], '%Y-%m-%d').date()
        else:
            product.purchase_date = None
    if 'status' in data:
        from app.services.inventory import LifecycleService
        status_value = (data.get('status') or '').strip()
        allowed = {'available', 'borrowed', 'missing', 'defective', 'in_repair', 'retired'}
        if status_value in allowed:
            try:
                LifecycleService.change_status(
                    product,
                    status_value,
                    current_user.id,
                    reason='api_product_update',
                    force=True,
                )
            except ValueError as exc:
                db.session.rollback()
                return jsonify({'error': str(exc)}), 409
            if status_value == 'retired':
                _apply_retired_folder_assignment(product)

    # DGUV: explicit clear, or update last/interval/next
    if data.get('dguv_clear') in (True, 1, '1', 'true'):
        _clear_dguv_fields(product)
    elif any(k in data for k in ('dguv_last_check', 'dguv_interval_months', 'dguv_next_check', 'dguv_required')):
        if data.get('dguv_required') in (False, 0, '0', 'false'):
            _clear_dguv_fields(product)
        else:
            _apply_dguv_fields(
                product,
                data.get('dguv_last_check'),
                data.get('dguv_interval_months'),
                next_equals_created_if_no_last=True,
            )
            # Optional override of computed next if client sends one
            if data.get('dguv_next_check'):
                next_parsed = _parse_optional_date(data.get('dguv_next_check'))
                if next_parsed:
                    product.dguv_next_check = next_parsed

    db.session.commit()

    return jsonify({
        'message': 'Produkt aktualisiert.',
        'product': _serialize_product_api(
            Product.query.options(joinedload(Product.folder)).get(product.id) or product
        ),
    })


@login_required
def api_product_delete(product_id):
    """API: Produkt in den Papierkorb verschieben."""
    # Gast-Accounts können keine Produkte löschen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({'error': translate('inventory.errors.guests_cannot_delete')}), 403
    
    product = Product.query.get_or_404(product_id)
    
    from app.services.inventory.checkout_service import find_active_checkout_item_for_product
    if find_active_checkout_item_for_product(product_id) or product.status == 'borrowed':
        return jsonify({'error': translate('inventory.errors.product_borrowed_cannot_delete')}), 400
    
    try:
        # Produkt aus Sets entfernen (Gerät darf trotzdem in den Papierkorb)
        ProductSetItem.query.filter_by(product_id=product_id).delete()

        from app.services.inventory import LifecycleService
        LifecycleService.change_status(
            product,
            'retired',
            current_user.id,
            reason='api_delete',
            force=True,
        )
        _apply_retired_folder_assignment(product)
        db.session.commit()

        return jsonify({'message': f'Produkt "{product.name}" wurde in den Papierkorb verschoben.'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Fehler beim Löschen von Produkt {product_id}: {e}", exc_info=True)
        
        error_msg = str(e)
        if 'foreign key constraint' in error_msg.lower() or '1451' in error_msg:
            return jsonify({'error': f'Das Produkt "{product.name}" kann nicht gelöscht werden, da es noch in Verwendung ist (z.B. in einem Produktset).'}), 400
        else:
            return jsonify({'error': f'Fehler beim Löschen des Produkts: {error_msg}'}), 500


@login_required
def api_products_bulk_update():
    """API: Mehrere Produkte gleichzeitig aktualisieren."""
    # Gast-Accounts können keine Produkte aktualisieren
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({'error': translate('inventory.errors.guests_cannot_update')}), 403
    
    data = request.get_json()
    
    if not data:
        return jsonify({'error': translate('inventory.errors.no_data_submitted')}), 400
    
    product_ids = data.get('product_ids', [])
    if not product_ids or not isinstance(product_ids, list):
        return jsonify({'error': translate('inventory.errors.invalid_product_ids_array')}), 400
    
    if len(product_ids) == 0:
        return jsonify({'error': translate('inventory.errors.no_product_ids')}), 400
    
    try:
        product_ids_int = [int(pid) for pid in product_ids]
    except (ValueError, TypeError):
        return jsonify({'error': translate('inventory.errors.invalid_product_ids_numeric')}), 400
    
    products = Product.query.filter(Product.id.in_(product_ids_int)).all()
    
    if len(products) != len(product_ids_int):
        return jsonify({'error': translate('inventory.errors.some_product_ids_not_found')}), 404
    
    updates = {}
    errors = []
    convert_to_cable = bool(data.get('convert_to_cable'))
    
    if 'location' in data:
        location_value = data.get('location', '').strip() or None
        updates['location'] = location_value
    
    if 'length' in data:
        length_raw = data.get('length')
        if length_raw in (None, ''):
            updates['length'] = None
        else:
            normalized_length, _unused = normalize_length_input(str(length_raw))
            if normalized_length is None:
                errors.append('Ungültige Längenangabe. Erwartet Meterwert (z.B. 5.5).')
            else:
                updates['length'] = normalized_length
    
    if 'condition' in data:
        condition_value = data.get('condition', '').strip() or None
        if condition_value not in (None, '', 'Neu', 'Gut', 'Gebraucht', 'Beschädigt'):
            errors.append('Ungültiger Zustand. Erlaubt: Neu, Gut, Gebraucht, Beschädigt.')
        else:
            updates['condition'] = condition_value
    
    if 'category' in data:
        category_value = data.get('category', '').strip() or None
        updates['category'] = category_value
    
    if 'folder_id' in data:
        folder_id_raw = data.get('folder_id')
        if folder_id_raw in (None, ''):
            updates['folder_id'] = None
        else:
            try:
                folder_id_int = int(folder_id_raw)
                folder = ProductFolder.query.get(folder_id_int)
                if not folder:
                    errors.append(f'Ordner mit ID {folder_id_int} nicht gefunden.')
                else:
                    updates['folder_id'] = folder_id_int
            except (ValueError, TypeError):
                errors.append('Ungültige Ordner-ID.')

    if 'status' in data:
        status_value = (data.get('status') or '').strip()
        if status_value not in ('available', 'borrowed', 'missing', 'defective', 'in_repair', 'retired'):
            errors.append('Ungültiger Status.')
        else:
            updates['status'] = status_value
    
    if 'remove_image' in data and data.get('remove_image'):
        updates['remove_image'] = True

    if 'dguv_interval_months' in data:
        interval = _parse_optional_int(data.get('dguv_interval_months'))
        if interval is None or interval < 1:
            errors.append('Ungültiges DGUV-Intervall (Monate >= 1).')
        else:
            updates['dguv_interval_months'] = interval

    if 'dguv_last_check' in data or data.get('dguv_default_last_to_today'):
        updates['dguv_last_check'] = data.get('dguv_last_check')
        updates['dguv_default_last_to_today'] = bool(data.get('dguv_default_last_to_today'))
    
    if errors:
        return jsonify({'error': translate('inventory.errors.validation_error'), 'details': errors}), 400
    
    if not updates and not convert_to_cable:
        return jsonify({'error': translate('inventory.errors.no_update_data')}), 400

    if convert_to_cable:
        from app.services.inventory import StockService

        names = {str(p.name or '').strip() for p in products}
        categories = {str(p.category or '').strip() for p in products}
        lengths = {str(p.length or '').strip() for p in products}
        if len(names) != 1 or len(categories) != 1 or len(lengths) != 1:
            return jsonify({'error': 'Konvertierung nur möglich, wenn Name, Kategorie und Länge bei allen ausgewählten Produkten gleich sind.'}), 400

        blocked = [p for p in products if p.status in ('borrowed', 'missing', 'defective', 'in_repair')]
        if blocked:
            return jsonify({'error': 'Konvertierung nicht möglich: Einige ausgewählte Produkte sind nicht verfügbar (ausgeliehen/defekt/fehlend).'}), 400

        target = next((p for p in products if p.status != 'retired'), products[0])
        stock_total = 0
        for product in products:
            if product.item_type == 'consumable':
                stock_total += int(product.total_on_hand or 0)
            else:
                stock_total += 0 if product.status == 'retired' else 1
        stock_total = max(0, int(stock_total))

        try:
            target.item_type = 'consumable'
            if target.status == 'retired' and stock_total > 0:
                target.status = 'available'
                _apply_retired_folder_assignment(target)

            for product in products:
                if product.id == target.id:
                    continue
                if product.item_type == 'consumable' and int(product.total_on_hand or 0) > 0:
                    StockService.set_stock_count(
                        product,
                        0,
                        current_user.id,
                        reason='Bestand in Sammel-Mengenartikel überführt',
                        context_type='manual',
                        context_id=f'bulk-convert:{target.id}',
                    )
                product.status = 'retired'
                _apply_retired_folder_assignment(product)

            StockService.set_stock_count(
                target,
                stock_total,
                current_user.id,
                reason='Bulk-Konvertierung zu Mengenartikel',
                context_type='manual',
                context_id=f'bulk-convert:{target.id}',
            )
            db.session.commit()
            return jsonify({
                'message': f'Auswahl wurde in Mengenartikel "{target.name}" überführt (Bestand: {stock_total}).',
                'updated_count': len(products)
            })
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Fehler bei Bulk-Konvertierung zu Mengenartikel: {e}", exc_info=True)
            return jsonify({'error': translate('inventory.errors.update_error')}), 500
    
    # Batch-Update durchführen
    updated_count = 0
    for product in products:
        try:
            if 'location' in updates:
                product.location = updates['location']
            if 'length' in updates:
                product.length = updates['length']
            if 'condition' in updates:
                product.condition = updates['condition']
            if 'category' in updates:
                product.category = updates['category']
            if 'folder_id' in updates:
                product.folder_id = updates['folder_id']
            if 'status' in updates:
                from app.services.inventory import LifecycleService
                LifecycleService.change_status(
                    product,
                    updates['status'],
                    current_user.id,
                    reason='bulk_update',
                    force=True,
                )
                if updates['status'] == 'retired':
                    _apply_retired_folder_assignment(product)
            if updates.get('remove_image'):
                if product.image_path:
                    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_images')
                    filepath = os.path.join(upload_dir, product.image_path)
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except Exception as e:
                            current_app.logger.error(f"Fehler beim Löschen des Bildes: {e}")
                product.image_path = None
            if 'dguv_interval_months' in updates and 'dguv_last_check' not in updates:
                product.dguv_interval_months = updates['dguv_interval_months']
                product.dguv_next_check = compute_dguv_next(product.dguv_last_check, product.dguv_interval_months)
            if 'dguv_last_check' in updates:
                _apply_dguv_fields(
                    product,
                    updates.get('dguv_last_check'),
                    updates.get('dguv_interval_months', product.dguv_interval_months),
                    keep_existing_interval='dguv_interval_months' not in updates,
                    default_last_to_today=bool(updates.get('dguv_default_last_to_today')),
                )
            updated_count += 1
        except Exception as e:
            current_app.logger.error(f"Fehler beim Aktualisieren von Produkt {product.id}: {e}")
            errors.append(f"Fehler bei Produkt {product.id}: {str(e)}")
    
    if errors:
        db.session.rollback()
        return jsonify({'error': translate('inventory.errors.update_error'), 'details': errors}), 500
    
    db.session.commit()
    
    return jsonify({
        'message': f'{updated_count} Produkt(e) erfolgreich aktualisiert.',
        'updated_count': updated_count
    })


@login_required
def api_products_bulk_delete():
    """API: Mehrere Produkte gleichzeitig in den Papierkorb verschieben."""
    # Gast-Accounts können keine Produkte löschen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({'error': translate('inventory.errors.guests_cannot_delete')}), 403
    
    data = request.get_json()
    
    if not data:
        return jsonify({'error': translate('inventory.errors.no_data_submitted')}), 400
    
    product_ids = data.get('product_ids', [])
    if not product_ids or not isinstance(product_ids, list):
        return jsonify({'error': translate('inventory.errors.invalid_product_ids_array')}), 400
    
    if len(product_ids) == 0:
        return jsonify({'error': translate('inventory.errors.no_product_ids')}), 400
    
    try:
        product_ids_int = [int(pid) for pid in product_ids]
    except (ValueError, TypeError):
        return jsonify({'error': translate('inventory.errors.invalid_product_ids_numeric')}), 400
    
    products = Product.query.filter(Product.id.in_(product_ids_int)).all()
    
    if len(products) != len(product_ids_int):
        return jsonify({'error': translate('inventory.errors.some_product_ids_not_found')}), 404
    
    active_items = CheckoutItem.query.filter(
        CheckoutItem.product_id.in_(product_ids_int),
        CheckoutItem.returned_at.is_(None),
    ).all()
    
    if active_items:
        borrowed_product_ids = [i.product_id for i in active_items]
        borrowed_products = [p for p in products if p.id in borrowed_product_ids]
        product_names = [p.name for p in borrowed_products]
        return jsonify({
            'error': 'Einige Produkte können nicht gelöscht werden, da sie ausgeliehen sind.',
            'details': product_names
        }), 400
    
    moved_count = 0
    errors = []
    
    for product in products:
        product_id = product.id  # Speichere ID vor möglichem Rollback
        product_name = product.name  # Speichere Name für Fehlermeldung
        
        try:
            # Produkt aus Sets entfernen (Gerät darf trotzdem in den Papierkorb)
            ProductSetItem.query.filter_by(product_id=product_id).delete()

            from app.services.inventory import LifecycleService
            LifecycleService.change_status(
                product,
                'retired',
                current_user.id,
                reason='bulk_delete',
                force=True,
            )
            _apply_retired_folder_assignment(product)
            moved_count += 1
            
        except Exception as e:
            db.session.rollback()
            error_msg = str(e)
            current_app.logger.error(f"Fehler beim Verschieben in Papierkorb von Produkt {product_id} ({product_name}): {e}", exc_info=True)
            
            # Prüfe ob es ein Foreign Key Constraint Fehler ist
            if 'foreign key constraint' in error_msg.lower() or '1451' in error_msg:
                errors.append(f'Das Produkt "{product_name}" konnte nicht in den Papierkorb verschoben werden, da es noch in Verwendung ist.')
            else:
                errors.append(f'Fehler bei Produkt "{product_name}" (ID: {product_id}): {error_msg}')
    
    if errors:
        db.session.rollback()
        return jsonify({'error': translate('inventory.errors.delete_error'), 'details': errors}), 500
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Fehler beim Commit der Papierkorb-Verschiebung: {e}", exc_info=True)
        return jsonify({'error': 'Fehler beim Speichern der Änderungen. Bitte versuchen Sie es erneut.'}), 500
    
    return jsonify({
        'message': f'{moved_count} Produkt(e) in den Papierkorb verschoben.',
        'deleted_count': moved_count
    })


@login_required
def api_folders():
    """API: Liste aller Ordner oder neuen Ordner erstellen."""
    if request.method == 'POST':
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        description = (data.get('description') or '').strip() or None
        color = (data.get('color') or '').strip() or None
        if not name:
            return jsonify({'error': translate('inventory.errors.folder_name_required')}), 400
        existing = ProductFolder.query.filter_by(name=name).first()
        if existing:
            return jsonify({'error': translate('inventory.errors.folder_name_exists')}), 400
        folder = ProductFolder(
            name=name,
            description=description,
            color=color,
            created_by=current_user.id
        )
        db.session.add(folder)
        db.session.commit()
        return jsonify({
            'id': folder.id,
            'name': folder.name,
            'description': folder.description,
            'color': folder.color,
            'product_count': folder.product_count
        }), 201
    try:
        folders = ProductFolder.query.order_by(ProductFolder.name).all()
        return jsonify([{
            'id': f.id,
            'name': f.name,
            'description': f.description,
            'color': f.color,
            'product_count': f.product_count
        } for f in folders])
    except Exception as e:
        current_app.logger.error(f"Fehler beim Laden der Ordner: {e}", exc_info=True)
        return jsonify({'error': f'Server-Fehler: {str(e)}'}), 500


@inventory_bp.route('/api/stock', methods=['GET'])
@login_required
def api_stock():
    """API: Effiziente Abfrage des gesamten Bestands mit Such- und Filterunterstützung."""
    search = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    status = request.args.get('status', '').strip()
    
    query = Product.query
    
    if search:
        query = query.filter(
            or_(
                Product.name.ilike(f'%{search}%'),
                Product.serial_number.ilike(f'%{search}%')
            )
        )
    
    if category:
        query = query.filter_by(category=category)
    
    if status:
        query = query.filter_by(status=status)
    
    products = query.options(joinedload(Product.folder)).order_by(Product.name).all()
    
    result = []
    for p in products:
        try:
            image_path_value = None
            if p.image_path:
                if os.path.isabs(p.image_path):
                    image_path_value = os.path.basename(p.image_path)
                else:
                    image_path_value = p.image_path
            
            result.append({
                'id': p.id,
                'name': p.name,
                'category': p.category,
                'serial_number': p.serial_number,
                'status': p.status,
                'item_type': p.item_type,
                'on_hand': p.total_on_hand,
                'available': p.total_available,
                'location': p.location,
                'length': p.length,
                'length_meters': parse_length_to_meters(p.length),
                'folder_id': getattr(p, 'folder_id', None),
                'folder_name': p.folder.name if p.folder else None,
                'image_path': image_path_value,
                'qr_code_data': p.qr_code_data
            })
        except Exception as e:
            current_app.logger.error(f"Fehler beim Serialisieren von Produkt {p.id} in api_stock: {e}")
            # Normalisiere image_path auch im Fallback
            image_path_value = None
            if p.image_path:
                if os.path.isabs(p.image_path):
                    image_path_value = os.path.basename(p.image_path)
                else:
                    image_path_value = p.image_path
            # Fallback ohne Ordner-Informationen
            result.append({
                'id': p.id,
                'name': p.name,
                'category': p.category,
                'serial_number': p.serial_number,
                'status': p.status,
                'item_type': getattr(p, 'item_type', 'asset'),
                'on_hand': getattr(p, 'total_on_hand', 0),
                'available': getattr(p, 'total_available', 0),
                'location': p.location,
                'length': getattr(p, 'length', None),
                'length_meters': parse_length_to_meters(getattr(p, 'length', None)),
                'folder_id': None,
                'folder_name': None,
                'image_path': image_path_value,
                'qr_code_data': p.qr_code_data
            })
    
    return jsonify(result)


@login_required
def api_filter_options():
    """API: Gibt alle verfügbaren Filter-Optionen zurück (optional gefiltert nach Ordner)."""
    try:
        from sqlalchemy import distinct, func, extract
        
        # Hole optionalen folder_id Parameter
        folder_id_param = request.args.get('folder_id', type=int)
        
        # Basis-Query mit optionaler Ordner-Filterung
        base_query = Product.query
        if folder_id_param is not None:
            # Filtere nach Ordner (auch None für Produkte ohne Ordner)
            if folder_id_param == 0:
                # 0 bedeutet: nur Produkte ohne Ordner (Root)
                base_query = base_query.filter(Product.folder_id.is_(None))
            else:
                # Spezifischer Ordner
                base_query = base_query.filter(Product.folder_id == folder_id_param)
        
        # Verwende DISTINCT-Abfragen für bessere Performance und Korrektheit
        # Kategorien
        categories_query = base_query.with_entities(distinct(Product.category)).filter(
            Product.category.isnot(None),
            Product.category != ''
        )
        categories_result = categories_query.all()
        categories = sorted([cat[0].strip() for cat in categories_result if cat[0] and cat[0].strip()])
        
        # Zustände
        conditions_query = base_query.with_entities(distinct(Product.condition)).filter(
            Product.condition.isnot(None),
            Product.condition != ''
        )
        conditions_result = conditions_query.all()
        conditions = sorted([cond[0].strip() for cond in conditions_result if cond[0] and cond[0].strip()])
        
        # Lagerorte
        locations_query = base_query.with_entities(distinct(Product.location)).filter(
            Product.location.isnot(None),
            Product.location != ''
        )
        locations_result = locations_query.all()
        locations = sorted([loc[0].strip() for loc in locations_result if loc[0] and loc[0].strip()])
        
        # Längen
        lengths_query = base_query.with_entities(distinct(Product.length)).filter(
            Product.length.isnot(None),
            Product.length != ''
        )
        lengths_result = lengths_query.all()
        lengths_raw = [len[0].strip() for len in lengths_result if len[0] and len[0].strip()]
        
        try:
            lengths = sorted(lengths_raw, key=lambda x: (
                float(str(x).replace(',', '.').replace('m', '').replace('cm', '').replace('mm', '').strip()) 
                if str(x).replace(',', '.').replace('m', '').replace('cm', '').replace('mm', '').strip().replace('.', '').replace('-', '').replace('+', '').isdigit() 
                else float('inf'),
                str(x)
            ))
        except (ValueError, AttributeError):
            lengths = sorted(lengths_raw)
        
        # Anschaffungsjahre - verwende EXTRACT für Jahr
        years_query = base_query.with_entities(
            distinct(extract('year', Product.purchase_date))
        ).filter(
            Product.purchase_date.isnot(None)
        )
        years_result = years_query.all()
        purchase_years = sorted(
            [str(int(year[0])) for year in years_result if year[0] is not None and year[0] > 0],
            key=lambda x: int(x) if x.isdigit() else 0,
            reverse=True
        )
        
        folder_info = f"Ordner {folder_id_param}" if folder_id_param is not None else "alle Ordner"
        current_app.logger.debug(f"Filter-Optionen extrahiert für {folder_info}: {len(categories)} Kategorien, {len(conditions)} Zustände, {len(locations)} Lagerorte, {len(lengths)} Längen, {len(purchase_years)} Jahre")
        
        return jsonify({
            'categories': categories,
            'conditions': conditions,
            'locations': locations,
            'lengths': lengths,
            'purchase_years': purchase_years
        })
    except Exception as e:
        current_app.logger.error(f"Fehler beim Abrufen der Filter-Optionen: {e}", exc_info=True)
        return jsonify({'error': f'Fehler beim Abrufen der Filter-Optionen: {str(e)}'}), 500


@inventory_bp.route('/api/borrow', methods=['POST'])
@login_required
def api_borrow():
    """API: Ausleihvorgang registrieren (Checkout Compat)."""
    from app.services.inventory.checkout_service import create_checkout, serialize_checkout

    if not check_borrow_permission():
        return jsonify({'error': translate('inventory.errors.no_borrow_permission')}), 403
    
    data = request.get_json()
    
    if not data:
        return jsonify({'error': translate('inventory.errors.no_data_submitted')}), 400
    
    product_id = data.get('product_id')
    product_ids = data.get('product_ids') or ([product_id] if product_id else [])
    borrower_id = data.get('borrower_id', current_user.id)
    expected_return_date_str = data.get('expected_return_date') or data.get('end_date')
    event_name = (data.get('event_name') or 'API Ausleihe').strip()
    borrower_name = (data.get('borrower_name') or '').strip()
    
    if not product_ids or not expected_return_date_str:
        return jsonify({'error': translate('inventory.errors.product_id_return_date_required')}), 400
    
    try:
        product_ids = [int(pid) for pid in product_ids]
    except (TypeError, ValueError):
        return jsonify({'error': translate('inventory.errors.invalid_product_ids')}), 400

    try:
        if 'T' in str(expected_return_date_str):
            end_date = datetime.strptime(expected_return_date_str, '%Y-%m-%dT%H:%M')
        else:
            end_date = datetime.strptime(expected_return_date_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': translate('inventory.errors.invalid_date_format')}), 400
    
    borrower = User.query.get(borrower_id) if borrower_id else current_user
    if not borrower:
        return jsonify({'error': translate('inventory.errors.user_not_found')}), 404
    if not borrower_name:
        borrower_name = borrower.full_name

    start_raw = data.get('start_date')
    if start_raw:
        try:
            start_date = datetime.strptime(start_raw, '%Y-%m-%dT%H:%M') if 'T' in str(start_raw) else datetime.strptime(start_raw, '%Y-%m-%d')
        except ValueError:
            start_date = datetime.utcnow()
    else:
        start_date = datetime.utcnow()

    try:
        checkout = create_checkout(
            product_ids=product_ids,
            event_name=event_name,
            borrower_name=borrower_name,
            created_by_id=current_user.id,
            start_date=start_date,
            end_date=end_date,
            borrower_id=borrower.id,
        )
    except ValueError as exc:
        from app.services.inventory.checkout_service import (
            CheckoutUnavailableError,
            checkout_error_message,
        )
        payload = {'error': checkout_error_message(exc)}
        if isinstance(exc, CheckoutUnavailableError):
            payload['unavailable'] = list(exc.product_labels)
        return jsonify(payload), 400
    
    return jsonify({
        'transaction_id': checkout.id,
        'checkout_id': checkout.id,
        'transaction_number': checkout.checkout_number,
        'borrow_group_id': checkout.checkout_number,
        'qr_code_data': checkout.qr_code_data,
        'receipt_email_sent': bool(getattr(checkout, 'receipt_email_sent', False)),
        'checkout': serialize_checkout(checkout),
    }), 201


@login_required
def api_borrows():
    """API: Checkout-Items für Historie-UI (inkl. zurückgegebene).

    Non-Admins sehen nur eigene Vorgänge (borrower oder Ersteller).
    Admins sehen alle; optional mine=1 zum Filtern.
    """
    status = request.args.get('status', 'all')
    mine = request.args.get('mine', '').lower() in ('1', 'true', 'yes')
    can_list_all = bool(
        getattr(current_user, 'is_admin', False)
        or getattr(current_user, 'is_super_admin', False)
    )
    q = Checkout.query.options(
        selectinload(Checkout.items).joinedload(CheckoutItem.product),
        selectinload(Checkout.items).joinedload(CheckoutItem.source_set).selectinload(ProductSet.items).joinedload(ProductSetItem.product),
    )
    if status == 'active':
        q = q.filter(Checkout.status.in_(('active', 'partially_returned')))
    elif status == 'completed':
        q = q.filter_by(status='completed')
    elif status not in ('all', 'returned', 'overdue'):
        q = q.filter_by(status=status)
    # Serverseitig erzwingen — mine-Flag allein reicht nicht (F05)
    if mine or not can_list_all:
        q = q.filter(or_(Checkout.borrower_id == current_user.id, Checkout.created_by == current_user.id))
    checkouts = q.order_by(Checkout.start_date.desc()).all()
    payload = []
    for c in checkouts:
        for item in c.items:
            item_status = 'returned' if item.returned_at else 'active'
            is_overdue = bool(c.is_overdue and item.returned_at is None)
            if status == 'active' and item.returned_at is not None:
                continue
            if status == 'returned' and item.returned_at is None:
                continue
            if status == 'overdue' and not is_overdue:
                continue
            end_date = c.end_date.date().isoformat() if c.end_date else None
            set_id, set_name, set_members = _source_set_api_payload(item.source_set)
            payload.append({
                'id': item.id,
                'checkout_id': c.id,
                'transaction_number': c.checkout_number,
                'borrow_group_id': c.checkout_number,
                'product_id': item.product_id,
                'product_name': item.product.name if item.product else None,
                'borrower_id': c.borrower_id,
                'borrower_name': c.borrower_name,
                'created_by': c.created_by,
                'contact_email': c.contact_email,
                'event_name': c.event_name,
                'borrow_date': c.start_date.isoformat() if c.start_date else None,
                'expected_return_date': end_date,
                'is_overdue': is_overdue,
                'qr_code_data': c.qr_code_data,
                'status': item_status,
                'returned_at': item.returned_at.isoformat() if item.returned_at else None,
                'source_set_id': set_id,
                'source_set_name': set_name,
                'source_set_members': set_members,
            })
    return jsonify(payload)


@login_required
def api_borrows_my():
    """API: Meine aktuellen Checkout-Items."""
    checkouts = Checkout.query.filter(
        Checkout.borrower_id == current_user.id,
        Checkout.status.in_(('active', 'partially_returned')),
    ).order_by(Checkout.start_date.desc()).all()

    payload = []
    for c in checkouts:
        for item in c.active_items:
            payload.append({
                'id': item.id,
                'checkout_id': c.id,
                'transaction_number': c.checkout_number,
                'borrow_group_id': c.checkout_number,
                'product_id': item.product_id,
                'product_name': item.product.name if item.product else None,
                'event_name': c.event_name,
                'borrow_date': c.start_date.isoformat() if c.start_date else None,
                'expected_return_date': c.end_date.date().isoformat() if c.end_date else None,
                'is_overdue': c.is_overdue,
                'qr_code_data': c.qr_code_data,
            })
    return jsonify(payload)


@inventory_bp.route('/api/borrows/my/grouped', methods=['GET'])
@login_required
def api_borrows_my_grouped():
    """API: Meine Ausleihen gruppiert nach Checkout (für Widget)."""
    checkouts = Checkout.query.filter(
        Checkout.borrower_id == current_user.id,
        Checkout.status.in_(('active', 'partially_returned')),
    ).order_by(Checkout.start_date.desc()).all()

    result = []
    for c in checkouts:
        items = list(c.active_items)
        if not items:
            continue
        result.append({
            'borrow_group_id': c.checkout_number,
            'checkout_id': c.id,
            'event_name': c.event_name,
            'borrow_date': c.start_date.isoformat() if c.start_date else None,
            'expected_return_date': c.end_date.date().isoformat() if c.end_date else None,
            'product_count': len(items),
            'is_overdue': c.is_overdue,
            'products': [i.product.name for i in items if i.product],
            'transactions': [{
                'id': i.id,
                'transaction_number': c.checkout_number,
                'product_id': i.product_id,
                'product_name': i.product.name if i.product else None,
                'expected_return_date': c.end_date.date().isoformat() if c.end_date else None,
                'is_overdue': c.is_overdue,
                'qr_code_data': c.qr_code_data,
            } for i in items],
        })
    return jsonify(result)


@inventory_bp.route('/api/return', methods=['POST'])
@login_required
def api_return():
    """API: Rueckgabe eines oder mehrerer Checkout-Items.

    ID-Aliase:
    - item_ids / return_item_ids / checkout_item_id → CheckoutItem.id
    - checkout_id → alle aktiven Items des Checkouts
    - transaction_id (Legacy): CheckoutItem.id, sonst Checkout.id, sonst legacy_transaction_id
    - product_id / checkout_number / borrow_ref
    """
    from app.services.inventory.checkout_service import (
        find_active_checkout_item_for_product,
        resolve_return_item_ids,
        return_checkout_items,
        return_checkout_by_ref,
    )
    data = request.get_json() or {}
    item_ids = data.get('item_ids') or data.get('return_item_ids') or []
    checkout_item_id = data.get('checkout_item_id')
    checkout_id = data.get('checkout_id')
    transaction_id = data.get('transaction_id')
    checkout_ref = data.get('checkout_number') or data.get('borrow_ref') or data.get('transaction_number')
    product_id = data.get('product_id')
    mark_defective = bool(data.get('mark_defective'))

    try:
        if item_ids:
            returned = return_checkout_items(
                item_ids, mark_defective=mark_defective, actor=current_user
            )
            return jsonify({
                'success': True,
                'returned_count': len(returned),
                'return_email_sent': _return_email_ok(returned),
            })
        if checkout_item_id is not None:
            returned = return_checkout_items(
                [int(checkout_item_id)], mark_defective=mark_defective, actor=current_user
            )
            return jsonify({
                'success': True,
                'returned_count': len(returned),
                'return_email_sent': _return_email_ok(returned),
            })
        if checkout_id is not None:
            checkout = Checkout.query.get(int(checkout_id))
            if not checkout:
                return jsonify({'error': translate('inventory.errors.borrow_transaction_not_found')}), 404
            returned = return_checkout_items(
                [i.id for i in checkout.active_items],
                mark_defective=mark_defective,
                actor=current_user,
            )
            return jsonify({
                'success': True,
                'returned_count': len(returned),
                'checkout_id': checkout.id,
                'return_email_sent': _return_email_ok(returned),
            })
        if transaction_id is not None:
            # Compat: historisch Checkout-ODER-Item-ID — Auflösung wie Mobile/return-pdf
            resolved_ids = resolve_return_item_ids(int(transaction_id))
            returned = return_checkout_items(
                resolved_ids, mark_defective=mark_defective, actor=current_user
            )
            return jsonify({
                'success': True,
                'returned_count': len(returned),
                'return_email_sent': _return_email_ok(returned),
            })
        if product_id:
            item = find_active_checkout_item_for_product(int(product_id), actor=current_user)
            if not item:
                return jsonify({'error': translate('inventory.errors.no_active_borrow')}), 404
            returned = return_checkout_items(
                [item.id], mark_defective=mark_defective, actor=current_user
            )
            return jsonify({
                'success': True,
                'returned_count': len(returned),
                'return_email_sent': _return_email_ok(returned),
            })
        if checkout_ref:
            checkout = return_checkout_by_ref(str(checkout_ref), actor=current_user)
            return jsonify({
                'success': True,
                'checkout_id': checkout.id,
                'status': checkout.status,
                'return_email_sent': bool(getattr(checkout, 'return_email_sent', True)),
            })
    except PermissionError:
        db.session.rollback()
        return jsonify({'error': translate('inventory.errors.no_return_permission')}), 403
    except ValueError as exc:
        db.session.rollback()
        code = str(exc)
        key = f'inventory.errors.{code}'
        msg = translate(key)
        return jsonify({'error': msg if msg != key else code}), 400

    return jsonify({'error': translate('inventory.errors.transaction_id_required')}), 400


@inventory_bp.route('/api/borrow/<int:transaction_id>/pdf', methods=['GET'])
@login_required
@check_module_access('module_inventory')
def api_borrow_pdf(transaction_id):
    """API: Ausleihschein-PDF generieren (Checkout-ID)."""
    checkout = Checkout.query.get(transaction_id)
    if not checkout:
        # Compat: legacy borrow transaction id -> mapped checkout item
        item = CheckoutItem.query.filter_by(legacy_transaction_id=transaction_id).first()
        checkout = item.checkout if item else None
    if not checkout:
        return jsonify({'error': 'Checkout nicht gefunden.'}), 404

    from app.services.inventory.checkout_service import user_can_return_checkout
    if not user_can_return_checkout(current_user, checkout):
        return jsonify({'error': translate('inventory.errors.no_return_permission')}), 403

    pdf_buffer = BytesIO()
    generate_borrow_receipt_pdf(checkout, pdf_buffer)
    pdf_buffer.seek(0)
    filename = f"Ausleihschein_{checkout.checkout_number}.pdf"
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )


@inventory_bp.route('/api/borrow/<int:transaction_id>/return-pdf', methods=['GET'])
@login_required
@check_module_access('module_inventory')
def api_return_pdf(transaction_id):
    """API: Rückgabeschein-PDF (CheckoutItem-ID bevorzugt, sonst Checkout-ID)."""
    from app.utils.pdf_generator import generate_return_confirmation_pdf

    # Historie liefert Item-IDs — zuerst CheckoutItem prüfen (vermeidet ID-Kollision mit Checkout)
    item = CheckoutItem.query.get(transaction_id)
    checkout = item.checkout if item else None
    if not checkout:
        checkout = Checkout.query.get(transaction_id)
    if not checkout:
        legacy = CheckoutItem.query.filter_by(legacy_transaction_id=transaction_id).first()
        if legacy:
            item = legacy
            checkout = legacy.checkout
    if not checkout:
        return jsonify({'error': 'Checkout nicht gefunden.'}), 404

    from app.services.inventory.checkout_service import user_can_return_checkout
    if not user_can_return_checkout(current_user, checkout):
        return jsonify({'error': translate('inventory.errors.no_return_permission')}), 403

    source = item if item else checkout
    pdf_buffer = BytesIO()
    generate_return_confirmation_pdf(source, pdf_buffer)
    pdf_buffer.seek(0)
    filename = f"Rueckgabeschein_{checkout.checkout_number}.pdf"
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )


@inventory_bp.route('/api/print-qr-codes', methods=['POST'])
@login_required
def api_print_qr_codes():
    """API: QR-Code-Druckbogen generieren."""
    data = request.get_json()
    
    if not data or not data.get('product_ids'):
        return jsonify({'error': translate('inventory.errors.no_product_ids')}), 400
    
    try:
        product_ids = [int(pid) for pid in data['product_ids']]
        products = Product.query.filter(Product.id.in_(product_ids)).all()
        
        if not products:
            return jsonify({'error': translate('inventory.errors.no_valid_products')}), 404
        
        pdf_buffer = BytesIO()
        generate_qr_code_sheet_pdf(products, pdf_buffer)
        pdf_buffer.seek(0)
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"QR-Codes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )
    except Exception as e:
        current_app.logger.error(f"Fehler beim Generieren des QR-Code-Druckbogens: {e}")
        return jsonify({'error': translate('inventory.errors.print_sheet_error')}), 500
