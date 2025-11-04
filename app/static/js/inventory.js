// Inventory Management JavaScript

// Stock Manager - Verwaltet die Bestandsübersicht
class StockManager {
    constructor() {
        this.products = [];
        this.filteredProducts = [];
        this.categories = new Set();
        this.folders = new Set();
        this.conditions = new Set();
        this.locations = new Set();
        this.lengths = new Set();
        this.purchaseYears = new Set();
        this.searchTimeout = null;
        this.selectedProducts = new Set(); // Verwaltet ausgewählte Produkt-IDs
    }
    
    async init() {
        this.setupEventListeners();
        await this.loadFolders(); // Lade alle Ordner zuerst
        await this.loadProducts();
        // Initiale UI-Aktualisierung
        this.updateSelectionUI();
    }
    
    async loadFolders() {
        try {
            const response = await fetch('/inventory/api/folders');
            if (response.ok) {
                const foldersData = await response.json();
                // Füge alle Ordner zum Set hinzu
                foldersData.forEach(folder => {
                    this.folders.add({ id: folder.id, name: folder.name });
                });
                this.updateFolders();
            } else {
                console.warn('Fehler beim Laden der Ordner, verwende nur Ordner aus Produkten');
            }
        } catch (error) {
            console.warn('Fehler beim Laden der Ordner:', error);
            // Nicht kritisch, verwende Ordner aus Produkten
        }
    }
    
    async loadProducts() {
        try {
            // Verwende die vollständige API, um alle Attribute zu erhalten
            const response = await fetch('/inventory/api/products');
            
            if (!response.ok) {
                const errorText = await response.text();
                console.error('API-Fehler:', response.status, errorText);
                this.showError(`Fehler beim Laden der Produkte (Status: ${response.status})`);
                return;
            }
            
            const data = await response.json();
            
            if (!Array.isArray(data)) {
                console.error('Ungültige API-Antwort:', data);
                this.showError('Ungültige Daten vom Server erhalten');
                return;
            }
            
            this.products = data;
            this.filteredProducts = [...this.products];
            
            // Debug: Prüfe ob location und length vorhanden sind
            if (this.products.length > 0) {
                const firstProduct = this.products[0];
                console.log('Erstes Produkt (vollständig):', firstProduct);
                console.log('Location valid:', this.isValidValue(firstProduct.location), 'Value:', firstProduct.location);
                console.log('Length valid:', this.isValidValue(firstProduct.length), 'Value:', firstProduct.length);
                console.log('Serial valid:', this.isValidValue(firstProduct.serial_number), 'Value:', firstProduct.serial_number);
            }
            
            // Extrahiere auch Ordner aus Produkten (zusätzlich zu den bereits geladenen)
            this.extractCategories();
            // Aktualisiere Ordner-Filter, falls neue Ordner aus Produkten gefunden wurden
            this.updateFolders();
            this.renderProducts();
        } catch (error) {
            console.error('Fehler beim Laden der Produkte:', error);
            this.showError(`Fehler beim Laden der Produkte: ${error.message}`);
        }
    }
    
    extractCategories() {
        this.categories.clear();
        this.folders.clear();
        this.conditions.clear();
        this.locations.clear();
        this.lengths.clear();
        this.purchaseYears.clear();
        
        this.products.forEach(p => {
            if (p.category) {
                this.categories.add(p.category);
            }
            if (p.folder_id && p.folder_name) {
                this.folders.add({ id: p.folder_id, name: p.folder_name });
            }
            if (p.condition) {
                this.conditions.add(p.condition);
            }
            if (p.location) {
                this.locations.add(p.location);
            }
            if (p.length) {
                this.lengths.add(p.length);
            }
            if (p.purchase_date) {
                // Extrahiere Jahr aus Datum (Format: YYYY-MM-DD)
                const year = p.purchase_date.substring(0, 4);
                if (year && year !== 'null') {
                    this.purchaseYears.add(year);
                }
            }
        });
        
        this.updateCategories();
        this.updateFolders();
        this.updateConditions();
        this.updateLocations();
        this.updateLengths();
        this.updatePurchaseYears();
    }
    
    updateCategories() {
        const categoryFilter = document.getElementById('categoryFilter');
        if (!categoryFilter) return;
        
        const currentValue = categoryFilter.value;
        categoryFilter.innerHTML = '<option value="">Alle Kategorien</option>';
        
        Array.from(this.categories).sort().forEach(cat => {
            const option = document.createElement('option');
            option.value = cat;
            option.textContent = cat;
            categoryFilter.appendChild(option);
        });
        
        categoryFilter.value = currentValue;
    }
    
    updateFolders() {
        const folderFilter = document.getElementById('folderFilter');
        if (!folderFilter) return;
        
        const currentValue = folderFilter.value;
        folderFilter.innerHTML = '<option value="">Alle Ordner</option>';
        
        // Konvertiere Set zu Array und sortiere nach Name
        const foldersArray = Array.from(this.folders);
        // Entferne Duplikate basierend auf ID
        const uniqueFolders = Array.from(new Map(foldersArray.map(f => [f.id, f])).values());
        uniqueFolders.sort((a, b) => a.name.localeCompare(b.name));
        
        uniqueFolders.forEach(folder => {
            const option = document.createElement('option');
            option.value = folder.id;
            option.textContent = folder.name;
            folderFilter.appendChild(option);
        });
        
        folderFilter.value = currentValue;
    }
    
    updateConditions() {
        const conditionFilter = document.getElementById('conditionFilter');
        if (!conditionFilter) return;
        
        const currentValue = conditionFilter.value;
        conditionFilter.innerHTML = '<option value="">Alle Zustände</option>';
        
        Array.from(this.conditions).sort().forEach(cond => {
            const option = document.createElement('option');
            option.value = cond;
            option.textContent = cond;
            conditionFilter.appendChild(option);
        });
        
        conditionFilter.value = currentValue;
    }
    
    updateLocations() {
        const locationFilter = document.getElementById('locationFilter');
        if (!locationFilter) return;
        
        const currentValue = locationFilter.value;
        locationFilter.innerHTML = '<option value="">Alle Lagerorte</option>';
        
        Array.from(this.locations).sort().forEach(loc => {
            const option = document.createElement('option');
            option.value = loc;
            option.textContent = loc;
            locationFilter.appendChild(option);
        });
        
        locationFilter.value = currentValue;
    }
    
    updateLengths() {
        const lengthFilter = document.getElementById('lengthFilter');
        if (!lengthFilter) return;
        
        const currentValue = lengthFilter.value;
        lengthFilter.innerHTML = '<option value="">Alle Längen</option>';
        
        // Sortiere Längen intelligent (zuerst nach Zahl, dann alphabetisch)
        const sortedLengths = Array.from(this.lengths).sort((a, b) => {
            // Extrahiere Zahlen aus Strings (z.B. "5m" -> 5)
            const numA = parseFloat(a.replace(/[^0-9.]/g, '')) || 0;
            const numB = parseFloat(b.replace(/[^0-9.]/g, '')) || 0;
            if (numA !== numB) {
                return numA - numB;
            }
            return a.localeCompare(b);
        });
        
        sortedLengths.forEach(len => {
            const option = document.createElement('option');
            option.value = len;
            option.textContent = len;
            lengthFilter.appendChild(option);
        });
        
        lengthFilter.value = currentValue;
    }
    
    updatePurchaseYears() {
        const purchaseYearFilter = document.getElementById('purchaseYearFilter');
        if (!purchaseYearFilter) return;
        
        const currentValue = purchaseYearFilter.value;
        purchaseYearFilter.innerHTML = '<option value="">Alle Jahre</option>';
        
        // Sortiere Jahre absteigend (neueste zuerst)
        Array.from(this.purchaseYears).sort((a, b) => b - a).forEach(year => {
            const option = document.createElement('option');
            option.value = year;
            option.textContent = year;
            purchaseYearFilter.appendChild(option);
        });
        
        purchaseYearFilter.value = currentValue;
    }
    
    setupEventListeners() {
        const searchInput = document.getElementById('searchInput');
        const folderFilter = document.getElementById('folderFilter');
        const categoryFilter = document.getElementById('categoryFilter');
        const statusFilter = document.getElementById('statusFilter');
        const conditionFilter = document.getElementById('conditionFilter');
        const locationFilter = document.getElementById('locationFilter');
        const lengthFilter = document.getElementById('lengthFilter');
        const purchaseYearFilter = document.getElementById('purchaseYearFilter');
        const resetFiltersBtn = document.getElementById('resetFiltersBtn');
        const selectionModeToggle = document.getElementById('selectionModeToggle');
        const selectAllBtn = document.getElementById('selectAllBtn');
        const deselectAllBtn = document.getElementById('deselectAllBtn');
        const borrowSelectedBtn = document.getElementById('borrowSelectedBtn');
        
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                clearTimeout(this.searchTimeout);
                this.searchTimeout = setTimeout(() => this.applyFilters(), 300);
            });
        }
        
        // Alle Filter mit Event-Listenern versehen
        [folderFilter, categoryFilter, statusFilter, conditionFilter, locationFilter, lengthFilter, purchaseYearFilter].forEach(filter => {
            if (filter) {
                filter.addEventListener('change', () => this.applyFilters());
            }
        });
        
        if (resetFiltersBtn) {
            resetFiltersBtn.addEventListener('click', () => this.resetFilters());
        }
        
        if (selectionModeToggle) {
            selectionModeToggle.addEventListener('change', () => {
                // Wenn Selection Mode deaktiviert wird, alle auswählen zurücksetzen
                if (!selectionModeToggle.checked) {
                    this.selectedProducts.clear();
                }
                this.renderProducts();
                this.updateSelectionUI();
            });
        }
        
        if (selectAllBtn) {
            selectAllBtn.addEventListener('click', () => this.selectAllAvailable());
        }
        
        if (deselectAllBtn) {
            deselectAllBtn.addEventListener('click', () => this.deselectAll());
        }
        
        if (borrowSelectedBtn) {
            borrowSelectedBtn.addEventListener('click', () => this.borrowSelected());
        }
        
        // Checkbox-Events werden direkt in attachCheckboxHandlers() behandelt
    }
    
    applyFilters() {
        const search = document.getElementById('searchInput')?.value.toLowerCase() || '';
        const folder = document.getElementById('folderFilter')?.value || '';
        const category = document.getElementById('categoryFilter')?.value || '';
        const status = document.getElementById('statusFilter')?.value || '';
        const condition = document.getElementById('conditionFilter')?.value || '';
        const location = document.getElementById('locationFilter')?.value || '';
        const length = document.getElementById('lengthFilter')?.value || '';
        const purchaseYear = document.getElementById('purchaseYearFilter')?.value || '';
        
        this.filteredProducts = this.products.filter(p => {
            // Erweiterte Suche - durchsucht alle Attribute
            const matchesSearch = !search || this.matchesSearch(p, search);
            
            // Filter
            const matchesFolder = !folder || (p.folder_id && p.folder_id.toString() === folder);
            const matchesCategory = !category || p.category === category;
            const matchesStatus = !status || p.status === status;
            const matchesCondition = !condition || p.condition === condition;
            const matchesLocation = !location || p.location === location;
            const matchesLength = !length || p.length === length;
            const matchesPurchaseYear = !purchaseYear || this.matchesPurchaseYear(p, purchaseYear);
            
            return matchesSearch && matchesFolder && matchesCategory && matchesStatus && 
                   matchesCondition && matchesLocation && matchesLength && matchesPurchaseYear;
        });
        
        this.renderProducts();
    }
    
    matchesSearch(product, searchTerm) {
        // Suche in allen Attributen
        const searchLower = searchTerm.toLowerCase();
        
        // Name
        if (product.name && product.name.toLowerCase().includes(searchLower)) return true;
        
        // Seriennummer
        if (product.serial_number && product.serial_number.toLowerCase().includes(searchLower)) return true;
        
        // Länge (z.B. "5m" findet "5m", "5 m", etc.)
        if (product.length && product.length.toLowerCase().includes(searchLower)) return true;
        
        // Beschreibung
        if (product.description && product.description.toLowerCase().includes(searchLower)) return true;
        
        // Kategorie
        if (product.category && product.category.toLowerCase().includes(searchLower)) return true;
        
        // Ordner
        if (product.folder_name && product.folder_name.toLowerCase().includes(searchLower)) return true;
        
        // Lagerort
        if (product.location && product.location.toLowerCase().includes(searchLower)) return true;
        
        // Zustand
        if (product.condition && product.condition.toLowerCase().includes(searchLower)) return true;
        
        return false;
    }
    
    matchesPurchaseYear(product, year) {
        if (!product.purchase_date) return false;
        // purchase_date Format: "YYYY-MM-DD" oder "YYYY-MM-DDTHH:mm:ss"
        const productYear = product.purchase_date.substring(0, 4);
        return productYear === year;
    }
    
    resetFilters() {
        document.getElementById('searchInput').value = '';
        document.getElementById('folderFilter').value = '';
        document.getElementById('categoryFilter').value = '';
        document.getElementById('statusFilter').value = '';
        document.getElementById('conditionFilter').value = '';
        document.getElementById('locationFilter').value = '';
        document.getElementById('lengthFilter').value = '';
        document.getElementById('purchaseYearFilter').value = '';
        this.applyFilters();
    }
    
    isValidValue(value) {
        // Prüft ob ein Wert gültig ist und angezeigt werden sollte
        if (value === null || value === undefined) return false;
        // Konvertiere zu String für weitere Prüfungen
        const strValue = String(value).trim();
        // Prüfe auf leere Strings oder ungültige Werte
        if (strValue === '' || 
            strValue === 'null' || 
            strValue === 'None' || 
            strValue === 'none' ||
            strValue === 'undefined') {
            return false;
        }
        return true;
    }
    
    filterByFolder(folderId) {
        // Setze Ordner-Filter und klappe Filter aus
        const folderFilter = document.getElementById('folderFilter');
        const filterCollapse = document.getElementById('filterCollapse');
        
        if (folderFilter) {
            folderFilter.value = folderId.toString();
            // Klappe Filter-Accordion aus, damit Filter sichtbar ist
            if (filterCollapse) {
                const bsCollapse = new bootstrap.Collapse(filterCollapse, { show: true });
            }
            this.applyFilters();
        }
    }
    
    renderProducts() {
        const container = document.getElementById('productsContainer');
        if (!container) return;
        
        if (this.filteredProducts.length === 0) {
            container.innerHTML = `
                <div class="inventory-empty">
                    <i class="bi bi-inbox fs-1 mb-3"></i>
                    <p>Keine Produkte gefunden</p>
                </div>
            `;
            return;
        }
        
        const html = this.filteredProducts.map(product => this.renderProductCard(product)).join('');
        container.innerHTML = `<div class="inventory-grid">${html}</div>`;
        
        // Nach dem Rendern Event-Handler für Checkboxen setzen
        this.attachCheckboxHandlers();
    }
    
    attachCheckboxHandlers() {
        // Event-Handler für alle Checkboxen setzen
        document.querySelectorAll('.product-checkbox').forEach(checkbox => {
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
        });
    }
    
    updateCardSelection(productId) {
        // Aktualisiere die visuelle Darstellung einer einzelnen Karte
        const checkbox = document.querySelector(`.product-checkbox[data-product-id="${productId}"]`);
        if (!checkbox) return;
        
        const card = checkbox.closest('.product-card');
        if (!card) return;
        
        const isSelected = this.selectedProducts.has(productId);
        checkbox.checked = isSelected;
        
        if (isSelected) {
            card.classList.add('selection-mode');
        } else {
            card.classList.remove('selection-mode');
        }
    }
    
    renderProductCard(product) {
        let statusBadge = '';
        if (product.status === 'available') {
            statusBadge = '<span class="badge bg-success">Verfügbar</span>';
        } else if (product.status === 'borrowed') {
            statusBadge = '<span class="badge bg-warning">Ausgeliehen</span>';
        } else if (product.status === 'missing') {
            statusBadge = '<span class="badge bg-danger">Fehlend</span>';
        }
        
        const imageHtml = product.image_path 
            ? `<img src="file://${product.image_path}" alt="${product.name}" class="product-image">`
            : '<div class="product-image d-flex align-items-center justify-content-center bg-light"><i class="bi bi-box-seam fs-1 text-muted"></i></div>';
        
        const isSelectionMode = document.getElementById('selectionModeToggle')?.checked || false;
        const isSelected = this.selectedProducts.has(product.id);
        const showCheckbox = isSelectionMode && product.status === 'available';
        const checkbox = showCheckbox
            ? `<div class="position-absolute top-0 start-0 m-2">
                <input type="checkbox" class="form-check-input product-checkbox" 
                       value="${product.id}" data-product-id="${product.id}" 
                       ${isSelected ? 'checked' : ''}
                       style="width: 1.2rem; height: 1.2rem; background-color: white;">
               </div>`
            : '';
        
        // Sicherstellen, dass stockManager existiert bevor es verwendet wird
        const cardClickHandler = isSelectionMode && product.status === 'available'
            ? `onclick="if(window.stockManager){window.stockManager.toggleProductSelection(${product.id});}"`
            : `onclick="if(window.stockManager){window.stockManager.showProductDetail(${product.id});}"`;
        
        // selection-mode Klasse nur hinzufügen, wenn das Produkt tatsächlich ausgewählt ist
        const selectionModeClass = (isSelectionMode && product.status === 'available' && isSelected) ? 'selection-mode' : '';
        
        return `
            <div class="card product-card ${selectionModeClass}" ${cardClickHandler}>
                <div class="position-relative">
                    ${imageHtml}
                    ${checkbox}
                    <span class="badge product-status-badge">${statusBadge}</span>
                </div>
                <div class="card-body">
                    <h5 class="card-title">${product.name}</h5>
                        ${product.folder_name 
                        ? `<p class="mb-1">
                            <span class="badge bg-info cursor-pointer" 
                                  onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.filterByFolder(${product.folder_id});}" 
                                  title="Klicken um nach diesem Ordner zu filtern">
                                <i class="bi bi-folder"></i> ${product.folder_name}
                            </span>
                          </p>`
                        : ''}
                    ${product.category ? `<p class="text-muted mb-1"><small>${product.category}</small></p>` : ''}
                    <div class="product-details mb-2">
                        ${this.isValidValue(product.serial_number) 
                            ? `<p class="text-muted mb-1"><small><i class="bi bi-upc"></i> SN: ${product.serial_number}</small></p>` 
                            : ''}
                        ${this.isValidValue(product.location) 
                            ? `<p class="text-muted mb-1"><small><i class="bi bi-geo-alt"></i> ${product.location}</small></p>` 
                            : ''}
                        ${this.isValidValue(product.length) 
                            ? `<p class="text-muted mb-0"><small><i class="bi bi-arrows-expand"></i> ${product.length}</small></p>` 
                            : ''}
                    </div>
                    <div class="mt-2">
                        ${!isSelectionMode && product.status === 'available' 
                            ? `<a href="/inventory/products/${product.id}/borrow" class="btn btn-sm btn-primary" onclick="event.stopPropagation()">Ausleihen</a>`
                            : ''}
                        <a href="/inventory/products/${product.id}/edit" class="btn btn-sm btn-outline-secondary" onclick="event.stopPropagation()">Bearbeiten</a>
                    </div>
                </div>
            </div>
        `;
    }
    
    showProductDetail(productId) {
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
        
        const modal = new bootstrap.Modal(modalElement);
        const content = document.getElementById('productDetailContent');
        
        const imageHtml = product.image_path
            ? `<img src="file://${product.image_path}" alt="${product.name}" class="product-detail-image mb-3">`
            : '';
        
        content.innerHTML = `
            ${imageHtml}
            <h4>${product.name}</h4>
            <table class="table">
                ${product.category ? `<tr><th>Kategorie:</th><td>${product.category}</td></tr>` : ''}
                ${product.serial_number ? `<tr><th>Seriennummer:</th><td>${product.serial_number}</td></tr>` : ''}
                ${product.condition ? `<tr><th>Zustand:</th><td>${product.condition}</td></tr>` : ''}
                ${product.location ? `<tr><th>Lagerort:</th><td>${product.location}</td></tr>` : ''}
                ${product.length ? `<tr><th>Länge:</th><td>${product.length}</td></tr>` : ''}
                ${product.purchase_date ? `<tr><th>Anschaffungsdatum:</th><td>${product.purchase_date}</td></tr>` : ''}
                <tr><th>Status:</th><td>${
                    product.status === 'available' ? 'Verfügbar' : 
                    product.status === 'borrowed' ? 'Ausgeliehen' : 
                    product.status === 'missing' ? 'Fehlend' : product.status
                }</td></tr>
            </table>
            ${product.description ? `<p>${product.description}</p>` : ''}
            <div class="d-flex gap-2">
                ${product.status === 'available' 
                    ? `<a href="/inventory/products/${product.id}/borrow" class="btn btn-primary">Ausleihen</a>`
                    : ''}
                <a href="/inventory/products/${product.id}/edit" class="btn btn-outline-secondary">Bearbeiten</a>
                ${product.status === 'missing'
                    ? `<button class="btn btn-success btn-sm mt-2" onclick="markAsFound(${product.id})">Als gefunden markieren</button>`
                    : `<button class="btn btn-outline-danger btn-sm mt-2" onclick="markAsMissing(${product.id})">Als fehlend markieren</button>`}
            </div>
        `;
        
        modal.show();
    }
    
    showError(message) {
        const container = document.getElementById('productsContainer');
        if (container) {
            container.innerHTML = `
                <div class="alert alert-danger">
                    <i class="bi bi-exclamation-triangle"></i> ${message}
                </div>
            `;
        }
    }
    
    toggleProductSelection(productId) {
        const checkbox = document.querySelector(`.product-checkbox[data-product-id="${productId}"]`);
        if (checkbox) {
            checkbox.checked = !checkbox.checked;
            // Aktualisiere selectedProducts Set
            if (checkbox.checked) {
                this.selectedProducts.add(productId);
            } else {
                this.selectedProducts.delete(productId);
            }
            this.updateCardSelection(productId);
            this.updateSelectionUI();
        }
    }
    
    selectAllAvailable() {
        // Füge alle verfügbaren Produkte zur Auswahl hinzu
        this.filteredProducts.forEach(product => {
            if (product.status === 'available') {
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
    }
    
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
    }
    
    getSelectedProducts() {
        // Verwende selectedProducts Set als einzige Quelle der Wahrheit
        return Array.from(this.selectedProducts);
    }
    
    updateSelectionUI() {
        const selected = this.getSelectedProducts();
        const selectedCountEl = document.getElementById('selectedCount');
        const borrowSelectedBtn = document.getElementById('borrowSelectedBtn');
        
        if (selectedCountEl) {
            selectedCountEl.textContent = selected.length;
        }
        
        if (borrowSelectedBtn) {
            borrowSelectedBtn.style.display = selected.length > 0 ? 'inline-block' : 'none';
        }
        
        // Stelle sicher, dass alle Karten visuell korrekt aktualisiert sind
        document.querySelectorAll('.product-checkbox').forEach(cb => {
            const productId = parseInt(cb.dataset.productId);
            this.updateCardSelection(productId);
        });
    }
    
    async borrowSelected() {
        const selectedIds = this.getSelectedProducts();
        
        if (selectedIds.length === 0) {
            alert('Bitte wählen Sie mindestens ein Produkt aus.');
            return;
        }
        
        // Prüfe ob alle ausgewählten Produkte verfügbar sind
        const unavailableProducts = this.filteredProducts.filter(p => 
            selectedIds.includes(p.id) && p.status !== 'available'
        );
        
        if (unavailableProducts.length > 0) {
            alert('Einige ausgewählte Produkte sind nicht verfügbar. Bitte wählen Sie nur verfügbare Produkte aus.');
            return;
        }
        
        // Weiterleitung zur Mehrfachausleihe-Seite mit Produkt-IDs als Parameter
        const productIdsParam = selectedIds.join(',');
        window.location.href = `/inventory/borrow-multiple?product_ids=${productIdsParam}`;
    }
}

// Borrows Manager - Verwaltet die Ausleih-Übersicht
class BorrowsManager {
    constructor() {
        this.borrows = [];
        this.filteredBorrows = [];
    }
    
    async init() {
        await this.loadBorrows();
        this.renderBorrows();
        
        // Auto-Refresh alle 30 Sekunden
        setInterval(() => this.loadBorrows(), 30000);
    }
    
    async loadBorrows() {
        try {
            const urlParams = new URLSearchParams(window.location.search);
            const filterMy = urlParams.get('filter') === 'my';
            
            const endpoint = filterMy ? '/inventory/api/borrows/my' : '/inventory/api/borrows';
            const response = await fetch(endpoint);
            
            if (response.ok) {
                this.borrows = await response.json();
                this.applyFilters();
            } else {
                console.error('Fehler beim Laden der Ausleihen');
            }
        } catch (error) {
            console.error('Fehler beim Laden der Ausleihen:', error);
        }
    }
    
    applyFilters() {
        const borrowerFilter = document.getElementById('filterBorrower')?.value.toLowerCase() || '';
        const productFilter = document.getElementById('filterProduct')?.value.toLowerCase() || '';
        const statusFilter = document.getElementById('filterStatus')?.value || '';
        
        this.filteredBorrows = this.borrows.filter(b => {
            const matchesBorrower = !borrowerFilter || 
                (b.borrower_name && b.borrower_name.toLowerCase().includes(borrowerFilter));
            const matchesProduct = !productFilter || 
                (b.product_name && b.product_name.toLowerCase().includes(productFilter));
            const matchesStatus = statusFilter === 'all' || !statusFilter ||
                (statusFilter === 'active' && !b.is_overdue) ||
                (statusFilter === 'overdue' && b.is_overdue);
            
            return matchesBorrower && matchesProduct && matchesStatus;
        });
        
        this.renderBorrows();
    }
    
    renderBorrows() {
        const tbody = document.getElementById('borrowsTableBody');
        const countBadge = document.getElementById('borrowsCount');
        
        if (countBadge) {
            countBadge.textContent = this.filteredBorrows.length;
        }
        
        if (!tbody) return;
        
        if (this.filteredBorrows.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center py-5">
                        <p class="text-muted">Keine Ausleihen gefunden</p>
                    </td>
                </tr>
            `;
            return;
        }
        
        tbody.innerHTML = this.filteredBorrows.map(borrow => `
            <tr class="${borrow.is_overdue ? 'table-danger' : ''}">
                <td><code>${borrow.transaction_number}</code></td>
                <td><strong>${borrow.product_name}</strong></td>
                <td>${borrow.borrower_name || 'Unbekannt'}</td>
                <td>${new Date(borrow.borrow_date).toLocaleDateString('de-DE')}</td>
                <td>
                    ${new Date(borrow.expected_return_date).toLocaleDateString('de-DE')}
                    ${borrow.is_overdue ? '<br><span class="badge bg-danger">Überfällig</span>' : ''}
                </td>
                <td>
                    <span class="badge bg-warning">Aktiv</span>
                </td>
                <td>
                    <a href="/inventory/api/borrow/${borrow.id}/pdf" 
                       class="btn btn-sm btn-outline-secondary" 
                       title="Ausleihschein herunterladen">
                        <i class="bi bi-file-pdf"></i>
                    </a>
                </td>
            </tr>
        `).join('');
    }
}

// Return Manager - Verwaltet die Rückgabe mit QR-Scanner
class ReturnManager {
    constructor() {
        this.stream = null;
        this.scanning = false;
    }
    
    init() {
        const startBtn = document.getElementById('startScannerBtn');
        const stopBtn = document.getElementById('stopScannerBtn');
        const video = document.getElementById('scannerVideo');
        const form = document.getElementById('returnForm');
        
        if (startBtn) {
            startBtn.addEventListener('click', () => this.startScanner());
        }
        
        if (stopBtn) {
            stopBtn.addEventListener('click', () => this.stopScanner());
        }
        
        if (form) {
            form.addEventListener('submit', (e) => this.handleSubmit(e));
        }
    }
    
    async startScanner() {
        if (!('getUserMedia' in navigator.mediaDevices)) {
            this.showError('Ihr Browser unterstützt keine Kamera-API.');
            return;
        }
        
        try {
            // Optimierte Kamera-Einstellungen für bessere QR-Code-Erkennung
            const constraints = {
                video: { 
                    facingMode: 'environment',
                    width: { ideal: 1920, min: 640 },
                    height: { ideal: 1080, min: 480 }
                } 
            };
            
            // Versuche erweiterte Einstellungen (nicht alle Browser unterstützen dies)
            try {
                constraints.video.advanced = [
                    { focusMode: 'continuous' },
                    { exposureMode: 'continuous' }
                ];
            } catch (e) {
                // Ignoriere wenn nicht unterstützt
            }
            
            this.stream = await navigator.mediaDevices.getUserMedia(constraints);
            
            const video = document.getElementById('scannerVideo');
            const startBtn = document.getElementById('startScannerBtn');
            const stopBtn = document.getElementById('stopScannerBtn');
            
            if (video) {
                video.srcObject = this.stream;
                video.setAttribute('playsinline', 'true');
                video.setAttribute('autoplay', 'true');
                video.style.display = 'block';
                
                // Warte bis Video bereit ist
                await new Promise((resolve, reject) => {
                    video.onloadedmetadata = () => {
                        video.play()
                            .then(() => {
                                console.log('Video gestartet, Video-Dimensionen:', video.videoWidth, 'x', video.videoHeight);
                                resolve();
                            })
                            .catch(reject);
                    };
                    video.onerror = reject;
                    
                    // Timeout nach 5 Sekunden
                    setTimeout(() => reject(new Error('Video konnte nicht geladen werden')), 5000);
                });
            }
            
            if (startBtn) startBtn.style.display = 'none';
            if (stopBtn) stopBtn.style.display = 'inline-block';
            
            this.scanning = true;
            // Starte Scan-Loop nach kurzer Verzögerung, damit Video vollständig geladen ist
            setTimeout(() => this.scanForQR(), 300);
        } catch (error) {
            console.error('Fehler beim Zugriff auf die Kamera:', error);
            this.showError('Fehler beim Zugriff auf die Kamera. Bitte verwenden Sie die manuelle Eingabe.');
            this.scanning = false;
        }
    }
    
    stopScanner() {
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
        
        const video = document.getElementById('scannerVideo');
        const startBtn = document.getElementById('startScannerBtn');
        const stopBtn = document.getElementById('stopScannerBtn');
        
        if (video) {
            video.srcObject = null;
            video.style.display = 'none';
        }
        
        if (startBtn) startBtn.style.display = 'inline-block';
        if (stopBtn) stopBtn.style.display = 'none';
        
        this.scanning = false;
    }
    
    scanForQR() {
        if (!this.scanning) return;
        
        const video = document.getElementById('scannerVideo');
        const canvas = document.getElementById('scannerCanvas');
        const qrInput = document.getElementById('qr_code');
        
        if (!video || !canvas || !qrInput) {
            setTimeout(() => this.scanForQR(), 500);
            return;
        }
        
        // Prüfe ob jsQR geladen ist
        if (typeof jsQR === 'undefined' && typeof window.jsQR === 'undefined') {
            console.error('jsQR ist nicht geladen!');
            setTimeout(() => this.scanForQR(), 500);
            return;
        }
        
        const jsQRFunction = window.jsQR || jsQR;
        
        // Prüfe Video-Status
        if (video.readyState < 2) {
            // Video ist noch nicht bereit (HAVE_CURRENT_DATA)
            setTimeout(() => this.scanForQR(), 200);
            return;
        }
        
        const videoWidth = video.videoWidth;
        const videoHeight = video.videoHeight;
        
        if (videoWidth === 0 || videoHeight === 0) {
            setTimeout(() => this.scanForQR(), 200);
            return;
        }
        
        // Canvas-Größe setzen (nur wenn sich geändert hat)
        if (canvas.width !== videoWidth || canvas.height !== videoHeight) {
            canvas.width = videoWidth;
            canvas.height = videoHeight;
        }
        
        // Aktuelles Frame auf Canvas zeichnen
        const context = canvas.getContext('2d');
        context.drawImage(video, 0, 0, videoWidth, videoHeight);
        
        // Bilddaten für QR-Code-Erkennung extrahieren
        try {
            const imageData = context.getImageData(0, 0, videoWidth, videoHeight);
            
            // Verbesserte QR-Code-Erkennung mit mehreren Versuchen und Optionen
            let code = null;
            
            // Versuch 1: Standard mit Inversion
            code = jsQRFunction(imageData.data, imageData.width, imageData.height, {
                inversionAttempts: 'attemptBoth',
            });
            
            // Versuch 2: Falls nicht gefunden, mit Graustufen-Optimierung
            if (!code) {
                // Graustufen-Bild erstellen für bessere Erkennung
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
            
            // Versuch 3: Mit reduzierter Auflösung bei großen Bildern
            if (!code && (videoWidth > 1280 || videoHeight > 720)) {
                const scaleFactor = Math.min(1280 / videoWidth, 720 / videoHeight);
                const scaledWidth = Math.floor(videoWidth * scaleFactor);
                const scaledHeight = Math.floor(videoHeight * scaleFactor);
                
                // Canvas für Skalierung erstellen
                const tempCanvas = document.createElement('canvas');
                tempCanvas.width = scaledWidth;
                tempCanvas.height = scaledHeight;
                const tempContext = tempCanvas.getContext('2d');
                tempContext.drawImage(video, 0, 0, scaledWidth, scaledHeight);
                const scaledImageData = tempContext.getImageData(0, 0, scaledWidth, scaledHeight);
                
                code = jsQRFunction(scaledImageData.data, scaledImageData.width, scaledImageData.height, {
                    inversionAttempts: 'attemptBoth',
                });
            }
            
            if (code) {
                // QR-Code gefunden!
                console.log('QR-Code erkannt:', code.data);
                qrInput.value = code.data;
                this.stopScanner();
                
                // Automatisch Formular absenden
                const form = document.getElementById('returnForm');
                if (form) {
                    // Verwende dispatchEvent mit korrekten Optionen
                    const submitEvent = new Event('submit', { 
                        cancelable: true, 
                        bubbles: true 
                    });
                    form.dispatchEvent(submitEvent);
                }
            } else {
                // Weiter scannen - kontinuierlich
                requestAnimationFrame(() => this.scanForQR());
            }
        } catch (error) {
            console.error('Fehler beim Scannen:', error);
            // Bei Fehler weiter versuchen
            setTimeout(() => this.scanForQR(), 200);
        }
    }
    
    async handleSubmit(e) {
        e.preventDefault();
        
        const form = e.target;
        const formData = new FormData(form);
        
        try {
            const response = await fetch('/inventory/return', {
                method: 'POST',
                body: formData
            });
            
            // Prüfe die Antwort
            if (response.ok || response.status === 200) {
                const result = await response.text();
                
                // Wenn die Antwort erfolgreich war ODER ein Redirect erfolgt ist, zum Dashboard leiten
                // (Bei einem Redirect wird die Dashboard-HTML zurückgegeben)
                if (result.includes('erfolgreich') || 
                    result.includes('Rückgabe erfolgreich') || 
                    result.includes('Lagerverwaltung') ||
                    response.redirected ||
                    response.url.includes('/inventory/')) {
                    // Erfolgreiche Rückgabe - Zum Dashboard leiten
                    window.location.href = '/inventory/';
                } else if (result.includes('Keine aktive Ausleihe') || result.includes('fehlgeschlagen')) {
                    // Fehler - Seite neu laden um Fehlermeldung zu sehen
                    window.location.reload();
                } else {
                    // Unbekannte Antwort, aber Status OK - trotzdem zum Dashboard
                    window.location.href = '/inventory/';
                }
            } else {
                // HTTP Fehler
                const result = await response.text();
                if (result.includes('Keine aktive Ausleihe')) {
                    alert('Keine aktive Ausleihe gefunden. Bitte überprüfen Sie die Eingabe.');
                } else {
                    alert('Fehler bei der Rückgabe. Bitte versuchen Sie es erneut.');
                }
            }
        } catch (error) {
            console.error('Fehler:', error);
            alert('Fehler bei der Rückgabe. Bitte versuchen Sie es erneut.');
        }
    }
    
    showError(message) {
        const errorDiv = document.getElementById('scannerError');
        if (errorDiv) {
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
        }
    }
}

// Borrow Scanner Manager - Verwaltet die "Ausleihen geben" Seite mit Scanner und Warenkorb
class BorrowScannerManager {
    constructor() {
        this.stream = null;
        this.scanning = false;
    }
    
    init() {
        const startBtn = document.getElementById('startScannerBtn');
        const stopBtn = document.getElementById('stopScannerBtn');
        const addBtn = document.getElementById('addToCartBtn');
        const manualInput = document.getElementById('manualQrInput');
        
        if (startBtn) {
            startBtn.addEventListener('click', () => this.startScanner());
        }
        
        if (stopBtn) {
            stopBtn.addEventListener('click', () => this.stopScanner());
        }
        
        if (addBtn && manualInput) {
            addBtn.addEventListener('click', () => this.addFromInput());
            manualInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.addFromInput();
                }
            });
        }
        
        // Remove from cart buttons
        document.querySelectorAll('.remove-from-cart').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const productId = e.target.closest('.remove-from-cart').dataset.productId;
                this.removeFromCart(productId);
            });
        });
    }
    
    async startScanner() {
        if (!('getUserMedia' in navigator.mediaDevices)) {
            this.showError('Ihr Browser unterstützt keine Kamera-API.');
            return;
        }
        
        try {
            // Optimierte Kamera-Einstellungen für bessere QR-Code-Erkennung
            const constraints = {
                video: { 
                    facingMode: 'environment',
                    width: { ideal: 1920, min: 640 },
                    height: { ideal: 1080, min: 480 }
                } 
            };
            
            // Versuche erweiterte Einstellungen (nicht alle Browser unterstützen dies)
            try {
                constraints.video.advanced = [
                    { focusMode: 'continuous' },
                    { exposureMode: 'continuous' }
                ];
            } catch (e) {
                // Ignoriere wenn nicht unterstützt
            }
            
            this.stream = await navigator.mediaDevices.getUserMedia(constraints);
            
            const video = document.getElementById('scannerVideo');
            const startBtn = document.getElementById('startScannerBtn');
            const stopBtn = document.getElementById('stopScannerBtn');
            
            if (video) {
                video.srcObject = this.stream;
                video.setAttribute('playsinline', 'true');
                video.setAttribute('autoplay', 'true');
                video.style.display = 'block';
                
                // Warte bis Video bereit ist
                await new Promise((resolve, reject) => {
                    video.onloadedmetadata = () => {
                        video.play()
                            .then(() => {
                                console.log('Video gestartet (BorrowScanner), Video-Dimensionen:', video.videoWidth, 'x', video.videoHeight);
                                resolve();
                            })
                            .catch(reject);
                    };
                    video.onerror = reject;
                    
                    // Timeout nach 5 Sekunden
                    setTimeout(() => reject(new Error('Video konnte nicht geladen werden')), 5000);
                });
            }
            
            if (startBtn) startBtn.style.display = 'none';
            if (stopBtn) stopBtn.style.display = 'inline-block';
            
            this.scanning = true;
            // Starte Scan-Loop nach kurzer Verzögerung
            setTimeout(() => this.scanForQR(), 300);
        } catch (error) {
            console.error('Fehler beim Zugriff auf die Kamera:', error);
            this.showError('Fehler beim Zugriff auf die Kamera.');
            this.scanning = false;
        }
    }
    
    stopScanner() {
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
        
        const video = document.getElementById('scannerVideo');
        const startBtn = document.getElementById('startScannerBtn');
        const stopBtn = document.getElementById('stopScannerBtn');
        
        if (video) {
            video.srcObject = null;
            video.style.display = 'none';
        }
        
        if (startBtn) startBtn.style.display = 'inline-block';
        if (stopBtn) stopBtn.style.display = 'none';
        
        this.scanning = false;
    }
    
    scanForQR() {
        if (!this.scanning) return;
        
        const video = document.getElementById('scannerVideo');
        const canvas = document.getElementById('scannerCanvas');
        
        if (!video || !canvas) {
            setTimeout(() => this.scanForQR(), 500);
            return;
        }
        
        // Prüfe ob jsQR geladen ist
        if (typeof jsQR === 'undefined' && typeof window.jsQR === 'undefined') {
            console.error('jsQR ist nicht geladen!');
            setTimeout(() => this.scanForQR(), 500);
            return;
        }
        
        const jsQRFunction = window.jsQR || jsQR;
        
        // Prüfe Video-Status
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
        
        // Canvas-Größe setzen (nur wenn sich geändert hat)
        if (canvas.width !== videoWidth || canvas.height !== videoHeight) {
            canvas.width = videoWidth;
            canvas.height = videoHeight;
        }
        
        // Aktuelles Frame auf Canvas zeichnen
        const context = canvas.getContext('2d');
        context.drawImage(video, 0, 0, videoWidth, videoHeight);
        
        // Bilddaten für QR-Code-Erkennung extrahieren
        try {
            const imageData = context.getImageData(0, 0, videoWidth, videoHeight);
            
            // Verbesserte QR-Code-Erkennung mit mehreren Versuchen und Optionen
            let code = null;
            
            // Versuch 1: Standard mit Inversion
            code = jsQRFunction(imageData.data, imageData.width, imageData.height, {
                inversionAttempts: 'attemptBoth',
            });
            
            // Versuch 2: Falls nicht gefunden, mit Graustufen-Optimierung
            if (!code) {
                // Graustufen-Bild erstellen für bessere Erkennung
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
            
            // Versuch 3: Mit reduzierter Auflösung bei großen Bildern
            if (!code && (videoWidth > 1280 || videoHeight > 720)) {
                const scaleFactor = Math.min(1280 / videoWidth, 720 / videoHeight);
                const scaledWidth = Math.floor(videoWidth * scaleFactor);
                const scaledHeight = Math.floor(videoHeight * scaleFactor);
                
                // Canvas für Skalierung erstellen
                const tempCanvas = document.createElement('canvas');
                tempCanvas.width = scaledWidth;
                tempCanvas.height = scaledHeight;
                const tempContext = tempCanvas.getContext('2d');
                tempContext.drawImage(video, 0, 0, scaledWidth, scaledHeight);
                const scaledImageData = tempContext.getImageData(0, 0, scaledWidth, scaledHeight);
                
                code = jsQRFunction(scaledImageData.data, scaledImageData.width, scaledImageData.height, {
                    inversionAttempts: 'attemptBoth',
                });
            }
            
            if (code) {
                // QR-Code gefunden!
                console.log('QR-Code erkannt (BorrowScanner):', code.data);
                this.stopScanner();
                this.addToCart(code.data);
            } else {
                // Weiter scannen - kontinuierlich
                requestAnimationFrame(() => this.scanForQR());
            }
        } catch (error) {
            console.error('Fehler beim Scannen (BorrowScanner):', error);
            setTimeout(() => this.scanForQR(), 200);
        }
    }
    
    async addFromInput() {
        const input = document.getElementById('manualQrInput');
        if (input && input.value) {
            await this.addToCart(input.value);
            input.value = '';
        }
    }
    
    async addToCart(qrCode) {
        try {
            const formData = new FormData();
            formData.append('action', 'add_to_cart');
            formData.append('qr_code', qrCode);
            
            const response = await fetch('/inventory/borrow-scanner', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (result.success) {
                // Seite neu laden um Warenkorb zu aktualisieren
                window.location.reload();
            } else {
                alert(result.error || 'Fehler beim Hinzufügen zum Warenkorb');
            }
        } catch (error) {
            console.error('Fehler:', error);
            alert('Fehler beim Hinzufügen zum Warenkorb');
        }
    }
    
    async removeFromCart(productId) {
        try {
            const formData = new FormData();
            formData.append('action', 'remove_from_cart');
            formData.append('product_id', productId);
            
            const response = await fetch('/inventory/borrow-scanner', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (result.success) {
                window.location.reload();
            }
        } catch (error) {
            console.error('Fehler:', error);
            alert('Fehler beim Entfernen aus dem Warenkorb');
        }
    }
    
    showError(message) {
        const errorDiv = document.getElementById('scannerError');
        if (errorDiv) {
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
        }
    }
}

// Globale Instanzen (werden in Templates initialisiert)
let stockManager;
let borrowsManager;
let returnManager;
let borrowScannerManager;

// Markiere Produkt als gefunden (Status: available)
async function markAsFound(productId) {
    if (!confirm('Möchten Sie dieses Produkt als gefunden markieren?')) {
        return;
    }
    
    try {
        const response = await fetch(`/inventory/products/${productId}/status`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ status: 'available' })
        });
        
        const result = await response.json();
        if (result.success) {
            alert('Produkt wurde als gefunden markiert.');
            window.location.reload();
        } else {
            alert('Fehler beim Aktualisieren des Status.');
        }
    } catch (error) {
        console.error('Fehler:', error);
        alert('Fehler beim Aktualisieren des Status.');
    }
}

// Markiere Produkt als fehlend (Status: missing)
async function markAsMissing(productId) {
    if (!confirm('Möchten Sie dieses Produkt als fehlend markieren?')) {
        return;
    }
    
    try {
        const response = await fetch(`/inventory/products/${productId}/status`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ status: 'missing' })
        });
        
        const result = await response.json();
        if (result.success) {
            alert('Produkt wurde als fehlend markiert.');
            window.location.reload();
        } else {
            alert('Fehler beim Aktualisieren des Status.');
        }
    } catch (error) {
        console.error('Fehler:', error);
        alert('Fehler beim Aktualisieren des Status.');
    }
}

