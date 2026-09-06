"""Shared Flask blueprint and constants for the inventory module."""

from flask import Blueprint, flash, jsonify, redirect, request, url_for
from flask_login import current_user

inventory_bp = Blueprint("inventory", "app.blueprints.inventory")

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xls', 'xlsx'}
DOCUMENT_FILE_TYPES = {'handbook', 'datasheet', 'invoice', 'warranty', 'dguv', 'other'}
DEFAULT_DGUV_INTERVAL_MONTHS = 12
CART_SET_META_KEY = 'borrow_cart_set_meta'
CART_QTY_META_KEY = 'borrow_cart_quantities'
RETIRED_FOLDER_NAME = 'Papierkorb'

# Öffentliche Seiten ohne Login / Modulrolle
PUBLIC_ENDPOINTS = frozenset({
    'inventory.public_product',
    'inventory.serve_public_product_image',
})

# Mobile Bearer-API: Auth + Modulcheck in verify_api_token (kein Session-Login)
MOBILE_BEARER_ENDPOINTS = frozenset({
    'inventory.api_mobile_products',
    'inventory.api_mobile_product_detail',
    'inventory.api_mobile_borrow',
    'inventory.api_mobile_return',
    'inventory.api_mobile_scan',
    'inventory.api_mobile_statistics',
})


def inventory_wants_json() -> bool:
    if request.method == 'OPTIONS':
        return True
    path = request.path or ''
    if '/api/' in path:
        return True
    if request.is_json:
        return True
    best = request.accept_mimetypes.best_match(['application/json', 'text/html'])
    return best == 'application/json'


def deny_inventory_module_access():
    """403/Redirect wenn Modulzugriff fehlt."""
    if inventory_wants_json():
        from app.utils.i18n import translate
        return jsonify({'error': translate('inventory.errors.no_permission')}), 403
    flash('Sie haben keinen Zugriff auf dieses Modul.', 'warning')
    return redirect(url_for('dashboard.index'))


@inventory_bp.before_request
def require_inventory_module_access():
    """Alle Inventar-Routen: Login + module_inventory (außer Public / Mobile-Bearer)."""
    if request.method == 'OPTIONS':
        return None

    endpoint = request.endpoint or ''
    if endpoint in PUBLIC_ENDPOINTS:
        return None

    # Bearer-Mobile ohne Session — Handler prüft Token inkl. Modul
    if endpoint in MOBILE_BEARER_ENDPOINTS and not current_user.is_authenticated:
        return None

    if not current_user.is_authenticated:
        if inventory_wants_json():
            return jsonify({'error': 'Unauthorized'}), 401
        return redirect(url_for('auth.login', next=request.url))

    from app.utils.access_control import has_module_access
    if has_module_access(current_user, 'module_inventory'):
        return None
    return deny_inventory_module_access()
