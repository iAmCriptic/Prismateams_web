// Inventory Management JavaScript

// Stock Manager - Verwaltet die Bestandsübersicht
class StockManager {
    constructor() {
        this.products = [];
        this.filteredProducts = [];
        this.categories = new Set();
        this.searchTimeout = null;
    }
    
    async init() {
        await this.loadProducts();
        this.setupEventListeners();
        this.updateCategories();
        this.renderProducts();
    }
    
    async loadProducts() {
        try {
            const response = await fetch('/inventory/api/stock');
            if (response.ok) {
                this.products = await response.json();
                this.filteredProducts = [...this.products];
                this.extractCategories();
            } else {
                console.error('Fehler beim Laden der Produkte');
                this.showError('Fehler beim Laden der Produkte');
            }
        } catch (error) {
            console.error('Fehler beim Laden der Produkte:', error);
            this.showError('Fehler beim Laden der Produkte');
        }
    }
    
    extractCategories() {
        this.categories.clear();
        this.products.forEach(p => {
            if (p.category) {
                this.categories.add(p.category);
            }
        });
        this.updateCategories();
    }
    
    updateCategories() {
        const categoryFilter = document.getElementById('categoryFilter');
        if (!categoryFilter) return;
        
        // Leere Optionen behalten, dann Kategorien hinzufügen
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
    
    setupEventListeners() {
        const searchInput = document.getElementById('searchInput');
        const categoryFilter = document.getElementById('categoryFilter');
        const statusFilter = document.getElementById('statusFilter');
        
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                clearTimeout(this.searchTimeout);
                this.searchTimeout = setTimeout(() => this.applyFilters(), 300);
            });
        }
        
        if (categoryFilter) {
            categoryFilter.addEventListener('change', () => this.applyFilters());
        }
        
        if (statusFilter) {
            statusFilter.addEventListener('change', () => this.applyFilters());
        }
    }
    
    applyFilters() {
        const search = document.getElementById('searchInput')?.value.toLowerCase() || '';
        const category = document.getElementById('categoryFilter')?.value || '';
        const status = document.getElementById('statusFilter')?.value || '';
        
        this.filteredProducts = this.products.filter(p => {
            const matchesSearch = !search || 
                p.name.toLowerCase().includes(search) ||
                (p.serial_number && p.serial_number.toLowerCase().includes(search));
            const matchesCategory = !category || p.category === category;
            const matchesStatus = !status || p.status === status;
            
            return matchesSearch && matchesCategory && matchesStatus;
        });
        
        this.renderProducts();
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
        
        return `
            <div class="card product-card" onclick="stockManager.showProductDetail(${product.id})">
                <div class="position-relative">
                    ${imageHtml}
                    <span class="badge product-status-badge">${statusBadge}</span>
                </div>
                <div class="card-body">
                    <h5 class="card-title">${product.name}</h5>
                    ${product.category ? `<p class="text-muted mb-1"><small>${product.category}</small></p>` : ''}
                    ${product.serial_number ? `<p class="text-muted mb-0"><small>SN: ${product.serial_number}</small></p>` : ''}
                    <div class="mt-2">
                        ${product.status === 'available' 
                            ? `<a href="/inventory/products/${product.id}/borrow" class="btn btn-sm btn-primary">Ausleihen</a>`
                            : ''}
                        <a href="/inventory/products/${product.id}/edit" class="btn btn-sm btn-outline-secondary">Bearbeiten</a>
                    </div>
                </div>
            </div>
        `;
    }
    
    async showProductDetail(productId) {
        const product = this.products.find(p => p.id === productId);
        if (!product) return;
        
        const modal = new bootstrap.Modal(document.getElementById('productDetailModal'));
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

