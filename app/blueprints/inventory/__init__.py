"""Inventory module package. Public API matches the former inventory.py."""

from app.blueprints.inventory._bp import inventory_bp
from app.blueprints.inventory.helpers import (  # noqa: F401
    check_borrow_permission,
    generate_borrow_group_id,
    generate_transaction_number,
    get_inventory_categories,
    get_product_folders,
    save_inventory_categories,
)

# Register routes on inventory_bp
from app.blueprints.inventory import views as _views  # noqa: F401
from app.blueprints.inventory import borrow as _borrow  # noqa: F401
from app.blueprints.inventory import sessions as _sessions  # noqa: F401
from app.blueprints.inventory import api_products as _api_products  # noqa: F401
from app.blueprints.inventory import sets as _sets  # noqa: F401
from app.blueprints.inventory import extra as _extra  # noqa: F401
from app.blueprints.inventory import mobile as _mobile  # noqa: F401

# inventory_vnext aliases: from app.blueprints import inventory as legacy_inventory
from app.blueprints.inventory.api_products import (
    api_borrow_pdf,
    api_borrows,
    api_borrows_my,
    api_filter_options,
    api_folders,
    api_product_create,
    api_product_delete,
    api_product_get,
    api_product_update,
    api_products,
    api_products_bulk_delete,
    api_products_bulk_update,
)
from app.blueprints.inventory.extra import api_favorite_toggle, api_favorites, api_statistics
from app.blueprints.inventory.mobile import (
    api_categories,
    api_category_update_delete,
    api_folder_update_delete,
)
from app.blueprints.inventory.sessions import api_inventory_scan

__all__ = [
    "api_borrow_pdf",
    "api_borrows",
    "api_borrows_my",
    "api_categories",
    "api_category_update_delete",
    "api_favorite_toggle",
    "api_favorites",
    "api_filter_options",
    "api_folder_update_delete",
    "api_folders",
    "api_inventory_scan",
    "api_product_create",
    "api_product_delete",
    "api_product_get",
    "api_product_update",
    "api_products",
    "api_products_bulk_delete",
    "api_products_bulk_update",
    "api_statistics",
    "check_borrow_permission",
    "generate_borrow_group_id",
    "generate_transaction_number",
    "get_inventory_categories",
    "get_product_folders",
    "inventory_bp",
    "save_inventory_categories",
]
