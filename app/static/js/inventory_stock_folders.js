/** Bestandsübersicht — View-Toggle, Ordner, Sortierung. */
/* global StockManager, inventoryNotify, fetchInventoryApi */

Object.assign(StockManager.prototype, {
    setupViewToggle() {
        const bindToggle = (listBtn, gridBtn) => {
            if (!listBtn || !gridBtn) return;
            listBtn.addEventListener('click', () => {
                this.viewMode = 'list';
                localStorage.setItem('inventoryViewMode', 'list');
                this.applyViewMode();
            });
            gridBtn.addEventListener('click', () => {
                this.viewMode = 'grid';
                localStorage.setItem('inventoryViewMode', 'grid');
                this.applyViewMode();
            });
        };

        bindToggle(document.getElementById('listViewBtn'), document.getElementById('gridViewBtn'));
        bindToggle(document.getElementById('listViewBtnMobile'), document.getElementById('gridViewBtnMobile'));
    },

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
        const mode = this.viewMode === 'list' ? 'list' : 'grid';
        
        if (mode === 'list') {
            if (listViewContainer) listViewContainer.style.display = 'block';
            if (gridViewContainer) gridViewContainer.style.display = 'none';
            listBtns.forEach((btn) => {
                btn.classList.add('active', 'is-active');
            });
            gridBtns.forEach((btn) => {
                btn.classList.remove('active', 'is-active');
            });
        } else {
            if (gridViewContainer) gridViewContainer.style.display = 'block';
            if (listViewContainer) listViewContainer.style.display = 'none';
            gridBtns.forEach((btn) => {
                btn.classList.add('active', 'is-active');
            });
            listBtns.forEach((btn) => {
                btn.classList.remove('active', 'is-active');
            });
        }

        document.querySelectorAll('.inventory-shell .mod-view-toggle').forEach((el) => {
            el.dataset.view = mode;
        });
        
        // Rendere Produkte neu mit aktuellem View-Mode
        this.renderProducts();
    },
    
    // Ordner-Funktionen

    renderFolders() {
        // Ordner werden zusammen mit Produkten in renderProducts* gerendert
        this.renderProducts();
    },

    renderFolderCard(folder) {
        const productCount = folder.product_count || 0;
        const colorValue = folder.color || '#ffc107';
        const colorStyle = folder.color ? `style="color: ${this.escapeHtml(folder.color)};"` : '';
        const colorClass = folder.color ? '' : 'text-warning';
        const isEditing = Number(this.editingFolderId) === Number(folder.id);

        if (isEditing) {
            return `
                <div class="col-12 col-md-6 col-lg-3" data-folder-edit-wrap="${folder.id}">
                    <div class="card folder-item inventory-folder-card h-100 inventory-folder-card--editing" onclick="event.stopPropagation()">
                        <div class="card-body">
                            ${this.renderFolderInlineEditForm(folder, colorValue)}
                        </div>
                    </div>
                </div>
            `;
        }

        return `
            <div class="col-12 col-md-6 col-lg-3" data-context-zone data-context-menu="template" data-context-menu-id="context-menu-folder-${folder.id}">
                <div class="card folder-item inventory-folder-card h-100" onclick="if(window.stockManager){window.stockManager.navigateToFolder(${folder.id});}" style="cursor: pointer;">
                    ${this.buildFolderContextMenuHtml(folder)}
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-start gap-2">
                            <div class="min-width-0">
                                <i class="bi bi-folder-fill fs-1 folder-color-icon ${colorClass}" ${colorStyle}></i>
                                <h6 class="mt-2 mb-0 text-truncate" title="${this.escapeHtml(folder.name)}">${this.escapeHtml(folder.name)}</h6>
                                <small class="text-muted">${productCount} Produkt${productCount !== 1 ? 'e' : ''}</small>
                            </div>
                            <div class="inventory-card-actions gap-1" onclick="event.stopPropagation()">
                                <div class="inventory-grid-hover-actions">
                                    <button type="button" class="btn btn-sm btn-link" title="Umbenennen / Farbe"
                                            onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.startFolderInlineEdit(${folder.id});}">
                                        <i class="bi bi-pencil"></i>
                                    </button>
                                    <button type="button" class="btn btn-sm btn-link" title="Öffnen"
                                            onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.navigateToFolder(${folder.id});}">
                                        <i class="bi bi-folder2-open"></i>
                                    </button>
                                </div>
                                <div class="dropdown inventory-card-menu">
                                    <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" data-bs-display="static" aria-expanded="false">
                                        <i class="bi bi-three-dots-vertical"></i>
                                    </button>
                                    <ul class="dropdown-menu dropdown-menu-end inventory-actions-menu">
                                        <li>
                                            <button type="button" class="dropdown-item" onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.navigateToFolder(${folder.id});}">
                                                <i class="bi bi-folder2-open me-2"></i>Öffnen
                                            </button>
                                        </li>
                                        <li>
                                            <button type="button" class="dropdown-item" onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.startFolderInlineEdit(${folder.id});}">
                                                <i class="bi bi-pencil me-2"></i>Umbenennen / Farbe
                                            </button>
                                        </li>
                                        <li><a class="dropdown-item" href="/inventory/folders"><i class="bi bi-gear me-2"></i>Ordner verwalten</a></li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    renderFolderListItem(folder) {
        const productCount = folder.product_count || 0;
        const colorValue = folder.color || '#ffc107';
        const colorStyle = folder.color ? `style="color: ${this.escapeHtml(folder.color)};"` : '';
        const colorClass = folder.color ? '' : 'text-warning';
        const isEditing = Number(this.editingFolderId) === Number(folder.id);

        if (isEditing) {
            return `
                <tr class="mod-list-row inventory-folder-row inventory-folder-row--editing" data-folder-edit-wrap="${folder.id}" onclick="event.stopPropagation()">
                    <td colspan="7">
                        ${this.renderFolderInlineEditForm(folder, colorValue)}
                    </td>
                </tr>
            `;
        }

        return `
            <tr class="mod-list-row inventory-folder-row" data-context-zone data-context-menu="template" data-context-menu-id="context-menu-folder-${folder.id}" role="button" tabindex="0" onclick="if(window.stockManager){window.stockManager.navigateToFolder(${folder.id});}">
                <td class="inventory-list-check-col">
                    ${this.buildFolderContextMenuHtml(folder)}
                </td>
                <td>
                    <span class="mod-list-name inventory-item-name">
                        <i class="bi bi-folder-fill me-2 folder-color-icon ${colorClass}" ${colorStyle}></i>
                        <span class="inventory-item-name-text" title="${this.escapeHtml(folder.name)}">${this.escapeHtml(folder.name)}</span>
                    </span>
                </td>
                <td class="d-none d-md-table-cell text-muted">${productCount} Produkt${productCount !== 1 ? 'e' : ''}</td>
                <td class="d-none d-md-table-cell text-muted">—</td>
                <td class="d-none d-lg-table-cell text-muted">—</td>
                <td class="d-none d-xl-table-cell text-muted">—</td>
                <td class="text-end">
                    <div class="mod-list-actions">
                        <div class="mod-list-hover-actions">
                            <button type="button" class="btn btn-sm btn-link" title="Umbenennen / Farbe"
                                    onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.startFolderInlineEdit(${folder.id});}">
                                <i class="bi bi-pencil"></i>
                            </button>
                            <button type="button" class="btn btn-sm btn-link" title="Öffnen"
                                    onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.navigateToFolder(${folder.id});}">
                                <i class="bi bi-folder2-open"></i>
                            </button>
                        </div>
                        <div class="dropdown d-inline-block" onclick="event.stopPropagation()">
                            <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" data-bs-display="static" aria-expanded="false">
                                <i class="bi bi-three-dots-vertical"></i>
                            </button>
                            <ul class="dropdown-menu dropdown-menu-end inventory-actions-menu">
                                <li>
                                    <button type="button" class="dropdown-item" onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.navigateToFolder(${folder.id});}">
                                        <i class="bi bi-folder2-open me-2"></i>Öffnen
                                    </button>
                                </li>
                                <li>
                                    <button type="button" class="dropdown-item" onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.startFolderInlineEdit(${folder.id});}">
                                        <i class="bi bi-pencil me-2"></i>Umbenennen / Farbe
                                    </button>
                                </li>
                                <li><a class="dropdown-item" href="/inventory/folders"><i class="bi bi-gear me-2"></i>Ordner verwalten</a></li>
                            </ul>
                        </div>
                    </div>
                </td>
            </tr>
        `;
    },

    renderFolderInlineEditForm(folder, colorValue) {
        return `
            <form class="inventory-folder-inline" onsubmit="event.preventDefault(); if(window.stockManager){window.stockManager.saveFolderInlineEdit(${folder.id});}">
                <label class="form-label" for="inventoryFolderEditName${folder.id}">Name</label>
                <input type="text" class="form-control form-control-sm inventory-folder-inline-input" id="inventoryFolderEditName${folder.id}"
                       value="${this.escapeHtml(folder.name)}" maxlength="100" required autocomplete="off">
                <label class="form-label mt-2" for="inventoryFolderEditColor${folder.id}">Farbe</label>
                <input type="color" class="form-control form-control-color inventory-folder-inline-color" id="inventoryFolderEditColor${folder.id}"
                       value="${this.escapeHtml(colorValue)}" title="Ordnerfarbe">
                <div class="inventory-folder-inline-actions">
                    <button type="submit" class="btn btn-sm btn-accent inventory-folder-inline-submit">
                        <i class="bi bi-check2 me-1"></i>Speichern
                    </button>
                    <button type="button" class="btn btn-sm inventory-folder-inline-cancel"
                            onclick="event.preventDefault(); if(window.stockManager){window.stockManager.cancelFolderInlineEdit();}">
                        Abbrechen
                    </button>
                </div>
            </form>
        `;
    },

    startFolderInlineEdit(folderId) {
        this.editingFolderId = Number(folderId);
        this.renderProducts();
        const nameInput = document.getElementById(`inventoryFolderEditName${folderId}`);
        if (nameInput) {
            nameInput.focus();
            nameInput.select();
        }
    },

    cancelFolderInlineEdit() {
        this.editingFolderId = null;
        this.renderProducts();
    },

    async saveFolderInlineEdit(folderId) {
        const nameInput = document.getElementById(`inventoryFolderEditName${folderId}`);
        const colorInput = document.getElementById(`inventoryFolderEditColor${folderId}`);
        const name = (nameInput?.value || '').trim();
        const color = (colorInput?.value || '').trim() || null;
        if (!name) {
            inventoryNotify('Ordnername ist erforderlich.', 'warning');
            nameInput?.focus();
            return;
        }

        try {
            const response = await fetchInventoryApi(`/folders/${folderId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, color }),
            });
            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.error || 'Ordner konnte nicht gespeichert werden.');
            }
            const updated = await response.json();
            const idx = this.folders.findIndex((f) => Number(f.id) === Number(folderId));
            if (idx >= 0) {
                this.folders[idx] = { ...this.folders[idx], ...updated };
            }
            this.editingFolderId = null;
            this.renderProducts();
            inventoryNotify('Ordner gespeichert.', 'success');
        } catch (error) {
            console.error(error);
            inventoryNotify(error.message || 'Ordner konnte nicht gespeichert werden.', 'danger');
        }
    },

    navigateToFolder(folderId) {
        window.location.href = `/inventory/stock/${folderId}`;
    },

    getLengthInMeters(product) {
        if (!product) {
            return null;
        }
        if (typeof product.length_meters === 'number' && !Number.isNaN(product.length_meters)) {
            return product.length_meters;
        }
        const rawLength = product.length;
        if (!rawLength) {
            return null;
        }
        let text = rawLength.toString().trim().toLowerCase().replace(',', '.');
        let multiplier = 1;
        if (text.endsWith('mm')) {
            multiplier = 0.001;
            text = text.slice(0, -2);
        } else if (text.endsWith('cm')) {
            multiplier = 0.01;
            text = text.slice(0, -2);
        } else if (text.endsWith('km')) {
            multiplier = 1000;
            text = text.slice(0, -2);
        } else if (text.endsWith('m')) {
            text = text.slice(0, -1);
        }
        const numericPart = text.replace(/[^0-9.+-]/g, '');
        const numeric = parseFloat(numericPart);
        if (Number.isNaN(numeric)) {
            return null;
        }
        return parseFloat((numeric * multiplier).toFixed(6));
    },

    sortFilteredProducts() {
        if (!Array.isArray(this.filteredProducts) || this.filteredProducts.length === 0) {
            return;
        }
        const field = this.sortField || 'name';
        const direction = this.sortDirection === 'desc' ? -1 : 1;
        const collator = new Intl.Collator('de', { sensitivity: 'base' });
        const getString = (value) => (value ?? '').toString();
        
        this.filteredProducts.sort((a, b) => {
            if (field === 'length') {
                const valueA = this.getLengthInMeters(a);
                const valueB = this.getLengthInMeters(b);
                const aNull = valueA === null || valueA === undefined;
                const bNull = valueB === null || valueB === undefined;
                if (aNull && bNull) {
                    return collator.compare(getString(a.name), getString(b.name)) * direction;
                }
                if (aNull) return 1;
                if (bNull) return -1;
                if (valueA === valueB) {
                    return collator.compare(getString(a.name), getString(b.name)) * direction;
                }
                return valueA < valueB ? -1 * direction : 1 * direction;
            }
            
            let valueA;
            let valueB;
            switch (field) {
                case 'category':
                case 'condition':
                case 'location':
                case 'status':
                case 'serial_number':
                    valueA = getString(a[field]);
                    valueB = getString(b[field]);
                    break;
                case 'purchase_date':
                    valueA = getString(a.purchase_date);
                    valueB = getString(b.purchase_date);
                    break;
                case 'name':
                default:
                    valueA = getString(a.name);
                    valueB = getString(b.name);
                    break;
            }
            
            const aEmpty = valueA.trim() === '';
            const bEmpty = valueB.trim() === '';
            if (aEmpty && bEmpty) {
                return collator.compare(getString(a.name), getString(b.name)) * direction;
            }
            if (aEmpty) return 1;
            if (bEmpty) return -1;
            
            const comparison = collator.compare(valueA, valueB);
            if (comparison !== 0) {
                return comparison * direction;
            }
            return collator.compare(getString(a.name), getString(b.name)) * direction;
        });
    },

});
