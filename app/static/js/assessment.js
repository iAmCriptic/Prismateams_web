/**
 * Assessment UI helpers: pill selects, print URL sync, view toggle, bulk select, double confirm.
 */
(function (global) {
    function escapeHtml(str) {
        return String(str ?? '').replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    function qs(sel, root) {
        return (root || document).querySelector(sel);
    }

    function qsa(sel, root) {
        return Array.from((root || document).querySelectorAll(sel));
    }

    function enhancePills(root) {
        if (global.InventoryPillSelect) {
            global.InventoryPillSelect.enhanceAll(root || document);
        }
    }

    /**
     * Dateien-Stil: Hover-Icons + immer sichtbares 3-Punkte-Menü.
     * items: [{ icon, label, title?, href?, attrs?, danger?, hover? }]
     * attrs = HTML-Attribute-String, z.B. 'data-edit-id="3"'
     */
    function buildRowActions(items) {
        const list = Array.isArray(items) ? items : [];
        const hoverHtml = list.filter((i) => i && i.hover).map((item) => {
            const title = escapeHtml(item.title || item.label || '');
            const cls = 'btn btn-sm btn-link';
            const inner = `<i class="bi ${escapeHtml(item.icon || 'bi-circle')}"></i>`;
            if (item.href) {
                return `<a class="${cls}" href="${escapeHtml(item.href)}" target="${item.target || '_self'}" rel="${item.rel || ''}" title="${title}">${inner}</a>`;
            }
            return `<button type="button" class="${cls}" title="${title}" ${item.attrs || ''}>${inner}</button>`;
        }).join('');

        const menuHtml = list.filter(Boolean).map((item) => {
            const label = escapeHtml(item.label || '');
            const icon = escapeHtml(item.icon || 'bi-circle');
            const danger = item.danger ? ' text-danger' : '';
            if (item.href) {
                return `<li><a class="dropdown-item${danger}" href="${escapeHtml(item.href)}" target="${item.target || '_self'}" rel="${item.rel || ''}" ${item.attrs || ''}><i class="bi ${icon} me-2"></i>${label}</a></li>`;
            }
            return `<li><button type="button" class="dropdown-item${danger}" ${item.attrs || ''}><i class="bi ${icon} me-2"></i>${label}</button></li>`;
        }).join('');

        if (!menuHtml && !hoverHtml) return '';

        return `
            <div class="mod-list-actions">
                <div class="mod-list-hover-actions">${hoverHtml}</div>
                <div class="dropdown d-inline-block">
                    <button type="button" class="btn btn-sm btn-link" data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}' aria-expanded="false">
                        <i class="bi bi-three-dots-vertical"></i>
                    </button>
                    <ul class="dropdown-menu dropdown-menu-end files-dropdown-menu">${menuHtml}</ul>
                </div>
            </div>`;
    }

    /** Name-Zelle ohne Dateien-Checkbox/Flex-Collapse. */
    function buildNameCell(iconClass, text, opts) {
        const name = escapeHtml(text || '');
        const icon = escapeHtml(iconClass || 'bi-circle');
        const color = escapeHtml((opts && opts.iconColor) || 'text-primary');
        const prefix = (opts && opts.prefix) ? `<span class="text-muted me-1">${escapeHtml(opts.prefix)}</span>` : '';
        const sub = (opts && opts.sub) ? `<div class="small text-muted">${escapeHtml(opts.sub)}</div>` : '';
        return `<span class="mod-list-name"><i class="bi ${icon} ${color} me-2" aria-hidden="true"></i>${prefix}<span title="${name}">${name}</span></span>${sub}`;
    }

    function syncPrintLinks(params) {
        const links = qsa('[data-assessment-print]');
        if (!links.length) return;
        links.forEach((link) => {
            try {
                const url = new URL(link.href, window.location.origin);
                Object.entries(params || {}).forEach(([k, v]) => {
                    if (v === undefined || v === null || v === '') url.searchParams.delete(k);
                    else url.searchParams.set(k, v);
                });
                link.href = url.pathname + url.search;
            } catch (e) { /* ignore */ }
        });
    }

    function initViewToggle(storageKey, root) {
        const wrap = qs('[data-assessment-view-toggle]', root);
        if (!wrap) return 'list';
        const key = storageKey || 'assessmentViewMode';
        let mode = localStorage.getItem(key) || 'list';
        const apply = () => {
            qsa('[data-assessment-view]', root).forEach((el) => {
                el.hidden = el.dataset.assessmentView !== mode;
            });
            qsa('[data-assessment-view-btn]', wrap).forEach((btn) => {
                btn.classList.toggle('active', btn.dataset.assessmentViewBtn === mode);
                btn.classList.toggle('is-active', btn.dataset.assessmentViewBtn === mode);
            });
        };
        qsa('[data-assessment-view-btn]', wrap).forEach((btn) => {
            btn.addEventListener('click', () => {
                mode = btn.dataset.assessmentViewBtn;
                localStorage.setItem(key, mode);
                apply();
            });
        });
        apply();
        return mode;
    }

    function initBulkSelect(root) {
        const container = qs('[data-assessment-bulk]', root);
        if (!container) return;
        const selected = new Set();
        const bar = qs('[data-assessment-bulk-bar]', container);
        const countEl = qs('[data-assessment-bulk-count]', container);

        function refresh() {
            qsa('[data-assessment-bulk-item]', container).forEach((el) => {
                const id = el.dataset.assessmentBulkItem;
                const on = selected.has(id);
                el.classList.toggle('is-selected', on);
                const check = qs('.assessment-select-check', el);
                if (check) check.checked = on;
            });
            if (bar) bar.hidden = selected.size === 0;
            if (countEl) countEl.textContent = String(selected.size);
            document.body.classList.toggle('assessment-has-selection', selected.size > 0);
            document.body.classList.toggle('files-has-selection', selected.size > 0);
        }

        container.addEventListener('change', (e) => {
            const check = e.target.closest('.assessment-select-check');
            if (!check) return;
            const item = check.closest('[data-assessment-bulk-item]');
            if (!item) return;
            const id = item.dataset.assessmentBulkItem;
            if (check.checked) selected.add(id);
            else selected.delete(id);
            refresh();
        });

        const clearBtn = qs('[data-assessment-bulk-clear]', container);
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                selected.clear();
                refresh();
            });
        }

        refresh();
        return {
            getSelected: () => Array.from(selected),
            clear: () => { selected.clear(); refresh(); },
        };
    }

    function notify(message, category, options) {
        const opts = Object.assign({ timeout: 6500 }, options || {});
        if (typeof global.showAppBanner === 'function') {
            return global.showAppBanner(String(message || ''), category || 'info', opts);
        }
        window.alert(String(message || ''));
        return null;
    }

    async function doubleConfirm(message1, message2, options) {
        const opts = options || {};
        const confirmFn = global.ptConfirm;
        if (!confirmFn) {
            return window.confirm(message1) && window.confirm(message2 || message1);
        }
        const ok1 = await confirmFn(message1, {
            title: opts.title || '',
            confirmLabel: opts.confirmLabel || undefined,
            cancelLabel: opts.cancelLabel || undefined,
            danger: opts.danger !== false,
        });
        if (!ok1) return false;
        return confirmFn(message2 || message1, {
            title: opts.title2 || opts.title || '',
            confirmLabel: opts.confirmLabel2 || opts.confirmLabel || undefined,
            cancelLabel: opts.cancelLabel || undefined,
            danger: true,
        });
    }

    function init() {
        enhancePills(document.querySelector('.assessment-page') || document);
        initViewToggle('assessmentViewMode');
        initBulkSelect(document.querySelector('[data-assessment-bulk]'));
    }

    global.AssessmentUI = {
        escapeHtml,
        enhancePills,
        buildRowActions,
        buildNameCell,
        syncPrintLinks,
        initViewToggle,
        initBulkSelect,
        doubleConfirm,
        notify,
        init,
    };
})(window);
