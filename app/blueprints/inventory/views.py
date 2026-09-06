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

@inventory_bp.route('/public/product/<int:product_id>')
def public_product(product_id):
    """Öffentliche Produktseite ohne Anmeldung."""
    product = Product.query.get_or_404(product_id)
    
    portal_logo_filename = None
    ownership_text = "Eigentum der Technik"  # Standardwert
    
    portal_logo_setting = SystemSettings.query.filter_by(key='portal_logo').first()
    if portal_logo_setting and portal_logo_setting.value:
        portal_logo_filename = portal_logo_setting.value
    
    ownership_setting = SystemSettings.query.filter_by(key='inventory_ownership_text').first()
    if ownership_setting and ownership_setting.value:
        ownership_text = ownership_setting.value
    
    return render_template('inventory/public_product.html',
                         product=product,
                         portal_logo_filename=portal_logo_filename,
                         ownership_text=ownership_text)


@inventory_bp.route('/')
@login_required
@check_module_access('module_inventory')
def dashboard():
    """Lager-Dashboard Hauptansicht."""
    from datetime import date as date_cls

    checkouts = Checkout.query.filter(
        Checkout.status.in_(('active', 'partially_returned')),
        or_(Checkout.borrower_id == current_user.id, Checkout.created_by == current_user.id),
    ).order_by(Checkout.start_date.desc()).all()

    my_borrows = []
    for checkout in checkouts:
        active = checkout.active_items
        if not active:
            continue
        names = [i.product.name for i in active if i.product]
        display_names = ', '.join(names[:3])
        if len(names) > 3:
            display_names += f' (+{len(names) - 3})'
        end_date = checkout.end_date.date() if checkout.end_date else date_cls.today()
        my_borrows.append({
            'first': checkout,
            'count': len(active),
            'is_group': len(active) > 1,
            'product_names': display_names or checkout.event_name,
            'borrow_date': checkout.start_date,
            'expected_return_date': end_date,
            'is_overdue': checkout.is_overdue,
            'ref_id': checkout.id,
            'return_number': checkout.checkout_number,
        })

    today = date_cls.today()
    stats = {
        'total': Product.query.count(),
        'available': Product.query.filter_by(status='available').count(),
        'borrowed': Product.query.filter_by(status='borrowed').count(),
        'defective': Product.query.filter(
            Product.status.in_(('defective', 'in_repair'))
        ).count(),
        'dguv_due': Product.query.filter(
            Product.dguv_next_check.isnot(None),
            Product.dguv_next_check <= today,
            Product.status != 'retired',
        ).count(),
    }

    return render_template(
        'inventory/dashboard.html',
        my_borrows=my_borrows,
        stats=stats,
    )


@inventory_bp.route('/stock')
@inventory_bp.route('/stock/<int:folder_id>')
@login_required
@check_module_access('module_inventory')
def stock(folder_id=None):
    """Bestandsübersicht mit optionaler Ordner-Filterung."""
    _sync_retired_folder_assignments()
    retired_folder = _get_retired_folder(create=False)
    if not retired_folder:
        retired_folder = _get_retired_folder(create=True)
        db.session.commit()

    current_folder = None
    subfolders = []
    
    if folder_id:
        current_folder = ProductFolder.query.get(folder_id)
        if not current_folder:
            flash(_('inventory.flash.folder_not_found'), 'warning')
            return redirect(url_for('inventory.stock'))
    else:
        subfolders = [
            f for f in ProductFolder.query.order_by(ProductFolder.name).all()
            if not retired_folder or f.id != retired_folder.id
        ]
    
    is_retired_folder_view = bool(
        current_folder and retired_folder and current_folder.id == retired_folder.id
    )

    return render_template(
        'inventory/stock.html',
        current_folder=current_folder,
        subfolders=subfolders,
        retired_folder_id=(retired_folder.id if retired_folder else None),
        is_retired_folder_view=is_retired_folder_view,
        manuals=_accessible_manuals(),
    )


def _cable_match_candidates(name, category, normalized_length):
    query = Product.query.filter(
        Product.item_type == 'consumable',
        Product.name == name,
        Product.category == (category or None),
        Product.length == normalized_length,
    ).order_by(Product.updated_at.desc(), Product.id.asc())
    return query.all()


def _cable_existing_candidates():
    return Product.query.filter(
        Product.item_type == 'consumable'
    ).order_by(Product.name.asc(), Product.length.asc(), Product.id.asc()).all()


@inventory_bp.route('/products/cables/new', methods=['GET', 'POST'])
@login_required
@check_module_access('module_inventory')
def cable_new():
    """Dedizierte Anlage für Kabel-Mengenartikel."""
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash(translate('inventory.flash.guests_cannot_create'), 'danger')
        return redirect(url_for('inventory.stock'))

    categories = get_inventory_categories()
    folders = get_product_folders()
    mode = (request.form.get('mode') or request.args.get('mode') or 'new').strip().lower()
    if mode not in {'new', 'existing'}:
        mode = 'new'

    form_data = {
        'name': (request.form.get('name') or '').strip(),
        'description': (request.form.get('description') or '').strip(),
        'category': (request.form.get('category') or '').strip(),
        'location': (request.form.get('location') or '').strip(),
        'length': (request.form.get('length') or '').strip(),
        'folder_id': (request.form.get('folder_id') or '').strip(),
        'quantity': (request.form.get('quantity') or '1').strip(),
        'mode': mode,
        'existing_product_id': (request.form.get('existing_product_id') or '').strip(),
    }

    candidates = []
    if mode == 'existing':
        candidates = _cable_existing_candidates()
    elif form_data['name'] and form_data['length']:
        normalized_length_preview, _unused = normalize_length_input(form_data['length'])
        if normalized_length_preview is not None:
            candidates = _cable_match_candidates(
                form_data['name'],
                form_data['category'],
                normalized_length_preview,
            )

    if request.method == 'POST':
        from app.services.inventory import StockService

        name = form_data['name']
        category = form_data['category']
        location = form_data['location']
        description = form_data['description']
        length_input = form_data['length']
        folder_id = form_data['folder_id']
        quantity_str = form_data['quantity']

        try:
            quantity = int(quantity_str)
        except ValueError:
            quantity = 0
        if quantity < 1 or quantity > 50000:
            flash(_('inventory.cable_form.errors.quantity_range'), 'danger')
            return render_template('inventory/cable_form.html', categories=categories, folders=folders, form_data=form_data, candidates=candidates)

        if mode == 'existing':
            selected_id_raw = form_data['existing_product_id']
            target = None
            if selected_id_raw:
                try:
                    selected_id = int(selected_id_raw)
                except ValueError:
                    selected_id = None
                if selected_id is not None:
                    target = next((p for p in candidates if p.id == selected_id), None)
            if not target:
                flash(_('inventory.cable_form.errors.select_matching_product'), 'danger')
                return render_template('inventory/cable_form.html', categories=categories, folders=folders, form_data=form_data, candidates=candidates)

            try:
                StockService.add_stock(
                    target,
                    quantity,
                    current_user.id,
                    reason='Kabelbestand ergänzt',
                    context_type='manual',
                    context_id=f'cable_add:{target.id}',
                )
                db.session.commit()
                flash(_('inventory.cable_form.flash.stock_added', name=target.name, qty=quantity), 'success')
                return redirect(url_for('inventory.stock'))
            except Exception as exc:
                db.session.rollback()
                current_app.logger.error(f'Fehler beim Ergänzen von Kabelbestand: {exc}', exc_info=True)
                flash(_('inventory.flash.create_error'), 'danger')
                return render_template('inventory/cable_form.html', categories=categories, folders=folders, form_data=form_data, candidates=candidates)

        if not name:
            flash(_('inventory.cable_form.errors.name_required'), 'danger')
            return render_template('inventory/cable_form.html', categories=categories, folders=folders, form_data=form_data, candidates=candidates)
        if not length_input:
            flash(_('inventory.cable_form.errors.length_required'), 'danger')
            return render_template('inventory/cable_form.html', categories=categories, folders=folders, form_data=form_data, candidates=candidates)

        normalized_length, _unused = normalize_length_input(length_input)
        if normalized_length is None:
            flash(_('inventory.flash.invalid_length'), 'danger')
            return render_template('inventory/cable_form.html', categories=categories, folders=folders, form_data=form_data, candidates=candidates)

        folder_id_int = None
        if folder_id:
            try:
                folder_id_int = int(folder_id)
                if not ProductFolder.query.get(folder_id_int):
                    folder_id_int = None
            except ValueError:
                folder_id_int = None

        candidates = _cable_match_candidates(name, category, normalized_length)
        if candidates:
            flash(_('inventory.cable_form.errors.match_exists_use_existing'), 'warning')
            return render_template('inventory/cable_form.html', categories=categories, folders=folders, form_data=form_data, candidates=candidates)

        try:
            product = Product(
                name=name,
                description=description or None,
                category=category or None,
                serial_number=None,
                condition=None,
                location=location or None,
                length=normalized_length,
                purchase_date=None,
                folder_id=folder_id_int,
                status='available',
                item_type='consumable',
                image_path=None,
                created_by=current_user.id,
                weight_kg=None,
                width_cm=None,
                height_cm=None,
                depth_cm=None,
                purchase_price=None,
                replacement_value=None,
            )
            _apply_dguv_from_form(
                product,
                request.form,
                next_equals_created_if_no_last=True,
            )
            db.session.add(product)
            db.session.flush()
            product.qr_code_data = generate_product_qr_code(product.id)
            StockService.add_stock(
                product,
                quantity,
                current_user.id,
                reason='Initialer Kabelbestand',
                context_type='manual',
                context_id=f'cable_create:{product.id}',
            )
            db.session.commit()
            flash(_('inventory.cable_form.flash.created', name=name, qty=quantity), 'success')
            return redirect(url_for('inventory.stock'))
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error(f'Fehler beim Erstellen von Kabel-Mengenartikel: {exc}', exc_info=True)
            flash(_('inventory.flash.create_error'), 'danger')

    return render_template(
        'inventory/cable_form.html',
        categories=categories,
        folders=folders,
        form_data=form_data,
        candidates=candidates,
    )


@inventory_bp.route('/products/new', methods=['GET', 'POST'])
@login_required
@check_module_access('module_inventory')
def product_new():
    """Neues Produkt erstellen."""
    # Gast-Accounts können keine Produkte erstellen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash(translate('inventory.flash.guests_cannot_create'), 'danger')
        return redirect(url_for('inventory.stock'))
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash(translate('inventory.flash.product_name_required'), 'danger')
            categories = get_inventory_categories()
            folders = get_product_folders()
            return render_template('inventory/product_form.html', categories=categories, folders=folders, manuals=_accessible_manuals())
        
        description = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip()
        serial_number = request.form.get('serial_number', '').strip()
        condition = request.form.get('condition', '').strip()
        location = request.form.get('location', '').strip()
        length_input = request.form.get('length', '').strip()
        normalized_length, _unused = normalize_length_input(length_input) if length_input else (None, None)
        if length_input and normalized_length is None:
            flash(_('inventory.flash.invalid_length'), 'danger')
            categories = get_inventory_categories()
            folders = get_product_folders()
            return render_template('inventory/product_form.html', categories=categories, folders=folders, manuals=_accessible_manuals())
        folder_id = request.form.get('folder_id', '').strip()
        purchase_date_str = request.form.get('purchase_date', '').strip()
        
        purchase_date = None
        if purchase_date_str:
            try:
                purchase_date = datetime.strptime(purchase_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        folder_id_int = None
        if folder_id:
            try:
                folder_id_int = int(folder_id)
                if not ProductFolder.query.get(folder_id_int):
                    folder_id_int = None
            except ValueError:
                folder_id_int = None
        
        quantity = 1
        quantity_str = request.form.get('quantity', '1').strip()
        try:
            quantity = int(quantity_str)
            if quantity < 1 or quantity > 100:
                flash(_('inventory.flash.quantity_range'), 'danger')
                categories = get_inventory_categories()
                folders = get_product_folders()
                return render_template('inventory/product_form.html', categories=categories, folders=folders, manuals=_accessible_manuals())
        except ValueError:
            flash(_('inventory.flash.invalid_quantity'), 'danger')
            categories = get_inventory_categories()
            folders = get_product_folders()
            return render_template('inventory/product_form.html', categories=categories, folders=folders, manuals=_accessible_manuals())

        external_barcode = _normalize_external_barcode(request.form.get('external_barcode'))
        if external_barcode and quantity > 1:
            flash(_('inventory.flash.external_barcode_qty'), 'danger')
            categories = get_inventory_categories()
            folders = get_product_folders()
            return render_template('inventory/product_form.html', categories=categories, folders=folders, manuals=_accessible_manuals())
        if external_barcode and _external_barcode_taken(external_barcode):
            flash(_('inventory.flash.external_barcode_taken', code=external_barcode), 'danger')
            categories = get_inventory_categories()
            folders = get_product_folders()
            return render_template('inventory/product_form.html', categories=categories, folders=folders, manuals=_accessible_manuals())
        
        image_path = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                stored_filename = f"{timestamp}_{filename}"
                upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_images')
                os.makedirs(upload_dir, exist_ok=True)
                filepath = os.path.join(upload_dir, stored_filename)
                file.save(filepath)
                image_path = stored_filename
        
        created_products = []
        try:
            for i in range(quantity):
                product = Product(
                    name=name,
                    description=description or None,
                    category=category or None,
                    serial_number=serial_number or None,  # Gleiche Seriennummer für alle
                    condition=condition or None,
                    location=location or None,
                    length=normalized_length,
                    purchase_date=purchase_date,
                    folder_id=folder_id_int,
                    status='available',
                    item_type='asset',
                    image_path=image_path,  # Gleiches Bild für alle
                    external_barcode=external_barcode if quantity == 1 else None,
                    created_by=current_user.id,
                    weight_kg=_parse_optional_float(request.form.get('weight_kg')),
                    width_cm=_parse_optional_float(request.form.get('width_cm')),
                    height_cm=_parse_optional_float(request.form.get('height_cm')),
                    depth_cm=_parse_optional_float(request.form.get('depth_cm')),
                    purchase_price=_parse_optional_float(request.form.get('purchase_price')),
                    replacement_value=_parse_optional_float(request.form.get('replacement_value')),
                )
                _apply_dguv_from_form(
                    product,
                    request.form,
                    next_equals_created_if_no_last=True,
                )
                
                db.session.add(product)
                db.session.flush()  # Um die ID zu erhalten
                
                qr_data = generate_product_qr_code(product.id)
                product.qr_code_data = qr_data
                
                created_products.append(product)
            
            db.session.commit()

            try:
                _attach_form_documents_to_products(created_products, request.form, request.files)
                db.session.commit()
            except Exception as doc_err:
                db.session.rollback()
                current_app.logger.error(f"Fehler beim Anhängen von Dokumenten: {doc_err}", exc_info=True)
                flash(_('inventory.flash.document_attach_error'), 'warning')

            # Flash-Nachricht anpassen je nach Anzahl
            if quantity == 1:
                flash(_('inventory.flash.product_created', name=name), 'success')
            else:
                flash(_('inventory.flash.products_created', quantity=quantity, name=name), 'success')
            
            return redirect(url_for('inventory.stock'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Fehler beim Erstellen der Produkte: {e}", exc_info=True)
            flash(_('inventory.flash.create_error'), 'danger')
            categories = get_inventory_categories()
            folders = get_product_folders()
            return render_template(
                'inventory/product_form.html',
                categories=categories,
                folders=folders,
                manuals=_accessible_manuals(),
            )
    
    categories = get_inventory_categories()
    folders = get_product_folders()
    
    return render_template(
        'inventory/product_form.html',
        categories=categories,
        folders=folders,
        manuals=_accessible_manuals(),
    )


@inventory_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
@check_module_access('module_inventory')
def product_edit(product_id):
    """Produkt bearbeiten."""
    # Gast-Accounts können keine Produkte bearbeiten
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash(translate('inventory.flash.guests_cannot_edit'), 'danger')
        return redirect(url_for('inventory.stock'))
    
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash(translate('inventory.flash.product_name_required'), 'danger')
            categories = get_inventory_categories()
            folders = get_product_folders()
            return render_template('inventory/product_form.html', product=product, categories=categories, folders=folders, manuals=_accessible_manuals())
        
        product.name = name
        product.description = request.form.get('description', '').strip() or None
        product.category = request.form.get('category', '').strip() or None
        product.serial_number = request.form.get('serial_number', '').strip() or None
        product.condition = request.form.get('condition', '').strip() or None
        product.location = request.form.get('location', '').strip() or None

        external_barcode = _normalize_external_barcode(request.form.get('external_barcode'))
        if external_barcode and _external_barcode_taken(external_barcode, exclude_product_id=product.id):
            flash(_('inventory.flash.external_barcode_taken', code=external_barcode), 'danger')
            categories = get_inventory_categories()
            folders = get_product_folders()
            purchase_date_formatted = product.purchase_date.strftime('%Y-%m-%d') if product.purchase_date else ''
            return render_template(
                'inventory/product_form.html',
                product=product,
                purchase_date_formatted=purchase_date_formatted,
                categories=categories,
                folders=folders,
                manuals=_accessible_manuals(),
            )
        product.external_barcode = external_barcode
        
        length_input = request.form.get('length', '').strip()
        if length_input:
            normalized_length, _unused = normalize_length_input(length_input)
            if normalized_length is None:
                flash(translate('inventory.flash.invalid_length'), 'danger')
                categories = get_inventory_categories()
                folders = get_product_folders()
                purchase_date_formatted = product.purchase_date.strftime('%Y-%m-%d') if product.purchase_date else ''
                return render_template('inventory/product_form.html', product=product, purchase_date_formatted=purchase_date_formatted, categories=categories, folders=folders, manuals=_accessible_manuals())
            product.length = normalized_length
        else:
            product.length = None
        
        folder_id = request.form.get('folder_id', '').strip()
        folder_id_int = None
        if folder_id:
            try:
                folder_id_int = int(folder_id)
                if not ProductFolder.query.get(folder_id_int):
                    folder_id_int = None
            except ValueError:
                folder_id_int = None
        product.folder_id = folder_id_int
        
        if 'status' in request.form:
            product.status = request.form.get('status', 'available')
            _apply_retired_folder_assignment(product)
        
        purchase_date_str = request.form.get('purchase_date', '').strip()
        if purchase_date_str:
            try:
                product.purchase_date = datetime.strptime(purchase_date_str, '%Y-%m-%d').date()
            except ValueError:
                product.purchase_date = None
        else:
            product.purchase_date = None

        product.weight_kg = _parse_optional_float(request.form.get('weight_kg'))
        product.width_cm = _parse_optional_float(request.form.get('width_cm'))
        product.height_cm = _parse_optional_float(request.form.get('height_cm'))
        product.depth_cm = _parse_optional_float(request.form.get('depth_cm'))
        product.purchase_price = _parse_optional_float(request.form.get('purchase_price'))
        product.replacement_value = _parse_optional_float(request.form.get('replacement_value'))
        _apply_dguv_from_form(
            product,
            request.form,
            next_equals_created_if_no_last=True,
        )
        if request.form.get('remove_image') == '1':
            if product.image_path:
                upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_images')
                filepath = os.path.join(upload_dir, product.image_path)
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception as e:
                        current_app.logger.error(f"Fehler beim Löschen des Bildes: {e}")
            product.image_path = None
        
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '' and allowed_file(file.filename):
                if product.image_path:
                    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_images')
                    old_filepath = os.path.join(upload_dir, product.image_path)
                    if os.path.exists(old_filepath):
                        try:
                            os.remove(old_filepath)
                        except:
                            pass
                
                filename = secure_filename(file.filename)
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                stored_filename = f"{timestamp}_{filename}"
                upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_images')
                os.makedirs(upload_dir, exist_ok=True)
                filepath = os.path.join(upload_dir, stored_filename)
                file.save(filepath)
                product.image_path = stored_filename
        
        if not product.qr_code_data:
            product.qr_code_data = generate_product_qr_code(product.id)

        if request.form.get('convert_to_cable') == '1':
            from app.services.inventory import StockService

            merge_similar = request.form.get('merge_similar_cables') == '1'
            product.item_type = 'consumable'
            if product.status == 'retired':
                product.status = 'available'

            converted_count = 1
            merged_products = []
            if merge_similar:
                candidates = Product.query.filter(
                    Product.id != product.id,
                    Product.item_type == 'asset',
                    Product.status == 'available',
                    Product.name == product.name,
                    Product.category == product.category,
                    Product.length == product.length,
                ).all()
                for candidate in candidates:
                    if candidate.serial_number and product.serial_number and candidate.serial_number != product.serial_number:
                        continue
                    merged_products.append(candidate)
                for candidate in merged_products:
                    candidate.status = 'retired'
                    _apply_retired_folder_assignment(candidate)
                    converted_count += 1

            existing_qty = product.total_on_hand if product.item_type == 'consumable' else 0
            target_qty = max(existing_qty, converted_count)
            if target_qty > 0:
                StockService.set_stock_count(
                    product,
                    target_qty,
                    current_user.id,
                    reason='Konvertierung zu Kabel-Mengenartikel',
                    context_type='manual',
                    context_id=f'convert:{product.id}',
                )
            flash(f'Produkt wurde als Kabel-Mengenartikel umgestellt (Bestand: {target_qty}).', 'success')
            if merged_products:
                flash(f'{len(merged_products)} ähnliche Einzelartikel wurden auf "ausgemustert" gesetzt.', 'info')
        
        db.session.commit()

        try:
            attached = _attach_form_documents_to_products([product], request.form, request.files)
            if attached:
                db.session.commit()
        except Exception as doc_err:
            db.session.rollback()
            current_app.logger.error(f"Fehler beim Anhängen von Dokumenten: {doc_err}", exc_info=True)
            flash(_('inventory.flash.document_attach_error'), 'warning')
        
        if request.form.get('convert_to_cable') != '1':
            flash(_('inventory.flash.product_updated', name=name), 'success')
        return redirect(url_for('inventory.stock'))
    
    purchase_date_formatted = product.purchase_date.strftime('%Y-%m-%d') if product.purchase_date else ''
    
    categories = get_inventory_categories()
    folders = get_product_folders()
    
    return render_template(
        'inventory/product_form.html',
        product=product,
        purchase_date_formatted=purchase_date_formatted,
        categories=categories,
        folders=folders,
        manuals=_accessible_manuals(),
    )


@inventory_bp.route('/public/product-images/<path:filename>')
def serve_public_product_image(filename):
    """Serviere Produktbilder für öffentliche Produktseiten."""
    try:
        from flask import abort
        from urllib.parse import unquote
        
        filename = unquote(filename)
        
        if os.path.isabs(filename) or '/' in filename or '\\' in filename:
            filename = os.path.basename(filename)
        
        project_root = os.path.dirname(current_app.root_path)
        directory = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_images')
        full_path = os.path.join(directory, filename)
        
        if not os.path.abspath(full_path).startswith(os.path.abspath(directory)):
            abort(403)
        
        if os.path.isfile(full_path):
            return send_from_directory(directory, filename)
        else:
            abort(404)
    except Exception as e:
        current_app.logger.error(f"Fehler beim Servieren des Produktbildes: {e}")
        abort(404)


@inventory_bp.route('/product-images/<path:filename>')
@login_required
def serve_product_image(filename):
    """Serviere Produktbilder."""
    try:
        from flask import abort
        from urllib.parse import unquote
        
        filename = unquote(filename)
        
        if os.path.isabs(filename) or '/' in filename or '\\' in filename:
            filename = os.path.basename(filename)
        
        project_root = os.path.dirname(current_app.root_path)
        directory = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_images')
        full_path = os.path.join(directory, filename)
        
        if current_app.debug:
            current_app.logger.debug(f"[PRODUCT IMAGE] Requested filename: {filename}")
            current_app.logger.debug(f"[PRODUCT IMAGE] Full path: {full_path}")
            current_app.logger.debug(f"[PRODUCT IMAGE] File exists: {os.path.isfile(full_path)}")
            if not os.path.isfile(full_path):
                if os.path.exists(directory):
                    current_app.logger.debug(f"[PRODUCT IMAGE] Directory contents: {os.listdir(directory)}")
        
        if not os.path.isfile(full_path):
            current_app.logger.warning(f"Produktbild nicht gefunden: {filename} (Pfad: {full_path})")
            abort(404)
        
        return send_from_directory(directory, filename)
    except FileNotFoundError:
        from flask import abort
        current_app.logger.warning(f"Produktbild nicht gefunden: {filename}")
        abort(404)
    except Exception as e:
        from flask import abort
        current_app.logger.error(f"Fehler beim Servieren des Produktbildes {filename}: {e}", exc_info=True)
        abort(404)


@inventory_bp.route('/products/<int:product_id>/status', methods=['POST'])
@login_required
def product_update_status(product_id):
    """API-Endpoint zum Aktualisieren des Produkt-Status."""
    product = Product.query.get_or_404(product_id)
    
    data = request.get_json()
    new_status = data.get('status', '').strip()
    
    if new_status not in ['available', 'borrowed', 'missing', 'defective', 'in_repair', 'retired']:
        return jsonify({'success': False, 'error': 'Ungültiger Status.'}), 400
    
    product.status = new_status
    _apply_retired_folder_assignment(product)
    db.session.commit()
    
    return jsonify({'success': True, 'status': new_status})


@inventory_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@login_required
def product_delete(product_id):
    """Produkt löschen."""
    # Gast-Accounts können keine Produkte löschen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash(translate('inventory.flash.guests_cannot_delete'), 'danger')
        return redirect(url_for('inventory.stock'))
    
    product = Product.query.get_or_404(product_id)
    
    from app.services.inventory.checkout_service import find_active_checkout_item_for_product
    if find_active_checkout_item_for_product(product_id) or product.status == 'borrowed':
        flash(_('inventory.flash.product_cannot_delete'), 'danger')
        return redirect(url_for('inventory.stock'))
    
    if product.image_path and os.path.exists(product.image_path):
        try:
            os.remove(product.image_path)
        except:
            pass
    
    db.session.delete(product)
    db.session.commit()
    
    flash(_('inventory.flash.product_deleted', name=product.name), 'success')
    return redirect(url_for('inventory.stock'))
