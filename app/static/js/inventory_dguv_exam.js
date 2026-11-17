/**
 * DGUV V3 Prüfung — Scan → Stammdaten → Messwerte → OTP → signiertes PDF.
 */
/* global BorrowScannerManager, InventoryScanLookup, bootstrap, inventoryNotify */

class DguvExamManager extends BorrowScannerManager {
    constructor() {
        super();
        const cfg = window.INVENTORY_DGUV_EXAM || {};
        this.cfg = cfg;
        this.i18n = cfg.i18n || {};
        this.currentProduct = null;
        this.otpModal = null;
        this.rPeLimit = Number(cfg.rPeLimit) || 0.3;
        this.rIsoLimit = Number(cfg.rIsoLimit) || 1.0;
    }

    t(key, fallback = '') {
        return this.i18n[key] || fallback || key;
    }

    ensureModalOnBody(modalElement) {
        if (!modalElement) return;
        if (modalElement.parentElement !== document.body) {
            document.body.appendChild(modalElement);
        }
    }

    clearModalArtifacts() {
        document.querySelectorAll('.modal-backdrop').forEach((el) => el.remove());
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('overflow');
        document.body.style.removeProperty('padding-right');
    }

    csrfHeaders(extra = {}) {
        const headers = Object.assign({ Accept: 'application/json' }, extra);
        const meta = document.querySelector('meta[name="csrf-token"]');
        const token = (meta && meta.content)
            || (window.PrismateamsCsrf && typeof window.PrismateamsCsrf.getToken === 'function'
                ? window.PrismateamsCsrf.getToken()
                : '');
        if (token) {
            headers['X-CSRFToken'] = token;
            headers['X-CSRF-Token'] = token;
        }
        return headers;
    }

    notify(msg, category = 'info') {
        if (typeof inventoryNotify === 'function') {
            inventoryNotify(msg, category);
            return;
        }
        if (typeof window.showAppBanner === 'function') {
            window.showAppBanner(String(msg || ''), category === 'error' ? 'danger' : category);
            return;
        }
        window.alert(String(msg || ''));
    }

    showFormAlert(msg, type = 'danger') {
        const el = document.getElementById('dguvFormAlert');
        if (el) {
            el.className = `alert alert-${type} mb-3`;
            el.textContent = msg || '';
            el.classList.remove('d-none');
            el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        this.showFeedback(msg, type);
        this.notify(msg, type === 'danger' ? 'danger' : type);
    }

    clearFormAlert() {
        const el = document.getElementById('dguvFormAlert');
        if (el) {
            el.classList.add('d-none');
            el.textContent = '';
        }
    }

    escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    init() {
        const startBtn = document.getElementById('startScannerBtn');
        const stopBtn = document.getElementById('stopScannerBtn');
        const lookupBtn = document.getElementById('lookupBtn');
        const manualInput = document.getElementById('manualQrInput');
        const nextBtn = document.getElementById('nextScanBtn');
        const form = document.getElementById('dguvExamForm');
        const otpBtn = document.getElementById('dguvOtpConfirmBtn');
        const modalEl = document.getElementById('dguvOtpModal');

        if (modalEl && typeof bootstrap !== 'undefined' && bootstrap.Modal) {
            this.ensureModalOnBody(modalEl);
            this.otpModal = bootstrap.Modal.getOrCreateInstance(modalEl);
            modalEl.addEventListener('hidden.bs.modal', () => this.clearModalArtifacts());
        }

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
            nextBtn.addEventListener('click', () => this.clearForm());
        }
        if (form && !form.dataset.bound) {
            form.dataset.bound = '1';
            form.addEventListener('submit', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.prepareExam();
            });
        }
        if (otpBtn && !otpBtn.dataset.bound) {
            otpBtn.dataset.bound = '1';
            otpBtn.addEventListener('click', () => this.completeExam());
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

        const examDate = document.getElementById('examDate');
        const interval = document.getElementById('intervalMonths');
        if (examDate && !examDate.value) {
            examDate.value = new Date().toISOString().slice(0, 10);
        }
        const recompute = () => this.recomputeNextExam();
        if (examDate) examDate.addEventListener('change', recompute);
        if (interval) interval.addEventListener('change', recompute);
        recompute();

        const rPe = document.getElementById('rPe');
        const rIso = document.getElementById('rIso');
        if (rPe) rPe.addEventListener('input', () => this.updateLimitHints());
        if (rIso) rIso.addEventListener('input', () => this.updateLimitHints());

        const preset = document.getElementById('devicePreset');
        if (preset && !preset.dataset.bound) {
            preset.dataset.bound = '1';
            preset.addEventListener('change', () => {
                const opt = preset.selectedOptions[0];
                if (!opt || !opt.value) return;
                const nameEl = document.getElementById('deviceName');
                const serialEl = document.getElementById('deviceSerial');
                const calEl = document.getElementById('deviceCal');
                if (nameEl) nameEl.value = opt.dataset.name || '';
                if (serialEl) serialEl.value = opt.dataset.serial || '';
                if (calEl) calEl.value = opt.dataset.cal || '';
            });
        }
    }

    addMonths(isoDate, months) {
        const d = new Date(`${isoDate}T12:00:00`);
        if (Number.isNaN(d.getTime())) return '';
        const day = d.getDate();
        d.setMonth(d.getMonth() + Number(months));
        if (d.getDate() < day) d.setDate(0);
        return d.toISOString().slice(0, 10);
    }

    recomputeNextExam() {
        const examDate = document.getElementById('examDate');
        const interval = document.getElementById('intervalMonths');
        const next = document.getElementById('nextExamDate');
        if (!examDate || !interval || !next) return;
        next.value = this.addMonths(examDate.value, interval.value) || '';
    }

    updateLimitHints() {
        const rPe = document.getElementById('rPe');
        const rIso = document.getElementById('rIso');
        const rPeHint = document.getElementById('rPeHint');
        const rIsoHint = document.getElementById('rIsoHint');
        if (rPe && rPeHint && rPe.value !== '') {
            const v = parseFloat(rPe.value);
            const ok = !Number.isNaN(v) && v <= this.rPeLimit;
            rPeHint.textContent = ok ? this.t('limit_ok') : this.t('limit_fail');
            rPeHint.classList.toggle('text-success', ok);
            rPeHint.classList.toggle('text-danger', !ok);
        }
        if (rIso && rIsoHint && rIso.value !== '') {
            const v = parseFloat(rIso.value);
            const ok = !Number.isNaN(v) && v >= this.rIsoLimit;
            rIsoHint.textContent = ok ? this.t('limit_ok') : this.t('limit_fail');
            rIsoHint.classList.toggle('text-success', ok);
            rIsoHint.classList.toggle('text-danger', !ok);
        }
    }

    async addFromInput() {
        const input = document.getElementById('manualQrInput');
        const code = (input && input.value || '').trim();
        if (!code) return;
        await this.lookupProduct(code);
        if (input) input.select();
    }

    async addToCart(qrCode) {
        return this.lookupProduct(qrCode);
    }

    async lookupProduct(code) {
        const url = this.cfg.lookupUrl || '/inventory/api/dguv-exam/product';
        try {
            const res = await fetch(url, {
                method: 'POST',
                credentials: 'same-origin',
                headers: this.csrfHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ code }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.ok) {
                this.showFormAlert(data.error || data.detail || this.t('err_lookup'), 'danger');
                return;
            }
            this.clearFormAlert();
            this.showProduct(data.product);
        } catch (err) {
            this.showFormAlert(this.t('err_lookup'), 'danger');
        }
    }

    showFeedback(msg, type) {
        const el = document.getElementById('scannerFeedback');
        if (!el) return;
        el.className = `alert alert-${type || 'info'} mt-2`;
        el.textContent = msg;
        el.classList.remove('d-none');
    }

    clearForm() {
        this.currentProduct = null;
        const empty = document.getElementById('dguvExamEmpty');
        const wrap = document.getElementById('dguvExamFormWrap');
        const nextBtn = document.getElementById('nextScanBtn');
        if (empty) empty.classList.remove('d-none');
        if (wrap) wrap.classList.add('d-none');
        if (nextBtn) nextBtn.classList.add('d-none');
        const form = document.getElementById('dguvExamForm');
        if (form) form.reset();
        const examDate = document.getElementById('examDate');
        if (examDate) examDate.value = new Date().toISOString().slice(0, 10);
        this.recomputeNextExam();
        this.clearFormAlert();
    }

    showProduct(product) {
        this.currentProduct = product;
        const empty = document.getElementById('dguvExamEmpty');
        const wrap = document.getElementById('dguvExamFormWrap');
        const nextBtn = document.getElementById('nextScanBtn');
        const meta = document.getElementById('dguvProductMeta');
        const pid = document.getElementById('dguvProductId');
        if (empty) empty.classList.add('d-none');
        if (wrap) wrap.classList.remove('d-none');
        if (nextBtn) nextBtn.classList.remove('d-none');
        if (pid) pid.value = product.id;

        const rows = [
            [this.t('meta_inv'), product.inventory_number_display || `PROD-${product.id}`],
            [this.t('meta_serial'), product.serial_number || '—'],
            [this.t('meta_owner'), product.owner_display || '—'],
            [this.t('meta_location'), product.location || '—'],
            [this.t('meta_length'), product.length || '—'],
            [this.t('meta_folder'), product.folder_name || '—'],
            [this.t('meta_dguv_last'), product.dguv_last_check || '—'],
            [this.t('meta_dguv_interval'), product.dguv_interval_months != null ? `${product.dguv_interval_months}` : '—'],
            [this.t('meta_dguv_next'), product.dguv_next_check || '—'],
        ];
        if (meta) {
            meta.innerHTML = `
              <div class="dguv-product-meta">
                <strong class="d-block mb-2">${this.escapeHtml(product.name || '')}</strong>
                <dl class="row mb-0 small">
                  ${rows.map(([k, v]) => `
                    <dt class="col-5 text-muted">${this.escapeHtml(k)}</dt>
                    <dd class="col-7">${this.escapeHtml(v)}</dd>
                  `).join('')}
                </dl>
              </div>`;
        }

        const interval = document.getElementById('intervalMonths');
        if (interval && product.dguv_interval_months) {
            const opt = Array.from(interval.options).find((o) => o.value === String(product.dguv_interval_months));
            if (opt) interval.value = opt.value;
            else {
                const custom = document.createElement('option');
                custom.value = String(product.dguv_interval_months);
                custom.textContent = String(product.dguv_interval_months);
                custom.selected = true;
                interval.appendChild(custom);
            }
        }
        this.recomputeNextExam();
        this.stopScanner();
    }

    collectPayload() {
        const productId = document.getElementById('dguvProductId')?.value;
        return {
            product_id: productId ? Number(productId) : null,
            examiner_email: (document.getElementById('examinerEmail')?.value || '').trim(),
            device_name: (document.getElementById('deviceName')?.value || '').trim(),
            device_serial: (document.getElementById('deviceSerial')?.value || '').trim(),
            device_calibration_date: document.getElementById('deviceCal')?.value || null,
            visual_ok: document.getElementById('visualOk')?.value,
            function_ok: document.getElementById('functionOk')?.value,
            r_pe_ohm: document.getElementById('rPe')?.value,
            r_iso_mohm: document.getElementById('rIso')?.value,
            i_pe_ma: document.getElementById('iPe')?.value,
            i_touch_ma: document.getElementById('iTouch')?.value,
            r_pe_limit: this.rPeLimit,
            r_iso_limit: this.rIsoLimit,
            overall_result: document.getElementById('overallResult')?.value,
            interval_months: document.getElementById('intervalMonths')?.value,
            exam_date: document.getElementById('examDate')?.value,
        };
    }

    validateClient(payload) {
        if (!payload.product_id) return this.t('err_lookup', 'Produkt fehlt.');
        if (!payload.examiner_email) return this.t('err_prepare', 'E-Mail fehlt.');
        if (!payload.device_name) return this.i18n.err_device || 'Prüfgerät ist Pflicht.';
        if (payload.visual_ok !== 'true' && payload.visual_ok !== 'false') {
            return this.i18n.err_visual || 'Sichtprüfung ist Pflicht.';
        }
        if (payload.function_ok !== 'true' && payload.function_ok !== 'false') {
            return this.i18n.err_function || 'Funktionsprüfung ist Pflicht.';
        }
        if (!payload.overall_result) return this.i18n.err_result || 'Gesamtergebnis ist Pflicht.';
        if (!payload.interval_months) return this.i18n.err_interval || 'Intervall ist Pflicht.';
        return null;
    }

    /** True when a fresh email OTP must be entered (modal). */
    otpIsRequired(data) {
        if (!data || typeof data !== 'object') return true;
        const v = data.otp_required;
        if (v === false || v === 0 || v === 'false' || v === '0') return false;
        // Explicit true / missing → require OTP (safe default)
        return v !== undefined && v !== null ? !!v : true;
    }

    hideOtpModal() {
        if (this.otpModal) {
            try { this.otpModal.hide(); } catch (_) { /* ignore */ }
        }
        this.clearModalArtifacts();
    }

    openOtpUi(data) {
        // Never show the modal when no code entry is needed
        if (!this.otpIsRequired(data)) {
            this.hideOtpModal();
            return this.completeExam({ skipOtp: true });
        }

        const modalEl = document.getElementById('dguvOtpModal');
        this.ensureModalOnBody(modalEl);
        if (modalEl && typeof bootstrap !== 'undefined' && bootstrap.Modal && !this.otpModal) {
            this.otpModal = bootstrap.Modal.getOrCreateInstance(modalEl);
        }

        const hint = document.getElementById('dguvOtpHint');
        if (hint) {
            if (data.hint) {
                hint.textContent = data.hint + (data.dev_otp ? ` (Dev-OTP: ${data.dev_otp})` : '');
            } else if (data.examiner_email) {
                hint.textContent = data.examiner_email;
            }
        }
        const otpInput = document.getElementById('dguvOtpInput');
        const otpErr = document.getElementById('dguvOtpError');
        if (otpInput) otpInput.value = data.dev_otp || '';
        if (otpErr) {
            otpErr.style.display = 'none';
            otpErr.textContent = '';
        }
        if (this.otpModal) {
            this.otpModal.show();
            return;
        }
        // Fallback without Bootstrap Modal
        const code = window.prompt(
            (hint && hint.textContent) || 'OTP-Code eingeben',
            data.dev_otp || ''
        );
        if (code != null) {
            if (otpInput) otpInput.value = String(code).trim();
            this.completeExam();
        }
    }

    async prepareExam() {
        this.clearFormAlert();
        if (!this.cfg.signingReady) {
            this.showFormAlert(this.t('err_prepare'), 'warning');
            return;
        }
        const payload = this.collectPayload();
        const clientErr = this.validateClient(payload);
        if (clientErr) {
            this.showFormAlert(clientErr, 'warning');
            return;
        }
        const btn = document.getElementById('dguvSubmitBtn');
        if (btn) btn.disabled = true;
        try {
            const res = await fetch(this.cfg.prepareUrl || '/inventory/api/dguv-exam/prepare', {
                method: 'POST',
                credentials: 'same-origin',
                headers: this.csrfHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.ok) {
                const msg = data.error || data.detail || this.t('err_prepare');
                this.showFormAlert(msg, 'danger');
                return;
            }
            this.clearFormAlert();
            // Skip OTP modal entirely when monthly window is still active
            if (!this.otpIsRequired(data)) {
                this.hideOtpModal();
                if (data.hint) this.notify(data.hint, 'info');
                await this.completeExam({ skipOtp: true });
                return;
            }
            this.openOtpUi(data);
        } catch (err) {
            console.error(err);
            this.showFormAlert(this.t('err_prepare'), 'danger');
        } finally {
            if (btn) btn.disabled = !this.cfg.signingReady;
        }
    }

    async completeExam(opts = {}) {
        const skipOtp = !!opts.skipOtp;
        const otp = skipOtp ? '' : (document.getElementById('dguvOtpInput')?.value || '').trim();
        const otpErr = document.getElementById('dguvOtpError');
        const btn = document.getElementById('dguvOtpConfirmBtn');
        if (btn) btn.disabled = true;
        try {
            const res = await fetch(this.cfg.completeUrl || '/inventory/api/dguv-exam/complete', {
                method: 'POST',
                credentials: 'same-origin',
                headers: this.csrfHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ otp }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.ok) {
                const msg = data.error || data.detail || this.t('err_complete');
                if (otpErr && !skipOtp) {
                    otpErr.style.display = 'block';
                    otpErr.textContent = msg;
                }
                this.notify(msg, 'danger');
                if (skipOtp) this.showFormAlert(msg, 'danger');
                return;
            }
            this.hideOtpModal();
            this.showFormAlert(this.t('success'), 'success');
            if (data.pdf_url) {
                window.open(data.pdf_url, '_blank');
            }
            this.clearForm();
        } catch (err) {
            console.error(err);
            const msg = this.t('err_complete');
            if (otpErr && !skipOtp) {
                otpErr.style.display = 'block';
                otpErr.textContent = msg;
            }
            this.notify(msg, 'danger');
        } finally {
            if (btn) btn.disabled = false;
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const mgr = new DguvExamManager();
    mgr.init();
    window.dguvExamManager = mgr;
});
