/** Ausleih-Scanner (Kamera / QR) — aus inventory.js ausgelagert. */
/* global inventoryNotify, inventoryConfirm, fetchInventoryApi */

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
            <button class="btn btn-sm mod-pill-btn mod-pill-btn--outline-danger remove-from-cart" type="button" data-product-id="${product.id}">
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
                    if (result.needs_confirm) {
                        const msg = result.confirm_message
                            || `Rückgabe von ${result.checkout_number || 'Checkout'} bestätigen?`;
                        const ok = typeof inventoryConfirm === 'function'
                            ? await inventoryConfirm(msg, { danger: true })
                            : window.confirm(msg);
                        if (!ok) {
                            this.setReturnScanResult('Rückgabe abgebrochen.', 'warning');
                            return Promise.resolve({ ...result, cancelled: true });
                        }
                        const confirmData = new FormData();
                        confirmData.append('action', 'confirm_return');
                        confirmData.append('qr_code', result.qr_ref || qrCode);
                        if (result.checkout_number) {
                            confirmData.append('checkout_number', result.checkout_number);
                        }
                        const confirmResp = await fetch('/inventory/borrow-scanner', {
                            method: 'POST',
                            body: confirmData,
                        });
                        let confirmed;
                        try {
                            confirmed = await confirmResp.json();
                        } catch (_err) {
                            throw new Error(`Server-Antwort konnte nicht geparst werden. Status: ${confirmResp.status}`);
                        }
                        if (!confirmResp.ok || confirmed.error) {
                            throw new Error(confirmed.error || `HTTP error! status: ${confirmResp.status}`);
                        }
                        result = confirmed;
                    }
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
