// Inventurtool JavaScript

// Inventory Tool Manager - Verwaltet das Inventurtool
class InventoryToolManager {
    constructor(inventoryId) {
        this.inventoryId = inventoryId;
        this.items = new Map();
        this.pollingInterval = null;
        this.lastUpdateTime = null;
    }
    
    init() {
        console.log('InventoryToolManager initialisiert für Inventur:', this.inventoryId);
        
        // Lade initiale Daten
        this.loadItems();
        
        // Starte Polling für Live-Updates
        this.startPolling();
        
        // Event Listeners
        this.setupEventListeners();
        
        // Tab-Wechsel Handler
        this.setupTabHandlers();
    }
    
    setupEventListeners() {
        // Suchfunktion
        const searchInput = document.getElementById('searchInput');
        if (searchInput) {
            searchInput.addEventListener('input', () => this.filterItems());
        }
        
        // Save Button im Modal
        const saveBtn = document.getElementById('saveProductBtn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.saveProduct());
        }
        
        // Modal Close Event - Scanner wieder aktivieren und Backdrop entfernen
        const productModal = document.getElementById('productEditModal');
        if (productModal) {
            productModal.addEventListener('hidden.bs.modal', () => {
                // Entferne Backdrop falls vorhanden
                const backdrop = document.querySelector('.modal-backdrop');
                if (backdrop) {
                    backdrop.remove();
                }
                // Entferne modal-open Klasse vom body
                document.body.classList.remove('modal-open');
                document.body.style.overflow = '';
                document.body.style.paddingRight = '';
                
                // Scanner wieder aktivieren
                this.resumeScannerIfActive();
            });
        }
    }
    
    setupTabHandlers() {
        // Tab-Wechsel: Scanner stoppen wenn Tab gewechselt wird
        const tabs = document.querySelectorAll('#inventoryTabs button[data-bs-toggle="tab"]');
        tabs.forEach(tab => {
            tab.addEventListener('shown.bs.tab', (e) => {
                const targetId = e.target.getAttribute('data-bs-target');
                
                // Wenn Scanner-Tab verlassen wird, Scanner stoppen
                if (targetId !== '#scanner' && window.inventoryScannerManager) {
                    window.inventoryScannerManager.stopScanner();
                }
                
                // Wenn Scanner-Tab aktiviert wird, Scanner initialisieren
                if (targetId === '#scanner' && window.inventoryScannerManager) {
                    // Scanner wird automatisch initialisiert wenn Tab aktiv ist
                }
            });
        });
    }
    
    async loadItems() {
        try {
            const response = await fetch(`/inventory/api/inventory/${this.inventoryId}/items`);
            if (!response.ok) {
                throw new Error('Fehler beim Laden der Inventur-Items');
            }
            
            const data = await response.json();
            
            // Speichere Items
            this.items.clear();
            data.items.forEach(item => {
                this.items.set(item.product_id, item);
            });
            
            // Rendere Tabelle
            this.renderTable();
            
            // Update Fortschritt
            this.updateProgress(data.inventory);
            
            this.lastUpdateTime = new Date();
        } catch (error) {
            console.error('Fehler beim Laden der Items:', error);
        }
    }
    
    renderTable() {
        const tbody = document.getElementById('inventoryTableBody');
        if (!tbody) return;
        
        const searchTerm = document.getElementById('searchInput')?.value.toLowerCase() || '';
        
        let html = '';
        for (const [productId, item] of this.items.entries()) {
            const product = {
                id: item.product_id,
                name: item.product_name,
                category: item.product_category,
                location: item.product_location,
                condition: item.product_condition
            };
            
            // Filter nach Suchbegriff
            if (searchTerm) {
                const searchable = `${product.name} ${product.category} ${product.location} ${item.notes || ''}`.toLowerCase();
                if (!searchable.includes(searchTerm)) {
                    continue;
                }
            }
            
            const checkedClass = item.checked ? 'checked' : '';
            const hasChanges = item.location_changed || item.condition_changed || item.notes;
            const changeBadge = hasChanges ? '<span class="badge bg-warning ms-2">Geändert</span>' : '';
            
            html += `
                <tr class="inventory-item-row ${checkedClass}" data-product-id="${product.id}">
                    <td>
                        <input type="checkbox" class="form-check-input item-checkbox" 
                               data-product-id="${product.id}" 
                               ${item.checked ? 'checked' : ''}>
                    </td>
                    <td>
                        <strong>${this.escapeHtml(product.name)}</strong>
                        ${changeBadge}
                    </td>
                    <td>${this.escapeHtml(product.category || '-')}</td>
                    <td>
                        ${item.location_changed ? '<span class="text-warning">' + this.escapeHtml(item.new_location || '-') + '</span>' : this.escapeHtml(product.location || '-')}
                    </td>
                    <td>
                        ${item.condition_changed ? '<span class="text-warning">' + this.escapeHtml(item.new_condition || '-') + '</span>' : this.escapeHtml(product.condition || '-')}
                    </td>
                    <td>
                        <small class="text-muted">${item.notes ? this.escapeHtml(item.notes.substring(0, 50)) + (item.notes.length > 50 ? '...' : '') : '-'}</small>
                    </td>
                    <td>
                        <button class="btn btn-sm btn-outline-primary edit-item-btn" data-product-id="${product.id}">
                            <i class="bi bi-pencil"></i> Bearbeiten
                        </button>
                    </td>
                </tr>
            `;
        }
        
        tbody.innerHTML = html || '<tr><td colspan="7" class="text-center text-muted">Keine Produkte gefunden</td></tr>';
        
        // Event Listeners für Checkboxen
        tbody.querySelectorAll('.item-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const productId = parseInt(e.target.dataset.productId);
                this.toggleCheck(productId, e.target.checked);
            });
        });
        
        // Event Listeners für Bearbeiten-Buttons
        tbody.querySelectorAll('.edit-item-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const productId = parseInt(e.target.closest('.edit-item-btn').dataset.productId);
                this.showProductModal(productId);
            });
        });
    }
    
    filterItems() {
        this.renderTable();
    }
    
    async toggleCheck(productId, checked) {
        try {
            const response = await fetch(`/inventory/api/inventory/${this.inventoryId}/item/${productId}/check`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ checked: checked })
            });
            
            if (!response.ok) {
                throw new Error('Fehler beim Aktualisieren');
            }
            
            const data = await response.json();
            
            // Update lokale Daten
            const item = this.items.get(productId);
            if (item) {
                item.checked = data.checked;
                item.checked_at = data.checked_at;
            }
            
            // Rendere Tabelle neu
            this.renderTable();
            
            // Update Fortschritt
            this.loadItems();
        } catch (error) {
            console.error('Fehler beim Toggle Check:', error);
            alert('Fehler beim Aktualisieren der Checkbox');
        }
    }
    
    async showProductModal(productId) {
        const item = this.items.get(productId);
        if (!item) {
            alert('Produkt nicht gefunden');
            return;
        }
        
        const modalBody = document.getElementById('productEditModalBody');
        if (!modalBody) return;
        
        const product = {
            id: item.product_id,
            name: item.product_name,
            category: item.product_category,
            location: item.product_location,
            condition: item.product_condition
        };
        
        modalBody.innerHTML = `
            <form id="productEditForm">
                <input type="hidden" id="editProductId" value="${product.id}">
                
                <div class="mb-3">
                    <h5>${this.escapeHtml(product.name)}</h5>
                    <small class="text-muted">${this.escapeHtml(product.category || 'Keine Kategorie')}</small>
                </div>
                
                <div class="mb-3">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="editChecked" ${item.checked ? 'checked' : ''}>
                        <label class="form-check-label" for="editChecked">
                            Inventiert
                        </label>
                    </div>
                </div>
                
                <div class="mb-3">
                    <label for="editNotes" class="form-label">Anmerkungen</label>
                    <textarea class="form-control" id="editNotes" rows="3" placeholder="Anmerkungen zur Inventur...">${this.escapeHtml(item.notes || '')}</textarea>
                </div>
                
                <div class="row">
                    <div class="col-md-6 mb-3">
                        <label for="editLocation" class="form-label">Lagerort</label>
                        <input type="text" class="form-control" id="editLocation" 
                               value="${this.escapeHtml(item.new_location || product.location || '')}" 
                               placeholder="Aktuell: ${this.escapeHtml(product.location || 'Nicht gesetzt')}">
                        <small class="text-muted">Leer lassen um nicht zu ändern</small>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label for="editCondition" class="form-label">Zustand</label>
                        <select class="form-select" id="editCondition">
                            <option value="">Bitte wählen...</option>
                            <option value="Neu" ${item.new_condition === 'Neu' ? 'selected' : ''}>Neu</option>
                            <option value="Gut" ${item.new_condition === 'Gut' ? 'selected' : ''}>Gut</option>
                            <option value="Gebraucht" ${item.new_condition === 'Gebraucht' ? 'selected' : ''}>Gebraucht</option>
                            <option value="Beschädigt" ${item.new_condition === 'Beschädigt' ? 'selected' : ''}>Beschädigt</option>
                        </select>
                        <small class="text-muted">Aktuell: ${this.escapeHtml(product.condition || 'Nicht gesetzt')}</small>
                    </div>
                </div>
            </form>
        `;
        
        const modalElement = document.getElementById('productEditModal');
        
        // Prüfe ob Modal bereits existiert und entferne alte Instanz
        const existingModal = bootstrap.Modal.getInstance(modalElement);
        if (existingModal) {
            existingModal.dispose();
        }
        
        const modal = new bootstrap.Modal(modalElement);
        modal.show();
    }
    
    async saveProduct() {
        const productId = parseInt(document.getElementById('editProductId')?.value);
        if (!productId) return;
        
        const checked = document.getElementById('editChecked')?.checked || false;
        const notes = document.getElementById('editNotes')?.value.trim() || null;
        const newLocation = document.getElementById('editLocation')?.value.trim() || null;
        const newCondition = document.getElementById('editCondition')?.value || null;
        
        try {
            const response = await fetch(`/inventory/api/inventory/${this.inventoryId}/item/${productId}/update`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    checked: checked,
                    notes: notes,
                    new_location: newLocation,
                    new_condition: newCondition
                })
            });
            
            if (!response.ok) {
                throw new Error('Fehler beim Speichern');
            }
            
            const data = await response.json();
            
            // Update lokale Daten
            const item = this.items.get(productId);
            if (item) {
                Object.assign(item, data.item);
            }
            
            // Schließe Modal
            const modalElement = document.getElementById('productEditModal');
            const modal = bootstrap.Modal.getInstance(modalElement);
            if (modal) {
                modal.hide();
            }
            
            // Warte bis Modal vollständig geschlossen ist, dann entferne Backdrop
            setTimeout(() => {
                const backdrop = document.querySelector('.modal-backdrop');
                if (backdrop) {
                    backdrop.remove();
                }
                // Entferne modal-open Klasse vom body
                document.body.classList.remove('modal-open');
                document.body.style.overflow = '';
                document.body.style.paddingRight = '';
            }, 300);
            
            // Rendere Tabelle neu
            this.renderTable();
            
            // Update Fortschritt
            this.loadItems();
            
            // Scanner wieder aktivieren wenn Scanner-Tab aktiv ist
            this.resumeScannerIfActive();
        } catch (error) {
            console.error('Fehler beim Speichern:', error);
            alert('Fehler beim Speichern der Änderungen');
        }
    }
    
    resumeScannerIfActive() {
        // Prüfe ob Scanner-Tab aktiv ist
        const scannerTab = document.getElementById('scanner-tab');
        const scannerPane = document.getElementById('scanner');
        
        if (scannerTab && scannerPane && 
            scannerTab.classList.contains('active') && 
            scannerPane.classList.contains('active') &&
            scannerPane.classList.contains('show')) {
            
            // Prüfe ob Scanner-Manager existiert und Scanner gestartet werden sollte
            if (window.inventoryScannerManager && window.inventoryScannerManager.stream) {
                // Scanner sollte bereits laufen, aber sicherstellen dass er aktiv ist
                if (!window.inventoryScannerManager.scanning) {
                    window.inventoryScannerManager.scanning = true;
                    setTimeout(() => {
                        window.inventoryScannerManager.scanForQR();
                    }, 500);
                }
            }
        }
    }
    
    async handleScan(qrData) {
        try {
            const response = await fetch(`/inventory/api/inventory/${this.inventoryId}/scan`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ qr_data: qrData })
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Fehler beim Scannen');
            }
            
            const data = await response.json();
            
            // Zeige Erfolgs-Popup
            this.showScanSuccess();
            
            // Pausiere Scanner während Modal offen ist
            if (window.inventoryScannerManager) {
                window.inventoryScannerManager.scanning = false;
            }
            
            // Öffne Produkt-Modal automatisch
            setTimeout(() => {
                this.showProductModal(data.product.id);
            }, 500);
            
            // Update Items
            this.loadItems();
        } catch (error) {
            console.error('Fehler beim Scannen:', error);
            this.showError(error.message);
            
            // Bei Fehler Scanner wieder aktivieren
            if (window.inventoryScannerManager && window.inventoryScannerManager.stream) {
                setTimeout(() => {
                    window.inventoryScannerManager.scanning = true;
                    window.inventoryScannerManager.scanForQR();
                }, 1000);
            }
        }
    }
    
    async handleManualInput(input) {
        if (!input || !input.trim()) {
            return;
        }
        
        const trimmedInput = input.trim();
        console.log('Manuelle Eingabe verarbeiten:', trimmedInput);
        
        // Versuche als Produkt-ID zu parsen
        let productId = null;
        
        // Normalisiere Eingabe: Entferne alle nicht-numerischen Zeichen am Anfang
        // Unterstützt Formate wie: PROD-123, PRODB1, 123, PROD123, etc.
        let cleaned = trimmedInput;
        
        // Entferne PROD- oder PRODB Präfix (auch mit Bindestrich oder ohne)
        cleaned = cleaned.replace(/^PROD[B-]?/i, '').trim();
        
        // Versuche als Zahl zu parsen
        const parsed = parseInt(cleaned);
        if (!isNaN(parsed) && parsed > 0) {
            productId = parsed;
        } else {
            // Falls Parsing fehlschlägt, versuche direkt als QR-Code
            // Aber zuerst nochmal versuchen, alle Buchstaben zu entfernen und nur Zahlen zu nehmen
            const numbersOnly = trimmedInput.replace(/\D/g, '');
            if (numbersOnly) {
                const numParsed = parseInt(numbersOnly);
                if (!isNaN(numParsed) && numParsed > 0) {
                    productId = numParsed;
                } else {
                    // Versuche als QR-Code zu parsen (kann PROD-123 oder SET-456 sein)
                    try {
                        await this.handleScan(trimmedInput);
                        return;
                    } catch (error) {
                        console.error('Fehler beim Scannen:', error);
                        alert('Ungültiger QR-Code oder Produkt-ID: ' + trimmedInput + '\n\nBitte verwenden Sie:\n- Produkt-ID (z.B. 123)\n- QR-Code (z.B. PROD-123)');
                        return;
                    }
                }
            } else {
                // Versuche als QR-Code zu parsen
                try {
                    await this.handleScan(trimmedInput);
                    return;
                } catch (error) {
                    console.error('Fehler beim Scannen:', error);
                    alert('Ungültiger QR-Code oder Produkt-ID: ' + trimmedInput + '\n\nBitte verwenden Sie:\n- Produkt-ID (z.B. 123)\n- QR-Code (z.B. PROD-123)');
                    return;
                }
            }
        }
        
        // Finde Produkt
        const item = this.items.get(productId);
        if (!item) {
            // Warte kurz und versuche es nochmal (falls Items noch nicht geladen sind)
            await new Promise(resolve => setTimeout(resolve, 100));
            const retryItem = this.items.get(productId);
            if (!retryItem) {
                alert('Produkt nicht in dieser Inventur gefunden: ' + productId);
                return;
            }
            // Verwende retryItem
            productId = retryItem.product_id;
        }
        
        // Automatisch abhaken
        try {
            await this.toggleCheck(productId, true);
        } catch (error) {
            console.error('Fehler beim Abhaken:', error);
        }
        
        // Öffne Modal nach kurzer Verzögerung, damit UI aktualisiert werden kann
        setTimeout(() => {
            this.showProductModal(productId);
        }, 100);
    }
    
    updateProgress(inventory) {
        // Update Fortschrittsanzeige im Alert
        const alert = document.querySelector('.alert-info');
        if (alert && inventory) {
            const progressText = alert.querySelector('small');
            if (progressText) {
                progressText.textContent = `Fortschritt: ${inventory.checked_count} von ${inventory.total_count} Produkten inventiert`;
            }
        }
    }
    
    startPolling() {
        // Polling alle 3 Sekunden
        this.pollingInterval = setInterval(() => {
            this.loadItems();
        }, 3000);
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
            setTimeout(() => {
                popup.style.display = 'none';
            }, 2000);
        }
    }
    
    showError(message) {
        const errorDiv = document.getElementById('scannerError');
        if (errorDiv) {
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
            setTimeout(() => {
                errorDiv.style.display = 'none';
            }, 5000);
        }
    }
    
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Inventory Scanner Manager - Verwaltet den QR-Code Scanner für Inventur
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
        
        if (startBtn) {
            startBtn.addEventListener('click', () => this.startScanner());
        }
        
        if (stopBtn) {
            stopBtn.addEventListener('click', () => this.stopScanner());
        }
    }
    
    async startScanner() {
        if (!('getUserMedia' in navigator.mediaDevices)) {
            alert('Ihr Browser unterstützt keine Kamera-API.');
            return;
        }
        
        try {
            const constraints = {
                video: { 
                    facingMode: 'environment',
                    width: { ideal: 1280 },
                    height: { ideal: 720 }
                }
            };
            
            this.stream = await navigator.mediaDevices.getUserMedia(constraints);
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
            alert('Fehler beim Starten der Kamera: ' + error.message);
        }
    }
    
    stopScanner() {
        this.scanning = false;
        
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
        
        const video = document.getElementById('scannerVideo');
        const container = document.getElementById('scannerContainer');
        
        if (video) {
            video.srcObject = null;
        }
        
        if (container) {
            container.style.display = 'none';
        }
        
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
        
        if (typeof jsQR === 'undefined' && typeof window.jsQR === 'undefined') {
            console.error('jsQR ist nicht geladen!');
            setTimeout(() => this.scanForQR(), 500);
            return;
        }
        
        const jsQRFunction = window.jsQR || jsQR;
        
        if (video.readyState < 2) {
            setTimeout(() => this.scanForQR(), 200);
            return;
        }
        
        const videoWidth = video.videoWidth;
        const videoHeight = video.videoHeight;
        
        if (videoWidth === 0 || videoHeight === 0) {
            setTimeout(() => this.scanForQR(), 200);
            return;
        }
        
        if (canvas.width !== videoWidth || canvas.height !== videoHeight) {
            canvas.width = videoWidth;
            canvas.height = videoHeight;
        }
        
        const context = canvas.getContext('2d');
        context.drawImage(video, 0, 0, videoWidth, videoHeight);
        
        try {
            const imageData = context.getImageData(0, 0, videoWidth, videoHeight);
            
            let code = null;
            
            code = jsQRFunction(imageData.data, imageData.width, imageData.height, {
                inversionAttempts: 'attemptBoth',
            });
            
            if (!code) {
                const grayscaleData = new Uint8ClampedArray(imageData.data.length);
                for (let i = 0; i < imageData.data.length; i += 4) {
                    const gray = Math.round(
                        0.299 * imageData.data[i] +
                        0.587 * imageData.data[i + 1] +
                        0.114 * imageData.data[i + 2]
                    );
                    grayscaleData[i] = gray;
                    grayscaleData[i + 1] = gray;
                    grayscaleData[i + 2] = gray;
                    grayscaleData[i + 3] = imageData.data[i + 3];
                }
                
                code = jsQRFunction(grayscaleData, imageData.width, imageData.height, {
                    inversionAttempts: 'attemptBoth',
                });
            }
            
            if (code) {
                console.log('QR-Code erkannt (InventoryScanner):', code.data);
                this.scanning = false;
                
                const qrCodeData = code.data;
                
                // Zeige Erfolgs-Popup
                if (this.toolManager) {
                    this.toolManager.showScanSuccess();
                }
                
                // Verarbeite Scan
                if (this.toolManager) {
                    this.toolManager.handleScan(qrCodeData).then(() => {
                        // Scanner wird nach Modal-Schließung wieder aktiviert
                        // Nicht hier aktivieren, da Modal geöffnet wird
                    }).catch(() => {
                        // Bei Fehler Scanner wieder aktivieren
                        setTimeout(() => {
                            if (this.stream && !this.scanning) {
                                this.scanning = true;
                                this.scanForQR();
                            }
                        }, 1000);
                    });
                }
                return;
            } else {
                requestAnimationFrame(() => this.scanForQR());
            }
        } catch (error) {
            console.error('Fehler beim Scannen:', error);
            setTimeout(() => this.scanForQR(), 200);
        }
    }
}

// Globale Verfügbarkeit
window.InventoryToolManager = InventoryToolManager;
window.InventoryScannerManager = InventoryScannerManager;

