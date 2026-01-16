// Inventory Management JavaScript

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
        this.viewMode = localStorage.getItem('inventoryViewMode') || 'grid'; // 'grid' oder 'list'
        this.activeQuickFilter = null; // Aktiver Schnellfilter
        this.sortField = localStorage.getItem('inventorySortField') || 'name';
        this.sortDirection = localStorage.getItem('inventorySortDirection') || 'asc';
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
        await this.loadFolders(); // Lade alle Ordner zuerst
        await this.loadCategories(); // Lade alle Kategorien
        await this.loadFilterOptions(); // Lade alle Filter-Optionen vom Server
        await this.loadProducts();
        this.renderFolders(); // Rendere Ordner-Struktur
        // Initiale UI-Aktualisierung
        this.updateSelectionUI();
        this.applyViewMode(); // Wende gespeicherten View-Mode an
        // Wende Filter an nach dem Laden
        this.applyFilters();
    }
    
    async loadFolders() {
        try {
            const response = await fetch('/inventory/api/folders');
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
            const response = await fetch('/inventory/api/categories');
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
            // Wenn currentFolderId null ist (Root), verwende folder_id=0 für Produkte ohne Ordner
            let url = '/inventory/api/inventory/filter-options';
            if (this.currentFolderId !== null) {
                url += `?folder_id=${this.currentFolderId}`;
            } else {
                // Root: nur Produkte ohne Ordner
                url += '?folder_id=0';
            }
            
            const response = await fetch(url);
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
                
                console.log(`Filter-Optionen geladen für Ordner: ${this.currentFolderId || 'Root'}`, {
                    categories: this.categories.size,
                    conditions: this.conditions.size,
                    locations: this.locations.size,
                    lengths: this.lengths.size,
                    purchaseYears: this.purchaseYears.size
                });
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
            const response = await fetch(`/inventory/api/products?${params.toString()}`);
            
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
        
        // Debug: Prüfe ob Filter-Werte extrahiert wurden (nur in Entwicklung)
        if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
            console.log('Filter-Werte extrahiert:', {
                categories: this.categories.size,
                conditions: this.conditions.size,
                locations: this.locations.size,
                lengths: this.lengths.size,
                purchaseYears: this.purchaseYears.size,
                products: this.products.length
            });
        }
    }
    
    // Öffentliche Methode zum Aktualisieren der Filter (kann von außen aufgerufen werden)
    async refreshFilters() {
        // Lade Filter-Optionen neu (mit aktuellem Ordner)
        await this.loadFilterOptions();
        // Lade Produkte neu und aktualisiere Filter
        await this.loadProducts();
        console.log('Filter aktualisiert');
    }
    
    updateCategories() {
        const categoryFilter = document.getElementById('categoryFilter');
        if (!categoryFilter) {
            console.warn('categoryFilter Element nicht gefunden');
            return;
        }
        
        const currentValue = categoryFilter.value || '';
        categoryFilter.innerHTML = '<option value="">Alle Kategorien</option>';
        
        // Füge alle Kategorien hinzu (auch wenn Set leer ist)
        const categoriesArray = Array.from(this.categories).filter(cat => cat && cat.trim() !== '');
        categoriesArray.sort().forEach(cat => {
            if (cat && cat.trim() !== '') {
                const option = document.createElement('option');
                option.value = cat;
                option.textContent = cat;
                categoryFilter.appendChild(option);
            }
        });
        
        // Stelle vorherigen Wert wieder her, falls er noch existiert
        if (currentValue && categoriesArray.includes(currentValue)) {
            categoryFilter.value = currentValue;
        } else {
            categoryFilter.value = '';
        }
    }
    
    updateFolders() {
        // Ordner-Filter wurde entfernt, daher diese Funktion ist nicht mehr nötig
        // Wird nur noch für interne Zwecke verwendet (falls benötigt)
        // Keine UI-Aktualisierung mehr
    }
    
    updateConditions() {
        const conditionFilter = document.getElementById('conditionFilter');
        if (!conditionFilter) {
            console.warn('conditionFilter Element nicht gefunden');
            return;
        }
        
        const currentValue = conditionFilter.value || '';
        conditionFilter.innerHTML = '<option value="">Alle Zustände</option>';
        
        // Füge alle Zustände hinzu (auch wenn Set leer ist)
        const conditionsArray = Array.from(this.conditions).filter(cond => cond && cond.trim() !== '');
        conditionsArray.sort().forEach(cond => {
            if (cond && cond.trim() !== '') {
                const option = document.createElement('option');
                option.value = cond;
                option.textContent = cond;
                conditionFilter.appendChild(option);
            }
        });
        
        // Stelle vorherigen Wert wieder her, falls er noch existiert
        if (currentValue && conditionsArray.includes(currentValue)) {
            conditionFilter.value = currentValue;
        } else {
            conditionFilter.value = '';
        }
    }
    
    updateLocations() {
        const locationFilter = document.getElementById('locationFilter');
        if (!locationFilter) {
            console.warn('locationFilter Element nicht gefunden');
            return;
        }
        
        const currentValue = locationFilter.value || '';
        locationFilter.innerHTML = '<option value="">Alle Lagerorte</option>';
        
        // Füge alle Lagerorte hinzu (auch wenn Set leer ist)
        const locationsArray = Array.from(this.locations).filter(loc => loc && loc.trim() !== '');
        locationsArray.sort().forEach(loc => {
            if (loc && loc.trim() !== '') {
                const option = document.createElement('option');
                option.value = loc;
                option.textContent = loc;
                locationFilter.appendChild(option);
            }
        });
        
        // Stelle vorherigen Wert wieder her, falls er noch existiert
        if (currentValue && locationsArray.includes(currentValue)) {
            locationFilter.value = currentValue;
        } else {
            locationFilter.value = '';
        }
    }
    
    updateLengths() {
        const lengthFilter = document.getElementById('lengthFilter');
        if (!lengthFilter) {
            console.warn('lengthFilter Element nicht gefunden');
            return;
        }
        
        const currentValue = lengthFilter.value || '';
        lengthFilter.innerHTML = '<option value="">Alle Längen</option>';
        
        // Füge alle Längen hinzu (auch wenn Set leer ist)
        const lengthsArray = Array.from(this.lengths).filter(len => len && len.trim() !== '');
        
        // Sortiere Längen intelligent (zuerst nach Zahl, dann alphabetisch)
        const sortedLengths = lengthsArray.sort((a, b) => {
            // Versuche zuerst numerischen Vergleich mit length_meters (falls verfügbar)
            // Extrahiere Zahlen aus Strings (z.B. "5m" -> 5)
            const numA = parseFloat(String(a).replace(/[^0-9.]/g, '')) || 0;
            const numB = parseFloat(String(b).replace(/[^0-9.]/g, '')) || 0;
            if (numA !== numB) {
                return numA - numB;
            }
            // Fallback: alphabetisch
            return String(a).localeCompare(String(b));
        });
        
        sortedLengths.forEach(len => {
            if (len && String(len).trim() !== '') {
                const option = document.createElement('option');
                option.value = String(len);
                option.textContent = String(len);
                lengthFilter.appendChild(option);
            }
        });
        
        // Stelle vorherigen Wert wieder her, falls er noch existiert
        if (currentValue && sortedLengths.includes(currentValue)) {
            lengthFilter.value = currentValue;
        } else {
            lengthFilter.value = '';
        }
    }
    
    updatePurchaseYears() {
        const purchaseYearFilter = document.getElementById('purchaseYearFilter');
        if (!purchaseYearFilter) {
            console.warn('purchaseYearFilter Element nicht gefunden');
            return;
        }
        
        const currentValue = purchaseYearFilter.value || '';
        purchaseYearFilter.innerHTML = '<option value="">Alle Jahre</option>';
        
        // Füge alle Jahre hinzu (auch wenn Set leer ist)
        const yearsArray = Array.from(this.purchaseYears).filter(year => year && String(year).trim() !== '');
        
        // Sortiere Jahre absteigend (neueste zuerst)
        const sortedYears = yearsArray.sort((a, b) => {
            const yearA = parseInt(String(a)) || 0;
            const yearB = parseInt(String(b)) || 0;
            return yearB - yearA; // Absteigend
        });
        
        sortedYears.forEach(year => {
            if (year && String(year).trim() !== '') {
                const option = document.createElement('option');
                option.value = String(year);
                option.textContent = String(year);
                purchaseYearFilter.appendChild(option);
            }
        });
        
        // Stelle vorherigen Wert wieder her, falls er noch existiert
        if (currentValue && sortedYears.includes(currentValue)) {
            purchaseYearFilter.value = currentValue;
        } else {
            purchaseYearFilter.value = '';
        }
    }
    
    setupEventListeners() {
        const searchInput = document.getElementById('searchInput');
        const categoryFilter = document.getElementById('categoryFilter');
        const statusFilter = document.getElementById('statusFilter');
        const conditionFilter = document.getElementById('conditionFilter');
        const locationFilter = document.getElementById('locationFilter');
        const lengthFilter = document.getElementById('lengthFilter');
        const purchaseYearFilter = document.getElementById('purchaseYearFilter');
        const resetFiltersBtn = document.getElementById('resetFiltersBtn');
        const borrowSelectedBtn = document.getElementById('borrowSelectedBtn');
        const bulkSelectAllBtn = document.getElementById('bulkSelectAllBtn');
        const bulkDeselectAllBtn = document.getElementById('bulkDeselectAllBtn');
        const bulkEditBtn = document.getElementById('bulkEditBtn');
        const bulkBorrowBtn = document.getElementById('bulkBorrowBtn');
        const bulkDeleteBtn = document.getElementById('bulkDeleteBtn');
        
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                clearTimeout(this.searchTimeout);
                this.searchTimeout = setTimeout(() => {
                    // Entferne active-Klasse von Schnellfilter-Buttons bei Suche
                    document.querySelectorAll('.quick-filter').forEach(b => {
                        b.classList.remove('active');
                    });
                    this.activeQuickFilter = null;
                    this.applyFilters();
                }, 300);
            });
        }
        
        // Alle Filter mit Event-Listenern versehen
        [categoryFilter, statusFilter, conditionFilter, locationFilter, lengthFilter, purchaseYearFilter].forEach(filter => {
            if (filter) {
                filter.addEventListener('change', () => this.applyFilters());
            }
        });
        
        if (resetFiltersBtn) {
            resetFiltersBtn.addEventListener('click', () => this.resetFilters());
        }
        
        if (bulkSelectAllBtn) {
            bulkSelectAllBtn.addEventListener('click', () => this.selectAllAvailable());
        }
        
        if (bulkDeselectAllBtn) {
            bulkDeselectAllBtn.addEventListener('click', () => this.deselectAll());
        }
        
        if (bulkEditBtn) {
            bulkEditBtn.addEventListener('click', () => this.openBulkEditModal());
        }
        
        if (bulkBorrowBtn) {
            bulkBorrowBtn.addEventListener('click', () => this.borrowSelected());
        }
        
        if (bulkDeleteBtn) {
            bulkDeleteBtn.addEventListener('click', () => this.openBulkDeleteModal());
        }
        
        if (borrowSelectedBtn) {
            borrowSelectedBtn.addEventListener('click', () => this.borrowSelected());
        }
        
        // Checkbox-Events werden direkt in attachCheckboxHandlers() behandelt
    }
    
    setupSortControls() {
        const validFields = ['name', 'category', 'condition', 'length'];
        if (!validFields.includes(this.sortField)) {
            this.sortField = 'name';
        }
        if (!['asc', 'desc'].includes(this.sortDirection)) {
            this.sortDirection = 'asc';
        }
        
        const sortFieldSelect = document.getElementById('sortField');
        const sortDirectionSelect = document.getElementById('sortDirection');
        const resetSortBtn = document.getElementById('resetSortBtn');
        
        if (sortFieldSelect) {
            sortFieldSelect.value = this.sortField;
            sortFieldSelect.addEventListener('change', () => {
                const selectedValue = sortFieldSelect.value;
                this.sortField = validFields.includes(selectedValue) ? selectedValue : 'name';
                localStorage.setItem('inventorySortField', this.sortField);
                this.applyFilters();
            });
        }
        
        if (sortDirectionSelect) {
            sortDirectionSelect.value = this.sortDirection;
            sortDirectionSelect.addEventListener('change', () => {
                const selectedValue = sortDirectionSelect.value === 'desc' ? 'desc' : 'asc';
                this.sortDirection = selectedValue;
                localStorage.setItem('inventorySortDirection', this.sortDirection);
                this.applyFilters();
            });
        }
        
        if (resetSortBtn) {
            resetSortBtn.addEventListener('click', () => {
                this.sortField = 'name';
                this.sortDirection = 'asc';
                localStorage.removeItem('inventorySortField');
                localStorage.removeItem('inventorySortDirection');
                if (sortFieldSelect) sortFieldSelect.value = 'name';
                if (sortDirectionSelect) sortDirectionSelect.value = 'asc';
                this.applyFilters();
            });
        }
    }
    
    applyFilters() {
        const search = document.getElementById('searchInput')?.value.trim() || '';
        const searchLower = search.toLowerCase();
        const category = document.getElementById('categoryFilter')?.value || '';
        const status = document.getElementById('statusFilter')?.value || '';
        const condition = document.getElementById('conditionFilter')?.value || '';
        const location = document.getElementById('locationFilter')?.value || '';
        const length = document.getElementById('lengthFilter')?.value || '';
        const purchaseYear = document.getElementById('purchaseYearFilter')?.value || '';
        
        this.filteredProducts = this.products.filter(p => {
            // Erweiterte Suche - durchsucht alle Attribute
            const matchesSearch = !search || this.matchesSearch(p, searchLower);
            
            // Ordner-Filter: 
            // - Wenn eine Suche aktiv ist: IGNORIERE Ordner-Filterung (durchsuche alle Ordner)
            // - Wenn keine Suche aktiv ist:
            //   - Wenn currentFolderId gesetzt ist: zeige nur Produkte aus diesem Ordner
            //   - Wenn kein currentFolderId (Root): zeige nur Produkte ohne Ordner (folder_id === null oder undefined)
            let matchesFolder = true;
            if (!search) {
                // Nur Ordner-Filterung anwenden, wenn keine Suche aktiv ist
                if (this.currentFolderId !== null && this.currentFolderId !== undefined) {
                    // Wir sind in einem Ordner: zeige nur Produkte aus diesem Ordner
                    matchesFolder = p.folder_id === this.currentFolderId;
                } else {
                    // Wir sind im Root: zeige NUR Produkte ohne Ordner (folder_id ist null, undefined oder nicht gesetzt)
                    matchesFolder = !p.folder_id || p.folder_id === null || p.folder_id === undefined;
                }
            }
            // Wenn search aktiv ist, bleibt matchesFolder = true (alle Ordner durchsuchen)
            
            // Andere Filter - behandeln null/undefined korrekt
            const matchesCategory = !category || (p.category !== null && p.category !== undefined && p.category === category);
            const matchesStatus = !status || (p.status !== null && p.status !== undefined && p.status === status);
            const matchesCondition = !condition || (p.condition !== null && p.condition !== undefined && p.condition === condition);
            const matchesLocation = !location || (p.location !== null && p.location !== undefined && p.location === location);
            const matchesLength = !length || this.matchesLength(p, length);
            const matchesPurchaseYear = !purchaseYear || this.matchesPurchaseYear(p, purchaseYear);
            
            return matchesSearch && matchesFolder && matchesCategory && matchesStatus && 
                   matchesCondition && matchesLocation && matchesLength && matchesPurchaseYear;
        });
        
        this.sortFilteredProducts();
        
        // Rendere Ordner neu (werden bei Suche ausgeblendet)
        this.renderFolders();
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
        document.getElementById('searchInput').value = '';
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
    
    renderProductsGrid() {
        const container = document.getElementById('productsContainer');
        if (!container) return;
        
        if (this.filteredProducts.length === 0) {
            container.innerHTML = `
                <div class="col-12">
                    <div class="inventory-empty text-center py-5">
                        <i class="bi bi-inbox fs-1 mb-3 text-muted"></i>
                        <p class="text-muted">Keine Produkte gefunden</p>
                    </div>
                </div>
            `;
            return;
        }
        
        const html = this.filteredProducts.map(product => 
            `<div class="col-12 col-md-6 col-lg-4 col-xl-3">${this.renderProductCard(product)}</div>`
        ).join('');
        container.innerHTML = html;
        
        // Nach dem Rendern Event-Handler für Checkboxen setzen
        this.attachCheckboxHandlers();
        
        // Favoriten-Buttons aktualisieren, falls Favoriten geladen wurden
        if (typeof updateFavoriteButtons === 'function') {
            setTimeout(() => updateFavoriteButtons(), 100);
        }
    }
    
    renderProductsList() {
        const container = document.getElementById('productsList');
        if (!container) return;
        
        if (this.filteredProducts.length === 0) {
            container.innerHTML = `
                <div class="list-group-item text-center py-5">
                    <i class="bi bi-inbox fs-1 mb-3 text-muted"></i>
                    <p class="text-muted mb-0">Keine Produkte gefunden</p>
                </div>
            `;
            return;
        }
        
        const html = this.filteredProducts.map(product => this.renderProductListItem(product)).join('');
        container.innerHTML = html;
        
        // Nach dem Rendern Event-Handler für Checkboxen setzen
        this.attachCheckboxHandlers();
        
        // Favoriten-Buttons aktualisieren, falls Favoriten geladen wurden
        if (typeof updateFavoriteButtons === 'function') {
            setTimeout(() => updateFavoriteButtons(), 100);
        }
    }
    
    renderProductListItem(product) {
        let statusBadge = '';
        if (product.status === 'available') {
            statusBadge = '<span class="badge bg-success">Verfügbar</span>';
        } else if (product.status === 'borrowed') {
            statusBadge = '<span class="badge bg-warning">Ausgeliehen</span>';
        } else if (product.status === 'missing') {
            statusBadge = '<span class="badge bg-danger">Fehlend</span>';
        }
        
        const isSelected = this.selectedProducts.has(product.id);
        const isSelectable = product.status === 'available';
        const checkboxTitle = isSelectable ? '' : ' title="Nur verfügbare Produkte lassen sich auswählen"';
        const checkbox = `
            <input type="checkbox" class="form-check-input me-2 product-checkbox"
                   value="${product.id}" data-product-id="${product.id}"
                   ${isSelected ? 'checked' : ''} ${isSelectable ? '' : 'disabled'}${checkboxTitle}
                   style="width: 1.1rem; height: 1.1rem;">
        `;
        
        const cardClickHandler = `onclick="if(window.stockManager){window.stockManager.handleCardClick(${product.id}, ${isSelectable});}"`;
        
        const selectionModeClass = isSelected ? 'selection-mode' : '';
        
        const folderBadge = product.folder_name 
            ? `<span class="badge bg-info me-2" 
                     onclick="event.stopPropagation(); if(window.stockManager){window.stockManager.navigateToFolder(${product.folder_id});}" 
                     title="Klicken um zu diesem Ordner zu navigieren">
                  <i class="bi bi-folder"></i> ${this.escapeHtml(product.folder_name)}
               </span>`
            : '';
        
        const details = [];
        if (this.isValidValue(product.category)) {
            details.push(`<span class="text-muted">${this.escapeHtml(product.category)}</span>`);
        }
        if (this.isValidValue(product.serial_number)) {
            details.push(`<small class="text-muted"><i class="bi bi-upc"></i> ${this.escapeHtml(product.serial_number)}</small>`);
        }
        if (this.isValidValue(product.location)) {
            details.push(`<small class="text-muted"><i class="bi bi-geo-alt"></i> ${this.escapeHtml(product.location)}</small>`);
        }
        if (this.isValidValue(product.length)) {
            details.push(`<small class="text-muted"><i class="bi bi-arrows-expand"></i> ${this.escapeHtml(product.length)}</small>`);
        }
        
        return `
            <div class="list-group-item list-group-item-action ${selectionModeClass}" style="cursor: pointer;">
                <div class="d-flex align-items-center">
                    <div class="form-check me-2" style="z-index: 10; position: relative;">
                        ${checkbox}
                    </div>
                    <div class="flex-grow-1" ${cardClickHandler}>
                        <div class="d-flex align-items-center mb-1">
                            <h6 class="mb-0 me-2">${this.escapeHtml(product.name)}</h6>
                            ${statusBadge}
                            ${folderBadge}
                        </div>
                        <div class="d-flex flex-wrap gap-2 align-items-center">
                            ${details.join('')}
                        </div>
                    </div>
                    <div class="d-flex gap-2 align-items-center">
                        ${isSelectable 
                            ? `<a href="/inventory/products/${product.id}/borrow" class="btn btn-sm btn-primary" onclick="event.stopPropagation()">Ausleihen</a>`
                            : ''}
                        <a href="/inventory/products/${product.id}/edit" class="btn btn-sm btn-outline-secondary" onclick="event.stopPropagation()">Bearbeiten</a>
                        <button type="button" class="btn btn-sm btn-outline-warning favorite-btn" 
                                data-product-id="${product.id}" 
                                onclick="event.stopPropagation(); toggleFavorite(${product.id});"
                                title="Zu Favoriten hinzufügen">
                            <i class="bi bi-star"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
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
            ? `<img src="/inventory/product-images/${this.escapeHtml(product.image_path)}" alt="${this.escapeHtml(product.name)}" class="product-image" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">`
            : '';
        const imageContainer = product.image_path
            ? `<div class="position-relative" style="width: 100%; height: 200px; overflow: hidden;">${imageHtml}<div class="product-image-placeholder" style="display: none;"><i class="bi bi-box-seam fs-1 text-muted"></i></div></div>`
            : '<div class="product-image-placeholder"><i class="bi bi-box-seam fs-1 text-muted"></i></div>';
        
        const isSelected = this.selectedProducts.has(product.id);
        const isSelectable = product.status === 'available';
        const checkboxTitle = isSelectable ? '' : ' title="Nur verfügbare Produkte lassen sich auswählen"';
        const checkbox = `
            <div class="position-absolute top-0 start-0 m-2" style="z-index: 10;">
                <div class="form-check">
                    <input type="checkbox" class="form-check-input product-checkbox"
                           value="${product.id}" data-product-id="${product.id}"
                           ${isSelected ? 'checked' : ''} ${isSelectable ? '' : 'disabled'}${checkboxTitle}
                           style="width: 1.2rem; height: 1.2rem; background-color: white; cursor: pointer;">
                </div>
            </div>
        `;
        
        // Click-Handler: Wenn Auswahl aktiv, toggle Auswahl; sonst Details anzeigen
        const cardClickHandler = `onclick="if(window.stockManager){window.stockManager.handleCardClick(${product.id}, ${isSelectable});}"`;
        
        // selection-mode Klasse nur hinzufügen, wenn das Produkt tatsächlich ausgewählt ist
        const selectionModeClass = isSelected ? 'selection-mode' : '';
        
        return `
            <div class="card product-card ${selectionModeClass}" ${cardClickHandler} style="cursor: pointer;">
                <div class="position-relative">
                    ${imageContainer}
                    ${checkbox}
                    ${statusBadge ? `<div class="position-absolute top-0 end-0 m-2" style="z-index: 5;">${statusBadge}</div>` : ''}
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
                    <div class="mt-2 d-flex justify-content-between align-items-center">
                        <div>
                            ${isSelectable 
                                ? `<a href="/inventory/products/${product.id}/borrow" class="btn btn-sm btn-primary" onclick="event.stopPropagation()">Ausleihen</a>`
                                : ''}
                            <a href="/inventory/products/${product.id}/edit" class="btn btn-sm btn-outline-secondary" onclick="event.stopPropagation()">Bearbeiten</a>
                        </div>
                        <button type="button" class="btn btn-sm btn-outline-warning favorite-btn" 
                                data-product-id="${product.id}" 
                                onclick="event.stopPropagation(); toggleFavorite(${product.id});"
                                title="Zu Favoriten hinzufügen">
                            <i class="bi bi-star"></i>
                        </button>
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
            ? `<img src="/inventory/product-images/${this.escapeHtml(product.image_path)}" alt="${this.escapeHtml(product.name)}" class="product-detail-image mb-3" onerror="this.style.display='none';">`
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
            <div class="d-flex gap-2 flex-wrap">
                ${product.status === 'available' 
                    ? `<a href="/inventory/products/${product.id}/borrow" class="btn btn-primary">Ausleihen</a>`
                    : ''}
                <a href="/inventory/products/${product.id}/edit" class="btn btn-outline-secondary">Bearbeiten</a>
                <a href="/inventory/products/${product.id}/documents" class="btn btn-outline-info">
                    <i class="bi bi-file-earmark"></i> Dokumente
                </a>
                <button type="button" class="btn btn-outline-warning favorite-btn" 
                        data-product-id="${product.id}" 
                        onclick="toggleFavorite(${product.id});">
                    <i class="bi bi-star"></i> Favorit
                </button>
                ${product.status === 'missing'
                    ? `<button class="btn btn-success btn-sm" onclick="markAsFound(${product.id})">Als gefunden markieren</button>`
                    : `<button class="btn btn-outline-danger btn-sm" onclick="markAsMissing(${product.id})">Als fehlend markieren</button>`}
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
    
    showSuccess(message) {
        // Erstelle Toast-Benachrichtigung
        const toast = document.createElement('div');
        toast.className = 'toast align-items-center text-white bg-success border-0';
        toast.setAttribute('role', 'alert');
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    <i class="bi bi-check-circle me-2"></i>${this.escapeHtml(message)}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;
        
        // Füge Toast-Container hinzu falls nicht vorhanden
        let toastContainer = document.getElementById('toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
            toastContainer.style.zIndex = '1060';
            document.body.appendChild(toastContainer);
        }
        
        toastContainer.appendChild(toast);
        
        // Zeige Toast
        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();
        
        // Entferne Toast nach dem Ausblenden
        toast.addEventListener('hidden.bs.toast', () => {
            toast.remove();
        });
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
                if (product && product.status === 'available') {
                    this.selectedProducts.add(productId);
                }
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
        const bulkToolbar = document.getElementById('bulkSelectionToolbar');
        const bulkSelectionCount = document.getElementById('bulkSelectionCount');
        
        if (selectedCountEl) {
            selectedCountEl.textContent = selected.length;
        }
        
        if (borrowSelectedBtn) {
            borrowSelectedBtn.style.display = selected.length > 0 ? 'inline-block' : 'none';
        }
        
        // Toolbar anzeigen/verstecken
        if (bulkToolbar) {
            if (selected.length > 0) {
                bulkToolbar.style.display = 'block';
            } else {
                bulkToolbar.style.display = 'none';
            }
        }
        
        if (bulkSelectionCount) {
            bulkSelectionCount.textContent = selected.length;
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
    
    openBulkDeleteModal() {
        const selectedIds = this.getSelectedProducts();
        if (selectedIds.length === 0) {
            alert('Bitte wählen Sie mindestens ein Produkt aus.');
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
            alert('Keine Produkte zum Löschen ausgewählt.');
            return;
        }
        
        const confirmBtn = document.getElementById('bulkDeleteConfirmBtn');
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Löschen...';
        }
        
        try {
            const response = await fetch('/inventory/api/products/bulk-delete', {
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
                throw new Error(data.error || 'Fehler beim Löschen der Produkte');
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
            this.showSuccess(data.message || `${data.deleted_count} Produkt(e) erfolgreich gelöscht.`);
            
            // Entferne gelöschte Produkte aus der Auswahl
            productIds.forEach(id => {
                this.selectedProducts.delete(id);
            });
            
            // Lade Produkte neu
            await this.loadProducts();
            
        } catch (error) {
            console.error('Fehler beim Löschen:', error);
            this.showError(error.message || 'Fehler beim Löschen der Produkte. Bitte versuchen Sie es erneut.');
            
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
                confirmBtn.innerHTML = '<i class="bi bi-trash"></i> Ja, löschen';
            }
        }
    }
    
    async deleteProduct(productId) {
        if (!productId) {
            alert('Keine Produkt-ID angegeben.');
            return;
        }
        
        // Bestätigung
        if (!confirm(`Möchten Sie dieses Produkt wirklich löschen? Diese Aktion kann nicht rückgängig gemacht werden.`)) {
            return;
        }
        
        try {
            const response = await fetch(`/inventory/api/products/${productId}`, {
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
            this.showSuccess(data.message || 'Produkt erfolgreich gelöscht.');
            
            // Entferne aus der Auswahl falls ausgewählt
            this.selectedProducts.delete(productId);
            
            // Lade Produkte neu
            await this.loadProducts();
            
        } catch (error) {
            console.error('Fehler beim Löschen:', error);
            this.showError(error.message || 'Fehler beim Löschen des Produkts. Bitte versuchen Sie es erneut.');
        }
    }
    
    openBulkEditModal() {
        // Hole aktuelle Auswahl und speichere in lokaler Variable (Snapshot)
        const selectedIds = [...this.getSelectedProducts()];
        if (selectedIds.length === 0) {
            alert('Bitte wählen Sie mindestens ein Produkt aus.');
            return;
        }
        
        const modalEl = document.getElementById('bulkEditModal');
        if (!modalEl) {
            console.error('Bulk-Edit-Modal nicht gefunden');
            return;
        }
        
        const modal = new bootstrap.Modal(modalEl);
        const productCountEl = document.getElementById('bulkEditProductCount');
        const attributeSelect = document.getElementById('bulkEditAttribute');
        const fieldsContainer = document.getElementById('bulkEditFields');
        const form = document.getElementById('bulkEditForm');
        let submitBtn = document.getElementById('bulkEditSubmitBtn');
        
        if (productCountEl) {
            productCountEl.textContent = selectedIds.length;
        }
        
        // Reset Formular
        if (form) {
            form.reset();
        }
        if (fieldsContainer) {
            fieldsContainer.innerHTML = '<p class="text-muted">Bitte wählen Sie ein Attribut aus.</p>';
        }
        if (submitBtn) {
            submitBtn.disabled = true;
        }
        
        // Entferne alle alten Event-Handler durch Klonen des Elements
        // Dies stellt sicher, dass keine alten Handler mehr aktiv sind
        if (attributeSelect) {
            const newAttributeSelect = attributeSelect.cloneNode(true);
            attributeSelect.parentNode.replaceChild(newAttributeSelect, attributeSelect);
            // Aktualisiere Referenz
            const attributeSelectRef = newAttributeSelect;
            
            const handleAttributeChange = () => {
                const attribute = attributeSelectRef.value;
                if (!fieldsContainer) return;
                
                // Hole aktuelle submitBtn Referenz (kann nach Klonen geändert worden sein)
                const currentSubmitBtn = document.getElementById('bulkEditSubmitBtn');
                
                fieldsContainer.innerHTML = '';
                
                // Aktiviere Button sofort, wenn ein Attribut ausgewählt ist
                // (auch leere Werte sind gültig, um Werte zu entfernen)
                if (currentSubmitBtn) {
                    currentSubmitBtn.disabled = !attribute;
                }
                
                if (!attribute) {
                    fieldsContainer.innerHTML = '<p class="text-muted">Bitte wählen Sie ein Attribut aus.</p>';
                    if (currentSubmitBtn) {
                        currentSubmitBtn.disabled = true;
                    }
                    return;
                }
                
                let fieldHtml = '';
                
                switch (attribute) {
                    case 'location':
                        fieldHtml = `
                            <div class="mb-3">
                                <label for="bulkEditLocation" class="form-label">Neuer Lagerort</label>
                                <input type="text" class="form-control" id="bulkEditLocation" 
                                       placeholder="z.B. Regal A, Kiste 3">
                                <small class="form-text text-muted">Leer lassen um Lagerort zu entfernen.</small>
                            </div>
                        `;
                        break;
                    
                    case 'length':
                        fieldHtml = `
                            <div class="mb-3">
                                <label for="bulkEditLength" class="form-label">Neue Länge (in Metern)</label>
                                <input type="number" class="form-control" id="bulkEditLength" 
                                       step="0.01" min="0" placeholder="z.B. 5.5">
                                <small class="form-text text-muted">Leer lassen um Länge zu entfernen.</small>
                            </div>
                        `;
                        break;
                    
                    case 'condition':
                        fieldHtml = `
                            <div class="mb-3">
                                <label for="bulkEditCondition" class="form-label">Neuer Zustand</label>
                                <select class="form-select" id="bulkEditCondition">
                                    <option value="">Kein Zustand (entfernen)</option>
                                    <option value="Neu">Neu</option>
                                    <option value="Gut">Gut</option>
                                    <option value="Gebraucht">Gebraucht</option>
                                    <option value="Beschädigt">Beschädigt</option>
                                </select>
                            </div>
                        `;
                        break;
                    
                    case 'category':
                        fieldHtml = `
                            <div class="mb-3">
                                <label for="bulkEditCategory" class="form-label">Neue Kategorie</label>
                                <select class="form-select" id="bulkEditCategory">
                                    <option value="">Keine Kategorie (entfernen)</option>
                                    ${this.categories ? Array.from(this.categories).sort().map(cat => 
                                        `<option value="${this.escapeHtml(cat)}">${this.escapeHtml(cat)}</option>`
                                    ).join('') : ''}
                                </select>
                            </div>
                        `;
                        break;
                    
                    case 'folder_id':
                        fieldHtml = `
                            <div class="mb-3">
                                <label for="bulkEditFolder" class="form-label">Neuer Ordner</label>
                                <select class="form-select" id="bulkEditFolder">
                                    <option value="">Kein Ordner (entfernen)</option>
                                    ${this.folders ? Array.from(this.folders).sort((a, b) => a.name.localeCompare(b.name)).map(folder => 
                                        `<option value="${folder.id}">${this.escapeHtml(folder.name)}</option>`
                                    ).join('') : ''}
                                </select>
                            </div>
                        `;
                        break;
                    
                    case 'remove_image':
                        fieldHtml = `
                            <div class="alert alert-warning">
                                <i class="bi bi-exclamation-triangle"></i> 
                                Die Produktbilder aller ausgewählten Produkte werden entfernt. Diese Aktion kann nicht rückgängig gemacht werden.
                            </div>
                        `;
                        break;
                }
                
                fieldsContainer.innerHTML = fieldHtml;
                
                // Füge Event-Handler für Eingabefelder hinzu, um Button zu aktivieren
                // Warte kurz, damit das DOM aktualisiert ist
                setTimeout(() => {
                    // Hole aktuelle submitBtn Referenz (kann nach Klonen geändert worden sein)
                    const currentSubmitBtn = document.getElementById('bulkEditSubmitBtn');
                    if (!currentSubmitBtn) return;
                    
                    const updateSubmitButton = () => {
                        const attribute = attributeSelectRef.value;
                        if (!attribute) {
                            currentSubmitBtn.disabled = true;
                            return;
                        }
                        
                        // Für alle Attribute: Button ist aktiviert, sobald ein Attribut ausgewählt ist
                        // (auch leere Werte sind gültig, um Werte zu entfernen)
                        // Ausnahme: Dropdowns müssen eine Auswahl haben (auch wenn es "entfernen" ist)
                        let isEnabled = true;
                        
                        switch (attribute) {
                            case 'location':
                                // Textfeld: Button ist immer aktiviert (leer = entfernen ist gültig)
                                isEnabled = true;
                                break;
                            
                            case 'length':
                                // Textfeld: Button ist immer aktiviert (leer = entfernen ist gültig)
                                isEnabled = true;
                                break;
                            
                            case 'condition':
                                const conditionSelect = document.getElementById('bulkEditCondition');
                                // Dropdown: muss existieren (wird automatisch aktiviert wenn Feld erstellt wird)
                                isEnabled = conditionSelect !== null;
                                break;
                            
                            case 'category':
                                const categorySelect = document.getElementById('bulkEditCategory');
                                // Dropdown: muss existieren
                                isEnabled = categorySelect !== null;
                                break;
                            
                            case 'folder_id':
                                const folderSelect = document.getElementById('bulkEditFolder');
                                // Dropdown: muss existieren
                                isEnabled = folderSelect !== null;
                                break;
                            
                            case 'remove_image':
                                // Für remove_image ist immer aktiviert (die Aktion selbst)
                                isEnabled = true;
                                break;
                        }
                        
                        currentSubmitBtn.disabled = !isEnabled;
                    };
                    
                    // Event-Handler für verschiedene Feldtypen hinzufügen
                    const locationInput = document.getElementById('bulkEditLocation');
                    if (locationInput) {
                        locationInput.addEventListener('input', updateSubmitButton);
                        locationInput.addEventListener('change', updateSubmitButton);
                    }
                    
                    const lengthInput = document.getElementById('bulkEditLength');
                    if (lengthInput) {
                        lengthInput.addEventListener('input', updateSubmitButton);
                        lengthInput.addEventListener('change', updateSubmitButton);
                    }
                    
                    const conditionSelect = document.getElementById('bulkEditCondition');
                    if (conditionSelect) {
                        conditionSelect.addEventListener('change', updateSubmitButton);
                    }
                    
                    const categorySelect = document.getElementById('bulkEditCategory');
                    if (categorySelect) {
                        categorySelect.addEventListener('change', updateSubmitButton);
                    }
                    
                    const folderSelect = document.getElementById('bulkEditFolder');
                    if (folderSelect) {
                        folderSelect.addEventListener('change', updateSubmitButton);
                    }
                    
                    // Initiale Prüfung
                    updateSubmitButton();
                }, 10);
            };
            
            attributeSelectRef.addEventListener('change', handleAttributeChange);
        }
        
        // Submit-Handler - verwende lokale selectedIds (Snapshot)
        // WICHTIG: submitBtn wird NICHT geklont, damit die Referenz konsistent bleibt
        if (submitBtn) {
            // Entferne alte Event-Handler (falls vorhanden)
            const newSubmitBtn = submitBtn.cloneNode(true);
            submitBtn.parentNode.replaceChild(newSubmitBtn, submitBtn);
            // Aktualisiere Referenz für alle nachfolgenden Verwendungen
            submitBtn = newSubmitBtn;
            
            const handleSubmit = async () => {
                const attribute = attributeSelect ? (document.getElementById('bulkEditAttribute')?.value || '') : '';
                if (!attribute) {
                    alert('Bitte wählen Sie ein Attribut aus.');
                    return;
                }
                
                // Verwende die lokale selectedIds-Variable (Snapshot beim Öffnen)
                const updateData = {
                    product_ids: selectedIds,
                };
                
                let value = null;
                
                switch (attribute) {
                    case 'location':
                        const locationInput = document.getElementById('bulkEditLocation');
                        value = locationInput ? locationInput.value.trim() || null : null;
                        updateData.location = value;
                        break;
                    
                    case 'length':
                        const lengthInput = document.getElementById('bulkEditLength');
                        if (lengthInput && lengthInput.value) {
                            value = parseFloat(lengthInput.value);
                            if (isNaN(value) || value < 0) {
                                alert('Bitte geben Sie eine gültige Länge ein (Zahl >= 0).');
                                return;
                            }
                            updateData.length = value;
                        } else {
                            updateData.length = null;
                        }
                        break;
                    
                    case 'condition':
                        const conditionSelect = document.getElementById('bulkEditCondition');
                        value = conditionSelect ? conditionSelect.value || null : null;
                        updateData.condition = value;
                        break;
                    
                    case 'category':
                        const categorySelect = document.getElementById('bulkEditCategory');
                        value = categorySelect ? categorySelect.value || null : null;
                        updateData.category = value;
                        break;
                    
                    case 'folder_id':
                        const folderSelect = document.getElementById('bulkEditFolder');
                        value = folderSelect ? folderSelect.value || null : null;
                        updateData.folder_id = value;
                        break;
                    
                    case 'remove_image':
                        if (!confirm(`Möchten Sie wirklich die Produktbilder von ${selectedIds.length} Produkt(en) entfernen?`)) {
                            return;
                        }
                        updateData.remove_image = true;
                        break;
                }
                
                // Loading-State
                submitBtn.disabled = true;
                const originalText = submitBtn.innerHTML;
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Aktualisiere...';
                
                try {
                    const response = await fetch('/inventory/api/products/bulk-update', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(updateData),
                    });
                    
                    const result = await response.json();
                    
                    if (!response.ok) {
                        throw new Error(result.error || 'Fehler beim Aktualisieren');
                    }
                    
                    // Erfolg
                    modal.hide();
                    alert(result.message || `${result.updated_count || selectedIds.length} Produkt(e) erfolgreich aktualisiert.`);
                    
                    // Produktliste neu laden
                    await this.loadProducts();
                    this.applyFilters();
                    
                    // Auswahl zurücksetzen - WICHTIG: Leere die Auswahl nach erfolgreicher Bearbeitung
                    this.selectedProducts.clear();
                    this.updateSelectionUI();
                    
                } catch (error) {
                    console.error('Bulk-Update Fehler:', error);
                    alert('Fehler beim Aktualisieren: ' + (error.message || 'Unbekannter Fehler'));
                } finally {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = originalText;
                }
            };
            
            submitBtn.addEventListener('click', handleSubmit);
        }
        
        modal.show();
    }
    
    // View Toggle Funktionen
    setupViewToggle() {
        const listViewBtn = document.getElementById('listViewBtn');
        const gridViewBtn = document.getElementById('gridViewBtn');
        
        if (listViewBtn && gridViewBtn) {
            listViewBtn.addEventListener('click', () => {
                this.viewMode = 'list';
                localStorage.setItem('inventoryViewMode', 'list');
                this.applyViewMode();
            });
            
            gridViewBtn.addEventListener('click', () => {
                this.viewMode = 'grid';
                localStorage.setItem('inventoryViewMode', 'grid');
                this.applyViewMode();
            });
        }
    }
    
    applyViewMode() {
        const listViewBtn = document.getElementById('listViewBtn');
        const gridViewBtn = document.getElementById('gridViewBtn');
        const gridViewContainer = document.getElementById('gridViewContainer');
        const listViewContainer = document.getElementById('listViewContainer');
        
        if (this.viewMode === 'list') {
            if (listViewContainer) listViewContainer.style.display = 'block';
            if (gridViewContainer) gridViewContainer.style.display = 'none';
            if (listViewBtn) listViewBtn.classList.add('active');
            if (gridViewBtn) gridViewBtn.classList.remove('active');
        } else {
            if (gridViewContainer) gridViewContainer.style.display = 'block';
            if (listViewContainer) listViewContainer.style.display = 'none';
            if (gridViewBtn) gridViewBtn.classList.add('active');
            if (listViewBtn) listViewBtn.classList.remove('active');
        }
        
        // Rendere Produkte neu mit aktuellem View-Mode
        this.renderProducts();
    }
    
    // Ordner-Funktionen
    renderFolders() {
        // Zeige Ordner nur wenn keine Suche aktiv ist
        const searchInput = document.getElementById('searchInput');
        const hasSearch = searchInput && searchInput.value.trim() !== '';
        
        if (hasSearch) {
            // Verstecke Ordner bei Suche
            const foldersGrid = document.getElementById('foldersGridView');
            const foldersList = document.getElementById('foldersListView');
            if (foldersGrid) foldersGrid.style.display = 'none';
            if (foldersList) foldersList.style.display = 'none';
            return;
        }
        
        // Zeige Ordner nur im Root (nicht wenn wir in einem Ordner sind)
        // Im Root: zeige alle Ordner
        // In einem Ordner: zeige keine Ordner (da Unterordner noch nicht implementiert sind)
        let foldersToShow = [];
        if (this.currentFolderId === null) {
            // Wir sind im Root: zeige alle Ordner
            foldersToShow = this.folders;
        }
        // Wenn wir in einem Ordner sind: zeige keine Ordner (Unterordner-Funktion noch nicht implementiert)
        
        if (foldersToShow.length === 0) {
            const foldersGrid = document.getElementById('foldersGridView');
            const foldersList = document.getElementById('foldersListView');
            if (foldersGrid) foldersGrid.style.display = 'none';
            if (foldersList) foldersList.style.display = 'none';
            return;
        }
        
        // Rendere Ordner in Grid-View
        const foldersGrid = document.getElementById('foldersGridView');
        if (foldersGrid) {
            const html = foldersToShow.map(folder => this.renderFolderCard(folder)).join('');
            foldersGrid.innerHTML = html;
            foldersGrid.style.display = 'flex';
        }
        
        // Rendere Ordner in List-View
        const foldersList = document.getElementById('foldersListView');
        if (foldersList) {
            const html = foldersToShow.map(folder => this.renderFolderListItem(folder)).join('');
            foldersList.innerHTML = html;
            foldersList.style.display = 'block';
        }
    }
    
    renderFolderCard(folder) {
        const productCount = folder.product_count || 0;
        return `
            <div class="col-12 col-md-6 col-lg-4 col-xl-3">
                <div class="card folder-item h-100" onclick="if(window.stockManager){window.stockManager.navigateToFolder(${folder.id});}">
                    <div class="card-body text-center">
                        <i class="bi bi-folder-fill text-warning fs-1 mb-2"></i>
                        <h6 class="mb-1">${this.escapeHtml(folder.name)}</h6>
                        <small class="text-muted">${productCount} Produkt${productCount !== 1 ? 'e' : ''}</small>
                    </div>
                </div>
            </div>
        `;
    }
    
    renderFolderListItem(folder) {
        const productCount = folder.product_count || 0;
        return `
            <a href="#" class="list-group-item list-group-item-action" onclick="event.preventDefault(); if(window.stockManager){window.stockManager.navigateToFolder(${folder.id});}">
                <div class="d-flex align-items-center">
                    <i class="bi bi-folder-fill text-warning fs-4 me-3"></i>
                    <div class="flex-grow-1">
                        <h6 class="mb-0">${this.escapeHtml(folder.name)}</h6>
                        <small class="text-muted">${productCount} Produkt${productCount !== 1 ? 'e' : ''}</small>
                    </div>
                </div>
            </a>
        `;
    }
    
    navigateToFolder(folderId) {
        // Navigiere zu Ordner-Ansicht
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
                    valueA = getString(a[field]);
                    valueB = getString(b[field]);
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
                    <div class="btn-group" role="group">
                        <a href="/inventory/return?transaction_number=${borrow.transaction_number}" 
                           class="btn btn-sm btn-success" 
                           title="Zurückgeben">
                            <i class="bi bi-arrow-return-left"></i> Rückgabe
                        </a>
                        <a href="/inventory/api/borrow/${borrow.id}/pdf" 
                           class="btn btn-sm btn-outline-secondary" 
                           title="Ausleihschein herunterladen">
                            <i class="bi bi-file-pdf"></i>
                        </a>
                    </div>
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
                                console.log('Video gestartet, Video-Dimensionen:', video.videoWidth, 'x', video.videoHeight);
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
                            // Verwende dispatchEvent mit korrekten Optionen
                            const submitEvent = new Event('submit', { 
                                cancelable: true, 
                                bubbles: true 
                            });
                            form.dispatchEvent(submitEvent);
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
                    this.showError('QR Code Nicht erkannt');
                    setTimeout(() => this.hideError(), 5000);
                } else {
                    this.showError('QR Code Nicht erkannt');
                    setTimeout(() => this.hideError(), 5000);
                }
            }
        } catch (error) {
            console.error('Fehler:', error);
            this.showError('QR Code Nicht erkannt');
            setTimeout(() => this.hideError(), 5000);
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
                                console.log('Video gestartet (BorrowScanner), Video-Dimensionen:', video.videoWidth, 'x', video.videoHeight);
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
                console.log('QR-Code erkannt (BorrowScanner):', code.data);
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
                    console.log('Starte addToCart für:', qrCodeData);
                    this.addToCart(qrCodeData).then(() => {
                        console.log('addToCart erfolgreich abgeschlossen');
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
        console.log('=== addToCart START ===', qrCode);
        try {
            const formData = new FormData();
            formData.append('action', 'add_to_cart');
            formData.append('qr_code', qrCode);
            
            console.log('Sende Request an Server...');
            const response = await fetch('/inventory/borrow-scanner', {
                method: 'POST',
                body: formData
            });
            
            console.log('Response erhalten, Status:', response.status);
            
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
            console.log('JSON Response:', result);
            
            if (result.success) {
                console.log('=== SERVER ERFOLGREICH ===');
                
                // Zeige Modal für Sets
                if (result.is_set) {
                    this.showSetScannedModal(result);
                }
                
                console.log('Produkt:', result.product);
                console.log('Set:', result.set);
                console.log('Cart Count:', result.cart_count);
                
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
                
                // ensureCheckoutForm wird jetzt in updateCartFromJSON aufgerufen
                
                return Promise.resolve();
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
        console.log('=== updateCartFromJSON START ===', result);
        
        // Aktualisiere Cart-Count SOFORT
        const cartCount = document.getElementById('cartCount');
        if (cartCount) {
            if (result.cart_count !== undefined) {
                cartCount.textContent = result.cart_count;
                console.log('✓ Cart-Count aktualisiert:', result.cart_count);
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
            console.log('Füge Set-Produkte hinzu:', result.added_products);
            
            // Verhindere, dass loadCheckoutForm den Warenkorb überschreibt
            cartItems.setAttribute('data-updating', 'true');
            
            // Entferne "Keine Produkte hinzugefügt" Nachricht
            const emptyMessage = cartItems.querySelector('p.text-muted');
            if (emptyMessage) {
                emptyMessage.remove();
                console.log('✓ Leere Nachricht entfernt');
            }
            
            // Füge alle Produkte des Sets hinzu
            result.added_products.forEach(product => {
                // Prüfe ob Produkt bereits vorhanden ist
                const existingItem = cartItems.querySelector(`[data-product-id="${product.id}"]`);
                if (existingItem) {
                    console.log(`⚠ Produkt ${product.id} bereits vorhanden, überspringe`);
                    return;
                }
                
                // Erstelle neues Cart-Item
                const newItem = document.createElement('div');
                newItem.className = 'card mb-2 cart-item';
                newItem.setAttribute('data-product-id', product.id);
                
                const categoryHtml = product.category 
                    ? `<br><small class="text-muted">${this.escapeHtml(product.category)}</small>` 
                    : '';
                
                newItem.innerHTML = `
                    <div class="card-body p-2">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <strong>${this.escapeHtml(product.name)}</strong>
                                ${categoryHtml}
                            </div>
                            <button class="btn btn-sm btn-outline-danger remove-from-cart" data-product-id="${product.id}">
                                <i class="bi bi-trash"></i>
                            </button>
                        </div>
                    </div>
                `;
                
                cartItems.appendChild(newItem);
                console.log(`✓ Produkt ${product.id} zum DOM hinzugefügt`);
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
        
        console.log('Füge Produkt hinzu:', result.product);
        
        // Prüfe ob Produkt bereits vorhanden ist
        const existingItem = cartItems.querySelector(`[data-product-id="${result.product.id}"]`);
        if (existingItem) {
            console.log('⚠ Produkt bereits vorhanden, überspringe Hinzufügen');
            return;
        }
        
        // Verhindere, dass loadCheckoutForm den Warenkorb überschreibt
        // Markiere dass wir gerade ein Produkt hinzufügen
        cartItems.setAttribute('data-updating', 'true');
        
        // Entferne "Keine Produkte hinzugefügt" Nachricht
        const emptyMessage = cartItems.querySelector('p.text-muted');
        if (emptyMessage) {
            emptyMessage.remove();
            console.log('✓ Leere Nachricht entfernt');
        }
        
        // Erstelle neues Cart-Item
        const newItem = document.createElement('div');
        newItem.className = 'card mb-2 cart-item';
        newItem.setAttribute('data-product-id', result.product.id);
        
        const categoryHtml = result.product.category 
            ? `<br><small class="text-muted">${this.escapeHtml(result.product.category)}</small>` 
            : '';
        
        newItem.innerHTML = `
            <div class="card-body p-2">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>${this.escapeHtml(result.product.name)}</strong>
                        ${categoryHtml}
                    </div>
                    <button class="btn btn-sm btn-outline-danger remove-from-cart" data-product-id="${result.product.id}">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>
        `;
        
        cartItems.appendChild(newItem);
        console.log('✓ Produkt zum DOM hinzugefügt');
        
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
        
        // Prüfe ob Checkout-Formular benötigt wird
        this.ensureCheckoutForm(result.cart_count);
        
        console.log('=== updateCartFromJSON FERTIG ===');
    }
    
    ensureCheckoutForm(cartCount) {
        // Stelle sicher, dass das Checkout-Formular vorhanden ist, wenn Produkte im Warenkorb sind
        const checkoutForm = document.getElementById('checkoutForm');
        if (!checkoutForm && cartCount > 0) {
            // Warte bis updateCartFromJSON vollständig fertig ist
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    const checkoutFormNow = document.getElementById('checkoutForm');
                    if (!checkoutFormNow) {
                        console.log('Lade Checkout-Formular für', cartCount, 'Produkte...');
                        this.loadCheckoutForm().catch(err => {
                            console.error('Checkout-Formular konnte nicht geladen werden:', err);
                        });
                    }
                });
            });
        }
    }
    
    async loadCheckoutForm() {
        // Lade nur das Checkout-Formular nach, ohne die gesamte Seite neu zu laden
        try {
            // Prüfe ob Checkout-Formular bereits existiert
            const existingCheckoutForm = document.getElementById('checkoutForm');
            if (existingCheckoutForm) {
                console.log('Checkout-Formular existiert bereits, überspringe Laden');
                return;
            }
            
            // Prüfe ob gerade ein Update läuft - warte bis es fertig ist
            const cartItemsContainer = document.getElementById('cartItems');
            if (cartItemsContainer && cartItemsContainer.getAttribute('data-updating') === 'true') {
                console.log('Warenkorb wird gerade aktualisiert, warte...');
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
            const cartCardBody = cartItemsContainer?.closest('.card-body');
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
                console.log('✓ Benutzer-Liste kopiert:', borrowerSelect.options.length, 'Optionen');
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
            console.log('✓ Checkout-Formular erfolgreich hinzugefügt');
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
        // Zeige Modal mit Set-Informationen
        const modal = document.getElementById('setScannedModal');
        if (!modal) {
            console.warn('Set-Modal nicht gefunden, verwende Alert als Fallback');
            let message = `Set "${result.set.name}" wurde gescannt.\n\n`;
            message += `${result.added_products.length} Produkt(e) wurden zum Warenkorb hinzugefügt:\n`;
            result.added_products.forEach(p => {
                message += `- ${p.name}${p.category ? ' (' + p.category + ')' : ''}\n`;
            });
            if (result.unavailable_products && result.unavailable_products.length > 0) {
                message += `\n${result.unavailable_products.length} Produkt(e) konnten nicht hinzugefügt werden (nicht verfügbar):\n`;
                result.unavailable_products.forEach(p => {
                    message += `- ${p.name}\n`;
                });
            }
            alert(message);
            return;
        }
        
        // Setze Set-Namen
        const setNameEl = document.getElementById('setScannedName');
        if (setNameEl) {
            setNameEl.textContent = result.set.name;
        }
        
        // Fülle Produkt-Liste
        const productsList = document.getElementById('setScannedProducts');
        if (productsList) {
            productsList.innerHTML = '';
            
            if (result.added_products && result.added_products.length > 0) {
                result.added_products.forEach(product => {
                    const listItem = document.createElement('li');
                    listItem.className = 'list-group-item d-flex justify-content-between align-items-center';
                    
                    const productInfo = document.createElement('div');
                    let productText = `<strong>${this.escapeHtml(product.name)}</strong>`;
                    if (product.category) {
                        productText += ` <span class="text-muted">(${this.escapeHtml(product.category)})</span>`;
                    }
                    // Zeige Menge wenn vorhanden und > 1
                    if (product.quantity && product.quantity > 1) {
                        productText += ` <span class="badge bg-info">x${product.quantity}</span>`;
                    }
                    productInfo.innerHTML = productText;
                    
                    const badge = document.createElement('span');
                    if (product.was_in_cart) {
                        badge.className = 'badge bg-info';
                        badge.innerHTML = `<i class="bi bi-info-circle"></i> Bereits im Warenkorb`;
                    } else if (product.added > 0) {
                        badge.className = 'badge bg-success';
                        badge.innerHTML = `<i class="bi bi-check-circle"></i> ${product.added} hinzugefügt`;
                    } else {
                        badge.className = 'badge bg-secondary';
                        badge.innerHTML = `<i class="bi bi-dash-circle"></i> Nicht verfügbar`;
                    }
                    
                    listItem.appendChild(productInfo);
                    listItem.appendChild(badge);
                    productsList.appendChild(listItem);
                });
            } else {
                const emptyItem = document.createElement('li');
                emptyItem.className = 'list-group-item text-muted';
                emptyItem.textContent = 'Keine Produkte hinzugefügt';
                productsList.appendChild(emptyItem);
            }
        }
        
        // Zeige nicht verfügbare Produkte
        const unavailableDiv = document.getElementById('setScannedUnavailable');
        const unavailableList = document.getElementById('setScannedUnavailableList');
        if (unavailableDiv && unavailableList) {
            if (result.unavailable_products && result.unavailable_products.length > 0) {
                unavailableList.innerHTML = '';
                result.unavailable_products.forEach(product => {
                    const listItem = document.createElement('li');
                    listItem.innerHTML = `<strong>${this.escapeHtml(product.name)}</strong> <span class="text-muted">(${product.status === 'borrowed' ? 'Ausgeliehen' : 'Fehlend'})</span>`;
                    unavailableList.appendChild(listItem);
                });
                unavailableDiv.style.display = 'block';
            } else {
                unavailableDiv.style.display = 'none';
            }
        }
        
        // Zeige Modal
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    async updateCartDisplay() {
        // Lade Warenkorb-Daten und aktualisiere die Anzeige
        // WICHTIG: Diese Funktion sollte NUR verwendet werden wenn der Warenkorb leer ist
        // oder wenn explizit eine vollständige Aktualisierung benötigt wird
        console.log('updateCartDisplay() aufgerufen');
        
        // Prüfe ob bereits Produkte im Warenkorb sind - wenn ja, überspringe
        const currentCartItems = document.getElementById('cartItems');
        if (currentCartItems) {
            const existingProducts = currentCartItems.querySelectorAll('.cart-item[data-product-id]');
            if (existingProducts.length > 0) {
                console.log('⚠ updateCartDisplay() übersprungen - Warenkorb enthält bereits Produkte');
                return;
            }
        }
        try {
            console.log('Lade Warenkorb-Daten...');
            const response = await fetch('/inventory/borrow-scanner');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const html = await response.text();
            console.log('HTML geladen, Länge:', html.length);
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');
            
            // Aktualisiere Warenkorb-Bereich
            const newCartItems = doc.querySelector('#cartItems');
            const newCartCount = doc.querySelector('#cartCount');
            const newCheckoutForm = doc.querySelector('#checkoutForm');
            
            console.log('Gefundene Elemente:', {
                newCartItems: !!newCartItems,
                newCartCount: !!newCartCount,
                newCheckoutForm: !!newCheckoutForm
            });
            
            // Aktualisiere cartItems NUR wenn keine Produkte vorhanden sind
            // Verhindere Überschreibung wenn bereits Produkte im Warenkorb sind
            const currentCartItems = document.getElementById('cartItems');
            if (newCartItems && currentCartItems) {
                // Prüfe ob bereits Produkte im Warenkorb sind
                const existingProducts = currentCartItems.querySelectorAll('.cart-item[data-product-id]');
                if (existingProducts.length > 0) {
                    console.log('⚠ Warenkorb enthält bereits Produkte, überspringe Überschreibung');
                    // Aktualisiere nur den Cart-Count, nicht die Items
                } else {
                    console.log('Aktualisiere cartItems...');
                    const oldContent = currentCartItems.innerHTML;
                    currentCartItems.innerHTML = newCartItems.innerHTML;
                    console.log('cartItems aktualisiert. Alt:', oldContent.substring(0, 50), 'Neu:', currentCartItems.innerHTML.substring(0, 50));
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
                    console.log('⚠ Cart-Count basiert auf vorhandenen Produkten:', existingProducts);
                } else if (newCartCount) {
                    console.log('Aktualisiere cartCount von', currentCartCount.textContent, 'zu', newCartCount.textContent);
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
            console.log('Gefundene remove-from-cart Buttons:', removeButtons.length);
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
            
            console.log('Warenkorb erfolgreich aktualisiert');
        } catch (error) {
            console.error('Fehler beim Aktualisieren des Warenkorbs:', error);
            console.error('Error Details:', error.message, error.stack);
            // Fallback: Seite neu laden
            window.location.reload();
        }
    }
    
    setupCheckoutForm() {
        const checkoutForm = document.getElementById('checkoutForm');
        if (checkoutForm) {
            const dateInput = document.getElementById('expected_return_date');
            if (dateInput) {
                const tomorrow = new Date();
                tomorrow.setDate(tomorrow.getDate() + 1);
                dateInput.min = tomorrow.toISOString().split('T')[0];
            }
            
            checkoutForm.addEventListener('submit', async function(e) {
                e.preventDefault();
                const formData = new FormData(checkoutForm);
                
                // Deaktiviere Button während des Requests
                const submitBtn = checkoutForm.querySelector('button[type="submit"]');
                const originalBtnText = submitBtn ? submitBtn.innerHTML : '';
                if (submitBtn) {
                    submitBtn.disabled = true;
                    submitBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Wird verarbeitet...';
                }
                
                try {
                    const response = await fetch(checkoutForm.action, {
                        method: 'POST',
                        body: formData
                    });
                    
                    // Die Checkout-Route gibt immer einen Redirect zurück (302)
                    // Daher ist response.ok möglicherweise false, aber die Ausleihe war erfolgreich
                    // Wir leiten zum Dashboard weiter - die Flash-Messages werden serverseitig gesetzt
                    window.location.href = '/inventory/';
                    
                } catch (error) {
                    console.error('Fehler beim Checkout:', error);
                    // Bei Netzwerkfehlern Button wieder aktivieren
                    if (submitBtn) {
                        submitBtn.disabled = false;
                        submitBtn.innerHTML = originalBtnText;
                    }
                    // Trotzdem weiterleiten - könnte erfolgreich gewesen sein
                    // Die Flash-Message wird serverseitig gesetzt
                    window.location.href = '/inventory/borrow-scanner';
                }
            });
        }
    }
    
    showSuccess(message) {
        const errorDiv = document.getElementById('scannerError');
        if (errorDiv) {
            errorDiv.className = 'alert alert-success mt-2';
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
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
                // Entferne nur das spezifische Produkt aus dem DOM, nicht den gesamten Warenkorb
                const cartItems = document.getElementById('cartItems');
                if (cartItems) {
                    const productItem = cartItems.querySelector(`[data-product-id="${productId}"]`);
                    if (productItem) {
                        productItem.remove();
                        console.log('✓ Produkt aus DOM entfernt');
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
                        cartItems.innerHTML = '<p class="text-muted text-center py-3">Keine Produkte hinzugefügt</p>';
                    }
                }
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
    
    hideError() {
        const errorDiv = document.getElementById('scannerError');
        if (errorDiv) {
            errorDiv.style.display = 'none';
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

