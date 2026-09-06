// Inventory shared helpers (API base, notify, confirm).
// Stock/Borrows/Scanner leben in eigenen Hot-Path-Dateien.

const INVENTORY_API_BASE = '/inventory/api';

/** Portal-Banner statt window.alert (success|info|warning|danger). */
function inventoryNotify(message, category = 'info') {
    const cat = category === 'error' ? 'danger' : (category || 'info');
    if (typeof window.showAppBanner === 'function') {
        window.showAppBanner(String(message || ''), cat);
        return;
    }
    window.alert(String(message || ''));
}

/** Portal-Confirm-Modal statt window.confirm. */
function inventoryConfirm(message, options) {
    if (typeof window.ptConfirm === 'function') {
        return window.ptConfirm(String(message || ''), options || {});
    }
    return Promise.resolve(window.confirm(String(message || '')));
}

function normalizeInventoryApiPath(path) {
    if (!path) return '';
    return path.startsWith('/') ? path : `/${path}`;
}

function resolveInventoryApiUrl(path) {
    return `${INVENTORY_API_BASE}${normalizeInventoryApiPath(path)}`;
}

async function fetchInventoryApi(path, options = {}) {
    return fetch(resolveInventoryApiUrl(path), options);
}

window.INVENTORY_API_BASE = INVENTORY_API_BASE;
window.inventoryNotify = inventoryNotify;
window.inventoryConfirm = inventoryConfirm;
window.fetchInventoryApi = fetchInventoryApi;
window.resolveInventoryApiUrl = resolveInventoryApiUrl;
