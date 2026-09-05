// Inventory Management JavaScript

const INVENTORY_API_BASES = ['/inventory/api', '/inventory/vnext/api', '/vnext/api'];
let activeInventoryApiBase = INVENTORY_API_BASES[0];

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
    return `${activeInventoryApiBase}${normalizeInventoryApiPath(path)}`;
}

async function fetchInventoryApi(path, options = {}) {
    const normalizedPath = normalizeInventoryApiPath(path);
    const candidateBases = [
        activeInventoryApiBase,
        ...INVENTORY_API_BASES.filter(base => base !== activeInventoryApiBase)
    ];

    let lastResponse = null;
    let lastError = null;

    for (const base of candidateBases) {
        try {
            const response = await fetch(`${base}${normalizedPath}`, options);
            lastResponse = response;

            if (response.status !== 404) {
                activeInventoryApiBase = base;
                return response;
            }
        } catch (error) {
            lastError = error;
        }
    }

    if (lastResponse) {
        return lastResponse;
    }
    throw lastError || new Error('API-Anfrage fehlgeschlagen');
}

// Stock Manager - Verwaltet die Bestandsübersicht
class StockManager {
    constructor() {
        this.products = [];
        this.filteredProducts = [];
        this.folders = [];
        this.categories = new Set();
        this.foldersSet = new Set();
        this.conditions = new Set();
        this.locations = new Set();
        this.lengths = new Set();
        this.purchaseYears = new Set();
        this.searchTimeout = null;
        this.selectedProducts = new Set(); // Verwaltet ausgewählte Produkt-IDs
        this.currentFolderId = null; // Aktueller Ordner (aus URL)
        this.viewMode = localStorage.getItem('inventoryViewMode') || 'list'; // 'grid' oder 'list'
        this.sortField = localStorage.getItem('inventorySortField') || 'name';
        this.sortDirection = localStorage.getItem('inventorySortDirection') || 'asc';
        this.overdueProductIds = new Set();
        this.favoriteProductIds = new Set();
        this.editingFolderId = null;
        this.retiredFolderId = Number(window.INVENTORY_RETIRED_FOLDER_ID || 0) || null;
        this.isRetiredFolderView = !!window.INVENTORY_IS_RETIRED_FOLDER_VIEW;
    }

    getFilterEls(key) {
        return Array.from(document.querySelectorAll(`[data-inv-filter="${key}"]`));
    }

    getFilterValue(key) {
        const els = this.getFilterEls(key);
        const filled = els.find((el) => (el.value || '').trim() !== '');
        return (filled || els[0])?.value || '';
    }

    setFilterValue(key, value) {
        this.getFilterEls(key).forEach((el) => {
            el.value = value;
        });
    }

    fillSelectOptions(key, placeholder, values, { sortFn = null, restore = true } = {}) {
        const selects = this.getFilterEls(key);
        if (!selects.length) return;
        const currentValue = restore ? this.getFilterValue(key) : '';
        let items = Array.from(values).filter((v) => v !== null && v !== undefined && String(v).trim() !== '');
        items = sortFn ? items.sort(sortFn) : items.sort((a, b) => String(a).localeCompare(String(b), 'de'));
        selects.forEach((select) => {
            select.innerHTML = '';
            const empty = document.createElement('option');
            empty.value = '';
            empty.textContent = placeholder;
            select.appendChild(empty);
            items.forEach((val) => {
                const option = document.createElement('option');
                option.value = String(val);
                option.textContent = String(val);
                select.appendChild(option);
            });
            if (currentValue && items.map(String).includes(String(currentValue))) {
                select.value = String(currentValue);
            } else {
                select.value = '';
            }
            if (window.InventoryPillSelect) {
                window.InventoryPillSelect.enhance(select);
                window.InventoryPillSelect.sync(select);
            }
        });
    }
    
    async init() {
        // Lade aktuellen Ordner aus URL
        const urlPath = window.location.pathname;
        const folderMatch = urlPath.match(/\/stock\/(\d+)/);
        if (folderMatch) {
            this.currentFolderId = parseInt(folderMatch[1]);
        } else {
            // Explizit auf null setzen wenn wir im Root sind
            this.currentFolderId = null;
        }
        
        this.setupEventListeners();
        this.setupViewToggle();
        this.setupSortControls();
        this.applyUrlFilters();
        await this.loadFolders(); // Lade alle Ordner zuerst
        await this.loadCategories(); // Lade alle Kategorien
        await this.loadFilterOptions(); // Lade alle Filter-Optionen vom Server
        await this.loadProducts();
        // Initiale UI-Aktualisierung
        this.updateSelectionUI();
        this.applyViewMode(); // Wende gespeicherten View-Mode an
        // Wende Filter an nach dem Laden
        this.applyFilters();
        if (window.InventoryPillSelect) {
            window.InventoryPillSelect.enhanceAll(document);
        }
    }

    applyUrlFilters() {
        try {
            const params = new URLSearchParams(window.location.search);
            const dguv = (params.get('dguv') || '').trim();
            const status = (params.get('status') || '').trim();
            if (dguv) this.setFilterValue('dguvFilter', dguv);
            if (status) this.setFilterValue('statusFilter', status);
        } catch (e) {
            /* ignore */
        }
    }
    
    async loadFolders() {
        try {
            const response = await fetchInventoryApi('/folders');
            if (response.ok) {
                const foldersData = await response.json();
                this.folders = foldersData;
                // Füge auch zum Set hinzu für Filter
                foldersData.forEach(folder => {
                    this.foldersSet.add({ id: folder.id, name: folder.name });
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
    
    async loadCategories() {
        try {
            const response = await fetchInventoryApi('/categories');
            if (response.ok) {
                const categoriesData = await response.json();
                // Füge alle Kategorien zum Set hinzu
                categoriesData.forEach(cat => {
                    this.categories.add(cat);
                });
            } else {
                console.warn('Fehler beim Laden der Kategorien, verwende nur Kategorien aus Produkten');
            }
        } catch (error) {
            console.warn('Fehler beim Laden der Kategorien:', error);
            // Nicht kritisch, verwende Kategorien aus Produkten
        }
    }
    
    async loadFilterOptions() {
        try {
            // Baue URL mit optionalem folder_id Parameter
            let url = '/inventory/filter-options';
            if (this.currentFolderId !== null) {
                url += `?folder_id=${this.currentFolderId}`;
            }
            
            const response = await fetchInventoryApi(url);
            if (response.ok) {
                const filterData = await response.json();
                
                // Leere alle Filter-Sets, damit nur die Optionen für den aktuellen Ordner angezeigt werden
                this.categories.clear();
                this.conditions.clear();
                this.locations.clear();
                this.lengths.clear();
                this.purchaseYears.clear();
                
                // Aktualisiere alle Filter-Sets mit Daten vom Server (nur für aktuellen Ordner)
                if (filterData.categories && Array.isArray(filterData.categories)) {
                    filterData.categories.forEach(cat => {
                        if (cat && cat.trim()) {
                            this.categories.add(cat.trim());
                        }
                    });
                }
                
                if (filterData.conditions && Array.isArray(filterData.conditions)) {
                    filterData.conditions.forEach(cond => {
                        if (cond && cond.trim()) {
                            this.conditions.add(cond.trim());
                        }
                    });
                }
                
                if (filterData.locations && Array.isArray(filterData.locations)) {
                    filterData.locations.forEach(loc => {
                        if (loc && loc.trim()) {
                            this.locations.add(loc.trim());
                        }
                    });
                }
                
                if (filterData.lengths && Array.isArray(filterData.lengths)) {
                    filterData.lengths.forEach(len => {
                        if (len && String(len).trim()) {
                            this.lengths.add(String(len).trim());
                        }
                    });
                }
                
                if (filterData.purchase_years && Array.isArray(filterData.purchase_years)) {
                    filterData.purchase_years.forEach(year => {
                        if (year && String(year).trim()) {
                            this.purchaseYears.add(String(year).trim());
                        }
                    });
                }
                
                // Aktualisiere alle Filter-Dropdowns
                this.updateCategories();
                this.updateConditions();
                this.updateLocations();
                this.updateLengths();
                this.updatePurchaseYears();
                
            } else {
                console.warn('Fehler beim Laden der Filter-Optionen, verwende nur Optionen aus geladenen Produkten');
            }
        } catch (error) {
            console.warn('Fehler beim Laden der Filter-Optionen:', error);
            // Nicht kritisch, verwende Optionen aus geladenen Produkten
        }
    }
    
    async loadProducts() {
        try {
            // Verwende die vollständige API, um alle Attribute zu erhalten
            const params = new URLSearchParams({
                sort_by: this.sortField || 'name',
                sort_dir: this.sortDirection === 'desc' ? 'desc' : 'asc'
            });
            const response = await fetchInventoryApi(`/products?${params.toString()}`);
            
            if (!response.ok) {
                const errorText = await response.text();
                console.error('API-Fehler:', response.status, errorText);
                this.showError(`Fehler beim Laden der Produkte (Status: ${response.status})`);
                return;
            }
            
            // Prüfe Content-Type bevor JSON geparst wird
            const contentType = response.headers.get('content-type');
            let data;
            
            if (contentType && contentType.includes('application/json')) {
                data = await response.json();
            } else {
                // Wenn keine JSON-Antwort, versuche Text zu lesen
                const text = await response.text();
                console.error('Ungültige Antwort vom Server beim Laden der Produkte:', text);
                this.showError('Ungültige Antwort vom Server. Bitte laden Sie die Seite neu.');
                return;
            }
            
            // Unterstütze sowohl Legacy-Format (Array) als auch vNext-Format ({ products: [...] })
            if (!Array.isArray(data) && data && Array.isArray(data.products)) {
                data = data.products;
            }

            if (!Array.isArray(data)) {
                console.error('Ungültige API-Antwort:', data);
                this.showError('Ungültige Daten vom Server erhalten');
                return;
            }
            
            this.products = data;
            
            // Ergänze Filter-Werte aus den geladenen Produkten (überschreibt nicht die Server-Daten)
            // Dies muss NACH dem Laden der Produkte erfolgen
            this.extractCategories();
            
            // Aktualisiere Filter-Dropdowns (falls neue Werte hinzugefügt wurden)
            this.updateCategories();
            this.updateConditions();
            this.updateLocations();
            this.updateLengths();
            this.updatePurchaseYears();
            this.updateTrashFooterCount();
            
            // Wende Filter an (nicht direkt renderProducts, damit Filterlogik angewendet wird)
            this.applyFilters();
        } catch (error) {
            console.error('Fehler beim Laden der Produkte:', error);
            this.showError(`Fehler beim Laden der Produkte: ${error.message}`);
        }
    }
    
    extractCategories() {
        // NICHT die Sets leeren - die Filter-Optionen wurden bereits vom Server geladen
        // Nur zusätzliche Werte aus den aktuell geladenen Produkten hinzufügen
        // (falls neue Produkte hinzugefügt wurden, die noch nicht im Server-Index sind)
        
        // Extrahiere alle verfügbaren Werte aus den Produkten
        this.products.forEach(p => {
            // Kategorien
            if (this.isValidValue(p.category)) {
                this.categories.add(p.category.trim());
            }
            
            // Ordner
            if (p.folder_id && this.isValidValue(p.folder_name)) {
                this.foldersSet.add({ id: p.folder_id, name: p.folder_name.trim() });
            }
            
            // Zustände
            if (this.isValidValue(p.condition)) {
                this.conditions.add(p.condition.trim());
            }
            
            // Lagerorte
            if (this.isValidValue(p.location)) {
                this.locations.add(p.location.trim());
            }
            
            // Längen
            if (this.isValidValue(p.length)) {
                // Füge sowohl das Original-Format als auch normalisierte Version hinzu
                const lengthStr = p.length.trim();
                this.lengths.add(lengthStr);
            }
            
            // Anschaffungsjahre
            if (p.purchase_date) {
                try {
                    // Extrahiere Jahr aus Datum (Format: YYYY-MM-DD oder YYYY-MM-DDTHH:mm:ss)
                    const dateStr = String(p.purchase_date);
                    const year = dateStr.substring(0, 4);
                    if (year && year !== 'null' && year !== 'undefined' && /^\d{4}$/.test(year)) {
                        this.purchaseYears.add(year);
                    }
                } catch (e) {
                    // Ignoriere Fehler beim Parsen des Datums
                    console.warn('Fehler beim Parsen des Anschaffungsdatums:', p.purchase_date, e);
                }
            }
        });
        
    }
    
    // Öffentliche Methode zum Aktualisieren der Filter (kann von außen aufgerufen werden)
    async refreshFilters() {
        // Lade Filter-Optionen neu (mit aktuellem Ordner)
        await this.loadFilterOptions();
        // Lade Produkte neu und aktualisiere Filter
        await this.loadProducts();
    }
    
    updateCategories() {
        this.fillSelectOptions('categoryFilter', 'Alle Kategorien', this.categories);
    }
    
    updateFolders() {
        // Ordner-Filter entfernt — Navigation über Ordner-Tiles
    }
    
    updateConditions() {
        this.fillSelectOptions('conditionFilter', 'Alle Zustände', this.conditions);
    }
    
    updateLocations() {
        this.fillSelectOptions('locationFilter', 'Alle Lagerorte', this.locations);
    }
    
    updateLengths() {
        this.fillSelectOptions('lengthFilter', 'Alle Längen', this.lengths, {
            sortFn: (a, b) => {
                const numA = parseFloat(String(a).replace(/[^0-9.]/g, '')) || 0;
                const numB = parseFloat(String(b).replace(/[^0-9.]/g, '')) || 0;
                if (numA !== numB) return numA - numB;
                return String(a).localeCompare(String(b), 'de');
            },
        });
    }
    
    updatePurchaseYears() {
        this.fillSelectOptions('purchaseYearFilter', 'Alle Jahre', this.purchaseYears, {
            sortFn: (a, b) => (parseInt(String(b), 10) || 0) - (parseInt(String(a), 10) || 0),
        });
    }
    
    setupEventListeners() {
        const filterKeys = [
            'searchInput', 'categoryFilter', 'statusFilter', 'favoritesFilter',
            'conditionFilter', 'locationFilter', 'lengthFilter', 'purchaseYearFilter',
            'serialPresenceFilter', 'dguvFilter',
        ];

        filterKeys.forEach((key) => {
            this.getFilterEls(key).forEach((el) => {
                const eventName = key === 'searchInput' ? 'input' : 'change';
                el.addEventListener(eventName, () => {
                    this.getFilterEls(key).forEach((other) => {
                        if (other !== el) other.value = el.value;
                    });
                    if (key === 'searchInput') {
                        clearTimeout(this.searchTimeout);
                        this.searchTimeout = setTimeout(() => this.applyFilters(), 300);
                        return;
                    }
                    this.applyFilters();
                });
            });
        });

        document.querySelectorAll('.inventory-reset-filters-btn').forEach((btn) => {
            btn.addEventListener('click', () => this.resetFilters());
        });

        const bulkSelectAllBtn = document.getElementById('bulkSelectAllBtn');
        const bulkDeselectAllBtn = document.getElementById('bulkDeselectAllBtn');
        const bulkEditBtn = document.getElementById('bulkEditBtn');
        const bulkBorrowBtn = document.getElementById('bulkBorrowBtn');
        const bulkDeleteBtn = document.getElementById('bulkDeleteBtn');
        const bulkRestoreBtn = document.getElementById('bulkRestoreBtn');
        const bulkQrBtn = document.getElementById('bulkQrBtn');
        const bulkRepairBtn = document.getElementById('bulkRepairBtn');
        const bulkAvailableBtn = document.getElementById('bulkAvailableBtn');

        if (bulkSelectAllBtn) bulkSelectAllBtn.addEventListener('click', () => this.selectAllAvailable());
        if (bulkDeselectAllBtn) bulkDeselectAllBtn.addEventListener('click', () => this.deselectAll());
        if (bulkEditBtn) bulkEditBtn.addEventListener('click', () => this.openBulkEditModal());
        if (bulkBorrowBtn) bulkBorrowBtn.addEventListener('click', () => this.borrowSelected());
        if (bulkQrBtn) bulkQrBtn.addEventListener('click', () => this.printSelectedQr());
        if (bulkRepairBtn) bulkRepairBtn.addEventListener('click', () => this.markSelectedInRepair());
        if (bulkAvailableBtn) bulkAvailableBtn.addEventListener('click', () => this.markSelectedAvailable());
        if (bulkDeleteBtn) bulkDeleteBtn.addEventListener('click', () => this.openBulkDeleteModal());
        if (bulkRestoreBtn) bulkRestoreBtn.addEventListener('click', () => this.restoreSelectedProducts());
    }
    
    setupSortControls() {
        const validFields = [
            'name', 'category', 'condition', 'length',
            'location', 'status', 'purchase_date', 'serial_number',
        ];
        if (!validFields.includes(this.sortField)) {
            this.sortField = 'name';
        }
        if (!['asc', 'desc'].includes(this.sortDirection)) {
            this.sortDirection = 'asc';
        }

        this.setFilterValue('sortField', this.sortField);
        this.setFilterValue('sortDirection', this.sortDirection);

        this.getFilterEls('sortField').forEach((sortFieldSelect) => {
            sortFieldSelect.addEventListener('change', () => {
                const selectedValue = sortFieldSelect.value;
                this.sortField = validFields.includes(selectedValue) ? selectedValue : 'name';
                this.setFilterValue('sortField', this.sortField);
                localStorage.setItem('inventorySortField', this.sortField);
                this.applyFilters();
            });
        });

        this.getFilterEls('sortDirection').forEach((sortDirectionSelect) => {
            sortDirectionSelect.addEventListener('change', () => {
                const selectedValue = sortDirectionSelect.value === 'desc' ? 'desc' : 'asc';
                this.sortDirection = selectedValue;
                this.setFilterValue('sortDirection', this.sortDirection);
                localStorage.setItem('inventorySortDirection', this.sortDirection);
                this.applyFilters();
            });
        });

        document.querySelectorAll('.inventory-reset-sort-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                this.sortField = 'name';
                this.sortDirection = 'asc';
                localStorage.removeItem('inventorySortField');
                localStorage.removeItem('inventorySortDirection');
                this.setFilterValue('sortField', 'name');
                this.setFilterValue('sortDirection', 'asc');
                this.applyFilters();
            });
        });
    }
    
    applyFilters() {
        const search = (this.getFilterValue('searchInput') || '').trim();
        const searchLower = search.toLowerCase();
        const category = this.getFilterValue('categoryFilter') || '';
        const status = this.getFilterValue('statusFilter') || '';
        const condition = this.getFilterValue('conditionFilter') || '';
        const location = this.getFilterValue('locationFilter') || '';
        const length = this.getFilterValue('lengthFilter') || '';
        const purchaseYear = this.getFilterValue('purchaseYearFilter') || '';
        const serialPresence = this.getFilterValue('serialPresenceFilter') || '';
        const dguv = this.getFilterValue('dguvFilter') || '';
        const favoritesOnly = this.getFilterValue('favoritesFilter') === 'favorites';
        const today = new Date().toISOString().slice(0, 10);
        
        this.filteredProducts = this.products.filter(p => {
            const matchesSearch = !search || this.matchesSearch(p, searchLower);
            
            let matchesFolder = true;
            if (this.currentFolderId !== null && this.currentFolderId !== undefined) {
                matchesFolder = Number(p.folder_id) === Number(this.currentFolderId);
            } else if (!search) {
                // Root: nur Produkte ohne Ordner — Ordnerprodukte nur im jeweiligen Ordner
                matchesFolder = !p.folder_id;
            }
            
            const matchesCategory = !category || (p.category !== null && p.category !== undefined && p.category === category);
            let matchesStatus = true;
            if (status === 'overdue') {
                matchesStatus = this.overdueProductIds.has(Number(p.id));
            } else if (status === 'defective_repair') {
                matchesStatus = p.status === 'defective' || p.status === 'in_repair';
            } else if (status) {
                matchesStatus = p.status !== null && p.status !== undefined && p.status === status;
            }
            const matchesFavorites = !favoritesOnly || this.favoriteProductIds.has(Number(p.id));
            const matchesCondition = !condition || (p.condition !== null && p.condition !== undefined && p.condition === condition);
            const matchesLocation = !location || (p.location !== null && p.location !== undefined && p.location === location);
            const matchesLength = !length || this.matchesLength(p, length);
            const matchesPurchaseYear = !purchaseYear || this.matchesPurchaseYear(p, purchaseYear);

            const hasSerial = !!(p.serial_number && String(p.serial_number).trim());
            const matchesSerial = !serialPresence
                || (serialPresence === 'with' && hasSerial)
                || (serialPresence === 'without' && !hasSerial);

            const dguvDate = p.dguv_next_check ? String(p.dguv_next_check).slice(0, 10) : '';
            const matchesDguv = !dguv
                || (dguv === 'due' && dguvDate && dguvDate <= today)
                || (dguv === 'ok' && dguvDate && dguvDate > today)
                || (dguv === 'none' && !dguvDate);
            
            return matchesSearch && matchesFolder && matchesCategory && matchesStatus &&
                   matchesFavorites && matchesCondition && matchesLocation && matchesLength &&
                   matchesPurchaseYear && matchesSerial && matchesDguv;
        });
        
        this.sortFilteredProducts();
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
    
    matchesLength(product, filterLength) {
        // Wenn kein Filter gesetzt, immer true
        if (!filterLength) return true;
        
        // Wenn Produkt keine Länge hat, nicht matchen
        if (!product.length && !product.length_meters) return false;
        
        // Versuche zuerst exakte Übereinstimmung mit length (String)
        if (product.length && product.length === filterLength) {
            return true;
        }
        
        // Falls length_meters verfügbar ist, vergleiche numerisch
        // Konvertiere filterLength zu Meter-Wert für Vergleich
        if (product.length_meters !== null && product.length_meters !== undefined) {
            // Versuche filterLength zu parsen (könnte "5m", "5.5", etc. sein)
            const filterMeters = this.parseLengthToMeters(filterLength);
            if (filterMeters !== null) {
                // Vergleiche mit Toleranz für Fließkommazahlen
                return Math.abs(product.length_meters - filterMeters) < 0.001;
            }
        }
        
        // Fallback: String-Vergleich (case-insensitive)
        if (product.length) {
            return product.length.toLowerCase() === filterLength.toLowerCase();
        }
        
        return false;
    }
    
    parseLengthToMeters(lengthStr) {
        // Einfacher Parser für Längenangaben (z.B. "5m", "5.5m", "120cm", "5")
        if (!lengthStr || typeof lengthStr !== 'string') return null;
        
        const trimmed = lengthStr.trim().toLowerCase();
        if (!trimmed) return null;
        
        // Entferne Leerzeichen zwischen Zahl und Einheit
        const normalized = trimmed.replace(/\s+/g, '');
        
        // Extrahiere Zahl und Einheit
        const match = normalized.match(/^([\d.]+)\s*(m|cm|mm)?$/);
        if (!match) return null;
        
        const value = parseFloat(match[1]);
        const unit = match[2] || 'm';
        
        if (isNaN(value)) return null;
        
        // Konvertiere zu Metern
        if (unit === 'm') return value;
        if (unit === 'cm') return value / 100;
        if (unit === 'mm') return value / 1000;
        
        return value; // Default: Meter
    }
    
    resetFilters() {
        [
            'searchInput', 'categoryFilter', 'statusFilter', 'favoritesFilter',
            'conditionFilter', 'locationFilter', 'lengthFilter', 'purchaseYearFilter',
            'serialPresenceFilter', 'dguvFilter',
        ].forEach((key) => this.setFilterValue(key, ''));
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
        // Navigiere zum Ordner (Ordner-Filter wurde entfernt, daher Navigation verwenden)
        // Diese Funktion wird möglicherweise noch für Navigation verwendet
        // Falls nicht mehr benötigt, kann sie entfernt werden
        window.location.href = `/inventory/stock/${folderId}`;
    }
    
    renderProducts() {
        if (this.viewMode === 'grid') {
            this.renderProductsGrid();
        } else {
            this.renderProductsList();
        }
    }

    getVisibleFolders() {
        const hasSearch = (this.getFilterValue('searchInput') || '').trim() !== '';
        if (hasSearch) return [];
        // Flat folders: nur im Root anzeigen
        if (this.currentFolderId !== null && this.currentFolderId !== undefined) return [];
        const folders = Array.isArray(this.folders) ? this.folders.slice() : [];
        // Papierkorb nicht als Grid-/Listen-Ordner, sondern als Footer in der Bestandsansicht
        if (!this.retiredFolderId) return folders;
        return folders.filter((folder) => Number(folder.id) !== Number(this.retiredFolderId));
    }

    updateTrashFooterCount() {
        const label = document.getElementById('inventoryTrashCountLabel');
        if (!label || !this.retiredFolderId) return;
        const count = (this.products || []).filter(
            (p) => Number(p.folder_id) === Number(this.retiredFolderId) || p.status === 'retired'
        ).length;
        label.textContent = count > 0
            ? `${count} Gerät${count === 1 ? '' : 'e'}`
            : 'Leer';
    }
    
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
    }
    
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
    }

    /** Checkbox: alles außer ausgemustert. Ausleihen nur bei available. */
    isProductSelectable(product) {
        if (!product) return false;
        if (this.isRetiredFolderView) {
            return product.status === 'retired';
        }
        return product.status !== 'retired';
    }

    isProductBorrowable(product) {
        if (!product || product.status !== 'available') return false;
        if (product.item_type === 'consumable') {
            return Number(product.available || 0) > 0;
        }
        return true;
    }

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
    }

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
    }

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
    }

    buildProductContextMenuHtml(product) {
        const id = product.id;
        return `<div class="context-menu-source d-none" id="context-menu-product-${id}"><ul class="dropdown-menu inventory-actions-menu">${this.buildProductActionItemsHtml(product)}</ul></div>`;
    }

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
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
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
    }
    
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
    }
    
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
    }
    
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
                        <button type="button" class="btn btn-sm inventory-pill-btn inventory-pill-btn--outline"
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
                        <a href="/inventory/products/${product.id}/documents" class="btn btn-sm inventory-pill-btn inventory-pill-btn--outline">Alle verwalten</a>
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
                            ? `<a href="/inventory/products/${product.id}/borrow" class="btn inventory-pill-btn inventory-pill-btn--primary">Ausleihen</a>`
                            : ''}
                        <a href="/inventory/products/${product.id}/edit" class="btn inventory-pill-btn inventory-pill-btn--outline">Bearbeiten</a>
                        <a href="/inventory/products/${product.id}/documents" class="btn inventory-pill-btn inventory-pill-btn--outline">
                            <i class="bi bi-file-earmark"></i> Dokumente
                        </a>
                        <button type="button" class="btn inventory-pill-btn inventory-pill-btn--outline favorite-btn"
                                data-product-id="${product.id}"
                                onclick="toggleFavorite(${product.id});">
                            <i class="bi bi-star"></i> Favorit
                        </button>
                        ${product.status === 'available'
                            ? `<button class="btn inventory-pill-btn inventory-pill-btn--outline-warning" onclick="markAsInRepair(${product.id})">In Reparatur</button>`
                            : ''}
                        ${(product.status === 'defective' || product.status === 'in_repair')
                            ? `<button class="btn inventory-pill-btn inventory-pill-btn--outline-success" onclick="markAsAvailable(${product.id})">Als einsatzbereit</button>`
                            : ''}
                        ${product.status !== 'defective' && product.status !== 'retired' && product.status !== 'in_repair'
                            ? `<button class="btn inventory-pill-btn inventory-pill-btn--outline-danger" onclick="markAsDefective(${product.id})">Als defekt markieren</button>`
                            : ''}
                        ${product.status === 'missing'
                            ? `<button class="btn inventory-pill-btn inventory-pill-btn--outline-success" onclick="markAsFound(${product.id})">Als gefunden markieren</button>`
                            : product.status !== 'retired'
                                ? `<button class="btn inventory-pill-btn inventory-pill-btn--outline-danger" onclick="markAsMissing(${product.id})">Als fehlend markieren</button>`
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
    }

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
    }

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
    }

    formatDateDe(value) {
        if (!this.isValidValue(value)) return '—';
        const raw = String(value).slice(0, 10);
        const d = new Date(`${raw}T00:00:00`);
        if (Number.isNaN(d.getTime())) return this.escapeHtml(raw);
        return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
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
    
    showSuccess(message) {
        inventoryNotify(message, 'success');
    }
    
    handleCardClick(productId, isSelectable) {
        // Wenn bereits Auswahl aktiv ist und Produkt auswählbar, toggle Auswahl
        if (this.selectedProducts.size > 0 && isSelectable) {
            this.toggleProductSelection(productId);
        } else {
            // Sonst Details anzeigen
            this.showProductDetail(productId);
        }
    }
    
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
    }
    
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
    }

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
    }
    
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
    }

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
    }

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
    }

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
    }
    
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
    }
    
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
    }
    
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
    }

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
    }

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
    }
    
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
    }

    // View Toggle Funktionen
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
        
        // Rendere Produkte neu mit aktuellem View-Mode
        this.renderProducts();
    }
    
    // Ordner-Funktionen
    renderFolders() {
        // Ordner werden zusammen mit Produkten in renderProducts* gerendert
        this.renderProducts();
    }
    
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
    }
    
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
    }

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
    }

    startFolderInlineEdit(folderId) {
        this.editingFolderId = Number(folderId);
        this.renderProducts();
        const nameInput = document.getElementById(`inventoryFolderEditName${folderId}`);
        if (nameInput) {
            nameInput.focus();
            nameInput.select();
        }
    }

    cancelFolderInlineEdit() {
        this.editingFolderId = null;
        this.renderProducts();
    }

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
    }
    
    navigateToFolder(folderId) {
        window.location.href = `/inventory/stock/${folderId}`;
    }
    
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
    }
    
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
    }
}

// Borrows Manager - Verwaltet die Ausleih-Übersicht
class BorrowsManager {
    constructor() {
        this.borrows = [];
        this.filteredBorrows = [];
    }

    getFilterEls(key) {
        return Array.from(document.querySelectorAll(`[data-inv-filter="${key}"]`));
    }

    getFilterValue(key) {
        const els = this.getFilterEls(key);
        if (!els.length) return '';
        if (els[0].type === 'checkbox') {
            return els.some((el) => el.checked);
        }
        return els[0]?.value || '';
    }

    setFilterValue(key, value) {
        this.getFilterEls(key).forEach((el) => {
            if (el.type === 'checkbox') {
                el.checked = !!value;
            } else {
                el.value = value;
                if (window.InventoryPillSelect) {
                    window.InventoryPillSelect.sync(el);
                }
            }
        });
    }
    
    async init() {
        this.setupFilterListeners();
        if (window.InventoryPillSelect) {
            window.InventoryPillSelect.enhanceAll(document);
        }
        await this.loadBorrows();
        this.renderBorrows();
        setInterval(() => this.loadBorrows(), 30000);
    }

    setupFilterListeners() {
        const textKeys = ['filterBorrower', 'filterEvent', 'filterProduct', 'filterDateFrom', 'filterDateTo'];
        textKeys.forEach((key) => {
            this.getFilterEls(key).forEach((el) => {
                el.addEventListener('input', () => {
                    this.getFilterEls(key).forEach((other) => {
                        if (other !== el) other.value = el.value;
                    });
                    this.applyFilters();
                });
            });
        });

        this.getFilterEls('filterStatus').forEach((el) => {
            el.addEventListener('change', () => {
                this.setFilterValue('filterStatus', el.value || 'all');
                this.applyFilters();
            });
        });

        this.getFilterEls('filterMine').forEach((el) => {
            el.addEventListener('change', () => {
                this.setFilterValue('filterMine', el.checked);
                this.applyFilters();
            });
        });
    }
    
    async loadBorrows() {
        try {
            const response = await fetchInventoryApi('/borrows?status=all');
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
        const borrowerFilter = (this.getFilterValue('filterBorrower') || '').toLowerCase();
        const eventFilter = (this.getFilterValue('filterEvent') || '').toLowerCase();
        const productFilter = (this.getFilterValue('filterProduct') || '').toLowerCase();
        const statusFilter = this.getFilterValue('filterStatus') || 'all';
        const mineOnly = !!this.getFilterValue('filterMine');
        const dateFrom = this.getFilterValue('filterDateFrom') || '';
        const dateTo = this.getFilterValue('filterDateTo') || '';
        const uid = window.currentUserId;
        
        this.filteredBorrows = this.borrows.filter(b => {
            const matchesBorrower = !borrowerFilter ||
                (b.borrower_name && b.borrower_name.toLowerCase().includes(borrowerFilter)) ||
                (b.contact_email && b.contact_email.toLowerCase().includes(borrowerFilter));
            const matchesEvent = !eventFilter ||
                (b.event_name && b.event_name.toLowerCase().includes(eventFilter));
            const matchesProduct = !productFilter ||
                (b.product_name && b.product_name.toLowerCase().includes(productFilter));

            let matchesStatus = true;
            if (statusFilter === 'active') {
                matchesStatus = b.status !== 'returned' && !b.is_overdue;
            } else if (statusFilter === 'overdue') {
                matchesStatus = !!b.is_overdue;
            } else if (statusFilter === 'returned') {
                matchesStatus = b.status === 'returned';
            }

            const matchesMine = !mineOnly || b.borrower_id === uid || b.created_by === uid;

            let matchesDate = true;
            if (dateFrom || dateTo) {
                const d = b.borrow_date ? b.borrow_date.substring(0, 10) : '';
                if (dateFrom && d && d < dateFrom) matchesDate = false;
                if (dateTo && d && d > dateTo) matchesDate = false;
            }

            return matchesBorrower && matchesEvent && matchesProduct && matchesStatus && matchesMine && matchesDate;
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
                    <td colspan="8">
                        <div class="mod-empty-state py-5 text-center">
                            <i class="bi bi-clock-history d-block mb-2 fs-3 text-muted" aria-hidden="true"></i>
                            <p class="text-muted mb-0">Keine Ausleihen gefunden</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }
        
        tbody.innerHTML = this.filteredBorrows.map(borrow => {
            let statusBadge = '<span class="badge bg-warning text-dark">Aktiv</span>';
            if (borrow.status === 'returned') {
                statusBadge = '<span class="badge bg-secondary">Zurückgegeben</span>';
            } else if (borrow.is_overdue) {
                statusBadge = '<span class="badge bg-danger">Überfällig</span>';
            }
            const checkoutId = borrow.checkout_id || borrow.id;
            const isReturned = borrow.status === 'returned';
            const borrowPdf = resolveInventoryApiUrl(`/borrow/${checkoutId}/pdf`);
            const returnPdf = resolveInventoryApiUrl(`/borrow/${borrow.id}/return-pdf`);
            const returnHref = `/inventory/checkout?transaction_number=${encodeURIComponent(borrow.transaction_number)}`;

            const hoverReturn = isReturned
                ? `<a class="btn btn-sm btn-link" href="${returnPdf}" title="Rückgabeschein" onclick="event.stopPropagation()">
                        <i class="bi bi-file-earmark-check"></i>
                   </a>`
                : `<a class="btn btn-sm btn-link" href="${returnHref}" title="Zurückgeben" onclick="event.stopPropagation()">
                        <i class="bi bi-arrow-return-left"></i>
                   </a>`;

            const menuReturn = isReturned
                ? `<li><a class="dropdown-item" href="${returnPdf}"><i class="bi bi-file-earmark-check me-2"></i>Rückgabeschein</a></li>`
                : `<li><a class="dropdown-item" href="${returnHref}"><i class="bi bi-arrow-return-left me-2"></i>Zurückgeben</a></li>`;

            const setBadge = borrow.source_set_name
                ? `<span class="badge inventory-set-badge" title="Aus Produktset"><i class="bi bi-collection" aria-hidden="true"></i> Set</span>`
                : '';
            const setDropdown = this.buildBorrowSetDropdown(borrow);
            const isExternal = !borrow.borrower_id;
            const contactEmail = (borrow.contact_email || '').trim();
            let externalBadge = '';
            if (isExternal) {
                const emailEscaped = this.escapeHtml(contactEmail);
                const composeHref = contactEmail
                    ? `/email/compose?to=${encodeURIComponent(contactEmail)}`
                    : '';
                const menuWidthStyle = contactEmail
                    ? `style="min-width: ${Math.max(contactEmail.length + 4, 18)}ch"`
                    : '';
                const dropdownBody = contactEmail
                    ? `<li class="px-3 py-2">
                            <div class="small text-muted mb-1">Kontakt-E-Mail</div>
                            <div class="fw-semibold text-nowrap">${emailEscaped}</div>
                       </li>
                       <li><hr class="dropdown-divider"></li>
                       <li>
                            <a class="dropdown-item" href="${composeHref}">
                                <i class="bi bi-envelope me-2" aria-hidden="true"></i>E-Mail schreiben
                            </a>
                       </li>`
                    : `<li class="px-3 py-2 small text-muted text-nowrap">Keine E-Mail hinterlegt</li>`;
                externalBadge = `
                    <div class="dropdown d-inline-block">
                        <button type="button"
                                class="badge inventory-extern-badge border-0"
                                data-bs-toggle="dropdown"
                                aria-expanded="false"
                                title="Externe Person"
                                onclick="event.stopPropagation()">
                            Extern
                        </button>
                        <ul class="dropdown-menu inventory-actions-menu" ${menuWidthStyle} onclick="event.stopPropagation()">
                            ${dropdownBody}
                        </ul>
                    </div>`;
            }

            return `
            <tr class="mod-list-row ${borrow.is_overdue ? 'table-danger' : ''}">
                <td><code>${this.escapeHtml(borrow.transaction_number || '')}</code></td>
                <td class="d-none d-md-table-cell">${this.escapeHtml(borrow.event_name || '—')}</td>
                <td>
                    <div class="d-flex flex-wrap align-items-center gap-2">
                        <strong>${this.escapeHtml(borrow.product_name || '')}</strong>
                        ${setBadge}
                    </div>
                    ${setDropdown}
                </td>
                <td class="d-none d-md-table-cell">
                    <div class="d-flex flex-wrap align-items-center gap-2">
                        <span>${this.escapeHtml(borrow.borrower_name || 'Unbekannt')}</span>
                        ${externalBadge}
                    </div>
                </td>
                <td class="d-none d-lg-table-cell">${borrow.borrow_date ? new Date(borrow.borrow_date).toLocaleDateString('de-DE') : '—'}</td>
                <td class="d-none d-md-table-cell">${borrow.expected_return_date ? new Date(borrow.expected_return_date).toLocaleDateString('de-DE') : '—'}</td>
                <td>${statusBadge}</td>
                <td class="text-end">
                    <div class="mod-list-actions">
                        <div class="mod-list-hover-actions">
                            ${hoverReturn}
                            <a class="btn btn-sm btn-link" href="${borrowPdf}" title="Ausleihschein" onclick="event.stopPropagation()">
                                <i class="bi bi-file-pdf"></i>
                            </a>
                        </div>
                        <div class="dropdown d-inline-block">
                            <button class="btn btn-sm btn-link" type="button" data-bs-toggle="dropdown" aria-expanded="false" onclick="event.stopPropagation()">
                                <i class="bi bi-three-dots-vertical"></i>
                            </button>
                            <ul class="dropdown-menu dropdown-menu-end inventory-actions-menu">
                                ${menuReturn}
                                <li><a class="dropdown-item" href="${borrowPdf}"><i class="bi bi-file-pdf me-2"></i>Ausleihschein</a></li>
                            </ul>
                        </div>
                    </div>
                </td>
            </tr>`;
        }).join('');
    }

    buildBorrowSetDropdown(borrow) {
        const members = Array.isArray(borrow.source_set_members) ? borrow.source_set_members : [];
        if (!borrow.source_set_name || !members.length) return '';
        const setName = this.escapeHtml(borrow.source_set_name);
        const memberHtml = members.map((member) => {
            const qty = member.quantity && member.quantity > 1
                ? ` <span class="badge bg-secondary">×${this.escapeHtml(String(member.quantity))}</span>`
                : '';
            return `<li><i class="bi bi-box-seam text-muted" aria-hidden="true"></i><span>${this.escapeHtml(member.name || '—')}</span>${qty}</li>`;
        }).join('');
        return `
            <details class="inventory-set-members mt-1">
                <summary class="inventory-set-members-summary">${setName} · Bestandteile</summary>
                <ul class="inventory-set-members-list">${memberHtml}</ul>
            </details>
        `;
    }

    escapeHtml(text) {
        if (text == null) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
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
        
        if (startBtn) {
            startBtn.addEventListener('click', () => this.startScanner());
        }
        
        if (stopBtn) {
            stopBtn.addEventListener('click', () => this.stopScanner());
        }
        
        // Wichtig: Kein AJAX-Submit hier.
        // Die Rückgabe-Seite nutzt Server-Rendering (inkl. Artikelauswahl bei Gruppen-Ausleihe).
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
            
            // Zeige Scanner-Container SOFORT, bevor Video geladen wird
            const scannerContainer = document.getElementById('scannerContainer');
            if (scannerContainer) {
                scannerContainer.style.cssText = 'display: block !important; visibility: visible !important; opacity: 1 !important; height: auto !important; position: relative !important;';
                // Force reflow
                scannerContainer.offsetHeight;
            }
            
            if (video) {
                // Stelle sicher, dass Video-Element sichtbar ist - mit !important
                video.style.cssText = 'display: block !important; visibility: visible !important; opacity: 1 !important; width: 100% !important; height: 400px !important;';
                
                video.srcObject = this.stream;
                video.setAttribute('playsinline', 'true');
                video.setAttribute('autoplay', 'true');
                video.setAttribute('muted', 'true'); // Muted für bessere Browser-Kompatibilität
                
                // Verstecke Fehlermeldung
                this.hideError();
                
                // Warte bis Video bereit ist
                await new Promise((resolve, reject) => {
                    const timeout = setTimeout(() => {
                        reject(new Error('Video konnte nicht geladen werden'));
                    }, 10000);
                    
                    const onLoadedMetadata = () => {
                        clearTimeout(timeout);
                        video.play()
                            .then(() => {
                                // Stelle sicher, dass Video sichtbar ist
                                video.style.cssText = 'display: block !important; visibility: visible !important; opacity: 1 !important; width: 100% !important; height: 400px !important;';
                                // Stelle sicher, dass Container auch sichtbar ist
                                if (scannerContainer) {
                                    scannerContainer.style.cssText = 'display: block !important; visibility: visible !important; opacity: 1 !important; height: auto !important; position: relative !important;';
                                }
                                // Force reflow um sicherzustellen, dass Browser rendert
                                video.offsetHeight;
                                scannerContainer.offsetHeight;
                                video.removeEventListener('loadedmetadata', onLoadedMetadata);
                                resolve();
                            })
                            .catch((err) => {
                                video.removeEventListener('loadedmetadata', onLoadedMetadata);
                                reject(err);
                            });
                    };
                    
                    video.addEventListener('loadedmetadata', onLoadedMetadata);
                    video.onerror = () => {
                        clearTimeout(timeout);
                        video.removeEventListener('loadedmetadata', onLoadedMetadata);
                        reject(new Error('Video-Fehler'));
                    };
                    
                    // Falls Video bereits geladen ist
                    if (video.readyState >= 2) {
                        onLoadedMetadata();
                    }
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
        const scannerContainer = document.getElementById('scannerContainer');
        const scannerFrame = document.getElementById('scannerFrame');
        const successPopup = document.getElementById('scannerSuccessPopup');
        
        if (video) {
            video.srcObject = null;
            video.style.display = 'none';
        }
        
        // Verstecke Container komplett
        if (scannerContainer) {
            scannerContainer.style.display = 'none';
        }
        
        // Entferne Erfolgs-Klasse vom Rahmen
        if (scannerFrame) {
            scannerFrame.classList.remove('scanner-success');
        }
        
        // Verstecke Popup
        if (successPopup) {
            successPopup.style.display = 'none';
        }
        
        // Reset Scan-Linie
        const scannerLine = document.getElementById('scannerLine');
        if (scannerLine) {
            scannerLine.classList.remove('animate');
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
                qrInput.value = code.data;
                
                // Friere Video kurz ein und zeige Scan-Animation
                this.freezeAndAnimate().then(() => {
                    // Zeige visuelles Feedback
                    this.showScanSuccess();
                    
                    // Warte kurz bevor Scanner gestoppt wird (für visuelles Feedback)
                    setTimeout(() => {
                        this.stopScanner();
                        
                        // Automatisch Formular absenden
                        const form = document.getElementById('returnForm');
                        if (form) {
                            if (typeof form.requestSubmit === 'function') {
                                form.requestSubmit();
                            } else {
                                form.submit();
                            }
                        }
                    }, 500);
                });
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
    
    showError(message) {
        const errorDiv = document.getElementById('scannerError');
        if (errorDiv) {
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
        }
    }
    
    hideError() {
        const errorDiv = document.getElementById('scannerError');
        if (errorDiv) {
            errorDiv.style.display = 'none';
        }
    }
    
    freezeAndAnimate() {
        return new Promise((resolve) => {
            const video = document.getElementById('scannerVideo');
            const scannerLine = document.getElementById('scannerLine');
            
            if (!video || !scannerLine) {
                resolve();
                return;
            }
            
            // Speichere aktuelles Frame als Canvas-Bild
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth || 640;
            canvas.height = video.videoHeight || 480;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            
            // Erstelle temporäres Bild-Element
            const frozenImage = new Image();
            frozenImage.src = canvas.toDataURL();
            frozenImage.style.cssText = 'position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; z-index: 5;';
            
            // Füge eingefrorenes Bild zum Container hinzu
            const container = document.getElementById('scannerContainer');
            if (container) {
                container.appendChild(frozenImage);
            }
            
            // Pausiere Video (falls unterstützt)
            if (video.pause) {
                video.pause();
            }
            
            // Starte Scan-Linien-Animation
            scannerLine.classList.add('animate');
            
            // Nach Animation: Entferne eingefrorenes Bild und setze Video fort
            setTimeout(() => {
                if (frozenImage.parentNode) {
                    frozenImage.parentNode.removeChild(frozenImage);
                }
                scannerLine.classList.remove('animate');
                
                // Setze Video fort
                if (video.play) {
                    video.play().catch(err => console.error('Video konnte nicht fortgesetzt werden:', err));
                }
                
                resolve();
            }, 500); // Animation dauert 0.5 Sekunden
        });
    }
    
    showScanSuccess() {
        const scannerFrame = document.getElementById('scannerFrame');
        const successPopup = document.getElementById('scannerSuccessPopup');
        
        // Zeige Popup
        if (successPopup) {
            successPopup.classList.remove('hide');
            successPopup.classList.add('show');
            // Popup wird nach 2 Sekunden automatisch ausgeblendet
            setTimeout(() => {
                successPopup.classList.remove('show');
                successPopup.classList.add('hide');
                setTimeout(() => {
                    successPopup.style.display = 'none';
                    successPopup.classList.remove('hide');
                }, 300);
            }, 2000);
        }
        
        // Grünes Leuchten des Rahmens
        if (scannerFrame) {
            scannerFrame.classList.add('scanner-success');
            // Entferne Klasse nach Animation (2 Sekunden)
            setTimeout(() => {
                scannerFrame.classList.remove('scanner-success');
            }, 2000);
        }
    }
}

// Borrow Scanner Manager - Verwaltet die "Ausleihen geben" Seite mit Scanner und Warenkorb
class InventoryScanLookup {
    /**
     * Klartext-Vorschläge für Produkte/Sets (eigenes Suchfeld).
     * @param {{input: HTMLInputElement, dropdown: HTMLElement, onPick: (code: string, item: object) => void, includeSets?: boolean}} opts
     */
    constructor(opts) {
        this.input = opts.input;
        this.dropdown = opts.dropdown;
        this.onPick = opts.onPick;
        this.includeSets = opts.includeSets !== false;
        this.searchUrl = opts.searchUrl || '/inventory/api/search';
        this.minChars = opts.minChars || 2;
        this.timer = null;
        this.activeIndex = -1;
        this.items = [];
        if (this.input && this.dropdown) this.bind();
    }

    escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    bind() {
        this.input.addEventListener('input', () => {
            clearTimeout(this.timer);
            this.timer = setTimeout(() => this.search(this.input.value), 220);
        });
        this.input.addEventListener('keydown', (e) => this.onKeydown(e));
        this.input.addEventListener('blur', () => {
            setTimeout(() => this.hide(), 180);
        });
        this.input.addEventListener('focus', () => {
            if (this.items.length) this.show();
        });
    }

    async search(raw) {
        const q = String(raw || '').trim();
        if (q.length < this.minChars) {
            this.hide();
            return;
        }
        try {
            const url = `${this.searchUrl}?q=${encodeURIComponent(q)}${this.includeSets ? '&include_sets=1' : ''}`;
            const res = await fetch(url);
            if (!res.ok) {
                this.hide();
                return;
            }
            const data = await res.json();
            let products = [];
            let sets = [];
            if (Array.isArray(data)) {
                products = data;
            } else {
                products = Array.isArray(data.products) ? data.products : [];
                sets = Array.isArray(data.sets) ? data.sets : [];
            }
            this.items = [
                ...sets.map((s) => ({
                    type: 'set',
                    id: s.id,
                    name: s.name,
                    meta: s.product_count != null ? `${s.product_count} Produkte` : 'Set',
                    code: `SET-${s.id}`,
                })),
                ...products.slice(0, 8).map((p) => ({
                    type: 'product',
                    id: p.id,
                    name: p.name,
                    meta: [p.category, p.serial_number, p.status].filter(Boolean).join(' · '),
                    code: `PROD-${p.id}`,
                    status: p.status,
                })),
            ].slice(0, 10);
            this.activeIndex = -1;
            this.render();
        } catch (err) {
            console.error('Produkt-Suche fehlgeschlagen:', err);
            this.hide();
        }
    }

    render() {
        if (!this.items.length) {
            this.hide();
            return;
        }
        this.dropdown.innerHTML = this.items.map((item, idx) => {
            const badge = item.type === 'set'
                ? '<span class="badge bg-primary ms-1">SET</span>'
                : '<span class="badge bg-secondary ms-1">PROD</span>';
            const meta = item.meta
                ? `<small class="text-muted d-block">${this.escapeHtml(item.meta)}</small>`
                : '';
            return `<button type="button" class="list-group-item list-group-item-action" role="option" data-idx="${idx}" aria-selected="${idx === this.activeIndex}">
                <span class="fw-semibold">${this.escapeHtml(item.name)}</span>${badge}
                ${meta}
            </button>`;
        }).join('');
        this.dropdown.querySelectorAll('button').forEach((btn) => {
            btn.addEventListener('mousedown', (e) => e.preventDefault());
            btn.addEventListener('click', () => {
                const idx = Number(btn.dataset.idx);
                this.pick(idx);
            });
        });
        this.show();
    }

    onKeydown(e) {
        if (!this.items.length || this.dropdown.style.display === 'none') return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.activeIndex = Math.min(this.activeIndex + 1, this.items.length - 1);
            this.highlight();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.activeIndex = Math.max(this.activeIndex - 1, 0);
            this.highlight();
        } else if (e.key === 'Enter' && this.activeIndex >= 0) {
            e.preventDefault();
            e.stopPropagation();
            this.pick(this.activeIndex);
        } else if (e.key === 'Escape') {
            this.hide();
        }
    }

    highlight() {
        this.dropdown.querySelectorAll('button').forEach((btn, idx) => {
            btn.classList.toggle('active', idx === this.activeIndex);
            btn.setAttribute('aria-selected', idx === this.activeIndex ? 'true' : 'false');
        });
    }

    pick(idx) {
        const item = this.items[idx];
        if (!item) return;
        this.input.value = item.code;
        this.hide();
        if (typeof this.onPick === 'function') this.onPick(item.code, item);
    }

    show() {
        this.dropdown.style.display = 'block';
    }

    hide() {
        this.dropdown.style.display = 'none';
        this.activeIndex = -1;
    }
}

class BorrowScannerManager {
    constructor() {
        this.stream = null;
        this.scanning = false;
        this.lastAction = null;
        this.lastRetryCallback = null;
        this._zxingReader = null;
        this._zxingFrameSkip = 0;
    }

    _ensureZxingReader() {
        if (this._zxingReader) return this._zxingReader;
        const ZX = window.ZXing;
        if (!ZX || !ZX.BrowserMultiFormatReader) return null;
        try {
            const hints = new Map();
            if (ZX.DecodeHintType && ZX.BarcodeFormat) {
                hints.set(ZX.DecodeHintType.POSSIBLE_FORMATS, [
                    ZX.BarcodeFormat.QR_CODE,
                    ZX.BarcodeFormat.CODE_128,
                    ZX.BarcodeFormat.CODE_39,
                    ZX.BarcodeFormat.EAN_13,
                    ZX.BarcodeFormat.EAN_8,
                    ZX.BarcodeFormat.ITF,
                    ZX.BarcodeFormat.CODABAR,
                ]);
                hints.set(ZX.DecodeHintType.TRY_HARDER, true);
            }
            this._zxingReader = new ZX.BrowserMultiFormatReader(hints);
            return this._zxingReader;
        } catch (err) {
            console.warn('ZXing Init fehlgeschlagen:', err);
            return null;
        }
    }

    _decodeWithZxing(canvas) {
        const reader = this._ensureZxingReader();
        if (!reader || !canvas) return null;
        try {
            // decodeFromCanvas ist sync in @zxing/browser UMD
            if (typeof reader.decodeFromCanvas === 'function') {
                const result = reader.decodeFromCanvas(canvas);
                return result && result.getText ? result.getText() : (result && result.text) || null;
            }
        } catch (_notFound) {
            // Kein Code in diesem Frame
        }
        // Fallback: MultiFormatReader + LuminanceSource
        const ZX = window.ZXing;
        if (!ZX || !ZX.HTMLCanvasElementLuminanceSource || !ZX.BinaryBitmap) return null;
        try {
            if (!this._zxingMultiReader) {
                this._zxingMultiReader = new ZX.MultiFormatReader();
                const hints = new Map();
                if (ZX.DecodeHintType && ZX.BarcodeFormat) {
                    hints.set(ZX.DecodeHintType.POSSIBLE_FORMATS, [
                        ZX.BarcodeFormat.CODE_128,
                        ZX.BarcodeFormat.CODE_39,
                        ZX.BarcodeFormat.EAN_13,
                        ZX.BarcodeFormat.EAN_8,
                        ZX.BarcodeFormat.ITF,
                        ZX.BarcodeFormat.CODABAR,
                    ]);
                    hints.set(ZX.DecodeHintType.TRY_HARDER, true);
                }
                this._zxingMultiReader.setHints(hints);
            }
            const luminance = new ZX.HTMLCanvasElementLuminanceSource(canvas);
            const binary = new ZX.BinaryBitmap(new ZX.HybridBinarizer(luminance));
            const result = this._zxingMultiReader.decode(binary);
            return result && result.getText ? result.getText() : null;
        } catch (_err) {
            return null;
        }
    }
    
    init() {
        const startBtn = document.getElementById('startScannerBtn');
        const stopBtn = document.getElementById('stopScannerBtn');
        const addBtn = document.getElementById('addToCartBtn');
        const manualInput = document.getElementById('manualQrInput');
        
        if (startBtn && !startBtn.dataset.scannerBound) {
            startBtn.dataset.scannerBound = '1';
            startBtn.addEventListener('click', () => this.startScanner());
        }
        
        if (stopBtn && !stopBtn.dataset.scannerBound) {
            stopBtn.dataset.scannerBound = '1';
            stopBtn.addEventListener('click', () => this.stopScanner());
        }
        
        // Single owner for manual add — templates must not re-bind these controls
        if (addBtn && manualInput && !addBtn.dataset.cartBound) {
            addBtn.dataset.cartBound = '1';
            manualInput.dataset.cartBound = '1';
            addBtn.addEventListener('click', () => this.addFromInput());
            manualInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.addFromInput();
                }
            });
        }

        const suggestEl = document.getElementById('productSuggest');
        const searchInput = document.getElementById('productSearchInput');
        if (searchInput && suggestEl && !searchInput.dataset.lookupBound) {
            searchInput.dataset.lookupBound = '1';
            this.productLookup = new InventoryScanLookup({
                input: searchInput,
                dropdown: suggestEl,
                includeSets: true,
                onPick: (code) => {
                    this.addToCart(code).then(() => {
                        searchInput.value = '';
                    }).catch(() => {});
                },
            });
        }
        
        // Remove from cart (SSR list). Dynamic rows get listeners in updateCartFromJSON.
        document.querySelectorAll('.remove-from-cart').forEach(btn => {
            if (btn.dataset.removeBound) return;
            btn.dataset.removeBound = '1';
            btn.addEventListener('click', (e) => {
                const productId = e.target.closest('.remove-from-cart')?.dataset?.productId;
                if (productId) this.removeFromCart(productId);
            });
        });
        this.bindCartQuantityInputs();

        this.setupCheckoutForm();
    }

    bindCartQuantityInputs(root = document) {
        root.querySelectorAll('.cart-qty-input').forEach((input) => {
            if (input.dataset.qtyBound) return;
            input.dataset.qtyBound = '1';
            input.addEventListener('change', async () => {
                const productId = parseInt(input.dataset.productId, 10);
                let qty = parseInt(input.value || '1', 10);
                if (!Number.isFinite(qty) || qty < 1) qty = 1;
                input.value = String(qty);
                try {
                    await this.updateCartQuantity(productId, qty);
                } catch (err) {
                    this.showError(err?.message || 'Menge konnte nicht aktualisiert werden');
                }
            });
        });
    }

    buildSetMembersDropdownHtml(sourceSet, productId) {
        if (!sourceSet || !sourceSet.name) return '';
        const members = Array.isArray(sourceSet.members) ? sourceSet.members : [];
        const setName = this.escapeHtml(sourceSet.name);
        const memberHtml = members.length
            ? members.map((member) => {
                const qty = member.quantity && member.quantity > 1
                    ? ` <span class="badge bg-secondary">×${this.escapeHtml(String(member.quantity))}</span>`
                    : '';
                return `<li><i class="bi bi-box-seam text-muted" aria-hidden="true"></i><span>${this.escapeHtml(member.name || '—')}</span>${qty}</li>`;
            }).join('')
            : '<li class="text-muted">Keine Produkte</li>';

        return `
            <details class="inventory-set-members">
                <summary class="inventory-set-members-summary">${setName} · Bestandteile</summary>
                <ul class="inventory-set-members-list">${memberHtml}</ul>
            </details>
        `;
    }

    buildCartItemElement(product) {
        const newItem = document.createElement('div');
        const sourceSet = product.source_set || null;
        newItem.className = `inventory-cart-item cart-item${sourceSet ? ' inventory-cart-item--set' : ''}`;
        newItem.setAttribute('data-product-id', product.id);
        if (sourceSet && sourceSet.id) {
            newItem.setAttribute('data-set-id', sourceSet.id);
        }
        const categoryHtml = product.category
            ? `<p class="inventory-cart-item-meta">${this.escapeHtml(product.category)}</p>`
            : '';
        const setBadge = sourceSet
            ? `<span class="badge inventory-set-badge" title="Aus Produktset"><i class="bi bi-collection" aria-hidden="true"></i> Set</span>`
            : '';
        const setDropdown = sourceSet ? this.buildSetMembersDropdownHtml(sourceSet, product.id) : '';
        const qty = Number(product.cart_quantity || 1);
        const qtyControls = product.item_type === 'consumable'
            ? `<div class="input-group input-group-sm mt-2" style="max-width: 190px;">
                    <span class="input-group-text">Menge</span>
                    <input type="number" min="1" class="form-control cart-qty-input" data-product-id="${product.id}" value="${this.escapeHtml(String(qty))}">
               </div>`
            : '';
        newItem.innerHTML = `
            <div class="inventory-cart-item-body">
                <p class="inventory-cart-item-title">${this.escapeHtml(product.name)} ${setBadge}</p>
                ${categoryHtml}
                ${qtyControls}
                ${setDropdown}
            </div>
            <button class="btn btn-sm inventory-pill-btn inventory-pill-btn--outline-danger remove-from-cart" type="button" data-product-id="${product.id}">
                <i class="bi bi-trash"></i>
            </button>
        `;
        return newItem;
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
            
            // Zeige Scanner-Container SOFORT, bevor Video geladen wird
            const scannerContainer = document.getElementById('scannerContainer');
            if (scannerContainer) {
                scannerContainer.style.display = 'block';
                scannerContainer.offsetHeight;
            }
            
            if (video) {
                video.style.cssText = 'display: block !important; visibility: visible !important; opacity: 1 !important; width: 100% !important; height: 100% !important; object-fit: cover !important;';
                
                video.srcObject = this.stream;
                video.setAttribute('playsinline', 'true');
                video.setAttribute('autoplay', 'true');
                video.setAttribute('muted', 'true'); // Muted für bessere Browser-Kompatibilität
                
                // Verstecke Fehlermeldung
                this.hideError();
                
                // Warte bis Video bereit ist
                await new Promise((resolve, reject) => {
                    const timeout = setTimeout(() => {
                        reject(new Error('Video konnte nicht geladen werden'));
                    }, 10000);
                    
                    const onLoadedMetadata = () => {
                        clearTimeout(timeout);
                        video.play()
                            .then(() => {
                                // Stelle sicher, dass Video sichtbar ist
                                video.style.cssText = 'display: block !important; visibility: visible !important; opacity: 1 !important; width: 100% !important; height: 100% !important; object-fit: cover !important;';
                                // Stelle sicher, dass Container auch sichtbar ist
                                if (scannerContainer) {
                                    scannerContainer.style.display = 'block';
                                }
                                // Force reflow um sicherzustellen, dass Browser rendert
                                video.offsetHeight;
                                scannerContainer.offsetHeight;
                                video.removeEventListener('loadedmetadata', onLoadedMetadata);
                                resolve();
                            })
                            .catch((err) => {
                                video.removeEventListener('loadedmetadata', onLoadedMetadata);
                                reject(err);
                            });
                    };
                    
                    video.addEventListener('loadedmetadata', onLoadedMetadata);
                    video.onerror = () => {
                        clearTimeout(timeout);
                        video.removeEventListener('loadedmetadata', onLoadedMetadata);
                        reject(new Error('Video-Fehler'));
                    };
                    
                    // Falls Video bereits geladen ist
                    if (video.readyState >= 2) {
                        onLoadedMetadata();
                    }
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
        const scannerContainer = document.getElementById('scannerContainer');
        const scannerFrame = document.getElementById('scannerFrame');
        const successPopup = document.getElementById('scannerSuccessPopup');
        
        if (video) {
            video.srcObject = null;
            video.style.display = 'none';
        }
        
        if (scannerContainer) {
            scannerContainer.style.display = 'none';
        }
        
        // Entferne Erfolgs-Klasse vom Rahmen
        if (scannerFrame) {
            scannerFrame.classList.remove('scanner-success');
        }
        
        // Verstecke Popup
        if (successPopup) {
            successPopup.style.display = 'none';
        }
        
        // Reset Scan-Linie
        const scannerLine = document.getElementById('scannerLine');
        if (scannerLine) {
            scannerLine.classList.remove('animate');
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
                // Kamera NICHT stoppen - für mehrere Scans offen lassen
                // Pausiere kurz das Scannen, um doppelte Scans zu vermeiden
                this.scanning = false;
                
                // Speichere QR-Code für später
                const qrCodeData = code.data;
                
                // Friere Video kurz ein und zeige Scan-Animation
                this.freezeAndAnimate().then(() => {
                    // Zeige visuelles Feedback
                    this.showScanSuccess();
                    
                    // Direktes Hinzufügen zum Warenkorb
                    this.addToCart(qrCodeData).then(() => {
                        // Nach erfolgreichem Hinzufügen, Scannen nach kurzer Pause fortsetzen
                        setTimeout(() => {
                            if (this.stream && !this.scanning) {
                                this.scanning = true;
                                this.scanForQR();
                            }
                        }, 2500); // Warte bis Animation fertig ist
                    }).catch((error) => {
                        console.error('addToCart Fehler:', error);
                        // Bei Fehler auch Scannen fortsetzen
                        setTimeout(() => {
                            if (this.stream && !this.scanning) {
                                this.scanning = true;
                                this.scanForQR();
                            }
                        }, 2500);
                    });
                }).catch((error) => {
                    console.error('freezeAndAnimate Fehler:', error);
                    // Auch bei Fehler versuchen hinzuzufügen
                    this.addToCart(qrCodeData);
                });
                return; // Verhindere weiteres Scannen bis addToCart fertig ist
            }

            // 1D-Barcodes (Esto Inventar-Etiketten): ZXing alle paar Frames
            this._zxingFrameSkip = (this._zxingFrameSkip + 1) % 3;
            let barcodeText = null;
            if (this._zxingFrameSkip === 0) {
                barcodeText = this._decodeWithZxing(canvas);
            }
            if (barcodeText) {
                this.scanning = false;
                const qrCodeData = barcodeText;
                this.freezeAndAnimate().then(() => {
                    this.showScanSuccess();
                    this.addToCart(qrCodeData).then(() => {
                        setTimeout(() => {
                            if (this.stream && !this.scanning) {
                                this.scanning = true;
                                this.scanForQR();
                            }
                        }, 2500);
                    }).catch((error) => {
                        console.error('addToCart Fehler:', error);
                        setTimeout(() => {
                            if (this.stream && !this.scanning) {
                                this.scanning = true;
                                this.scanForQR();
                            }
                        }, 2500);
                    });
                }).catch(() => {
                    this.addToCart(qrCodeData);
                });
                return;
            }

            // Weiter scannen - kontinuierlich
            requestAnimationFrame(() => this.scanForQR());
        } catch (error) {
            console.error('Fehler beim Scannen (BorrowScanner):', error);
            setTimeout(() => this.scanForQR(), 200);
        }
    }
    
    async addFromInput() {
        const input = document.getElementById('manualQrInput');
        if (!input || !input.value.trim()) {
            this.showError('Bitte ID eingeben.');
            return;
        }
        const value = this.normalizeScannedCode(input.value);
        try {
            await this.addToCart(value);
            input.value = '';
        } catch (_err) {
            // Input kept so user can correct / retry; errors already shown in addToCart
        }
    }

    normalizeScannedCode(rawValue) {
        if (rawValue == null) return '';
        let text = String(rawValue)
            .replace(/[\u0000-\u001F\u007F]+/g, '')
            .trim();
        if (!text) return '';

        // Handscanner tippt URL-Sonderzeichen oft falsch (US/DE-Layout):
        // http://host:5000/inventory/... -> httpÖ--hostÖ5000-inventorz-...
        let repaired = text
            .replace(/[Öö]--/g, '://')
            .replace(/[Öö]/g, ':')
            .replace(/inventorz/gi, 'inventory')
            .replace(/inventor[yz]/gi, 'inventory');

        const cleanUrl = repaired.match(/[/\\]inventory[/\\]public[/\\]product[/\\](\d+)/i);
        if (cleanUrl) return `PROD-${cleanUrl[1]}`;

        const mangledUrl = repaired.match(/inventor[yz]?[-_/\\]+public[-_/\\]+product[-_/\\]+(\d+)/i)
            || text.match(/inventor[yz]?[-_/\\]+public[-_/\\]+product[-_/\\]+(\d+)/i);
        if (mangledUrl) return `PROD-${mangledUrl[1]}`;

        if (/(?:https?|inventor|localhost|127\.0\.0\.1|public[-_/\\]+product)/i.test(repaired + text)) {
            const productTail = (repaired.match(/product[-_/\\]+(\d+)/i)
                || text.match(/product[-_/\\]+(\d+)/i));
            if (productTail) return `PROD-${productTail[1]}`;
        }

        const prod = text.match(/(?:^|[^A-Za-z0-9])PROD[\s:_-]*([0-9]+)/i);
        if (prod) return `PROD-${prod[1]}`;
        const setMatch = text.match(/(?:^|[^A-Za-z0-9])SET[\s:_-]*([0-9]+)/i);
        if (setMatch) return `SET-${setMatch[1]}`;

        return text;
    }
    
    async addToCart(qrCode) {
        qrCode = this.normalizeScannedCode(qrCode);
        if (!qrCode) {
            this.showError('Bitte ID eingeben.');
            return Promise.reject(new Error('Leerer Scan-Code'));
        }
        if (window.inventoryScanMode === 'return') {
            try {
                const response = await fetch('/inventory/api/return', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ checkout_number: qrCode, transaction_number: qrCode }),
                });
                let result = await response.json().catch(() => ({}));
                if (!response.ok || result.error) {
                    let productId = null;
                    const m = String(qrCode).match(/PROD-?(\d+)/i);
                    if (m) productId = parseInt(m[1], 10);
                    else if (/^\d+$/.test(String(qrCode).trim())) productId = parseInt(qrCode, 10);
                    if (productId) {
                        const r2 = await fetch('/inventory/api/return', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ product_id: productId }),
                        });
                        result = await r2.json().catch(() => ({}));
                        if (!r2.ok || result.error) throw new Error(result.error || 'Rückgabe fehlgeschlagen');
                    } else {
                        throw new Error(result.error || 'Rückgabe fehlgeschlagen');
                    }
                }
                const resultEl = document.getElementById('returnScanResult');
                const emailOk = result.return_email_sent !== false;
                if (resultEl) {
                    const count = result.returned_count ? ` (${Number(result.returned_count) || result.returned_count})` : '';
                    if (emailOk) {
                        this.setReturnScanResult(`Rückgabe OK${count}.`, 'success');
                    } else {
                        this.setReturnScanResult(`Rückgabe OK${count}, E-Mail fehlgeschlagen.`, 'warning');
                    }
                }
                if (emailOk) {
                    this.showSuccess('Rückgabe erfolgreich.');
                } else {
                    this.showError('Rückgabe registriert, Bestätigungs-E-Mail konnte nicht gesendet werden.');
                }
                return result;
            } catch (error) {
                this.setReturnScanResult(error.message || 'Fehler', 'danger');
                this.showError(error.message || 'Rückgabe fehlgeschlagen');
                throw error;
            }
        }
        try {
            const formData = new FormData();
            formData.append('action', 'add_to_cart');
            formData.append('qr_code', qrCode);
            
            const response = await fetch('/inventory/borrow-scanner', {
                method: 'POST',
                body: formData
            });
            
            
            let result;
            try {
                result = await response.json();
            } catch (jsonError) {
                console.error('Fehler beim Parsen der JSON-Antwort:', jsonError);
                const text = await response.text();
                console.error('Response-Text:', text);
                throw new Error(`Server-Antwort konnte nicht geparst werden. Status: ${response.status}`);
            }
            
            if (!response.ok) {
                // Server hat eine Fehlermeldung zurückgegeben
                const errorMessage = result.error || `HTTP error! status: ${response.status}`;
                console.error('Server-Fehler:', errorMessage);
                throw new Error(errorMessage);
            }
            
            if (result.success) {

                if (result.is_return) {
                    const count = result.returned_count ? ` (${Number(result.returned_count) || result.returned_count})` : '';
                    const checkoutNo = result.checkout_number ? `: ${result.checkout_number}` : '';
                    const emailOk = result.return_email_sent !== false;
                    if (emailOk) {
                        this.setReturnScanResult(`Rückgabe OK${count}${checkoutNo}.`, 'success');
                        this.showSuccess('Rückgabe erfolgreich.');
                    } else {
                        this.setReturnScanResult(`Rückgabe OK${count}${checkoutNo}, E-Mail fehlgeschlagen.`, 'warning');
                        this.showError('Rückgabe registriert, Bestätigungs-E-Mail konnte nicht gesendet werden.');
                    }
                    return Promise.resolve(result);
                }
                
                // Alert für Sets (kein Modal)
                if (result.is_set) {
                    this.showSetScannedModal(result);
                }
                
                
                // Prüfe ob result.product vorhanden ist (für einzelne Produkte)
                if (!result.is_set && !result.product) {
                    console.error('=== FEHLER: result.product fehlt ===', result);
                    const errorMessage = 'Produkt-Daten fehlen in der Server-Antwort.';
                    this.showError(errorMessage);
                    setTimeout(() => this.hideError(), 5000);
                    return Promise.reject(new Error(errorMessage));
                }
                
                // SOFORTIGE Aktualisierung - keine Verzögerung
                this.updateCartFromJSON(result);
                this.registerAddAction(result);
                if (!result.is_set) {
                    this.showSuccess('Produkt hinzugefügt');
                }

                // ensureCheckoutForm wird jetzt in updateCartFromJSON aufgerufen
                
                return Promise.resolve(result);
            } else {
                // Zeige Fehlermeldung im UI
                const errorMessage = result.error || 'QR Code Nicht erkannt';
                console.error('=== SERVER FEHLER ===', errorMessage);
                this.showError(errorMessage);
                setTimeout(() => this.hideError(), 5000);
                return Promise.reject(new Error(errorMessage));
            }
        } catch (error) {
            console.error('=== EXCEPTION ===', error);
            this.showError('QR Code Nicht erkannt');
            setTimeout(() => this.hideError(), 5000);
            return Promise.reject(error);
        }
    }
    
    updateCartFromJSON(result) {
        // Schnelles Update mit JSON-Daten aus der addToCart-Response
        
        // Aktualisiere Cart-Count SOFORT
        const cartCount = document.getElementById('cartCount');
        if (cartCount) {
            if (result.cart_count !== undefined) {
                cartCount.textContent = result.cart_count;
            } else {
                console.warn('⚠ cart_count nicht vorhanden');
            }
        } else {
            console.error('✗ cartCount Element nicht gefunden!');
        }
        
        const cartItems = document.getElementById('cartItems');
        if (!cartItems) {
            console.error('✗ cartItems Element nicht gefunden!');
            // Fallback: Seite neu laden
            window.location.reload();
            return;
        }
        
        // Wenn ein Set gescannt wurde, füge alle Produkte hinzu
        if (result.is_set && result.added_products && result.added_products.length > 0) {
            
            // Verhindere, dass loadCheckoutForm den Warenkorb überschreibt
            cartItems.setAttribute('data-updating', 'true');
            
            // Entferne "Keine Produkte hinzugefügt" Nachricht
            const emptyMessage = cartItems.querySelector('p.text-muted');
            if (emptyMessage) {
                emptyMessage.remove();
            }
            
            // Füge alle Produkte des Sets hinzu
            result.added_products.forEach(product => {
                if (!product.source_set && result.set) {
                    product.source_set = {
                        id: result.set.id,
                        name: result.set.name,
                        members: result.set.members || [],
                    };
                }
                // Prüfe ob Produkt bereits vorhanden ist
                const existingItem = cartItems.querySelector(`[data-product-id="${product.id}"]`);
                if (existingItem) {
                    // Ersetze durch Version mit Set-Badge
                    const refreshed = this.buildCartItemElement(product);
                    existingItem.replaceWith(refreshed);
                    return;
                }
                
                const newItem = this.buildCartItemElement(product);
                cartItems.appendChild(newItem);
            });
            
            // Entferne Update-Markierung
            cartItems.removeAttribute('data-updating');
            
            // Event-Listener für alle neuen Remove-Buttons hinzufügen
            cartItems.querySelectorAll('.remove-from-cart').forEach(btn => {
                if (!btn.hasAttribute('data-listener-attached')) {
                    btn.setAttribute('data-listener-attached', 'true');
                    btn.addEventListener('click', async (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        const productId = btn.dataset.productId;
                        await this.removeFromCart(productId);
                    });
                }
            });
            this.bindCartQuantityInputs(cartItems);
            
            // Prüfe ob Checkout-Formular benötigt wird
            this.ensureCheckoutForm(result.cart_count);
            return;
        }
        
        // Einzelnes Produkt hinzufügen
        if (!result.product) {
            console.error('⚠ Kein Produkt in result - result:', result);
            console.error('⚠ is_set:', result.is_set);
            // Wenn es kein Set ist, aber auch kein Produkt, ist das ein Fehler
            if (!result.is_set) {
                console.error('⚠ FEHLER: Weder Set noch Produkt in result!');
                this.showError('Fehler: Produkt-Daten fehlen.');
                setTimeout(() => this.hideError(), 5000);
            }
            return;
        }
        
        
        // Prüfe ob Produkt bereits vorhanden ist
        const existingItem = cartItems.querySelector(`[data-product-id="${result.product.id}"]`);
        if (existingItem) {
            const qtyInput = existingItem.querySelector('.cart-qty-input');
            if (qtyInput && result.product.cart_quantity != null) {
                qtyInput.value = String(result.product.cart_quantity);
            }
            return;
        }
        
        // Verhindere, dass loadCheckoutForm den Warenkorb überschreibt
        // Markiere dass wir gerade ein Produkt hinzufügen
        cartItems.setAttribute('data-updating', 'true');
        
        // Entferne "Keine Produkte hinzugefügt" Nachricht
        const emptyMessage = cartItems.querySelector('p.text-muted');
        if (emptyMessage) {
            emptyMessage.remove();
        }
        
        const newItem = this.buildCartItemElement(result.product);
        cartItems.appendChild(newItem);
        
        // Entferne Update-Markierung
        cartItems.removeAttribute('data-updating');
        
        // Event-Listener für Remove-Button
        const removeBtn = newItem.querySelector('.remove-from-cart');
        if (removeBtn) {
            removeBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const productId = removeBtn.dataset.productId;
                if (productId) {
                    this.removeFromCart(productId);
                }
            });
        }
        this.bindCartQuantityInputs(newItem);
        
        // Prüfe ob Checkout-Formular benötigt wird
        this.ensureCheckoutForm(result.cart_count);
        
    }

    async updateCartQuantity(productId, quantity) {
        const formData = new FormData();
        formData.append('action', 'update_cart_quantity');
        formData.append('product_id', String(productId));
        formData.append('quantity', String(quantity));
        const response = await fetch('/inventory/borrow-scanner', { method: 'POST', body: formData });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.error) {
            throw new Error(result.error || 'Menge konnte nicht aktualisiert werden');
        }
        const cartCount = document.getElementById('cartCount');
        if (cartCount && result.cart_count !== undefined) {
            cartCount.textContent = String(result.cart_count);
        }
    }
    
    ensureCheckoutForm(cartCount) {
        const checkoutForm = document.getElementById('checkoutForm');
        if (!checkoutForm) return;
        const submitBtn = checkoutForm.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = !(cartCount > 0);
        }
    }
    
    async loadCheckoutForm() {
        // Lade nur das Checkout-Formular nach, ohne die gesamte Seite neu zu laden
        try {
            // Prüfe ob Checkout-Formular bereits existiert
            const existingCheckoutForm = document.getElementById('checkoutForm');
            if (existingCheckoutForm) {
                return;
            }
            
            // Prüfe ob gerade ein Update läuft - warte bis es fertig ist
            const cartItemsContainer = document.getElementById('cartItems');
            if (cartItemsContainer && cartItemsContainer.getAttribute('data-updating') === 'true') {
                // Warte länger und prüfe mehrfach
                let attempts = 0;
                const checkInterval = setInterval(() => {
                    attempts++;
                    if (cartItemsContainer.getAttribute('data-updating') !== 'true' || attempts > 25) {
                        clearInterval(checkInterval);
                        if (attempts <= 25) {
                            this.loadCheckoutForm();
                        } else {
                            console.warn('Timeout beim Warten auf Warenkorb-Update');
                        }
                    }
                }, 100);
                return;
            }
            
            // WICHTIG: Erstelle das Checkout-Formular manuell statt die gesamte Seite zu laden
            // Das verhindert, dass der Warenkorb überschrieben wird
            const cartCardBody = cartItemsContainer?.closest('.inventory-panel-body')
                || cartItemsContainer?.closest('.card-body');
            if (!cartCardBody) {
                console.warn('cartCardBody nicht gefunden');
                return;
            }
            
            // Erstelle Checkout-Formular manuell
            const hr = document.createElement('hr');
            const form = document.createElement('form');
            form.id = 'checkoutForm';
            form.method = 'POST';
            form.action = '/inventory/borrow-scanner/checkout';
            
            // Erstelle Borrower-Dropdown
            const borrowerDiv = document.createElement('div');
            borrowerDiv.className = 'mb-3';
            const borrowerLabel = document.createElement('label');
            borrowerLabel.className = 'form-label';
            borrowerLabel.setAttribute('for', 'borrower_id');
            borrowerLabel.textContent = 'Ausleihender';
            const borrowerSelect = document.createElement('select');
            borrowerSelect.className = 'form-select';
            borrowerSelect.id = 'borrower_id';
            borrowerSelect.name = 'borrower_id';
            
            // Hole Benutzer-Liste aus verstecktem Template-Element oder vorhandenem Select
            let tempSelect = document.querySelector('select#hidden_borrower_list');
            if (!tempSelect) {
                tempSelect = document.querySelector('select#borrower_id');
            }
            if (!tempSelect) {
                tempSelect = document.querySelector('select[name="borrower_id"]');
            }
            
            if (tempSelect && tempSelect.options.length > 0) {
                // Kopiere alle Optionen vom vorhandenen Select
                Array.from(tempSelect.options).forEach(opt => {
                    const newOpt = opt.cloneNode(true);
                    borrowerSelect.appendChild(newOpt);
                });
            } else {
                // Fallback: Nur aktueller Benutzer
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = 'Ich';
                opt.selected = true;
                borrowerSelect.appendChild(opt);
                console.warn('⚠ Keine Benutzer-Liste gefunden, verwende Fallback');
            }
            
            borrowerDiv.appendChild(borrowerLabel);
            borrowerDiv.appendChild(borrowerSelect);
            
            // Erstelle Date-Input
            const dateDiv = document.createElement('div');
            dateDiv.className = 'mb-3';
            const dateLabel = document.createElement('label');
            dateLabel.className = 'form-label';
            dateLabel.setAttribute('for', 'expected_return_date');
            dateLabel.innerHTML = 'Erwartetes Rückgabedatum <span class="text-danger">*</span>';
            const dateInput = document.createElement('input');
            dateInput.type = 'date';
            dateInput.className = 'form-control';
            dateInput.id = 'expected_return_date';
            dateInput.name = 'expected_return_date';
            dateInput.required = true;
            const tomorrow = new Date();
            tomorrow.setDate(tomorrow.getDate() + 1);
            dateInput.min = tomorrow.toISOString().split('T')[0];
            
            dateDiv.appendChild(dateLabel);
            dateDiv.appendChild(dateInput);
            
            // Erstelle Submit-Button
            const submitBtn = document.createElement('button');
            submitBtn.type = 'submit';
            submitBtn.className = 'btn btn-accent w-100';
            submitBtn.innerHTML = '<i class="bi bi-check-circle"></i> Produkte ausleihen';
            
            form.appendChild(borrowerDiv);
            form.appendChild(dateDiv);
            form.appendChild(submitBtn);
            
            // Füge HR und Formular hinzu
            cartCardBody.appendChild(hr);
            cartCardBody.appendChild(form);
            
            // Initialisiere Event-Listener für das neue Formular
            this.initCheckoutForm();
            this.setupCheckoutForm();
        } catch (error) {
            console.error('Fehler beim Laden des Checkout-Formulars:', error);
            // KEIN automatisches Reload - das würde den Warenkorb zurücksetzen
        }
    }
    
    initCheckoutForm() {
        // Initialisiere Event-Listener für Checkout-Formular
        const checkoutForm = document.getElementById('checkoutForm');
        if (checkoutForm) {
            const dateInput = document.getElementById('expected_return_date');
            if (dateInput) {
                const tomorrow = new Date();
                tomorrow.setDate(tomorrow.getDate() + 1);
                dateInput.min = tomorrow.toISOString().split('T')[0];
            }
        }
    }
    
    showSetScannedModal(result) {
        // Alert statt Modal — Workflow nicht unterbrechen
        const setName = result?.set?.name || 'Set';
        const added = Array.isArray(result.added_products) ? result.added_products : [];
        const unavailable = Array.isArray(result.unavailable_products) ? result.unavailable_products : [];

        const details = added.map((product) => {
            if (product.was_in_cart) {
                return `${product.name}: bereits im Warenkorb`;
            }
            if (product.added > 0) {
                return `${product.name}: ${product.added} hinzugefügt`;
            }
            return `${product.name}: nicht verfügbar`;
        });

        let message = `Set "${setName}" gescannt`;
        if (details.length > 0) {
            message += ` — ${details.join('; ')}`;
        } else {
            message += ' — keine Produkte hinzugefügt';
        }

        if (unavailable.length > 0) {
            const names = unavailable.map((p) => {
                const status = p.status === 'borrowed' ? 'ausgeliehen' : 'fehlend';
                return `${p.name} (${status})`;
            }).join(', ');
            message += `. Nicht hinzugefügt: ${names}`;
            this.showSetScanAlert(message, 'warning');
            return;
        }

        this.showSetScanAlert(message, 'success');
    }

    showSetScanAlert(message, level) {
        const errorDiv = document.getElementById('scannerError');
        if (errorDiv) {
            errorDiv.className = `alert alert-${level} mt-2`;
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
            setTimeout(() => this.hideError(), 5000);
        }
        const feedback = document.getElementById('scannerFeedback');
        if (feedback) {
            feedback.className = `alert alert-${level} mt-2`;
            feedback.textContent = message;
            feedback.classList.remove('d-none');
            setTimeout(() => feedback.classList.add('d-none'), 5000);
        }
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    setReturnScanResult(message, level = 'success') {
        const resultEl = document.getElementById('returnScanResult');
        if (!resultEl) return;
        resultEl.replaceChildren();
        const alert = document.createElement('div');
        const tone = level === 'danger' ? 'danger' : (level === 'warning' ? 'warning' : 'success');
        alert.className = `alert alert-${tone} mb-0`;
        alert.textContent = message == null ? '' : String(message);
        resultEl.appendChild(alert);
    }
    
    async updateCartDisplay() {
        // Lade Warenkorb-Daten und aktualisiere die Anzeige
        // WICHTIG: Diese Funktion sollte NUR verwendet werden wenn der Warenkorb leer ist
        // oder wenn explizit eine vollständige Aktualisierung benötigt wird
        
        // Prüfe ob bereits Produkte im Warenkorb sind - wenn ja, überspringe
        const currentCartItems = document.getElementById('cartItems');
        if (currentCartItems) {
            const existingProducts = currentCartItems.querySelectorAll('.cart-item[data-product-id]');
            if (existingProducts.length > 0) {
                return;
            }
        }
        try {
            const response = await fetch('/inventory/borrow-scanner');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const html = await response.text();
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');
            
            // Aktualisiere Warenkorb-Bereich
            const newCartItems = doc.querySelector('#cartItems');
            const newCartCount = doc.querySelector('#cartCount');
            const newCheckoutForm = doc.querySelector('#checkoutForm');
            
            // Aktualisiere cartItems NUR wenn keine Produkte vorhanden sind
            // Verhindere Überschreibung wenn bereits Produkte im Warenkorb sind
            const currentCartItems = document.getElementById('cartItems');
            if (newCartItems && currentCartItems) {
                // Prüfe ob bereits Produkte im Warenkorb sind
                const existingProducts = currentCartItems.querySelectorAll('.cart-item[data-product-id]');
                if (existingProducts.length > 0) {
                    // Aktualisiere nur den Cart-Count, nicht die Items
                } else {
                    const oldContent = currentCartItems.innerHTML;
                    currentCartItems.innerHTML = newCartItems.innerHTML;
                }
            } else {
                console.warn('cartItems nicht gefunden:', { newCartItems: !!newCartItems, currentCartItems: !!currentCartItems });
            }
            
            // Aktualisiere cartCount nur wenn keine Produkte vorhanden sind
            // Wenn Produkte vorhanden sind, verwende die aktuelle Anzahl
            const currentCartCount = document.getElementById('cartCount');
            if (currentCartCount) {
                const existingProducts = currentCartItems ? currentCartItems.querySelectorAll('.cart-item[data-product-id]').length : 0;
                if (existingProducts > 0) {
                    // Verwende die Anzahl der vorhandenen Produkte
                    currentCartCount.textContent = existingProducts;
                } else if (newCartCount) {
                    currentCartCount.textContent = newCartCount.textContent;
                }
            } else {
                console.warn('cartCount nicht gefunden');
            }
            
            // Aktualisiere Checkout-Formular
            const currentCheckoutForm = document.getElementById('checkoutForm');
            const cartItemsContainer = document.getElementById('cartItems');
            
            if (newCheckoutForm) {
                // Formular existiert in der neuen Version
                if (currentCheckoutForm) {
                    // Ersetze vorhandenes Formular
                    currentCheckoutForm.outerHTML = newCheckoutForm.outerHTML;
                } else {
                    // Füge Formular hinzu falls es noch nicht existiert
                    if (cartItemsContainer) {
                        // Entferne eventuelles <hr> vor dem Formular
                        const hrAfterCart = cartItemsContainer.nextElementSibling;
                        if (hrAfterCart && hrAfterCart.tagName === 'HR') {
                            hrAfterCart.remove();
                        }
                        // Füge <hr> und Formular hinzu
                        cartItemsContainer.insertAdjacentHTML('afterend', '<hr>' + newCheckoutForm.outerHTML);
                    }
                }
                // Event-Listener neu setzen
                this.setupCheckoutForm();
            } else {
                // Formular existiert nicht mehr (Warenkorb leer)
                if (currentCheckoutForm) {
                    // Entferne Formular und vorhergehendes <hr>
                    const hrBeforeForm = currentCheckoutForm.previousElementSibling;
                    if (hrBeforeForm && hrBeforeForm.tagName === 'HR') {
                        hrBeforeForm.remove();
                    }
                    currentCheckoutForm.remove();
                }
            }
            
            // Remove-from-cart Buttons neu setzen (alte Event-Listener entfernen und neue hinzufügen)
            // Entferne alle alten Event-Listener durch Klonen der Elemente
            const removeButtons = document.querySelectorAll('.remove-from-cart');
            removeButtons.forEach(btn => {
                const newBtn = btn.cloneNode(true);
                btn.parentNode.replaceChild(newBtn, btn);
                
                // Füge neuen Event-Listener hinzu
                newBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const productId = newBtn.dataset.productId;
                    if (productId) {
                        this.removeFromCart(productId);
                    }
                });
            });
            
        } catch (error) {
            console.error('Fehler beim Aktualisieren des Warenkorbs:', error);
            console.error('Error Details:', error.message, error.stack);
            // Fallback: Seite neu laden
            window.location.reload();
        }
    }
    
    setupCheckoutForm() {
        const checkoutForm = document.getElementById('checkoutForm');
        if (!checkoutForm) return;

        const dateInput = document.getElementById('expected_return_date');
        if (dateInput) {
            const tomorrow = new Date();
            tomorrow.setDate(tomorrow.getDate() + 1);
            dateInput.min = tomorrow.toISOString().split('T')[0];
        }

        // Avoid stacking submit handlers on repeated cart updates / init
        if (checkoutForm.dataset.checkoutBound === '1') return;
        checkoutForm.dataset.checkoutBound = '1';

        checkoutForm.addEventListener('submit', (e) => this.handleCheckoutSubmit(e, checkoutForm));
    }

    async handleCheckoutSubmit(e, checkoutForm) {
        e.preventDefault();
        if (!checkoutForm || checkoutForm.dataset.checkoutSubmitting === '1') return;

        const borrowerInput = document.getElementById('borrower_name');
        const borrowerIdInput = document.getElementById('borrower_id');
        const emailInput = document.getElementById('contact_email');
        const eventNameInput = document.getElementById('event_name');
        const endInput = document.getElementById('end_date');

        if (borrowerInput && !borrowerInput.value.trim()) {
            if (window.showAppBanner) window.showAppBanner('Bitte Verantwortlichen angeben.', 'warning');
            else this.showError?.('Bitte Verantwortlichen angeben.');
            return;
        }
        if (borrowerIdInput && emailInput && !borrowerIdInput.value && !emailInput.value.trim()) {
            if (window.showAppBanner) {
                window.showAppBanner('Bitte Kontakt-E-Mail angeben (kein Portal-User gewählt).', 'warning');
            } else {
                this.showError?.('Bitte Kontakt-E-Mail angeben.');
            }
            emailInput.focus();
            return;
        }
        // Quick Scan: Projekt + Rückgabe-bis sind optional (kein required-Attribut).
        // Standard-Checkout: Felder mit required bleiben Pflicht.
        if (eventNameInput && eventNameInput.required && !eventNameInput.value.trim()) {
            if (window.showAppBanner) window.showAppBanner('Bitte Projekt / Veranstaltung angeben.', 'warning');
            else this.showError?.('Bitte Projekt / Veranstaltung angeben.');
            return;
        }
        if (endInput && endInput.required && !endInput.value) {
            if (window.showAppBanner) window.showAppBanner('Bitte Rückgabe-Zeitraum (Bis) angeben.', 'warning');
            else this.showError?.('Bitte Rückgabe-Zeitraum (Bis) angeben.');
            return;
        }

        const formData = new FormData(checkoutForm);
        ['event_name', 'borrower_name', 'borrower_id', 'contact_email', 'start_date', 'end_date', 'event_id', 'event_appointment_id'].forEach((name) => {
            const el = document.getElementById(name);
            if (!el) return;
            if (name === 'contact_email' && el.disabled) {
                formData.delete('contact_email');
                return;
            }
            if (!formData.has(name)) formData.set(name, el.value);
        });

        const submitBtn = checkoutForm.querySelector('button[type="submit"]');
        const originalBtnText = submitBtn ? submitBtn.innerHTML : '';
        checkoutForm.dataset.checkoutSubmitting = '1';
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Wird verarbeitet...';
        }

        try {
            const response = await fetch(checkoutForm.action, {
                method: 'POST',
                body: formData,
                redirect: 'follow',
            });
            if (!response.ok) throw new Error('Checkout fehlgeschlagen');
            this.showSuccess?.('Ausleihe erstellt. Weiterleitung...');
            window.setTimeout(() => { window.location.href = '/inventory/borrows'; }, 600);
        } catch (error) {
            console.error('Fehler beim Checkout:', error);
            if (window.showAppBanner) window.showAppBanner('Fehler beim Erstellen der Ausleihe.', 'danger');
            else this.showError?.('Fehler beim Erstellen der Ausleihe.');
            delete checkoutForm.dataset.checkoutSubmitting;
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalBtnText;
            }
        }
    }
    
    freezeAndAnimate() {
        return new Promise((resolve) => {
            const video = document.getElementById('scannerVideo');
            const scannerLine = document.getElementById('scannerLine');
            
            if (!video || !scannerLine) {
                resolve();
                return;
            }
            
            // Speichere aktuelles Frame als Canvas-Bild
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth || 640;
            canvas.height = video.videoHeight || 480;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            
            // Erstelle temporäres Bild-Element
            const frozenImage = new Image();
            frozenImage.src = canvas.toDataURL();
            frozenImage.style.cssText = 'position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; z-index: 5;';
            
            // Füge eingefrorenes Bild zum Container hinzu
            const container = document.getElementById('scannerContainer');
            if (container) {
                container.appendChild(frozenImage);
            }
            
            // Pausiere Video (falls unterstützt)
            if (video.pause) {
                video.pause();
            }
            
            // Starte Scan-Linien-Animation
            scannerLine.classList.add('animate');
            
            // Nach Animation: Entferne eingefrorenes Bild und setze Video fort
            setTimeout(() => {
                if (frozenImage.parentNode) {
                    frozenImage.parentNode.removeChild(frozenImage);
                }
                scannerLine.classList.remove('animate');
                
                // Setze Video fort
                if (video.play) {
                    video.play().catch(err => console.error('Video konnte nicht fortgesetzt werden:', err));
                }
                
                resolve();
            }, 500); // Animation dauert 0.5 Sekunden
        });
    }
    
    showScanSuccess() {
        const scannerFrame = document.getElementById('scannerFrame');
        const successPopup = document.getElementById('scannerSuccessPopup');
        
        // Zeige Popup
        if (successPopup) {
            successPopup.classList.remove('hide');
            successPopup.classList.add('show');
            // Popup wird nach 2 Sekunden automatisch ausgeblendet
            setTimeout(() => {
                successPopup.classList.remove('show');
                successPopup.classList.add('hide');
                setTimeout(() => {
                    successPopup.style.display = 'none';
                    successPopup.classList.remove('hide');
                }, 300);
            }, 2000);
        }
        
        // Grünes Leuchten des Rahmens
        if (scannerFrame) {
            scannerFrame.classList.add('scanner-success');
            // Entferne Klasse nach Animation (2 Sekunden)
            setTimeout(() => {
                scannerFrame.classList.remove('scanner-success');
            }, 2000);
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
                const removedItem = document.querySelector(`#cartItems .cart-item[data-product-id="${productId}"]`);
                const removedSnapshot = removedItem ? removedItem.outerHTML : null;
                // Entferne nur das spezifische Produkt aus dem DOM, nicht den gesamten Warenkorb
                const cartItems = document.getElementById('cartItems');
                if (cartItems) {
                    const productItem = cartItems.querySelector(`[data-product-id="${productId}"]`);
                    if (productItem) {
                        productItem.remove();
                    }
                }
                
                // Aktualisiere Cart-Count
                const cartCount = document.getElementById('cartCount');
                if (cartCount && result.cart_count !== undefined) {
                    cartCount.textContent = result.cart_count;
                }
                
                // Entferne Checkout-Formular wenn Warenkorb leer ist
                if (result.cart_count === 0) {
                    const checkoutForm = document.getElementById('checkoutForm');
                    if (checkoutForm) {
                        const hr = checkoutForm.previousElementSibling;
                        if (hr && hr.tagName === 'HR') {
                            hr.remove();
                        }
                        checkoutForm.remove();
                    }
                    
                    // Zeige "Keine Produkte" Nachricht
                    const cartItems = document.getElementById('cartItems');
                    if (cartItems && cartItems.querySelectorAll('.cart-item').length === 0) {
                        cartItems.innerHTML = '<p class="text-muted text-center inventory-empty-hint py-3 mb-0">Keine Produkte hinzugefügt</p>';
                    }
                }
                if (removedSnapshot) {
                    this.lastAction = {
                        type: 'remove_from_cart',
                        productId: productId,
                        snapshot: removedSnapshot,
                    };
                    this.toggleUndoButton(true);
                }
            }
        } catch (error) {
            console.error('Fehler:', error);
            this.showError('Fehler beim Entfernen aus dem Warenkorb');
            this.enableRetry();
        }
    }
    
    showError(message) {
        const errorDiv = document.getElementById('scannerError');
        if (errorDiv) {
            errorDiv.className = 'alert alert-danger mt-2';
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
        }
        this.showFeedback(message, 'danger');
    }
    
    hideError() {
        const errorDiv = document.getElementById('scannerError');
        if (errorDiv) {
            errorDiv.style.display = 'none';
        }
    }

    showSuccess(message) {
        inventoryNotify(message, 'success');
        const errorDiv = document.getElementById('scannerError');
        if (errorDiv) {
            errorDiv.className = 'alert alert-success mt-2';
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
            setTimeout(() => this.hideError(), 2500);
        }
        this.showFeedback(message, 'success');
    }

    showFeedback(message, level) {
        const feedback = document.getElementById('scannerFeedback');
        if (!feedback) return;
        feedback.className = `alert alert-${level} mt-2`;
        feedback.textContent = message;
        feedback.classList.remove('d-none');
        setTimeout(() => feedback.classList.add('d-none'), 3000);
    }

    enableRetry(callback = null) {
        if (callback) {
            this.lastRetryCallback = callback;
        }
        const retryBtn = document.getElementById('retryLastCartActionBtn');
        if (retryBtn) {
            retryBtn.disabled = false;
        }
    }

    async retryLastAction() {
        if (this.lastRetryCallback) {
            await this.lastRetryCallback();
            return;
        }
        this.showError('Keine wiederholbare Aktion vorhanden.');
    }

    toggleUndoButton(enabled) {
        const undoBtn = document.getElementById('undoLastCartActionBtn');
        if (undoBtn) {
            undoBtn.disabled = !enabled;
        }
    }

    registerAddAction(result) {
        const ids = [];
        if (result?.product?.id) {
            ids.push(String(result.product.id));
        }
        if (Array.isArray(result?.added_products)) {
            result.added_products.forEach((p) => {
                if (p?.id) ids.push(String(p.id));
            });
        }
        if (ids.length > 0) {
            this.lastAction = { type: 'add_to_cart', productIds: [...new Set(ids)] };
            this.toggleUndoButton(true);
        }
    }

    undoLastAction() {
        if (!this.lastAction) {
            this.showError('Keine rueckgaengige Aktion vorhanden.');
            return;
        }
        if (this.lastAction.type === 'add_to_cart' && Array.isArray(this.lastAction.productIds)) {
            this.lastAction.productIds.forEach((id) => {
                this.removeFromCart(id);
            });
            this.showSuccess('Hinzugefuegte Produkte wieder aus dem Warenkorb entfernt.');
            this.lastAction = null;
            this.toggleUndoButton(false);
            return;
        }
        if (this.lastAction.type === 'remove_from_cart' && this.lastAction.snapshot) {
            const cartItems = document.getElementById('cartItems');
            if (!cartItems) return;
            cartItems.insertAdjacentHTML('beforeend', this.lastAction.snapshot);
            const cartCount = document.getElementById('cartCount');
            if (cartCount) {
                cartCount.textContent = String((parseInt(cartCount.textContent || '0', 10) || 0) + 1);
            }
            this.showSuccess('Letzte Aktion rueckgaengig gemacht (nur UI).');
            this.lastAction = null;
            this.toggleUndoButton(false);
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
    if (!(await inventoryConfirm('Möchten Sie dieses Produkt als gefunden markieren?', {
        title: 'Als gefunden markieren',
        confirmLabel: 'Markieren',
        danger: false,
    }))) {
        return;
    }
    
    try {
        const response = await fetchInventoryApi(`/products/${productId}/lifecycle`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ status: 'available', reason: 'marked_found' })
        });
        
        const result = await response.json();
        if (response.ok) {
            inventoryNotify('Produkt wurde als gefunden markiert.', 'success');
            window.location.reload();
        } else {
            inventoryNotify('Fehler beim Aktualisieren des Status.', 'danger');
        }
    } catch (error) {
        console.error('Fehler:', error);
        inventoryNotify('Fehler beim Aktualisieren des Status.', 'danger');
    }
}

// Markiere Produkt als fehlend (Status: missing)
async function markAsMissing(productId) {
    if (!(await inventoryConfirm('Möchten Sie dieses Produkt als fehlend markieren?', {
        title: 'Als fehlend markieren',
        confirmLabel: 'Markieren',
        danger: true,
    }))) {
        return;
    }
    
    try {
        const response = await fetchInventoryApi(`/products/${productId}/lifecycle`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ status: 'missing', reason: 'marked_missing' })
        });
        
        const result = await response.json();
        if (response.ok) {
            inventoryNotify('Produkt wurde als fehlend markiert.', 'success');
            window.location.reload();
        } else {
            inventoryNotify('Fehler beim Aktualisieren des Status.', 'danger');
        }
    } catch (error) {
        console.error('Fehler:', error);
        inventoryNotify('Fehler beim Aktualisieren des Status.', 'danger');
    }
}

// Markiere Produkt als defekt (Status: defective)
async function markAsDefective(productId) {
    if (!(await inventoryConfirm('Möchten Sie dieses Produkt als defekt markieren?', {
        title: 'Als defekt markieren',
        confirmLabel: 'Als defekt markieren',
        danger: true,
    }))) {
        return;
    }

    try {
        const response = await fetchInventoryApi(`/products/${productId}/lifecycle`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ status: 'defective', reason: 'defect_reported' })
        });

        if (response.ok) {
            inventoryNotify('Produkt wurde als defekt markiert.', 'success');
            if (window.stockManager && typeof window.stockManager.loadProducts === 'function') {
                await window.stockManager.loadProducts();
            } else {
                window.location.reload();
            }
        } else {
            const result = await response.json().catch(() => ({}));
            const msg = result?.message || 'Fehler beim Aktualisieren des Status.';
            inventoryNotify(msg, 'danger');
        }
    } catch (error) {
        console.error('Fehler:', error);
        inventoryNotify('Fehler beim Aktualisieren des Status.', 'danger');
    }
}

async function markAsInRepair(productId) {
    if (!(await inventoryConfirm('Produkt auf „In Reparatur“ setzen?', {
        title: 'In Reparatur',
        confirmLabel: 'Ja, setzen',
        danger: false,
    }))) {
        return;
    }
    try {
        const response = await fetch('/inventory/api/products/bulk-update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ product_ids: [productId], status: 'in_repair' }),
            credentials: 'same-origin',
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || 'Status-Update fehlgeschlagen');
        inventoryNotify(result.message || 'Status aktualisiert.', 'success');
        if (window.stockManager && typeof window.stockManager.loadProducts === 'function') {
            await window.stockManager.loadProducts();
        } else {
            window.location.reload();
        }
    } catch (e) {
        inventoryNotify(e.message || 'Status-Update fehlgeschlagen', 'danger');
    }
}

async function markAsAvailable(productId) {
    if (!(await inventoryConfirm('Produkt wieder als einsatzbereit markieren?', {
        title: 'Einsatzbereit setzen',
        confirmLabel: 'Ja, setzen',
        danger: false,
    }))) {
        return;
    }
    try {
        const response = await fetch('/inventory/api/products/bulk-update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ product_ids: [productId], status: 'available' }),
            credentials: 'same-origin',
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || 'Status-Update fehlgeschlagen');
        inventoryNotify(result.message || 'Status aktualisiert.', 'success');
        if (window.stockManager && typeof window.stockManager.loadProducts === 'function') {
            await window.stockManager.loadProducts();
        } else {
            window.location.reload();
        }
    } catch (e) {
        inventoryNotify(e.message || 'Status-Update fehlgeschlagen', 'danger');
    }
}

