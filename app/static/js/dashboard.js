/**
 * Dashboard live editing: module bar order, widget DnD, settings modals.
 */
(function () {
    'use strict';

    const boot = window.DASHBOARD_BOOT || {};
    const i18n = window.DASHBOARD_I18N || {};
    const live = i18n.live || {};
    const editItems = (i18n.edit && i18n.edit.widgets && i18n.edit.widgets.items) || {};

    const page = document.querySelector('.dashboard-page--live');
    if (!page) return;

    const configUrl = boot.configUrl || page.dataset.dashboardConfigUrl || '/api/dashboard/config';
    const contactsSearchUrl = boot.contactsSearchUrl || page.dataset.contactsSearchUrl || '';
    let options = boot.options || {};
    let widgets = Array.isArray(boot.widgets) ? boot.widgets.map((w) => ({ ...w })) : [];

    let arrangeMode = false;
    let moduleSortable = null;
    let modalMode = null; // 'settings' | 'add'
    let activeWidgetId = null;

    const grid = document.getElementById('dashboardWidgetGrid');
    const moduleBar = document.getElementById('dashboardModuleBar');
    const arrangeBtn = document.getElementById('dashboardArrangeBtn');
    const addBtn = document.getElementById('dashboardAddWidgetBtn');
    const modalEl = document.getElementById('dashboardWidgetModal');
    const modalTitle = document.getElementById('dashboardWidgetModalTitle');
    const modalBody = document.getElementById('dashboardWidgetModalBody');
    const modalSave = document.getElementById('dashboardWidgetModalSave');

    function t(path, fallback) {
        const parts = String(path || '').split('.');
        let cur = i18n;
        for (const p of parts) {
            if (!cur || typeof cur !== 'object') return fallback;
            cur = cur[p];
        }
        return (typeof cur === 'string' && cur) || fallback;
    }

    function newId() {
        return Math.random().toString(16).slice(2, 12);
    }

    async function saveConfig(partial) {
        const res = await fetch(configUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            credentials: 'same-origin',
            body: JSON.stringify(partial),
        });
        if (!res.ok) throw new Error('save_failed');
        return res.json();
    }

    function clamp(n, min, max) {
        return Math.max(min, Math.min(max, n));
    }

    function collectWidgetsFromDom() {
        if (!grid) return widgets;
        const order = [];
        grid.querySelectorAll('.dash-widget[data-widget-id]').forEach((el) => {
            const id = el.dataset.widgetId;
            let cfg = {};
            try {
                cfg = JSON.parse(el.dataset.widgetConfig || '{}');
            } catch (_) { /* ignore */ }
            const existing = widgets.find((w) => w.id === id) || {};
            const merged = {
                ...existing,
                ...cfg,
                id,
                type: el.dataset.widgetType || cfg.type || existing.type,
                w: clamp(parseInt(el.dataset.colSpan, 10) || existing.w || cfg.w || 1, 1, 4),
                h: clamp(parseInt(el.dataset.rowSpan, 10) || existing.h || cfg.h || 2, 1, 6),
                x: clamp(parseInt(el.dataset.gridX, 10) || existing.x || cfg.x || 1, 1, 4),
                y: Math.max(1, parseInt(el.dataset.gridY, 10) || existing.y || cfg.y || 1),
                grid_v: 2,
            };
            order.push(merged);
            el.dataset.widgetConfig = JSON.stringify(merged);
        });
        order.sort((a, b) => (a.y - b.y) || (a.x - b.x));
        widgets = order;
        return widgets;
    }

    function readWidgetConfig(el) {
        try {
            return JSON.parse(el.dataset.widgetConfig || '{}');
        } catch (_) {
            return { id: el.dataset.widgetId, type: el.dataset.widgetType };
        }
    }

    function applyWidgetPlacement(el, x, y, w, h) {
        const nextW = clamp(w, 1, 4);
        const nextH = clamp(h, 1, 6);
        const nextX = clamp(x, 1, 5 - nextW);
        const nextY = Math.max(1, y | 0);
        el.dataset.colSpan = String(nextW);
        el.dataset.rowSpan = String(nextH);
        el.dataset.gridX = String(nextX);
        el.dataset.gridY = String(nextY);
        el.style.setProperty('--dash-w', String(nextW));
        el.style.setProperty('--dash-h', String(nextH));
        el.style.setProperty('--dash-x', String(nextX));
        el.style.setProperty('--dash-y', String(nextY));
        const cfg = readWidgetConfig(el);
        cfg.w = nextW;
        cfg.h = nextH;
        cfg.x = nextX;
        cfg.y = nextY;
        cfg.grid_v = 2;
        el.dataset.widgetConfig = JSON.stringify(cfg);
        return { x: nextX, y: nextY, w: nextW, h: nextH };
    }

    function applyWidgetSize(el, w, h) {
        const x = parseInt(el.dataset.gridX, 10) || 1;
        const y = parseInt(el.dataset.gridY, 10) || 1;
        applyWidgetPlacement(el, x, y, w, h);
    }

    function rectsOverlap(a, b) {
        return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
    }

    function otherRects(excludeId) {
        if (!grid) return [];
        const out = [];
        grid.querySelectorAll('.dash-widget[data-widget-id]').forEach((el) => {
            const id = el.dataset.widgetId;
            if (id === excludeId) return;
            out.push({
                id,
                x: parseInt(el.dataset.gridX, 10) || 1,
                y: parseInt(el.dataset.gridY, 10) || 1,
                w: parseInt(el.dataset.colSpan, 10) || 1,
                h: parseInt(el.dataset.rowSpan, 10) || 2,
            });
        });
        return out;
    }

    function placementFits(x, y, w, h, excludeId) {
        if (x < 1 || y < 1 || w < 1 || h < 1 || x + w - 1 > 4) return false;
        const rect = { x, y, w, h };
        return !otherRects(excludeId).some((o) => rectsOverlap(rect, o));
    }

    function ensureResizeHandles() {
        if (!grid) return;
        grid.querySelectorAll('.dash-widget').forEach((el) => {
            if (el.querySelector('.dash-widget-resize')) return;
            el.insertAdjacentHTML(
                'beforeend',
                '<span class="dash-widget-resize dash-widget-resize--e" data-resize="e" title="Breite"></span>' +
                '<span class="dash-widget-resize dash-widget-resize--s" data-resize="s" title="Höhe"></span>' +
                '<span class="dash-widget-resize dash-widget-resize--se" data-resize="se" title="Größe"></span>'
            );
        });
    }

    function getGridMetrics() {
        if (!grid) return { cols: 1, colWidth: 1, rowHeight: 88, gap: 0, left: 0, top: 0 };
        const styles = getComputedStyle(grid);
        const cols = (styles.gridTemplateColumns || '').split(' ').filter(Boolean).length || 1;
        const gap = parseFloat(styles.columnGap || styles.gap || '0') || 0;
        const rect = grid.getBoundingClientRect();
        const colWidth = cols > 0 ? (rect.width - gap * (cols - 1)) / cols : rect.width;
        const rowHeight = 5.5 * 16; // matches grid-auto-rows: 5.5rem
        return { cols, colWidth, rowHeight: rowHeight + gap, gap, left: rect.left, top: rect.top };
    }

    function cellFromPoint(clientX, clientY) {
        const m = getGridMetrics();
        let x = 1;
        let acc = m.left;
        for (let i = 1; i <= m.cols; i++) {
            const next = acc + m.colWidth;
            if (clientX < next + m.gap / 2 || i === m.cols) {
                x = i;
                break;
            }
            acc = next + m.gap;
        }
        const y = Math.max(1, Math.floor((clientY - m.top) / Math.max(m.rowHeight, 1)) + 1);
        return { x, y, cols: m.cols };
    }

    function setArrangeMode(on) {
        arrangeMode = !!on;
        page.classList.toggle('is-arranging', arrangeMode);
        if (arrangeBtn) {
            arrangeBtn.setAttribute('aria-pressed', arrangeMode ? 'true' : 'false');
            arrangeBtn.classList.toggle('active', arrangeMode);
        }
        document.querySelectorAll('.dash-widget-handle').forEach((h) => {
            h.classList.toggle('d-none', !arrangeMode);
        });
        if (arrangeMode) {
            ensureResizeHandles();
            bindModuleSortable();
        } else {
            destroyModuleSortable();
        }
    }

    function destroyModuleSortable() {
        if (moduleSortable) {
            moduleSortable.destroy();
            moduleSortable = null;
        }
        if (moduleBar) moduleBar.classList.remove('is-sorting');
    }

    function bindModuleSortable() {
        destroyModuleSortable();
        if (!window.Sortable || !moduleBar) return;
        moduleBar.classList.add('is-sorting');
        moduleSortable = window.Sortable.create(moduleBar, {
            animation: 150,
            draggable: '.dashboard-module-chip',
            ghostClass: 'dashboard-module-chip-ghost',
            onEnd: async () => {
                const keys = [...moduleBar.querySelectorAll('.dashboard-module-chip')]
                    .map((el) => el.dataset.moduleKey)
                    .filter(Boolean);
                try {
                    await saveConfig({ dashboard_module_order: keys });
                } catch (err) {
                    console.error(err);
                }
            },
        });
    }

    let resizeState = null;
    let dragState = null;

    function onResizePointerDown(e) {
        if (!arrangeMode || !grid) return;
        const handle = e.target.closest('.dash-widget-resize');
        if (!handle) return;
        e.preventDefault();
        e.stopPropagation();
        const widget = handle.closest('.dash-widget');
        if (!widget) return;
        const metrics = getGridMetrics();
        resizeState = {
            widget,
            mode: handle.dataset.resize || 'se',
            startX: e.clientX,
            startY: e.clientY,
            startW: parseInt(widget.dataset.colSpan, 10) || 1,
            startH: parseInt(widget.dataset.rowSpan, 10) || 2,
            startGX: parseInt(widget.dataset.gridX, 10) || 1,
            startGY: parseInt(widget.dataset.gridY, 10) || 1,
            colWidth: metrics.colWidth,
            rowHeight: metrics.rowHeight,
            pointerId: e.pointerId,
            lastGood: {
                w: parseInt(widget.dataset.colSpan, 10) || 1,
                h: parseInt(widget.dataset.rowSpan, 10) || 2,
            },
        };
        widget.classList.add('is-resizing');
        handle.setPointerCapture?.(e.pointerId);
    }

    function onResizePointerMove(e) {
        if (!resizeState) return;
        const { widget, mode, startX, startY, startW, startH, startGX, startGY, colWidth, rowHeight } = resizeState;
        let nextW = startW;
        let nextH = startH;
        if (mode === 'e' || mode === 'se') {
            const dw = Math.round((e.clientX - startX) / Math.max(colWidth, 1));
            nextW = startW + dw;
        }
        if (mode === 's' || mode === 'se') {
            const dh = Math.round((e.clientY - startY) / Math.max(rowHeight, 1));
            nextH = startH + dh;
        }
        nextW = clamp(nextW, 1, 5 - startGX);
        nextH = clamp(nextH, 1, 6);
        const id = widget.dataset.widgetId;
        if (placementFits(startGX, startGY, nextW, nextH, id)) {
            applyWidgetPlacement(widget, startGX, startGY, nextW, nextH);
            resizeState.lastGood = { w: nextW, h: nextH };
        }
    }

    async function onResizePointerUp() {
        if (!resizeState) return;
        const { widget } = resizeState;
        widget.classList.remove('is-resizing');
        resizeState = null;
        try {
            const next = collectWidgetsFromDom();
            await saveConfig({ widgets: next });
        } catch (err) {
            console.error(err);
        }
    }

    function onDragPointerDown(e) {
        if (!arrangeMode || !grid || resizeState) return;
        if (e.target.closest('.dash-widget-resize, .dash-widget-settings-btn, a, button, input, textarea, select')) {
            return;
        }
        const widget = e.target.closest('.dash-widget[data-widget-id]');
        if (!widget) return;
        // Only primary button / touch
        if (e.button != null && e.button !== 0) return;
        e.preventDefault();
        const startGX = parseInt(widget.dataset.gridX, 10) || 1;
        const startGY = parseInt(widget.dataset.gridY, 10) || 1;
        const cell = cellFromPoint(e.clientX, e.clientY);
        dragState = {
            widget,
            pointerId: e.pointerId,
            offsetX: cell.x - startGX,
            offsetY: cell.y - startGY,
            lastGood: { x: startGX, y: startGY },
            moved: false,
        };
        widget.classList.add('is-dragging');
        widget.setPointerCapture?.(e.pointerId);
    }

    function onDragPointerMove(e) {
        if (!dragState) return;
        const { widget, offsetX, offsetY } = dragState;
        const w = parseInt(widget.dataset.colSpan, 10) || 1;
        const h = parseInt(widget.dataset.rowSpan, 10) || 2;
        const cell = cellFromPoint(e.clientX, e.clientY);
        let nextX = clamp(cell.x - offsetX, 1, 5 - w);
        let nextY = Math.max(1, cell.y - offsetY);
        const id = widget.dataset.widgetId;
        if (placementFits(nextX, nextY, w, h, id)) {
            applyWidgetPlacement(widget, nextX, nextY, w, h);
            dragState.lastGood = { x: nextX, y: nextY };
            dragState.moved = true;
        }
    }

    async function onDragPointerUp() {
        if (!dragState) return;
        const { widget, moved } = dragState;
        widget.classList.remove('is-dragging');
        dragState = null;
        if (!moved) return;
        try {
            const next = collectWidgetsFromDom();
            await saveConfig({ widgets: next });
        } catch (err) {
            console.error(err);
        }
    }

    if (grid) {
        grid.addEventListener('pointerdown', (e) => {
            if (e.target.closest('.dash-widget-resize')) {
                onResizePointerDown(e);
                return;
            }
            onDragPointerDown(e);
        });
        window.addEventListener('pointermove', (e) => {
            if (resizeState) onResizePointerMove(e);
            else if (dragState) onDragPointerMove(e);
        });
        window.addEventListener('pointerup', async () => {
            if (resizeState) await onResizePointerUp();
            else if (dragState) await onDragPointerUp();
        });
        window.addEventListener('pointercancel', async () => {
            if (resizeState) await onResizePointerUp();
            else if (dragState) await onDragPointerUp();
        });
    }

    function openModal(title) {
        if (!modalEl || typeof bootstrap === 'undefined') return null;
        if (modalTitle) modalTitle.textContent = title;
        return bootstrap.Modal.getOrCreateInstance(modalEl);
    }

    function checkboxList(name, items, selectedIds, idKey, labelKey, visKey) {
        const selected = new Set((selectedIds || []).map(String));
        if (!items || !items.length) {
            return `<p class="text-muted small mb-0">${t('live.no_options', 'Keine Einträge verfügbar.')}</p>`;
        }
        return `<div class="dashboard-picker-list">${items.map((item) => {
            const id = item[idKey];
            const label = item[labelKey] || item.name || item.title || id;
            const vis = visKey ? item[visKey] : null;
            const visLabel = item.visibility_label || '';
            return `<label class="dashboard-picker-item">
                <input type="checkbox" name="${name}" value="${id}" ${selected.has(String(id)) ? 'checked' : ''}>
                <span class="dashboard-picker-label">${escapeHtml(label)}</span>
                ${vis ? `<span class="dash-vis-badge dash-vis-badge--${escapeHtml(vis)}" title="${escapeHtml(visLabel)}"><i class="bi ${visIcon(vis)}"></i></span>` : ''}
            </label>`;
        }).join('')}</div>`;
    }

    function radioList(name, items, selectedId) {
        const sel = selectedId === null || selectedId === undefined ? 'null' : String(selectedId);
        return `<div class="dashboard-picker-list">${items.map((item) => {
            const id = item.id === null || item.id === undefined ? 'null' : String(item.id);
            return `<label class="dashboard-picker-item">
                <input type="radio" name="${name}" value="${id}" ${sel === id ? 'checked' : ''}>
                <span class="dashboard-picker-label">${escapeHtml(item.name || item.title || id)}</span>
                ${item.type && item.type !== 'main' ? `<span class="dash-vis-badge dash-vis-badge--${escapeHtml(item.type === 'group' ? 'team' : item.type)}"><i class="bi ${visIcon(item.type === 'group' ? 'team' : item.type)}"></i></span>` : ''}
            </label>`;
        }).join('')}</div>`;
    }

    function visIcon(v) {
        if (v === 'private') return 'bi-lock';
        if (v === 'team' || v === 'group') return 'bi-people';
        return 'bi-globe2';
    }

    function escapeHtml(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function buildSettingsForm(widget) {
        const type = widget.type;
        let html = `<p class="text-muted small">${escapeHtml((editItems[type] && editItems[type].description) || '')}</p>`;

        if (type === 'termine') {
            html += `<label class="form-label">${t('edit.widgets.calendars_label', 'Kalender')}</label>`;
            html += checkboxList('calendar_ids', options.calendars || [], widget.calendar_ids || [], 'id', 'name');
            html += `<p class="form-text">${t('live.calendars_hint', 'Keine Auswahl = alle zugänglichen Kalender.')}</p>`;
        } else if (type === 'kontakte') {
            html += `<label class="form-label">${t('edit.widgets.contacts_label', 'Kontakte auswählen')}</label>`;
            html += `<input type="search" class="form-control form-control-sm mb-2" id="dashContactSearch" placeholder="${t('edit.widgets.contacts_search', 'Kontakt suchen…')}">`;
            html += `<div id="dashContactResults" class="dashboard-picker-list mb-2"></div>`;
            html += `<div id="dashContactSelected" class="dashboard-picker-selected"></div>`;
            html += `<p class="form-text">${t('edit.widgets.contacts_max', 'Maximal 5 Kontakte')}</p>`;
        } else if (type === 'emails') {
            html += `<label class="form-label">${t('live.mailbox_label', 'Postfach')}</label>`;
            html += radioList('mailbox_id', options.mailboxes || [], widget.mailbox_id);
        } else if (type === 'passwoerter') {
            html += `<label class="form-label">${t('live.credentials_label', 'Passwörter')}</label>`;
            html += checkboxList('credential_ids', options.credentials || [], widget.credential_ids || [], 'id', 'name', 'visibility');
            html += `<p class="form-text">${t('live.credentials_hint', 'Keine Auswahl = Favoriten.')}</p>`;
        } else if (type === 'kanban_aenderungen') {
            html += `<label class="form-label">${t('live.boards_label', 'Boards')}</label>`;
            html += checkboxList('board_ids', options.boards || [], widget.board_ids || [], 'id', 'title', 'visibility');
            html += `<p class="form-text">${t('live.boards_hint', 'Keine Auswahl = alle Boards mit Zugriff.')}</p>`;
        } else {
            html += `<p class="mb-0">${t('live.no_settings', 'Für dieses Widget gibt es keine weiteren Einstellungen.')}</p>`;
        }
        return html;
    }

    function renderSelectedContacts(ids, names) {
        const box = document.getElementById('dashContactSelected');
        if (!box) return;
        box.innerHTML = (ids || []).map((id) => {
            const name = (names && names[id]) || `#${id}`;
            return `<span class="dashboard-chip" data-contact-id="${id}">
                ${escapeHtml(name)}
                <button type="button" class="dashboard-chip-remove" aria-label="remove">&times;</button>
            </span>`;
        }).join('');
        box.querySelectorAll('.dashboard-chip-remove').forEach((btn) => {
            btn.addEventListener('click', () => {
                const chip = btn.closest('.dashboard-chip');
                if (chip) chip.remove();
            });
        });
    }

    function getSelectedContactIds() {
        return [...document.querySelectorAll('#dashContactSelected .dashboard-chip')]
            .map((el) => parseInt(el.dataset.contactId, 10))
            .filter((n) => !Number.isNaN(n))
            .slice(0, 5);
    }

    async function bindContactSearch(initialIds) {
        const search = document.getElementById('dashContactSearch');
        const results = document.getElementById('dashContactResults');
        const names = {};
        (initialIds || []).forEach((id) => { names[id] = `#${id}`; });
        renderSelectedContacts(initialIds || [], names);

        if (!search || !results || !contactsSearchUrl) return;

        let timer = null;
        search.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(async () => {
                const q = search.value.trim();
                if (q.length < 2) {
                    results.innerHTML = '';
                    return;
                }
                try {
                    const res = await fetch(`${contactsSearchUrl}?q=${encodeURIComponent(q)}`, {
                        headers: { 'X-Requested-With': 'XMLHttpRequest' },
                        credentials: 'same-origin',
                    });
                    if (!res.ok) return;
                    const data = await res.json();
                    const list = (Array.isArray(data) ? data : (data.contacts || data.results || []))
                        .filter((c) => c && c.type === 'contact' && c.id != null);
                    results.innerHTML = list.slice(0, 8).map((c) => {
                        const id = c.id;
                        const name = c.name || c.full_name || `#${id}`;
                        names[id] = name;
                        const vis = c.visibility || '';
                        return `<button type="button" class="dashboard-picker-item dashboard-picker-item--btn" data-contact-id="${id}" data-contact-name="${escapeHtml(name)}">
                            <span class="dashboard-picker-label">${escapeHtml(name)}</span>
                            ${vis ? `<span class="dash-vis-badge dash-vis-badge--${escapeHtml(vis)}"><i class="bi ${visIcon(vis)}"></i></span>` : ''}
                        </button>`;
                    }).join('');
                    results.querySelectorAll('[data-contact-id]').forEach((btn) => {
                        btn.addEventListener('click', () => {
                            const id = parseInt(btn.dataset.contactId, 10);
                            const name = btn.dataset.contactName || `#${id}`;
                            names[id] = name;
                            const current = getSelectedContactIds();
                            if (!current.includes(id) && current.length < 5) {
                                current.push(id);
                                renderSelectedContacts(current, names);
                            }
                        });
                    });
                } catch (err) {
                    console.error(err);
                }
            }, 200);
        });
    }

    function openSettings(widgetId) {
        const el = grid && grid.querySelector(`.dash-widget[data-widget-id="${widgetId}"]`);
        if (!el) return;
        const cfg = readWidgetConfig(el);
        const widget = widgets.find((w) => w.id === widgetId) || cfg;
        modalMode = 'settings';
        activeWidgetId = widgetId;
        if (modalBody) modalBody.innerHTML = buildSettingsForm(widget);
        const modal = openModal(t('live.settings', 'Widget-Einstellungen'));
        if (modal) modal.show();
        if (widget.type === 'kontakte') {
            bindContactSearch(widget.contact_ids || []);
        }
        if (modalSave) modalSave.classList.toggle('d-none', false);
    }

    function openAddWidget() {
        modalMode = 'add';
        activeWidgetId = null;
        const usedOnce = new Set(
            widgets.filter((w) => (options.widget_types || []).find((t) => t.type === w.type && t.once))
                .map((w) => w.type)
        );
        const types = (options.widget_types || []).filter((t) => !(t.once && usedOnce.has(t.type)));
        if (modalBody) {
            if (!types.length) {
                modalBody.innerHTML = `<p class="mb-0">${t('live.all_added', 'Alle verfügbaren Widgets sind bereits hinzugefügt.')}</p>`;
                if (modalSave) modalSave.classList.add('d-none');
            } else {
                modalBody.innerHTML = `<div class="dashboard-picker-list">${types.map((t) => `
                    <label class="dashboard-picker-item">
                        <input type="radio" name="add_widget_type" value="${escapeHtml(t.type)}">
                        <span>
                            <strong class="dashboard-picker-label d-block">${escapeHtml(t.label || t.type)}</strong>
                            <span class="text-muted small">${escapeHtml(t.description || '')}</span>
                        </span>
                    </label>
                `).join('')}</div>`;
                if (modalSave) modalSave.classList.remove('d-none');
            }
        }
        const modal = openModal(t('live.add_widget', 'Widget hinzufügen'));
        if (modal) modal.show();
    }

    function readSettingsFromForm(type, base) {
        const next = { ...base };
        if (type === 'termine') {
            next.calendar_ids = [...modalBody.querySelectorAll('input[name="calendar_ids"]:checked')]
                .map((el) => parseInt(el.value, 10))
                .filter((n) => !Number.isNaN(n));
        } else if (type === 'kontakte') {
            next.contact_ids = getSelectedContactIds();
        } else if (type === 'emails') {
            const checked = modalBody.querySelector('input[name="mailbox_id"]:checked');
            if (!checked || checked.value === 'null') next.mailbox_id = null;
            else next.mailbox_id = parseInt(checked.value, 10);
        } else if (type === 'passwoerter') {
            next.credential_ids = [...modalBody.querySelectorAll('input[name="credential_ids"]:checked')]
                .map((el) => parseInt(el.value, 10))
                .filter((n) => !Number.isNaN(n))
                .slice(0, 5);
        } else if (type === 'kanban_aenderungen') {
            next.board_ids = [...modalBody.querySelectorAll('input[name="board_ids"]:checked')]
                .map((el) => parseInt(el.value, 10))
                .filter((n) => !Number.isNaN(n));
        }
        return next;
    }

    async function onModalSave() {
        try {
            if (modalMode === 'add') {
                const checked = modalBody && modalBody.querySelector('input[name="add_widget_type"]:checked');
                if (!checked) return;
                const type = checked.value;
                const entry = { id: newId(), type, w: 1, h: 2, grid_v: 2 };
                if (type === 'termine') entry.calendar_ids = [];
                if (type === 'kontakte') entry.contact_ids = [];
                if (type === 'emails') entry.mailbox_id = null;
                if (type === 'passwoerter') entry.credential_ids = [];
                if (type === 'kanban_aenderungen') entry.board_ids = [];
                widgets = [...collectWidgetsFromDom(), entry];
                await saveConfig({ widgets });
                window.location.reload();
                return;
            }
            if (modalMode === 'settings' && activeWidgetId) {
                const current = widgets.find((w) => w.id === activeWidgetId) || { id: activeWidgetId };
                const updated = readSettingsFromForm(current.type, current);
                widgets = collectWidgetsFromDom().map((w) => (w.id === activeWidgetId ? updated : w));
                await saveConfig({ widgets });
                window.location.reload();
            }
        } catch (err) {
            console.error(err);
            if (typeof window.ptAlert === 'function') {
                window.ptAlert(t('live.save_error', 'Speichern fehlgeschlagen.'), 'danger');
            } else {
                window.alert(t('live.save_error', 'Speichern fehlgeschlagen.'));
            }
        }
    }

    // Widget card navigation (header/empty → module), ignore interactive children
    if (grid) {
        grid.addEventListener('click', (e) => {
            if (arrangeMode) return;
            if (e.target.closest('[data-stop-nav], a, button, input, .dash-widget-settings-btn, .dash-contact-actions, .dash-email-actions')) {
                const row = e.target.closest('[data-href]');
                if (row && row.dataset.href && !e.target.closest('a, button')) {
                    e.preventDefault();
                    window.location.href = row.dataset.href;
                }
                return;
            }
            const widget = e.target.closest('.dash-widget[data-widget-href]');
            if (widget && widget.dataset.widgetHref) {
                window.location.href = widget.dataset.widgetHref;
            }
        });

        grid.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-widget-settings]');
            if (!btn) return;
            e.preventDefault();
            e.stopPropagation();
            openSettings(btn.getAttribute('data-widget-settings'));
        });
    }

    if (arrangeBtn) {
        arrangeBtn.addEventListener('click', () => setArrangeMode(!arrangeMode));
    }
    if (addBtn) {
        addBtn.addEventListener('click', openAddWidget);
    }
    if (modalSave) {
        modalSave.addEventListener('click', onModalSave);
    }

    if (moduleBar) {
        moduleBar.addEventListener('click', (e) => {
            if (!arrangeMode) return;
            const chip = e.target.closest('.dashboard-module-chip');
            if (chip) {
                e.preventDefault();
                e.stopPropagation();
            }
        });
    }

    // Context menu hook: manage widgets → arrange mode
    window.dashboardEnterArrangeMode = function () {
        setArrangeMode(true);
    };

    // Sync widgets from DOM config attributes on load
    if (grid) {
        const fromDom = [];
        grid.querySelectorAll('.dash-widget[data-widget-id]').forEach((el) => {
            fromDom.push(readWidgetConfig(el));
        });
        if (fromDom.length) widgets = fromDom;
    }
})();
