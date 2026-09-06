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

@inventory_bp.route('/products/<int:product_id>/documents')
@login_required
@check_module_access('module_inventory')
def product_documents(product_id):
    """Dokumente eines Produkts anzeigen."""
    product = Product.query.get_or_404(product_id)
    documents = (
        ProductDocument.query
        .options(joinedload(ProductDocument.manual))
        .filter_by(product_id=product_id)
        .order_by(ProductDocument.created_at.desc())
        .all()
    )
    manuals = _accessible_manuals()
    return render_template(
        'inventory/product_documents.html',
        product=product,
        documents=documents,
        manuals=manuals,
    )


@inventory_bp.route('/products/<int:product_id>/documents/upload', methods=['POST'])
@login_required
@check_module_access('module_inventory')
def product_document_upload(product_id):
    """Dokument fuer ein Produkt hochladen (optional mit Manual-Verknuepfung)."""
    wants_json = (
        request.accept_mimetypes.best == 'application/json'
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.args.get('format') == 'json'
    )

    def _json_or_redirect(message, category, *, status=200, extra=None):
        if wants_json:
            payload = {'ok': category in ('success', 'info'), 'message': message, 'category': category}
            if extra:
                payload.update(extra)
            return jsonify(payload), status
        flash(message, category)
        return redirect(url_for('inventory.product_documents', product_id=product_id))

    Product.query.get_or_404(product_id)

    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return _json_or_redirect(
            translate('inventory.flash.guests_cannot_edit'), 'danger', status=403
        )

    if 'file' not in request.files:
        return _json_or_redirect(_('inventory.flash.no_file_selected'), 'danger', status=400)

    file = request.files['file']
    file_type = _normalize_document_file_type(request.form.get('file_type', 'other'))
    manual_id = request.form.get('manual_id', type=int) or None

    if not file or file.filename == '':
        return _json_or_redirect(_('inventory.flash.no_file_selected'), 'danger', status=400)

    if not allowed_document_file(file.filename):
        return _json_or_redirect(_('inventory.flash.document_invalid_type'), 'danger', status=400)

    manual = _get_accessible_manual(manual_id) if manual_id else None
    if manual_id and not manual:
        return _json_or_redirect(_('inventory.flash.manual_not_accessible'), 'danger', status=400)

    abs_path, orig_name, size = _save_document_upload(file)
    doc = _create_product_document(
        product_id=product_id,
        file_type=file_type,
        uploaded_by=current_user.id,
        file_path=abs_path,
        file_name=orig_name,
        file_size=size,
        manual_id=manual.id if manual else None,
    )
    db.session.commit()

    return _json_or_redirect(
        _('inventory.flash.document_uploaded', filename=orig_name),
        'success',
        extra={
            'document': {
                'id': doc.id,
                'file_name': doc.file_name,
                'display_name': doc.display_name,
                'file_type': doc.file_type,
                'file_size': doc.file_size,
                'manual_id': doc.manual_id,
                'has_file': bool(doc.file_path),
                'download_url': url_for(
                    'inventory.product_document_download',
                    product_id=product_id,
                    document_id=doc.id,
                ),
                'created_at': doc.created_at.isoformat() if doc.created_at else None,
            },
        },
    )


@inventory_bp.route('/products/<int:product_id>/documents/link-manual', methods=['POST'])
@login_required
@check_module_access('module_inventory')
def product_document_link_manual(product_id):
    """Reine Verknuepfung einer Bedienungsanleitung ohne Datei-Upload."""
    wants_json = (
        request.accept_mimetypes.best == 'application/json'
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.args.get('format') == 'json'
    )

    def _json_or_redirect(message, category, *, status=200, extra=None):
        if wants_json:
            payload = {'ok': category in ('success', 'info'), 'message': message, 'category': category}
            if extra:
                payload.update(extra)
            return jsonify(payload), status
        flash(message, category)
        return redirect(url_for('inventory.product_documents', product_id=product_id))

    Product.query.get_or_404(product_id)

    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        return _json_or_redirect(
            translate('inventory.flash.guests_cannot_edit'), 'danger', status=403
        )

    manual_id = request.form.get('manual_id', type=int)
    if manual_id is None and request.is_json:
        manual_id = (request.get_json(silent=True) or {}).get('manual_id')
        try:
            manual_id = int(manual_id) if manual_id is not None else None
        except (TypeError, ValueError):
            manual_id = None
    file_type = _normalize_document_file_type(
        request.form.get('file_type')
        or ((request.get_json(silent=True) or {}).get('file_type') if request.is_json else None)
        or 'handbook'
    )
    manual = _get_accessible_manual(manual_id)
    if not manual:
        return _json_or_redirect(_('inventory.flash.manual_link_required'), 'danger', status=400)

    existing = ProductDocument.query.filter_by(
        product_id=product_id, manual_id=manual.id, file_path=None
    ).first()
    if existing:
        return _json_or_redirect(
            _('inventory.flash.manual_already_linked', title=manual.title), 'info'
        )

    _create_product_document(
        product_id=product_id,
        file_type=file_type,
        uploaded_by=current_user.id,
        manual_id=manual.id,
    )
    db.session.commit()
    return _json_or_redirect(
        _('inventory.flash.manual_linked', title=manual.title),
        'success',
        extra={'manual_id': manual.id, 'manual_title': manual.title},
    )


@inventory_bp.route('/products/<int:product_id>/documents/<int:document_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_inventory')
def product_document_delete(product_id, document_id):
    """Dokument loeschen (Datei und/oder Verknuepfung; Manual selbst bleibt)."""
    document = ProductDocument.query.get_or_404(document_id)

    if document.product_id != product_id:
        flash(translate('inventory.flash.invalid_request'), 'danger')
        return redirect(url_for('inventory.product_documents', product_id=product_id))

    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash(translate('inventory.flash.guests_cannot_edit'), 'danger')
        return redirect(url_for('inventory.product_documents', product_id=product_id))

    if document.file_path and os.path.exists(document.file_path):
        try:
            os.remove(document.file_path)
        except Exception as e:
            current_app.logger.error(f"Fehler beim Loeschen der Datei: {e}")

    label = document.display_name
    db.session.delete(document)
    db.session.commit()

    flash(_('inventory.flash.document_deleted', filename=label), 'success')
    return redirect(url_for('inventory.product_documents', product_id=product_id))


@inventory_bp.route('/products/<int:product_id>/documents/<int:document_id>/download')
@login_required
@check_module_access('module_inventory')
def product_document_download(product_id, document_id):
    """Dokument herunterladen (nur wenn lokale Datei vorhanden)."""
    document = ProductDocument.query.get_or_404(document_id)

    if document.product_id != product_id:
        flash(translate('inventory.flash.invalid_request'), 'danger')
        return redirect(url_for('inventory.product_documents', product_id=product_id))

    if not document.file_path or not os.path.exists(document.file_path):
        if document.manual_id:
            return redirect(url_for('manuals.view', manual_id=document.manual_id))
        flash(_('inventory.flash.file_not_found'), 'danger')
        return redirect(url_for('inventory.product_documents', product_id=product_id))

    return send_file(
        document.file_path,
        as_attachment=True,
        download_name=document.file_name or os.path.basename(document.file_path),
    )


@inventory_bp.route('/api/products/<int:product_id>/documents', methods=['GET'])
@login_required
@check_module_access('module_inventory')
def api_product_documents(product_id):
    """API: Liste aller Dokumente eines Produkts."""
    Product.query.get_or_404(product_id)
    documents = (
        ProductDocument.query
        .options(joinedload(ProductDocument.manual))
        .filter_by(product_id=product_id)
        .order_by(ProductDocument.created_at.desc())
        .all()
    )

    result = []
    for doc in documents:
        manual_title = doc.manual.title if doc.manual else None
        result.append({
            'id': doc.id,
            'file_name': doc.file_name,
            'display_name': doc.display_name,
            'file_type': doc.file_type,
            'file_size': doc.file_size,
            'manual_id': doc.manual_id,
            'manual_title': manual_title,
            'manual_view_url': url_for('manuals.view', manual_id=doc.manual_id) if doc.manual_id else None,
            'has_file': bool(doc.file_path),
            'download_url': (
                url_for('inventory.product_document_download', product_id=product_id, document_id=doc.id)
                if doc.file_path else None
            ),
            'created_at': doc.created_at.isoformat(),
            'uploaded_by': doc.uploaded_by,
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
