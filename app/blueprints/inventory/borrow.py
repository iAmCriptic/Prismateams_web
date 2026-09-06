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

@inventory_bp.route('/borrow-multiple', methods=['GET', 'POST'])
@login_required
def borrow_multiple():
    """Mehrfachausleihe → Quick Scan Warenkorb (Checkout-Flow)."""
    if not check_borrow_permission():
        flash(_('inventory.flash.no_borrow_permission'), 'danger')
        return redirect(url_for('inventory.stock'))

    product_ids_str = request.args.get('product_ids', '') if request.method == 'GET' else request.form.get('product_ids', '')
    if not product_ids_str:
        flash(_('inventory.flash.no_products_selected'), 'danger')
        return redirect(url_for('inventory.stock'))

    try:
        product_ids = [int(pid) for pid in product_ids_str.split(',')]
    except ValueError:
        flash(_('inventory.flash.invalid_product_ids'), 'danger')
        return redirect(url_for('inventory.stock'))

    products = Product.query.filter(Product.id.in_(product_ids)).all()
    unavailable_products = [p for p in products if p.status != 'available']
    if unavailable_products:
        flash(_('inventory.flash.products_unavailable', products=', '.join([p.name for p in unavailable_products])), 'danger')
        return redirect(url_for('inventory.stock'))
    if not products:
        flash(_('inventory.flash.no_valid_products'), 'danger')
        return redirect(url_for('inventory.stock'))

    cart = session.get('borrow_cart', [])
    for p in products:
        if p.id not in cart:
            cart.append(p.id)
        if p.item_type == 'consumable':
            _set_cart_qty_for_product(p.id, _get_cart_qty_for_product(p.id) + 1)
    session['borrow_cart'] = cart
    session.modified = True
    flash(_('inventory.flash.product_added_to_cart'), 'info')
    return redirect(url_for('inventory.borrow_scanner'))


@inventory_bp.route('/products/<int:product_id>/borrow', methods=['GET', 'POST'])
@login_required
@check_module_access('module_inventory')
def product_borrow(product_id):
    """Einzelausleihe -> Quick Scan mit vorgefuelltem Warenkorb."""
    if not check_borrow_permission():
        flash(_('inventory.flash.no_borrow_permission'), 'danger')
        return redirect(url_for('inventory.stock'))
    product = Product.query.get_or_404(product_id)
    if product.status != 'available':
        flash(_('inventory.errors.product_not_available'), 'danger')
        return redirect(url_for('inventory.stock'))
    cart = session.get('borrow_cart', [])
    if product.item_type == 'consumable':
        current_qty = _get_cart_qty_for_product(product.id)
        if int(product.total_available or 0) <= current_qty:
            flash(f'Nicht genug Bestand für "{product.name}".', 'danger')
            return redirect(url_for('inventory.stock'))
        _set_cart_qty_for_product(product.id, current_qty + 1)
    if product.id not in cart:
        cart.append(product.id)
        session['borrow_cart'] = cart
        session.modified = True
    flash(_('inventory.flash.product_added_to_cart'), 'info')
    return redirect(url_for('inventory.borrow_scanner'))


@inventory_bp.route('/borrows')
@login_required
def borrows():
    """Ausleih-Listen-Ansicht."""
    return render_template('inventory/borrows.html')


@inventory_bp.route('/return', methods=['GET', 'POST'])
@login_required
@check_module_access('module_inventory')
def return_item():
    """Legacy-Rückgabe → Ausleihe / Rückgabe (Deep-Link mit QR/Nummer)."""
    args = {}
    ref = (
        request.args.get('transaction_number')
        or request.args.get('checkout_number')
        or request.form.get('transaction_number')
        or request.form.get('checkout_number')
        or request.form.get('qr_code')
        or ''
    ).strip()
    if ref:
        args['transaction_number'] = ref
    return redirect(url_for('inventory.inventory_checkout', **args))


@inventory_bp.route('/return/complete', methods=['POST'])
@login_required
def return_complete_borrow():
    """Komplette Rueckgabe eines Checkout-Vorgangs."""
    from app.services.inventory.checkout_service import return_checkout_by_ref

    borrow_ref = request.form.get('borrow_ref', '').strip()
    if not borrow_ref:
        flash(_('inventory.flash.no_active_borrow'), 'danger')
        return redirect(url_for('inventory.dashboard'))

    try:
        checkout = return_checkout_by_ref(borrow_ref)
    except ValueError:
        flash(_('inventory.flash.no_active_borrow'), 'danger')
        return redirect(url_for('inventory.dashboard'))

    _flash_return_email(checkout)
    return redirect(url_for('inventory.dashboard'))


@inventory_bp.route('/product-scan')
@login_required
@check_module_access('module_inventory')
def product_scan():
    """Scan & Prüfung: Artikel scannen und Felder/Docs bearbeiten."""
    return render_template(
        'inventory/product_scan.html',
        manuals=_accessible_manuals(),
    )


@inventory_bp.route('/api/product-scan', methods=['POST'])
@login_required
@check_module_access('module_inventory')
def api_product_scan():
    """Lookup per Scan/Inventar-Nr. ohne Side-Effects (kein Cart, keine Inventur)."""
    data = request.get_json(silent=True) or {}
    code = _normalize_scanner_code(
        data.get('code') or data.get('qr_code') or request.form.get('qr_code') or ''
    )
    if not code:
        return jsonify({'error': translate('inventory.errors.qr_data_required')}), 400

    product, product_set = _lookup_product_or_set_by_scan(code)
    if product_set and not product:
        return jsonify({
            'ok': False,
            'type': 'set',
            'error': translate('inventory.product_scan.errors.scan_set'),
            'set': {
                'id': product_set.id,
                'name': product_set.name,
            },
        }), 400

    if not product:
        return jsonify({
            'ok': False,
            'error': translate('inventory.errors.product_not_found'),
        }), 404

    product = Product.query.options(joinedload(Product.folder)).get(product.id) or product
    return jsonify({
        'ok': True,
        'type': 'product',
        'product': _serialize_product_api(product),
    })


@inventory_bp.route('/borrow-scanner', methods=['GET', 'POST'])
@login_required
def borrow_scanner():
    """Ausleihen geben - Scanner-Seite mit Warenkorb."""
    if not check_borrow_permission():
        if request.method == 'POST':
            return jsonify({'error': translate('inventory.errors.no_borrow_permission')}), 403
        flash(translate('inventory.flash.no_borrow_permission'), 'danger')
        return redirect(url_for('inventory.dashboard'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        current_app.logger.debug(f'borrow_scanner POST: action={action}, qr_code={request.form.get("qr_code", "")[:50]}')
        
        if not action:
            return jsonify({'error': translate('inventory.errors.no_action_specified')}), 400
        
        if action == 'add_to_cart':
            from app.services.inventory.checkout_service import (
                looks_like_return_qr,
                return_checkout_by_ref,
                find_checkout,
            )
            qr_code = _normalize_scanner_code(request.form.get('qr_code', ''))
            product_id = request.form.get('product_id')
            quantity_raw = request.form.get('quantity', '1')
            try:
                requested_quantity = max(1, int(quantity_raw))
            except (TypeError, ValueError):
                requested_quantity = 1
            
            product = None
            product_set = None
            
            if qr_code:
                # 1) Inventar-Nr. (Esto) zuerst — vor numerischer Produkt-ID
                product = _find_product_by_external_barcode(qr_code)
                if product:
                    current_app.logger.debug(f'Inventar-Nr. Treffer: {product.id}')

                parsed = parse_qr_code(qr_code) if not product else None
                current_app.logger.debug(f'QR-Code geparst: {parsed}, Original: {qr_code}')
                if not product and parsed:
                    qr_type, qr_id = parsed
                    if qr_type == 'borrow':
                        try:
                            checkout = return_checkout_by_ref(str(qr_id) if qr_id else qr_code)
                            return jsonify({
                                'success': True,
                                'is_return': True,
                                'checkout_id': checkout.id,
                                'checkout_number': checkout.checkout_number,
                                'returned_count': len(checkout.returned_items),
                                'status': checkout.status,
                                'return_email_sent': bool(getattr(checkout, 'return_email_sent', True)),
                            })
                        except ValueError as exc:
                            return jsonify({'error': str(exc), 'is_return': True}), 400
                    if qr_type == 'product':
                        product = Product.query.get(qr_id)
                        current_app.logger.debug(f'Produkt gefunden: {product.id if product else None}')
                    elif qr_type == 'set':
                        product_set = _product_set_query().get(qr_id)
                        current_app.logger.debug(f'Set gefunden: {product_set.id if product_set else None}')
                elif not product and looks_like_return_qr(qr_code):
                    try:
                        checkout = return_checkout_by_ref(qr_code)
                        return jsonify({
                            'success': True,
                            'is_return': True,
                            'checkout_id': checkout.id,
                            'checkout_number': checkout.checkout_number,
                            'returned_count': len([i for i in checkout.items if i.returned_at]),
                            'status': checkout.status,
                            'return_email_sent': bool(getattr(checkout, 'return_email_sent', True)),
                        })
                    except ValueError as exc:
                        return jsonify({'error': str(exc), 'is_return': True}), 400
                elif not product and not product_set and _can_use_as_numeric_product_id(qr_code):
                    try:
                        product = Product.query.get(int(qr_code))
                        current_app.logger.debug(
                            f'Direkte Produkt-ID: {qr_code}, Produkt gefunden: {product.id if product else None}'
                        )
                    except (ValueError, TypeError):
                        pass

                # Klartext: Produkt- oder Set-Name (exakt, sonst eindeutiger Teiltreffer)
                if not product and not product_set and qr_code:
                    name_q = qr_code.strip()
                    looks_like_code = bool(
                        parse_qr_code(name_q)
                        or looks_like_return_qr(name_q)
                        or name_q.isdigit()
                        or _find_product_by_external_barcode(name_q)
                    )
                    if not looks_like_code:
                        product = Product.query.filter(Product.name.ilike(name_q)).first()
                        if not product:
                            product_set = _product_set_query().filter(ProductSet.name.ilike(name_q)).first()
                        if not product and not product_set:
                            product_hits = Product.query.filter(Product.name.ilike(f'%{name_q}%')).limit(5).all()
                            set_hits = _product_set_query().filter(ProductSet.name.ilike(f'%{name_q}%')).limit(5).all()
                            if len(product_hits) == 1 and not set_hits:
                                product = product_hits[0]
                            elif len(set_hits) == 1 and not product_hits:
                                product_set = set_hits[0]
            elif product_id:
                try:
                    product = Product.query.get(int(product_id))
                    current_app.logger.debug(f'Produkt-ID aus Form: {product_id}, Produkt gefunden: {product.id if product else None}')
                except (ValueError, TypeError):
                    current_app.logger.debug(f'Ungültige Produkt-ID: {product_id}')
                    pass  # Keine gültige Produkt-ID
            
            if product_set:
                cart = session.get('borrow_cart', [])
                added_products = []
                unavailable_products = []
                product_quantities = {}
                
                for item in product_set.items:
                    product = item.product
                    if product:
                        if product.id not in product_quantities:
                            product_quantities[product.id] = {
                                'product': product,
                                'quantity': 0,
                                'added': 0,
                                'was_in_cart': product.id in cart
                            }
                        
                        for _ in range(item.quantity):
                            if product.status == 'available':
                                if product.id not in cart:
                                    cart.append(product.id)
                                    product_quantities[product.id]['added'] += 1
                            else:
                                if product.id not in [p['id'] for p in unavailable_products]:
                                    unavailable_products.append({
                                        'id': product.id,
                                        'name': product.name,
                                        'status': product.status
                                    })
                            product_quantities[product.id]['quantity'] += 1
                
                for product_id, info in product_quantities.items():
                    added_products.append({
                        'id': info['product'].id,
                        'name': info['product'].name,
                        'category': info['product'].category,
                        'quantity': info['quantity'],  # Gesamtmenge im Set
                        'added': info['added'],  # Anzahl die neu hinzugefügt wurden
                        'was_in_cart': info['was_in_cart'],  # Ob bereits im Warenkorb
                        'source_set': {
                            'id': product_set.id,
                            'name': product_set.name,
                            'members': _serialize_set_members(product_set),
                        },
                    })

                session['borrow_cart'] = cart
                session.modified = True  # Stelle sicher, dass Session gespeichert wird
                added_ids = [p['id'] for p in added_products if p.get('added', 0) > 0 or p.get('was_in_cart')]
                # Alle Set-Produkte im Warenkorb als Set markieren
                in_cart_ids = [pid for pid in cart if pid in product_quantities]
                _mark_cart_products_from_set(in_cart_ids, product_set)

                return jsonify({
                    'success': True,
                    'is_set': True,
                    'set': {
                        'id': product_set.id,
                        'name': product_set.name,
                        'description': product_set.description,
                        'members': _serialize_set_members(product_set),
                    },
                    'added_products': added_products,
                    'unavailable_products': unavailable_products,
                    'cart_count': _cart_total_count(cart)
                })
            
            if not product:
                current_app.logger.warning(f'Produkt nicht gefunden für QR-Code: {qr_code}')
                return jsonify({'error': translate('inventory.errors.product_or_set_not_found')}), 404
            
            current_app.logger.debug(f'Produkt Status: {product.status}, ID: {product.id}, Name: {product.name}')
            if product.status != 'available':
                current_app.logger.warning(f'Produkt nicht verfügbar: {product.id}, Status: {product.status}')
                blocked = product.status in ('borrowed', 'in_repair', 'defective', 'missing', 'retired')
                return jsonify({
                    'error': f'Alarm: Artikel „{product.name}“ ist nicht ausleihbar (Status: {product.status}).',
                    'blocked': blocked,
                    'status': product.status,
                    'product_id': product.id,
                    'product_name': product.name,
                }), 400
            
            cart = session.get('borrow_cart', [])
            if product.item_type == 'consumable':
                current_qty = _get_cart_qty_for_product(product.id)
                max_addable = max(0, int(product.total_available or 0) - current_qty)
                if requested_quantity > max_addable:
                    return jsonify({
                        'error': f'Nicht genug Bestand für "{product.name}". Verfügbar: {max_addable}.',
                        'blocked': True,
                        'status': product.status,
                        'product_id': product.id,
                        'product_name': product.name,
                    }), 400
                _set_cart_qty_for_product(product.id, current_qty + requested_quantity)
                if product.id not in cart:
                    cart.append(product.id)
                    session['borrow_cart'] = cart
                    session.modified = True
            else:
                if product.id not in cart:
                    cart.append(product.id)
                    session['borrow_cart'] = cart
                    session.modified = True  # Stelle sicher, dass Session gespeichert wird
            
            return jsonify({
                'success': True,
                'is_set': False,
                'product': {
                    'id': product.id,
                    'name': product.name,
                    'category': product.category,
                    'item_type': product.item_type,
                    'cart_quantity': _get_cart_qty_for_product(product.id) if product.item_type == 'consumable' else 1,
                },
                'cart_count': _cart_total_count(cart)
            })
        
        elif action == 'remove_from_cart':
            product_id = int(request.form.get('product_id'))
            cart = session.get('borrow_cart', [])
            if product_id in cart:
                cart.remove(product_id)
                session['borrow_cart'] = cart
                session.modified = True  # Stelle sicher, dass Session gespeichert wird
            _clear_cart_set_meta_for_product(product_id)
            return jsonify({'success': True, 'cart_count': _cart_total_count(cart)})

        elif action == 'update_cart_quantity':
            product_id = int(request.form.get('product_id'))
            quantity = int(request.form.get('quantity', 1))
            if quantity < 0:
                return jsonify({'error': 'Ungültige Menge.'}), 400
            product = Product.query.get(product_id)
            if not product:
                return jsonify({'error': translate('inventory.errors.product_not_found')}), 404
            if product.item_type != 'consumable':
                return jsonify({'error': 'Mengenanpassung nur für Kabel/Mengenartikel möglich.'}), 400
            cart = session.get('borrow_cart', [])
            current_qty = _get_cart_qty_for_product(product.id)
            max_available = int(product.total_available or 0) + current_qty
            if quantity > max_available:
                return jsonify({'error': f'Maximal verfügbar: {max_available}'}), 400
            if quantity == 0:
                if product.id in cart:
                    cart.remove(product.id)
                    session['borrow_cart'] = cart
                _clear_cart_set_meta_for_product(product.id)
            else:
                if product.id not in cart:
                    cart.append(product.id)
                    session['borrow_cart'] = cart
                _set_cart_qty_for_product(product.id, quantity)
            session.modified = True
            return jsonify({'success': True, 'cart_count': _cart_total_count(session.get('borrow_cart', []))})
        
        elif action == 'clear_cart':
            session.pop('borrow_cart', None)
            _clear_all_cart_set_meta()
            session.modified = True
            return jsonify({'success': True})
        else:
            current_app.logger.warning(f'Unbekannte Aktion in borrow_scanner: {action}')
            return jsonify({'error': f'Unbekannte Aktion: {action}'}), 400
    
    cart_product_ids = session.get('borrow_cart', [])
    cart_products = _ordered_cart_products(cart_product_ids)
    
    users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all()
    
    return render_template('inventory/borrow_scanner.html', cart_products=cart_products, users=users, cart_count=_cart_total_count(cart_product_ids))


@inventory_bp.route('/borrow-scanner/checkout', methods=['POST'])
@login_required
def borrow_scanner_checkout():
    """Quick Scan: Warenkorb ohne Pflicht-Kopfdaten ausleihen."""
    from app.services.inventory.checkout_service import create_checkout

    if not check_borrow_permission():
        flash(_('inventory.flash.no_borrow_permission'), 'danger')
        return redirect(url_for('inventory.borrow_scanner'))
    
    cart_product_ids = session.get('borrow_cart', [])
    cart_products = _ordered_cart_products(cart_product_ids)
    consumable_quantities = {
        p.id: int(getattr(p, 'cart_quantity', 0) or 0)
        for p in cart_products
        if p.item_type == 'consumable'
    }
    asset_product_ids = [p.id for p in cart_products if p.item_type != 'consumable']
    if not asset_product_ids and not consumable_quantities:
        flash(_('inventory.flash.no_products_to_borrow'), 'danger')
        return redirect(url_for('inventory.borrow_scanner'))

    event_name = request.form.get('event_name', '').strip()
    end_date_str = request.form.get('end_date', '').strip()
    start_date = datetime.utcnow()
    end_date = None
    if end_date_str:
        try:
            if 'T' in end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')
            else:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        except ValueError:
            flash(_('inventory.flash.invalid_date_format'), 'danger')
            return redirect(url_for('inventory.borrow_scanner'))

    try:
        checkout = create_checkout(
            product_ids=asset_product_ids,
            event_name=event_name,
            borrower_name=current_user.full_name,
            created_by_id=current_user.id,
            start_date=start_date,
            end_date=end_date,
            borrower_id=current_user.id,
            require_event=False,
            require_end_date=False,
            product_source_sets=_cart_product_source_sets_map(),
            consumable_quantities=consumable_quantities,
        )
    except ValueError as exc:
        code = str(exc)
        flash(_(f'inventory.flash.{code}') if code else _('inventory.flash.borrow_failed'), 'danger')
        return redirect(url_for('inventory.borrow_scanner'))

    session.pop('borrow_cart', None)
    _clear_all_cart_set_meta()
    flash(_('inventory.flash.borrow_success', count=len(checkout.items)), 'success')
    _flash_checkout_receipt_email(checkout)
    return redirect(url_for('inventory.borrows'))


@inventory_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def inventory_checkout():
    """Ausleihe / Rückgabe mit Kopfdaten (Projekt, Verantwortlicher, Zeitraum)."""
    if not check_borrow_permission():
        if request.method == 'POST':
            return jsonify({'error': translate('inventory.errors.no_borrow_permission')}), 403
        flash(translate('inventory.flash.no_borrow_permission'), 'danger')
        return redirect(url_for('inventory.dashboard'))

    # Same cart + scan POST handling as Quick Scan
    if request.method == 'POST':
        return borrow_scanner()

    cart_product_ids = session.get('borrow_cart', [])
    cart_products = _ordered_cart_products(cart_product_ids)
    users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all()
    users_payload = [
        {
            'id': u.id,
            'name': u.full_name,
            'email': u.email or '',
        }
        for u in users
    ]
    return render_template(
        'inventory/checkout.html',
        cart_products=cart_products,
        users=users,
        users_json=users_payload,
        preset_ref=request.args.get('transaction_number') or request.args.get('checkout_number') or '',
        preset_event_name=request.args.get('event_name', ''),
        preset_borrower_name=request.args.get('borrower_name', ''),
        preset_borrower_id=request.args.get('borrower_id', ''),
        preset_contact_email=request.args.get('contact_email', ''),
        preset_event_id=request.args.get('event_id', ''),
        preset_event_appointment_id=request.args.get('event_appointment_id', ''),
        cart_count=_cart_total_count(cart_product_ids),
    )


@inventory_bp.route('/checkout/confirm', methods=['POST'])
@login_required
def inventory_checkout_confirm():
    """Voller Checkout mit Pflicht-Kopfdaten."""
    from app.services.inventory.checkout_service import create_checkout

    if not check_borrow_permission():
        flash(_('inventory.flash.no_borrow_permission'), 'danger')
        return redirect(url_for('inventory.inventory_checkout'))

    cart_product_ids = session.get('borrow_cart', [])
    cart_products = _ordered_cart_products(cart_product_ids)
    consumable_quantities = {
        p.id: int(getattr(p, 'cart_quantity', 0) or 0)
        for p in cart_products
        if p.item_type == 'consumable'
    }
    asset_product_ids = [p.id for p in cart_products if p.item_type != 'consumable']
    if not asset_product_ids and not consumable_quantities:
        flash(_('inventory.flash.no_products_to_borrow'), 'danger')
        return redirect(url_for('inventory.inventory_checkout'))

    event_name = request.form.get('event_name', '').strip()
    borrower_name = request.form.get('borrower_name', '').strip()
    borrower_id_raw = request.form.get('borrower_id', '').strip()
    contact_email = request.form.get('contact_email', '').strip()
    start_date_str = request.form.get('start_date', '').strip()
    end_date_str = request.form.get('end_date', '').strip()
    event_id_raw = request.form.get('event_id', '').strip()
    event_appointment_id_raw = request.form.get('event_appointment_id', '').strip()

    if not event_name:
        flash(_('inventory.flash.event_name_required'), 'danger')
        return redirect(url_for('inventory.inventory_checkout'))
    if not borrower_name:
        flash(_('inventory.flash.borrower_name_required'), 'danger')
        return redirect(url_for('inventory.inventory_checkout'))
    if not end_date_str:
        flash(_('inventory.flash.return_date_required'), 'danger')
        return redirect(url_for('inventory.inventory_checkout'))

    linked_borrower_id = None
    if borrower_id_raw:
        try:
            linked_borrower_id = int(borrower_id_raw)
        except ValueError:
            linked_borrower_id = None

    linked_event_id = None
    if event_id_raw:
        try:
            linked_event_id = int(event_id_raw)
        except ValueError:
            linked_event_id = None

    linked_appointment_id = None
    if event_appointment_id_raw:
        try:
            linked_appointment_id = int(event_appointment_id_raw)
        except ValueError:
            linked_appointment_id = None

    if not linked_borrower_id and not contact_email:
        flash(_('inventory.flash.contact_email_required'), 'danger')
        return redirect(url_for('inventory.inventory_checkout'))

    try:
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%dT%H:%M') if 'T' in start_date_str else datetime.strptime(start_date_str, '%Y-%m-%d')
        else:
            start_date = datetime.utcnow()
        if 'T' in end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')
        else:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    except ValueError:
        flash(_('inventory.flash.invalid_date_format'), 'danger')
        return redirect(url_for('inventory.inventory_checkout'))

    try:
        checkout = create_checkout(
            product_ids=asset_product_ids,
            event_name=event_name,
            borrower_name=borrower_name,
            created_by_id=current_user.id,
            start_date=start_date,
            end_date=end_date,
            borrower_id=linked_borrower_id,
            contact_email=contact_email,
            require_event=True,
            require_end_date=True,
            event_id=linked_event_id,
            event_appointment_id=linked_appointment_id,
            product_source_sets=_cart_product_source_sets_map(),
            consumable_quantities=consumable_quantities,
        )
    except ValueError as exc:
        code = str(exc)
        flash(_(f'inventory.flash.{code}') if code else _('inventory.flash.borrow_failed'), 'danger')
        return redirect(url_for('inventory.inventory_checkout'))

    session.pop('borrow_cart', None)
    _clear_all_cart_set_meta()
    flash(_('inventory.flash.borrow_success', count=len(checkout.items)), 'success')
    _flash_checkout_receipt_email(checkout)
    return redirect(url_for('inventory.borrows'))
