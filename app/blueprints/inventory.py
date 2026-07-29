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

inventory_bp = Blueprint('inventory', __name__)

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
DEFAULT_DGUV_INTERVAL_MONTHS = 12
CART_SET_META_KEY = 'borrow_cart_set_meta'
CART_QTY_META_KEY = 'borrow_cart_quantities'
RETIRED_FOLDER_NAME = 'Papierkorb'


@inventory_bp.context_processor
def inject_inventory_trash_folder():
    """Papierkorb für Sidebar-Footer und Templates bereitstellen."""
    folder = _get_retired_folder(create=False)
    if not folder:
        try:
            folder = _get_retired_folder(create=True)
            if folder:
                db.session.commit()
        except Exception:
            db.session.rollback()
            folder = None
    view_folder_id = None
    try:
        view_folder_id = request.view_args.get('folder_id') if request.view_args else None
    except RuntimeError:
        view_folder_id = None
    trash_url = url_for('inventory.stock', folder_id=folder.id) if folder else None
    return {
        'inventory_trash_folder': folder,
        'inventory_trash_url': trash_url,
        'is_inventory_trash_view': bool(folder and view_folder_id and int(view_folder_id) == int(folder.id)),
    }


def _flash_checkout_receipt_email(checkout):
    """Warnung wenn Ausleihe ok, Ausleihschein-Mail aber fehlgeschlagen."""
    if not getattr(checkout, 'receipt_email_sent', True):
        flash(_('inventory.flash.borrow_registered_no_email'), 'warning')


def _return_email_ok(returned_or_checkout) -> bool:
    if returned_or_checkout is None:
        return True
    if hasattr(returned_or_checkout, 'return_email_sent'):
        return bool(getattr(returned_or_checkout, 'return_email_sent', True))
    if isinstance(returned_or_checkout, (list, tuple)):
        if not returned_or_checkout:
            return True
        return all(getattr(i, 'return_email_sent', True) for i in returned_or_checkout)
    return True


def _flash_return_email(returned_or_checkout):
    """Erfolg inkl. Mail-Hinweis, oder Warnung wenn Bestätigungs-Mail fehlschlug."""
    if _return_email_ok(returned_or_checkout):
        flash(_('inventory.flash.return_success'), 'success')
    else:
        flash(_('inventory.flash.return_registered_no_email'), 'warning')


def _serialize_set_members(product_set):
    """Set-Mitglieder für Badge/Dropdown-UI."""
    members = []
    for item in (product_set.items or []):
        members.append({
            'id': item.product_id,
            'name': item.product.name if item.product else '—',
            'quantity': item.quantity or 1,
        })
    return members


def _normalize_scanner_code(value):
    """Bereinigt Handscanner-Input (CR/LF, Layout-Artefakte) und kanonisiert Produkt-URLs."""
    from app.utils.qr_code import parse_qr_code

    if value is None:
        return ''
    text = unquote(str(value))
    text = re.sub(r'[\x00-\x1F\x7F]+', '', text).strip()
    if not text:
        return ''

    parsed = parse_qr_code(text)
    if parsed and parsed[0] == 'product':
        return f'PROD-{parsed[1]}'
    if parsed and parsed[0] == 'set':
        return f'SET-{parsed[1]}'
    if parsed and parsed[0] == 'borrow':
        return f'BORROW-{parsed[1]}'
    return text


def _get_cart_set_meta():
    meta = session.get(CART_SET_META_KEY) or {}
    return meta if isinstance(meta, dict) else {}


def _get_cart_qty_meta():
    meta = session.get(CART_QTY_META_KEY) or {}
    return meta if isinstance(meta, dict) else {}


def _get_cart_qty_for_product(product_id):
    try:
        return max(0, int(_get_cart_qty_meta().get(str(int(product_id)), 0)))
    except (TypeError, ValueError):
        return 0


def _set_cart_qty_for_product(product_id, qty):
    meta = _get_cart_qty_meta()
    key = str(int(product_id))
    qty_int = max(0, int(qty))
    if qty_int <= 0:
        meta.pop(key, None)
    else:
        meta[key] = qty_int
    session[CART_QTY_META_KEY] = meta
    session.modified = True


def _clear_cart_qty_for_product(product_id):
    meta = _get_cart_qty_meta()
    key = str(product_id)
    if key in meta:
        meta.pop(key, None)
        session[CART_QTY_META_KEY] = meta
        session.modified = True


def _cart_total_count(cart_product_ids):
    total = 0
    qty_meta = _get_cart_qty_meta()
    for pid in cart_product_ids or []:
        qty = qty_meta.get(str(pid))
        if qty is None:
            total += 1
            continue
        try:
            total += max(0, int(qty))
        except (TypeError, ValueError):
            total += 1
    return total


def _mark_cart_products_from_set(product_ids, product_set):
    """Markiert Warenkorb-Produkte als aus einem Set stammend."""
    if not product_set or not product_ids:
        return
    meta = _get_cart_set_meta()
    payload = {
        'set_id': product_set.id,
        'set_name': product_set.name,
        'members': _serialize_set_members(product_set),
    }
    for pid in product_ids:
        meta[str(pid)] = payload
    session[CART_SET_META_KEY] = meta
    session.modified = True


def _clear_cart_set_meta_for_product(product_id):
    meta = _get_cart_set_meta()
    key = str(product_id)
    if key in meta:
        meta.pop(key, None)
        session[CART_SET_META_KEY] = meta
        session.modified = True
    _clear_cart_qty_for_product(product_id)


def _clear_all_cart_set_meta():
    if CART_SET_META_KEY in session:
        session.pop(CART_SET_META_KEY, None)
        session.modified = True
    if CART_QTY_META_KEY in session:
        session.pop(CART_QTY_META_KEY, None)
        session.modified = True


def _cart_product_source_sets_map():
    """product_id -> set_id aus Session-Meta."""
    result = {}
    for key, info in _get_cart_set_meta().items():
        if not isinstance(info, dict) or not info.get('set_id'):
            continue
        try:
            result[int(key)] = int(info['set_id'])
        except (TypeError, ValueError):
            continue
    return result


def _ordered_cart_products(cart_product_ids):
    """Produkte in Warenkorb-Reihenfolge inkl. cart_source_set."""
    if not cart_product_ids:
        return []
    products = Product.query.filter(Product.id.in_(cart_product_ids)).all()
    by_id = {p.id: p for p in products}
    meta = _get_cart_set_meta()
    ordered = []
    for pid in cart_product_ids:
        product = by_id.get(pid)
        if not product:
            continue
        product.cart_source_set = meta.get(str(pid))
        product.cart_quantity = _get_cart_qty_for_product(pid) if product.item_type == 'consumable' else 1
        ordered.append(product)
    return ordered


def _source_set_api_payload(source_set):
    if not source_set:
        return None, None, None
    return (
        source_set.id,
        source_set.name,
        _serialize_set_members(source_set),
    )


def allowed_file(filename):
    """Prüft ob die Dateiendung erlaubt ist."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _parse_optional_float(value):
    raw = (value or '').strip()
    if not raw:
        return None
    try:
        return float(raw.replace(',', '.'))
    except ValueError:
        return None


def _parse_optional_int(value):
    raw = (value or '').strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_optional_date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    raw = (value or '').strip() if value is not None else ''
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


def _clear_dguv_fields(product):
    product.dguv_last_check = None
    product.dguv_next_check = None
    product.dguv_interval_months = None
    return product


def _apply_dguv_fields(
    product,
    last_raw,
    interval_raw=None,
    *,
    keep_existing_interval=False,
    default_last_to_today=False,
    next_equals_created_if_no_last=False,
):
    """Setzt letzte Prüfung (+ Intervall) und berechnet die nächste Prüfung automatisch.

    next_equals_created_if_no_last: Wenn keine letzte Prüfung gesetzt ist, wird
    die nächste Prüfung auf das Anlagedatum (heute / created_at) gesetzt.
    """
    last = _parse_optional_date(last_raw)
    if last is None and default_last_to_today:
        last = date.today()
    if keep_existing_interval:
        interval = product.dguv_interval_months or DEFAULT_DGUV_INTERVAL_MONTHS
    else:
        parsed = _parse_optional_int(interval_raw)
        interval = parsed if parsed is not None else DEFAULT_DGUV_INTERVAL_MONTHS

    product.dguv_last_check = last
    product.dguv_interval_months = interval
    if last:
        product.dguv_next_check = compute_dguv_next(last, interval)
    elif next_equals_created_if_no_last:
        created = product.created_at.date() if getattr(product, "created_at", None) else date.today()
        product.dguv_next_check = created
    else:
        product.dguv_next_check = None
    return product


def _apply_dguv_from_form(product, form, *, next_equals_created_if_no_last=False, keep_existing_interval=False):
    """Übernimmt DGUV-Felder aus dem Formular; ohne dguv_required werden sie geleert."""
    if form.get('dguv_required') != '1':
        return _clear_dguv_fields(product)
    return _apply_dguv_fields(
        product,
        form.get('dguv_last_check'),
        form.get('dguv_interval_months'),
        keep_existing_interval=keep_existing_interval,
        next_equals_created_if_no_last=next_equals_created_if_no_last,
    )


def _product_extra_fields(p):
    return {
        'weight_kg': p.weight_kg,
        'width_cm': p.width_cm,
        'height_cm': p.height_cm,
        'depth_cm': p.depth_cm,
        'purchase_price': p.purchase_price,
        'replacement_value': p.replacement_value,
        'dguv_last_check': p.dguv_last_check.isoformat() if p.dguv_last_check else None,
        'dguv_next_check': p.dguv_next_check.isoformat() if p.dguv_next_check else None,
        'dguv_interval_months': p.dguv_interval_months,
        'external_barcode': p.external_barcode,
    }


def get_inventory_categories():
    """Holt die verfügbaren Kategorien aus SystemSettings."""
    categories_setting = SystemSettings.query.filter_by(key='inventory_categories').first()
    if categories_setting and categories_setting.value:
        try:
            return json.loads(categories_setting.value)
        except:
            return []
    return []


def save_inventory_categories(categories, *, commit=True):
    """Speichert die Kategorienliste in SystemSettings."""
    categories = sorted(set(categories))
    categories_setting = SystemSettings.query.filter_by(key='inventory_categories').first()
    if categories_setting:
        categories_setting.value = json.dumps(categories)
    else:
        categories_setting = SystemSettings(
            key='inventory_categories',
            value=json.dumps(categories),
            description='Verfügbare Kategorien für Produkte'
        )
        db.session.add(categories_setting)
    if commit:
        db.session.commit()


def get_product_folders():
    """Holt alle Produktordner."""
    return ProductFolder.query.order_by(ProductFolder.name).all()


def _get_retired_folder(*, create=False):
    folder = ProductFolder.query.filter_by(name=RETIRED_FOLDER_NAME).first()
    if not folder:
        # Legacy-Migration: vorhandenen Systemordner "Ausgemustert" auf "Papierkorb" umbenennen
        legacy_folder = ProductFolder.query.filter_by(name='Ausgemustert').first()
        if legacy_folder:
            legacy_folder.name = RETIRED_FOLDER_NAME
            legacy_folder.description = 'Systemordner für Geräte im Papierkorb'
            folder = legacy_folder
    if folder or not create:
        return folder
    creator_id = getattr(current_user, 'id', None) or 1
    folder = ProductFolder(
        name=RETIRED_FOLDER_NAME,
        description='Systemordner für Geräte im Papierkorb',
        created_by=creator_id,
    )
    db.session.add(folder)
    db.session.flush()
    return folder


def _apply_retired_folder_assignment(product, *, create_folder=True):
    if not product:
        return
    retired_folder = _get_retired_folder(create=create_folder) if (create_folder or product.status == 'retired') else _get_retired_folder(create=False)
    if product.status == 'retired':
        if retired_folder:
            product.folder_id = retired_folder.id
        return
    if retired_folder and product.folder_id == retired_folder.id:
        product.folder_id = None


def _sync_retired_folder_assignments():
    retired_folder = _get_retired_folder(create=False)
    retired_products = Product.query.filter_by(status='retired').all()
    if not retired_products:
        return
    if not retired_folder:
        retired_folder = _get_retired_folder(create=True)
    changed = False
    for product in retired_products:
        if product.folder_id != retired_folder.id:
            product.folder_id = retired_folder.id
            changed = True
    if retired_folder:
        wrongly_assigned = Product.query.filter(
            Product.status != 'retired',
            Product.folder_id == retired_folder.id,
        ).all()
        for product in wrongly_assigned:
            product.folder_id = None
            changed = True
    if changed:
        db.session.commit()


def check_borrow_permission(user=None):
    """Prüft ob der User ausleihen darf (Session-User oder API-Token-User)."""
    if user is None:
        if not current_user.is_authenticated:
            return False
        user = current_user
    # Gast-Accounts können nicht ausleihen
    if hasattr(user, 'is_guest') and user.is_guest:
        return False
    if getattr(user, 'is_admin', False):
        return True
    return bool(getattr(user, 'can_borrow', False))


def generate_transaction_number():
    """Generiert eine eindeutige Ausleihvorgangsnummer."""
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"INV-{timestamp}-{random_part}"


def generate_borrow_group_id():
    """Generiert eine eindeutige Gruppierungs-ID für Mehrfachausleihen."""
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"INV-{timestamp}-{random_part}"


# ========== Frontend Routes ==========

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

    stats = {
        'total': Product.query.count(),
        'available': Product.query.filter_by(status='available').count(),
        'borrowed': Product.query.filter_by(status='borrowed').count(),
        'defective': Product.query.filter(
            Product.status.in_(('defective', 'in_repair'))
        ).count(),
        'overdue': Checkout.query.filter(
            Checkout.status.in_(('active', 'partially_returned')),
            Checkout.end_date < datetime.combine(date_cls.today(), datetime.min.time()),
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
            return render_template('inventory/product_form.html', categories=categories, folders=folders)
        
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
            return render_template('inventory/product_form.html', categories=categories, folders=folders)
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
                return render_template('inventory/product_form.html', categories=categories, folders=folders)
        except ValueError:
            flash(_('inventory.flash.invalid_quantity'), 'danger')
            categories = get_inventory_categories()
            folders = get_product_folders()
            return render_template('inventory/product_form.html', categories=categories, folders=folders)
        
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
            return render_template('inventory/product_form.html', categories=categories, folders=folders)
    
    categories = get_inventory_categories()
    folders = get_product_folders()
    
    return render_template('inventory/product_form.html', categories=categories, folders=folders)


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
            return render_template('inventory/product_form.html', product=product, categories=categories, folders=folders)
        
        product.name = name
        product.description = request.form.get('description', '').strip() or None
        product.category = request.form.get('category', '').strip() or None
        product.serial_number = request.form.get('serial_number', '').strip() or None
        product.condition = request.form.get('condition', '').strip() or None
        product.location = request.form.get('location', '').strip() or None
        
        length_input = request.form.get('length', '').strip()
        if length_input:
            normalized_length, _unused = normalize_length_input(length_input)
            if normalized_length is None:
                flash(translate('inventory.flash.invalid_length'), 'danger')
                categories = get_inventory_categories()
                folders = get_product_folders()
                purchase_date_formatted = product.purchase_date.strftime('%Y-%m-%d') if product.purchase_date else ''
                return render_template('inventory/product_form.html', product=product, purchase_date_formatted=purchase_date_formatted, categories=categories, folders=folders)
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
        
        if request.form.get('convert_to_cable') != '1':
            flash(_('inventory.flash.product_updated', name=name), 'success')
        return redirect(url_for('inventory.stock'))
    
    purchase_date_formatted = product.purchase_date.strftime('%Y-%m-%d') if product.purchase_date else ''
    
    categories = get_inventory_categories()
    folders = get_product_folders()
    
    return render_template('inventory/product_form.html', product=product, purchase_date_formatted=purchase_date_formatted, categories=categories, folders=folders)


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
                parsed = parse_qr_code(qr_code)
                current_app.logger.debug(f'QR-Code geparst: {parsed}, Original: {qr_code}')
                if parsed:
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
                        product_set = ProductSet.query.get(qr_id)
                        current_app.logger.debug(f'Set gefunden: {product_set.id if product_set else None}')
                elif looks_like_return_qr(qr_code):
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
                else:
                    try:
                        direct_product_id = int(qr_code)
                        product = Product.query.get(direct_product_id)
                        current_app.logger.debug(f'Direkte Produkt-ID: {direct_product_id}, Produkt gefunden: {product.id if product else None}')
                    except (ValueError, TypeError):
                        current_app.logger.debug(f'QR-Code konnte nicht als Produkt-ID interpretiert werden: {qr_code}')
                        pass  # Keine gültige Produkt-ID
                if not product and not product_set and qr_code:
                    product = Product.query.filter_by(external_barcode=qr_code).first()
                # Klartext: Produkt- oder Set-Name (exakt, sonst eindeutiger Teiltreffer)
                if not product and not product_set and qr_code:
                    name_q = qr_code.strip()
                    looks_like_code = bool(
                        parse_qr_code(name_q)
                        or looks_like_return_qr(name_q)
                        or name_q.isdigit()
                    )
                    if not looks_like_code:
                        product = Product.query.filter(Product.name.ilike(name_q)).first()
                        if not product:
                            product_set = ProductSet.query.filter(ProductSet.name.ilike(name_q)).first()
                        if not product and not product_set:
                            product_hits = Product.query.filter(Product.name.ilike(f'%{name_q}%')).limit(5).all()
                            set_hits = ProductSet.query.filter(ProductSet.name.ilike(f'%{name_q}%')).limit(5).all()
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
                    product = Product.query.get(item.product_id)
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
    stock_adjusted = 0
    mark_missing = request.form.get('mark_missing') in ('1', 'on', 'true', 'yes')

    from app.services.inventory import StockService

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
            item.product.status = 'missing'
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

def _sync_inventory_products(inventory):
    """Stellt sicher, dass alle relevanten Produkte (inkl. Defekt/Fehlend) in der Inventur sind."""
    if not inventory or inventory.status != 'active':
        return 0
    existing_ids = {
        row[0]
        for row in db.session.query(InventoryItem.product_id)
        .filter_by(inventory_id=inventory.id)
        .all()
    }
    products = Product.query.filter(Product.status != 'retired').all()
    added = 0
    for product in products:
        if product.id in existing_ids:
            continue
        db.session.add(InventoryItem(inventory_id=inventory.id, product_id=product.id))
        added += 1
    if added:
        db.session.commit()
    return added


@inventory_bp.route('/api/inventory/<int:inventory_id>/items', methods=['GET'])
@login_required
def api_inventory_items(inventory_id):
    """API: Alle Items einer Inventur abrufen."""
    inventory = Inventory.query.get_or_404(inventory_id)
    _sync_inventory_products(inventory)
    
    items = InventoryItem.query.filter_by(inventory_id=inventory_id).options(
        joinedload(InventoryItem.product),
        joinedload(InventoryItem.checker)
    ).all()
    
    result = []
    for item in items:
        if not item.product:
            continue
        # Ausgemusterte weiterhin anzeigen, falls schon in Inventur; neue kommen nicht dazu
        result.append({
            'id': item.id,
            'product_id': item.product_id,
            'product_name': item.product.name,
            'product_category': item.product.category,
            'product_location': item.product.location,
            'product_condition': item.product.condition,
            'product_status': item.product.status,
            'checked': item.checked,
            'notes': item.notes,
            'location_changed': item.location_changed,
            'new_location': item.new_location,
            'condition_changed': item.condition_changed,
            'new_condition': item.new_condition,
            'checked_by': item.checked_by,
            'checked_by_name': item.checker.full_name if item.checker else None,
            'checked_at': item.checked_at.isoformat() if item.checked_at else None,
            'updated_at': item.updated_at.isoformat(),
            'version': item.version,
        })
    
    return jsonify({
        'inventory': {
            'id': inventory.id,
            'name': inventory.name,
            'status': inventory.status,
            'checked_count': inventory.checked_count,
            'total_count': inventory.total_count
        },
        'items': result
    })


@inventory_bp.route('/api/inventory/<int:inventory_id>/item/<int:product_id>/update', methods=['POST'])
@login_required
def api_inventory_item_update(inventory_id, product_id):
    """API: Produkt in Inventur aktualisieren."""
    inventory = Inventory.query.get_or_404(inventory_id)
    
    if inventory.status != 'active':
        return jsonify({'error': translate('inventory.errors.inventory_not_active')}), 400
    
    item = InventoryItem.query.filter_by(
        inventory_id=inventory_id,
        product_id=product_id
    ).first()
    
    if not item:
        return jsonify({'error': translate('inventory.errors.product_not_in_inventory')}), 404
    
    data = request.get_json()
    
    if 'checked' in data:
        item.checked = bool(data['checked'])
        if item.checked:
            item.checked_by = current_user.id
            item.checked_at = datetime.utcnow()
        else:
            item.checked_by = None
            item.checked_at = None
    
    if 'notes' in data:
        item.notes = data['notes'].strip() if data['notes'] else None
    
    if 'new_location' in data:
        new_location = data['new_location'].strip() if data['new_location'] else None
        item.new_location = new_location
        item.location_changed = new_location is not None and new_location != item.product.location
    
    if 'new_condition' in data:
        new_condition = data['new_condition'].strip() if data['new_condition'] else None
        item.new_condition = new_condition
        item.condition_changed = new_condition is not None and new_condition != item.product.condition
    
    db.session.commit()
    
    return jsonify({
        'success': True,
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


@inventory_bp.route('/api/inventory/<int:inventory_id>/item/<int:product_id>/check', methods=['POST'])
@login_required
def api_inventory_item_check(inventory_id, product_id):
    """API: Produkt in Inventur abhaken."""
    inventory = Inventory.query.get_or_404(inventory_id)
    
    if inventory.status != 'active':
        return jsonify({'error': translate('inventory.errors.inventory_not_active')}), 400
    
    item = InventoryItem.query.filter_by(
        inventory_id=inventory_id,
        product_id=product_id
    ).first()
    
    if not item:
        return jsonify({'error': translate('inventory.errors.product_not_in_inventory')}), 404
    
    data = request.get_json()
    checked = data.get('checked', True)
    
    item.checked = checked
    if checked:
        item.checked_by = current_user.id
        item.checked_at = datetime.utcnow()
    else:
        item.checked_by = None
        item.checked_at = None
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'checked': item.checked,
        'checked_by': item.checked_by,
        'checked_at': item.checked_at.isoformat() if item.checked_at else None
    })


@inventory_bp.route('/api/inventory/<int:inventory_id>/scan', methods=['POST'])
@login_required
def api_inventory_scan(inventory_id):
    """API: QR-Code scannen und zu Produkt navigieren."""
    inventory = Inventory.query.get_or_404(inventory_id)
    
    if inventory.status != 'active':
        return jsonify({'error': translate('inventory.errors.inventory_not_active')}), 400
    
    data = request.get_json()
    qr_data = data.get('qr_data', '').strip()
    
    if not qr_data:
        return jsonify({'error': translate('inventory.errors.qr_data_required')}), 400
    
    # QR-Code parsen
    parsed = parse_qr_code(qr_data)
    if not parsed:
        return jsonify({'error': translate('inventory.errors.invalid_qr_code')}), 400
    
    qr_type, qr_id = parsed
    
    if qr_type == 'product':
        product = Product.query.get(qr_id)
        if not product:
            return jsonify({'error': translate('inventory.errors.product_not_found')}), 404
        
        item = InventoryItem.query.filter_by(
            inventory_id=inventory_id,
            product_id=product.id
        ).first()
        
        if not item:
            return jsonify({'error': translate('inventory.errors.product_not_in_inventory')}), 404
        
        item.checked = True
        item.checked_by = current_user.id
        item.checked_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'product': {
                'id': product.id,
                'name': product.name,
                'category': product.category,
                'location': product.location,
                'condition': product.condition
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
    elif qr_type == 'set':
        product_set = ProductSet.query.get(qr_id)
        if not product_set:
            return jsonify({'error': 'Set nicht gefunden.'}), 404
        checked = []
        missing = []
        for set_item in product_set.items:
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
            checked.append({
                'id': set_item.product_id,
                'name': set_item.product.name if set_item.product else None,
            })
        db.session.commit()
        return jsonify({
            'success': True,
            'is_set': True,
            'set': {'id': product_set.id, 'name': product_set.name},
            'checked_products': checked,
            'missing_products': missing,
            'checked_count': len(checked),
        })
    else:
        return jsonify({'error': translate('inventory.errors.only_product_qr_supported')}), 400


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


# ========== API Endpoints ==========

@inventory_bp.route('/api/products', methods=['GET'])
@login_required
def api_products():
    """API: Liste aller Produkte mit Such- und Filteroptionen."""
    try:
        search = request.args.get('search', '').strip()
        category = request.args.get('category', '').strip()
        status = request.args.get('status', '').strip()
        sort_by_param = request.args.get('sort_by', 'name')
        sort_dir_param = request.args.get('sort_dir', 'asc')
        
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
            
            products = products_query.all()
            
            if sort_by == 'length':
                def length_sort_key(prod):
                    meters = parse_length_to_meters(getattr(prod, 'length', None))
                    if meters is None:
                        return (1, 0.0)
                    return (0, -meters if descending else meters)
                
                products.sort(key=length_sort_key)
        except Exception as e:
            current_app.logger.warning(f"joinedload fehlgeschlagen, verwende Standard-Query: {e}")
            products = query.order_by(Product.name).all()
        
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
        
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Kritischer Fehler in api_products: {e}", exc_info=True)
        return jsonify({'error': f'Server-Fehler: {str(e)}'}), 500


@inventory_bp.route('/api/products/<int:product_id>', methods=['GET'])
@login_required
def api_product_get(product_id):
    """API: Einzelnes Produkt abrufen."""
    product = Product.query.options(joinedload(Product.folder)).get_or_404(product_id)
    
    image_path_value = None
    if product.image_path:
        if os.path.isabs(product.image_path):
            image_path_value = os.path.basename(product.image_path)
        else:
            image_path_value = product.image_path
    
    return jsonify({
        'id': product.id,
        'name': product.name,
        'description': product.description,
        'category': product.category,
        'serial_number': product.serial_number,
        'condition': product.condition,
        'location': product.location,
        'length': product.length,
        'length_meters': parse_length_to_meters(product.length),
        'folder_id': product.folder_id,
        'folder_name': product.folder.name if product.folder else None,
        'purchase_date': product.purchase_date.isoformat() if product.purchase_date else None,
        'status': product.status,
        'item_type': product.item_type,
        'on_hand': product.total_on_hand,
        'available': product.total_available,
        'image_path': image_path_value,
        'qr_code_data': product.qr_code_data,
        'created_at': product.created_at.isoformat(),
        'created_by': product.created_by,
        **_product_extra_fields(product),
    })


@inventory_bp.route('/api/products', methods=['POST'])
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
        created_by=current_user.id
    )
    
    qr_data = generate_product_qr_code(product.id)
    product.qr_code_data = qr_data
    
    db.session.add(product)
    db.session.flush()
    
    qr_data = generate_product_qr_code(product.id)
    product.qr_code_data = qr_data
    db.session.commit()
    
    return jsonify({
        'id': product.id,
        'name': product.name,
        'qr_code_data': product.qr_code_data
    }), 201


@inventory_bp.route('/api/products/<int:product_id>', methods=['PUT'])
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
    
    db.session.commit()
    
    return jsonify({'message': 'Produkt aktualisiert.'})


@inventory_bp.route('/api/products/<int:product_id>', methods=['DELETE'])
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

        product.status = 'retired'
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


@inventory_bp.route('/api/products/bulk-update', methods=['POST'])
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
                product.status = updates['status']
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


@inventory_bp.route('/api/products/bulk-delete', methods=['POST'])
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

            product.status = 'retired'
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


@inventory_bp.route('/api/folders', methods=['GET', 'POST'])
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


@inventory_bp.route('/api/inventory/filter-options', methods=['GET'])
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
        return jsonify({'error': str(exc)}), 400
    
    return jsonify({
        'transaction_id': checkout.id,
        'checkout_id': checkout.id,
        'transaction_number': checkout.checkout_number,
        'borrow_group_id': checkout.checkout_number,
        'qr_code_data': checkout.qr_code_data,
        'receipt_email_sent': bool(getattr(checkout, 'receipt_email_sent', False)),
        'checkout': serialize_checkout(checkout),
    }), 201


@inventory_bp.route('/api/borrows', methods=['GET'])
@login_required
def api_borrows():
    """API: Checkout-Items für Historie-UI (inkl. zurückgegebene)."""
    status = request.args.get('status', 'all')
    mine = request.args.get('mine', '').lower() in ('1', 'true', 'yes')
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
    if mine:
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


@inventory_bp.route('/api/borrows/my', methods=['GET'])
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
    """API: Rueckgabe eines oder mehrerer Checkout-Items."""
    from app.services.inventory.checkout_service import (
        find_active_checkout_item_for_product,
        return_checkout_items,
        return_checkout_by_ref,
    )
    data = request.get_json() or {}
    item_ids = data.get('item_ids') or data.get('return_item_ids') or []
    transaction_id = data.get('transaction_id')
    checkout_ref = data.get('checkout_number') or data.get('borrow_ref') or data.get('transaction_number')
    product_id = data.get('product_id')
    mark_defective = bool(data.get('mark_defective'))

    try:
        if item_ids:
            returned = return_checkout_items(item_ids, mark_defective=mark_defective)
            return jsonify({
                'success': True,
                'returned_count': len(returned),
                'return_email_sent': _return_email_ok(returned),
            })
        if transaction_id:
            returned = return_checkout_items([int(transaction_id)], mark_defective=mark_defective)
            return jsonify({
                'success': True,
                'returned_count': len(returned),
                'return_email_sent': _return_email_ok(returned),
            })
        if product_id:
            item = find_active_checkout_item_for_product(int(product_id))
            if not item:
                return jsonify({'error': translate('inventory.errors.no_active_borrow')}), 404
            returned = return_checkout_items([item.id], mark_defective=mark_defective)
            return jsonify({
                'success': True,
                'returned_count': len(returned),
                'return_email_sent': _return_email_ok(returned),
            })
        if checkout_ref:
            checkout = return_checkout_by_ref(str(checkout_ref))
            return jsonify({
                'success': True,
                'checkout_id': checkout.id,
                'status': checkout.status,
                'return_email_sent': bool(getattr(checkout, 'return_email_sent', True)),
            })
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

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

    if not current_user.is_admin and checkout.borrower_id != current_user.id and checkout.created_by != current_user.id:
        return jsonify({'error': 'Keine Berechtigung für diesen Ausleihschein.'}), 403

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

    if not current_user.is_admin and checkout.borrower_id != current_user.id and checkout.created_by != current_user.id:
        return jsonify({'error': 'Keine Berechtigung für diesen Rückgabeschein.'}), 403

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


# ========== Produktsets ==========

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


# ========== Dokumentenverwaltung ==========

@inventory_bp.route('/products/<int:product_id>/documents')
@login_required
def product_documents(product_id):
    """Dokumente eines Produkts anzeigen."""
    product = Product.query.get_or_404(product_id)
    documents = ProductDocument.query.filter_by(product_id=product_id).order_by(ProductDocument.created_at.desc()).all()
    from app.models.manual import Manual
    manuals = Manual.query.order_by(Manual.title).all()
    return render_template('inventory/product_documents.html', product=product, documents=documents, manuals=manuals)


@inventory_bp.route('/products/<int:product_id>/documents/upload', methods=['POST'])
@login_required
def product_document_upload(product_id):
    """Dokument für ein Produkt hochladen."""
    product = Product.query.get_or_404(product_id)
    
    if 'file' not in request.files:
        flash(_('inventory.flash.no_file_selected'), 'danger')
        return redirect(url_for('inventory.product_documents', product_id=product_id))
    
    file = request.files['file']
    file_type = request.form.get('file_type', 'other')
    manual_id = request.form.get('manual_id', type=int) or None
    
    if file.filename == '':
        flash(_('inventory.flash.no_file_selected'), 'danger')
        return redirect(url_for('inventory.product_documents', product_id=product_id))
    
    # Datei speichern
    filename = secure_filename(file.filename)
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    stored_filename = f"{timestamp}_{filename}"
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_documents')
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, stored_filename)
    file.save(filepath)
    absolute_filepath = os.path.abspath(filepath)
    
    # Dokument-Eintrag erstellen
    document = ProductDocument(
        product_id=product_id,
        manual_id=manual_id,
        file_path=absolute_filepath,
        file_name=filename,
        file_type=file_type,
        file_size=os.path.getsize(absolute_filepath),
        uploaded_by=current_user.id
    )
    
    db.session.add(document)
    db.session.commit()
    
    flash(_('inventory.flash.document_uploaded', filename=filename), 'success')
    return redirect(url_for('inventory.product_documents', product_id=product_id))


@inventory_bp.route('/products/<int:product_id>/documents/<int:document_id>/delete', methods=['POST'])
@login_required
def product_document_delete(product_id, document_id):
    """Dokument löschen."""
    document = ProductDocument.query.get_or_404(document_id)
    
    if document.product_id != product_id:
        flash(translate('inventory.flash.invalid_request'), 'danger')
        return redirect(url_for('inventory.product_documents', product_id=product_id))
    
    # Datei löschen
    if os.path.exists(document.file_path):
        try:
            os.remove(document.file_path)
        except Exception as e:
            current_app.logger.error(f"Fehler beim Löschen der Datei: {e}")
    
    filename = document.file_name
    db.session.delete(document)
    db.session.commit()
    
    flash(_('inventory.flash.document_deleted', filename=filename), 'success')
    return redirect(url_for('inventory.product_documents', product_id=product_id))


@inventory_bp.route('/products/<int:product_id>/documents/<int:document_id>/download')
@login_required
def product_document_download(product_id, document_id):
    """Dokument herunterladen."""
    document = ProductDocument.query.get_or_404(document_id)
    
    if document.product_id != product_id:
        flash(_('inventory.flash.invalid_request'), 'danger')
        return redirect(url_for('inventory.product_documents', product_id=product_id))
    
    if not os.path.exists(document.file_path):
        flash(_('inventory.flash.file_not_found'), 'danger')
        return redirect(url_for('inventory.product_documents', product_id=product_id))
    
    return send_file(document.file_path, as_attachment=True, download_name=document.file_name)


@inventory_bp.route('/api/products/<int:product_id>/documents', methods=['GET'])
@login_required
def api_product_documents(product_id):
    """API: Liste aller Dokumente eines Produkts."""
    product = Product.query.get_or_404(product_id)
    documents = ProductDocument.query.filter_by(product_id=product_id).order_by(ProductDocument.created_at.desc()).all()
    
    result = []
    for doc in documents:
        result.append({
            'id': doc.id,
            'file_name': doc.file_name,
            'file_type': doc.file_type,
            'file_size': doc.file_size,
            'manual_id': doc.manual_id,
            'created_at': doc.created_at.isoformat(),
            'uploaded_by': doc.uploaded_by
        })
    
    return jsonify(result)


# ========== Erweiterte Suche & Filter ==========

@inventory_bp.route('/api/search', methods=['GET'])
@login_required
def api_search():
    """Erweiterte Volltextsuche über alle Produktfelder (optional inkl. Sets)."""
    search_query = request.args.get('q', '').strip()
    include_sets = request.args.get('include_sets', '').lower() in ('1', 'true', 'yes')
    
    if not search_query:
        return jsonify({'error': translate('inventory.errors.search_term_required')}), 400
    
    # Volltextsuche über alle relevanten Felder
    search_pattern = f'%{search_query}%'
    products = Product.query.filter(
        or_(
            Product.name.ilike(search_pattern),
            Product.description.ilike(search_pattern),
            Product.serial_number.ilike(search_pattern),
            Product.category.ilike(search_pattern),
            Product.location.ilike(search_pattern),
            Product.condition.ilike(search_pattern)
        )
    ).order_by(Product.name).limit(20).all()
    
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
            'type': 'product',
        })

    if not include_sets:
        return jsonify(result)

    sets = ProductSet.query.filter(
        or_(
            ProductSet.name.ilike(search_pattern),
            ProductSet.description.ilike(search_pattern),
        )
    ).order_by(ProductSet.name).limit(10).all()
    set_results = [{
        'id': s.id,
        'name': s.name,
        'description': s.description,
        'product_count': len(s.items) if s.items is not None else 0,
        'type': 'set',
    } for s in sets]

    return jsonify({'products': result, 'sets': set_results})


@inventory_bp.route('/api/filters', methods=['GET'])
@login_required
def api_filters():
    """Gespeicherte Filter des aktuellen Benutzers laden."""
    filters = SavedFilter.query.filter_by(user_id=current_user.id).order_by(SavedFilter.created_at.desc()).all()
    
    result = []
    for f in filters:
        try:
            filter_data = json.loads(f.filter_data)
        except:
            filter_data = {}
        
        result.append({
            'id': f.id,
            'name': f.name,
            'filter_data': filter_data,
            'created_at': f.created_at.isoformat()
        })
    
    return jsonify(result)


@inventory_bp.route('/api/filters/save', methods=['POST'])
@login_required
def api_filter_save():
    """Filter speichern."""
    data = request.get_json()
    
    name = data.get('name', '').strip()
    filter_data = data.get('filter_data', {})
    
    if not name:
        return jsonify({'error': translate('inventory.errors.filter_name_required')}), 400
    
    existing = SavedFilter.query.filter_by(user_id=current_user.id, name=name).first()
    if existing:
        return jsonify({'error': translate('inventory.errors.filter_name_exists')}), 400
    
    saved_filter = SavedFilter(
        user_id=current_user.id,
        name=name,
        filter_data=json.dumps(filter_data)
    )
    
    db.session.add(saved_filter)
    db.session.commit()
    
    return jsonify({
        'id': saved_filter.id,
        'name': saved_filter.name,
        'message': 'Filter erfolgreich gespeichert.'
    })


@inventory_bp.route('/api/filters/<int:filter_id>', methods=['DELETE'])
@login_required
def api_filter_delete(filter_id):
    """Gespeicherten Filter löschen."""
    saved_filter = SavedFilter.query.get_or_404(filter_id)
    
    if saved_filter.user_id != current_user.id:
        return jsonify({'error': translate('inventory.errors.no_permission')}), 403
    
    db.session.delete(saved_filter)
    db.session.commit()
    
    return jsonify({'message': 'Filter erfolgreich gelöscht.'})


@inventory_bp.route('/api/favorites', methods=['GET'])
@login_required
def api_favorites():
    """Favoriten des aktuellen Benutzers laden."""
    favorites = ProductFavorite.query.filter_by(user_id=current_user.id).all()
    product_ids = [f.product_id for f in favorites]
    
    products = Product.query.filter(Product.id.in_(product_ids)).all()
    
    result = []
    for p in products:
        result.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'category': p.category,
            'status': p.status
        })
    
    return jsonify(result)


@inventory_bp.route('/api/favorites/<int:product_id>', methods=['POST', 'DELETE'])
@login_required
def api_favorite_toggle(product_id):
    """Favorit hinzufügen oder entfernen."""
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        existing = ProductFavorite.query.filter_by(
            user_id=current_user.id,
            product_id=product_id
        ).first()
        
        if existing:
            return jsonify({'message': 'Produkt ist bereits ein Favorit.'}), 400
        
        favorite = ProductFavorite(
            user_id=current_user.id,
            product_id=product_id
        )
        db.session.add(favorite)
        db.session.commit()
        
        return jsonify({'message': 'Produkt zu Favoriten hinzugefügt.'})
    
    elif request.method == 'DELETE':
        favorite = ProductFavorite.query.filter_by(
            user_id=current_user.id,
            product_id=product_id
        ).first()
        
        if not favorite:
            return jsonify({'error': translate('inventory.errors.product_not_favorite')}), 404
        
        db.session.delete(favorite)
        db.session.commit()
        
        return jsonify({'message': 'Produkt aus Favoriten entfernt.'})


# ========== Statistiken & Analytics Dashboard ==========

@inventory_bp.route('/statistics')
@login_required
def statistics():
    """Statistiken-Dashboard."""
    return render_template('inventory/statistics.html')




@inventory_bp.route('/api/statistics', methods=['GET'])
@login_required
def api_statistics():
    """API: Aggregierte Statistiken für Dashboard."""
    try:
        from sqlalchemy import func, extract
        
        # Gesamtbestand
        total_products = Product.query.count()
        
        # Ausgeliehene Artikel
        borrowed_count = Product.query.filter_by(status='borrowed').count()
        
        # Überfällige Checkout-Items
        overdue_count = CheckoutItem.query.join(Checkout).filter(
            CheckoutItem.returned_at.is_(None),
            Checkout.status.in_(('active', 'partially_returned')),
            Checkout.end_date < datetime.combine(date.today(), datetime.min.time()),
        ).count()
        
        # Verfügbare Artikel
        available_count = Product.query.filter_by(status='available').count()
        
        # Verfügbarkeitsquote
        availability_rate = (available_count / total_products * 100) if total_products > 0 else 0
        
        # Meist ausgeliehene Produkte (Top 10)
        try:
            returned_count = CheckoutItem.query.filter(CheckoutItem.returned_at.isnot(None)).count()
            if returned_count > 0:
                top_borrowed = db.session.query(
                    Product.id,
                    Product.name,
                    func.count(CheckoutItem.id).label('borrow_count')
                ).join(
                    CheckoutItem, Product.id == CheckoutItem.product_id
                ).filter(
                    CheckoutItem.returned_at.isnot(None)
                ).group_by(
                    Product.id, Product.name
                ).order_by(
                    func.count(CheckoutItem.id).desc()
                ).limit(10).all()
                
                top_borrowed_list = [{
                    'id': p.id,
                    'name': p.name,
                    'borrow_count': p.borrow_count
                } for p in top_borrowed]
            else:
                top_borrowed_list = []
        except Exception as e:
            current_app.logger.error(f"Fehler bei Top-Borrowed-Query: {e}", exc_info=True)
            top_borrowed_list = []
        
        # Kategorienverteilung
        try:
            category_distribution = db.session.query(
                Product.category,
                func.count(Product.id).label('count')
            ).filter(
                Product.category.isnot(None)
            ).group_by(
                Product.category
            ).all()
            
            category_data = [{
                'category': c.category or 'Keine Kategorie',
                'count': c.count
            } for c in category_distribution]
        except Exception as e:
            current_app.logger.error(f"Fehler bei Kategorienverteilung: {e}")
            category_data = []
        
        # Zeitreihen-Daten für Ausleihtrends (letzte 12 Monate)
        try:
            twelve_months_ago = datetime.utcnow() - timedelta(days=365)
            monthly_borrows = db.session.query(
                extract('year', Checkout.start_date).label('year'),
                extract('month', Checkout.start_date).label('month'),
                func.count(Checkout.id).label('count')
            ).filter(
                Checkout.start_date >= twelve_months_ago
            ).group_by(
                extract('year', Checkout.start_date),
                extract('month', Checkout.start_date)
            ).order_by(
                extract('year', Checkout.start_date),
                extract('month', Checkout.start_date)
            ).all()
            
            monthly_data = []
            for m in monthly_borrows:
                monthly_data.append({
                    'month': f"{int(m.month):02d}/{int(m.year)}",
                    'count': m.count
                })
        except Exception as e:
            current_app.logger.error(f"Fehler bei Monatstrends: {e}")
            monthly_data = []
        
        try:
            status_distribution = db.session.query(
                Product.status,
                func.count(Product.id).label('count')
            ).group_by(
                Product.status
            ).all()
            
            status_data = [{
                'status': s.status,
                'count': s.count
            } for s in status_distribution]
        except Exception as e:
            current_app.logger.error(f"Fehler bei Status-Verteilung: {e}")
            status_data = []
        
        return jsonify({
            'overview': {
                'total_products': total_products,
                'borrowed_count': borrowed_count,
                'overdue_count': overdue_count,
                'available_count': available_count,
                'availability_rate': round(availability_rate, 2)
            },
            'top_borrowed': top_borrowed_list,
            'category_distribution': category_data,
            'monthly_trends': monthly_data,
            'status_distribution': status_data
        })
    except Exception as e:
        current_app.logger.error(f"Fehler in api_statistics: {e}", exc_info=True)
        return jsonify({
            'error': 'Fehler beim Laden der Statistiken',
            'message': str(e)
        }), 500


# ========== Mobile API ==========

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
            returned = return_checkout_items(item_ids, mark_defective=mark_defective)
        elif transaction_id:
            # Compat: id kann Checkout-Item oder Checkout sein
            item = CheckoutItem.query.get(int(transaction_id))
            if item:
                returned = return_checkout_items([item.id], mark_defective=mark_defective)
            else:
                checkout = Checkout.query.get(int(transaction_id))
                if not checkout:
                    return jsonify({'error': translate('inventory.errors.transaction_id_required')}), 400
                returned = return_checkout_items([i.id for i in checkout.active_items], mark_defective=mark_defective)
        elif product_id:
            item = find_active_checkout_item_for_product(int(product_id))
            if not item:
                return jsonify({'error': translate('inventory.errors.no_active_borrow')}), 404
            returned = return_checkout_items([item.id], mark_defective=mark_defective)
        else:
            return jsonify({'error': translate('inventory.errors.transaction_id_required')}), 400
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
    qr_data = data.get('qr_data', '').strip()
    
    if not qr_data:
        return jsonify({'error': translate('inventory.errors.qr_data_required')}), 400
    
    # QR-Code parsen
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


@inventory_bp.route('/api/folders/<int:folder_id>', methods=['PUT', 'DELETE'])
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


@inventory_bp.route('/api/categories', methods=['GET', 'POST'])
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


@inventory_bp.route('/api/categories/<path:category_name>', methods=['PUT', 'DELETE'])
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

