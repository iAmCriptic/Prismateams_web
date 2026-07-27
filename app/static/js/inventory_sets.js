/** Produktsets-Übersicht: List/Grid wie Bestand + Multiselect. */

function setsNotify(message, category = 'info') {
    const cat = category === 'error' ? 'danger' : (category || 'info');
    if (typeof window.showAppBanner === 'function') {
        window.showAppBanner(String(message || ''), cat);
        return;
    }
    if (typeof inventoryNotify === 'function') {
        inventoryNotify(message, cat);
        return;
    }
    window.alert(String(message || ''));
}

class SetsManager {
    constructor(config = {}) {
        this.config = config;
        this.i18n = config.i18n || {};
        this.sets = [];
        this.filteredSets = [];
        this.selectedSets = new Set();
        this.viewMode = localStorage.getItem('inventorySetsViewMode')
            || localStorage.getItem('inventoryViewMode')
            || 'list';
        this.sortField = localStorage.getItem('inventorySetsSortField') || 'name';
        this.sortDirection = localStorage.getItem('inventorySetsSortDirection') || 'asc';
        this.searchTimeout = null;
        this.canBorrow = !!config.canBorrow;
        this.currentUserId = Number(config.currentUserId) || null;
        this.isAdmin = !!config.isAdmin;
        this.newSetUrl = config.newSetUrl || '/inventory/sets/new';
    }

    async init() {
        this.setupViewToggle();
        this.setupFilterControls();
        this.setupSortControls();
        this.setupBulkActions();
        if (window.InventoryPillSelect) {
            window.InventoryPillSelect.enhanceAll(document);
        }
        this.applyViewMode();
        await this.loadSets();
    }

    t(key, fallback = '') {
        return this.i18n[key] || fallback || key;
    }

    escapeHtml(text) {
        if (text == null) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    formatTemplate(template, values = {}) {
        return String(template || '').replace(/\{(\w+)\}/g, (_, key) => {
            return values[key] != null ? String(values[key]) : '';
        });
    }

    getFilterEls(key) {
        return Array.from(document.querySelectorAll(`[data-inv-filter="${key}"]`));
    }

    getFilterValue(key) {
        const els = this.getFilterEls(key);
        if (!els.length) return '';
        return els[0]?.value || '';
    }

    setFilterValue(key, value) {
        this.getFilterEls(key).forEach((el) => {
            el.value = value;
            if (window.InventoryPillSelect) {
                window.InventoryPillSelect.sync(el);
            }
        });
    }

    async loadSets() {
        const response = await fetch('/inventory/api/sets');
        if (!response.ok) {
            throw new Error(this.t('loadError', 'Fehler beim Laden der Sets'));
        }
        const data = await response.json();
        this.sets = Array.isArray(data) ? data : [];
        this.applyFilters();
    }

    setupFilterControls() {
        const filterKeys = ['searchInput', 'availabilityFilter', 'ownershipFilter', 'descriptionFilter'];
        filterKeys.forEach((key) => {
            this.getFilterEls(key).forEach((el) => {
                const eventName = key === 'searchInput' ? 'input' : 'change';
                el.addEventListener(eventName, () => {
                    this.getFilterEls(key).forEach((other) => {
                        if (other !== el) {
                            other.value = el.value;
                            if (window.InventoryPillSelect) {
                                window.InventoryPillSelect.sync(other);
                            }
                        }
                    });
                    if (key === 'searchInput') {
                        clearTimeout(this.searchTimeout);
                        this.searchTimeout = setTimeout(() => this.applyFilters(), 250);
                        return;
                    }
                    this.applyFilters();
                });
            });
        });

        document.querySelectorAll('.inventory-reset-filters-btn').forEach((btn) => {
            btn.addEventListener('click', () => this.resetFilters());
        });
    }

    setupSortControls() {
        const validFields = ['name', 'product_count', 'available_count', 'created_at', 'creator'];
        if (!validFields.includes(this.sortField)) this.sortField = 'name';
        if (!['asc', 'desc'].includes(this.sortDirection)) this.sortDirection = 'asc';

        this.setFilterValue('sortField', this.sortField);
        this.setFilterValue('sortDirection', this.sortDirection);

        this.getFilterEls('sortField').forEach((el) => {
            el.addEventListener('change', () => {
                const selected = el.value;
                this.sortField = validFields.includes(selected) ? selected : 'name';
                this.setFilterValue('sortField', this.sortField);
                localStorage.setItem('inventorySetsSortField', this.sortField);
                this.applyFilters();
            });
        });

        this.getFilterEls('sortDirection').forEach((el) => {
            el.addEventListener('change', () => {
                this.sortDirection = el.value === 'desc' ? 'desc' : 'asc';
                this.setFilterValue('sortDirection', this.sortDirection);
                localStorage.setItem('inventorySetsSortDirection', this.sortDirection);
                this.applyFilters();
            });
        });

        document.querySelectorAll('.inventory-reset-sort-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                this.sortField = 'name';
                this.sortDirection = 'asc';
                localStorage.removeItem('inventorySetsSortField');
                localStorage.removeItem('inventorySetsSortDirection');
                this.setFilterValue('sortField', 'name');
                this.setFilterValue('sortDirection', 'asc');
                this.applyFilters();
            });
        });
    }

    resetFilters() {
        ['searchInput', 'availabilityFilter', 'ownershipFilter', 'descriptionFilter'].forEach((key) => {
            this.setFilterValue(key, '');
        });
        this.applyFilters();
    }

    setupBulkActions() {
        const selectAllBtn = document.getElementById('bulkSelectAllBtn');
        const deselectAllBtn = document.getElementById('bulkDeselectAllBtn');
        const borrowBtn = document.getElementById('bulkBorrowBtn');
        const editBtn = document.getElementById('bulkEditBtn');
        const deleteBtn = document.getElementById('bulkDeleteBtn');

        if (selectAllBtn) selectAllBtn.addEventListener('click', () => this.selectAll());
        if (deselectAllBtn) deselectAllBtn.addEventListener('click', () => this.deselectAll());
        if (borrowBtn) borrowBtn.addEventListener('click', () => this.borrowSelected());
        if (editBtn) editBtn.addEventListener('click', () => this.editSelected());
        if (deleteBtn) deleteBtn.addEventListener('click', () => this.openBulkDeleteModal());
    }

    setupViewToggle() {
        const bindToggle = (listBtn, gridBtn) => {
            if (!listBtn || !gridBtn) return;
            listBtn.addEventListener('click', () => {
                this.viewMode = 'list';
                localStorage.setItem('inventorySetsViewMode', 'list');
                this.applyViewMode();
            });
            gridBtn.addEventListener('click', () => {
                this.viewMode = 'grid';
                localStorage.setItem('inventorySetsViewMode', 'grid');
                this.applyViewMode();
            });
        };

        bindToggle(document.getElementById('listViewBtn'), document.getElementById('gridViewBtn'));
        bindToggle(document.getElementById('listViewBtnMobile'), document.getElementById('gridViewBtnMobile'));
    }

    applyViewMode() {
        const listBtns = [
            document.getElementById('listViewBtn'),
            document.getElementById('listViewBtnMobile'),
        ].filter(Boolean);
        const gridBtns = [
            document.getElementById('gridViewBtn'),
            document.getElementById('gridViewBtnMobile'),
        ].filter(Boolean);
        const gridViewContainer = document.getElementById('gridViewContainer');
        const listViewContainer = document.getElementById('listViewContainer');

        if (this.viewMode === 'list') {
            if (listViewContainer) listViewContainer.style.display = 'block';
            if (gridViewContainer) gridViewContainer.style.display = 'none';
            listBtns.forEach((btn) => btn.classList.add('active', 'is-active'));
            gridBtns.forEach((btn) => btn.classList.remove('active', 'is-active'));
        } else {
            if (gridViewContainer) gridViewContainer.style.display = 'block';
            if (listViewContainer) listViewContainer.style.display = 'none';
            gridBtns.forEach((btn) => btn.classList.add('active', 'is-active'));
            listBtns.forEach((btn) => btn.classList.remove('active', 'is-active'));
        }

        this.renderSets();
    }

    matchesAvailability(set, filter) {
        if (!filter) return true;
        const total = Number(set.product_count || 0);
        const available = Number(set.available_count || 0);
        if (filter === 'empty') return total === 0;
        if (filter === 'full') return total > 0 && available === total;
        if (filter === 'partial') return total > 0 && available > 0 && available < total;
        if (filter === 'none') return total > 0 && available === 0;
        return true;
    }

    matchesOwnership(set, filter) {
        if (!filter) return true;
        if (filter === 'mine') {
            return Number(set.created_by) === this.currentUserId;
        }
        if (filter === 'editable') {
            return this.canEditSet(set);
        }
        return true;
    }

    matchesDescription(set, filter) {
        if (!filter) return true;
        const hasDescription = !!(set.description && String(set.description).trim());
        if (filter === 'with') return hasDescription;
        if (filter === 'without') return !hasDescription;
        return true;
    }

    applyFilters() {
        const search = (this.getFilterValue('searchInput') || '').trim().toLowerCase();
        const availability = this.getFilterValue('availabilityFilter') || '';
        const ownership = this.getFilterValue('ownershipFilter') || '';
        const description = this.getFilterValue('descriptionFilter') || '';

        this.filteredSets = this.sets.filter((set) => {
            if (search) {
                const haystack = [
                    set.name,
                    set.description,
                    set.creator_name,
                ].filter(Boolean).join(' ').toLowerCase();
                if (!haystack.includes(search)) return false;
            }
            if (!this.matchesAvailability(set, availability)) return false;
            if (!this.matchesOwnership(set, ownership)) return false;
            if (!this.matchesDescription(set, description)) return false;
            return true;
        });

        this.sortFilteredSets();
        this.renderSets();
        this.updateSelectionUI();
    }

    sortFilteredSets() {
        const field = this.sortField || 'name';
        const direction = this.sortDirection === 'desc' ? -1 : 1;
        const collator = new Intl.Collator('de', { numeric: true, sensitivity: 'base' });

        const getString = (value) => String(value == null ? '' : value).trim();
        const getNumber = (value) => {
            const n = Number(value);
            return Number.isFinite(n) ? n : 0;
        };

        this.filteredSets.sort((a, b) => {
            let valueA;
            let valueB;
            switch (field) {
                case 'product_count':
                    valueA = getNumber(a.product_count);
                    valueB = getNumber(b.product_count);
                    break;
                case 'available_count':
                    valueA = getNumber(a.available_count);
                    valueB = getNumber(b.available_count);
                    break;
                case 'created_at':
                    valueA = getString(a.created_at);
                    valueB = getString(b.created_at);
                    break;
                case 'creator':
                    valueA = getString(a.creator_name);
                    valueB = getString(b.creator_name);
                    break;
                case 'name':
                default:
                    valueA = getString(a.name);
                    valueB = getString(b.name);
                    break;
            }

            let comparison;
            if (typeof valueA === 'number' && typeof valueB === 'number') {
                comparison = valueA - valueB;
            } else {
                comparison = collator.compare(String(valueA), String(valueB));
            }
            if (comparison !== 0) return comparison * direction;
            return collator.compare(getString(a.name), getString(b.name)) * direction;
        });
    }

    canEditSet(set) {
        if (!set) return false;
        if (typeof set.can_edit === 'boolean') return set.can_edit;
        return this.isAdmin || Number(set.created_by) === this.currentUserId;
    }

    canDeleteSet(set) {
        return this.canEditSet(set);
    }

    isSetBorrowable(set) {
        return this.canBorrow && Number(set.available_count || 0) > 0;
    }

    availabilityBadgeHtml(set) {
        const total = Number(set.product_count || 0);
        const available = Number(set.available_count || 0);
        if (total === 0) {
            return '<span class="badge bg-secondary">0</span>';
        }
        if (available === total) {
            return `<span class="badge bg-success">${available}/${total}</span>`;
        }
        if (available === 0) {
            return `<span class="badge bg-danger">${available}/${total}</span>`;
        }
        return `<span class="badge bg-warning text-dark">${available}/${total}</span>`;
    }

    productsLabel(set) {
        const count = Number(set.product_count || 0);
        return this.formatTemplate(this.t('productsCount', '{count} Produkte'), { count });
    }

    availableLabel(set) {
        const available = Number(set.available_count || 0);
        const total = Number(set.product_count || 0);
        return this.formatTemplate(
            this.t('availableCount', '{available} von {total} verfügbar'),
            { available, total }
        );
    }

    renderSets() {
        if (this.viewMode === 'grid') {
            this.renderGrid();
        } else {
            this.renderList();
        }
        this.attachCheckboxHandlers();
    }

    renderEmptyState(colspan = null) {
        const createLink = this.newSetUrl
            ? ` <a href="${this.escapeHtml(this.newSetUrl)}">${this.escapeHtml(this.t('createHint', 'Erstellen Sie Ihr erstes Set!'))}</a>`
            : '';
        const body = `
            <div class="mod-empty-state">
                <div>
                    <i class="bi bi-collection display-6 d-block mb-2 opacity-50"></i>
                    ${this.escapeHtml(this.t('empty', 'Keine Sets vorhanden'))}${createLink}
                </div>
            </div>
        `;
        if (colspan) {
            return `<tr><td colspan="${colspan}">${body}</td></tr>`;
        }
        return `<div class="col-12">${body}</div>`;
    }

    renderGrid() {
        const container = document.getElementById('setsContainer');
        if (!container) return;

        if (this.filteredSets.length === 0) {
            container.innerHTML = this.renderEmptyState();
            return;
        }

        container.innerHTML = this.filteredSets
            .map((set) => `<div class="col-12 col-md-6 col-lg-4">${this.renderSetCard(set)}</div>`)
            .join('');
    }

    renderList() {
        const container = document.getElementById('setsList');
        if (!container) return;

        if (this.filteredSets.length === 0) {
            container.innerHTML = this.renderEmptyState(6);
            return;
        }

        container.innerHTML = this.filteredSets.map((set) => this.renderSetListItem(set)).join('');
    }

    buildSetContextMenuHtml(set) {
        const id = set.id;
        const canEdit = this.canEditSet(set);
        const canBorrow = this.isSetBorrowable(set);
        let items = '';
        items += `<li><a class="dropdown-item" href="/inventory/sets/${id}"><i class="bi bi-eye me-2"></i>${this.escapeHtml(this.t('view', 'Anzeigen'))}</a></li>`;
        if (canBorrow) {
            items += `<li><a class="dropdown-item" href="/inventory/sets/${id}/borrow"><i class="bi bi-cart-check me-2"></i>${this.escapeHtml(this.t('borrow', 'Ausleihen'))}</a></li>`;
        }
        if (canEdit) {
            items += `<li><a class="dropdown-item" href="/inventory/sets/${id}/edit"><i class="bi bi-pencil me-2"></i>${this.escapeHtml(this.t('edit', 'Bearbeiten'))}</a></li>`;
        }
        return `<div class="context-menu-source d-none" id="context-menu-set-${id}"><ul class="dropdown-menu inventory-actions-menu">${items}</ul></div>`;
    }

    renderSetCard(set) {
        const isSelected = this.selectedSets.has(set.id);
        const selectionModeClass = isSelected ? 'selection-mode' : '';
        const canEdit = this.canEditSet(set);
        const canBorrow = this.isSetBorrowable(set);
        const badge = this.availabilityBadgeHtml(set);
        const description = set.description
            ? `<p class="inventory-card-meta mb-0 text-truncate" title="${this.escapeHtml(set.description)}">${this.escapeHtml(set.description)}</p>`
            : '';

        const hoverBorrow = canBorrow
            ? `<a class="btn btn-sm btn-link" href="/inventory/sets/${set.id}/borrow" title="${this.escapeHtml(this.t('borrow', 'Ausleihen'))}" onclick="event.stopPropagation()"><i class="bi bi-cart-check"></i></a>`
            : '';
        const hoverEdit = canEdit
            ? `<a class="btn btn-sm btn-link" href="/inventory/sets/${set.id}/edit" title="${this.escapeHtml(this.t('edit', 'Bearbeiten'))}" onclick="event.stopPropagation()"><i class="bi bi-pencil"></i></a>`
            : '';

        return `
            <div class="card h-100 inventory-product-card product-card inventory-set-card ${selectionModeClass}"
                 style="cursor: pointer;"
                 onclick="if(window.setsManager){window.setsManager.handleCardClick(${set.id});}"
                 data-context-zone data-context-menu="template" data-context-menu-id="context-menu-set-${set.id}">
                ${this.buildSetContextMenuHtml(set)}
                <div class="card-body d-flex flex-column">
                    <div class="inventory-product-preview text-center mb-3">
                        <div class="inventory-product-preview-fallback"><i class="bi bi-collection"></i></div>
                        <div class="inventory-product-preview-check" onclick="event.stopPropagation()">
                            <input type="checkbox" class="form-check-input set-checkbox"
                                   value="${set.id}" data-set-id="${set.id}"
                                   ${isSelected ? 'checked' : ''}>
                        </div>
                    </div>
                    <div class="d-flex justify-content-between align-items-start gap-2">
                        <div class="flex-grow-1 min-width-0">
                            <div class="d-flex align-items-center gap-2 mb-1 min-width-0">
                                <h6 class="card-title text-truncate mb-0" title="${this.escapeHtml(set.name)}">${this.escapeHtml(set.name)}</h6>
                                ${badge}
                            </div>
                            <p class="inventory-card-meta mb-1 text-truncate">
                                <i class="bi bi-box"></i> ${this.escapeHtml(this.productsLabel(set))}
                            </p>
                            <p class="inventory-card-meta mb-1 text-truncate">
                                <i class="bi bi-check2-circle"></i> ${this.escapeHtml(this.availableLabel(set))}
                            </p>
                            ${description}
                        </div>
                        <div class="d-flex align-items-start gap-1 flex-shrink-0" onclick="event.stopPropagation()">
                            <div class="inventory-grid-hover-actions">
                                <a class="btn btn-sm btn-link" href="/inventory/sets/${set.id}" title="${this.escapeHtml(this.t('view', 'Anzeigen'))}">
                                    <i class="bi bi-eye"></i>
                                </a>
                                ${hoverBorrow}
                                ${hoverEdit}
                            </div>
                            <div class="dropdown inventory-card-menu">
                                <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}' aria-expanded="false">
                                    <i class="bi bi-three-dots-vertical"></i>
                                </button>
                                <ul class="dropdown-menu dropdown-menu-end inventory-actions-menu">
                                    <li><a class="dropdown-item" href="/inventory/sets/${set.id}"><i class="bi bi-eye me-2"></i>${this.escapeHtml(this.t('view', 'Anzeigen'))}</a></li>
                                    ${canBorrow ? `<li><a class="dropdown-item" href="/inventory/sets/${set.id}/borrow"><i class="bi bi-cart-check me-2"></i>${this.escapeHtml(this.t('borrow', 'Ausleihen'))}</a></li>` : ''}
                                    ${canEdit ? `<li><a class="dropdown-item" href="/inventory/sets/${set.id}/edit"><i class="bi bi-pencil me-2"></i>${this.escapeHtml(this.t('edit', 'Bearbeiten'))}</a></li>` : ''}
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    renderSetListItem(set) {
        const isSelected = this.selectedSets.has(set.id);
        const selectionModeClass = isSelected ? 'selection-mode' : '';
        const canEdit = this.canEditSet(set);
        const canBorrow = this.isSetBorrowable(set);
        const badge = this.availabilityBadgeHtml(set);
        const description = set.description ? this.escapeHtml(set.description) : '—';

        const hoverBorrow = canBorrow
            ? `<a class="btn btn-sm btn-link" href="/inventory/sets/${set.id}/borrow" title="${this.escapeHtml(this.t('borrow', 'Ausleihen'))}" onclick="event.stopPropagation()"><i class="bi bi-cart-check"></i></a>`
            : '';
        const hoverEdit = canEdit
            ? `<a class="btn btn-sm btn-link" href="/inventory/sets/${set.id}/edit" title="${this.escapeHtml(this.t('edit', 'Bearbeiten'))}" onclick="event.stopPropagation()"><i class="bi bi-pencil"></i></a>`
            : '';

        return `
            <tr class="mod-list-row ${selectionModeClass}" data-set-id="${set.id}"
                data-context-zone data-context-menu="template" data-context-menu-id="context-menu-set-${set.id}">
                <td class="inventory-list-check-col">
                    <input type="checkbox" class="form-check-input set-checkbox"
                           value="${set.id}" data-set-id="${set.id}"
                           ${isSelected ? 'checked' : ''}
                           onclick="event.stopPropagation()">
                    ${this.buildSetContextMenuHtml(set)}
                </td>
                <td>
                    <a class="mod-list-name inventory-item-name text-decoration-none text-start"
                       href="/inventory/sets/${set.id}">
                        <i class="bi bi-collection me-2 text-muted"></i>
                        <span class="inventory-item-name-text" title="${this.escapeHtml(set.name)}">${this.escapeHtml(set.name)}</span>
                    </a>
                    <div class="d-md-none mt-1 text-muted small">${this.escapeHtml(this.productsLabel(set))}</div>
                </td>
                <td class="d-none d-md-table-cell text-muted">${this.escapeHtml(this.productsLabel(set))}</td>
                <td class="d-none d-lg-table-cell">${badge}</td>
                <td class="d-none d-xl-table-cell text-muted text-truncate" style="max-width: 18rem;" title="${description}">${description}</td>
                <td class="text-end">
                    <div class="mod-list-actions">
                        <div class="mod-list-hover-actions">
                            <a class="btn btn-sm btn-link" href="/inventory/sets/${set.id}" title="${this.escapeHtml(this.t('view', 'Anzeigen'))}" onclick="event.stopPropagation()">
                                <i class="bi bi-eye"></i>
                            </a>
                            ${hoverBorrow}
                            ${hoverEdit}
                        </div>
                        <div class="dropdown d-inline-block">
                            <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}' aria-expanded="false" onclick="event.stopPropagation()">
                                <i class="bi bi-three-dots-vertical"></i>
                            </button>
                            <ul class="dropdown-menu dropdown-menu-end inventory-actions-menu">
                                <li><a class="dropdown-item" href="/inventory/sets/${set.id}"><i class="bi bi-eye me-2"></i>${this.escapeHtml(this.t('view', 'Anzeigen'))}</a></li>
                                ${canBorrow ? `<li><a class="dropdown-item" href="/inventory/sets/${set.id}/borrow"><i class="bi bi-cart-check me-2"></i>${this.escapeHtml(this.t('borrow', 'Ausleihen'))}</a></li>` : ''}
                                ${canEdit ? `<li><a class="dropdown-item" href="/inventory/sets/${set.id}/edit"><i class="bi bi-pencil me-2"></i>${this.escapeHtml(this.t('edit', 'Bearbeiten'))}</a></li>` : ''}
                            </ul>
                        </div>
                    </div>
                </td>
            </tr>
        `;
    }

    attachCheckboxHandlers() {
        document.querySelectorAll('.set-checkbox').forEach((checkbox) => {
            const setId = parseInt(checkbox.dataset.setId, 10);
            checkbox.checked = this.selectedSets.has(setId);
            this.updateCardSelection(setId);

            checkbox.onchange = (e) => {
                e.stopPropagation();
                const id = parseInt(e.target.dataset.setId, 10);
                if (e.target.checked) {
                    this.selectedSets.add(id);
                } else {
                    this.selectedSets.delete(id);
                }
                this.updateCardSelection(id);
                this.updateSelectionUI();
            };

            checkbox.onclick = (e) => e.stopPropagation();
        });
    }

    updateCardSelection(setId) {
        const checkbox = document.querySelector(`.set-checkbox[data-set-id="${setId}"]`);
        if (!checkbox) return;

        const isSelected = this.selectedSets.has(setId);
        checkbox.checked = isSelected;

        const card = checkbox.closest('.product-card, .inventory-set-card');
        if (card) {
            card.classList.toggle('selection-mode', isSelected);
        }
        const listRow = checkbox.closest('.mod-list-row');
        if (listRow) {
            listRow.classList.toggle('selection-mode', isSelected);
        }
    }

    handleCardClick(setId) {
        if (this.selectedSets.size > 0) {
            this.toggleSetSelection(setId);
            return;
        }
        window.location.href = `/inventory/sets/${setId}`;
    }

    toggleSetSelection(setId) {
        if (this.selectedSets.has(setId)) {
            this.selectedSets.delete(setId);
        } else {
            this.selectedSets.add(setId);
        }
        this.updateCardSelection(setId);
        this.updateSelectionUI();
    }

    selectAll() {
        this.filteredSets.forEach((set) => this.selectedSets.add(set.id));
        document.querySelectorAll('.set-checkbox').forEach((cb) => {
            const id = parseInt(cb.dataset.setId, 10);
            cb.checked = this.selectedSets.has(id);
            this.updateCardSelection(id);
        });
        this.updateSelectionUI();
    }

    deselectAll() {
        this.selectedSets.clear();
        document.querySelectorAll('.set-checkbox').forEach((cb) => {
            const id = parseInt(cb.dataset.setId, 10);
            cb.checked = false;
            this.updateCardSelection(id);
        });
        this.updateSelectionUI();
    }

    getSelectedIds() {
        return Array.from(this.selectedSets);
    }

    updateSelectionUI() {
        const selected = this.getSelectedIds();
        const bulkToolbar = document.getElementById('bulkSelectionToolbar');
        const bulkSelectionCount = document.getElementById('bulkSelectionCount');

        if (bulkToolbar) {
            bulkToolbar.style.display = selected.length > 0 ? 'block' : 'none';
        }
        if (bulkSelectionCount) {
            bulkSelectionCount.textContent = String(selected.length);
        }

        document.querySelectorAll('.set-checkbox').forEach((cb) => {
            const id = parseInt(cb.dataset.setId, 10);
            this.updateCardSelection(id);
        });
    }

    async borrowSelected() {
        const selectedIds = this.getSelectedIds();
        if (selectedIds.length === 0) {
            setsNotify(this.t('noneSelected', 'Bitte mindestens ein Set auswählen.'), 'warning');
            return;
        }
        if (!this.canBorrow) {
            setsNotify(this.t('noBorrowPermission', 'Keine Berechtigung zum Ausleihen.'), 'danger');
            return;
        }

        const selectedSets = this.sets.filter((s) => selectedIds.includes(s.id));
        const borrowable = selectedSets.filter((s) => Number(s.available_count || 0) > 0);
        if (borrowable.length === 0) {
            setsNotify(this.t('borrowNoneAvailable', 'In den ausgewählten Sets sind keine verfügbaren Produkte.'), 'warning');
            return;
        }

        try {
            const response = await fetch('/inventory/api/sets/bulk-borrow', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ set_ids: selectedIds }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || this.t('loadError', 'Fehler beim Ausleihen'));
            }
            if (data.redirect) {
                window.location.href = data.redirect;
                return;
            }
            window.location.href = '/inventory/borrow-scanner';
        } catch (error) {
            setsNotify(error.message || this.t('loadError', 'Fehler beim Ausleihen'), 'danger');
        }
    }

    editSelected() {
        const selectedIds = this.getSelectedIds();
        if (selectedIds.length === 0) {
            setsNotify(this.t('noneSelected', 'Bitte mindestens ein Set auswählen.'), 'warning');
            return;
        }
        if (selectedIds.length > 1) {
            setsNotify(this.t('editSingleOnly', 'Zum Bearbeiten bitte genau ein Set auswählen.'), 'warning');
            return;
        }

        const set = this.sets.find((s) => s.id === selectedIds[0]);
        if (!set || !this.canEditSet(set)) {
            setsNotify(this.t('noEditPermission', 'Keine Berechtigung zum Bearbeiten.'), 'danger');
            return;
        }
        window.location.href = `/inventory/sets/${selectedIds[0]}/edit`;
    }

    openBulkDeleteModal() {
        const selectedIds = this.getSelectedIds();
        if (selectedIds.length === 0) {
            setsNotify(this.t('noneSelected', 'Bitte mindestens ein Set auswählen.'), 'warning');
            return;
        }

        const forbidden = selectedIds.some((id) => {
            const set = this.sets.find((s) => s.id === id);
            return !this.canDeleteSet(set);
        });
        if (forbidden) {
            setsNotify(this.t('noDeletePermission', 'Keine Berechtigung zum Löschen aller ausgewählten Sets.'), 'danger');
            return;
        }

        const modalEl = document.getElementById('bulkDeleteModal');
        if (!modalEl) return;

        const countEl = document.getElementById('bulkDeleteSetCount');
        if (countEl) countEl.textContent = String(selectedIds.length);

        const confirmBtn = document.getElementById('bulkDeleteConfirmBtn');
        if (confirmBtn) {
            confirmBtn.onclick = () => this.confirmBulkDelete(selectedIds);
        }

        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }

    async confirmBulkDelete(setIds) {
        const confirmBtn = document.getElementById('bulkDeleteConfirmBtn');
        const originalText = confirmBtn ? confirmBtn.innerHTML : '';
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>${this.escapeHtml(this.t('deleteConfirming', 'Löschen...'))}`;
        }

        try {
            const response = await fetch('/inventory/api/sets/bulk-delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ set_ids: setIds }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || this.t('loadError', 'Fehler beim Löschen'));
            }

            const modalEl = document.getElementById('bulkDeleteModal');
            if (modalEl) {
                const modal = bootstrap.Modal.getInstance(modalEl);
                if (modal) modal.hide();
            }

            setsNotify(data.message || `${data.deleted_count || setIds.length} Set(s) gelöscht.`, 'success');
            this.selectedSets.clear();
            await this.loadSets();
        } catch (error) {
            setsNotify(error.message || this.t('loadError', 'Fehler beim Löschen'), 'danger');
        } finally {
            if (confirmBtn) {
                confirmBtn.disabled = false;
                confirmBtn.innerHTML = originalText;
            }
        }
    }
}

window.SetsManager = SetsManager;
