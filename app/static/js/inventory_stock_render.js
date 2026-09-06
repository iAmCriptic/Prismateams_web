/** Bestandsübersicht — Grid/List/Karten/Detail. */
/* global StockManager, inventoryNotify, fetchInventoryApi */

Object.assign(StockManager.prototype, {
    renderProducts() {
        if (this.viewMode === 'grid') {
            this.renderProductsGrid();
        } else {
            this.renderProductsList();
        }
    },

    getVisibleFolders() {
        const hasSearch = (this.getFilterValue('searchInput') || '').trim() !== '';
        if (hasSearch) return [];
        // Flat folders: nur im Root anzeigen
        if (this.currentFolderId !== null && this.currentFolderId !== undefined) return [];
        const folders = Array.isArray(this.folders) ? this.folders.slice() : [];
        // Papierkorb nicht als Grid-/Listen-Ordner, sondern als Footer in der Bestandsansicht
        if (!this.retiredFolderId) return folders;
        return folders.filter((folder) => Number(folder.id) !== Number(this.retiredFolderId));
    },

    updateTrashFooterCount() {
        const label = document.getElementById('inventoryTrashCountLabel');
        if (!label || !this.retiredFolderId) return;
        const count = (this.products || []).filter(
            (p) => Number(p.folder_id) === Number(this.retiredFolderId) || p.status === 'retired'
        ).length;
        label.textContent = count > 0
            ? `${count} Gerät${count === 1 ? '' : 'e'}`
            : 'Leer';
    },

    renderProductsGrid() {
        const container = document.getElementById('productsContainer');
        if (!container) return;

        const folders = this.getVisibleFolders();
        if (folders.length === 0 && this.filteredProducts.length === 0) {
            container.innerHTML = `
                <div class="col-12">
                    <div class="mod-empty-state">
                        <div>
                            <i class="bi bi-inbox display-6 d-block mb-2 opacity-50"></i>
                            Keine Produkte gefunden
                        </div>
                    </div>
                </div>
            `;
            return;
        }

        const folderHtml = folders.map((folder) => this.renderFolderCard(folder)).join('');
        const productHtml = this.filteredProducts.map((product) =>
            `<div class="col-12 col-md-6 col-lg-4">${this.renderProductCard(product)}</div>`
        ).join('');
        container.innerHTML = folderHtml + productHtml;
        
        this.attachCheckboxHandlers();
        
        if (typeof updateFavoriteButtons === 'function') {
            setTimeout(() => updateFavoriteButtons(), 100);
        }
    },

    renderProductsList() {
        const container = document.getElementById('productsList');
        if (!container) return;

        const folders = this.getVisibleFolders();
        if (folders.length === 0 && this.filteredProducts.length === 0) {
            container.innerHTML = `
                <tr>
                    <td colspan="7">
                        <div class="mod-empty-state">
                            <div>
                                <i class="bi bi-inbox display-6 d-block mb-2 opacity-50"></i>
                                Keine Produkte gefunden
                            </div>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        const folderHtml = folders.map((folder) => this.renderFolderListItem(folder)).join('');
        const productHtml = this.filteredProducts.map((product) => this.renderProductListItem(product)).join('');
        container.innerHTML = folderHtml + productHtml;
        
        this.attachCheckboxHandlers();
        
        if (typeof updateFavoriteButtons === 'function') {
            setTimeout(() => updateFavoriteButtons(), 100);
        }
    },

    /** Checkbox: alles außer ausgemustert. Ausleihen nur bei available. */

    isProductSelectable(product) {
        if (!product) return false;
        if (this.isRetiredFolderView) {
            return product.status === 'retired';
        }
        return product.status !== 'retired';
    },

    isProductBorrowable(product) {
        if (!product || product.status !== 'available') return false;
        if (product.item_type === 'consumable') {
            return Number(product.available || 0) > 0;
        }
        return true;
    },

    statusBadgeHtml(product) {
        if (product.status === 'available') {
            return '<span class="badge bg-success">Verfügbar</span>';
        }
        if (product.status === 'borrowed') {
            return '<span class="badge bg-warning">Ausgeliehen</span>';
        }
        if (product.status === 'missing') {
            return '<span class="badge bg-danger">Fehlend</span>';
        }
        if (product.status === 'defective' || product.status === 'in_repair') {
            return '<span class="badge bg-danger">Defekt</span>';
        }
        if (product.status === 'retired') {
            return '<span class="badge bg-secondary">Papierkorb</span>';
        }
        return `<span class="badge bg-secondary">${this.escapeHtml(product.status || '—')}</span>`;
    },

    renderProductListItem(product) {
        const statusBadge = this.statusBadgeHtml(product);
        const isSelected = this.selectedProducts.has(product.id);
        const isSelectable = this.isProductSelectable(product);
        const isBorrowable = this.isProductBorrowable(product);
        const checkboxTitle = isSelectable ? '' : ' title="Ausgemusterte Produkte lassen sich nicht auswählen"';
        const selectionModeClass = isSelected ? 'selection-mode' : '';
        const category = this.isValidValue(product.category) ? this.escapeHtml(product.category) : '—';
        const location = this.isValidValue(product.location) ? this.escapeHtml(product.location) : '—';
        const serial = this.isValidValue(product.serial_number) ? this.escapeHtml(product.serial_number) : '—';
        const qtyBadge = product.item_type === 'consumable'
            ? `<span class="badge bg-info-subtle text-dark ms-2">Bestand: ${this.escapeHtml(String(product.available ?? 0))}</span>`
            : '';

        const hoverBorrow = (!this.isRetiredFolderView && isBorrowable)
            ? `<a class="btn btn-sm btn-link" href="/inventory/products/${product.id}/borrow" title="Ausleihen" onclick="event.stopPropagation()"><i class="bi bi-cart-check"></i></a>`
            : '';

        const hoverEdit = this.isRetiredFolderView
            ? ''
            : `<a class="btn btn-sm btn-link" href="/inventory/products/${product.id}/edit" title="Bearbeiten" onclick="event.stopPropagation()">
                                <i class="bi bi-pencil"></i>
                            </a>`;
        const hoverFavorite = this.isRetiredFolderView
            ? ''
            : `<button type="button" class="btn btn-sm btn-link favorite-btn" data-product-id="${product.id}"
                                    title="Favorit" onclick="event.stopPropagation(); toggleFavorite(${product.id});">
                                <i class="bi bi-star"></i>
                            </button>`;
        const hoverRestore = this.isRetiredFolderView
            ? `<button type="button" class="btn btn-sm btn-link" title="Wieder in Betrieb nehmen"
                                    onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.restoreProduct(${product.id});}">
                                <i class="bi bi-arrow-counterclockwise"></i>
                            </button>`
            : '';

        return `
            <tr class="mod-list-row inventory-list-row-anim ${selectionModeClass}" data-product-id="${product.id}" data-context-zone data-context-menu="template" data-context-menu-id="context-menu-product-${product.id}">
                <td class="inventory-list-check-col">
                    <input type="checkbox" class="form-check-input product-checkbox"
                           value="${product.id}" data-product-id="${product.id}"
                           ${isSelected ? 'checked' : ''} ${isSelectable ? '' : 'disabled'}${checkboxTitle}
                           onclick="event.stopPropagation()">
                    ${this.buildProductContextMenuHtml(product)}
                </td>
                <td>
                    <button type="button" class="mod-list-name inventory-item-name text-decoration-none text-start border-0 bg-transparent p-0"
                            onclick="if(window.stockManager){window.stockManager.showProductDetail(${product.id});}">
                        <i class="bi bi-box-seam me-2 text-muted"></i><span class="inventory-item-name-text" title="${this.escapeHtml(product.name)}">${this.escapeHtml(product.name)}</span>${qtyBadge}
                    </button>
                    <div class="d-md-none mt-1">${statusBadge}</div>
                </td>
                <td class="d-none d-md-table-cell">${statusBadge}</td>
                <td class="d-none d-md-table-cell text-muted">${category}</td>
                <td class="d-none d-lg-table-cell text-muted">${location}</td>
                <td class="d-none d-xl-table-cell text-muted">${product.item_type === 'consumable' ? '—' : serial}</td>
                <td class="text-end">
                    <div class="mod-list-actions">
                        <div class="mod-list-hover-actions">
                            <button type="button" class="btn btn-sm btn-link" title="Ansehen"
                                    onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.showProductDetail(${product.id});}">
                                <i class="bi bi-eye"></i>
                            </button>
                            ${hoverBorrow}
                            ${hoverEdit}
                            ${hoverFavorite}
                            ${hoverRestore}
                        </div>
                        <div class="dropdown d-inline-block">
                            <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" data-bs-display="static" aria-expanded="false" onclick="event.stopPropagation()">
                                <i class="bi bi-three-dots-vertical"></i>
                            </button>
                            <ul class="dropdown-menu dropdown-menu-end inventory-actions-menu">
                                ${this.buildProductActionItemsHtml(product)}
                            </ul>
                        </div>
                    </div>
                </td>
            </tr>
        `;
    },

    buildProductActionItemsHtml(product) {
        const id = product.id;
        if (this.isRetiredFolderView || product.status === 'retired') {
            return `<li><button type="button" class="dropdown-item" onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.restoreProduct(${id});}"><i class="bi bi-arrow-counterclockwise me-2"></i>Wieder in Betrieb nehmen</button></li>`;
        }
        let items = '';
        items += `<li><button type="button" class="dropdown-item" onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.showProductDetail(${id});}"><i class="bi bi-eye me-2"></i>Ansehen</button></li>`;
        if (this.isProductBorrowable(product)) {
            items += `<li><a class="dropdown-item" href="/inventory/products/${id}/borrow"><i class="bi bi-cart-check me-2"></i>Ausleihen</a></li>`;
        }
        items += `<li><a class="dropdown-item" href="/inventory/products/${id}/edit"><i class="bi bi-pencil me-2"></i>Bearbeiten</a></li>`;
        items += `<li><a class="dropdown-item" href="/inventory/products/${id}/documents"><i class="bi bi-file-earmark me-2"></i>Dokumente</a></li>`;
        items += `<li><button type="button" class="dropdown-item" onclick="event.stopPropagation(); toggleFavorite(${id})"><i class="bi bi-star me-2"></i>Favorit</button></li>`;
        items += `<li><hr class="dropdown-divider"></li>`;
        if (product.status === 'available') {
            items += `<li><button type="button" class="dropdown-item" onclick="event.stopPropagation(); markAsInRepair(${id})"><i class="bi bi-tools me-2"></i>In Reparatur</button></li>`;
        }
        if (product.status === 'defective' || product.status === 'in_repair') {
            items += `<li><button type="button" class="dropdown-item" onclick="event.stopPropagation(); markAsAvailable(${id})"><i class="bi bi-check2-circle me-2"></i>Als einsatzbereit</button></li>`;
        }
        if (product.status !== 'defective' && product.status !== 'retired' && product.status !== 'in_repair') {
            items += `<li><button type="button" class="dropdown-item" onclick="event.stopPropagation(); markAsDefective(${id})"><i class="bi bi-exclamation-triangle me-2"></i>Als defekt markieren</button></li>`;
        }
        items += `<li><button type="button" class="dropdown-item text-danger" onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.deleteProduct(${id});}"><i class="bi bi-trash me-2"></i>Löschen</button></li>`;
        return items;
    },

    buildProductContextMenuHtml(product) {
        const id = product.id;
        return `<div class="context-menu-source d-none" id="context-menu-product-${id}"><ul class="dropdown-menu inventory-actions-menu">${this.buildProductActionItemsHtml(product)}</ul></div>`;
    },

    buildFolderContextMenuHtml(folder) {
        const id = folder.id;
        const name = this.escapeHtml(folder.name);
        return `<div class="context-menu-source d-none" id="context-menu-folder-${id}">
            <ul class="dropdown-menu inventory-actions-menu">
                <li><button type="button" class="dropdown-item" onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.navigateToFolder(${id});}"><i class="bi bi-folder2-open me-2"></i>Öffnen</button></li>
                <li><button type="button" class="dropdown-item" onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.startFolderInlineEdit(${id});}"><i class="bi bi-pencil me-2"></i>Umbenennen / Farbe</button></li>
                <li><a class="dropdown-item" href="/inventory/folders"><i class="bi bi-gear me-2"></i>Ordner verwalten</a></li>
                <li><hr class="dropdown-divider"></li>
                <li>
                    <form method="POST" action="/inventory/folders/${id}/delete" class="d-inline">
                        <button type="submit" class="dropdown-item text-danger"
                                data-confirm-delete="Ordner &quot;${name}&quot; wirklich löschen? Produkte bleiben erhalten.">
                            <i class="bi bi-trash me-2"></i>Löschen
                        </button>
                    </form>
                </li>
            </ul>
        </div>`;
    },

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    attachCheckboxHandlers() {
        // Event-Handler für alle Checkboxen setzen
        document.querySelectorAll('.product-checkbox').forEach(checkbox => {
            if (checkbox.disabled) {
                return;
            }
            // Stelle sicher, dass der checked-Status mit selectedProducts synchronisiert ist
            const productId = parseInt(checkbox.dataset.productId);
            checkbox.checked = this.selectedProducts.has(productId);
            this.updateCardSelection(productId);
            
            checkbox.addEventListener('change', (e) => {
                e.stopPropagation(); // Verhindere Card-Click
                const productId = parseInt(e.target.dataset.productId);
                if (e.target.checked) {
                    this.selectedProducts.add(productId);
                } else {
                    this.selectedProducts.delete(productId);
                }
                this.updateCardSelection(productId);
                this.updateSelectionUI();
            });
            
            // Verhindere Card-Click wenn Checkbox angeklickt wird
            checkbox.addEventListener('click', (e) => {
                e.stopPropagation();
            });
            
            // Verhindere auch Klicks auf den form-check Container (für List View)
            const formCheck = checkbox.closest('.form-check');
            if (formCheck) {
                formCheck.addEventListener('click', (e) => {
                    // Nur stoppen wenn direkt auf Checkbox oder Label geklickt wird
                    if (e.target === checkbox || e.target === formCheck.querySelector('label')) {
                        e.stopPropagation();
                    }
                });
            }
        });
    },

    updateCardSelection(productId) {
        // Aktualisiere die visuelle Darstellung einer einzelnen Karte
        const checkbox = document.querySelector(`.product-checkbox[data-product-id="${productId}"]`);
        if (!checkbox) return;
        
        const card = checkbox.closest('.product-card');
        if (!card) return;
        
        const isSelected = this.selectedProducts.has(productId);
        checkbox.checked = isSelected;
        
        if (card) {
            if (isSelected) {
                card.classList.add('selection-mode');
            } else {
                card.classList.remove('selection-mode');
            }
        }
        const listItem = checkbox.closest('.list-group-item');
        if (listItem) {
            if (isSelected) {
                listItem.classList.add('selection-mode');
            } else {
                listItem.classList.remove('selection-mode');
            }
        }
        const listRow = checkbox.closest('.mod-list-row');
        if (listRow) {
            if (isSelected) {
                listRow.classList.add('selection-mode');
            } else {
                listRow.classList.remove('selection-mode');
            }
        }
    },

    renderProductCard(product) {
        const statusBadge = this.statusBadgeHtml(product);
        const isSelected = this.selectedProducts.has(product.id);
        const isSelectable = this.isProductSelectable(product);
        const isBorrowable = this.isProductBorrowable(product);
        const checkboxTitle = isSelectable ? '' : ' title="Ausgemusterte Produkte lassen sich nicht auswählen"';
        const selectionModeClass = isSelected ? 'selection-mode' : '';
        const cardClickHandler = `onclick="if(window.stockManager){window.stockManager.handleCardClick(${product.id}, ${isSelectable});}"`;

        const preview = product.image_path
            ? `<img src="/inventory/product-images/${this.escapeHtml(product.image_path)}" alt="${this.escapeHtml(product.name)}" class="inventory-product-preview-img image-mini-preview img-fluid rounded" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
               <div class="inventory-product-preview-fallback" style="display: none;"><i class="bi bi-box-seam"></i></div>`
            : `<div class="inventory-product-preview-fallback"><i class="bi bi-box-seam"></i></div>`;

        const hoverBorrow = isBorrowable
            ? `<a class="btn btn-sm btn-link" href="/inventory/products/${product.id}/borrow" title="Ausleihen" onclick="event.stopPropagation()"><i class="bi bi-cart-check"></i></a>`
            : '';

        const quantityInfo = product.item_type === 'consumable'
            ? `<p class="inventory-card-meta mb-1 text-truncate"><i class="bi bi-boxes"></i> Bestand: ${this.escapeHtml(String(product.available ?? 0))}</p>`
            : '';
        return `
            <div class="card h-100 inventory-product-card product-card inv-item-anim ${selectionModeClass}" ${cardClickHandler} style="cursor: pointer;" data-context-zone data-context-menu="template" data-context-menu-id="context-menu-product-${product.id}">
                ${this.buildProductContextMenuHtml(product)}
                <div class="card-body d-flex flex-column">
                    <div class="inventory-product-preview text-center mb-3">
                        ${preview}
                        <div class="inventory-product-preview-check" onclick="event.stopPropagation()">
                            <input type="checkbox" class="form-check-input product-checkbox"
                                   value="${product.id}" data-product-id="${product.id}"
                                   ${isSelected ? 'checked' : ''} ${isSelectable ? '' : 'disabled'}${checkboxTitle}>
                        </div>
                    </div>
                    <div class="d-flex justify-content-between align-items-start gap-2">
                        <div class="flex-grow-1 min-width-0">
                            <div class="d-flex align-items-center gap-2 mb-1 min-width-0">
                                <h6 class="card-title text-truncate mb-0" title="${this.escapeHtml(product.name)}">${this.escapeHtml(product.name)}</h6>
                                ${statusBadge}
                            </div>
                            ${product.category ? `<p class="inventory-card-meta mb-1 text-truncate"><i class="bi bi-tag"></i> ${this.escapeHtml(product.category)}</p>` : ''}
                            ${quantityInfo}
                            ${this.isValidValue(product.serial_number) ? `<p class="inventory-card-meta mb-1 text-truncate"><i class="bi bi-upc"></i> ${this.escapeHtml(product.serial_number)}</p>` : ''}
                            ${this.isValidValue(product.location) ? `<p class="inventory-card-meta mb-0 text-truncate"><i class="bi bi-geo-alt"></i> ${this.escapeHtml(product.location)}</p>` : ''}
                        </div>
                        <div class="inventory-card-actions gap-1" onclick="event.stopPropagation()">
                            <div class="inventory-grid-hover-actions">
                                <button type="button" class="btn btn-sm btn-link favorite-btn" data-product-id="${product.id}"
                                        title="Favorit" onclick="event.stopPropagation(); toggleFavorite(${product.id});">
                                    <i class="bi bi-star"></i>
                                </button>
                                <button type="button" class="btn btn-sm btn-link" title="Ansehen"
                                        onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.showProductDetail(${product.id});}">
                                    <i class="bi bi-eye"></i>
                                </button>
                                ${hoverBorrow}
                                <a class="btn btn-sm btn-link" href="/inventory/products/${product.id}/edit" title="Bearbeiten" onclick="event.stopPropagation()">
                                    <i class="bi bi-pencil"></i>
                                </a>
                            </div>
                            <div class="dropdown inventory-card-menu">
                                <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" data-bs-display="static" aria-expanded="false">
                                    <i class="bi bi-three-dots-vertical"></i>
                                </button>
                                <ul class="dropdown-menu dropdown-menu-end inventory-actions-menu">
                                    ${this.buildProductActionItemsHtml(product)}
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    async showProductDetail(productId) {
        const product = this.products.find(p => p.id === productId);
        if (!product) {
            console.warn(`Produkt mit ID ${productId} nicht gefunden`);
            return;
        }

        const modalElement = document.getElementById('productDetailModal');
        if (!modalElement) {
            console.error('Modal-Element nicht gefunden');
            return;
        }

        if (modalElement.parentElement !== document.body) {
            document.body.appendChild(modalElement);
        }

        const modal = bootstrap.Modal.getOrCreateInstance(modalElement);
        const content = document.getElementById('productDetailContent');
        const val = (v) => (this.isValidValue(v) ? this.escapeHtml(String(v)) : '—');
        const statusBadge = this.statusBadgeHtml(product);
        const dguvLast = this.formatDateDe(product.dguv_last_check);
        const dguvNext = this.formatDateDe(product.dguv_next_check);
        const dguvInterval = product.dguv_interval_months != null ? `${product.dguv_interval_months} Monate` : '—';
        const dguvDue = product.dguv_next_check && String(product.dguv_next_check).slice(0, 10) <= new Date().toISOString().slice(0, 10);
        const dims = (product.width_cm || product.height_cm || product.depth_cm)
            ? `${product.width_cm ?? '—'} × ${product.height_cm ?? '—'} × ${product.depth_cm ?? '—'} cm`
            : null;

        const imageHtml = product.image_path
            ? `<div class="inventory-product-preview text-center mb-0">
                    <img src="/inventory/product-images/${this.escapeHtml(product.image_path)}" alt="${this.escapeHtml(product.name)}"
                         class="inventory-product-preview-img image-mini-preview img-fluid rounded"
                         onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                    <div class="inventory-product-preview-fallback" style="display:none;"><i class="bi bi-box-seam"></i></div>
               </div>`
            : `<div class="inventory-product-preview text-center"><div class="inventory-product-preview-fallback"><i class="bi bi-box-seam"></i></div></div>`;

        const row = (label, valueHtml) => `
            <div class="inventory-detail-row">
                <span class="inventory-detail-label">${label}</span>
                <span class="inventory-detail-value">${valueHtml}</span>
            </div>`;

        const manuals = Array.isArray(window.INVENTORY_MANUALS) ? window.INVENTORY_MANUALS : [];
        const manualsOptions = manuals.map((m) =>
            `<option value="${m.id}">${this.escapeHtml(m.title || '')}</option>`
        ).join('');
        const linkManualHtml = manuals.length
            ? `<div class="inventory-detail-link-manual mt-3">
                    <label class="form-label small mb-1" for="detailLinkManualSelect">Anleitung verknüpfen</label>
                    <div class="d-flex gap-2 flex-wrap align-items-stretch">
                        <select id="detailLinkManualSelect" class="form-select form-select-sm" style="min-width: 12rem; max-width: 22rem;">
                            <option value="">Anleitung wählen…</option>
                            ${manualsOptions}
                        </select>
                        <button type="button" class="btn btn-sm mod-pill-btn mod-pill-btn--outline"
                                id="detailLinkManualBtn"
                                data-product-id="${product.id}">
                            <i class="bi bi-link-45deg"></i> Verknüpfen
                        </button>
                    </div>
               </div>`
            : '';

        content.innerHTML = `
            <div class="inventory-inventur-edit-form">
                <section class="inventory-form-card">
                    <div class="inventory-form-card-head">
                        <h2 class="inventory-form-section-title"><i class="bi bi-box-seam"></i> Produkt</h2>
                    </div>
                    <div class="d-flex flex-column flex-md-row gap-3 align-items-md-start">
                        <div class="flex-shrink-0" style="min-width: 8rem; max-width: 11rem;">${imageHtml}</div>
                        <div class="flex-grow-1 min-width-0">
                            <div class="d-flex flex-wrap align-items-center gap-2 mb-1">
                                <h4 class="mb-0">${this.escapeHtml(product.name)}</h4>
                                ${statusBadge}
                                ${dguvDue ? '<span class="badge bg-danger">DGUV fällig</span>' : ''}
                            </div>
                            <div class="text-muted small mb-2">${val(product.category)}</div>
                            ${this.isValidValue(product.description) ? `<p class="mb-0">${this.escapeHtml(product.description)}</p>` : ''}
                        </div>
                    </div>
                </section>

                <section class="inventory-form-card">
                    <div class="inventory-form-card-head">
                        <h2 class="inventory-form-section-title"><i class="bi bi-info-circle"></i> Stammdaten</h2>
                    </div>
                    <div class="inventory-detail-list">
                        ${product.external_barcode ? row('Inventar-Nr.', `<strong>${val(product.external_barcode)}</strong>`) : ''}
                        ${row('Seriennummer', val(product.serial_number))}
                        ${row('Lagerort', val(product.location))}
                        ${row('Zustand', val(product.condition))}
                        ${row('Länge', val(product.length))}
                        ${product.item_type === 'consumable'
                            ? row('Bestand', `${this.escapeHtml(String(product.available ?? 0))} verfügbar${product.on_hand != null ? ` / ${this.escapeHtml(String(product.on_hand))} gesamt` : ''}`)
                            : ''}
                        ${row('Ordner', val(product.folder_name))}
                    </div>
                </section>

                <section class="inventory-form-card">
                    <div class="inventory-form-card-head">
                        <h2 class="inventory-form-section-title"><i class="bi bi-shield-check"></i> DGUV-Prüfung</h2>
                    </div>
                    <div class="inventory-detail-list">
                        ${row('Letzte Prüfung', dguvLast)}
                        ${row('Intervall', this.escapeHtml(dguvInterval))}
                        ${row('Nächste Prüfung', dguvDue ? `<span class="text-danger fw-semibold">${dguvNext}</span>` : dguvNext)}
                    </div>
                </section>

                ${(product.purchase_date || product.purchase_price != null || product.replacement_value != null || product.weight_kg != null || dims) ? `
                <section class="inventory-form-card">
                    <div class="inventory-form-card-head">
                        <h2 class="inventory-form-section-title"><i class="bi bi-clipboard-data"></i> Weitere Angaben</h2>
                    </div>
                    <div class="inventory-detail-list">
                        ${product.purchase_date ? row('Anschaffung', this.formatDateDe(product.purchase_date)) : ''}
                        ${product.purchase_price != null ? row('Kaufpreis', this.escapeHtml(String(product.purchase_price))) : ''}
                        ${product.replacement_value != null ? row('Wiederbeschaffung', this.escapeHtml(String(product.replacement_value))) : ''}
                        ${product.weight_kg != null ? row('Gewicht', `${this.escapeHtml(String(product.weight_kg))} kg`) : ''}
                        ${dims ? row('Abmessungen', this.escapeHtml(dims)) : ''}
                    </div>
                </section>` : ''}

                <section class="inventory-form-card" id="detailDocumentsSection">
                    <div class="inventory-form-card-head d-flex justify-content-between align-items-center flex-wrap gap-2">
                        <h2 class="inventory-form-section-title mb-0"><i class="bi bi-file-earmark"></i> Dokumente</h2>
                        <a href="/inventory/products/${product.id}/documents" class="btn btn-sm mod-pill-btn mod-pill-btn--outline">Alle verwalten</a>
                    </div>
                    <div id="detailDocumentsList" class="inventory-detail-docs text-muted small">Lade Dokumente…</div>
                    ${linkManualHtml}
                </section>

                <section class="inventory-form-card">
                    <div class="inventory-form-card-head">
                        <h2 class="inventory-form-section-title"><i class="bi bi-lightning"></i> Aktionen</h2>
                    </div>
                    <div class="d-flex gap-2 flex-wrap">
                        ${product.status === 'available'
                            ? `<a href="/inventory/products/${product.id}/borrow" class="btn mod-pill-btn mod-pill-btn--primary">Ausleihen</a>`
                            : ''}
                        <a href="/inventory/products/${product.id}/edit" class="btn mod-pill-btn mod-pill-btn--outline">Bearbeiten</a>
                        <a href="/inventory/products/${product.id}/documents" class="btn mod-pill-btn mod-pill-btn--outline">
                            <i class="bi bi-file-earmark"></i> Dokumente
                        </a>
                        <button type="button" class="btn mod-pill-btn mod-pill-btn--outline favorite-btn"
                                data-product-id="${product.id}"
                                onclick="toggleFavorite(${product.id});">
                            <i class="bi bi-star"></i> Favorit
                        </button>
                        ${product.status === 'available'
                            ? `<button class="btn mod-pill-btn mod-pill-btn--outline-warning" onclick="markAsInRepair(${product.id})">In Reparatur</button>`
                            : ''}
                        ${(product.status === 'defective' || product.status === 'in_repair')
                            ? `<button class="btn mod-pill-btn mod-pill-btn--outline-success" onclick="markAsAvailable(${product.id})">Als einsatzbereit</button>`
                            : ''}
                        ${product.status !== 'defective' && product.status !== 'retired' && product.status !== 'in_repair'
                            ? `<button class="btn mod-pill-btn mod-pill-btn--outline-danger" onclick="markAsDefective(${product.id})">Als defekt markieren</button>`
                            : ''}
                        ${product.status === 'missing'
                            ? `<button class="btn mod-pill-btn mod-pill-btn--outline-success" onclick="markAsFound(${product.id})">Als gefunden markieren</button>`
                            : product.status !== 'retired'
                                ? `<button class="btn mod-pill-btn mod-pill-btn--outline-danger" onclick="markAsMissing(${product.id})">Als fehlend markieren</button>`
                                : ''}
                    </div>
                </section>
            </div>
        `;

        modal.show();
        requestAnimationFrame(() => {
            modalElement.style.zIndex = '1055';
            const backdrop = document.querySelector('.modal-backdrop');
            if (backdrop) backdrop.style.zIndex = '1050';
        });

        this.loadProductDetailDocuments(product.id);
        const linkBtn = document.getElementById('detailLinkManualBtn');
        if (linkBtn) {
            linkBtn.addEventListener('click', () => this.linkManualFromDetail(product.id));
        }
    },

    async loadProductDetailDocuments(productId) {
        const listEl = document.getElementById('detailDocumentsList');
        if (!listEl) return;
        try {
            const response = await fetch(`/inventory/api/products/${productId}/documents`, {
                headers: { Accept: 'application/json' },
                credentials: 'same-origin',
            });
            if (!response.ok) throw new Error('load_failed');
            const docs = await response.json();
            const recent = (Array.isArray(docs) ? docs : []).slice(0, 3);
            if (!recent.length) {
                listEl.innerHTML = '<p class="mb-0 text-muted">Noch keine Dokumente.</p>';
                return;
            }
            listEl.innerHTML = `<ul class="list-unstyled mb-0 inventory-detail-docs-list">${recent.map((doc) => {
                const name = this.escapeHtml(doc.display_name || doc.file_name || doc.manual_title || 'Dokument');
                const href = doc.download_url || doc.manual_view_url || `/inventory/products/${productId}/documents`;
                const meta = doc.manual_title && !doc.has_file
                    ? '<span class="badge rounded-pill bg-secondary-subtle text-secondary">Anleitung</span>'
                    : (doc.file_type ? `<span class="text-muted">${this.escapeHtml(doc.file_type)}</span>` : '');
                return `<li class="inventory-detail-doc-item d-flex align-items-center justify-content-between gap-2 py-1">
                    <a href="${this.escapeHtml(href)}" class="text-decoration-none text-truncate" target="_blank" rel="noopener">
                        <i class="bi bi-file-earmark me-1"></i>${name}
                    </a>
                    ${meta}
                </li>`;
            }).join('')}</ul>`;
        } catch (e) {
            listEl.innerHTML = '<p class="mb-0 text-danger">Dokumente konnten nicht geladen werden.</p>';
        }
    },

    async linkManualFromDetail(productId) {
        const select = document.getElementById('detailLinkManualSelect');
        const manualId = select ? parseInt(select.value, 10) : NaN;
        if (!manualId) {
            inventoryNotify('Bitte eine Anleitung auswählen.', 'warning');
            return;
        }
        try {
            const body = new FormData();
            body.append('manual_id', String(manualId));
            body.append('file_type', 'handbook');
            const response = await fetch(`/inventory/products/${productId}/documents/link-manual`, {
                method: 'POST',
                body,
                headers: {
                    Accept: 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'same-origin',
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok || result.ok === false) {
                throw new Error(result.message || 'Verknüpfung fehlgeschlagen');
            }
            inventoryNotify(result.message || 'Anleitung verknüpft.', result.category === 'info' ? 'info' : 'success');
            if (select) select.value = '';
            await this.loadProductDetailDocuments(productId);
        } catch (e) {
            inventoryNotify(e.message || 'Verknüpfung fehlgeschlagen', 'danger');
        }
    },

    formatDateDe(value) {
        if (!this.isValidValue(value)) return '—';
        const raw = String(value).slice(0, 10);
        const d = new Date(`${raw}T00:00:00`);
        if (Number.isNaN(d.getTime())) return this.escapeHtml(raw);
        return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
    },

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
    },

    showError(message) {
        const container = document.getElementById('productsContainer');
        if (container) {
            container.innerHTML = `
                <div class="alert alert-danger">
                    <i class="bi bi-exclamation-triangle"></i> ${message}
                </div>
            `;
        }
    },

    showSuccess(message) {
        inventoryNotify(message, 'success');
    },

});
