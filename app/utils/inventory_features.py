"""Optional inventory sub-features (admin toggles in inventory settings)."""

from __future__ import annotations

from app.utils.system_settings_cache import setting_bool


FEATURE_KEYS = (
    'inventory_borrow_enabled',
    'inventory_quick_scan_enabled',
    'inventory_dguv_enabled',
    'inventory_owners_enabled',
    'inventory_accounting_enabled',
    'inventory_stocktake_enabled',
)


def is_inventory_borrow_enabled() -> bool:
    return setting_bool('inventory_borrow_enabled', True)


def is_inventory_quick_scan_enabled() -> bool:
    return setting_bool('inventory_quick_scan_enabled', True)


def is_inventory_dguv_enabled() -> bool:
    return setting_bool('inventory_dguv_enabled', True)


def is_inventory_owners_enabled() -> bool:
    return setting_bool('inventory_owners_enabled', True)


def is_inventory_accounting_enabled() -> bool:
    return setting_bool('inventory_accounting_enabled', True)


def is_inventory_stocktake_enabled() -> bool:
    return setting_bool('inventory_stocktake_enabled', True)


def inventory_feature_flags() -> dict[str, bool]:
    return {
        'borrow': is_inventory_borrow_enabled(),
        'quick_scan': is_inventory_quick_scan_enabled(),
        'dguv': is_inventory_dguv_enabled(),
        'owners': is_inventory_owners_enabled(),
        'accounting': is_inventory_accounting_enabled(),
        'stocktake': is_inventory_stocktake_enabled(),
    }


# endpoint -> setting key that must be enabled
FEATURE_ENDPOINT_GATES = {
    'inventory.product_borrow': 'inventory_borrow_enabled',
    'inventory.borrow_multiple': 'inventory_borrow_enabled',
    'inventory.borrows': 'inventory_borrow_enabled',
    'inventory.return': 'inventory_borrow_enabled',
    'inventory.return_complete': 'inventory_borrow_enabled',
    'inventory.inventory_checkout': 'inventory_borrow_enabled',
    'inventory.inventory_checkout_confirm': 'inventory_borrow_enabled',
    'inventory.api_borrow': 'inventory_borrow_enabled',
    'inventory.borrow_scanner': 'inventory_quick_scan_enabled',
    'inventory.borrow_scanner_checkout': 'inventory_quick_scan_enabled',
    'inventory.inventory_tool': 'inventory_stocktake_enabled',
    'inventory.inventory_session': 'inventory_stocktake_enabled',
    'inventory.inventory_history': 'inventory_stocktake_enabled',
    'inventory.inventory_list': 'inventory_stocktake_enabled',
    'inventory.inventory_list_pdf': 'inventory_stocktake_enabled',
    'inventory.inventory_complete': 'inventory_stocktake_enabled',
    'inventory.inventory_tool_pdf': 'inventory_stocktake_enabled',
}


def feature_enabled_for_endpoint(endpoint: str | None) -> bool:
    if not endpoint:
        return True
    key = FEATURE_ENDPOINT_GATES.get(endpoint)
    if not key:
        return True
    return setting_bool(key, True)
