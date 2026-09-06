/** Bestandsübersicht — Auswahl, Bulk-Status, Bulk-Edit/Delete. */
/* global StockManager, inventoryNotify, inventoryConfirm, fetchInventoryApi */

Object.assign(StockManager.prototype, {
    handleCardClick(productId, isSelectable) {
        // Wenn bereits Auswahl aktiv ist und Produkt auswählbar, toggle Auswahl
        if (this.selectedProducts.size > 0 && isSelectable) {
            this.toggleProductSelection(productId);
        } else {
            // Sonst Details anzeigen
            this.showProductDetail(productId);
        }
    },

    toggleProductSelection(productId) {
        const checkbox = document.querySelector(`.product-checkbox[data-product-id="${productId}"]`);
        if (checkbox && !checkbox.disabled) {
            checkbox.checked = !checkbox.checked;
            // Aktualisiere selectedProducts Set
            if (checkbox.checked) {
                this.selectedProducts.add(productId);
            } else {
                this.selectedProducts.delete(productId);
            }
            this.updateCardSelection(productId);
            this.updateSelectionUI();
        } else if (!checkbox) {
            // Fallback: Wenn keine Checkbox gefunden, direkt im Set togglen
            if (this.selectedProducts.has(productId)) {
                this.selectedProducts.delete(productId);
            } else {
                // Prüfe ob Produkt auswählbar ist
                const product = this.products.find(p => p.id === productId);
                if (product && this.isProductSelectable(product)) {
                    this.selectedProducts.add(productId);
                }
            }
            this.updateCardSelection(productId);
            this.updateSelectionUI();
        }
    },

    selectAllAvailable() {
        // Alle auswählbaren Produkte der aktuellen Filterliste
        this.filteredProducts.forEach(product => {
            if (this.isProductSelectable(product)) {
                this.selectedProducts.add(product.id);
            }
        });
        // Aktualisiere alle Checkboxen und Karten
        document.querySelectorAll('.product-checkbox').forEach(cb => {
            const productId = parseInt(cb.dataset.productId);
            cb.checked = this.selectedProducts.has(productId);
            this.updateCardSelection(productId);
        });
        this.updateSelectionUI();
    },

    deselectAll() {
        // Entferne alle Produkte aus der Auswahl
        this.selectedProducts.clear();
        // Aktualisiere alle Checkboxen und Karten
        document.querySelectorAll('.product-checkbox').forEach(cb => {
            const productId = parseInt(cb.dataset.productId);
            cb.checked = false;
            this.updateCardSelection(productId);
        });
        this.updateSelectionUI();
    },

    getSelectedProducts() {
        // Verwende selectedProducts Set als einzige Quelle der Wahrheit
        return Array.from(this.selectedProducts);
    },

    updateSelectionUI() {
        const selected = this.getSelectedProducts();
        const bulkToolbar = document.getElementById('bulkSelectionToolbar');
        const bulkSelectionCount = document.getElementById('bulkSelectionCount');

        document.body.classList.toggle('inventory-has-selection', selected.length > 0);
        
        // Toolbar anzeigen/verstecken
        if (bulkToolbar) {
            if (selected.length > 0) {
                bulkToolbar.style.display = 'block';
                bulkToolbar.classList.add('is-visible');
            } else {
                bulkToolbar.style.display = 'none';
                bulkToolbar.classList.remove('is-visible');
            }
        }
        
        if (bulkSelectionCount) {
            bulkSelectionCount.textContent = selected.length;
        }

        this.updateBulkStatusButtons(selected);
        
        // Stelle sicher, dass alle Karten visuell korrekt aktualisiert sind
        document.querySelectorAll('.product-checkbox').forEach(cb => {
            const productId = parseInt(cb.dataset.productId);
            this.updateCardSelection(productId);
        });
    },

    updateBulkStatusButtons(selectedIds) {
        const repairBtn = document.getElementById('bulkRepairBtn');
        const availableBtn = document.getElementById('bulkAvailableBtn');
        if (!repairBtn && !availableBtn) return;

        if (!selectedIds || selectedIds.length === 0) {
            if (repairBtn) repairBtn.classList.remove('d-none');
            if (availableBtn) availableBtn.classList.remove('d-none');
            return;
        }

        const selectedProducts = selectedIds
            .map((id) => this.products.find((p) => p.id === id))
            .filter(Boolean);
        if (!selectedProducts.length) {
            if (repairBtn) repairBtn.classList.remove('d-none');
            if (availableBtn) availableBtn.classList.remove('d-none');
            return;
        }

        const isBroken = (s) => s === 'defective' || s === 'in_repair';
        const allAvailable = selectedProducts.every((p) => p.status === 'available');
        const allBroken = selectedProducts.every((p) => isBroken(p.status));

        if (repairBtn) {
            repairBtn.classList.toggle('d-none', allBroken);
        }
        if (availableBtn) {
            availableBtn.classList.toggle('d-none', allAvailable);
        }
    },

    async borrowSelected() {
        const selectedIds = this.getSelectedProducts();
        
        if (selectedIds.length === 0) {
            inventoryNotify('Bitte wählen Sie mindestens ein Produkt aus.', 'warning');
            return;
        }
        
        // Prüfe ob alle ausgewählten Produkte verfügbar sind
        const unavailableProducts = this.filteredProducts.filter(p => 
            selectedIds.includes(p.id) && p.status !== 'available'
        );
        
        if (unavailableProducts.length > 0) {
            inventoryNotify('Einige ausgewählte Produkte sind nicht verfügbar. Bitte wählen Sie nur verfügbare Produkte aus.', 'warning');
            return;
        }
        
        // Weiterleitung zur Mehrfachausleihe-Seite mit Produkt-IDs als Parameter
        const productIdsParam = selectedIds.join(',');
        window.location.href = `/inventory/borrow-multiple?product_ids=${productIdsParam}`;
    },

    async printSelectedQr() {
        const selectedIds = this.getSelectedProducts();
        if (selectedIds.length === 0) {
            inventoryNotify('Bitte wählen Sie mindestens ein Produkt aus.', 'warning');
            return;
        }
        try {
            const response = await fetch('/inventory/api/print-qr-codes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_ids: selectedIds }),
            });
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.error || 'QR-Druck fehlgeschlagen');
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `QR-Codes_${new Date().toISOString().slice(0,10)}.pdf`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        } catch (e) {
            inventoryNotify(e.message || 'QR-Druck fehlgeschlagen', 'danger');
        }
    },

    async markSelectedInRepair() {
        const selectedIds = this.getSelectedProducts();
        if (selectedIds.length === 0) {
            inventoryNotify('Bitte wählen Sie mindestens ein Produkt aus.', 'warning');
            return;
        }
        if (!(await inventoryConfirm(`${selectedIds.length} Produkt(e) auf „In Reparatur“ setzen?`, {
            title: 'Status ändern',
            confirmLabel: 'Ja, setzen',
            cancelLabel: 'Abbrechen',
            danger: false,
        }))) {
            return;
        }
        try {
            const response = await fetch('/inventory/api/products/bulk-update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_ids: selectedIds, status: 'in_repair' }),
            });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.error || 'Status-Update fehlgeschlagen');
            }
            inventoryNotify(result.message || 'Status aktualisiert.', 'success');
            await this.loadProducts();
        } catch (e) {
            inventoryNotify(e.message || 'Status-Update fehlgeschlagen', 'danger');
        }
    },

    async markSelectedAvailable() {
        const selectedIds = this.getSelectedProducts();
        if (selectedIds.length === 0) {
            inventoryNotify('Bitte wählen Sie mindestens ein Produkt aus.', 'warning');
            return;
        }
        if (!(await inventoryConfirm(`${selectedIds.length} Produkt(e) wieder als einsatzbereit markieren?`, {
            title: 'Einsatzbereit setzen',
            confirmLabel: 'Ja, setzen',
            cancelLabel: 'Abbrechen',
            danger: false,
        }))) {
            return;
        }
        try {
            const response = await fetch('/inventory/api/products/bulk-update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_ids: selectedIds, status: 'available' }),
            });
            const result = await response.json();
            if (!response.ok) {
                throw new Error(result.error || 'Status-Update fehlgeschlagen');
            }
            inventoryNotify(result.message || 'Status aktualisiert.', 'success');
            await this.loadProducts();
        } catch (e) {
            inventoryNotify(e.message || 'Status-Update fehlgeschlagen', 'danger');
        }
    },

    openBulkDeleteModal() {
        const selectedIds = this.getSelectedProducts();
        if (selectedIds.length === 0) {
            inventoryNotify('Bitte wählen Sie mindestens ein Produkt aus.', 'warning');
            return;
        }
        
        const modalEl = document.getElementById('bulkDeleteModal');
        if (!modalEl) {
            console.error('Bulk-Delete-Modal nicht gefunden');
            return;
        }
        
        const modal = new bootstrap.Modal(modalEl);
        const productCountEl = document.getElementById('bulkDeleteProductCount');
        const confirmBtn = document.getElementById('bulkDeleteConfirmBtn');
        
        if (productCountEl) {
            productCountEl.textContent = selectedIds.length;
        }
        
        // Event-Handler für Bestätigungs-Button
        if (confirmBtn) {
            // Entferne alte Event-Listener
            const newConfirmBtn = confirmBtn.cloneNode(true);
            confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
            
            newConfirmBtn.addEventListener('click', () => {
                this.deleteSelectedProducts(selectedIds, modal);
            });
        }
        
        modal.show();
    },

    async deleteSelectedProducts(productIds, modal) {
        if (!productIds || productIds.length === 0) {
            inventoryNotify('Keine Produkte zum Verschieben ausgewählt.', 'warning');
            return;
        }
        
        const confirmBtn = document.getElementById('bulkDeleteConfirmBtn');
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Verschiebe...';
        }
        
        try {
            const response = await fetchInventoryApi('/products/bulk-delete', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    product_ids: productIds
                })
            });
            
            // Prüfe Content-Type bevor JSON geparst wird
            const contentType = response.headers.get('content-type');
            let data;
            
            if (contentType && contentType.includes('application/json')) {
                data = await response.json();
            } else {
                // Wenn keine JSON-Antwort, versuche Text zu lesen
                const text = await response.text();
                console.error('Ungültige Antwort vom Server:', text);
                throw new Error('Ungültige Antwort vom Server. Bitte versuchen Sie es erneut.');
            }
            
            if (!response.ok) {
                throw new Error(data.error || 'Fehler beim Verschieben der Produkte');
            }
            
            // Erfolgreich gelöscht
            if (modal) {
                modal.hide();
                // Warte kurz und entferne Backdrop falls vorhanden
                setTimeout(() => {
                    const backdrop = document.querySelector('.modal-backdrop');
                    if (backdrop) {
                        backdrop.remove();
                    }
                    document.body.classList.remove('modal-open');
                    document.body.style.overflow = '';
                    document.body.style.paddingRight = '';
                }, 300);
            }
            
            // Zeige Erfolgsmeldung
            this.showSuccess(data.message || `${data.deleted_count} Produkt(e) in den Papierkorb verschoben.`);
            
            // Entferne gelöschte Produkte aus der Auswahl
            productIds.forEach(id => {
                this.selectedProducts.delete(id);
            });
            
            // Lade Produkte neu
            await this.loadProducts();
            
        } catch (error) {
            console.error('Fehler beim Verschieben in den Papierkorb:', error);
            this.showError(error.message || 'Fehler beim Verschieben der Produkte. Bitte versuchen Sie es erneut.');
            
            // Modal schließen auch bei Fehler
            if (modal) {
                modal.hide();
                // Warte kurz und entferne Backdrop falls vorhanden
                setTimeout(() => {
                    const backdrop = document.querySelector('.modal-backdrop');
                    if (backdrop) {
                        backdrop.remove();
                    }
                    document.body.classList.remove('modal-open');
                    document.body.style.overflow = '';
                    document.body.style.paddingRight = '';
                }, 300);
            }
            
            if (confirmBtn) {
                confirmBtn.disabled = false;
                confirmBtn.innerHTML = '<i class="bi bi-trash"></i> In Papierkorb';
            }
        }
    },

    async deleteProduct(productId) {
        if (!productId) {
            inventoryNotify('Keine Produkt-ID angegeben.', 'warning');
            return;
        }
        
        // Bestätigung
        if (!(await inventoryConfirm('Gerät in den Papierkorb verschieben?', {
            title: 'In den Papierkorb',
            confirmLabel: 'Verschieben',
            danger: true,
        }))) {
            return;
        }
        
        try {
            const response = await fetchInventoryApi(`/products/${productId}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            // Prüfe Content-Type bevor JSON geparst wird
            const contentType = response.headers.get('content-type');
            let data;
            
            if (contentType && contentType.includes('application/json')) {
                data = await response.json();
            } else {
                // Wenn keine JSON-Antwort, versuche Text zu lesen
                const text = await response.text();
                console.error('Ungültige Antwort vom Server:', text);
                throw new Error('Ungültige Antwort vom Server. Bitte versuchen Sie es erneut.');
            }
            
            if (!response.ok) {
                throw new Error(data.error || 'Fehler beim Löschen des Produkts');
            }
            
            // Erfolgreich gelöscht
            this.showSuccess(data.message || 'Produkt wurde in den Papierkorb verschoben.');
            
            // Entferne aus der Auswahl falls ausgewählt
            this.selectedProducts.delete(productId);
            
            // Lade Produkte neu
            await this.loadProducts();
            
        } catch (error) {
            console.error('Fehler beim Löschen:', error);
            this.showError(error.message || 'Fehler beim Verschieben in den Papierkorb. Bitte versuchen Sie es erneut.');
        }
    },

    async restoreProduct(productId) {
        if (!productId) {
            inventoryNotify('Keine Produkt-ID angegeben.', 'warning');
            return;
        }
        if (!(await inventoryConfirm('Gerät wieder in Betrieb nehmen?', {
            title: 'Wieder in Betrieb nehmen',
            confirmLabel: 'Wiederherstellen',
        }))) {
            return;
        }
        try {
            const response = await fetchInventoryApi('/products/bulk-update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_ids: [productId], status: 'available' }),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || 'Wiederherstellen fehlgeschlagen');
            }
            this.showSuccess(data.message || 'Gerät wieder in Betrieb genommen.');
            this.selectedProducts.delete(productId);
            await this.loadProducts();
        } catch (error) {
            this.showError(error.message || 'Fehler beim Wiederherstellen.');
        }
    },

    async restoreSelectedProducts() {
        const selectedIds = this.getSelectedProducts();
        if (selectedIds.length === 0) {
            inventoryNotify('Bitte wählen Sie mindestens ein Produkt aus.', 'warning');
            return;
        }
        if (!(await inventoryConfirm(`${selectedIds.length} Gerät(e) wieder in Betrieb nehmen?`, {
            title: 'Wieder in Betrieb nehmen',
            confirmLabel: 'Wiederherstellen',
        }))) {
            return;
        }
        try {
            const response = await fetchInventoryApi('/products/bulk-update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_ids: selectedIds, status: 'available' }),
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || 'Wiederherstellen fehlgeschlagen');
            }
            this.showSuccess(data.message || `${selectedIds.length} Gerät(e) wieder in Betrieb genommen.`);
            this.selectedProducts.clear();
            await this.loadProducts();
        } catch (error) {
            this.showError(error.message || 'Fehler beim Wiederherstellen.');
        }
    },

    openBulkEditModal() {
        const selectedIds = [...this.getSelectedProducts()];
        if (selectedIds.length === 0) {
            inventoryNotify('Bitte wählen Sie mindestens ein Produkt aus.', 'warning');
            return;
        }

        const modalEl = document.getElementById('bulkEditModal');
        if (!modalEl) {
            console.error('Bulk-Edit-Modal nicht gefunden');
            return;
        }
        if (modalEl.parentElement !== document.body) {
            document.body.appendChild(modalEl);
        }

        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        const productCountEl = document.getElementById('bulkEditProductCount');
        const form = document.getElementById('bulkEditForm');
        let submitBtn = document.getElementById('bulkEditSubmitBtn');

        if (productCountEl) productCountEl.textContent = selectedIds.length;
        if (form) form.reset();

        const categorySelect = document.getElementById('bulkEditCategory');
        if (categorySelect) {
            categorySelect.innerHTML = '<option value="">— nicht ändern —</option>' +
                (this.categories ? Array.from(this.categories).sort().map((cat) =>
                    `<option value="${this.escapeHtml(cat)}">${this.escapeHtml(cat)}</option>`
                ).join('') : '');
        }
        const folderSelect = document.getElementById('bulkEditFolder');
        if (folderSelect) {
            folderSelect.innerHTML = '<option value="">— nicht ändern —</option>' +
                (this.folders ? Array.from(this.folders)
                    .filter((folder) => !this.retiredFolderId || Number(folder.id) !== Number(this.retiredFolderId))
                    .sort((a, b) => a.name.localeCompare(b.name)).map((folder) =>
                    `<option value="${folder.id}">${this.escapeHtml(folder.name)}</option>`
                ).join('') : '');
        }

        const lastEl = document.getElementById('bulkEditDguvLast');
        const intervalEl = document.getElementById('bulkEditDguvInterval');
        const nextEl = document.getElementById('bulkEditDguvNextDisplay');
        const refreshDguv = () => {
            if (!nextEl) return;
            if (lastEl?.value) {
                const nextIso = this.computeDguvNextIso(lastEl.value, intervalEl?.value || 12);
                nextEl.value = nextIso ? this.formatDateDe(nextIso) : '';
            } else if (intervalEl?.value) {
                nextEl.value = this.formatDateDe(new Date().toISOString().slice(0, 10));
            } else {
                nextEl.value = '';
            }
        };
        lastEl?.addEventListener('change', refreshDguv);
        lastEl?.addEventListener('input', refreshDguv);
        intervalEl?.addEventListener('change', refreshDguv);
        intervalEl?.addEventListener('input', refreshDguv);
        refreshDguv();

        if (submitBtn) {
            const newSubmitBtn = submitBtn.cloneNode(true);
            submitBtn.parentNode.replaceChild(newSubmitBtn, submitBtn);
            submitBtn = newSubmitBtn;
            submitBtn.disabled = false;

            submitBtn.addEventListener('click', async () => {
                const updateData = { product_ids: selectedIds };
                let hasUpdate = false;

                const location = document.getElementById('bulkEditLocation')?.value.trim();
                if (location) {
                    updateData.location = location;
                    hasUpdate = true;
                }
                const lengthRaw = document.getElementById('bulkEditLength')?.value;
                if (lengthRaw !== undefined && lengthRaw !== '') {
                    const length = parseFloat(lengthRaw);
                    if (Number.isNaN(length) || length < 0) {
                        inventoryNotify('Bitte eine gültige Länge eingeben.', 'warning');
                        return;
                    }
                    updateData.length = length;
                    hasUpdate = true;
                }
                const condition = document.getElementById('bulkEditCondition')?.value;
                if (condition) {
                    updateData.condition = condition;
                    hasUpdate = true;
                }
                const status = document.getElementById('bulkEditStatus')?.value;
                if (status) {
                    updateData.status = status;
                    hasUpdate = true;
                }
                const category = document.getElementById('bulkEditCategory')?.value;
                if (category) {
                    updateData.category = category;
                    hasUpdate = true;
                }
                const folderId = document.getElementById('bulkEditFolder')?.value;
                if (folderId) {
                    updateData.folder_id = folderId;
                    hasUpdate = true;
                }
                const dguvLast = document.getElementById('bulkEditDguvLast')?.value;
                const dguvIntervalRaw = document.getElementById('bulkEditDguvInterval')?.value;
                if (dguvLast || dguvIntervalRaw) {
                    if (dguvIntervalRaw) {
                        const interval = parseInt(dguvIntervalRaw, 10);
                        if (!Number.isFinite(interval) || interval < 1) {
                            inventoryNotify('Bitte ein gültiges DGUV-Intervall (>= 1) angeben.', 'warning');
                            return;
                        }
                        updateData.dguv_interval_months = interval;
                    }
                    if (dguvLast) {
                        updateData.dguv_last_check = dguvLast;
                    }
                    hasUpdate = true;
                }
                if (document.getElementById('bulkEditRemoveImage')?.checked) {
                    if (!(await inventoryConfirm(`Produktbilder von ${selectedIds.length} Produkt(en) entfernen?`, {
                        title: 'Bilder entfernen',
                        confirmLabel: 'Entfernen',
                        danger: true,
                    }))) {
                        return;
                    }
                    updateData.remove_image = true;
                    hasUpdate = true;
                }
                if (document.getElementById('bulkEditConvertToCable')?.checked) {
                    const confirmedConvert = await inventoryConfirm(
                        'Wirklich überführen? Dieser Schritt kann nicht rückgängig gemacht werden.',
                        {
                            title: 'Zu Mengenartikel überführen',
                            confirmLabel: 'Ja, überführen',
                            danger: true,
                        }
                    );
                    if (!confirmedConvert) {
                        return;
                    }
                    updateData.convert_to_cable = true;
                    hasUpdate = true;
                }

                if (!hasUpdate) {
                    inventoryNotify('Bitte mindestens ein Feld ausfüllen.', 'warning');
                    return;
                }

                submitBtn.disabled = true;
                const originalText = submitBtn.innerHTML;
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Aktualisiere...';
                try {
                    const response = await fetchInventoryApi('/products/bulk-update', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(updateData),
                    });
                    const result = await response.json();
                    if (!response.ok) throw new Error(result.error || 'Fehler beim Aktualisieren');
                    modal.hide();
                    inventoryNotify(result.message || `${result.updated_count || selectedIds.length} Produkt(e) aktualisiert.`, 'success');
                    await this.loadProducts();
                    this.applyFilters();
                    this.selectedProducts.clear();
                    this.updateSelectionUI();
                } catch (error) {
                    console.error('Bulk-Update Fehler:', error);
                    inventoryNotify('Fehler beim Aktualisieren: ' + (error.message || 'Unbekannter Fehler'), 'danger');
                } finally {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = originalText;
                }
            });
        }

        modal.show();
    },

});
