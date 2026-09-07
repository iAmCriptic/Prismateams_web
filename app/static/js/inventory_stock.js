/** Bestandsübersicht — Core (Load, Filter, Events). */
/* global fetchInventoryApi, inventoryNotify, inventoryConfirm */

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
        this.owners = []; // [{id, label, type, key}]
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
        this.productsOffset = 0;
        this.productsHasMore = false;
        this.productsLoadingMore = false;
        this.productsPageSize = 48;
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
        this.bindProductsLazyMore();
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
                this.owners = [];
                
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

                if (filterData.owners && Array.isArray(filterData.owners)) {
                    this.owners = filterData.owners.map((o) => ({
                        id: o.id,
                        label: o.label,
                        type: o.type,
                        key: o.id != null ? `user:${o.id}` : `label:${(o.label || '').trim()}`,
                    })).filter((o) => o.label);
                }
                
                // Aktualisiere alle Filter-Dropdowns
                this.updateCategories();
                this.updateConditions();
                this.updateLocations();
                this.updateLengths();
                this.updatePurchaseYears();
                this.updateOwners();
                
            } else {
                console.warn('Fehler beim Laden der Filter-Optionen, verwende nur Optionen aus geladenen Produkten');
            }
        } catch (error) {
            console.warn('Fehler beim Laden der Filter-Optionen:', error);
            // Nicht kritisch, verwende Optionen aus geladenen Produkten
        }
    }
    
    async loadProducts(options = {}) {
        const append = !!options.append;
        const offset = append ? (this.productsOffset || 0) : 0;
        if (append) {
            if (!this.productsHasMore || this.productsLoadingMore) return;
            this.productsLoadingMore = true;
        }
        try {
            const params = new URLSearchParams({
                sort_by: this.sortField || 'name',
                sort_dir: this.sortDirection === 'desc' ? 'desc' : 'asc',
                offset: String(offset),
                limit: String(this.productsPageSize || 48),
            });
            const search = (this.getFilterValue('searchInput') || '').trim();
            const category = this.getFilterValue('categoryFilter') || '';
            const status = this.getFilterValue('statusFilter') || '';
            if (search) params.set('search', search);
            if (category) params.set('category', category);
            if (status && status !== 'overdue' && status !== 'defective_repair') {
                params.set('status', status);
            }

            const response = await fetchInventoryApi(`/products?${params.toString()}`);
            
            if (!response.ok) {
                const errorText = await response.text();
                console.error('API-Fehler:', response.status, errorText);
                this.showError(`Fehler beim Laden der Produkte (Status: ${response.status})`);
                return;
            }
            
            const contentType = response.headers.get('content-type');
            let data;
            
            if (contentType && contentType.includes('application/json')) {
                data = await response.json();
            } else {
                const text = await response.text();
                console.error('Ungültige Antwort vom Server beim Laden der Produkte:', text);
                this.showError('Ungültige Antwort vom Server. Bitte laden Sie die Seite neu.');
                return;
            }

            let pageProducts = [];
            let hasMore = false;
            let nextOffset = offset;
            if (Array.isArray(data)) {
                pageProducts = data;
                hasMore = false;
                nextOffset = offset + pageProducts.length;
            } else if (data && Array.isArray(data.products)) {
                pageProducts = data.products;
                hasMore = !!data.has_more;
                nextOffset = Number.isFinite(data.next_offset) ? data.next_offset : (offset + pageProducts.length);
            } else {
                console.error('Ungültige API-Antwort:', data);
                this.showError('Ungültige Daten vom Server erhalten');
                return;
            }

            if (append) {
                const seen = new Set(this.products.map((p) => p.id));
                pageProducts.forEach((p) => {
                    if (!seen.has(p.id)) this.products.push(p);
                });
            } else {
                this.products = pageProducts;
            }
            this.productsHasMore = hasMore;
            this.productsOffset = nextOffset;
            this.updateProductsLazyMoreUi();
            
            this.extractCategories();
            
            this.updateCategories();
            this.updateConditions();
            this.updateLocations();
            this.updateLengths();
            this.updatePurchaseYears();
            this.updateTrashFooterCount();
            
            this.applyFilters();
        } catch (error) {
            console.error('Fehler beim Laden der Produkte:', error);
            this.showError(`Fehler beim Laden der Produkte: ${error.message}`);
        } finally {
            this.productsLoadingMore = false;
            this.updateProductsLazyMoreUi();
        }
    }

    updateProductsLazyMoreUi() {
        const wrap = document.getElementById('inventoryProductsLazyMore');
        if (!wrap) return;
        const show = !!this.productsHasMore;
        wrap.hidden = !show;
        const btn = wrap.querySelector('[data-inv-lazy-more-btn]');
        if (btn) btn.disabled = !!this.productsLoadingMore;
        const status = wrap.querySelector('[data-inv-lazy-more-status]');
        if (status) status.hidden = !this.productsLoadingMore;
    }

    bindProductsLazyMore() {
        const wrap = document.getElementById('inventoryProductsLazyMore');
        if (!wrap || wrap._invLazyBound) return;
        wrap._invLazyBound = true;
        const btn = wrap.querySelector('[data-inv-lazy-more-btn]');
        if (btn) {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                this.loadProducts({ append: true });
            });
        }
        const sentinel = wrap.querySelector('[data-inv-lazy-more-sentinel]');
        if (sentinel && 'IntersectionObserver' in window) {
            const io = new IntersectionObserver((entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) this.loadProducts({ append: true });
                });
            }, { rootMargin: '240px 0px' });
            io.observe(sentinel);
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

    updateOwners() {
        const selects = this.getFilterEls('ownerFilter');
        if (!selects.length) return;
        const current = this.getFilterValue('ownerFilter') || '';
        selects.forEach((select) => {
            const placeholder = select.options[0]?.textContent || 'Alle Eigentümer';
            select.innerHTML = '';
            const opt0 = document.createElement('option');
            opt0.value = '';
            opt0.textContent = placeholder;
            select.appendChild(opt0);
            (this.owners || []).forEach((o) => {
                const opt = document.createElement('option');
                opt.value = o.key;
                opt.textContent = o.label;
                select.appendChild(opt);
            });
            if (current && Array.from(select.options).some((o) => o.value === current)) {
                select.value = current;
            }
        });
    }
    
    setupEventListeners() {
        const filterKeys = [
            'searchInput', 'categoryFilter', 'statusFilter', 'favoritesFilter',
            'conditionFilter', 'locationFilter', 'lengthFilter', 'purchaseYearFilter',
            'serialPresenceFilter', 'dguvFilter', 'ownerFilter',
        ];

        filterKeys.forEach((key) => {
            this.getFilterEls(key).forEach((el) => {
                const eventName = key === 'searchInput' ? 'input' : 'change';
                el.addEventListener(eventName, () => {
                    this.getFilterEls(key).forEach((other) => {
                        if (other !== el) other.value = el.value;
                    });
                    const serverKeys = new Set(['searchInput', 'categoryFilter', 'statusFilter']);
                    if (serverKeys.has(key)) {
                        clearTimeout(this.searchTimeout);
                        const delay = key === 'searchInput' ? 300 : 0;
                        this.searchTimeout = setTimeout(() => this.loadProducts(), delay);
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
                this.loadProducts();
            });
        });

        this.getFilterEls('sortDirection').forEach((sortDirectionSelect) => {
            sortDirectionSelect.addEventListener('change', () => {
                const selectedValue = sortDirectionSelect.value === 'desc' ? 'desc' : 'asc';
                this.sortDirection = selectedValue;
                this.setFilterValue('sortDirection', this.sortDirection);
                localStorage.setItem('inventorySortDirection', this.sortDirection);
                this.loadProducts();
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
                this.loadProducts();
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
        const owner = this.getFilterValue('ownerFilter') || '';
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

            let matchesOwner = true;
            if (owner) {
                if (owner.startsWith('user:')) {
                    matchesOwner = Number(p.owner_user_id) === Number(owner.slice(5));
                } else if (owner.startsWith('label:')) {
                    const want = owner.slice(6).trim().toLowerCase();
                    const have = (p.owner_display || p.owner_label || '').trim().toLowerCase();
                    matchesOwner = have === want;
                }
            }
            
            return matchesSearch && matchesFolder && matchesCategory && matchesStatus &&
                   matchesFavorites && matchesCondition && matchesLocation && matchesLength &&
                   matchesPurchaseYear && matchesSerial && matchesDguv && matchesOwner;
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

        // Inventar-Nr. (eigene oder Portal PROD-{id})
        const invDisplay = product.inventory_number_display
            || product.external_barcode
            || (product.id != null ? `PROD-${product.id}` : '');
        if (invDisplay && String(invDisplay).toLowerCase().includes(searchLower)) return true;
        if (product.external_barcode && product.external_barcode.toLowerCase().includes(searchLower)) return true;
        
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

        // Eigentümer
        const owner = product.owner_display || product.owner_label || '';
        if (owner && String(owner).toLowerCase().includes(searchLower)) return true;
        
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
            'serialPresenceFilter', 'dguvFilter', 'ownerFilter',
        ].forEach((key) => this.setFilterValue(key, ''));
        this.loadProducts();
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
}

window.StockManager = StockManager;

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

window.markAsFound = markAsFound;
window.markAsMissing = markAsMissing;
window.markAsDefective = markAsDefective;
window.markAsInRepair = markAsInRepair;
window.markAsAvailable = markAsAvailable;
