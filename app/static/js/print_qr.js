(function () {
    'use strict';

    const cfg = window.PrintQrConfig || {};
    const i18n = cfg.i18n || {};
    const SETS_FOLDER_ID = cfg.setsFolderId || '__sets__';

    class PrintQrManager {
        constructor() {
            this.products = Array.isArray(cfg.products) ? cfg.products : [];
            this.folders = Array.isArray(cfg.folders) ? cfg.folders : [];
            this.sets = Array.isArray(cfg.sets) ? cfg.sets : [];
            this.selected = new Set();
            this.selectedSets = new Set();
            this.currentFolderId = null; // null = root, number = product folder, SETS_FOLDER_ID = sets
            this.viewMode = localStorage.getItem('inventoryViewMode') || 'list';
            this.searchQuery = '';
            this.searchTimeout = null;

            this.els = {
                backRow: document.getElementById('qrBackRow'),
                backBtn: document.getElementById('qrBackBtn'),
                folderTitle: document.getElementById('qrFolderTitle'),
                bulkBar: document.getElementById('qrBulkBar'),
                selectedCount: document.getElementById('qrSelectedCount'),
                selectAllBtn: document.getElementById('qrSelectAllBtn'),
                selectVisibleBtn: document.getElementById('qrSelectVisibleBtn'),
                generateBtn: document.getElementById('qrGeneratePdfBtn'),
                form: document.getElementById('qrPrintForm'),
                labelType: document.getElementById('qrLabelTypeInput'),
                gridView: document.getElementById('qrGridView'),
                gridContainer: document.getElementById('qrGridContainer'),
                listView: document.getElementById('qrListView'),
                listBody: document.getElementById('qrListBody'),
                emptyState: document.getElementById('qrEmptyState'),
                emptyText: document.getElementById('qrEmptyText'),
                searchDesktop: document.getElementById('qrSearchInput'),
                searchMobile: document.getElementById('qrSearchInputMobile'),
            };

            this.bindEvents();
            this.applyViewMode();
            this.render();
        }

        isSetsFolderId(folderId) {
            return String(folderId) === String(SETS_FOLDER_ID);
        }

        isSetsView() {
            return this.isSetsFolderId(this.currentFolderId);
        }

        bindEvents() {
            const bindToggle = (listBtn, gridBtn) => {
                if (!listBtn || !gridBtn) return;
                listBtn.addEventListener('click', () => this.setViewMode('list'));
                gridBtn.addEventListener('click', () => this.setViewMode('grid'));
            };
            bindToggle(document.getElementById('listViewBtn'), document.getElementById('gridViewBtn'));
            bindToggle(document.getElementById('listViewBtnMobile'), document.getElementById('gridViewBtnMobile'));

            const onSearch = (el) => {
                if (!el) return;
                el.addEventListener('input', () => {
                    clearTimeout(this.searchTimeout);
                    this.searchTimeout = setTimeout(() => {
                        this.searchQuery = (el.value || '').trim();
                        if (this.els.searchDesktop && this.els.searchDesktop !== el) {
                            this.els.searchDesktop.value = el.value;
                        }
                        if (this.els.searchMobile && this.els.searchMobile !== el) {
                            this.els.searchMobile.value = el.value;
                        }
                        this.render();
                    }, 200);
                });
            };
            onSearch(this.els.searchDesktop);
            onSearch(this.els.searchMobile);

            if (this.els.backBtn) {
                this.els.backBtn.addEventListener('click', () => {
                    this.currentFolderId = null;
                    this.render();
                });
            }

            this.els.selectAllBtn?.addEventListener('click', () => {
                if (this.areAllSelected()) this.deselectAll();
                else this.selectAll();
            });
            this.els.selectVisibleBtn?.addEventListener('click', () => {
                if (this.areVisibleSelected()) this.deselectVisible();
                else this.selectVisible();
            });

            document.querySelectorAll('.qr-pdf-type-option').forEach((btn) => {
                btn.addEventListener('click', () => this.submitPdf(btn.dataset.labelType || 'cable'));
            });

            document.addEventListener('change', (event) => {
                const folderCb = event.target.closest('.qr-folder-checkbox');
                if (folderCb) {
                    const raw = folderCb.value;
                    this.setFolderSelected(raw, folderCb.checked);
                    return;
                }

                const setCb = event.target.closest('.qr-set-checkbox');
                if (setCb) {
                    const id = Number(setCb.value);
                    if (!Number.isFinite(id)) return;
                    if (setCb.checked) this.selectedSets.add(id);
                    else this.selectedSets.delete(id);
                    this.updateSelectionUi();
                    this.syncSelectionClasses();
                    return;
                }

                const cb = event.target.closest('.qr-product-checkbox');
                if (!cb) return;
                const id = Number(cb.value);
                if (!Number.isFinite(id)) return;
                if (cb.checked) this.selected.add(id);
                else this.selected.delete(id);
                this.updateSelectionUi();
                this.syncSelectionClasses();
            });

            document.addEventListener('click', (event) => {
                const openBtn = event.target.closest('[data-qr-open-folder]');
                if (openBtn) {
                    event.preventDefault();
                    event.stopPropagation();
                    this.openFolder(openBtn.getAttribute('data-qr-open-folder'));
                    return;
                }

                const folderCard = event.target.closest('[data-qr-folder]');
                if (folderCard) {
                    if (event.target.closest('input, button, a, label, .qr-folder-check-wrap')) return;
                    this.openFolder(folderCard.getAttribute('data-qr-folder'));
                    return;
                }

                const setCard = event.target.closest('[data-qr-toggle-set]');
                if (setCard) {
                    if (event.target.closest('input, button, a, label')) return;
                    const id = Number(setCard.getAttribute('data-qr-toggle-set'));
                    if (Number.isFinite(id)) this.toggleSet(id);
                    return;
                }

                const productCard = event.target.closest('[data-qr-toggle-product]');
                if (!productCard) return;
                if (event.target.closest('input, button, a, label')) return;
                const id = Number(productCard.getAttribute('data-qr-toggle-product'));
                if (!Number.isFinite(id)) return;
                this.toggleProduct(id);
            });

            document.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter' && event.key !== ' ') return;
                if (event.target.closest('input, button, a, textarea')) return;

                const folderEl = event.target.closest('[data-qr-folder]');
                if (folderEl) {
                    event.preventDefault();
                    const folderId = folderEl.getAttribute('data-qr-folder');
                    if (event.key === ' ') this.toggleFolder(folderId);
                    else this.openFolder(folderId);
                    return;
                }

                const setEl = event.target.closest('[data-qr-toggle-set]');
                if (setEl) {
                    event.preventDefault();
                    const id = Number(setEl.getAttribute('data-qr-toggle-set'));
                    if (Number.isFinite(id)) this.toggleSet(id);
                    return;
                }

                const productEl = event.target.closest('[data-qr-toggle-product]');
                if (productEl) {
                    event.preventDefault();
                    const id = Number(productEl.getAttribute('data-qr-toggle-product'));
                    if (Number.isFinite(id)) this.toggleProduct(id);
                }
            });
        }

        setViewMode(mode) {
            this.viewMode = mode === 'grid' ? 'grid' : 'list';
            localStorage.setItem('inventoryViewMode', this.viewMode);
            this.applyViewMode();
            this.render();
        }

        applyViewMode() {
            const isList = this.viewMode === 'list';
            [
                document.getElementById('listViewBtn'),
                document.getElementById('listViewBtnMobile'),
            ].forEach((btn) => btn?.classList.toggle('active', isList));
            [
                document.getElementById('gridViewBtn'),
                document.getElementById('gridViewBtnMobile'),
            ].forEach((btn) => btn?.classList.toggle('active', !isList));
        }

        escapeHtml(value) {
            return String(value ?? '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        statusLabel(status) {
            const map = {
                available: i18n.available,
                borrowed: i18n.borrowed,
                missing: i18n.missing,
                defective: i18n.defective,
                in_repair: i18n.inRepair,
                retired: i18n.retired,
            };
            return map[status] || status || '—';
        }

        statusBadgeClass(status) {
            if (status === 'available') return 'bg-success';
            if (status === 'borrowed') return 'bg-warning text-dark';
            if (status === 'in_repair') return 'bg-info text-dark';
            if (status === 'defective' || status === 'missing') return 'bg-danger';
            return 'bg-secondary';
        }

        matchesSearch(item) {
            const q = this.searchQuery.toLowerCase();
            if (!q) return true;
            const hay = [
                item.name,
                item.serial_number,
                item.category,
                item.length,
                item.location,
                item.description,
            ].join(' ').toLowerCase();
            return hay.includes(q);
        }

        getSetsVirtualFolder() {
            return {
                id: SETS_FOLDER_ID,
                name: i18n.setsFolder || 'Sets',
                color: '#0d6efd',
                product_count: this.sets.length,
                is_sets: true,
            };
        }

        getVisibleFolders() {
            if (this.searchQuery || this.currentFolderId !== null) return [];
            const real = this.folders.slice().sort((a, b) => String(a.name).localeCompare(String(b.name), 'de'));
            return [this.getSetsVirtualFolder(), ...real];
        }

        getVisibleProducts() {
            if (this.isSetsView() && !this.searchQuery) return [];
            let list = this.products.slice();
            if (this.searchQuery) {
                list = list.filter((p) => this.matchesSearch(p));
            } else if (this.currentFolderId === null) {
                list = list.filter((p) => p.folder_id == null);
            } else {
                list = list.filter((p) => Number(p.folder_id) === Number(this.currentFolderId));
            }
            return list.sort((a, b) => String(a.name).localeCompare(String(b.name), 'de'));
        }

        getVisibleSets() {
            if (this.searchQuery) {
                return this.sets
                    .filter((s) => this.matchesSearch(s))
                    .sort((a, b) => String(a.name).localeCompare(String(b.name), 'de'));
            }
            if (!this.isSetsView()) return [];
            return this.sets.slice().sort((a, b) => String(a.name).localeCompare(String(b.name), 'de'));
        }

        productsInFolder(folderId) {
            if (this.isSetsFolderId(folderId)) return [];
            return this.products.filter((p) => Number(p.folder_id) === Number(folderId));
        }

        isFolderFullySelected(folderId) {
            if (this.isSetsFolderId(folderId)) {
                if (this.sets.length === 0) return false;
                return this.sets.every((s) => this.selectedSets.has(Number(s.id)));
            }
            const items = this.productsInFolder(folderId);
            if (items.length === 0) return false;
            return items.every((p) => this.selected.has(Number(p.id)));
        }

        isFolderPartiallySelected(folderId) {
            if (this.isSetsFolderId(folderId)) {
                if (this.sets.length === 0) return false;
                const selectedCount = this.sets.filter((s) => this.selectedSets.has(Number(s.id))).length;
                return selectedCount > 0 && selectedCount < this.sets.length;
            }
            const items = this.productsInFolder(folderId);
            if (items.length === 0) return false;
            const selectedCount = items.filter((p) => this.selected.has(Number(p.id))).length;
            return selectedCount > 0 && selectedCount < items.length;
        }

        currentFolder() {
            if (this.currentFolderId == null) return null;
            if (this.isSetsView()) return this.getSetsVirtualFolder();
            return this.folders.find((f) => Number(f.id) === Number(this.currentFolderId)) || null;
        }

        openFolder(folderId) {
            if (this.isSetsFolderId(folderId)) {
                this.currentFolderId = SETS_FOLDER_ID;
            } else {
                const id = Number(folderId);
                if (!Number.isFinite(id)) return;
                this.currentFolderId = id;
            }
            this.render();
        }

        toggleProduct(id) {
            if (this.selected.has(id)) this.selected.delete(id);
            else this.selected.add(id);
            this.updateSelectionUi();
            this.syncSelectionClasses();
        }

        toggleSet(id) {
            if (this.selectedSets.has(id)) this.selectedSets.delete(id);
            else this.selectedSets.add(id);
            this.updateSelectionUi();
            this.syncSelectionClasses();
        }

        setFolderSelected(folderId, selected) {
            if (this.isSetsFolderId(folderId)) {
                this.sets.forEach((s) => {
                    const id = Number(s.id);
                    if (selected) this.selectedSets.add(id);
                    else this.selectedSets.delete(id);
                });
            } else {
                this.productsInFolder(folderId).forEach((p) => {
                    const id = Number(p.id);
                    if (selected) this.selected.add(id);
                    else this.selected.delete(id);
                });
            }
            this.updateSelectionUi();
            this.syncSelectionClasses();
        }

        toggleFolder(folderId) {
            this.setFolderSelected(folderId, !this.isFolderFullySelected(folderId));
        }

        getVisibleProductIds() {
            const ids = new Set();
            this.getVisibleProducts().forEach((p) => ids.add(Number(p.id)));
            this.getVisibleFolders().forEach((folder) => {
                if (this.isSetsFolderId(folder.id)) return;
                this.productsInFolder(folder.id).forEach((p) => ids.add(Number(p.id)));
            });
            return ids;
        }

        getVisibleSetIds() {
            const ids = new Set();
            this.getVisibleSets().forEach((s) => ids.add(Number(s.id)));
            this.getVisibleFolders().forEach((folder) => {
                if (!this.isSetsFolderId(folder.id)) return;
                this.sets.forEach((s) => ids.add(Number(s.id)));
            });
            return ids;
        }

        selectionCount() {
            return this.selected.size + this.selectedSets.size;
        }

        areAllSelected() {
            const hasItems = this.products.length > 0 || this.sets.length > 0;
            if (!hasItems) return false;
            const productsOk = this.products.every((p) => this.selected.has(Number(p.id)));
            const setsOk = this.sets.every((s) => this.selectedSets.has(Number(s.id)));
            return productsOk && setsOk;
        }

        areVisibleSelected() {
            const productIds = this.getVisibleProductIds();
            const setIds = this.getVisibleSetIds();
            if (productIds.size === 0 && setIds.size === 0) return false;
            for (const id of productIds) {
                if (!this.selected.has(id)) return false;
            }
            for (const id of setIds) {
                if (!this.selectedSets.has(id)) return false;
            }
            return true;
        }

        selectAll() {
            this.products.forEach((p) => this.selected.add(Number(p.id)));
            this.sets.forEach((s) => this.selectedSets.add(Number(s.id)));
            this.render();
        }

        selectVisible() {
            this.getVisibleProductIds().forEach((id) => this.selected.add(id));
            this.getVisibleSetIds().forEach((id) => this.selectedSets.add(id));
            this.render();
        }

        deselectVisible() {
            this.getVisibleProductIds().forEach((id) => this.selected.delete(id));
            this.getVisibleSetIds().forEach((id) => this.selectedSets.delete(id));
            this.render();
        }

        deselectAll() {
            this.selected.clear();
            this.selectedSets.clear();
            this.render();
        }

        updateSelectionUi() {
            const count = this.selectionCount();
            if (this.els.selectedCount) this.els.selectedCount.textContent = String(count);
            if (this.els.generateBtn) {
                this.els.generateBtn.disabled = count === 0;
                this.els.generateBtn.setAttribute('aria-disabled', count === 0 ? 'true' : 'false');
            }
            this.updateToggleButtons();
        }

        updateToggleButtons() {
            const allOn = this.areAllSelected();
            const visibleOn = this.areVisibleSelected();

            const allBtn = this.els.selectAllBtn;
            if (allBtn) {
                const label = allOn
                    ? (i18n.deselectAll || 'Alle abwählen')
                    : (i18n.selectAll || 'Alle auswählen');
                const icon = allOn ? 'bi-x-square' : 'bi-check2-all';
                allBtn.dataset.mode = allOn ? 'deselect' : 'select';
                allBtn.title = label;
                allBtn.classList.toggle('inventory-pill-btn--outline-muted', allOn);
                allBtn.classList.toggle('inventory-pill-btn--outline', !allOn);
                const iconEl = allBtn.querySelector('i');
                const labelEl = allBtn.querySelector('.qr-select-all-label');
                if (iconEl) iconEl.className = `bi ${icon}`;
                if (labelEl) labelEl.textContent = label;
            }

            const visibleBtn = this.els.selectVisibleBtn;
            if (visibleBtn) {
                const label = visibleOn
                    ? (i18n.deselectVisible || 'Sichtbare abwählen')
                    : (i18n.selectVisible || 'Sichtbare auswählen');
                const icon = visibleOn ? 'bi-square' : 'bi-check-square';
                visibleBtn.dataset.mode = visibleOn ? 'deselect' : 'select';
                visibleBtn.title = label;
                visibleBtn.classList.toggle('inventory-pill-btn--outline-muted', visibleOn);
                visibleBtn.classList.toggle('inventory-pill-btn--outline', !visibleOn);
                const iconEl = visibleBtn.querySelector('i');
                const labelEl = visibleBtn.querySelector('.qr-select-visible-label');
                if (iconEl) iconEl.className = `bi ${icon}`;
                if (labelEl) labelEl.textContent = label;
            }
        }

        syncSelectionClasses() {
            document.querySelectorAll('[data-qr-toggle-product]').forEach((el) => {
                const id = Number(el.getAttribute('data-qr-toggle-product'));
                const on = this.selected.has(id);
                el.classList.toggle('selection-mode', on);
                el.classList.toggle('is-checked', on);
                const cb = el.querySelector('.qr-product-checkbox');
                if (cb) cb.checked = on;
            });

            document.querySelectorAll('[data-qr-toggle-set]').forEach((el) => {
                const id = Number(el.getAttribute('data-qr-toggle-set'));
                const on = this.selectedSets.has(id);
                el.classList.toggle('selection-mode', on);
                el.classList.toggle('is-checked', on);
                const cb = el.querySelector('.qr-set-checkbox');
                if (cb) cb.checked = on;
            });

            document.querySelectorAll('[data-qr-folder]').forEach((el) => {
                const folderId = el.getAttribute('data-qr-folder');
                const full = this.isFolderFullySelected(folderId);
                const partial = this.isFolderPartiallySelected(folderId);
                el.classList.toggle('selection-mode', full || partial);
                el.classList.toggle('is-checked', full);
                const cb = el.querySelector('.qr-folder-checkbox');
                if (cb) {
                    cb.checked = full;
                    cb.indeterminate = partial;
                }
            });
        }

        submitPdf(labelType) {
            if (this.selectionCount() === 0) {
                if (window.showAppBanner) window.showAppBanner(i18n.noSelection || 'Bitte wählen Sie mindestens ein Produkt aus.', 'warning');
                return;
            }
            if (!this.els.form || !this.els.labelType) return;

            this.els.form.querySelectorAll('input[name="product_ids"], input[name="set_ids"]').forEach((el) => el.remove());
            this.selected.forEach((id) => {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'product_ids';
                input.value = String(id);
                this.els.form.appendChild(input);
            });
            this.selectedSets.forEach((id) => {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'set_ids';
                input.value = String(id);
                this.els.form.appendChild(input);
            });
            this.els.labelType.value = labelType;
            this.els.form.submit();
        }

        productsCountLabel(count) {
            const template = i18n.productsCount || '{count} Produkte';
            return template.replace('{count}', String(count));
        }

        setsCountLabel(count) {
            const template = i18n.setsCount || '{count} Sets';
            return template.replace('{count}', String(count));
        }

        renderFolderCard(folder) {
            const isSets = this.isSetsFolderId(folder.id);
            const colorStyle = folder.color ? `style="color: ${this.escapeHtml(folder.color)};"` : '';
            const colorClass = folder.color ? '' : 'text-warning';
            const icon = isSets ? 'bi-collection-fill' : 'bi-folder-fill';
            const full = this.isFolderFullySelected(folder.id);
            const partial = this.isFolderPartiallySelected(folder.id);
            const selectLabel = i18n.selectFolder || 'Ordner auswählen';
            const countLabel = isSets
                ? this.setsCountLabel(folder.product_count || 0)
                : this.productsCountLabel(folder.product_count || 0);
            return `
                <div class="col-12 col-md-6 col-lg-3">
                    <div class="card inventory-folder-card h-100 ${full || partial ? 'selection-mode' : ''} ${full ? 'is-checked' : ''}"
                         data-qr-folder="${this.escapeHtml(String(folder.id))}" role="button" tabindex="0" style="cursor: pointer;">
                        <div class="card-body">
                            <div class="d-flex justify-content-between align-items-start gap-2">
                                <div class="min-width-0 flex-grow-1">
                                    <div class="d-flex align-items-start gap-2">
                                        <div class="pt-1 qr-folder-check-wrap" onclick="event.stopPropagation()">
                                            <input type="checkbox" class="form-check-input qr-folder-checkbox"
                                                   value="${this.escapeHtml(String(folder.id))}" ${full ? 'checked' : ''}
                                                   aria-label="${this.escapeHtml(selectLabel)}: ${this.escapeHtml(folder.name)}">
                                        </div>
                                        <div class="min-width-0">
                                            <i class="bi ${icon} fs-1 folder-color-icon ${colorClass}" ${colorStyle}></i>
                                            <h6 class="mt-2 mb-0 text-truncate" title="${this.escapeHtml(folder.name)}">${this.escapeHtml(folder.name)}</h6>
                                            <small class="text-muted">${countLabel}</small>
                                        </div>
                                    </div>
                                </div>
                                <div class="inventory-grid-hover-actions">
                                    <button type="button" class="btn btn-sm btn-link" title="${this.escapeHtml(i18n.openFolder || 'Öffnen')}"
                                            data-qr-open-folder="${this.escapeHtml(String(folder.id))}">
                                        <i class="bi bi-folder2-open"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        renderFolderListItem(folder) {
            const isSets = this.isSetsFolderId(folder.id);
            const colorStyle = folder.color ? `style="color: ${this.escapeHtml(folder.color)};"` : '';
            const colorClass = folder.color ? '' : 'text-warning';
            const icon = isSets ? 'bi-collection-fill' : 'bi-folder-fill';
            const full = this.isFolderFullySelected(folder.id);
            const partial = this.isFolderPartiallySelected(folder.id);
            const selectLabel = i18n.selectFolder || 'Ordner auswählen';
            const countLabel = isSets
                ? this.setsCountLabel(folder.product_count || 0)
                : this.productsCountLabel(folder.product_count || 0);
            return `
                <tr class="mod-list-row inventory-folder-row ${full || partial ? 'selection-mode' : ''} ${full ? 'is-checked' : ''}"
                    data-qr-folder="${this.escapeHtml(String(folder.id))}" role="button" tabindex="0" style="cursor: pointer;">
                    <td class="inventory-list-check-col qr-folder-check-wrap" onclick="event.stopPropagation()">
                        <input type="checkbox" class="form-check-input qr-folder-checkbox"
                               value="${this.escapeHtml(String(folder.id))}" ${full ? 'checked' : ''}
                               aria-label="${this.escapeHtml(selectLabel)}: ${this.escapeHtml(folder.name)}">
                    </td>
                    <td>
                        <span class="mod-list-name inventory-item-name">
                            <i class="bi ${icon} me-2 folder-color-icon ${colorClass}" ${colorStyle}></i>
                            <span class="inventory-item-name-text" title="${this.escapeHtml(folder.name)}">${this.escapeHtml(folder.name)}</span>
                        </span>
                    </td>
                    <td class="d-none d-md-table-cell text-muted">${countLabel}</td>
                    <td class="d-none d-md-table-cell text-muted">—</td>
                    <td class="d-none d-lg-table-cell text-muted">—</td>
                    <td class="d-none d-xl-table-cell text-end">
                        <button type="button" class="btn btn-sm btn-link" title="${this.escapeHtml(i18n.openFolder || 'Öffnen')}"
                                data-qr-open-folder="${this.escapeHtml(String(folder.id))}">
                            <i class="bi bi-folder2-open"></i>
                        </button>
                    </td>
                </tr>
            `;
        }

        productPreview(product) {
            if (product.image_path) {
                return `
                    <img src="/inventory/product-images/${this.escapeHtml(product.image_path)}"
                         alt="${this.escapeHtml(product.name)}"
                         class="inventory-product-preview-img image-mini-preview img-fluid rounded"
                         onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                    <div class="inventory-product-preview-fallback" style="display: none;"><i class="bi bi-box-seam"></i></div>
                `;
            }
            return `<div class="inventory-product-preview-fallback"><i class="bi bi-box-seam"></i></div>`;
        }

        renderProductCard(product) {
            const id = Number(product.id);
            const selected = this.selected.has(id);
            const badgeClass = this.statusBadgeClass(product.status);
            return `
                <div class="col-12 col-md-6 col-lg-4">
                    <div class="card h-100 inventory-product-card product-card ${selected ? 'selection-mode is-checked' : ''}"
                         data-qr-toggle-product="${id}" style="cursor: pointer;">
                        <div class="card-body d-flex flex-column">
                            <div class="inventory-product-preview text-center mb-3">
                                ${this.productPreview(product)}
                                <div class="inventory-product-preview-check" onclick="event.stopPropagation()">
                                    <input type="checkbox" class="form-check-input qr-product-checkbox"
                                           value="${id}" ${selected ? 'checked' : ''}
                                           aria-label="${this.escapeHtml(product.name)}">
                                </div>
                            </div>
                            <div class="min-width-0">
                                <div class="d-flex align-items-center gap-2 mb-1 min-width-0">
                                    <h6 class="card-title text-truncate mb-0" title="${this.escapeHtml(product.name)}">${this.escapeHtml(product.name)}</h6>
                                    <span class="badge ${badgeClass}">${this.escapeHtml(this.statusLabel(product.status))}</span>
                                </div>
                                ${product.category ? `<p class="inventory-card-meta mb-1 text-truncate"><i class="bi bi-tag"></i> ${this.escapeHtml(product.category)}</p>` : ''}
                                ${product.serial_number ? `<p class="inventory-card-meta mb-1 text-truncate"><i class="bi bi-upc"></i> ${this.escapeHtml(product.serial_number)}</p>` : ''}
                                ${product.length ? `<p class="inventory-card-meta mb-0 text-truncate"><i class="bi bi-rulers"></i> ${this.escapeHtml(product.length)}</p>` : ''}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        renderProductListItem(product) {
            const id = Number(product.id);
            const selected = this.selected.has(id);
            const badgeClass = this.statusBadgeClass(product.status);
            return `
                <tr class="mod-list-row ${selected ? 'selection-mode' : ''}" data-qr-toggle-product="${id}" style="cursor: pointer;">
                    <td class="inventory-list-check-col" onclick="event.stopPropagation()">
                        <input type="checkbox" class="form-check-input qr-product-checkbox"
                               value="${id}" ${selected ? 'checked' : ''}
                               aria-label="${this.escapeHtml(product.name)}">
                    </td>
                    <td>
                        <span class="mod-list-name inventory-item-name">
                            <span class="inventory-item-name-text" title="${this.escapeHtml(product.name)}">${this.escapeHtml(product.name)}</span>
                        </span>
                    </td>
                    <td class="d-none d-md-table-cell">
                        <span class="badge ${badgeClass}">${this.escapeHtml(this.statusLabel(product.status))}</span>
                    </td>
                    <td class="d-none d-md-table-cell text-muted">${product.category ? this.escapeHtml(product.category) : '—'}</td>
                    <td class="d-none d-lg-table-cell text-muted">${product.serial_number ? this.escapeHtml(product.serial_number) : '—'}</td>
                    <td class="d-none d-xl-table-cell text-muted">${product.length ? this.escapeHtml(product.length) : '—'}</td>
                </tr>
            `;
        }

        renderSetCard(setItem) {
            const id = Number(setItem.id);
            const selected = this.selectedSets.has(id);
            const setBadge = i18n.setBadge || 'Set';
            return `
                <div class="col-12 col-md-6 col-lg-4">
                    <div class="card h-100 inventory-product-card product-card ${selected ? 'selection-mode is-checked' : ''}"
                         data-qr-toggle-set="${id}" style="cursor: pointer;">
                        <div class="card-body d-flex flex-column">
                            <div class="inventory-product-preview text-center mb-3">
                                <div class="inventory-product-preview-fallback"><i class="bi bi-collection"></i></div>
                                <div class="inventory-product-preview-check" onclick="event.stopPropagation()">
                                    <input type="checkbox" class="form-check-input qr-set-checkbox"
                                           value="${id}" ${selected ? 'checked' : ''}
                                           aria-label="${this.escapeHtml(setItem.name)}">
                                </div>
                            </div>
                            <div class="min-width-0">
                                <div class="d-flex align-items-center gap-2 mb-1 min-width-0">
                                    <h6 class="card-title text-truncate mb-0" title="${this.escapeHtml(setItem.name)}">${this.escapeHtml(setItem.name)}</h6>
                                    <span class="badge bg-primary">${this.escapeHtml(setBadge)}</span>
                                </div>
                                <p class="inventory-card-meta mb-0 text-truncate">
                                    <i class="bi bi-qr-code"></i> SET-${id}
                                </p>
                                <p class="inventory-card-meta mb-0 text-truncate">
                                    <i class="bi bi-box-seam"></i> ${this.productsCountLabel(setItem.product_count || 0)}
                                </p>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        renderSetListItem(setItem) {
            const id = Number(setItem.id);
            const selected = this.selectedSets.has(id);
            const setBadge = i18n.setBadge || 'Set';
            return `
                <tr class="mod-list-row ${selected ? 'selection-mode' : ''}" data-qr-toggle-set="${id}" style="cursor: pointer;">
                    <td class="inventory-list-check-col" onclick="event.stopPropagation()">
                        <input type="checkbox" class="form-check-input qr-set-checkbox"
                               value="${id}" ${selected ? 'checked' : ''}
                               aria-label="${this.escapeHtml(setItem.name)}">
                    </td>
                    <td>
                        <span class="mod-list-name inventory-item-name">
                            <i class="bi bi-collection me-2 text-primary"></i>
                            <span class="inventory-item-name-text" title="${this.escapeHtml(setItem.name)}">${this.escapeHtml(setItem.name)}</span>
                        </span>
                    </td>
                    <td class="d-none d-md-table-cell">
                        <span class="badge bg-primary">${this.escapeHtml(setBadge)}</span>
                    </td>
                    <td class="d-none d-md-table-cell text-muted">${this.productsCountLabel(setItem.product_count || 0)}</td>
                    <td class="d-none d-lg-table-cell text-muted">SET-${id}</td>
                    <td class="d-none d-xl-table-cell text-muted">—</td>
                </tr>
            `;
        }

        render() {
            const folders = this.getVisibleFolders();
            const products = this.getVisibleProducts();
            const sets = this.getVisibleSets();
            const folder = this.currentFolder();
            const hasSearch = Boolean(this.searchQuery);

            if (this.els.backRow) {
                this.els.backRow.hidden = this.currentFolderId == null || hasSearch;
            }
            if (this.els.folderTitle) {
                this.els.folderTitle.textContent = folder ? folder.name : '';
            }

            const isEmpty = folders.length === 0 && products.length === 0 && sets.length === 0;
            if (this.els.emptyState) this.els.emptyState.hidden = !isEmpty;
            if (this.els.gridView) this.els.gridView.hidden = isEmpty || this.viewMode !== 'grid';
            if (this.els.listView) this.els.listView.hidden = isEmpty || this.viewMode !== 'list';

            if (this.els.emptyText) {
                if (hasSearch) this.els.emptyText.textContent = i18n.emptySearch || i18n.empty || 'Keine Treffer.';
                else if (this.isSetsView()) this.els.emptyText.textContent = i18n.emptySets || 'Keine Sets vorhanden.';
                else if (this.currentFolderId != null) this.els.emptyText.textContent = i18n.emptyFolder || i18n.empty || 'Ordner ist leer.';
                else this.els.emptyText.textContent = i18n.empty || 'Keine Produkte vorhanden.';
            }

            if (!isEmpty) {
                if (this.viewMode === 'grid' && this.els.gridContainer) {
                    this.els.gridContainer.innerHTML =
                        folders.map((f) => this.renderFolderCard(f)).join('') +
                        sets.map((s) => this.renderSetCard(s)).join('') +
                        products.map((p) => this.renderProductCard(p)).join('');
                }
                if (this.viewMode === 'list' && this.els.listBody) {
                    this.els.listBody.innerHTML =
                        folders.map((f) => this.renderFolderListItem(f)).join('') +
                        sets.map((s) => this.renderSetListItem(s)).join('') +
                        products.map((p) => this.renderProductListItem(p)).join('');
                }
            }

            this.updateSelectionUi();
            this.syncSelectionClasses();
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        window.printQrManager = new PrintQrManager();
    });
})();
