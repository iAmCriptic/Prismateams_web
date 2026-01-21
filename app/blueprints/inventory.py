from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app, session, send_from_directory
from flask_login import login_required, current_user
from app import db
from app.utils.i18n import _, translate
from app.models.inventory import Product, BorrowTransaction, ProductFolder, ProductSet, ProductSetItem, ProductDocument, SavedFilter, ProductFavorite, Inventory, InventoryItem
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
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload
import os
import secrets
import string
from io import BytesIO

inventory_bp = Blueprint('inventory', __name__)

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def allowed_file(filename):
    """Prüft ob die Dateiendung erlaubt ist."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


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


def check_borrow_permission():
    """Prüft ob der aktuelle User ausleihen darf."""
    if not current_user.is_authenticated:
        return False
    # Gast-Accounts können nicht ausleihen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return False
    if current_user.is_admin:
        return True
    return current_user.can_borrow


def generate_transaction_number():
    """Generiert eine eindeutige Ausleihvorgangsnummer."""
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"INV-{timestamp}-{random_part}"


def generate_borrow_group_id():
    """Generiert eine eindeutige Gruppierungs-ID für Mehrfachausleihen."""
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"GRP-{timestamp}-{random_part}"


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
    # Meine aktuellen Ausleihen
    my_borrows = BorrowTransaction.query.filter_by(
        borrower_id=current_user.id,
        status='active'
    ).order_by(BorrowTransaction.borrow_date.desc()).all()
    
    return render_template('inventory/dashboard.html', my_borrows=my_borrows)


@inventory_bp.route('/stock')
@inventory_bp.route('/stock/<int:folder_id>')
@login_required
@check_module_access('module_inventory')
def stock(folder_id=None):
    """Bestandsübersicht mit optionaler Ordner-Filterung."""
    current_folder = None
    subfolders = []
    
    if folder_id:
        current_folder = ProductFolder.query.get(folder_id)
        if not current_folder:
            flash(_('inventory.flash.folder_not_found'), 'warning')
            return redirect(url_for('inventory.stock'))
    else:
        subfolders = ProductFolder.query.order_by(ProductFolder.name).all()
    
    return render_template('inventory/stock.html', 
                          current_folder=current_folder, 
                          subfolders=subfolders)


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
                    image_path=image_path,  # Gleiches Bild für alle
                    created_by=current_user.id
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
        
        purchase_date_str = request.form.get('purchase_date', '').strip()
        if purchase_date_str:
            try:
                product.purchase_date = datetime.strptime(purchase_date_str, '%Y-%m-%d').date()
            except ValueError:
                product.purchase_date = None
        else:
            product.purchase_date = None
        
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
        
        db.session.commit()
        
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
    
    if new_status not in ['available', 'borrowed', 'missing']:
        return jsonify({'success': False, 'error': 'Ungültiger Status.'}), 400
    
    product.status = new_status
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
    
    active_borrow = BorrowTransaction.query.filter_by(
        product_id=product_id,
        status='active'
    ).first()
    
    if active_borrow:
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
    """Mehrfachausleihe - mehrere Produkte gleichzeitig ausleihen."""
    if not check_borrow_permission():
        flash(_('inventory.flash.no_borrow_permission'), 'danger')
        return redirect(url_for('inventory.stock'))
    
    if request.method == 'GET':
        product_ids_str = request.args.get('product_ids', '')
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
        
        users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all()
        
        return render_template('inventory/borrow_multiple.html', products=products, users=users)
    
    if request.method == 'POST':
        product_ids_str = request.form.get('product_ids', '')
        if not product_ids_str:
            flash(translate('inventory.flash.no_products_selected'), 'danger')
            return redirect(url_for('inventory.stock'))
        
        try:
            product_ids = [int(pid) for pid in product_ids_str.split(',')]
        except ValueError:
            flash(translate('inventory.flash.invalid_product_ids'), 'danger')
            return redirect(url_for('inventory.stock'))
        
        expected_return_date_str = request.form.get('expected_return_date', '').strip()
        borrower_id = request.form.get('borrower_id', '').strip()
        
        if not expected_return_date_str:
            flash(_('inventory.flash.return_date_required'), 'danger')
            return redirect(url_for('inventory.borrow_multiple', product_ids=','.join(map(str, product_ids))))
        
        try:
            expected_return_date = datetime.strptime(expected_return_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash(_('inventory.flash.invalid_date_format'), 'danger')
            return redirect(url_for('inventory.borrow_multiple', product_ids=','.join(map(str, product_ids))))
        
        if expected_return_date < date.today():
            flash(_('inventory.flash.return_date_past'), 'danger')
            return redirect(url_for('inventory.borrow_multiple', product_ids=','.join(map(str, product_ids))))
        
        if borrower_id:
            try:
                borrower = User.query.get(int(borrower_id))
                if not borrower:
                    borrower = current_user
            except:
                borrower = current_user
        else:
            borrower = current_user
        
        products = Product.query.filter(Product.id.in_(product_ids)).all()
        transactions = []
        
        borrow_group_id = generate_borrow_group_id()
        
        for product in products:
            if product.status != 'available':
                continue
            
            transaction_number = generate_transaction_number()
            borrow_transaction = BorrowTransaction(
                transaction_number=transaction_number,
                borrow_group_id=borrow_group_id,
                product_id=product.id,
                borrower_id=borrower.id,
                borrowed_by_id=current_user.id,
                borrow_date=datetime.utcnow(),
                expected_return_date=expected_return_date,
                status='active'
            )
            
            qr_data = generate_borrow_qr_code(transaction_number)
            borrow_transaction.qr_code_data = qr_data
            product.status = 'borrowed'
            
            db.session.add(borrow_transaction)
            transactions.append(borrow_transaction)
        
        db.session.commit()
        
        flash(_('inventory.flash.borrow_success', count=len(transactions)), 'success')
        
        if transactions:
            from app.utils.email_sender import send_borrow_receipt_email
            email_sent = send_borrow_receipt_email(transactions)
            
            if email_sent:
                flash(_('inventory.flash.receipt_sent'), 'success')
            else:
                flash(_('inventory.flash.borrow_registered_no_email'), 'warning')
        
        return redirect(url_for('inventory.dashboard'))


@inventory_bp.route('/products/<int:product_id>/borrow', methods=['GET', 'POST'])
@login_required
def product_borrow(product_id):
    """Ausleihvorgang starten."""
    if not check_borrow_permission():
        flash(_('inventory.flash.no_borrow_permission'), 'danger')
        return redirect(url_for('inventory.stock'))
    
    product = Product.query.get_or_404(product_id)
    
    if product.status != 'available':
        flash(_('inventory.flash.product_unavailable'), 'danger')
        return redirect(url_for('inventory.stock'))
    
    if request.method == 'POST':
        expected_return_date_str = request.form.get('expected_return_date', '').strip()
        borrower_id = request.form.get('borrower_id', '').strip()
        
        if not expected_return_date_str:
            flash(_('inventory.flash.return_date_required'), 'danger')
            return render_template('inventory/borrow.html', product=product)
        
        try:
            expected_return_date = datetime.strptime(expected_return_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash(_('inventory.flash.invalid_date_format'), 'danger')
            return render_template('inventory/borrow.html', product=product)
        
        if expected_return_date < date.today():
            flash(_('inventory.flash.return_date_past'), 'danger')
            return render_template('inventory/borrow.html', product=product)
        
        if borrower_id:
            try:
                borrower = User.query.get(int(borrower_id))
                if not borrower:
                    borrower = current_user
            except:
                borrower = current_user
        else:
            borrower = current_user
        
        transaction_number = generate_transaction_number()
        
        borrow_transaction = BorrowTransaction(
            transaction_number=transaction_number,
            product_id=product.id,
            borrower_id=borrower.id,
            borrowed_by_id=current_user.id,
            borrow_date=datetime.utcnow(),
            expected_return_date=expected_return_date,
            status='active'
        )
        
        qr_data = generate_borrow_qr_code(transaction_number)
        borrow_transaction.qr_code_data = qr_data
        
        product.status = 'borrowed'
        product.qr_code_data = qr_data  # Temporär für Ausleihe
        
        db.session.add(borrow_transaction)
        db.session.commit()
        
        flash(_('inventory.flash.borrow_registered', transaction_number=transaction_number), 'success')
        
        from app.utils.email_sender import send_borrow_receipt_email
        email_sent = send_borrow_receipt_email(borrow_transaction)
        
        if email_sent:
            flash(_('inventory.flash.receipt_sent'), 'success')
        else:
            flash(_('inventory.flash.borrow_registered_no_email'), 'warning')
        
        return redirect(url_for('inventory.dashboard'))
    
    users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all()
    
    return render_template('inventory/borrow.html', product=product, users=users)


@inventory_bp.route('/borrows')
@login_required
def borrows():
    """Ausleih-Listen-Ansicht."""
    return render_template('inventory/borrows.html')


@inventory_bp.route('/return', methods=['GET', 'POST'])
@login_required
def return_item():
    """Rückgabe-Interface."""
    preset_transaction_number = request.args.get('transaction_number', '')
    
    if request.method == 'POST':
        qr_code = request.form.get('qr_code', '').strip()
        transaction_number = request.form.get('transaction_number', '').strip()
        
        borrow_transaction = None
        
        if qr_code:
            parsed = parse_qr_code(qr_code)
            if parsed:
                qr_type, identifier = parsed
                if qr_type == 'borrow':
                    borrow_transaction = BorrowTransaction.query.filter_by(
                        transaction_number=identifier,
                        status='active'
                    ).first()
                elif qr_type == 'product':
                    product = Product.query.get(identifier)
                    if product:
                        borrow_transaction = BorrowTransaction.query.filter_by(
                            product_id=product.id,
                            status='active'
                        ).first()
        
        elif transaction_number:
            borrow_transaction = BorrowTransaction.query.filter_by(
                transaction_number=transaction_number,
                status='active'
            ).first()
        
        if not borrow_transaction:
            flash(_('inventory.flash.no_active_borrow'), 'danger')
            return render_template('inventory/return.html', preset_transaction_number=preset_transaction_number)
        
        borrow_transaction.mark_as_returned()
        db.session.commit()
        
        from app.utils.email_sender import send_return_confirmation_email
        try:
            send_return_confirmation_email(borrow_transaction)
        except Exception as e:
            current_app.logger.error(f"Fehler beim Senden der Rückgabe-Bestätigung: {e}")
        
        flash(_('inventory.flash.return_success'), 'success')
        return redirect(url_for('inventory.dashboard'))
    
    return render_template('inventory/return.html', preset_transaction_number=preset_transaction_number)


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
            qr_code = request.form.get('qr_code', '').strip()
            product_id = request.form.get('product_id')
            
            product = None
            product_set = None
            
            if qr_code:
                parsed = parse_qr_code(qr_code)
                current_app.logger.debug(f'QR-Code geparst: {parsed}, Original: {qr_code}')
                if parsed:
                    qr_type, qr_id = parsed
                    if qr_type == 'product':
                        product = Product.query.get(qr_id)
                        current_app.logger.debug(f'Produkt gefunden: {product.id if product else None}')
                    elif qr_type == 'set':
                        product_set = ProductSet.query.get(qr_id)
                        current_app.logger.debug(f'Set gefunden: {product_set.id if product_set else None}')
                else:
                    try:
                        direct_product_id = int(qr_code)
                        product = Product.query.get(direct_product_id)
                        current_app.logger.debug(f'Direkte Produkt-ID: {direct_product_id}, Produkt gefunden: {product.id if product else None}')
                    except (ValueError, TypeError):
                        current_app.logger.debug(f'QR-Code konnte nicht als Produkt-ID interpretiert werden: {qr_code}')
                        pass  # Keine gültige Produkt-ID
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
                        'was_in_cart': info['was_in_cart']  # Ob bereits im Warenkorb
                    })
                
                session['borrow_cart'] = cart
                session.modified = True  # Stelle sicher, dass Session gespeichert wird
                
                return jsonify({
                    'success': True,
                    'is_set': True,
                    'set': {
                        'id': product_set.id,
                        'name': product_set.name,
                        'description': product_set.description
                    },
                    'added_products': added_products,
                    'unavailable_products': unavailable_products,
                    'cart_count': len(cart)
                })
            
            if not product:
                current_app.logger.warning(f'Produkt nicht gefunden für QR-Code: {qr_code}')
                return jsonify({'error': translate('inventory.errors.product_or_set_not_found')}), 404
            
            current_app.logger.debug(f'Produkt Status: {product.status}, ID: {product.id}, Name: {product.name}')
            if product.status != 'available':
                current_app.logger.warning(f'Produkt nicht verfügbar: {product.id}, Status: {product.status}')
                return jsonify({'error': f'Produkt ist nicht verfügbar. Status: {product.status}'}), 400
            
            cart = session.get('borrow_cart', [])
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
                    'category': product.category
                },
                'cart_count': len(cart)
            })
        
        elif action == 'remove_from_cart':
            product_id = int(request.form.get('product_id'))
            cart = session.get('borrow_cart', [])
            if product_id in cart:
                cart.remove(product_id)
                session['borrow_cart'] = cart
                session.modified = True  # Stelle sicher, dass Session gespeichert wird
            return jsonify({'success': True, 'cart_count': len(cart)})
        
        elif action == 'clear_cart':
            session.pop('borrow_cart', None)
            session.modified = True
            return jsonify({'success': True})
        else:
            current_app.logger.warning(f'Unbekannte Aktion in borrow_scanner: {action}')
            return jsonify({'error': f'Unbekannte Aktion: {action}'}), 400
    
    cart_product_ids = session.get('borrow_cart', [])
    cart_products = Product.query.filter(Product.id.in_(cart_product_ids)).all() if cart_product_ids else []
    
    users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all()
    
    return render_template('inventory/borrow_scanner.html', cart_products=cart_products, users=users)


@inventory_bp.route('/borrow-scanner/checkout', methods=['POST'])
@login_required
def borrow_scanner_checkout():
    """Warenkorb checkout - alle Produkte ausleihen."""
    if not check_borrow_permission():
        flash(_('inventory.flash.no_borrow_permission'), 'danger')
        return redirect(url_for('inventory.borrow_scanner'))
    
    cart_product_ids = session.get('borrow_cart', [])
    if not cart_product_ids:
        flash(_('inventory.flash.no_products_to_borrow'), 'danger')
        return redirect(url_for('inventory.borrow_scanner'))
    
    expected_return_date_str = request.form.get('expected_return_date', '').strip()
    borrower_id = request.form.get('borrower_id', '').strip()
    
    if not expected_return_date_str:
        flash(_('inventory.flash.return_date_required'), 'danger')
        return redirect(url_for('inventory.borrow_scanner'))
    
    try:
        expected_return_date = datetime.strptime(expected_return_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash(_('inventory.flash.invalid_date_format'), 'danger')
        return redirect(url_for('inventory.borrow_scanner'))
    
    if expected_return_date < date.today():
        flash(_('inventory.flash.return_date_past'), 'danger')
        return redirect(url_for('inventory.borrow_scanner'))
    
    # Ausleihender bestimmen
    if borrower_id:
        try:
            borrower = User.query.get(int(borrower_id))
            if not borrower:
                borrower = current_user
        except:
            borrower = current_user
    else:
        borrower = current_user
    
    # Alle Produkte ausleihen
    products = Product.query.filter(Product.id.in_(cart_product_ids)).all()
    transactions = []
    
    # Gemeinsame Gruppierungs-ID für alle Produkte dieser Mehrfachausleihe
    borrow_group_id = generate_borrow_group_id()
    
    for product in products:
        if product.status != 'available':
            continue
        
        transaction_number = generate_transaction_number()
        borrow_transaction = BorrowTransaction(
            transaction_number=transaction_number,
            borrow_group_id=borrow_group_id,
            product_id=product.id,
            borrower_id=borrower.id,
            borrowed_by_id=current_user.id,
            borrow_date=datetime.utcnow(),
            expected_return_date=expected_return_date,
            status='active'
        )
        
        qr_data = generate_borrow_qr_code(transaction_number)
        borrow_transaction.qr_code_data = qr_data
        product.status = 'borrowed'
        
        db.session.add(borrow_transaction)
        transactions.append(borrow_transaction)
    
    db.session.commit()
    
    session.pop('borrow_cart', None)
    
    flash(_('inventory.flash.borrow_success', count=len(transactions)), 'success')
    
    # PDF per E-Mail versenden mit allen Transaktionen
    if transactions:
        from app.utils.email_sender import send_borrow_receipt_email
        email_sent = send_borrow_receipt_email(transactions)
        
        if email_sent:
            flash(_('inventory.flash.receipt_sent'), 'success')
        else:
            flash(_('inventory.flash.borrow_registered_no_email'), 'warning')
    
    return redirect(url_for('inventory.dashboard'))


@inventory_bp.route('/inventory-list')
@login_required
def inventory_list():
    """Inventurliste - Übersicht aller Produkte für Inventur (Legacy)."""
    products = Product.query.order_by(Product.name).all()
    return render_template('inventory/inventory_list.html', products=products)


@inventory_bp.route('/inventory-list/pdf')
@login_required
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
    """Hauptseite für das Inventurtool."""
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
            
            products = Product.query.all()
            for product in products:
                inventory_item = InventoryItem(
                    inventory_id=new_inventory.id,
                    product_id=product.id
                )
                db.session.add(inventory_item)
            
            db.session.commit()
            flash(_('inventory.flash.inventory_started', name=name), 'success')
            return redirect(url_for('inventory.inventory_tool'))
    
    inventory_items = []
    if active_inventory:
        inventory_items = InventoryItem.query.filter_by(inventory_id=active_inventory.id).options(
            joinedload(InventoryItem.product),
            joinedload(InventoryItem.checker)
        ).all()
    
    return render_template('inventory/inventory_tool.html', 
                         active_inventory=active_inventory,
                         inventory_items=inventory_items)


@inventory_bp.route('/inventory-tool/<int:inventory_id>/complete', methods=['POST'])
@login_required
def inventory_complete(inventory_id):
    """Inventur abschließen und Änderungen auf Produkte anwenden."""
    inventory = Inventory.query.get_or_404(inventory_id)
    
    if inventory.status != 'active':
        flash(_('inventory.flash.inventory_completed'), 'warning')
        return redirect(url_for('inventory.inventory_tool'))
    
    items = InventoryItem.query.filter_by(inventory_id=inventory_id).all()
    updated_count = 0
    
    for item in items:
        if item.location_changed and item.new_location:
            item.product.location = item.new_location
            updated_count += 1
        
        if item.condition_changed and item.new_condition:
            item.product.condition = item.new_condition
            updated_count += 1
    
    inventory.status = 'completed'
    inventory.completed_at = datetime.utcnow()
    
    db.session.commit()
    
    flash(_('inventory.flash.inventory_finished', count=updated_count), 'success')
    return redirect(url_for('inventory.inventory_tool'))


@inventory_bp.route('/inventory-tool/history')
@login_required
def inventory_history():
    """Liste aller abgeschlossenen Inventuren."""
    completed_inventories = Inventory.query.filter_by(status='completed').order_by(
        Inventory.completed_at.desc()
    ).all()
    
    return render_template('inventory/inventory_history.html', inventories=completed_inventories)


@inventory_bp.route('/inventory-tool/<int:inventory_id>/pdf')
@login_required
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

@inventory_bp.route('/api/inventory/<int:inventory_id>/items', methods=['GET'])
@login_required
def api_inventory_items(inventory_id):
    """API: Alle Items einer Inventur abrufen."""
    inventory = Inventory.query.get_or_404(inventory_id)
    
    items = InventoryItem.query.filter_by(inventory_id=inventory_id).options(
        joinedload(InventoryItem.product),
        joinedload(InventoryItem.checker)
    ).all()
    
    result = []
    for item in items:
        result.append({
            'id': item.id,
            'product_id': item.product_id,
            'product_name': item.product.name,
            'product_category': item.product.category,
            'product_location': item.product.location,
            'product_condition': item.product.condition,
            'checked': item.checked,
            'notes': item.notes,
            'location_changed': item.location_changed,
            'new_location': item.new_location,
            'condition_changed': item.condition_changed,
            'new_condition': item.new_condition,
            'checked_by': item.checked_by,
            'checked_by_name': item.checker.full_name if item.checker else None,
            'checked_at': item.checked_at.isoformat() if item.checked_at else None,
            'updated_at': item.updated_at.isoformat()
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
def print_qr():
    """QR-Code-Druck."""
    if request.method == 'POST':
        product_ids = request.form.getlist('product_ids')
        label_type = request.form.get('label_type', 'cable')  # 'cable' oder 'device'
        
        if not product_ids:
            flash(_('inventory.flash.select_products'), 'danger')
            return redirect(url_for('inventory.print_qr'))
        
        try:
            product_ids = [int(pid) for pid in product_ids]
            products = Product.query.filter(Product.id.in_(product_ids)).all()
            
            if not products:
                flash(_('inventory.flash.no_valid_products'), 'danger')
                return redirect(url_for('inventory.print_qr'))
            
            pdf_buffer = BytesIO()
            generate_qr_code_sheet_pdf(products, pdf_buffer, label_type=label_type)
            pdf_buffer.seek(0)
            
            label_type_name = "Kabel" if label_type == 'cable' else "Geräte"
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
    
    products = Product.query.options(joinedload(Product.folder)).all()
    
    def sort_key(product):
        if product.folder:
            return (1, product.folder.name, product.name)
        else:
            return (0, '', product.name)
    
    products = sorted(products, key=sort_key)
    
    folders = ProductFolder.query.order_by(ProductFolder.name).all()
    
    return render_template('inventory/print_qr.html', products=products, folders=folders)


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
                    'image_path': image_path_value,
                    'qr_code_data': p.qr_code_data,
                    'created_at': p.created_at.isoformat(),
                    'created_by': p.created_by
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
        'image_path': image_path_value,
        'qr_code_data': product.qr_code_data,
        'created_at': product.created_at.isoformat(),
        'created_by': product.created_by
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
    """API: Produkt löschen."""
    # Gast-Accounts können keine Produkte löschen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return jsonify({'error': translate('inventory.errors.guests_cannot_delete')}), 403
    
    product = Product.query.get_or_404(product_id)
    
    active_borrow = BorrowTransaction.query.filter_by(
        product_id=product_id,
        status='active'
    ).first()
    
    if active_borrow:
        return jsonify({'error': translate('inventory.errors.product_borrowed_cannot_delete')}), 400
    
    # Prüfe ob Produkt in Produktsets enthalten ist
    set_items = ProductSetItem.query.filter_by(product_id=product_id).all()
    if set_items:
        set_names = [item.set.name for item in set_items if item.set]
        return jsonify({
            'error': f'Das Produkt "{product.name}" kann nicht gelöscht werden, da es in folgenden Produktsets enthalten ist: {", ".join(set_names)}. Bitte entfernen Sie das Produkt zuerst aus den Sets.'
        }), 400
    
    try:
        # Lösche zugehörige Produktset-Items (falls vorhanden)
        ProductSetItem.query.filter_by(product_id=product_id).delete()
        
        # Lösche Produktbild
        if product.image_path:
            image_path_full = product.image_path
            if not os.path.isabs(image_path_full):
                image_path_full = os.path.join(current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_images', image_path_full)
            
            if os.path.exists(image_path_full):
                try:
                    os.remove(image_path_full)
                except Exception as e:
                    current_app.logger.warning(f"Fehler beim Löschen des Bildes von Produkt {product_id}: {e}")
        
        # Lösche zugehörige Dokumente
        documents = ProductDocument.query.filter_by(product_id=product_id).all()
        for doc in documents:
            if doc.file_path and os.path.exists(doc.file_path):
                try:
                    os.remove(doc.file_path)
                except Exception as e:
                    current_app.logger.warning(f"Fehler beim Löschen des Dokuments {doc.id}: {e}")
            db.session.delete(doc)
        
        # Lösche das Produkt
        db.session.delete(product)
        db.session.commit()
        
        return jsonify({'message': 'Produkt gelöscht.'})
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
    
    if 'remove_image' in data and data.get('remove_image'):
        updates['remove_image'] = True
    
    if errors:
        return jsonify({'error': translate('inventory.errors.validation_error'), 'details': errors}), 400
    
    if not updates:
        return jsonify({'error': translate('inventory.errors.no_update_data')}), 400
    
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
    """API: Mehrere Produkte gleichzeitig löschen."""
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
    
    active_borrows = BorrowTransaction.query.filter(
        BorrowTransaction.product_id.in_(product_ids_int),
        BorrowTransaction.status == 'active'
    ).all()
    
    if active_borrows:
        borrowed_product_ids = [b.product_id for b in active_borrows]
        borrowed_products = [p for p in products if p.id in borrowed_product_ids]
        product_names = [p.name for p in borrowed_products]
        return jsonify({
            'error': 'Einige Produkte können nicht gelöscht werden, da sie ausgeliehen sind.',
            'details': product_names
        }), 400
    
    # Lösche Produkte und deren Bilder
    deleted_count = 0
    errors = []
    
    for product in products:
        product_id = product.id  # Speichere ID vor möglichem Rollback
        product_name = product.name  # Speichere Name für Fehlermeldung
        
        try:
            # Prüfe ob Produkt in Produktsets enthalten ist
            set_items = ProductSetItem.query.filter_by(product_id=product_id).all()
            if set_items:
                set_names = [item.set.name for item in set_items if item.set]
                return jsonify({
                    'error': f'Das Produkt "{product_name}" kann nicht gelöscht werden, da es in folgenden Produktsets enthalten ist: {", ".join(set_names)}. Bitte entfernen Sie das Produkt zuerst aus den Sets.',
                    'details': [f'Produkt in Set: {name}' for name in set_names]
                }), 400
            
            # Lösche zugehörige Produktset-Items (falls vorhanden)
            ProductSetItem.query.filter_by(product_id=product_id).delete()
            
            # Lösche Produktbild
            if product.image_path:
                image_path_full = product.image_path
                if not os.path.isabs(image_path_full):
                    image_path_full = os.path.join(current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_images', image_path_full)
                
                if os.path.exists(image_path_full):
                    try:
                        os.remove(image_path_full)
                    except Exception as e:
                        current_app.logger.warning(f"Fehler beim Löschen des Bildes von Produkt {product_id}: {e}")
            
            # Lösche auch zugehörige Dokumente
            documents = ProductDocument.query.filter_by(product_id=product_id).all()
            for doc in documents:
                if doc.file_path and os.path.exists(doc.file_path):
                    try:
                        os.remove(doc.file_path)
                    except Exception as e:
                        current_app.logger.warning(f"Fehler beim Löschen des Dokuments {doc.id}: {e}")
                db.session.delete(doc)
            
            # Lösche das Produkt
            db.session.delete(product)
            deleted_count += 1
            
        except Exception as e:
            db.session.rollback()
            error_msg = str(e)
            current_app.logger.error(f"Fehler beim Löschen von Produkt {product_id} ({product_name}): {e}", exc_info=True)
            
            # Prüfe ob es ein Foreign Key Constraint Fehler ist
            if 'foreign key constraint' in error_msg.lower() or '1451' in error_msg:
                errors.append(f'Das Produkt "{product_name}" kann nicht gelöscht werden, da es noch in Verwendung ist (z.B. in einem Produktset).')
            else:
                errors.append(f'Fehler bei Produkt "{product_name}" (ID: {product_id}): {error_msg}')
    
    if errors:
        db.session.rollback()
        return jsonify({'error': translate('inventory.errors.delete_error'), 'details': errors}), 500
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Fehler beim Commit der Löschung: {e}", exc_info=True)
        return jsonify({'error': 'Fehler beim Speichern der Änderungen. Bitte versuchen Sie es erneut.'}), 500
    
    return jsonify({
        'message': f'{deleted_count} Produkt(e) erfolgreich gelöscht.',
        'deleted_count': deleted_count
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
    """API: Ausleihvorgang registrieren."""
    if not check_borrow_permission():
        return jsonify({'error': translate('inventory.errors.no_borrow_permission')}), 403
    
    data = request.get_json()
    
    if not data:
        return jsonify({'error': translate('inventory.errors.no_data_submitted')}), 400
    
    product_id = data.get('product_id')
    borrower_id = data.get('borrower_id', current_user.id)
    expected_return_date_str = data.get('expected_return_date')
    
    if not product_id or not expected_return_date_str:
        return jsonify({'error': translate('inventory.errors.product_id_return_date_required')}), 400
    
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'error': translate('inventory.errors.product_not_found')}), 404
    
    if product.status != 'available':
        return jsonify({'error': translate('inventory.errors.product_not_available')}), 400
    
    try:
        expected_return_date = datetime.strptime(expected_return_date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': translate('inventory.errors.invalid_date_format')}), 400
    
    borrower = User.query.get(borrower_id)
    if not borrower:
        return jsonify({'error': translate('inventory.errors.user_not_found')}), 404
    
    transaction_number = generate_transaction_number()
    
    borrow_transaction = BorrowTransaction(
        transaction_number=transaction_number,
        product_id=product.id,
        borrower_id=borrower.id,
        borrowed_by_id=current_user.id,
        borrow_date=datetime.utcnow(),
        expected_return_date=expected_return_date,
        status='active'
    )
    
    qr_data = generate_borrow_qr_code(transaction_number)
    borrow_transaction.qr_code_data = qr_data
    
    product.status = 'borrowed'
    
    db.session.add(borrow_transaction)
    db.session.commit()
    
    return jsonify({
        'transaction_id': borrow_transaction.id,
        'transaction_number': transaction_number,
        'borrow_group_id': borrow_transaction.borrow_group_id,
        'qr_code_data': qr_data
    }), 201


@inventory_bp.route('/api/borrows', methods=['GET'])
@login_required
def api_borrows():
    """API: Liste aller aktuell ausgeliehenen Produkte."""
    borrows = BorrowTransaction.query.filter_by(
        status='active'
    ).order_by(BorrowTransaction.borrow_date.desc()).all()
    
    return jsonify([{
        'id': b.id,
        'transaction_number': b.transaction_number,
        'borrow_group_id': b.borrow_group_id,
        'product_id': b.product_id,
        'product_name': b.product.name,
        'borrower_id': b.borrower_id,
        'borrower_name': f"{b.borrower.first_name} {b.borrower.last_name}",
        'borrow_date': b.borrow_date.isoformat(),
        'expected_return_date': b.expected_return_date.isoformat(),
        'is_overdue': b.is_overdue,
        'qr_code_data': b.qr_code_data
    } for b in borrows])


@inventory_bp.route('/api/borrows/my', methods=['GET'])
@login_required
def api_borrows_my():
    """API: Meine aktuellen Ausleihen."""
    borrows = BorrowTransaction.query.filter_by(
        borrower_id=current_user.id,
        status='active'
    ).order_by(BorrowTransaction.borrow_date.desc()).all()
    
    return jsonify([{
        'id': b.id,
        'transaction_number': b.transaction_number,
        'borrow_group_id': b.borrow_group_id,
        'product_id': b.product_id,
        'product_name': b.product.name,
        'borrow_date': b.borrow_date.isoformat(),
        'expected_return_date': b.expected_return_date.isoformat(),
        'is_overdue': b.is_overdue,
        'qr_code_data': b.qr_code_data
    } for b in borrows])


@inventory_bp.route('/api/borrows/my/grouped', methods=['GET'])
@login_required
def api_borrows_my_grouped():
    """API: Meine Ausleihen gruppiert nach Ausleihvorgang (für Widget)."""
    borrows = BorrowTransaction.query.filter_by(
        borrower_id=current_user.id,
        status='active'
    ).order_by(BorrowTransaction.borrow_date.desc()).all()
    
    # Gruppiere nach borrow_group_id (oder falls None, nach transaction_number für Einzelausleihen)
    grouped = {}
    for b in borrows:
        # Verwende borrow_group_id falls vorhanden, sonst transaction_number für Einzelausleihen
        group_key = b.borrow_group_id if b.borrow_group_id else b.transaction_number
        
        if group_key not in grouped:
            grouped[group_key] = {
                'borrow_group_id': b.borrow_group_id,
                'borrow_date': b.borrow_date.isoformat(),
                'expected_return_date': b.expected_return_date.isoformat(),
                'transactions': [],
                'product_count': 0,
                'is_overdue': False
            }
        
        grouped[group_key]['transactions'].append({
            'id': b.id,
            'transaction_number': b.transaction_number,
            'product_id': b.product_id,
            'product_name': b.product.name,
            'expected_return_date': b.expected_return_date.isoformat(),
            'is_overdue': b.is_overdue,
            'qr_code_data': b.qr_code_data
        })
        
        # Aktualisiere erwartetes Rückgabedatum (spätestes Datum)
        current_max_date = date.fromisoformat(grouped[group_key]['expected_return_date'])
        if b.expected_return_date > current_max_date:
            grouped[group_key]['expected_return_date'] = b.expected_return_date.isoformat()
        
        if b.is_overdue:
            grouped[group_key]['is_overdue'] = True
    
    # Formatiere für Widget
    result = []
    for group_key, group_data in grouped.items():
        group_data['product_count'] = len(group_data['transactions'])
        # Entferne transactions aus der Hauptantwort (optional, kann auch enthalten bleiben)
        result.append({
            'borrow_group_id': group_data['borrow_group_id'],
            'borrow_date': group_data['borrow_date'],
            'expected_return_date': group_data['expected_return_date'],
            'product_count': group_data['product_count'],
            'is_overdue': group_data['is_overdue'],
            'products': [t['product_name'] for t in group_data['transactions']],
            'transactions': group_data['transactions']  # Für Details falls benötigt
        })
    
    result.sort(key=lambda x: x['borrow_date'], reverse=True)
    
    return jsonify(result)


@inventory_bp.route('/api/return', methods=['POST'])
@login_required
def api_return():
    """API: Rückgabe registrieren."""
    data = request.get_json()
    
    qr_code = data.get('qr_code', '').strip() if data else ''
    transaction_number = data.get('transaction_number', '').strip() if data else ''
    
    borrow_transaction = None
    
    if qr_code:
        parsed = parse_qr_code(qr_code)
        if parsed:
            qr_type, identifier = parsed
            if qr_type == 'borrow':
                borrow_transaction = BorrowTransaction.query.filter_by(
                    transaction_number=identifier,
                    status='active'
                ).first()
            elif qr_type == 'product':
                product = Product.query.get(identifier)
                if product:
                    borrow_transaction = BorrowTransaction.query.filter_by(
                        product_id=product.id,
                        status='active'
                    ).first()
    
    elif transaction_number:
        borrow_transaction = BorrowTransaction.query.filter_by(
            transaction_number=transaction_number,
            status='active'
        ).first()
    
    if not borrow_transaction:
        return jsonify({'error': translate('inventory.errors.no_active_borrow')}), 404
    
    borrow_transaction.mark_as_returned()
    db.session.commit()
    
    from app.utils.email_sender import send_return_confirmation_email
    try:
        send_return_confirmation_email(borrow_transaction)
    except Exception as e:
        current_app.logger.error(f"Fehler beim Senden der Rückgabe-Bestätigung: {e}")
    
    return jsonify({
        'message': 'Rückgabe erfolgreich registriert.',
        'transaction_id': borrow_transaction.id
    })


@inventory_bp.route('/api/borrow/<int:transaction_id>/pdf', methods=['GET'])
@login_required
def api_borrow_pdf(transaction_id):
    """API: Ausleihschein-PDF generieren."""
    borrow_transaction = BorrowTransaction.query.get_or_404(transaction_id)
    
    pdf_buffer = BytesIO()
    generate_borrow_receipt_pdf(borrow_transaction, pdf_buffer)
    pdf_buffer.seek(0)
    
    filename = f"Ausleihschein_{borrow_transaction.transaction_number}.pdf"
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
    sets = ProductSet.query.order_by(ProductSet.name).all()
    return render_template('inventory/sets.html', sets=sets)


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
    if not hasattr(product_set, 'qr_code_data') or not product_set.qr_code_data:
        qr_data = generate_set_qr_code(product_set.id)
        product_set.qr_code_data = qr_data
    return render_template('inventory/set_view.html', product_set=product_set)


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
    """Alle Produkte eines Sets ausleihen."""
    if not check_borrow_permission():
        flash(_('inventory.flash.no_borrow_permission'), 'danger')
        return redirect(url_for('inventory.sets'))
    
    product_set = ProductSet.query.get_or_404(set_id)
    
    if request.method == 'POST':
        borrower_id = request.form.get('borrower_id', type=int)
        expected_return_date = request.form.get('expected_return_date')
        
        if not borrower_id or not expected_return_date:
            flash(_('inventory.flash.fill_all_fields'), 'danger')
            users = User.query.filter_by(is_active=True).order_by(User.last_name, User.first_name).all()
            return render_template('inventory/set_borrow.html', product_set=product_set, users=users)
        
        try:
            expected_return_date = datetime.strptime(expected_return_date, '%Y-%m-%d').date()
        except ValueError:
            flash(_('inventory.flash.invalid_date'), 'danger')
            users = User.query.filter_by(is_active=True).order_by(User.last_name, User.first_name).all()
            return render_template('inventory/set_borrow.html', product_set=product_set, users=users)
        
        borrower = User.query.get_or_404(borrower_id)
        borrow_group_id = generate_borrow_group_id()
        
        borrowed_products = []
        failed_products = []
        
        for item in product_set.items:
            product = item.product
            if product.status != 'available':
                failed_products.append(product.name)
                continue
            
            transaction_number = generate_transaction_number()
            borrow_transaction = BorrowTransaction(
                transaction_number=transaction_number,
                borrow_group_id=borrow_group_id,
                product_id=product.id,
                borrower_id=borrower.id,
                borrowed_by_id=current_user.id,
                expected_return_date=expected_return_date,
                qr_code_data=generate_borrow_qr_code(transaction_number)
            )
            
            product.status = 'borrowed'
            db.session.add(borrow_transaction)
            borrowed_products.append(product.name)
        
        db.session.commit()
        
        if borrowed_products:
            flash(_('inventory.flash.set_borrow_success', name=product_set.name, count=len(borrowed_products)), 'success')
        if failed_products:
            flash(_('inventory.flash.set_borrow_partial', products=', '.join(failed_products)), 'warning')
        
        return redirect(url_for('inventory.dashboard'))
    
    # GET: Formular anzeigen
    users = User.query.filter_by(is_active=True).order_by(User.last_name, User.first_name).all()
    min_date = (date.today() + timedelta(days=1)).strftime('%Y-%m-%d')
    return render_template('inventory/set_borrow.html', product_set=product_set, users=users, min_date=min_date)


@inventory_bp.route('/api/sets', methods=['GET'])
@login_required
def api_sets():
    """API: Liste aller Produktsets."""
    sets = ProductSet.query.order_by(ProductSet.name).all()
    result = []
    for s in sets:
        result.append({
            'id': s.id,
            'name': s.name,
            'description': s.description,
            'product_count': s.product_count,
            'created_at': s.created_at.isoformat(),
            'created_by': s.created_by
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
            'product_name': item.product.name,
            'quantity': item.quantity
        })
    
    return jsonify({
        'id': product_set.id,
        'name': product_set.name,
        'description': product_set.description,
        'items': items,
        'created_at': product_set.created_at.isoformat(),
        'created_by': product_set.created_by
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
    """Erweiterte Volltextsuche über alle Produktfelder."""
    search_query = request.args.get('q', '').strip()
    
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
    ).order_by(Product.name).all()
    
    result = []
    for p in products:
        result.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'category': p.category,
            'serial_number': p.serial_number,
            'status': p.status,
            'location': p.location
        })
    
    return jsonify(result)


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
        
        # Überfällige Ausleihen
        overdue_count = BorrowTransaction.query.filter(
            BorrowTransaction.status == 'active',
            BorrowTransaction.expected_return_date < date.today()
        ).count()
        
        # Verfügbare Artikel
        available_count = Product.query.filter_by(status='available').count()
        
        # Verfügbarkeitsquote
        availability_rate = (available_count / total_products * 100) if total_products > 0 else 0
        
        # Meist ausgeliehene Produkte (Top 10)
        try:
            returned_count = BorrowTransaction.query.filter_by(status='returned').count()
            if returned_count > 0:
                top_borrowed = db.session.query(
                    Product.id,
                    Product.name,
                    func.count(BorrowTransaction.id).label('borrow_count')
                ).join(
                    BorrowTransaction, Product.id == BorrowTransaction.product_id
                ).filter(
                    BorrowTransaction.status == 'returned'
                ).group_by(
                    Product.id, Product.name
                ).order_by(
                    func.count(BorrowTransaction.id).desc()
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
                extract('year', BorrowTransaction.borrow_date).label('year'),
                extract('month', BorrowTransaction.borrow_date).label('month'),
                func.count(BorrowTransaction.id).label('count')
            ).filter(
                BorrowTransaction.borrow_date >= twelve_months_ago
            ).group_by(
                extract('year', BorrowTransaction.borrow_date),
                extract('month', BorrowTransaction.borrow_date)
            ).order_by(
                extract('year', BorrowTransaction.borrow_date),
                extract('month', BorrowTransaction.borrow_date)
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
    """Mobile API: Ausleihe erstellen."""
    user = verify_api_token()
    if not user:
        return jsonify({'error': translate('inventory.errors.invalid_or_expired_token')}), 401
    
    data = request.get_json()
    product_id = data.get('product_id', type=int)
    borrower_id = data.get('borrower_id', type=int) or user.id
    expected_return_date_str = data.get('expected_return_date')
    
    if not product_id or not expected_return_date_str:
        return jsonify({'error': translate('inventory.errors.product_id_return_date_required')}), 400
    
    try:
        expected_return_date = datetime.strptime(expected_return_date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': translate('inventory.errors.invalid_date_format_iso')}), 400
    
    product = Product.query.get_or_404(product_id)
    
    if product.status != 'available':
        return jsonify({'error': translate('inventory.errors.product_not_available')}), 400
    
    borrower = User.query.get_or_404(borrower_id)
    transaction_number = generate_transaction_number()
    
    borrow_transaction = BorrowTransaction(
        transaction_number=transaction_number,
        product_id=product_id,
        borrower_id=borrower_id,
        borrowed_by_id=user.id,
        expected_return_date=expected_return_date,
        qr_code_data=generate_borrow_qr_code(transaction_number)
    )
    
    product.status = 'borrowed'
    db.session.add(borrow_transaction)
    db.session.commit()
    
    return jsonify({
        'message': 'Ausleihe erfolgreich erstellt.',
        'transaction_id': borrow_transaction.id,
        'transaction_number': transaction_number
    })


@inventory_bp.route('/api/mobile/return', methods=['POST'])
def api_mobile_return():
    """Mobile API: Rückgabe."""
    user = verify_api_token()
    if not user:
        return jsonify({'error': translate('inventory.errors.invalid_or_expired_token')}), 401
    
    data = request.get_json()
    transaction_id = data.get('transaction_id', type=int)
    
    if not transaction_id:
        return jsonify({'error': translate('inventory.errors.transaction_id_required')}), 400
    
    borrow_transaction = BorrowTransaction.query.get_or_404(transaction_id)
    
    if borrow_transaction.status == 'returned':
        return jsonify({'error': translate('inventory.errors.already_returned')}), 400
    
    borrow_transaction.mark_as_returned()
    db.session.commit()
    
    return jsonify({
        'message': 'Rückgabe erfolgreich registriert.',
        'transaction_id': borrow_transaction.id
    })


@inventory_bp.route('/api/mobile/scan', methods=['POST'])
def api_mobile_scan():
    """Mobile API: QR-Code-Scanning."""
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
        # Ausleihtransaktion gefunden
        transaction = BorrowTransaction.query.filter_by(transaction_number=qr_id).first()
        if transaction:
            return jsonify({
                'type': 'borrow',
                'transaction': {
                    'id': transaction.id,
                    'transaction_number': transaction.transaction_number,
                    'product_name': transaction.product.name,
                    'borrower_name': transaction.borrower.full_name,
                    'status': transaction.status,
                    'expected_return_date': transaction.expected_return_date.isoformat()
                }
            })
        else:
            return jsonify({'error': translate('inventory.errors.borrow_transaction_not_found')}), 404
    
    elif qr_type == 'set':
        product_set = ProductSet.query.get(qr_id)
        if product_set:
            items_data = [{
                'product_id': item.product_id,
                'product_name': item.product.name,
                'quantity': item.quantity
            } for item in product_set.items]
            return jsonify({
                'type': 'set',
                'set': {
                    'id': product_set.id,
                    'name': product_set.name,
                    'description': product_set.description,
                    'product_count': product_set.product_count,
                    'items': items_data
                }
            })
        else:
            return jsonify({'error': translate('inventory.errors.product_set_not_found')}), 404
    
    else:
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
    if request.method == 'PUT':
        data = request.get_json() or {}
        new_name = (data.get('name') or '').strip()
        description = (data.get('description') or '').strip() or None
        color = (data.get('color') or '').strip() or None
        if not new_name:
            return jsonify({'error': translate('inventory.errors.folder_name_required')}), 400
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

