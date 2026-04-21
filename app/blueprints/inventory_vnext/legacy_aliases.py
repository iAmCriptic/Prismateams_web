"""
V-Next Alias-Routen.

Diese Routen mappen bestehende Inventar-API-Handler auf den neuen
/inventory/vnext/api/-Pfad, damit Frontends konsistent V-Next nutzen koennen.
"""

from flask import Blueprint, request
from flask_login import login_required

from app.blueprints import inventory as legacy_inventory

legacy_aliases_bp = Blueprint("inventory_vnext_legacy_aliases", __name__)


@legacy_aliases_bp.route("/folders", methods=["GET", "POST"])
@login_required
def folders_alias():
    return legacy_inventory.api_folders()


@legacy_aliases_bp.route("/categories", methods=["GET", "POST"])
@login_required
def categories_alias():
    return legacy_inventory.api_categories()


@legacy_aliases_bp.route("/categories/<path:category_name>", methods=["PUT", "DELETE"])
@login_required
def category_update_delete_alias(category_name):
    return legacy_inventory.api_category_update_delete(category_name)


@legacy_aliases_bp.route("/inventory/filter-options", methods=["GET"])
@login_required
def inventory_filter_options_alias():
    return legacy_inventory.api_filter_options()


@legacy_aliases_bp.route("/products", methods=["GET", "POST"])
@login_required
def products_alias():
    if request.method == "GET":
        return legacy_inventory.api_products()
    return legacy_inventory.api_product_create()


@legacy_aliases_bp.route("/products/<int:product_id>", methods=["GET", "PUT", "DELETE"])
@login_required
def product_detail_alias(product_id):
    method = request.method
    if method == "GET":
        return legacy_inventory.api_product_get(product_id)
    if method == "PUT":
        return legacy_inventory.api_product_update(product_id)
    return legacy_inventory.api_product_delete(product_id)


@legacy_aliases_bp.route("/products/bulk-update", methods=["POST"])
@login_required
def products_bulk_update_alias():
    return legacy_inventory.api_products_bulk_update()


@legacy_aliases_bp.route("/products/bulk-delete", methods=["POST"])
@login_required
def products_bulk_delete_alias():
    return legacy_inventory.api_products_bulk_delete()


@legacy_aliases_bp.route("/borrows", methods=["GET"])
@login_required
def borrows_alias():
    return legacy_inventory.api_borrows()


@legacy_aliases_bp.route("/borrows/my", methods=["GET"])
@login_required
def borrows_my_alias():
    return legacy_inventory.api_borrows_my()


@legacy_aliases_bp.route("/borrow/<int:transaction_id>/pdf", methods=["GET"])
@login_required
def borrow_pdf_alias(transaction_id):
    return legacy_inventory.api_borrow_pdf(transaction_id)


@legacy_aliases_bp.route("/favorites", methods=["GET"])
@login_required
def favorites_alias():
    return legacy_inventory.api_favorites()


@legacy_aliases_bp.route("/favorites/<int:product_id>", methods=["POST", "DELETE"])
@login_required
def favorite_toggle_alias(product_id):
    return legacy_inventory.api_favorite_toggle(product_id)


@legacy_aliases_bp.route("/statistics", methods=["GET"])
@login_required
def statistics_alias():
    return legacy_inventory.api_statistics()


@legacy_aliases_bp.route("/inventory/<int:inventory_id>/scan", methods=["POST"])
@login_required
def inventory_scan_alias(inventory_id):
    return legacy_inventory.api_inventory_scan(inventory_id)
