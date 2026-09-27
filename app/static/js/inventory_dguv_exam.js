/**
 * DGUV V3 Prüfung — Scan → Stammdaten → Messwerte → OTP → signiertes PDF.
 */
/* global BorrowScannerManager, InventoryScanLookup, bootstrap */

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

        if (modalEl && typeof bootstrap !== 'undefined') {
            this.otpModal = bootstrap.Modal.getOrCreateInstance(modalEl);
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
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({ code }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.ok) {
                this.showFeedback(data.error || this.t('err_lookup'), 'danger');
                return;
            }
            this.showProduct(data.product);
        } catch (err) {
            this.showFeedback(this.t('err_lookup'), 'danger');
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
            examiner_email: document.getElementById('examinerEmail')?.value || '',
            device_name: document.getElementById('deviceName')?.value || '',
            device_serial: document.getElementById('deviceSerial')?.value || '',
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

    async prepareExam() {
        if (!this.cfg.signingReady) {
            this.showFeedback(this.t('err_prepare'), 'warning');
            return;
        }
        const payload = this.collectPayload();
        const btn = document.getElementById('dguvSubmitBtn');
        if (btn) btn.disabled = true;
        try {
            const res = await fetch(this.cfg.prepareUrl || '/inventory/api/dguv-exam/prepare', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.ok) {
                this.showFeedback(data.error || this.t('err_prepare'), 'danger');
                return;
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
            if (otpInput) {
                otpInput.value = data.dev_otp || '';
            }
            if (otpErr) {
                otpErr.style.display = 'none';
                otpErr.textContent = '';
            }
            if (this.otpModal) this.otpModal.show();
        } catch (err) {
            this.showFeedback(this.t('err_prepare'), 'danger');
        } finally {
            if (btn) btn.disabled = !this.cfg.signingReady;
        }
    }

    async completeExam() {
        const otp = (document.getElementById('dguvOtpInput')?.value || '').trim();
        const otpErr = document.getElementById('dguvOtpError');
        const btn = document.getElementById('dguvOtpConfirmBtn');
        if (btn) btn.disabled = true;
        try {
            const res = await fetch(this.cfg.completeUrl || '/inventory/api/dguv-exam/complete', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify({ otp }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.ok) {
                if (otpErr) {
                    otpErr.style.display = 'block';
                    otpErr.textContent = data.error || this.t('err_complete');
                }
                return;
            }
            if (this.otpModal) this.otpModal.hide();
            let msg = this.t('success');
            if (data.pdf_url) {
                msg += ` — ${this.t('open_pdf')}: ${data.pdf_url}`;
            }
            this.showFeedback(msg, 'success');
            if (data.pdf_url) {
                window.open(data.pdf_url, '_blank');
            }
            this.clearForm();
        } catch (err) {
            if (otpErr) {
                otpErr.style.display = 'block';
                otpErr.textContent = this.t('err_complete');
            }
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
