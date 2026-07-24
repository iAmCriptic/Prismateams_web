// Inventurtool JavaScript

class InventoryToolManager {
    constructor(inventoryId, options = {}) {
        this.inventoryId = inventoryId;
        this.readOnly = !!options.readOnly;
        this.items = new Map();
        this.pollingInterval = null;
        this.lastUpdateTime = null;
        this.currentEditingProductId = null;
        this.lockRefreshTimer = null;
        this.statusFilter = 'open';
        this.viewMode = 'list';
    }

    init() {
        this.setupEventListeners();
        this.setupViewToggle();
        this.setupFilterChips();
        this.loadItems();
        if (!this.readOnly) {
            this.startPolling();
        }
    }

    setupEventListeners() {
        const searchInput = document.getElementById('searchInput');
        if (searchInput) {
            searchInput.addEventListener('input', () => this.renderItems());
        }

        const saveBtn = document.getElementById('saveProductBtn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.saveProduct());
        }

        const productModal = document.getElementById('productEditModal');
        if (productModal) {
            this.ensureModalOnBody(productModal);
            productModal.addEventListener('hidden.bs.modal', () => {
                this.clearModalArtifacts();
                this.resumeScannerIfActive();
                if (this.currentEditingProductId) {
                    this.releaseLock(this.currentEditingProductId);
                    this.currentEditingProductId = null;
                }
                if (this.lockRefreshTimer) {
                    clearInterval(this.lockRefreshTimer);
                    this.lockRefreshTimer = null;
                }
            });
        }

        const completeModal = document.getElementById('completeInventoryModal');
        if (completeModal) {
            this.ensureModalOnBody(completeModal);
            completeModal.addEventListener('hidden.bs.modal', () => {
                this.clearModalArtifacts();
            });
        }
    }

    ensureModalOnBody(modalElement) {
        if (!modalElement) return;
        if (modalElement.parentElement !== document.body) {
            document.body.appendChild(modalElement);
        }
    }

    clearModalArtifacts() {
        document.querySelectorAll('.modal-backdrop').forEach((el) => el.remove());
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('overflow');
        document.body.style.removeProperty('padding-right');
    }

    setupViewToggle() {
        const listBtn = document.getElementById('sessionListViewBtn');
        const gridBtn = document.getElementById('sessionGridViewBtn');
        const storageKey = 'inventurSessionViewMode';
        let saved = 'list';
        try { saved = localStorage.getItem(storageKey) || 'list'; } catch (e) {}
        this.applyViewMode(saved);

        if (listBtn) listBtn.addEventListener('click', () => this.applyViewMode('list'));
        if (gridBtn) gridBtn.addEventListener('click', () => this.applyViewMode('grid'));
    }

    applyViewMode(mode) {
        this.viewMode = mode === 'grid' ? 'grid' : 'list';
        const listView = document.getElementById('sessionListView');
        const gridView = document.getElementById('sessionGridView');
        const listBtn = document.getElementById('sessionListViewBtn');
        const gridBtn = document.getElementById('sessionGridViewBtn');
        const isGrid = this.viewMode === 'grid';
        if (listView) listView.style.display = isGrid ? 'none' : '';
        if (gridView) gridView.style.display = isGrid ? '' : 'none';
        if (listBtn) listBtn.classList.toggle('active', !isGrid);
        if (gridBtn) gridBtn.classList.toggle('active', isGrid);
        try { localStorage.setItem('inventurSessionViewMode', this.viewMode); } catch (e) {}
        this.renderItems();
    }

    setupFilterChips() {
        document.querySelectorAll('#inventurFilterChips [data-filter]').forEach((btn) => {
            btn.addEventListener('click', () => {
                this.statusFilter = btn.dataset.filter || 'all';
                document.querySelectorAll('#inventurFilterChips [data-filter]').forEach((el) => {
                    el.classList.toggle('active', el === btn);
                });
                this.renderItems();
            });
        });
    }

    async loadItems() {
        try {
            const response = await fetch(`/inventory/vnext/api/inventory/${this.inventoryId}/items`);
            if (!response.ok) throw new Error('Fehler beim Laden der Inventur-Items');

            const data = await response.json();
            this.items.clear();
            data.items.forEach((item) => {
                this.items.set(item.product_id, item);
            });

            this.renderItems();
            this.updateProgress(data.inventory);
            this.updateStats();
            this.lastUpdateTime = new Date();
        } catch (error) {
            console.error('Fehler beim Laden der Items:', error);
        }
    }

    getFilteredItems() {
        const searchTerm = document.getElementById('searchInput')?.value.toLowerCase() || '';
        let items = Array.from(this.items.values());

        items = items.filter((item) => {
            if (this.statusFilter === 'open' && item.checked) return false;
            if (this.statusFilter === 'checked' && !item.checked) return false;
            if (this.statusFilter === 'changed') {
                const hasChanges = item.location_changed || item.condition_changed || !!item.notes;
                if (!hasChanges) return false;
            }
            if (searchTerm) {
                const searchable = `${item.product_name || ''} ${item.product_category || ''} ${item.product_location || ''} ${item.notes || ''}`.toLowerCase();
                if (!searchable.includes(searchTerm)) return false;
            }
            return true;
        });

        items.sort((a, b) => {
            if (this.statusFilter === 'all' || this.statusFilter === 'open') {
                if (!!a.checked !== !!b.checked) return a.checked ? 1 : -1;
            }
            return String(a.product_name || '').localeCompare(String(b.product_name || ''), 'de');
        });

        return items;
    }

    statusBadgeHtml(item) {
        const statusLabels = {
            available: 'Verfügbar',
            borrowed: 'Ausgeliehen',
            missing: 'Fehlend',
            defective: 'Defekt',
            in_repair: 'In Reparatur',
            retired: 'Ausgemustert',
        };
        const status = item.product_status || '';
        if (status === 'available') return '<span class="badge bg-success">Verfügbar</span>';
        if (status === 'borrowed') return '<span class="badge bg-warning text-dark">Ausgeliehen</span>';
        if (status === 'missing' || status === 'defective' || status === 'in_repair') {
            return `<span class="badge bg-danger">${statusLabels[status] || status}</span>`;
        }
        if (status) return `<span class="badge bg-secondary">${statusLabels[status] || status}</span>`;
        return '<span class="badge bg-secondary">—</span>';
    }

    itemHasChanges(item) {
        return !!(item.location_changed || item.condition_changed || item.notes || item.counted_quantity != null);
    }

    quantityDiffers(item) {
        if (item.counted_quantity == null) return false;
        const expected = item.expected_quantity != null ? Number(item.expected_quantity) : 1;
        return Number(item.counted_quantity) !== expected;
    }

    quantityCellHtml(item) {
        const expected = item.expected_quantity != null ? Number(item.expected_quantity) : 1;
        if (item.counted_quantity == null) {
            return `<span class="text-muted">${expected}</span>`;
        }
        const counted = Number(item.counted_quantity);
        const cls = counted !== expected ? 'text-warning fw-semibold' : '';
        return `<span class="${cls}">${counted}</span><small class="text-muted"> / ${expected}</small>`;
    }

    dguvBadgeHtml(item) {
        if (item.dguv_due) {
            return '<span class="badge bg-danger ms-1">DGUV fällig</span>';
        }
        if (item.dguv_next_check) {
            return `<span class="badge bg-light text-dark border ms-1">DGUV ${this.escapeHtml(this.formatDate(item.dguv_next_check))}</span>`;
        }
        return '';
    }

    inventurActionHtml(item) {
        const productId = item.product_id;
        const inventurBadge = item.checked
            ? '<span class="badge bg-success">OK</span>'
            : '<span class="badge bg-secondary">Offen</span>';
        if (this.readOnly) {
            return `<span class="me-1">${inventurBadge}</span>`;
        }
        return `
            <button class="btn btn-sm btn-link toggle-check-btn p-0 me-1" type="button"
                    data-product-id="${productId}"
                    title="${item.checked ? 'Als offen markieren' : 'Als inventiert markieren'}">
                ${inventurBadge}
            </button>`;
    }

    itemActionsHtml(item) {
        const productId = item.product_id;
        if (this.readOnly) {
            return '';
        }
        return `
            <div class="mod-list-actions">
                <div class="mod-list-hover-actions align-items-center">
                    <button class="btn btn-sm btn-link edit-item-btn" type="button" data-product-id="${productId}" title="Bearbeiten">
                        <i class="bi bi-pencil"></i>
                    </button>
                </div>
                <div class="dropdown d-inline-block">
                    <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}' aria-expanded="false">
                        <i class="bi bi-three-dots-vertical"></i>
                    </button>
                    <ul class="dropdown-menu dropdown-menu-end inventory-actions-menu">
                        <li>
                            <button class="dropdown-item toggle-check-btn" type="button" data-product-id="${productId}">
                                <i class="bi bi-${item.checked ? 'x-circle' : 'check-circle'} me-2"></i>
                                ${item.checked ? 'Als offen markieren' : 'Als inventiert markieren'}
                            </button>
                        </li>
                        <li>
                            <button class="dropdown-item edit-item-btn" type="button" data-product-id="${productId}">
                                <i class="bi bi-pencil me-2"></i>Bearbeiten
                            </button>
                        </li>
                    </ul>
                </div>
            </div>`;
    }

    productImageHtml(item) {
        const name = this.escapeHtml(item.product_name || '');
        if (item.product_image_path) {
            return `
                <img src="/inventory/product-images/${this.escapeHtml(item.product_image_path)}"
                     alt="${name}"
                     class="inventory-product-preview-img image-mini-preview img-fluid rounded"
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                <div class="inventory-product-preview-fallback" style="display: none;"><i class="bi bi-box-seam"></i></div>`;
        }
        return `<div class="inventory-product-preview-fallback"><i class="bi bi-box-seam"></i></div>`;
    }

    renderItems() {
        if (this.viewMode === 'grid') {
            this.renderGrid();
        } else {
            this.renderTable();
        }
        this.updateStats();
    }

    renderTable() {
        const tbody = document.getElementById('inventoryTableBody');
        if (!tbody) return;

        const items = this.getFilteredItems();
        if (!items.length) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9">
                        <div class="mod-empty-state py-4 text-center">
                            <p class="text-muted mb-0">Keine Produkte in diesem Filter</p>
                        </div>
                    </td>
                </tr>`;
            return;
        }

        tbody.innerHTML = items.map((item) => {
            const productId = item.product_id;
            const changeBadge = this.itemHasChanges(item)
                ? '<span class="badge bg-warning ms-1">Geändert</span>'
                : '';
            const qtyBadge = this.quantityDiffers(item)
                ? '<span class="badge bg-warning ms-1">Menge</span>'
                : '';
            const locationRaw = item.location_changed
                ? this.cleanText(item.new_location)
                : this.cleanText(item.product_location);
            const location = locationRaw
                ? (item.location_changed
                    ? `<span class="text-warning">${this.escapeHtml(locationRaw)}</span>`
                    : this.escapeHtml(locationRaw))
                : '—';
            const conditionRaw = item.condition_changed
                ? this.cleanText(item.new_condition)
                : this.cleanText(item.product_condition);
            const condition = conditionRaw
                ? (item.condition_changed
                    ? `<span class="text-warning">${this.escapeHtml(conditionRaw)}</span>`
                    : this.escapeHtml(conditionRaw))
                : '—';
            const notes = item.notes
                ? this.escapeHtml(item.notes.substring(0, 50)) + (item.notes.length > 50 ? '...' : '')
                : '—';
            const dguvCell = item.dguv_due
                ? `<span class="text-danger fw-semibold">${this.escapeHtml(this.formatDate(item.dguv_next_check))}</span>`
                : (item.dguv_next_check ? this.escapeHtml(this.formatDate(item.dguv_next_check)) : '—');

            return `
                <tr class="mod-list-row inventory-item-row ${item.checked ? 'checked' : ''}" data-product-id="${productId}">
                    <td>
                        <div class="d-flex align-items-center flex-wrap gap-1">
                            <strong>${this.escapeHtml(item.product_name || '')}</strong>
                            ${this.inventurActionHtml(item)}
                            ${this.dguvBadgeHtml(item)}${qtyBadge}${changeBadge}
                        </div>
                    </td>
                    <td>${this.statusBadgeHtml(item)}</td>
                    <td class="d-none d-md-table-cell">${this.escapeHtml(this.cleanText(item.product_category) || '—')}</td>
                    <td class="d-none d-lg-table-cell">${location}</td>
                    <td class="d-none d-md-table-cell">${this.quantityCellHtml(item)}</td>
                    <td class="d-none d-lg-table-cell">${condition}</td>
                    <td class="d-none d-xl-table-cell"><small>${dguvCell}</small></td>
                    <td class="d-none d-xl-table-cell"><small class="text-muted">${notes}</small></td>
                    <td class="text-end" onclick="event.stopPropagation()">${this.itemActionsHtml(item)}</td>
                </tr>`;
        }).join('');

        this.bindItemActions(tbody);
    }

    renderGrid() {
        const grid = document.getElementById('sessionGridView');
        if (!grid) return;

        const items = this.getFilteredItems();
        if (!items.length) {
            grid.innerHTML = `
                <div class="col-12">
                    <div class="mod-empty-state py-4 text-center">
                        <p class="text-muted mb-0">Keine Produkte in diesem Filter</p>
                    </div>
                </div>`;
            return;
        }

        grid.innerHTML = items.map((item) => {
            const productId = item.product_id;
            const changeBadge = this.itemHasChanges(item)
                ? '<span class="badge bg-warning">Geändert</span>'
                : '';
            const locDisplay = this.cleanText(item.location_changed ? item.new_location : item.product_location) || '—';
            const editBtn = this.readOnly
                ? ''
                : `<button class="btn btn-sm btn-link edit-item-btn" type="button" data-product-id="${productId}" title="Bearbeiten">
                        <i class="bi bi-pencil"></i>
                   </button>`;
            const menu = this.readOnly
                ? ''
                : `<div class="dropdown">
                        <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}'>
                            <i class="bi bi-three-dots-vertical"></i>
                        </button>
                        <ul class="dropdown-menu dropdown-menu-end inventory-actions-menu">
                            <li>
                                <button class="dropdown-item toggle-check-btn" type="button" data-product-id="${productId}">
                                    <i class="bi bi-${item.checked ? 'x-circle' : 'check-circle'} me-2"></i>
                                    ${item.checked ? 'Als offen markieren' : 'Als inventiert markieren'}
                                </button>
                            </li>
                            <li>
                                <button class="dropdown-item edit-item-btn" type="button" data-product-id="${productId}">
                                    <i class="bi bi-pencil me-2"></i>Bearbeiten
                                </button>
                            </li>
                        </ul>
                   </div>`;

            return `
                <div class="col-12 col-md-6 col-lg-4">
                    <article class="card h-100 inventory-product-card product-card inventory-session-card ${item.checked ? 'is-checked' : ''}"
                             data-product-id="${productId}">
                        <div class="card-body d-flex flex-column">
                            <div class="inventory-product-preview text-center mb-3">
                                ${this.productImageHtml(item)}
                            </div>
                            <div class="d-flex justify-content-between align-items-start gap-2">
                                <div class="flex-grow-1 min-width-0">
                                    <div class="d-flex align-items-center gap-2 mb-1 min-width-0 flex-wrap">
                                        <h6 class="card-title text-truncate mb-0" title="${this.escapeHtml(item.product_name || '')}">
                                            ${this.escapeHtml(item.product_name || '')}
                                        </h6>
                                        ${this.inventurActionHtml(item)}
                                        ${this.statusBadgeHtml(item)}
                                        ${changeBadge}
                                        ${this.dguvBadgeHtml(item)}
                                    </div>
                                    ${item.product_category ? `<p class="inventory-card-meta mb-1 text-truncate"><i class="bi bi-tag"></i> ${this.escapeHtml(item.product_category)}</p>` : ''}
                                    <p class="inventory-card-meta mb-1 text-truncate"><i class="bi bi-hash"></i> ${this.quantityCellHtml(item)}</p>
                                    <p class="inventory-card-meta mb-0 text-truncate"><i class="bi bi-geo-alt"></i> ${this.escapeHtml(locDisplay)}</p>
                                </div>
                                <div class="d-flex align-items-start gap-1 flex-shrink-0" onclick="event.stopPropagation()">
                                    <div class="inventory-grid-hover-actions align-items-center">
                                        ${editBtn}
                                    </div>
                                    ${menu}
                                </div>
                            </div>
                        </div>
                    </article>
                </div>`;
        }).join('');

        this.bindItemActions(grid);
    }

    bindItemActions(root) {
        if (this.readOnly) return;
        root.querySelectorAll('.toggle-check-btn').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const el = e.target.closest('.toggle-check-btn');
                const productId = parseInt(el.dataset.productId, 10);
                const item = this.items.get(productId);
                if (!item) return;
                this.toggleCheck(productId, !item.checked);
            });
        });
        root.querySelectorAll('.edit-item-btn').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const productId = parseInt(e.target.closest('.edit-item-btn').dataset.productId, 10);
                this.showProductModal(productId);
            });
        });
    }

    filterItems() {
        this.renderItems();
    }

    getOpenCount() {
        let n = 0;
        this.items.forEach((item) => {
            if (!item.checked) n += 1;
        });
        return n;
    }

    updateStats() {
        let total = 0;
        let open = 0;
        let checked = 0;
        let changed = 0;
        this.items.forEach((item) => {
            total += 1;
            if (item.checked) checked += 1;
            else open += 1;
            if (this.itemHasChanges(item)) changed += 1;
        });
        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = String(val);
        };
        set('statTotal', total);
        set('statOpen', open);
        set('statChecked', checked);
        set('statChanged', changed);
    }

    async toggleCheck(productId, checked) {
        if (this.readOnly) return;
        try {
            const item = this.items.get(productId);
            const payload = { checked: checked, version: item?.version };
            const response = await fetch(`/inventory/vnext/api/inventory/${this.inventoryId}/item/${productId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            if (!response.ok) {
                if (response.status === 409) {
                    const conflict = await response.json();
                    this.showConflictMessage(conflict);
                    await this.loadItems();
                    return;
                }
                throw new Error('Fehler beim Aktualisieren');
            }

            const data = await response.json();
            const local = this.items.get(productId);
            if (local) {
                if (data.item) Object.assign(local, data.item);
                else {
                    local.checked = data.checked;
                    local.checked_at = data.checked_at;
                }
            }
            await this.loadItems();
        } catch (error) {
            console.error('Fehler beim Toggle Check:', error);
            this.showError('Fehler beim Aktualisieren der Checkbox.');
        }
    }

    async showProductModal(productId) {
        if (this.readOnly) return;
        const item = this.items.get(productId);
        if (!item) {
            this.showError('Produkt nicht gefunden.');
            return;
        }

        const lock = await this.acquireLock(productId);
        if (!lock) return;
        this.currentEditingProductId = productId;
        if (this.lockRefreshTimer) clearInterval(this.lockRefreshTimer);
        this.lockRefreshTimer = setInterval(() => this.refreshLock(productId), 30000);

        const modalBody = document.getElementById('productEditModalBody');
        if (!modalBody) return;

        const product = {
            id: item.product_id,
            name: item.product_name,
            category: item.product_category,
            location: this.cleanText(item.product_location),
            condition: this.cleanText(item.product_condition),
            status: item.product_status || 'available',
        };
        const locationValue = this.cleanText(item.new_location) || product.location;
        const conditionValue = this.cleanText(item.new_condition) || product.condition;
        const changedAt = this.formatDateTime(item.last_changed_at);
        const dguvLast = this.formatDateInput(item.dguv_last_check);
        const dguvNext = this.formatDateInput(item.dguv_next_check);
        const dguvDueAlert = item.dguv_due
            ? `<div class="alert alert-warning py-2 px-3 mb-0" style="border-radius: 1rem;">
                    <i class="bi bi-exclamation-triangle me-1"></i>
                    DGUV-Prüfung fällig${item.dguv_next_check ? ` seit ${this.escapeHtml(this.formatDate(item.dguv_next_check))}` : ''}.
               </div>`
            : '';

        const statusOptions = [
            ['available', 'Verfügbar'],
            ['borrowed', 'Ausgeliehen'],
            ['missing', 'Fehlend'],
            ['defective', 'Defekt'],
            ['in_repair', 'In Reparatur'],
            ['retired', 'Ausgemustert'],
        ].map(([value, label]) =>
            `<option value="${value}" ${product.status === value ? 'selected' : ''}>${label}</option>`
        ).join('');

        const conditionOptions = ['Neu', 'Gut', 'Gebraucht', 'Beschädigt'].map((value) =>
            `<option value="${value}" ${conditionValue === value ? 'selected' : ''}>${value}</option>`
        ).join('');

        const expectedQty = item.expected_quantity != null ? Number(item.expected_quantity) : 1;
        const countedQty = item.counted_quantity != null ? String(item.counted_quantity) : '';
        const isConsumable = (item.product_item_type || 'asset') === 'consumable';
        const qtyHint = isConsumable
            ? 'Wird beim Abschließen als neuer Bestand übernommen'
            : 'Für gleiche Artikel (z.B. Kabel). Bestand wird nur bei Verbrauchsmaterial übernommen';
        const dguvIntervalNum = item.dguv_interval_months != null ? Number(item.dguv_interval_months) : 12;
        const dguvNextComputed = this.computeDguvNextIso(dguvLast, dguvIntervalNum) || dguvNext;

        modalBody.innerHTML = `
            <form id="productEditForm" class="inventory-inventur-edit-form">
                <input type="hidden" id="editProductId" value="${product.id}">
                <input type="hidden" id="editProductVersion" value="${item.version || 1}">

                <section class="inventory-form-card">
                    <div class="inventory-form-card-head">
                        <h2 class="inventory-form-section-title"><i class="bi bi-box-seam"></i> Produkt</h2>
                    </div>
                    <div class="inventory-form-fields">
                        <div>
                            <div class="fw-semibold fs-5">${this.escapeHtml(product.name)}</div>
                            <div class="text-muted small">${this.escapeHtml(product.category || 'Keine Kategorie')}</div>
                            <div class="text-muted small mt-1">
                                Letzte Änderung: ${this.escapeHtml(item.last_changed_by || 'Unbekannt')} um ${this.escapeHtml(changedAt)}
                            </div>
                        </div>
                        ${dguvDueAlert}
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" id="editChecked" ${item.checked ? 'checked' : ''}>
                            <label class="form-check-label" for="editChecked">Inventiert</label>
                        </div>
                    </div>
                </section>

                <section class="inventory-form-card">
                    <div class="inventory-form-card-head">
                        <h2 class="inventory-form-section-title"><i class="bi bi-hash"></i> Zählung</h2>
                    </div>
                    <div class="inventory-form-fields inventory-form-fields--2">
                        <div class="inventory-form-field">
                            <label for="editCountedQuantity" class="form-label">Anzahl (gezählt)</label>
                            <input type="number" min="0" step="1" class="form-control" id="editCountedQuantity"
                                   value="${this.escapeHtml(countedQty)}" placeholder="Soll: ${expectedQty}">
                            <small class="text-muted">Aktuell im System: ${expectedQty}. ${qtyHint}</small>
                        </div>
                        <div class="inventory-form-field">
                            <label for="editNotes" class="form-label">Anmerkungen</label>
                            <textarea class="form-control" id="editNotes" rows="2" placeholder="Anmerkungen zur Inventur...">${this.escapeHtml(item.notes || '')}</textarea>
                        </div>
                    </div>
                </section>

                <section class="inventory-form-card">
                    <div class="inventory-form-card-head">
                        <h2 class="inventory-form-section-title"><i class="bi bi-geo-alt"></i> Zustand & Ort</h2>
                    </div>
                    <div class="inventory-form-fields inventory-form-fields--3">
                        <div class="inventory-form-field">
                            <label for="editLocation" class="form-label">Lagerort</label>
                            <input type="text" class="form-control" id="editLocation"
                                   value="${this.escapeHtml(locationValue)}"
                                   placeholder="${this.escapeHtml(product.location || 'Nicht gesetzt')}">
                            <small class="text-muted">Beim Abschließen übernehmen</small>
                        </div>
                        <div class="inventory-form-field">
                            <label for="editCondition" class="form-label">Zustand</label>
                            <select class="form-select" id="editCondition">
                                <option value="">Bitte wählen...</option>
                                ${conditionOptions}
                            </select>
                            <small class="text-muted">Aktuell: ${this.escapeHtml(product.condition || 'Nicht gesetzt')}</small>
                        </div>
                        <div class="inventory-form-field">
                            <label for="editProductStatus" class="form-label">Status</label>
                            <select class="form-select" id="editProductStatus">${statusOptions}</select>
                            <small class="text-muted">Sofort gespeichert</small>
                        </div>
                    </div>
                </section>

                <section class="inventory-form-card">
                    <div class="inventory-form-card-head">
                        <h2 class="inventory-form-section-title"><i class="bi bi-shield-check"></i> DGUV-Prüfung</h2>
                    </div>
                    <div class="inventory-form-fields inventory-form-fields--3">
                        <div class="inventory-form-field">
                            <label for="editDguvLast" class="form-label">Letzte Prüfung</label>
                            <input type="date" class="form-control" id="editDguvLast" value="${this.escapeHtml(dguvLast)}">
                            <small class="text-muted">Nur dieses Datum angeben</small>
                        </div>
                        <div class="inventory-form-field">
                            <label class="form-label">Intervall</label>
                            <input type="text" class="form-control" id="editDguvIntervalDisplay" readonly
                                   value="${dguvIntervalNum} Monate">
                            <input type="hidden" id="editDguvInterval" value="${dguvIntervalNum}">
                            <small class="text-muted">Fest (nicht änderbar)</small>
                        </div>
                        <div class="inventory-form-field">
                            <label class="form-label">Nächste Prüfung</label>
                            <input type="text" class="form-control" id="editDguvNextDisplay" readonly
                                   value="${this.escapeHtml(dguvNextComputed ? this.formatDate(dguvNextComputed) : '')}"
                                   placeholder="—">
                            <small class="text-muted">Automatisch berechnet</small>
                        </div>
                    </div>
                </section>
            </form>
        `;

        const lastEl = document.getElementById('editDguvLast');
        const intervalEl = document.getElementById('editDguvInterval');
        const nextDisplayEl = document.getElementById('editDguvNextDisplay');
        const refreshDguvNext = () => {
            const nextIso = this.computeDguvNextIso(lastEl?.value, intervalEl?.value || 12);
            if (nextDisplayEl) nextDisplayEl.value = nextIso ? this.formatDate(nextIso) : '';
        };
        if (lastEl) {
            lastEl.addEventListener('change', refreshDguvNext);
            lastEl.addEventListener('input', refreshDguvNext);
        }

        const modalElement = document.getElementById('productEditModal');
        if (!modalElement) return;
        this.ensureModalOnBody(modalElement);
        this.clearModalArtifacts();

        let modal = bootstrap.Modal.getInstance(modalElement);
        if (!modal) {
            modal = new bootstrap.Modal(modalElement, { backdrop: true, keyboard: true, focus: true });
        }
        modal.show();

        requestAnimationFrame(() => {
            const backdrops = document.querySelectorAll('.modal-backdrop');
            if (backdrops.length > 1) {
                backdrops.forEach((el, idx) => {
                    if (idx < backdrops.length - 1) el.remove();
                });
            }
            modalElement.style.zIndex = '1055';
            const activeBackdrop = document.querySelector('.modal-backdrop');
            if (activeBackdrop) activeBackdrop.style.zIndex = '1050';
        });
    }

    computeDguvNextIso(isoDate, months) {
        if (!isoDate || !months) return null;
        const parts = String(isoDate).slice(0, 10).split('-').map(Number);
        if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return null;
        const [y, m, d] = parts;
        const totalMonths = (y * 12 + (m - 1)) + Number(months);
        const year = Math.floor(totalMonths / 12);
        const month = (totalMonths % 12) + 1;
        const daysInMonth = new Date(year, month, 0).getDate();
        const day = Math.min(d, daysInMonth);
        return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    }

    async saveProduct() {
        const productId = parseInt(document.getElementById('editProductId')?.value, 10);
        const version = parseInt(document.getElementById('editProductVersion')?.value || '1', 10);
        if (!productId) return;

        const checked = document.getElementById('editChecked')?.checked || false;
        const notes = document.getElementById('editNotes')?.value.trim() || null;
        let newLocation = document.getElementById('editLocation')?.value.trim() || null;
        if (newLocation === 'None' || newLocation === 'null') newLocation = null;
        const newCondition = document.getElementById('editCondition')?.value || null;
        const productStatus = document.getElementById('editProductStatus')?.value || null;
        const dguvLast = document.getElementById('editDguvLast')?.value || null;
        const countedRaw = document.getElementById('editCountedQuantity')?.value;
        const countedQuantity = countedRaw === '' || countedRaw == null ? null : parseInt(countedRaw, 10);
        if (countedQuantity != null && (!Number.isFinite(countedQuantity) || countedQuantity < 0)) {
            this.showError('Anzahl muss eine ganze Zahl >= 0 sein.');
            return;
        }

        try {
            const response = await fetch(`/inventory/vnext/api/inventory/${this.inventoryId}/item/${productId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    checked: checked || countedQuantity != null,
                    notes,
                    counted_quantity: countedQuantity,
                    new_location: newLocation,
                    new_condition: newCondition,
                    product_status: productStatus,
                    dguv_last_check: dguvLast,
                    version,
                }),
            });

            if (!response.ok) {
                if (response.status === 409) {
                    const conflict = await response.json();
                    this.showConflictMessage(conflict);
                    await this.loadItems();
                    return;
                }
                throw new Error('Fehler beim Speichern');
            }

            const data = await response.json();
            const item = this.items.get(productId);
            if (item) Object.assign(item, data.item);

            const modalElement = document.getElementById('productEditModal');
            const modal = bootstrap.Modal.getInstance(modalElement);
            if (modal) modal.hide();
            setTimeout(() => this.clearModalArtifacts(), 300);

            await this.loadItems();
            this.resumeScannerIfActive();
        } catch (error) {
            console.error('Fehler beim Speichern:', error);
            this.showError('Fehler beim Speichern der Änderungen.');
        }
    }

    resumeScannerIfActive() {
        if (window.inventoryScannerManager && window.inventoryScannerManager.stream) {
            if (!window.inventoryScannerManager.scanning) {
                window.inventoryScannerManager.scanning = true;
                setTimeout(() => window.inventoryScannerManager.scanForQR(), 500);
            }
        }
    }

    async handleScan(qrData) {
        try {
            const response = await fetch(`/inventory/vnext/api/inventory/${this.inventoryId}/scan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ qr_data: qrData }),
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Fehler beim Scannen');
            }

            const data = await response.json();
            this.showScanSuccess();
            if (window.inventoryScannerManager) {
                window.inventoryScannerManager.scanning = false;
            }
            setTimeout(() => this.showProductModal(data.product.id), 500);
            this.loadItems();
        } catch (error) {
            console.error('Fehler beim Scannen:', error);
            this.showError(error.message);
            if (window.inventoryScannerManager && window.inventoryScannerManager.stream) {
                setTimeout(() => {
                    window.inventoryScannerManager.scanning = true;
                    window.inventoryScannerManager.scanForQR();
                }, 1000);
            }
        }
    }

    async handleManualInput(input) {
        if (!input || !input.trim()) return;
        const trimmedInput = input.trim();
        let productId = null;
        let cleaned = trimmedInput.replace(/^PROD[B-]?/i, '').trim();
        const parsed = parseInt(cleaned, 10);
        if (!isNaN(parsed) && parsed > 0) {
            productId = parsed;
        } else {
            const numbersOnly = trimmedInput.replace(/\D/g, '');
            if (numbersOnly) {
                const numParsed = parseInt(numbersOnly, 10);
                if (!isNaN(numParsed) && numParsed > 0) productId = numParsed;
                else {
                    await this.handleScan(trimmedInput);
                    return;
                }
            } else {
                await this.handleScan(trimmedInput);
                return;
            }
        }

        let item = this.items.get(productId);
        if (!item) {
            await new Promise((resolve) => setTimeout(resolve, 100));
            item = this.items.get(productId);
            if (!item) {
                this.showError('Produkt nicht in dieser Inventur gefunden: ' + productId);
                return;
            }
            productId = item.product_id;
        }

        try {
            await this.toggleCheck(productId, true);
        } catch (error) {
            console.error('Fehler beim Abhaken:', error);
        }
        setTimeout(() => this.showProductModal(productId), 100);
    }

    updateProgress(inventory) {
        if (!inventory) {
            this.updateStats();
            return;
        }
        const progressText = document.getElementById('inventurProgressText');
        if (progressText) {
            progressText.textContent = `Fortschritt: ${inventory.checked_count} von ${inventory.total_count} Produkten inventiert`;
        }
        const bar = document.getElementById('inventurProgressBar');
        if (bar) {
            const pct = inventory.total_count > 0
                ? (inventory.checked_count / inventory.total_count) * 100
                : 0;
            bar.style.width = `${pct}%`;
            const wrap = bar.parentElement;
            if (wrap) wrap.setAttribute('aria-valuenow', String(Math.round(pct)));
        }
        this.updateStats();
    }

    startPolling() {
        this.pollingInterval = setInterval(() => this.loadItems(), 3000);
    }

    stopPolling() {
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
    }

    showScanSuccess() {
        const popup = document.getElementById('scannerSuccessPopup');
        if (popup) {
            popup.style.display = 'block';
            setTimeout(() => { popup.style.display = 'none'; }, 2000);
        }
    }

    showError(message) {
        const errorDiv = document.getElementById('scannerError');
        if (errorDiv) {
            errorDiv.className = 'alert alert-danger';
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
            setTimeout(() => { errorDiv.style.display = 'none'; }, 5000);
            return;
        }
        if (window.showAppBanner) window.showAppBanner(message, 'danger');
    }

    showConflictMessage(conflictPayload) {
        const currentVersion = conflictPayload?.details?.current_version;
        this.showError(`Konflikt erkannt: Datensatz wurde inzwischen geändert (Version ${currentVersion || 'neu'}). Bitte erneut pruefen.`);
    }

    async acquireLock(productId) {
        try {
            const response = await fetch(`/inventory/vnext/api/inventory/${this.inventoryId}/locks/acquire`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_id: productId, ttl_seconds: 90, reason: 'modal_edit' }),
            });
            if (!response.ok) {
                if (response.status === 409) {
                    const payload = await response.json();
                    const lockUser = payload?.details?.locked_by || 'anderem Nutzer';
                    this.showError(`Dieses Produkt wird gerade von ${lockUser} bearbeitet.`);
                    return null;
                }
                return null;
            }
            return await response.json();
        } catch (error) {
            console.warn('Locking nicht verfügbar, fahre ohne Lock fort', error);
            return { ok: true };
        }
    }

    async releaseLock(productId) {
        try {
            await fetch(`/inventory/vnext/api/inventory/${this.inventoryId}/locks/release`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_id: productId }),
            });
        } catch (error) {
            console.warn('Lock release fehlgeschlagen', error);
        }
    }

    async refreshLock(productId) {
        try {
            await fetch(`/inventory/vnext/api/inventory/${this.inventoryId}/locks/refresh`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_id: productId, ttl_seconds: 90 }),
            });
        } catch (error) {
            console.warn('Lock refresh fehlgeschlagen', error);
        }
    }

    escapeHtml(text) {
        if (text === null || text === undefined) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    cleanText(value) {
        if (value === null || value === undefined) return '';
        const s = String(value).trim();
        if (!s || s === 'None' || s === 'null' || s === 'undefined') return '';
        return s;
    }

    formatDateTime(value) {
        const raw = this.cleanText(value);
        if (!raw) return '—';
        const d = new Date(raw);
        if (Number.isNaN(d.getTime())) return raw;
        return d.toLocaleString('de-DE', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    formatDate(value) {
        const raw = this.cleanText(value);
        if (!raw) return '—';
        const d = new Date(raw.length <= 10 ? `${raw}T00:00:00` : raw);
        if (Number.isNaN(d.getTime())) return raw;
        return d.toLocaleDateString('de-DE', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
        });
    }

    formatDateInput(value) {
        const raw = this.cleanText(value);
        if (!raw) return '';
        return raw.slice(0, 10);
    }
}

class InventoryScannerManager {
    constructor(inventoryId, toolManager) {
        this.inventoryId = inventoryId;
        this.toolManager = toolManager;
        this.stream = null;
        this.scanning = false;
    }

    init() {
        const startBtn = document.getElementById('startScannerBtn');
        const stopBtn = document.getElementById('stopScannerBtn');
        if (startBtn) startBtn.addEventListener('click', () => this.startScanner());
        if (stopBtn) stopBtn.addEventListener('click', () => this.stopScanner());
    }

    async startScanner() {
        if (!('getUserMedia' in navigator.mediaDevices)) {
            this.toolManager?.showError('Ihr Browser unterstuetzt keine Kamera-API.');
            return;
        }
        try {
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } },
            });
            const video = document.getElementById('scannerVideo');
            const container = document.getElementById('scannerContainer');
            if (video && container) {
                video.srcObject = this.stream;
                container.style.display = 'block';
                const startBtn = document.getElementById('startScannerBtn');
                const stopBtn = document.getElementById('stopScannerBtn');
                if (startBtn) startBtn.style.display = 'none';
                if (stopBtn) stopBtn.style.display = 'inline-block';
                this.scanning = true;
                this.scanForQR();
            }
        } catch (error) {
            console.error('Fehler beim Starten der Kamera:', error);
            this.toolManager?.showError('Fehler beim Starten der Kamera: ' + error.message);
        }
    }

    stopScanner() {
        this.scanning = false;
        if (this.stream) {
            this.stream.getTracks().forEach((track) => track.stop());
            this.stream = null;
        }
        const video = document.getElementById('scannerVideo');
        const container = document.getElementById('scannerContainer');
        if (video) video.srcObject = null;
        if (container) container.style.display = 'none';
        const startBtn = document.getElementById('startScannerBtn');
        const stopBtn = document.getElementById('stopScannerBtn');
        if (startBtn) startBtn.style.display = 'inline-block';
        if (stopBtn) stopBtn.style.display = 'none';
    }

    scanForQR() {
        if (!this.scanning) return;
        const video = document.getElementById('scannerVideo');
        const canvas = document.getElementById('scannerCanvas');
        if (!video || !canvas) {
            setTimeout(() => this.scanForQR(), 500);
            return;
        }
        const jsQRFunction = window.jsQR || (typeof jsQR !== 'undefined' ? jsQR : null);
        if (!jsQRFunction) {
            setTimeout(() => this.scanForQR(), 500);
            return;
        }
        if (video.readyState < 2 || !video.videoWidth) {
            setTimeout(() => this.scanForQR(), 200);
            return;
        }
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const context = canvas.getContext('2d');
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        try {
            const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
            const code = jsQRFunction(imageData.data, imageData.width, imageData.height, {
                inversionAttempts: 'attemptBoth',
            });
            if (code) {
                this.scanning = false;
                this.toolManager?.showScanSuccess();
                this.toolManager?.handleScan(code.data).catch(() => {
                    setTimeout(() => {
                        if (this.stream && !this.scanning) {
                            this.scanning = true;
                            this.scanForQR();
                        }
                    }, 1000);
                });
                return;
            }
            requestAnimationFrame(() => this.scanForQR());
        } catch (error) {
            console.error('Fehler beim Scannen:', error);
            setTimeout(() => this.scanForQR(), 200);
        }
    }
}

window.InventoryToolManager = InventoryToolManager;
window.InventoryScannerManager = InventoryScannerManager;
