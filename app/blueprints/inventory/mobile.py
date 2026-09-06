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

def verify_api_token():
    """Hilfsfunktion zur Token-Validierung für Mobile API."""
    auth_header = request.headers.get('Authorization', '')
    
    if not auth_header.startswith('Bearer '):
        return None
    
    token = auth_header.replace('Bearer ', '').strip()
    api_token = ApiToken.query.filter_by(token=token).first()
    
    if not api_token or api_token.is_expired():
        return None
    
    # Token als verwendet markieren
    api_token.mark_as_used()
    
    return api_token.user


@inventory_bp.route('/api/mobile/token', methods=['POST'])
@login_required
def api_mobile_create_token():
    """API-Token für Mobile API erstellen."""
    data = request.get_json() or {}
    name = data.get('name', 'Mobile App').strip()
    expires_in_days = data.get('expires_in_days', type=int) or None
    
    token = ApiToken.create_token(
        user_id=current_user.id,
        name=name,
        expires_in_days=expires_in_days
    )
    
    return jsonify({
        'token': token.token,
        'name': token.name,
        'expires_at': token.expires_at.isoformat() if token.expires_at else None,
        'created_at': token.created_at.isoformat()
    })


@inventory_bp.route('/api/mobile/tokens', methods=['GET'])
@login_required
def api_mobile_list_tokens():
    """Liste aller API-Tokens des aktuellen Benutzers."""
    tokens = ApiToken.query.filter_by(user_id=current_user.id).order_by(ApiToken.created_at.desc()).all()
    
    result = []
    for token in tokens:
        result.append({
            'id': token.id,
            'name': token.name,
            'expires_at': token.expires_at.isoformat() if token.expires_at else None,
            'created_at': token.created_at.isoformat(),
            'last_used_at': token.last_used_at.isoformat() if token.last_used_at else None,
            'is_expired': token.is_expired()
        })
    
    return jsonify(result)


@inventory_bp.route('/api/mobile/tokens/<int:token_id>', methods=['DELETE'])
@login_required
def api_mobile_delete_token(token_id):
    """API-Token löschen."""
    token = ApiToken.query.get_or_404(token_id)
    
    if token.user_id != current_user.id:
        return jsonify({'error': translate('inventory.errors.no_permission')}), 403
    
    db.session.delete(token)
    db.session.commit()
    
    return jsonify({'message': 'Token erfolgreich gelöscht.'})


@inventory_bp.route('/api/mobile/products', methods=['GET'])
def api_mobile_products():
    """Mobile API: Liste aller Produkte."""
    user = verify_api_token()
    if not user:
        return jsonify({'error': translate('inventory.errors.invalid_or_expired_token')}), 401
    
    products = Product.query.order_by(Product.name).all()
    result = []
    for p in products:
        result.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'category': p.category,
            'serial_number': p.serial_number,
            'status': p.status,
            'location': p.location,
            'qr_code_data': p.qr_code_data
        })
    
    return jsonify(result)


@inventory_bp.route('/api/mobile/products/<int:product_id>', methods=['GET'])
def api_mobile_product_detail(product_id):
    """Mobile API: Produktdetails."""
    user = verify_api_token()
    if not user:
        return jsonify({'error': translate('inventory.errors.invalid_or_expired_token')}), 401
    
    product = Product.query.get_or_404(product_id)
    
    return jsonify({
        'id': product.id,
        'name': product.name,
        'description': product.description,
        'category': product.category,
        'serial_number': product.serial_number,
        'condition': product.condition,
        'location': product.location,
        'length': product.length,
        'status': product.status,
        'qr_code_data': product.qr_code_data,
        'purchase_date': product.purchase_date.isoformat() if product.purchase_date else None
    })


@inventory_bp.route('/api/mobile/borrow', methods=['POST'])
def api_mobile_borrow():
    """Mobile API: Checkout erstellen (Compat)."""
    from app.services.inventory.checkout_service import create_checkout

    user = verify_api_token()
    if not user:
        return jsonify({'error': translate('inventory.errors.invalid_or_expired_token')}), 401

    if not check_borrow_permission(user):
        return jsonify({'error': translate('inventory.errors.no_borrow_permission')}), 403
    
    data = request.get_json() or {}
    product_id = data.get('product_id')
    product_ids = data.get('product_ids') or ([product_id] if product_id else [])
    borrower_id = data.get('borrower_id') or user.id
    expected_return_date_str = data.get('expected_return_date') or data.get('end_date')
    event_name = (data.get('event_name') or 'Mobile Ausleihe').strip()
    borrower_name = (data.get('borrower_name') or '').strip()
    
    if not product_ids or not expected_return_date_str:
        return jsonify({'error': translate('inventory.errors.product_id_return_date_required')}), 400
    
    try:
        product_ids = [int(pid) for pid in product_ids]
        end_date = datetime.strptime(expected_return_date_str, '%Y-%m-%d')
    except (ValueError, TypeError):
        return jsonify({'error': translate('inventory.errors.invalid_date_format_iso')}), 400
    
    borrower = User.query.get_or_404(int(borrower_id))
    if not borrower_name:
        borrower_name = borrower.full_name

    try:
        checkout = create_checkout(
            product_ids=product_ids,
            event_name=event_name,
            borrower_name=borrower_name,
            created_by_id=user.id,
            start_date=datetime.utcnow(),
            end_date=end_date,
            borrower_id=borrower.id,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    
    return jsonify({
        'message': 'Ausleihe erfolgreich erstellt.',
        'transaction_id': checkout.id,
        'checkout_id': checkout.id,
        'transaction_number': checkout.checkout_number,
        'receipt_email_sent': bool(getattr(checkout, 'receipt_email_sent', False)),
    })


@inventory_bp.route('/api/mobile/return', methods=['POST'])
def api_mobile_return():
    """Mobile API: Rückgabe (Checkout Compat + Partial)."""
    from app.services.inventory.checkout_service import return_checkout_items, find_active_checkout_item_for_product

    user = verify_api_token()
    if not user:
        return jsonify({'error': translate('inventory.errors.invalid_or_expired_token')}), 401
    
    data = request.get_json() or {}
    item_ids = data.get('item_ids') or []
    transaction_id = data.get('transaction_id')
    product_id = data.get('product_id')
    mark_defective = bool(data.get('mark_defective'))
    
    try:
        if item_ids:
            returned = return_checkout_items(item_ids, mark_defective=mark_defective, actor=user)
        elif transaction_id:
            # Compat: id kann Checkout-Item oder Checkout sein
            item = CheckoutItem.query.get(int(transaction_id))
            if item:
                returned = return_checkout_items([item.id], mark_defective=mark_defective, actor=user)
            else:
                checkout = Checkout.query.get(int(transaction_id))
                if not checkout:
                    return jsonify({'error': translate('inventory.errors.transaction_id_required')}), 400
                returned = return_checkout_items(
                    [i.id for i in checkout.active_items],
                    mark_defective=mark_defective,
                    actor=user,
                )
        elif product_id:
            item = find_active_checkout_item_for_product(int(product_id), actor=user)
            if not item:
                return jsonify({'error': translate('inventory.errors.no_active_borrow')}), 404
            returned = return_checkout_items([item.id], mark_defective=mark_defective, actor=user)
        else:
            return jsonify({'error': translate('inventory.errors.transaction_id_required')}), 400
    except PermissionError:
        return jsonify({'error': translate('inventory.errors.no_return_permission')}), 403
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    
    return jsonify({
        'message': 'Rückgabe erfolgreich registriert.',
        'returned_count': len(returned),
        'transaction_id': returned[0].id if returned else None,
        'return_email_sent': _return_email_ok(returned),
    })


@inventory_bp.route('/api/mobile/scan', methods=['POST'])
def api_mobile_scan():
    """Mobile API: QR-Code-Scanning."""
    from app.services.inventory.checkout_service import find_checkout

    user = verify_api_token()
    if not user:
        return jsonify({'error': translate('inventory.errors.invalid_or_expired_token')}), 401
    
    data = request.get_json()
    qr_data = _normalize_scanner_code((data.get('qr_data') or '').strip())
    
    if not qr_data:
        return jsonify({'error': translate('inventory.errors.qr_data_required')}), 400

    product, product_set = _lookup_product_or_set_by_scan(qr_data)
    if product:
        return jsonify({
            'type': 'product',
            'product': {
                'id': product.id,
                'name': product.name,
                'status': product.status,
                'location': product.location,
                'external_barcode': product.external_barcode,
            }
        })
    if product_set:
        return jsonify({
            'type': 'set',
            'set': {
                'id': product_set.id,
                'name': product_set.name,
                'product_count': product_set.product_count,
            }
        })
    
    # QR-Code parsen (Borrow / Checkout)
    parsed = parse_qr_code(qr_data)
    if not parsed:
        # Fallback: raw checkout number
        checkout = find_checkout(qr_data)
        if checkout:
            parsed = ('borrow', checkout.checkout_number)
        else:
            return jsonify({'error': translate('inventory.errors.invalid_qr_code')}), 400
    
    qr_type, qr_id = parsed
    
    if qr_type == 'product':
        product = Product.query.get(qr_id)
        if product:
            return jsonify({
                'type': 'product',
                'product': {
                    'id': product.id,
                    'name': product.name,
                    'status': product.status,
                    'location': product.location
                }
            })
        else:
            return jsonify({'error': translate('inventory.errors.product_not_found')}), 404
    
    elif qr_type == 'borrow':
        checkout = find_checkout(str(qr_id))
        if checkout:
            active = list(checkout.active_items)
            first = active[0] if active else None
            return jsonify({
                'type': 'borrow',
                'transaction': {
                    'id': first.id if first else checkout.id,
                    'checkout_id': checkout.id,
                    'transaction_number': checkout.checkout_number,
                    'product_name': first.product.name if first and first.product else None,
                    'borrower_name': checkout.borrower_name,
                    'event_name': checkout.event_name,
                    'status': checkout.status,
                    'expected_return_date': checkout.end_date.date().isoformat() if checkout.end_date else None,
                }
            })
        return jsonify({'error': translate('inventory.errors.transaction_not_found')}), 404
    elif qr_type == 'set':
        product_set = ProductSet.query.get(qr_id)
        if product_set:
            return jsonify({
                'type': 'set',
                'set': {
                    'id': product_set.id,
                    'name': product_set.name,
                    'product_count': product_set.product_count,
                }
            })
        return jsonify({'error': 'Set nicht gefunden.'}), 404
    
    return jsonify({'error': translate('inventory.errors.invalid_qr_code')}), 400


@inventory_bp.route('/api/mobile/statistics', methods=['GET'])
def api_mobile_statistics():
    """Mobile API: Basis-Statistiken."""
    user = verify_api_token()
    if not user:
        return jsonify({'error': translate('inventory.errors.invalid_or_expired_token')}), 401
    
    total_products = Product.query.count()
    borrowed_count = Product.query.filter_by(status='borrowed').count()
    available_count = Product.query.filter_by(status='available').count()
    
    return jsonify({
        'total_products': total_products,
        'borrowed_count': borrowed_count,
        'available_count': available_count
    })


@login_required
def api_folder_update_delete(folder_id):
    folder = ProductFolder.query.get_or_404(folder_id)
    if folder.name == RETIRED_FOLDER_NAME:
        return jsonify({'error': 'Der Papierkorb kann nicht geändert oder gelöscht werden.'}), 400
    if request.method == 'PUT':
        data = request.get_json() or {}
        new_name = (data.get('name') or '').strip()
        description = (data.get('description') or '').strip() or None
        color = (data.get('color') or '').strip() or None
        if not new_name:
            return jsonify({'error': translate('inventory.errors.folder_name_required')}), 400
        if new_name == RETIRED_FOLDER_NAME:
            return jsonify({'error': 'Der Name „Papierkorb“ ist für den Systemordner reserviert.'}), 400
        existing = ProductFolder.query.filter(ProductFolder.id != folder_id, ProductFolder.name == new_name).first()
        if existing:
            return jsonify({'error': translate('inventory.errors.folder_name_exists')}), 400
        folder.name = new_name
        folder.description = description
        folder.color = color
        db.session.commit()
        return jsonify({
            'id': folder.id,
            'name': folder.name,
            'description': folder.description,
            'color': folder.color,
            'product_count': folder.product_count
        })
    # DELETE
    # Entferne Ordnerbezug aus Produkten
    for product in folder.products:
        product.folder_id = None
    db.session.delete(folder)
    db.session.commit()
    return jsonify({'success': True})


@login_required
def api_categories():
    """API: Kategorien abrufen oder erstellen."""
    if request.method == 'POST':
        data = request.get_json() or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error': translate('inventory.errors.category_name_required')}), 400
        categories = get_inventory_categories()
        if name in categories:
            return jsonify({'error': translate('inventory.errors.category_name_exists')}), 400
        categories.append(name)
        save_inventory_categories(categories)
        return jsonify({'name': name}), 201
    categories = get_inventory_categories()
    return jsonify(sorted(categories))


@login_required
def api_category_update_delete(category_name):
    original_name = unquote(category_name).strip()
    if not original_name:
        return jsonify({'error': translate('inventory.errors.invalid_category_name')}), 400
    categories = get_inventory_categories()
    if original_name not in categories:
        return jsonify({'error': translate('inventory.errors.category_not_found')}), 404
    if request.method == 'PUT':
        data = request.get_json() or {}
        new_name = (data.get('name') or '').strip()
        if not new_name:
            return jsonify({'error': translate('inventory.errors.new_category_name_required')}), 400
        if new_name != original_name and new_name in categories:
            return jsonify({'error': translate('inventory.errors.category_name_exists')}), 400
        updated_categories = [new_name if c == original_name else c for c in categories]
        save_inventory_categories(updated_categories)
        Product.query.filter_by(category=original_name).update({'category': new_name}, synchronize_session=False)
        db.session.commit()
        return jsonify({'name': new_name})
    # DELETE
    updated_categories = [c for c in categories if c != original_name]
    save_inventory_categories(updated_categories)
    # Entferne Kategorie aus Produkten
    Product.query.filter_by(category=original_name).update({'category': None}, synchronize_session=False)
    db.session.commit()
    return jsonify({'success': True})
