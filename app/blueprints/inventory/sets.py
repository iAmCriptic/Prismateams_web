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

@inventory_bp.route('/sets')
@login_required
def sets():
    """Produktsets Übersicht."""
    return render_template(
        'inventory/sets.html',
        can_borrow=check_borrow_permission(),
    )


@inventory_bp.route('/sets/new', methods=['GET', 'POST'])
@login_required
def set_new():
    """Neues Produktset erstellen."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip() or None
        
        if not name:
            flash(translate('inventory.flash.enter_set_name'), 'danger')
            products = Product.query.order_by(Product.name).all()
            products_data = [{'id': p.id, 'name': p.name} for p in products]
            return render_template('inventory/set_form.html', products=products, products_data=products_data)
        
        product_ids = request.form.getlist('product_ids')
        quantities = request.form.getlist('quantities')
        
        if not product_ids:
            flash(translate('inventory.flash.select_at_least_one_product'), 'danger')
            products = Product.query.order_by(Product.name).all()
            products_data = [{'id': p.id, 'name': p.name} for p in products]
            return render_template('inventory/set_form.html', products=products, products_data=products_data)
        
        # Set erstellen
        product_set = ProductSet(
            name=name,
            description=description,
            created_by=current_user.id
        )
        db.session.add(product_set)
        db.session.flush()
        
        for i, product_id in enumerate(product_ids):
            try:
                product_id_int = int(product_id)
                quantity = int(quantities[i]) if i < len(quantities) and quantities[i] else 1
                
                product = Product.query.get(product_id_int)
                if not product:
                    continue
                
                set_item = ProductSetItem(
                    set_id=product_set.id,
                    product_id=product_id_int,
                    quantity=quantity
                )
                db.session.add(set_item)
            except (ValueError, IndexError):
                continue
        
        db.session.commit()
        flash(_('inventory.flash.set_created', name=name), 'success')
        return redirect(url_for('inventory.sets'))
    
    # GET: Formular anzeigen
    products = Product.query.order_by(Product.name).all()
    # Konvertiere Produkte zu Dictionaries für JSON-Serialisierung
    products_data = [{'id': p.id, 'name': p.name} for p in products]
    return render_template('inventory/set_form.html', products=products, products_data=products_data)


@inventory_bp.route('/sets/<int:set_id>')
@login_required
def set_view(set_id):
    """Produktset Details anzeigen."""
    product_set = ProductSet.query.get_or_404(set_id)
    available_count = sum(
        1 for item in product_set.items
        if item.product and item.product.status == 'available'
    )
    return render_template(
        'inventory/set_view.html',
        product_set=product_set,
        available_count=available_count,
    )


@inventory_bp.route('/sets/<int:set_id>/qr-code')
@login_required
def set_qr_code(set_id):
    """QR-Code für ein Produktset anzeigen."""
    product_set = ProductSet.query.get_or_404(set_id)
    qr_data = generate_set_qr_code(set_id)
    
    qr_image_bytes = generate_qr_code_bytes(qr_data)
    
    from flask import Response
    return Response(qr_image_bytes, mimetype='image/png')


@inventory_bp.route('/sets/<int:set_id>/edit', methods=['GET', 'POST'])
@login_required
def set_edit(set_id):
    """Produktset bearbeiten."""
    product_set = ProductSet.query.get_or_404(set_id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip() or None
        
        if not name:
            flash(_('inventory.flash.set_name_required'), 'danger')
            products = Product.query.order_by(Product.name).all()
            products_data = [{'id': p.id, 'name': p.name} for p in products]
            return render_template('inventory/set_form.html', product_set=product_set, products=products, products_data=products_data)
        
        product_set.name = name
        product_set.description = description
        
        product_ids = request.form.getlist('product_ids')
        quantities = request.form.getlist('quantities')
        
        # Alte Items löschen
        ProductSetItem.query.filter_by(set_id=product_set.id).delete()
        
        # Neue Items hinzufügen
        for i, product_id in enumerate(product_ids):
            try:
                product_id_int = int(product_id)
                quantity = int(quantities[i]) if i < len(quantities) and quantities[i] else 1
                
                product = Product.query.get(product_id_int)
                if not product:
                    continue
                
                set_item = ProductSetItem(
                    set_id=product_set.id,
                    product_id=product_id_int,
                    quantity=quantity
                )
                db.session.add(set_item)
            except (ValueError, IndexError):
                continue
        
        db.session.commit()
        flash(_('inventory.flash.set_updated', name=name), 'success')
        return redirect(url_for('inventory.set_view', set_id=product_set.id))
    
    # GET: Formular anzeigen
    products = Product.query.order_by(Product.name).all()
    products_data = [{'id': p.id, 'name': p.name} for p in products]
    return render_template('inventory/set_form.html', product_set=product_set, products=products, products_data=products_data)


@inventory_bp.route('/sets/<int:set_id>/delete', methods=['POST'])
@login_required
def set_delete(set_id):
    """Produktset löschen."""
    product_set = ProductSet.query.get_or_404(set_id)
    
    # Nur Admin oder Ersteller kann löschen
    if not current_user.is_admin and product_set.created_by != current_user.id:
        flash(translate('inventory.flash.no_permission_delete_set'), 'danger')
        return redirect(url_for('inventory.sets'))
    
    name = product_set.name
    db.session.delete(product_set)
    db.session.commit()
    
    flash(f'Produktset "{name}" wurde erfolgreich gelöscht.', 'success')
    return redirect(url_for('inventory.sets'))


@inventory_bp.route('/sets/<int:set_id>/borrow', methods=['GET', 'POST'])
@login_required
def set_borrow(set_id):
    """Set-Ausleihe → Quick Scan Warenkorb."""
    if not check_borrow_permission():
        flash(_('inventory.flash.no_borrow_permission'), 'danger')
        return redirect(url_for('inventory.sets'))
    
    product_set = ProductSet.query.get_or_404(set_id)
    cart = session.get('borrow_cart', [])
    added = 0
    failed = []
    added_ids = []
    for item in product_set.items:
        product = item.product
        if not product:
            continue
        if product.status != 'available':
            failed.append(product.name)
            continue
        if product.id not in cart:
            cart.append(product.id)
            added += 1
            added_ids.append(product.id)
        elif product.id not in added_ids:
            added_ids.append(product.id)
    session['borrow_cart'] = cart
    session.modified = True
    in_cart_from_set = [pid for pid in cart if any(i.product_id == pid for i in product_set.items)]
    _mark_cart_products_from_set(in_cart_from_set, product_set)
    if added:
        flash(_('inventory.flash.set_borrow_success', name=product_set.name, count=added), 'success')
    if failed:
        flash(_('inventory.flash.set_borrow_partial', products=', '.join(failed)), 'warning')
    if not added and not failed:
        flash(_('inventory.flash.no_available_products'), 'danger')
        return redirect(url_for('inventory.sets'))
    return redirect(url_for('inventory.borrow_scanner'))


@inventory_bp.route('/api/sets', methods=['GET'])
@login_required
def api_sets():
    """API: Liste aller Produktsets."""
    sets = ProductSet.query.order_by(ProductSet.name).all()
    result = []
    for s in sets:
        available_count = sum(
            1 for item in s.items
            if item.product and item.product.status == 'available'
        )
        can_edit = bool(current_user.is_admin or s.created_by == current_user.id)
        creator_name = None
        if s.creator is not None:
            creator_name = getattr(s.creator, 'full_name', None) or getattr(s.creator, 'username', None)
        result.append({
            'id': s.id,
            'name': s.name,
            'description': s.description,
            'product_count': s.product_count,
            'available_count': available_count,
            'created_at': s.created_at.isoformat() if s.created_at else None,
            'created_by': s.created_by,
            'creator_name': creator_name,
            'can_edit': can_edit,
            'can_delete': can_edit,
        })
    return jsonify(result)


@inventory_bp.route('/api/sets/<int:set_id>', methods=['GET'])
@login_required
def api_set_detail(set_id):
    """API: Details eines Produktsets."""
    product_set = ProductSet.query.get_or_404(set_id)
    items = []
    for item in product_set.items:
        items.append({
            'product_id': item.product_id,
            'product_name': item.product.name if item.product else None,
            'quantity': item.quantity,
            'status': item.product.status if item.product else None,
        })

    can_edit = bool(current_user.is_admin or product_set.created_by == current_user.id)
    return jsonify({
        'id': product_set.id,
        'name': product_set.name,
        'description': product_set.description,
        'items': items,
        'product_count': product_set.product_count,
        'available_count': sum(1 for i in items if i.get('status') == 'available'),
        'created_at': product_set.created_at.isoformat() if product_set.created_at else None,
        'created_by': product_set.created_by,
        'can_edit': can_edit,
        'can_delete': can_edit,
    })


@inventory_bp.route('/api/sets/bulk-borrow', methods=['POST'])
@login_required
def api_sets_bulk_borrow():
    """API: Mehrere Sets in den Ausleih-Warenkorb legen."""
    if not check_borrow_permission():
        return jsonify({'error': translate('inventory.flash.no_borrow_permission')}), 403

    data = request.get_json(silent=True) or {}
    set_ids = data.get('set_ids', [])
    if not set_ids or not isinstance(set_ids, list):
        return jsonify({'error': translate('inventory.errors.invalid_set_ids')}), 400

    try:
        set_ids_int = [int(sid) for sid in set_ids]
    except (ValueError, TypeError):
        return jsonify({'error': translate('inventory.errors.invalid_set_ids')}), 400

    product_sets = ProductSet.query.filter(ProductSet.id.in_(set_ids_int)).all()
    if not product_sets:
        return jsonify({'error': translate('inventory.errors.product_or_set_not_found')}), 404

    cart = session.get('borrow_cart', [])
    added = 0
    failed = []
    for product_set in product_sets:
        set_product_ids = []
        for item in product_set.items:
            product = item.product
            if not product:
                continue
            if product.status != 'available':
                failed.append(product.name)
                continue
            if product.id not in cart:
                cart.append(product.id)
                added += 1
            set_product_ids.append(product.id)
        in_cart_from_set = [pid for pid in cart if pid in set_product_ids]
        _mark_cart_products_from_set(in_cart_from_set, product_set)

    session['borrow_cart'] = cart
    session.modified = True

    if not added:
        return jsonify({
            'error': translate('inventory.flash.no_available_products'),
            'failed': failed,
        }), 400

    return jsonify({
        'ok': True,
        'added': added,
        'failed': failed,
        'redirect': url_for('inventory.borrow_scanner'),
        'message': translate('inventory.flash.sets_bulk_borrow_success', count=added),
    })


@inventory_bp.route('/api/sets/bulk-delete', methods=['POST'])
@login_required
def api_sets_bulk_delete():
    """API: Mehrere Produktsets löschen."""
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({'error': translate('inventory.errors.guests_cannot_delete')}), 403

    data = request.get_json(silent=True) or {}
    set_ids = data.get('set_ids', [])
    if not set_ids or not isinstance(set_ids, list):
        return jsonify({'error': translate('inventory.errors.invalid_set_ids')}), 400

    try:
        set_ids_int = [int(sid) for sid in set_ids]
    except (ValueError, TypeError):
        return jsonify({'error': translate('inventory.errors.invalid_set_ids')}), 400

    product_sets = ProductSet.query.filter(ProductSet.id.in_(set_ids_int)).all()
    if not product_sets:
        return jsonify({'error': translate('inventory.errors.product_or_set_not_found')}), 404

    deleted = 0
    skipped = []
    for product_set in product_sets:
        if not current_user.is_admin and product_set.created_by != current_user.id:
            skipped.append(product_set.name)
            continue
        db.session.delete(product_set)
        deleted += 1

    if deleted == 0:
        return jsonify({'error': translate('inventory.flash.set_no_delete_permission')}), 403

    db.session.commit()
    return jsonify({
        'ok': True,
        'deleted_count': deleted,
        'skipped': skipped,
        'message': translate('inventory.flash.sets_bulk_deleted', count=deleted),
    })
