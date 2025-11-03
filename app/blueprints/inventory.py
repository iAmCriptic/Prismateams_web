from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app, session
from flask_login import login_required, current_user
from app import db
from app.models.inventory import Product, BorrowTransaction
from app.models.user import User
from app.models.settings import SystemSettings
import json
from app.utils.qr_code import (
    generate_product_qr_code, generate_borrow_qr_code, 
    parse_qr_code, generate_qr_code_bytes
)
from app.utils.pdf_generator import generate_borrow_receipt_pdf, generate_qr_code_sheet_pdf
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
from sqlalchemy import or_, and_
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


def check_borrow_permission():
    """Prüft ob der aktuelle User ausleihen darf."""
    if not current_user.is_authenticated:
        return False
    if current_user.is_admin:
        return True
    return current_user.can_borrow


def generate_transaction_number():
    """Generiert eine eindeutige Ausleihvorgangsnummer."""
    # Format: INV-YYYYMMDD-HHMMSS-XXXX
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"INV-{timestamp}-{random_part}"


# ========== Frontend Routes ==========

@inventory_bp.route('/')
@login_required
def dashboard():
    """Lager-Dashboard Hauptansicht."""
    # Meine aktuellen Ausleihen
    my_borrows = BorrowTransaction.query.filter_by(
        borrower_id=current_user.id,
        status='active'
    ).order_by(BorrowTransaction.borrow_date.desc()).all()
    
    return render_template('inventory/dashboard.html', my_borrows=my_borrows)


@inventory_bp.route('/stock')
@login_required
def stock():
    """Bestandsübersicht."""
    return render_template('inventory/stock.html')


@inventory_bp.route('/products/new', methods=['GET', 'POST'])
@login_required
def product_new():
    """Neues Produkt erstellen."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Der Produktname ist verpflichtend.', 'danger')
            return render_template('inventory/product_form.html')
        
        description = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip()
        serial_number = request.form.get('serial_number', '').strip()
        condition = request.form.get('condition', '').strip()
        location = request.form.get('location', '').strip()
        length = request.form.get('length', '').strip()
        purchase_date_str = request.form.get('purchase_date', '').strip()
        
        purchase_date = None
        if purchase_date_str:
            try:
                purchase_date = datetime.strptime(purchase_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        # Bild-Upload verarbeiten
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
                image_path = os.path.abspath(filepath)
        
        # Produkt erstellen
        product = Product(
            name=name,
            description=description or None,
            category=category or None,
            serial_number=serial_number or None,
            condition=condition or None,
            location=location or None,
            length=length or None,
            purchase_date=purchase_date,
            status='available',
            image_path=image_path,
            created_by=current_user.id
        )
        
        # QR-Code generieren
        qr_data = generate_product_qr_code(product.id)
        product.qr_code_data = qr_data
        
        db.session.add(product)
        db.session.flush()  # Um die ID zu erhalten
        
        # QR-Code nochmal mit der tatsächlichen ID generieren
        qr_data = generate_product_qr_code(product.id)
        product.qr_code_data = qr_data
        db.session.commit()
        
        flash(f'Produkt "{name}" wurde erfolgreich erstellt.', 'success')
        return redirect(url_for('inventory.stock'))
    
    # Kategorien laden
    categories = get_inventory_categories()
    
    return render_template('inventory/product_form.html', categories=categories)


@inventory_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def product_edit(product_id):
    """Produkt bearbeiten."""
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Der Produktname ist verpflichtend.', 'danger')
            return render_template('inventory/product_form.html', product=product)
        
        product.name = name
        product.description = request.form.get('description', '').strip() or None
        product.category = request.form.get('category', '').strip() or None
        product.serial_number = request.form.get('serial_number', '').strip() or None
        product.condition = request.form.get('condition', '').strip() or None
        product.location = request.form.get('location', '').strip() or None
        product.length = request.form.get('length', '').strip() or None
        
        # Status aktualisieren (nur beim Bearbeiten)
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
        
        # Neues Bild hochladen (optional)
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '' and allowed_file(file.filename):
                # Altes Bild löschen (optional)
                if product.image_path and os.path.exists(product.image_path):
                    try:
                        os.remove(product.image_path)
                    except:
                        pass
                
                filename = secure_filename(file.filename)
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                stored_filename = f"{timestamp}_{filename}"
                upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'inventory', 'product_images')
                os.makedirs(upload_dir, exist_ok=True)
                filepath = os.path.join(upload_dir, stored_filename)
                file.save(filepath)
                product.image_path = os.path.abspath(filepath)
        
        # QR-Code aktualisieren falls nötig
        if not product.qr_code_data:
            product.qr_code_data = generate_product_qr_code(product.id)
        
        db.session.commit()
        
        flash(f'Produkt "{name}" wurde erfolgreich aktualisiert.', 'success')
        return redirect(url_for('inventory.stock'))
    
    # Datum formatieren für Input-Feld
    purchase_date_formatted = product.purchase_date.strftime('%Y-%m-%d') if product.purchase_date else ''
    
    # Kategorien laden
    categories = get_inventory_categories()
    
    return render_template('inventory/product_form.html', product=product, purchase_date_formatted=purchase_date_formatted, categories=categories)


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
    product = Product.query.get_or_404(product_id)
    
    # Prüfen ob Produkt ausgeliehen ist
    active_borrow = BorrowTransaction.query.filter_by(
        product_id=product_id,
        status='active'
    ).first()
    
    if active_borrow:
        flash('Das Produkt kann nicht gelöscht werden, da es aktuell ausgeliehen ist.', 'danger')
        return redirect(url_for('inventory.stock'))
    
    # Bild löschen falls vorhanden
    if product.image_path and os.path.exists(product.image_path):
        try:
            os.remove(product.image_path)
        except:
            pass
    
    db.session.delete(product)
    db.session.commit()
    
    flash(f'Produkt "{product.name}" wurde gelöscht.', 'success')
    return redirect(url_for('inventory.stock'))


@inventory_bp.route('/products/<int:product_id>/borrow', methods=['GET', 'POST'])
@login_required
def product_borrow(product_id):
    """Ausleihvorgang starten."""
    if not check_borrow_permission():
        flash('Sie haben keine Berechtigung, Artikel auszuleihen.', 'danger')
        return redirect(url_for('inventory.stock'))
    
    product = Product.query.get_or_404(product_id)
    
    if product.status != 'available':
        flash('Das Produkt ist nicht verfügbar.', 'danger')
        return redirect(url_for('inventory.stock'))
    
    if request.method == 'POST':
        expected_return_date_str = request.form.get('expected_return_date', '').strip()
        borrower_id = request.form.get('borrower_id', '').strip()
        
        if not expected_return_date_str:
            flash('Das erwartete Rückgabedatum ist verpflichtend.', 'danger')
            return render_template('inventory/borrow.html', product=product)
        
        try:
            expected_return_date = datetime.strptime(expected_return_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Ungültiges Datumsformat.', 'danger')
            return render_template('inventory/borrow.html', product=product)
        
        # Prüfen ob Datum in der Zukunft liegt
        if expected_return_date < date.today():
            flash('Das Rückgabedatum darf nicht in der Vergangenheit liegen.', 'danger')
            return render_template('inventory/borrow.html', product=product)
        
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
        
        # Transaktionsnummer generieren
        transaction_number = generate_transaction_number()
        
        # Ausleihvorgang erstellen
        borrow_transaction = BorrowTransaction(
            transaction_number=transaction_number,
            product_id=product.id,
            borrower_id=borrower.id,
            borrowed_by_id=current_user.id,
            borrow_date=datetime.utcnow(),
            expected_return_date=expected_return_date,
            status='active'
        )
        
        # QR-Code für Ausleihvorgang generieren
        qr_data = generate_borrow_qr_code(transaction_number)
        borrow_transaction.qr_code_data = qr_data
        
        # Produktstatus ändern
        product.status = 'borrowed'
        product.qr_code_data = qr_data  # Temporär für Ausleihe
        
        db.session.add(borrow_transaction)
        db.session.commit()
        
        flash(f'Ausleihe erfolgreich registriert. Vorgangsnummer: {transaction_number}', 'success')
        
        # PDF generieren und zurückgeben
        pdf_buffer = BytesIO()
        generate_borrow_receipt_pdf(borrow_transaction, pdf_buffer)
        pdf_buffer.seek(0)
        
        filename = f"Ausleihschein_{transaction_number}.pdf"
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    
    # Alle Benutzer für Auswahl
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
    # Query-Parameter für vorausgefüllte Transaktionsnummer
    preset_transaction_number = request.args.get('transaction_number', '')
    
    if request.method == 'POST':
        qr_code = request.form.get('qr_code', '').strip()
        transaction_number = request.form.get('transaction_number', '').strip()
        
        borrow_transaction = None
        
        # QR-Code parsen
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
                    # Suche aktive Ausleihe für dieses Produkt
                    product = Product.query.get(identifier)
                    if product:
                        borrow_transaction = BorrowTransaction.query.filter_by(
                            product_id=product.id,
                            status='active'
                        ).first()
        
        # Oder direkt nach Transaktionsnummer suchen
        elif transaction_number:
            borrow_transaction = BorrowTransaction.query.filter_by(
                transaction_number=transaction_number,
                status='active'
            ).first()
        
        if not borrow_transaction:
            flash('Keine aktive Ausleihe gefunden. Bitte überprüfen Sie die Eingabe.', 'danger')
            return render_template('inventory/return.html', preset_transaction_number=preset_transaction_number)
        
        # Rückgabe durchführen
        borrow_transaction.mark_as_returned()
        db.session.commit()
        
        # E-Mail-Bestätigung senden
        from app.utils.email_sender import send_return_confirmation_email
        try:
            send_return_confirmation_email(borrow_transaction)
        except Exception as e:
            current_app.logger.error(f"Fehler beim Senden der Rückgabe-Bestätigung: {e}")
        
        flash(f'Rückgabe erfolgreich registriert. Eine Bestätigungs-E-Mail wurde gesendet.', 'success')
        return redirect(url_for('inventory.dashboard'))
    
    return render_template('inventory/return.html', preset_transaction_number=preset_transaction_number)


@inventory_bp.route('/borrow-scanner', methods=['GET', 'POST'])
@login_required
def borrow_scanner():
    """Ausleihen geben - Scanner-Seite mit Warenkorb."""
    if not check_borrow_permission():
        flash('Sie haben keine Berechtigung, Artikel auszuleihen.', 'danger')
        return redirect(url_for('inventory.dashboard'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_to_cart':
            # QR-Code oder Produkt-ID hinzufügen
            qr_code = request.form.get('qr_code', '').strip()
            product_id = request.form.get('product_id')
            
            product = None
            if qr_code:
                parsed = parse_qr_code(qr_code)
                if parsed and parsed[0] == 'product':
                    product = Product.query.get(parsed[1])
            elif product_id:
                product = Product.query.get(int(product_id))
            
            if not product:
                return jsonify({'error': 'Produkt nicht gefunden.'}), 404
            
            if product.status != 'available':
                return jsonify({'error': 'Produkt ist nicht verfügbar.'}), 400
            
            # Session-Warenkorb verwenden
            cart = session.get('borrow_cart', [])
            if product.id not in cart:
                cart.append(product.id)
                session['borrow_cart'] = cart
            
            return jsonify({
                'success': True,
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
            return jsonify({'success': True, 'cart_count': len(cart)})
        
        elif action == 'clear_cart':
            session.pop('borrow_cart', None)
            return jsonify({'success': True})
    
    # Warenkorb laden
    cart_product_ids = session.get('borrow_cart', [])
    cart_products = Product.query.filter(Product.id.in_(cart_product_ids)).all() if cart_product_ids else []
    
    # Alle Benutzer für Auswahl
    users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all()
    
    return render_template('inventory/borrow_scanner.html', cart_products=cart_products, users=users)


@inventory_bp.route('/borrow-scanner/checkout', methods=['POST'])
@login_required
def borrow_scanner_checkout():
    """Warenkorb checkout - alle Produkte ausleihen."""
    if not check_borrow_permission():
        flash('Sie haben keine Berechtigung, Artikel auszuleihen.', 'danger')
        return redirect(url_for('inventory.borrow_scanner'))
    
    cart_product_ids = session.get('borrow_cart', [])
    if not cart_product_ids:
        flash('Keine Produkte zum Ausleihen ausgewählt.', 'danger')
        return redirect(url_for('inventory.borrow_scanner'))
    
    expected_return_date_str = request.form.get('expected_return_date', '').strip()
    borrower_id = request.form.get('borrower_id', '').strip()
    
    if not expected_return_date_str:
        flash('Das erwartete Rückgabedatum ist verpflichtend.', 'danger')
        return redirect(url_for('inventory.borrow_scanner'))
    
    try:
        expected_return_date = datetime.strptime(expected_return_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Ungültiges Datumsformat.', 'danger')
        return redirect(url_for('inventory.borrow_scanner'))
    
    if expected_return_date < date.today():
        flash('Das Rückgabedatum darf nicht in der Vergangenheit liegen.', 'danger')
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
    
    for product in products:
        if product.status != 'available':
            continue
        
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
        transactions.append(borrow_transaction)
    
    db.session.commit()
    
    # Warenkorb leeren
    session.pop('borrow_cart', None)
    
    flash(f'{len(transactions)} Produkt(e) erfolgreich ausgeliehen.', 'success')
    
    # PDF generieren mit allen Transaktionen
    # Hier könnten wir ein kombiniertes PDF erstellen, aber für jetzt nur die erste
    if transactions:
        pdf_buffer = BytesIO()
        generate_borrow_receipt_pdf(transactions[0], pdf_buffer)
        pdf_buffer.seek(0)
        
        filename = f"Ausleihscheine_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    
    return redirect(url_for('inventory.borrow_scanner'))


@inventory_bp.route('/inventory-list')
@login_required
def inventory_list():
    """Inventurliste - Übersicht aller Produkte für Inventur."""
    products = Product.query.order_by(Product.name).all()
    return render_template('inventory/inventory_list.html', products=products)


@inventory_bp.route('/inventory-list/pdf')
@login_required
def inventory_list_pdf():
    """PDF-Generierung für Inventurliste."""
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


@inventory_bp.route('/print-qr', methods=['GET', 'POST'])
@login_required
def print_qr():
    """QR-Code-Druck."""
    if request.method == 'POST':
        product_ids = request.form.getlist('product_ids')
        
        if not product_ids:
            flash('Bitte wählen Sie mindestens ein Produkt aus.', 'danger')
            return redirect(url_for('inventory.print_qr'))
        
        try:
            product_ids = [int(pid) for pid in product_ids]
            products = Product.query.filter(Product.id.in_(product_ids)).all()
            
            if not products:
                flash('Keine gültigen Produkte gefunden.', 'danger')
                return redirect(url_for('inventory.print_qr'))
            
            # PDF generieren
            pdf_buffer = BytesIO()
            generate_qr_code_sheet_pdf(products, pdf_buffer)
            pdf_buffer.seek(0)
            
            filename = f"QR-Codes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=filename
            )
        except Exception as e:
            current_app.logger.error(f"Fehler beim Generieren des QR-Code-Druckbogens: {e}")
            flash('Fehler beim Generieren des Druckbogens.', 'danger')
            return redirect(url_for('inventory.print_qr'))
    
    # Alle Produkte für Auswahl
    products = Product.query.order_by(Product.name).all()
    return render_template('inventory/print_qr.html', products=products)


# ========== API Endpoints ==========

@inventory_bp.route('/api/products', methods=['GET'])
@login_required
def api_products():
    """API: Liste aller Produkte mit Such- und Filteroptionen."""
    search = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    status = request.args.get('status', '').strip()
    
    query = Product.query
    
    # Suchfilter
    if search:
        query = query.filter(
            or_(
                Product.name.ilike(f'%{search}%'),
                Product.serial_number.ilike(f'%{search}%'),
                Product.description.ilike(f'%{search}%')
            )
        )
    
    # Kategorie-Filter
    if category:
        query = query.filter_by(category=category)
    
    # Status-Filter
    if status:
        query = query.filter_by(status=status)
    
    products = query.order_by(Product.name).all()
    
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'description': p.description,
        'category': p.category,
        'serial_number': p.serial_number,
        'condition': p.condition,
        'location': p.location,
        'purchase_date': p.purchase_date.isoformat() if p.purchase_date else None,
        'status': p.status,
        'image_path': p.image_path,
        'qr_code_data': p.qr_code_data,
        'created_at': p.created_at.isoformat(),
        'created_by': p.created_by
    } for p in products])


@inventory_bp.route('/api/products/<int:product_id>', methods=['GET'])
@login_required
def api_product_get(product_id):
    """API: Einzelnes Produkt abrufen."""
    product = Product.query.get_or_404(product_id)
    
    return jsonify({
        'id': product.id,
        'name': product.name,
        'description': product.description,
        'category': product.category,
        'serial_number': product.serial_number,
        'condition': product.condition,
        'location': product.location,
        'purchase_date': product.purchase_date.isoformat() if product.purchase_date else None,
        'status': product.status,
        'image_path': product.image_path,
        'qr_code_data': product.qr_code_data,
        'created_at': product.created_at.isoformat(),
        'created_by': product.created_by
    })


@inventory_bp.route('/api/products', methods=['POST'])
@login_required
def api_product_create():
    """API: Neues Produkt erstellen."""
    data = request.get_json()
    
    if not data or not data.get('name'):
        return jsonify({'error': 'Der Produktname ist verpflichtend.'}), 400
    
    product = Product(
        name=data['name'],
        description=data.get('description'),
        category=data.get('category'),
        serial_number=data.get('serial_number'),
        condition=data.get('condition'),
        location=data.get('location'),
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
    product = Product.query.get_or_404(product_id)
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Keine Daten übermittelt.'}), 400
    
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
    product = Product.query.get_or_404(product_id)
    
    active_borrow = BorrowTransaction.query.filter_by(
        product_id=product_id,
        status='active'
    ).first()
    
    if active_borrow:
        return jsonify({'error': 'Produkt kann nicht gelöscht werden, da es ausgeliehen ist.'}), 400
    
    db.session.delete(product)
    db.session.commit()
    
    return jsonify({'message': 'Produkt gelöscht.'})


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
    
    products = query.order_by(Product.name).all()
    
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'category': p.category,
        'serial_number': p.serial_number,
        'status': p.status,
        'location': p.location,
        'image_path': p.image_path,
        'qr_code_data': p.qr_code_data
    } for p in products])


@inventory_bp.route('/api/borrow', methods=['POST'])
@login_required
def api_borrow():
    """API: Ausleihvorgang registrieren."""
    if not check_borrow_permission():
        return jsonify({'error': 'Sie haben keine Berechtigung, Artikel auszuleihen.'}), 403
    
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Keine Daten übermittelt.'}), 400
    
    product_id = data.get('product_id')
    borrower_id = data.get('borrower_id', current_user.id)
    expected_return_date_str = data.get('expected_return_date')
    
    if not product_id or not expected_return_date_str:
        return jsonify({'error': 'Produkt-ID und erwartetes Rückgabedatum sind erforderlich.'}), 400
    
    product = Product.query.get(product_id)
    if not product:
        return jsonify({'error': 'Produkt nicht gefunden.'}), 404
    
    if product.status != 'available':
        return jsonify({'error': 'Produkt ist nicht verfügbar.'}), 400
    
    try:
        expected_return_date = datetime.strptime(expected_return_date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Ungültiges Datumsformat.'}), 400
    
    borrower = User.query.get(borrower_id)
    if not borrower:
        return jsonify({'error': 'Benutzer nicht gefunden.'}), 404
    
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
        'product_id': b.product_id,
        'product_name': b.product.name,
        'borrow_date': b.borrow_date.isoformat(),
        'expected_return_date': b.expected_return_date.isoformat(),
        'is_overdue': b.is_overdue,
        'qr_code_data': b.qr_code_data
    } for b in borrows])


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
        return jsonify({'error': 'Keine aktive Ausleihe gefunden.'}), 404
    
    borrow_transaction.mark_as_returned()
    db.session.commit()
    
    # E-Mail-Bestätigung senden
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
        return jsonify({'error': 'Keine Produkt-IDs übermittelt.'}), 400
    
    try:
        product_ids = [int(pid) for pid in data['product_ids']]
        products = Product.query.filter(Product.id.in_(product_ids)).all()
        
        if not products:
            return jsonify({'error': 'Keine gültigen Produkte gefunden.'}), 404
        
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
        return jsonify({'error': 'Fehler beim Generieren des Druckbogens.'}), 500

