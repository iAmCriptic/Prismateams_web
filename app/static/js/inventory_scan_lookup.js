/** Klartext-Produktsuche für Scanner-Seiten. */
/* global fetchInventoryApi */

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

window.InventoryScanLookup = InventoryScanLookup;
