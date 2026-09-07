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
from sqlalchemy import or_, and_, distinct
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

@inventory_bp.context_processor
def inject_inventory_trash_folder():
    """Papierkorb, Feature-Flags und Templates-Kontext bereitstellen."""
    from app.utils.inventory_features import inventory_feature_flags

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
    features = inventory_feature_flags()
    ctx = {
        'inventory_trash_folder': folder,
        'inventory_trash_url': trash_url,
        'is_inventory_trash_view': bool(folder and view_folder_id and int(view_folder_id) == int(folder.id)),
        'inventory_features': features,
        'owner_suggestions': [],
    }
    try:
        ep = request.endpoint or ''
        if features.get('owners') and ep in ('inventory.product_new', 'inventory.product_edit'):
            ctx['owner_suggestions'] = owner_suggestion_payload()
    except Exception:
        pass
    return ctx


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


def _normalize_external_barcode(value):
    """Inventar-Nr. vom Etikett: trimmen, Steuerzeichen entfernen, exakt behalten (inkl. führender Nullen)."""
    if value is None:
        return None
    text = re.sub(r'[\x00-\x1F\x7F]+', '', str(value)).strip()
    return text or None


def _external_barcode_taken(code, exclude_product_id=None):
    if not code:
        return False
    q = Product.query.filter_by(external_barcode=code)
    if exclude_product_id is not None:
        q = q.filter(Product.id != exclude_product_id)
    return q.first() is not None


def _can_use_as_numeric_product_id(code):
    """Numerische Produkt-ID nur ohne führende Nullen (sonst Kollision mit Inventar-Nr. 001)."""
    if not code or not str(code).isdigit():
        return False
    s = str(code)
    if len(s) > 1 and s.startswith('0'):
        return False
    return True


def _find_product_by_external_barcode(code):
    if not code:
        return None
    return Product.query.filter_by(external_barcode=code).first()


def _product_set_query():
    """ProductSet inkl. Items und Produkte (vermeidet N+1 beim Set-Scan)."""
    return ProductSet.query.options(
        selectinload(ProductSet.items).joinedload(ProductSetItem.product),
    )


def _lookup_product_or_set_by_scan(code):
    """
    Löst Scan-Code zu (product, product_set) auf.
    Reihenfolge: Inventar-Nr. → Portal-QR (PROD/SET) → numerische ID ohne führende Nullen.
    BORROW wird nicht hier aufgelöst (None, None).
    """
    from app.utils.qr_code import parse_qr_code

    code = (code or '').strip()
    if not code:
        return None, None

    product = _find_product_by_external_barcode(code)
    if product:
        return product, None

    parsed = parse_qr_code(code)
    if parsed:
        qr_type, qr_id = parsed
        if qr_type == 'product':
            return Product.query.get(qr_id), None
        if qr_type == 'set':
            return None, _product_set_query().get(qr_id)
        return None, None

    if _can_use_as_numeric_product_id(code):
        try:
            return Product.query.get(int(code)), None
        except (TypeError, ValueError):
            pass

    return None, None


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


def allowed_document_file(filename):
    """Prüft ob eine Dokument-Endung erlaubt ist (PDF/PNG/JPEG + Office)."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_DOCUMENT_EXTENSIONS


def _normalize_document_file_type(raw):
    value = (raw or 'other').strip().lower()
    return value if value in DOCUMENT_FILE_TYPES else 'other'


def _product_documents_dir():
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_documents')
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _accessible_manuals():
    """Sichtbare Manuals für den aktuellen User (leer wenn Modul aus)."""
    from app.models.manual import Manual
    from app.utils.common import is_module_enabled
    from app.utils.module_visibility import accessible_query

    if not is_module_enabled('module_manuals'):
        return []
    return accessible_query(current_user, Manual, 'manuals').order_by(Manual.title).all()


def _get_accessible_manual(manual_id):
    if not manual_id:
        return None
    from app.models.manual import Manual
    from app.utils.common import is_module_enabled
    from app.utils.module_visibility import can_view_item

    if not is_module_enabled('module_manuals'):
        return None
    manual = Manual.query.get(manual_id)
    if not manual or not can_view_item(current_user, manual, 'manuals'):
        return None
    return manual


def _save_document_upload(file_storage, *, copy_from_path=None, original_name=None):
    """Speichert Upload oder kopiert bestehende Datei. Returns (abs_path, file_name, size)."""
    import shutil

    upload_dir = _product_documents_dir()
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')

    if copy_from_path:
        base_name = secure_filename(original_name or os.path.basename(copy_from_path) or 'document')
        stored = f"{timestamp}_{secrets.token_hex(4)}_{base_name}"
        dest = os.path.join(upload_dir, stored)
        shutil.copy2(copy_from_path, dest)
        return os.path.abspath(dest), original_name or base_name, os.path.getsize(dest)

    filename = secure_filename(file_storage.filename or 'document')
    stored = f"{timestamp}_{filename}"
    dest = os.path.join(upload_dir, stored)
    file_storage.save(dest)
    abs_path = os.path.abspath(dest)
    return abs_path, file_storage.filename or filename, os.path.getsize(abs_path)


def _create_product_document(*, product_id, file_type, uploaded_by, file_path=None, file_name=None, file_size=None, manual_id=None):
    if not file_path and not manual_id:
        raise ValueError('file_path or manual_id required')
    doc = ProductDocument(
        product_id=product_id,
        manual_id=manual_id,
        file_path=file_path,
        file_name=file_name,
        file_type=_normalize_document_file_type(file_type),
        file_size=file_size,
        uploaded_by=uploaded_by,
    )
    db.session.add(doc)
    return doc


def _attach_form_documents_to_products(products, form, files):
    """Hängt Uploads und Manual-Links aus dem Produktformular an alle Produkte."""
    if not products:
        return 0

    file_type = _normalize_document_file_type(form.get('document_file_type', 'other'))
    uploaded = files.getlist('documents') if files else []
    saved_uploads = []
    for f in uploaded:
        if not f or not f.filename:
            continue
        if not allowed_document_file(f.filename):
            continue
        abs_path, orig_name, size = _save_document_upload(f)
        saved_uploads.append((abs_path, orig_name, size))

    manual_ids = []
    raw_ids = form.getlist('link_manual_ids') if hasattr(form, 'getlist') else []
    if not raw_ids:
        single = form.get('link_manual_id', type=int) if hasattr(form, 'get') else None
        if single:
            raw_ids = [single]
    for raw in raw_ids:
        try:
            mid = int(raw)
        except (TypeError, ValueError):
            continue
        if _get_accessible_manual(mid):
            manual_ids.append(mid)

    count = 0
    for idx, product in enumerate(products):
        for abs_path, orig_name, size in saved_uploads:
            if idx == 0:
                path, name, fsize = abs_path, orig_name, size
            else:
                path, name, fsize = _save_document_upload(
                    None, copy_from_path=abs_path, original_name=orig_name
                )
            _create_product_document(
                product_id=product.id,
                file_type=file_type,
                uploaded_by=current_user.id,
                file_path=path,
                file_name=name,
                file_size=fsize,
            )
            count += 1
        for mid in manual_ids:
            _create_product_document(
                product_id=product.id,
                file_type='handbook',
                uploaded_by=current_user.id,
                manual_id=mid,
            )
            count += 1
    return count


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


def inventory_number_display(product) -> str:
    """Anzeige-Inventar-Nr.: eigene Etiketten-Nr. oder Portal-Code PROD-{id}."""
    code = getattr(product, 'external_barcode', None)
    if code and str(code).strip():
        return str(code).strip()
    pid = getattr(product, 'id', None)
    if pid is not None:
        return f'PROD-{int(pid)}'
    return ''


def product_owner_display(product) -> str | None:
    """Lesbarer Eigentümer-Text für Listen/Detail."""
    label = (getattr(product, 'owner_label', None) or '').strip()
    if label:
        return label
    owner = getattr(product, 'owner_user', None)
    if owner is not None:
        return owner.full_name
    return None


def _apply_owner_from_form(product, form):
    """Setzt owner_user_id / owner_label aus Formularfeldern."""
    raw_user_id = (form.get('owner_user_id') or '').strip()
    raw_label = (form.get('owner_label') or form.get('owner_input') or '').strip()
    owner_user_id = None
    if raw_user_id.isdigit():
        uid = int(raw_user_id)
        user = User.query.filter_by(id=uid, is_active=True).first()
        if user and not getattr(user, 'is_guest', False):
            owner_user_id = user.id
            if not raw_label:
                raw_label = user.full_name
    product.owner_user_id = owner_user_id
    product.owner_label = raw_label or None


def _apply_owner_from_data(product, data: dict):
    """Setzt Eigentümer aus JSON/API-Payload."""
    raw_user_id = data.get('owner_user_id')
    raw_label = data.get('owner_label')
    if raw_label is None:
        raw_label = data.get('owner_input')
    raw_label = (str(raw_label).strip() if raw_label is not None else '')
    owner_user_id = None
    if raw_user_id is not None and str(raw_user_id).strip().isdigit():
        uid = int(raw_user_id)
        user = User.query.filter_by(id=uid, is_active=True).first()
        if user and not getattr(user, 'is_guest', False):
            owner_user_id = user.id
            if not raw_label:
                raw_label = user.full_name
    product.owner_user_id = owner_user_id
    product.owner_label = raw_label or None


def owner_suggestion_payload():
    """Portalnutzer + bisherige Freitext-Labels für Combobox/Filter."""
    users = (
        User.query.filter_by(is_active=True, is_guest=False)
        .order_by(User.last_name, User.first_name)
        .all()
    )
    user_items = [
        {'id': u.id, 'label': u.full_name, 'type': 'user'}
        for u in users
    ]
    labels = (
        db.session.query(distinct(Product.owner_label))
        .filter(Product.owner_label.isnot(None), Product.owner_label != '')
        .all()
    )
    user_names = {u['label'].casefold() for u in user_items}
    free_labels = sorted(
        {lab[0].strip() for lab in labels if lab[0] and lab[0].strip() and lab[0].strip().casefold() not in user_names},
        key=lambda s: s.casefold(),
    )
    free_items = [{'id': None, 'label': lab, 'type': 'label'} for lab in free_labels]
    return user_items + free_items


def _product_extra_fields(p):
    display = inventory_number_display(p)
    owner_label = product_owner_display(p)
    return {
        'weight_kg': p.weight_kg,
        'width_cm': p.width_cm,
        'height_cm': p.height_cm,
        'depth_cm': p.depth_cm,
        'purchase_price': float(p.purchase_price) if p.purchase_price is not None else None,
        'replacement_value': float(p.replacement_value) if p.replacement_value is not None else None,
        'dguv_last_check': p.dguv_last_check.isoformat() if p.dguv_last_check else None,
        'dguv_next_check': p.dguv_next_check.isoformat() if p.dguv_next_check else None,
        'dguv_interval_months': p.dguv_interval_months,
        'external_barcode': p.external_barcode,
        'inventory_number_display': display,
        'inventory_number_is_portal': not bool(p.external_barcode and str(p.external_barcode).strip()),
        'owner_user_id': p.owner_user_id,
        'owner_label': p.owner_label,
        'owner_display': owner_label,
    }


def _serialize_product_api(product):
    """Einheitliche Produkt-JSON-Antwort für GET/Scan-Lookup."""
    image_path_value = None
    if product.image_path:
        if os.path.isabs(product.image_path):
            image_path_value = os.path.basename(product.image_path)
        else:
            image_path_value = product.image_path
    folder = getattr(product, 'folder', None)
    return {
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
        'folder_name': folder.name if folder else None,
        'purchase_date': product.purchase_date.isoformat() if product.purchase_date else None,
        'status': product.status,
        'item_type': product.item_type,
        'on_hand': product.total_on_hand,
        'available': product.total_available,
        'image_path': image_path_value,
        'qr_code_data': product.qr_code_data,
        'created_at': product.created_at.isoformat() if product.created_at else None,
        'created_by': product.created_by,
        **_product_extra_fields(product),
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

__all__ = [
    "allowed_document_file",
    "allowed_file",
    "check_borrow_permission",
    "generate_borrow_group_id",
    "generate_transaction_number",
    "get_inventory_categories",
    "get_product_folders",
    "inject_inventory_trash_folder",
    "save_inventory_categories",
    "_accessible_manuals",
    "_apply_dguv_fields",
    "_apply_dguv_from_form",
    "_apply_retired_folder_assignment",
    "_attach_form_documents_to_products",
    "_can_use_as_numeric_product_id",
    "_cart_product_source_sets_map",
    "_cart_total_count",
    "_clear_all_cart_set_meta",
    "_clear_cart_qty_for_product",
    "_clear_cart_set_meta_for_product",
    "_clear_dguv_fields",
    "_create_product_document",
    "_external_barcode_taken",
    "_find_product_by_external_barcode",
    "_flash_checkout_receipt_email",
    "_flash_return_email",
    "_get_accessible_manual",
    "_get_cart_qty_for_product",
    "_get_cart_qty_meta",
    "_get_cart_set_meta",
    "_get_retired_folder",
    "_lookup_product_or_set_by_scan",
    "_mark_cart_products_from_set",
    "_normalize_document_file_type",
    "_normalize_external_barcode",
    "_normalize_scanner_code",
    "_ordered_cart_products",
    "_parse_optional_date",
    "_parse_optional_float",
    "_parse_optional_int",
    "_product_documents_dir",
    "_product_extra_fields",
    "_product_set_query",
    "_return_email_ok",
    "_save_document_upload",
    "_serialize_product_api",
    "_serialize_set_members",
    "_set_cart_qty_for_product",
    "_source_set_api_payload",
    "_sync_retired_folder_assignments",
]
