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

@inventory_bp.route('/inventory-list')
@login_required
def inventory_list():
    """Inventurliste - Übersicht aller Produkte für Inventur (Legacy)."""
    products = Product.query.order_by(Product.name).all()
    return render_template('inventory/inventory_list.html', products=products)


@inventory_bp.route('/inventory-list/pdf')
@login_required
@check_module_access('module_inventory')
def inventory_list_pdf():
    """PDF-Generierung für Inventurliste (Legacy)."""
    from app.utils.pdf_generator import generate_inventory_list_pdf
    
    products = Product.query.order_by(Product.name).all()
    
    pdf_buffer = BytesIO()
    generate_inventory_list_pdf(products, pdf_buffer)
    pdf_buffer.seek(0)
    
    filename = f"Inventurliste_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )


# ========== Inventurtool Routes ==========

@inventory_bp.route('/inventory-tool', methods=['GET', 'POST'])
@login_required
def inventory_tool():
    """Übersicht: Neue Inventur starten + Historie (aktiv und abgeschlossen)."""
    active_inventory = Inventory.query.filter_by(status='active').first()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'start':
            if active_inventory:
                flash(_('inventory.flash.inventory_active_exists'), 'warning')
                return redirect(url_for('inventory.inventory_tool'))

            name = request.form.get('name', '').strip()
            if not name:
                name = f"Inventur {datetime.now().strftime('%d.%m.%Y %H:%M')}"

            description = request.form.get('description', '').strip() or None

            new_inventory = Inventory(
                name=name,
                description=description,
                status='active',
                started_by=current_user.id
            )
            db.session.add(new_inventory)
            db.session.flush()

            products = Product.query.filter(Product.status != 'retired').order_by(Product.name).all()
            for product in products:
                inventory_item = InventoryItem(
                    inventory_id=new_inventory.id,
                    product_id=product.id
                )
                db.session.add(inventory_item)

            db.session.commit()
            flash(_('inventory.flash.inventory_started', name=name), 'success')
            return redirect(url_for('inventory.inventory_tool'))

    inventories = Inventory.query.filter(
        Inventory.status.in_(('active', 'completed'))
    ).order_by(Inventory.started_at.desc()).all()

    inventories = sorted(
        inventories,
        key=lambda inv: (
            0 if inv.status == 'active' else 1,
            -(inv.completed_at or inv.started_at or datetime.min).timestamp(),
        )
    )

    return render_template(
        'inventory/inventory_tool.html',
        active_inventory=active_inventory,
        inventories=inventories,
    )


@inventory_bp.route('/inventory-tool/history')
@login_required
def inventory_history():
    """Historie liegt auf der Inventur-Startseite."""
    return redirect(url_for('inventory.inventory_tool') + '#history')


@inventory_bp.route('/inventory-tool/<int:inventory_id>')
@login_required
def inventory_session(inventory_id):
    """Durchführung / Ansicht einer Inventur-Session."""
    inventory = Inventory.query.get_or_404(inventory_id)
    inventory_items = InventoryItem.query.filter_by(inventory_id=inventory.id).options(
        joinedload(InventoryItem.product),
        joinedload(InventoryItem.checker)
    ).all()
    open_count = sum(1 for item in inventory_items if not item.checked)
    return render_template(
        'inventory/inventory_session.html',
        inventory=inventory,
        inventory_items=inventory_items,
        open_count=open_count,
        is_active=inventory.status == 'active',
    )


@inventory_bp.route('/inventory-tool/<int:inventory_id>/complete', methods=['POST'])
@login_required
def inventory_complete(inventory_id):
    """Inventur abschließen und Änderungen auf Produkte anwenden."""
    inventory = Inventory.query.get_or_404(inventory_id)

    if inventory.status != 'active':
        flash(_('inventory.flash.inventory_completed'), 'warning')
        return redirect(url_for('inventory.inventory_tool'))

    items = InventoryItem.query.filter_by(inventory_id=inventory_id).options(
        joinedload(InventoryItem.product).selectinload(Product.lots)
    ).all()
    updated_count = 0
    missing_count = 0
    missing_skipped = 0
    stock_adjusted = 0
    mark_missing = request.form.get('mark_missing') in ('1', 'on', 'true', 'yes')

    from app.services.inventory import StockService
    from app.services.inventory.checkout_service import find_active_checkout_item_for_product

    # Statusse, die „fehlend“ nicht überschreiben darf (Checkout / Lifecycle)
    protected_from_missing = frozenset({'borrowed', 'in_repair', 'defective', 'retired'})

    for item in items:
        if item.location_changed and item.new_location:
            item.product.location = item.new_location
            updated_count += 1

        if item.condition_changed and item.new_condition:
            item.product.condition = item.new_condition
            updated_count += 1

        if (
            item.product
            and item.product.item_type == 'consumable'
            and item.counted_quantity is not None
        ):
            try:
                movement = StockService.set_stock_count(
                    item.product,
                    item.counted_quantity,
                    current_user.id,
                    reason=f'Inventur {inventory.name}',
                    context_type='inventory',
                    context_id=inventory.id,
                )
                if movement:
                    stock_adjusted += 1
                    updated_count += 1
            except ValueError:
                pass

        if mark_missing and not item.checked and item.product:
            product = item.product
            if product.status in protected_from_missing:
                missing_skipped += 1
                continue
            if find_active_checkout_item_for_product(product.id):
                missing_skipped += 1
                continue
            product.status = 'missing'
            missing_count += 1

    inventory.status = 'completed'
    inventory.completed_at = datetime.utcnow()

    db.session.commit()

    msg = _('inventory.flash.inventory_finished', count=updated_count)
    extras = []
    if stock_adjusted:
        extras.append(f'{stock_adjusted} Bestände angepasst')
    if missing_count:
        extras.append(f'{missing_count} als fehlend markiert')
    if missing_skipped:
        extras.append(
            translate(
                'inventory.flash.inventory_missing_skipped',
                count=missing_skipped,
            )
        )
    if extras:
        flash(f"{msg} ({', '.join(extras)})", 'success')
    else:
        flash(msg, 'success')
    return redirect(url_for('inventory.inventory_tool'))


@inventory_bp.route('/inventory-tool/<int:inventory_id>/pdf')
@login_required
@check_module_access('module_inventory')
def inventory_tool_pdf(inventory_id):
    """PDF-Generierung für eine Inventur."""
    from app.utils.pdf_generator import generate_inventory_tool_pdf
    
    inventory = Inventory.query.get_or_404(inventory_id)
    items = InventoryItem.query.filter_by(inventory_id=inventory_id).options(
        joinedload(InventoryItem.product)
    ).all()
    
    items.sort(key=lambda x: x.product.name if x.product else '')
    
    pdf_buffer = BytesIO()
    generate_inventory_tool_pdf(inventory, items, pdf_buffer)
    pdf_buffer.seek(0)
    
    filename = f"Inventur_{inventory.name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )


# ========== Inventurtool API Routes ==========


@login_required
def api_inventory_scan(inventory_id):
    """API: QR-Code scannen und zu Produkt navigieren."""
    inventory = Inventory.query.get_or_404(inventory_id)
    
    if inventory.status != 'active':
        return jsonify({'error': translate('inventory.errors.inventory_not_active')}), 400
    
    data = request.get_json()
    qr_data = _normalize_scanner_code((data.get('qr_data') or '').strip())
    
    if not qr_data:
        return jsonify({'error': translate('inventory.errors.qr_data_required')}), 400

    # Inventar-Nr. → PROD/SET → numerische ID (ohne führende Nullen)
    product, product_set = _lookup_product_or_set_by_scan(qr_data)
    if product:
        from app.services.inventory import InventoryLockService

        foreign = InventoryLockService.foreign_lock(inventory_id, product.id, current_user.id)
        if foreign:
            return jsonify({
                'error': translate('inventory.errors.lock_conflict'),
                'code': 'lock_conflict',
                'details': {
                    'locked_by': foreign.locked_by,
                    'expires_at': foreign.expires_at.isoformat() if foreign.expires_at else None,
                },
            }), 409

        item = InventoryItem.query.filter_by(
            inventory_id=inventory_id,
            product_id=product.id
        ).first()
        
        if not item:
            return jsonify({'error': translate('inventory.errors.product_not_in_inventory')}), 404
        
        item.checked = True
        item.checked_by = current_user.id
        item.checked_at = datetime.utcnow()
        item.version = int(item.version or 1) + 1
        db.session.commit()
        try:
            from app.blueprints.sse import emit_inventory_update
            emit_inventory_update(
                inventory_id,
                'scan',
                {'product_id': product.id, 'actor_id': current_user.id},
            )
        except Exception:
            pass
        
        return jsonify({
            'success': True,
            'product': {
                'id': product.id,
                'name': product.name,
                'category': product.category,
                'location': product.location,
                'condition': product.condition,
                'external_barcode': product.external_barcode,
            },
            'item': {
                'id': item.id,
                'checked': item.checked,
                'notes': item.notes,
                'location_changed': item.location_changed,
                'new_location': item.new_location,
                'condition_changed': item.condition_changed,
                'new_condition': item.new_condition
            }
        })
    if product_set:
        from app.services.inventory import InventoryLockService

        checked = []
        missing = []
        locked = []
        for set_item in product_set.items:
            foreign = InventoryLockService.foreign_lock(
                inventory_id, set_item.product_id, current_user.id
            )
            if foreign:
                locked.append(set_item.product.name if set_item.product else str(set_item.product_id))
                continue
            inv_item = InventoryItem.query.filter_by(
                inventory_id=inventory_id,
                product_id=set_item.product_id,
            ).first()
            if not inv_item:
                missing.append(set_item.product.name if set_item.product else str(set_item.product_id))
                continue
            inv_item.checked = True
            inv_item.checked_by = current_user.id
            inv_item.checked_at = datetime.utcnow()
            inv_item.version = int(inv_item.version or 1) + 1
            checked.append({
                'id': set_item.product_id,
                'name': set_item.product.name if set_item.product else None,
            })
        if not checked and locked:
            return jsonify({
                'error': translate('inventory.errors.lock_conflict'),
                'code': 'lock_conflict',
                'details': {'locked_products': locked},
            }), 409
        db.session.commit()
        try:
            from app.blueprints.sse import emit_inventory_update
            emit_inventory_update(
                inventory_id,
                'scan',
                {
                    'set_id': product_set.id,
                    'product_ids': [c['id'] for c in checked],
                    'actor_id': current_user.id,
                },
            )
        except Exception:
            pass
        return jsonify({
            'success': True,
            'is_set': True,
            'set': {'id': product_set.id, 'name': product_set.name},
            'checked_products': checked,
            'missing_products': missing,
            'checked_count': len(checked),
        })

    return jsonify({'error': translate('inventory.errors.invalid_qr_code')}), 400


@inventory_bp.route('/folders', methods=['GET', 'POST'])
@login_required
def folders():
    """Ordner-Verwaltung."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash(_('inventory.flash.folder_name_required'), 'danger')
            return redirect(url_for('inventory.folders'))
        
        description = request.form.get('description', '').strip()
        color = request.form.get('color', '').strip() or None
        
        existing = ProductFolder.query.filter_by(name=name).first()
        if existing:
            flash(_('inventory.flash.folder_exists'), 'danger')
            return redirect(url_for('inventory.folders'))
        
        folder = ProductFolder(
            name=name,
            description=description or None,
            color=color,
            created_by=current_user.id
        )
        
        db.session.add(folder)
        db.session.commit()
        
        flash(_('inventory.flash.folder_created', name=name), 'success')
        return redirect(url_for('inventory.folders'))
    
    folders_list = ProductFolder.query.order_by(ProductFolder.name).all()
    return render_template('inventory/folders.html', folders=folders_list)


@inventory_bp.route('/folders/<int:folder_id>/delete', methods=['POST'])
@login_required
def folder_delete(folder_id):
    """Ordner löschen."""
    folder = ProductFolder.query.get_or_404(folder_id)
    if folder.name == RETIRED_FOLDER_NAME:
        flash('Der Papierkorb kann nicht gelöscht werden.', 'warning')
        return redirect(url_for('inventory.folders'))
    
    if folder.products:
        for product in folder.products:
            product.folder_id = None
        db.session.commit()
    
    db.session.delete(folder)
    db.session.commit()
    
    flash(_('inventory.flash.folder_deleted', name=folder.name), 'success')
    return redirect(url_for('inventory.folders'))


@inventory_bp.route('/print-qr', methods=['GET', 'POST'])
@login_required
@check_module_access('module_inventory')
def print_qr():
    """QR-Code-Druck mit Ordner-/Grid-/Listenansicht (inkl. Sets)."""
    if request.method == 'POST':
        product_ids = request.form.getlist('product_ids')
        set_ids = request.form.getlist('set_ids')
        label_type = request.form.get('label_type', 'cable')  # 'cable' oder 'device'

        if not product_ids and not set_ids:
            flash(_('inventory.flash.select_products'), 'danger')
            return redirect(url_for('inventory.print_qr'))

        try:
            products = []
            if product_ids:
                product_ids = [int(pid) for pid in product_ids]
                products = Product.query.filter(Product.id.in_(product_ids)).all()

            sets = []
            if set_ids:
                set_ids = [int(sid) for sid in set_ids]
                sets = ProductSet.query.filter(ProductSet.id.in_(set_ids)).order_by(ProductSet.name).all()

            if not products and not sets:
                flash(_('inventory.flash.no_valid_products'), 'danger')
                return redirect(url_for('inventory.print_qr'))

            pdf_buffer = BytesIO()
            generate_qr_code_sheet_pdf(products, pdf_buffer, label_type=label_type, sets=sets)
            pdf_buffer.seek(0)

            label_type_name = "Kabel" if label_type == 'cable' else "Geräte"
            if sets and not products:
                label_type_name = "Sets"
            elif sets and products:
                label_type_name = f"{label_type_name}_Sets"
            filename = f"QR-Codes_{label_type_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=filename
            )
        except Exception as e:
            current_app.logger.error(f"Fehler beim Generieren des QR-Code-Druckbogens: {e}")
            flash(_('inventory.flash.generate_error'), 'danger')
            return redirect(url_for('inventory.print_qr'))

    products = Product.query.options(joinedload(Product.folder)).order_by(Product.name).all()
    folders = ProductFolder.query.order_by(ProductFolder.name).all()
    product_sets = ProductSet.query.order_by(ProductSet.name).all()

    folder_counts = {}
    for product in products:
        key = product.folder_id if product.folder_id is not None else None
        folder_counts[key] = folder_counts.get(key, 0) + 1

    products_payload = [{
        'id': p.id,
        'name': p.name or '',
        'serial_number': p.serial_number or '',
        'category': p.category or '',
        'length': p.length or '',
        'location': p.location or '',
        'status': p.status or 'available',
        'folder_id': p.folder_id,
        'image_path': p.image_path or '',
    } for p in products]

    folders_payload = [{
        'id': f.id,
        'name': f.name or '',
        'color': f.color or '',
        'product_count': folder_counts.get(f.id, 0),
    } for f in folders]

    sets_payload = [{
        'id': s.id,
        'name': s.name or '',
        'description': s.description or '',
        'product_count': len(s.items) if s.items is not None else 0,
    } for s in product_sets]

    return render_template(
        'inventory/print_qr.html',
        products_payload=products_payload,
        folders_payload=folders_payload,
        sets_payload=sets_payload,
        unfiled_count=folder_counts.get(None, 0),
    )


@inventory_bp.route('/print-qr/color-codes', methods=['GET'])
@login_required
def print_color_codes():
    """Farbcodes-Tabelle drucken."""
    try:
        pdf_buffer = BytesIO()
        generate_color_code_table_pdf(pdf_buffer)
        pdf_buffer.seek(0)
        
        filename = f"Farbcodes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        current_app.logger.error(f"Fehler beim Generieren der Farbcodes-Tabelle: {e}")
        flash(_('inventory.flash.color_table_error'), 'danger')
        return redirect(url_for('inventory.print_qr'))
