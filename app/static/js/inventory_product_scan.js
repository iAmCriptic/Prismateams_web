/**
 * Scan & Prüfung — Kamera/Suche → Produktkarte mit Inline-Edit und Docs.
 * Nutzt BorrowScannerManager für Kamera (jsQR + ZXing).
 */
/* global BorrowScannerManager, InventoryScanLookup, inventoryNotify */

class ProductScanManager extends BorrowScannerManager {
    constructor() {
        super();
        this.currentProduct = null;
        this.lastLookupCode = null;
        this.lookupCooldownUntil = 0;
        this.i18n = window.INVENTORY_PRODUCT_SCAN_I18N || {};
        this.manuals = Array.isArray(window.INVENTORY_MANUALS) ? window.INVENTORY_MANUALS : [];
    }

    t(key, fallback = '') {
        return this.i18n[key] || fallback || key;
    }

    init() {
        const startBtn = document.getElementById('startScannerBtn');
        const stopBtn = document.getElementById('stopScannerBtn');
        const lookupBtn = document.getElementById('lookupBtn');
        const manualInput = document.getElementById('manualQrInput');
        const nextBtn = document.getElementById('nextScanBtn');

        if (startBtn && !startBtn.dataset.scannerBound) {
            startBtn.dataset.scannerBound = '1';
            startBtn.addEventListener('click', () => this.startScanner());
        }
        if (stopBtn && !stopBtn.dataset.scannerBound) {
            stopBtn.dataset.scannerBound = '1';
            stopBtn.addEventListener('click', () => this.stopScanner());
        }
        if (lookupBtn && manualInput && !lookupBtn.dataset.bound) {
            lookupBtn.dataset.bound = '1';
            manualInput.dataset.bound = '1';
            lookupBtn.addEventListener('click', () => this.addFromInput());
            manualInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.addFromInput();
                }
            });
        }
        if (nextBtn && !nextBtn.dataset.bound) {
            nextBtn.dataset.bound = '1';
            nextBtn.addEventListener('click', () => this.clearCard());
        }

        const suggestEl = document.getElementById('productSuggest');
        const searchInput = document.getElementById('productSearchInput');
        if (searchInput && suggestEl && !searchInput.dataset.lookupBound) {
            searchInput.dataset.lookupBound = '1';
            this.productLookup = new InventoryScanLookup({
                input: searchInput,
                dropdown: suggestEl,
                includeSets: false,
                onPick: (code) => {
                    this.lookupProduct(code).then(() => {
                        searchInput.value = '';
                    }).catch(() => {});
                },
            });
        }
    }

    async addFromInput() {
        const input = document.getElementById('manualQrInput');
        const code = (input && input.value || '').trim();
        if (!code) return;
        await this.lookupProduct(code);
        if (input) input.select();
    }

    /** Override: Scan öffnet Produktkarte statt Warenkorb */
    async addToCart(qrCode) {
        return this.lookupProduct(qrCode);
    }

    async lookupProduct(code) {
        const normalized = String(code || '').trim();
        if (!normalized) return;

        const now = Date.now();
        if (normalized === this.lastLookupCode && now < this.lookupCooldownUntil) {
            return;
        }
        this.lastLookupCode = normalized;
        this.lookupCooldownUntil = now + 1800;

        try {
            const response = await fetch('/inventory/api/product-scan', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Accept: 'application/json',
                },
                credentials: 'same-origin',
                body: JSON.stringify({ code: normalized }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.ok) {
                const msg = data.error || this.t('err_lookup');
                if (typeof this.showError === 'function') this.showError(msg);
                else inventoryNotify(msg, 'danger');
                return;
            }
            this.showProduct(data.product);
            const manual = document.getElementById('manualQrInput');
            if (manual) {
                manual.value = '';
                manual.focus();
            }
        } catch (err) {
            console.error(err);
            inventoryNotify(this.t('err_lookup'), 'danger');
        }
    }

    clearCard() {
        this.currentProduct = null;
        const card = document.getElementById('productScanCard');
        const empty = document.getElementById('productScanEmpty');
        const nextBtn = document.getElementById('nextScanBtn');
        if (card) {
            card.classList.add('d-none');
            card.innerHTML = '';
        }
        if (empty) empty.classList.remove('d-none');
        if (nextBtn) nextBtn.classList.add('d-none');
        const manual = document.getElementById('manualQrInput');
        if (manual) manual.focus();
    }

    escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    formatDateDe(iso) {
        if (!iso) return '—';
        const raw = String(iso).slice(0, 10);
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

    isDguvDue(product) {
        if (!product || !product.dguv_next_check) return false;
        return String(product.dguv_next_check).slice(0, 10) <= new Date().toISOString().slice(0, 10);
    }

    showProduct(product) {
        this.currentProduct = product;
        const card = document.getElementById('productScanCard');
        const empty = document.getElementById('productScanEmpty');
        const nextBtn = document.getElementById('nextScanBtn');
        if (!card) return;
        if (empty) empty.classList.add('d-none');
        if (nextBtn) nextBtn.classList.remove('d-none');
        card.classList.remove('d-none');

        const hasDguv = !!(product.dguv_last_check || product.dguv_next_check || product.dguv_interval_months);
        const dguvDue = this.isDguvDue(product);
        const cond = product.condition || '';
        const status = product.status || 'available';
        const interval = product.dguv_interval_months != null ? product.dguv_interval_months : 12;
        const last = product.dguv_last_check ? String(product.dguv_last_check).slice(0, 10) : '';
        const nextDisplay = this.formatDateDe(product.dguv_next_check);

        const manualsOptions = this.manuals.map((m) =>
            `<option value="${m.id}">${this.escapeHtml(m.title || '')}</option>`
        ).join('');

        card.innerHTML = `
            <div class="inventory-product-scan-card inv-fade-up">
                <div class="d-flex flex-wrap align-items-start justify-content-between gap-2 mb-3">
                    <div class="min-width-0">
                        <h3 class="h5 mb-1 text-truncate">${this.escapeHtml(product.name)}</h3>
                        <div class="d-flex flex-wrap gap-2 align-items-center">
                            <span class="badge rounded-pill bg-secondary">${this.escapeHtml(status)}</span>
                            ${product.external_barcode ? `<span class="text-muted small"><i class="bi bi-upc"></i> ${this.escapeHtml(product.external_barcode)}</span>` : ''}
                            ${product.serial_number ? `<span class="text-muted small"><i class="bi bi-hash"></i> ${this.escapeHtml(product.serial_number)}</span>` : ''}
                            ${dguvDue ? '<span class="badge rounded-pill bg-danger">DGUV fällig</span>' : ''}
                        </div>
                    </div>
                    <div class="d-flex gap-2 flex-wrap">
                        <a href="/inventory/products/${product.id}/edit" class="btn btn-sm inventory-pill-btn inventory-pill-btn--outline">${this.t('full_edit')}</a>
                        <a href="/inventory/products/${product.id}/documents" class="btn btn-sm inventory-pill-btn inventory-pill-btn--outline">${this.t('all_docs')}</a>
                    </div>
                </div>

                <form id="productScanEditForm" class="inventory-form inventory-product-scan-form">
                    <div class="inventory-form-fields inventory-form-fields--3">
                        <div class="inventory-form-field">
                            <label class="form-label" for="psLocation">${this.t('location')}</label>
                            <input type="text" class="form-control" id="psLocation" value="${this.escapeHtml(product.location || '')}">
                        </div>
                        <div class="inventory-form-field">
                            <label class="form-label" for="psCondition">${this.t('condition')}</label>
                            <select class="form-select" id="psCondition">
                                <option value="">—</option>
                                <option value="Neu" ${cond === 'Neu' ? 'selected' : ''}>${this.t('condition_new')}</option>
                                <option value="Gut" ${cond === 'Gut' ? 'selected' : ''}>${this.t('condition_good')}</option>
                                <option value="Gebraucht" ${cond === 'Gebraucht' ? 'selected' : ''}>${this.t('condition_used')}</option>
                                <option value="Beschädigt" ${cond === 'Beschädigt' ? 'selected' : ''}>${this.t('condition_damaged')}</option>
                            </select>
                        </div>
                        <div class="inventory-form-field">
                            <label class="form-label" for="psStatus">${this.t('status')}</label>
                            <select class="form-select" id="psStatus">
                                <option value="available" ${status === 'available' ? 'selected' : ''}>${this.t('status_available')}</option>
                                <option value="borrowed" ${status === 'borrowed' ? 'selected' : ''}>${this.t('status_borrowed')}</option>
                                <option value="missing" ${status === 'missing' ? 'selected' : ''}>${this.t('status_missing')}</option>
                                <option value="defective" ${status === 'defective' ? 'selected' : ''}>${this.t('status_defective')}</option>
                                <option value="in_repair" ${status === 'in_repair' ? 'selected' : ''}>${this.t('status_in_repair')}</option>
                                <option value="retired" ${status === 'retired' ? 'selected' : ''}>${this.t('status_retired')}</option>
                            </select>
                        </div>
                    </div>

                    <div class="inventory-form-card mt-3 mb-0">
                        <div class="inventory-form-card-head inventory-form-card-head--split">
                            <h4 class="inventory-form-section-title mb-0"><i class="bi bi-shield-check"></i> DGUV</h4>
                            <div class="form-check form-switch mb-0">
                                <input class="form-check-input" type="checkbox" id="psDguvRequired" ${hasDguv ? 'checked' : ''}>
                                <label class="form-check-label" for="psDguvRequired">${this.t('dguv_required')}</label>
                            </div>
                        </div>
                        <div id="psDguvFields" class="inventory-form-fields inventory-form-fields--3 ${hasDguv ? '' : 'd-none'}">
                            <div class="inventory-form-field">
                                <label class="form-label" for="psDguvLast">${this.t('dguv_last')}</label>
                                <input type="date" class="form-control" id="psDguvLast" value="${this.escapeHtml(last)}">
                            </div>
                            <div class="inventory-form-field">
                                <label class="form-label" for="psDguvInterval">${this.t('dguv_interval')}</label>
                                <input type="number" min="1" class="form-control" id="psDguvInterval" value="${interval}">
                            </div>
                            <div class="inventory-form-field">
                                <label class="form-label" for="psDguvNext">${this.t('dguv_next')}</label>
                                <input type="text" class="form-control" id="psDguvNext" readonly value="${nextDisplay}" placeholder="—">
                            </div>
                        </div>
                    </div>

                    <div class="inventory-form-actions mt-3">
                        <button type="submit" class="btn inventory-pill-btn inventory-pill-btn--primary">
                            <i class="bi bi-check-circle"></i> ${this.t('save')}
                        </button>
                    </div>
                </form>

                <section class="inventory-form-card mt-3 mb-0">
                    <div class="inventory-form-card-head d-flex justify-content-between align-items-center flex-wrap gap-2">
                        <h4 class="inventory-form-section-title mb-0"><i class="bi bi-file-earmark"></i> ${this.t('docs_title')}</h4>
                    </div>
                    <div id="psDocsList" class="small text-muted mb-3">${this.t('docs_empty')}</div>
                    <div class="inventory-form-fields inventory-form-fields--2 align-items-end">
                        <div class="inventory-form-field">
                            <label class="form-label" for="psDocFile">${this.t('docs_upload')}</label>
                            <input type="file" class="form-control" id="psDocFile"
                                   accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx,application/pdf,image/png,image/jpeg">
                        </div>
                        <div class="inventory-form-field">
                            <label class="form-label" for="psDocType">${this.t('docs_type')}</label>
                            <select class="form-select" id="psDocType">
                                <option value="dguv">${this.t('type_dguv')}</option>
                                <option value="handbook">${this.t('type_handbook')}</option>
                                <option value="datasheet">${this.t('type_datasheet')}</option>
                                <option value="invoice">${this.t('type_invoice')}</option>
                                <option value="warranty">${this.t('type_warranty')}</option>
                                <option value="other">${this.t('type_other')}</option>
                            </select>
                        </div>
                    </div>
                    <div class="mt-2">
                        <button type="button" class="btn btn-sm inventory-pill-btn inventory-pill-btn--outline" id="psDocUploadBtn">
                            <i class="bi bi-upload"></i> ${this.t('docs_upload')}
                        </button>
                    </div>
                    ${this.manuals.length ? `
                    <div class="mt-3 inventory-form-fields inventory-form-fields--2 align-items-end">
                        <div class="inventory-form-field">
                            <label class="form-label" for="psManualSelect">${this.t('link_manual')}</label>
                            <select class="form-select" id="psManualSelect">
                                <option value="">—</option>
                                ${manualsOptions}
                            </select>
                        </div>
                        <div class="inventory-form-field">
                            <button type="button" class="btn btn-sm inventory-pill-btn inventory-pill-btn--outline" id="psManualLinkBtn">
                                <i class="bi bi-link-45deg"></i> ${this.t('link')}
                            </button>
                        </div>
                    </div>` : ''}
                </section>
            </div>
        `;

        this.bindCardEvents();
        this.refreshDguvNext();
        this.loadDocuments(product.id);
        if (window.InventoryPillSelect) {
            window.InventoryPillSelect.enhanceAll(card);
        }
    }

    bindCardEvents() {
        const form = document.getElementById('productScanEditForm');
        if (form) {
            form.addEventListener('submit', (e) => {
                e.preventDefault();
                this.saveProduct();
            });
        }
        const dguvToggle = document.getElementById('psDguvRequired');
        const wrap = document.getElementById('psDguvFields');
        if (dguvToggle && wrap) {
            dguvToggle.addEventListener('change', () => {
                wrap.classList.toggle('d-none', !dguvToggle.checked);
                this.refreshDguvNext();
            });
        }
        ['psDguvLast', 'psDguvInterval'].forEach((id) => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('change', () => this.refreshDguvNext());
                el.addEventListener('input', () => this.refreshDguvNext());
            }
        });
        const uploadBtn = document.getElementById('psDocUploadBtn');
        if (uploadBtn) uploadBtn.addEventListener('click', () => this.uploadDocument());
        const linkBtn = document.getElementById('psManualLinkBtn');
        if (linkBtn) linkBtn.addEventListener('click', () => this.linkManual());
    }

    refreshDguvNext() {
        const required = document.getElementById('psDguvRequired')?.checked;
        const nextEl = document.getElementById('psDguvNext');
        if (!nextEl) return;
        if (!required) {
            nextEl.value = '—';
            return;
        }
        const last = document.getElementById('psDguvLast')?.value;
        const interval = parseInt(document.getElementById('psDguvInterval')?.value || '12', 10);
        if (!last) {
            nextEl.value = '—';
            return;
        }
        const iso = this.computeDguvNextIso(last, interval || 12);
        nextEl.value = iso ? this.formatDateDe(iso) : '—';
    }

    async saveProduct() {
        if (!this.currentProduct) return;
        const id = this.currentProduct.id;
        const dguvRequired = !!document.getElementById('psDguvRequired')?.checked;
        const payload = {
            location: document.getElementById('psLocation')?.value || '',
            condition: document.getElementById('psCondition')?.value || '',
            status: document.getElementById('psStatus')?.value || 'available',
            dguv_required: dguvRequired ? 1 : 0,
        };
        if (dguvRequired) {
            payload.dguv_last_check = document.getElementById('psDguvLast')?.value || null;
            payload.dguv_interval_months = parseInt(document.getElementById('psDguvInterval')?.value || '12', 10);
        } else {
            payload.dguv_clear = true;
        }

        try {
            const response = await fetch(`/inventory/api/products/${id}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    Accept: 'application/json',
                },
                credentials: 'same-origin',
                body: JSON.stringify(payload),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || this.t('err_save'));
            }
            inventoryNotify(data.message || this.t('saved'), 'success');
            if (data.product) {
                this.showProduct(data.product);
            }
        } catch (err) {
            inventoryNotify(err.message || this.t('err_save'), 'danger');
        }
    }

    async loadDocuments(productId) {
        const listEl = document.getElementById('psDocsList');
        if (!listEl) return;
        try {
            const response = await fetch(`/inventory/api/products/${productId}/documents`, {
                headers: { Accept: 'application/json' },
                credentials: 'same-origin',
            });
            if (!response.ok) throw new Error('load_failed');
            const docs = await response.json();
            const recent = (Array.isArray(docs) ? docs : []).slice(0, 5);
            if (!recent.length) {
                listEl.innerHTML = `<p class="mb-0 text-muted">${this.t('docs_empty')}</p>`;
                return;
            }
            listEl.innerHTML = `<ul class="list-unstyled mb-0">${recent.map((doc) => {
                const name = this.escapeHtml(doc.display_name || doc.file_name || doc.manual_title || 'Dokument');
                const href = doc.download_url || doc.manual_view_url || `/inventory/products/${productId}/documents`;
                return `<li class="d-flex justify-content-between gap-2 py-1 border-bottom border-secondary-subtle">
                    <a href="${this.escapeHtml(href)}" class="text-decoration-none text-truncate" target="_blank" rel="noopener">
                        <i class="bi bi-file-earmark me-1"></i>${name}
                    </a>
                    <span class="text-muted">${this.escapeHtml(doc.file_type || '')}</span>
                </li>`;
            }).join('')}</ul>`;
        } catch (e) {
            listEl.innerHTML = `<p class="mb-0 text-danger">${this.t('err_upload')}</p>`;
        }
    }

    async uploadDocument() {
        if (!this.currentProduct) return;
        const fileInput = document.getElementById('psDocFile');
        const typeSelect = document.getElementById('psDocType');
        if (!fileInput || !fileInput.files || !fileInput.files[0]) {
            inventoryNotify(this.t('err_upload'), 'warning');
            return;
        }
        const body = new FormData();
        body.append('file', fileInput.files[0]);
        body.append('file_type', typeSelect?.value || 'other');
        try {
            const response = await fetch(`/inventory/products/${this.currentProduct.id}/documents/upload`, {
                method: 'POST',
                body,
                headers: {
                    Accept: 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'same-origin',
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.message || this.t('err_upload'));
            }
            inventoryNotify(data.message || this.t('uploaded'), 'success');
            fileInput.value = '';
            await this.loadDocuments(this.currentProduct.id);
        } catch (err) {
            inventoryNotify(err.message || this.t('err_upload'), 'danger');
        }
    }

    async linkManual() {
        if (!this.currentProduct) return;
        const select = document.getElementById('psManualSelect');
        const manualId = select ? parseInt(select.value, 10) : NaN;
        if (!manualId) {
            inventoryNotify(this.t('link_manual'), 'warning');
            return;
        }
        try {
            const body = new FormData();
            body.append('manual_id', String(manualId));
            body.append('file_type', 'handbook');
            const response = await fetch(`/inventory/products/${this.currentProduct.id}/documents/link-manual`, {
                method: 'POST',
                body,
                headers: {
                    Accept: 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'same-origin',
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.ok === false) {
                throw new Error(data.message || this.t('err_upload'));
            }
            inventoryNotify(data.message || this.t('uploaded'), data.category === 'info' ? 'info' : 'success');
            if (select) select.value = '';
            await this.loadDocuments(this.currentProduct.id);
        } catch (err) {
            inventoryNotify(err.message || this.t('err_upload'), 'danger');
        }
    }
}

window.ProductScanManager = ProductScanManager;
