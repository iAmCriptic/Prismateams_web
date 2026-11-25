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
    const modalDialog = document.getElementById('dashboardWidgetModalDialog');
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

    function listRowGap(listEl) {
        const style = window.getComputedStyle(listEl);
        const gap = parseFloat(style.rowGap || style.gap);
        return Number.isFinite(gap) ? gap : 0;
    }

    function fitWidgetList(widget) {
        const list = widget.querySelector('.dash-widget-list');
        if (!list) return;

        const rows = [...list.querySelectorAll(':scope > .dash-widget-row')];
        let moreEl = list.querySelector(':scope > .dash-widget-more');

        rows.forEach((row) => row.classList.remove('is-clipped'));

        if (!rows.length) {
            if (moreEl) moreEl.remove();
            return;
        }

        const available = list.clientHeight;
        if (available <= 0) return;

        const gap = listRowGap(list);
        const moreTemplate = t('live.more_items', '+{count} more');
        let used = 0;
        let visibleCount = 0;

        for (let i = 0; i < rows.length; i += 1) {
            const row = rows[i];
            const rowHeight = row.offsetHeight;
            const gapBefore = visibleCount > 0 ? gap : 0;
            const hiddenAfter = rows.length - i - 1;
            let moreReserve = 0;
            if (hiddenAfter > 0) {
                if (!moreEl) {
                    moreEl = document.createElement('div');
                    moreEl.className = 'dash-widget-more';
                    list.appendChild(moreEl);
                }
                moreEl.textContent = moreTemplate.replace('{count}', String(hiddenAfter));
                moreEl.classList.remove('is-clipped');
                moreReserve = moreEl.offsetHeight + (visibleCount > 0 || rowHeight > 0 ? gap : 0);
            } else if (moreEl) {
                moreEl.classList.add('is-clipped');
            }

            if (used + gapBefore + rowHeight + moreReserve <= available + 0.5) {
                used += gapBefore + rowHeight;
                visibleCount += 1;
            } else {
                for (let j = i; j < rows.length; j += 1) {
                    rows[j].classList.add('is-clipped');
                }
                break;
            }
        }

        const hidden = rows.length - visibleCount;
        if (hidden > 0) {
            if (!moreEl) {
                moreEl = document.createElement('div');
                moreEl.className = 'dash-widget-more';
                list.appendChild(moreEl);
            }
            moreEl.textContent = moreTemplate.replace('{count}', String(hidden));
            moreEl.classList.remove('is-clipped');
        } else if (moreEl) {
            moreEl.remove();
        }
    }

    function fitWidgetLists(root) {
        const scope = root || grid;
        if (!scope) return;
        const widgetsToFit = scope.classList?.contains('dash-widget')
            ? [scope]
            : [...scope.querySelectorAll('.dash-widget')];
        widgetsToFit.forEach((widget) => fitWidgetList(widget));
    }

    let fitListsRaf = null;
    function scheduleFitWidgetLists(root) {
        if (fitListsRaf) cancelAnimationFrame(fitListsRaf);
        fitListsRaf = requestAnimationFrame(() => {
            fitListsRaf = null;
            fitWidgetLists(root);
        });
    }

    let resizeDebounce = null;
    function onWindowResize() {
        clearTimeout(resizeDebounce);
        resizeDebounce = setTimeout(() => scheduleFitWidgetLists(), 120);
    }

    const MOBILE_BREAKPOINT = 768;

    function isMobileLayout() {
        return window.innerWidth < MOBILE_BREAKPOINT;
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
            const w = clamp(parseInt(el.dataset.colSpan, 10) || existing.w || cfg.w || 1, 1, 4);
            const h = clamp(parseInt(el.dataset.rowSpan, 10) || existing.h || cfg.h || 2, 1, 6);
            const x = clamp(parseInt(el.dataset.gridX, 10) || existing.x || cfg.x || 1, 1, 4);
            const y = Math.max(1, parseInt(el.dataset.gridY, 10) || existing.y || cfg.y || 1);
            const mobile_w = clamp(parseInt(el.dataset.mobileColSpan, 10) || existing.mobile_w || cfg.mobile_w || 2, 1, 2);
            const mobile_h = clamp(parseInt(el.dataset.mobileRowSpan, 10) || existing.mobile_h || cfg.mobile_h || Math.max(2, h), 1, 6);
            const mobile_x = clamp(parseInt(el.dataset.mobileGridX, 10) || existing.mobile_x || cfg.mobile_x || 1, 1, 2);
            const mobile_y = Math.max(1, parseInt(el.dataset.mobileGridY, 10) || existing.mobile_y || cfg.mobile_y || 1);
            const merged = {
                ...existing,
                ...cfg,
                id,
                type: el.dataset.widgetType || cfg.type || existing.type,
                w,
                h,
                x,
                y,
                mobile_w,
                mobile_h,
                mobile_x,
                mobile_y,
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

    function updateMobileControlsUI(el) {
        const bar = el.querySelector('.dash-widget-mobile-controls');
        if (!bar) return;
        const mw = clamp(parseInt(el.dataset.mobileColSpan, 10) || 2, 1, 2);
        const mh = clamp(parseInt(el.dataset.mobileRowSpan, 10) || 2, 1, 6);
        const widthBtn = bar.querySelector('[data-mobile-action="width"]');
        const dimEl = bar.querySelector('.dash-widget-mobile-dim');
        const decBtn = bar.querySelector('[data-mobile-action="h-dec"]');
        const incBtn = bar.querySelector('[data-mobile-action="h-inc"]');
        if (widthBtn) {
            widthBtn.textContent = mw === 1 ? '1/2' : '2/2';
            widthBtn.setAttribute('aria-pressed', mw === 2 ? 'true' : 'false');
        }
        if (dimEl) dimEl.textContent = `${mw}×${mh}`;
        if (decBtn) decBtn.disabled = mh <= 1;
        if (incBtn) incBtn.disabled = mh >= 6;
    }

    function applyWidgetPlacement(el, x, y, w, h, mobile = isMobileLayout()) {
        const cfg = readWidgetConfig(el);
        if (mobile) {
            const nextW = clamp(w, 1, 2);
            const nextH = clamp(h, 1, 6);
            const nextX = clamp(x, 1, 3 - nextW);
            const nextY = Math.max(1, y | 0);
            el.dataset.mobileColSpan = String(nextW);
            el.dataset.mobileRowSpan = String(nextH);
            el.dataset.mobileGridX = String(nextX);
            el.dataset.mobileGridY = String(nextY);
            el.style.setProperty('--dash-mw', String(nextW));
            el.style.setProperty('--dash-mh', String(nextH));
            el.style.setProperty('--dash-mx', String(nextX));
            el.style.setProperty('--dash-my', String(nextY));
            cfg.mobile_w = nextW;
            cfg.mobile_h = nextH;
            cfg.mobile_x = nextX;
            cfg.mobile_y = nextY;
            cfg.grid_v = 2;
            el.dataset.widgetConfig = JSON.stringify(cfg);
            updateMobileControlsUI(el);
            return { x: nextX, y: nextY, w: nextW, h: nextH };
        }
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
        cfg.w = nextW;
        cfg.h = nextH;
        cfg.x = nextX;
        cfg.y = nextY;
        cfg.grid_v = 2;
        el.dataset.widgetConfig = JSON.stringify(cfg);
        return { x: nextX, y: nextY, w: nextW, h: nextH };
    }

    function rectsOverlap(a, b) {
        return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
    }

    function otherRects(excludeId, mobile = isMobileLayout()) {
        if (!grid) return [];
        const out = [];
        grid.querySelectorAll('.dash-widget[data-widget-id]').forEach((el) => {
            const id = el.dataset.widgetId;
            if (id === excludeId) return;
            if (mobile) {
                out.push({
                    id,
                    x: parseInt(el.dataset.mobileGridX, 10) || 1,
                    y: parseInt(el.dataset.mobileGridY, 10) || 1,
                    w: parseInt(el.dataset.mobileColSpan, 10) || 2,
                    h: parseInt(el.dataset.mobileRowSpan, 10) || 2,
                });
            } else {
                out.push({
                    id,
                    x: parseInt(el.dataset.gridX, 10) || 1,
                    y: parseInt(el.dataset.gridY, 10) || 1,
                    w: parseInt(el.dataset.colSpan, 10) || 1,
                    h: parseInt(el.dataset.rowSpan, 10) || 2,
                });
            }
        });
        return out;
    }

    function placementFits(x, y, w, h, excludeId, mobile = isMobileLayout()) {
        const cols = mobile ? 2 : 4;
        if (x < 1 || y < 1 || w < 1 || h < 1 || x + w - 1 > cols) return false;
        const rect = { x, y, w, h };
        return !otherRects(excludeId, mobile).some((o) => rectsOverlap(rect, o));
    }

    function reflowMobileWidgets(priorityEl, nextW, nextH) {
        if (!grid || !priorityEl) return;
        const curX = clamp(parseInt(priorityEl.dataset.mobileGridX, 10) || 1, 1, 3 - nextW);
        const curY = Math.max(1, parseInt(priorityEl.dataset.mobileGridY, 10) || 1);
        const placed = [];
        const pRect = applyWidgetPlacement(priorityEl, nextW === 2 ? 1 : curX, curY, nextW, nextH, true);
        placed.push(pRect);

        const fitsIn = (x, y, w, h) => {
            if (x < 1 || y < 1 || x + w - 1 > 2) return false;
            const r = { x, y, w, h };
            return !placed.some((o) => rectsOverlap(r, o));
        };

        const firstFit = (w, h) => {
            for (let y = 1; y < 500; y += 1) {
                for (let x = 1; x <= 3 - w; x += 1) {
                    if (fitsIn(x, y, w, h)) return { x, y };
                }
            }
            return { x: 1, y: 1 };
        };

        const others = [...grid.querySelectorAll('.dash-widget[data-widget-id]')]
            .filter((el) => el !== priorityEl)
            .sort((a, b) => {
                const ay = parseInt(a.dataset.mobileGridY, 10) || 1;
                const by = parseInt(b.dataset.mobileGridY, 10) || 1;
                if (ay !== by) return ay - by;
                return (parseInt(a.dataset.mobileGridX, 10) || 1) - (parseInt(b.dataset.mobileGridX, 10) || 1);
            });

        others.forEach((el) => {
            const mw = clamp(parseInt(el.dataset.mobileColSpan, 10) || 2, 1, 2);
            const mh = clamp(parseInt(el.dataset.mobileRowSpan, 10) || 2, 1, 6);
            let mx = clamp(parseInt(el.dataset.mobileGridX, 10) || 1, 1, 3 - mw);
            let my = Math.max(1, parseInt(el.dataset.mobileGridY, 10) || 1);
            if (!fitsIn(mx, my, mw, mh)) {
                const pos = firstFit(mw, mh);
                mx = pos.x;
                my = pos.y;
            }
            const rect = applyWidgetPlacement(el, mx, my, mw, mh, true);
            placed.push(rect);
        });
    }

    function ensureResizeHandles() {
        if (!grid) return;
        grid.querySelectorAll('.dash-widget').forEach((el) => {
            if (el.querySelector('.dash-widget-resize')) return;
            el.insertAdjacentHTML(
                'beforeend',
                `<span class="dash-widget-resize dash-widget-resize--e" data-resize="e" title="${escapeHtml(t('live.resize_width', 'Breite'))}"></span>` +
                `<span class="dash-widget-resize dash-widget-resize--s" data-resize="s" title="${escapeHtml(t('live.resize_height', 'Höhe'))}"></span>` +
                `<span class="dash-widget-resize dash-widget-resize--se" data-resize="se" title="${escapeHtml(t('live.resize_size', 'Größe'))}"></span>`
            );
        });
    }

    function ensureMobileControls() {
        if (!grid) return;
        grid.querySelectorAll('.dash-widget').forEach((el) => {
            if (el.querySelector('.dash-widget-mobile-controls')) {
                updateMobileControlsUI(el);
                return;
            }
            el.insertAdjacentHTML(
                'beforeend',
                `<div class="dash-widget-mobile-controls" data-stop-nav>` +
                    `<button type="button" class="dash-widget-mobile-btn" data-mobile-action="width" title="${escapeHtml(t('live.mobile_width_toggle', 'Breite umschalten'))}" aria-label="${escapeHtml(t('live.mobile_width_toggle', 'Breite umschalten'))}">2/2</button>` +
                    `<div class="dash-widget-mobile-height">` +
                        `<button type="button" class="dash-widget-mobile-btn" data-mobile-action="h-dec" title="${escapeHtml(t('live.mobile_height_decrease', 'Höhe verringern'))}" aria-label="${escapeHtml(t('live.mobile_height_decrease', 'Höhe verringern'))}"><i class="bi bi-dash" aria-hidden="true"></i></button>` +
                        `<span class="dash-widget-mobile-dim">2×2</span>` +
                        `<button type="button" class="dash-widget-mobile-btn" data-mobile-action="h-inc" title="${escapeHtml(t('live.mobile_height_increase', 'Höhe vergrößern'))}" aria-label="${escapeHtml(t('live.mobile_height_increase', 'Höhe vergrößern'))}"><i class="bi bi-plus" aria-hidden="true"></i></button>` +
                    `</div>` +
                `</div>`
            );
            updateMobileControlsUI(el);
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
            ensureMobileControls();
            bindModuleSortable();
        } else {
            destroyModuleSortable();
        }
        scheduleFitWidgetLists();
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
        if (!arrangeMode || !grid || isMobileLayout()) return;
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
        if (placementFits(startGX, startGY, nextW, nextH, id, false)) {
            applyWidgetPlacement(widget, startGX, startGY, nextW, nextH, false);
            resizeState.lastGood = { w: nextW, h: nextH };
            scheduleFitWidgetLists(widget);
        }
    }

    async function onResizePointerUp() {
        if (!resizeState) return;
        const { widget } = resizeState;
        widget.classList.remove('is-resizing');
        resizeState = null;
        scheduleFitWidgetLists(widget);
        try {
            const next = collectWidgetsFromDom();
            await saveConfig({ widgets: next });
        } catch (err) {
            console.error(err);
        }
    }

    function onDragPointerDown(e) {
        if (!arrangeMode || !grid || resizeState) return;
        if (e.target.closest('.dash-widget-resize, .dash-widget-mobile-controls, .dash-widget-settings-btn, a, button, input, textarea, select')) {
            return;
        }
        const mobile = isMobileLayout();
        if (mobile && !e.target.closest('.dash-widget-handle')) {
            return;
        }
        const widget = e.target.closest('.dash-widget[data-widget-id]');
        if (!widget) return;
        // Only primary button / touch
        if (e.button != null && e.button !== 0) return;
        e.preventDefault();
        const startGX = mobile
            ? (parseInt(widget.dataset.mobileGridX, 10) || 1)
            : (parseInt(widget.dataset.gridX, 10) || 1);
        const startGY = mobile
            ? (parseInt(widget.dataset.mobileGridY, 10) || 1)
            : (parseInt(widget.dataset.gridY, 10) || 1);
        const cell = cellFromPoint(e.clientX, e.clientY);
        dragState = {
            widget,
            mobile,
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
        const { widget, mobile, offsetX, offsetY } = dragState;
        const cols = mobile ? 2 : 4;
        const w = mobile
            ? (parseInt(widget.dataset.mobileColSpan, 10) || 2)
            : (parseInt(widget.dataset.colSpan, 10) || 1);
        const h = mobile
            ? (parseInt(widget.dataset.mobileRowSpan, 10) || 2)
            : (parseInt(widget.dataset.rowSpan, 10) || 2);
        const cell = cellFromPoint(e.clientX, e.clientY);
        const nextX = clamp(cell.x - offsetX, 1, cols + 1 - w);
        const nextY = Math.max(1, cell.y - offsetY);
        const id = widget.dataset.widgetId;
        if (placementFits(nextX, nextY, w, h, id, mobile)) {
            applyWidgetPlacement(widget, nextX, nextY, w, h, mobile);
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

    function buildSizePills(field, values, activeValue, labelsMap) {
        return `<div class="dashboard-size-pills" data-size-group="${field}">` +
            values.map((v) => {
                const label = (labelsMap && labelsMap[v]) || String(v);
                const active = Number(activeValue) === v;
                return `<button type="button" class="dashboard-size-pill${active ? ' is-active' : ''}" data-size-field="${field}" data-size-val="${v}" aria-pressed="${active ? 'true' : 'false'}">${escapeHtml(label)}</button>`;
            }).join('') +
            `<input type="hidden" name="${field}" value="${Number(activeValue)}">` +
        `</div>`;
    }

    function buildSizeSection(widget) {
        const activeTab = isMobileLayout() ? 'mobile' : 'desktop';
        const pcW = clamp(parseInt(widget.w, 10) || 1, 1, 4);
        const pcH = clamp(parseInt(widget.h, 10) || 2, 1, 6);
        const mobW = clamp(parseInt(widget.mobile_w, 10) || 2, 1, 2);
        const mobH = clamp(parseInt(widget.mobile_h, 10) || Math.max(2, pcH), 1, 6);
        const mobWLabels = {
            1: t('live.size_half', 'Halb (1/2)'),
            2: t('live.size_full', 'Voll (2/2)'),
        };

        return `
            <div class="dashboard-size-panel">
                <div class="dashboard-size-panel__header">
                    <h6 class="dashboard-size-panel__title">${escapeHtml(t('live.size_section', 'Größe & Layout'))}</h6>
                    <div class="dashboard-size-tabs" role="tablist">
                        <button type="button" class="dashboard-size-tab${activeTab === 'mobile' ? ' is-active' : ''}" data-size-tab="mobile" role="tab" aria-selected="${activeTab === 'mobile' ? 'true' : 'false'}">
                            <i class="bi bi-phone" aria-hidden="true"></i>
                            <span>${escapeHtml(t('live.size_tab_mobile', 'Mobil'))}</span>
                        </button>
                        <button type="button" class="dashboard-size-tab${activeTab === 'desktop' ? ' is-active' : ''}" data-size-tab="desktop" role="tab" aria-selected="${activeTab === 'desktop' ? 'true' : 'false'}">
                            <i class="bi bi-display" aria-hidden="true"></i>
                            <span>${escapeHtml(t('live.size_tab_desktop', 'Desktop (PC)'))}</span>
                        </button>
                    </div>
                </div>
                <div class="dashboard-size-pane${activeTab === 'mobile' ? '' : ' d-none'}" data-size-pane="mobile">
                    <div class="dashboard-size-row">
                        <span class="dashboard-size-row__label">${escapeHtml(t('live.size_width', 'Breite'))}</span>
                        ${buildSizePills('mobile_w', [1, 2], mobW, mobWLabels)}
                    </div>
                    <div class="dashboard-size-row">
                        <span class="dashboard-size-row__label">${escapeHtml(t('live.size_height', 'Höhe'))}</span>
                        ${buildSizePills('mobile_h', [1, 2, 3, 4, 5, 6], mobH)}
                    </div>
                    <p class="dashboard-size-hint">${escapeHtml(t('live.size_mobile_hint', 'Gilt nur für die Smartphone-Ansicht (< 768px) und beeinflusst den PC nicht.'))}</p>
                </div>
                <div class="dashboard-size-pane${activeTab === 'desktop' ? '' : ' d-none'}" data-size-pane="desktop">
                    <div class="dashboard-size-row">
                        <span class="dashboard-size-row__label">${escapeHtml(t('live.size_width', 'Breite'))}</span>
                        ${buildSizePills('w', [1, 2, 3, 4], pcW)}
                    </div>
                    <div class="dashboard-size-row">
                        <span class="dashboard-size-row__label">${escapeHtml(t('live.size_height', 'Höhe'))}</span>
                        ${buildSizePills('h', [1, 2, 3, 4, 5, 6], pcH)}
                    </div>
                    <p class="dashboard-size-hint">${escapeHtml(t('live.size_desktop_hint', 'Gilt nur für die Desktop-Ansicht (≥ 768px) und beeinflusst Mobilgeräte nicht.'))}</p>
                </div>
            </div>
        `;
    }

    function bindSizeSettings() {
        if (!modalBody) return;
        modalBody.querySelectorAll('[data-size-tab]').forEach((tab) => {
            tab.addEventListener('click', () => {
                const target = tab.dataset.sizeTab;
                modalBody.querySelectorAll('[data-size-tab]').forEach((b) => {
                    const active = b === tab;
                    b.classList.toggle('is-active', active);
                    b.setAttribute('aria-selected', active ? 'true' : 'false');
                });
                modalBody.querySelectorAll('[data-size-pane]').forEach((pane) => {
                    pane.classList.toggle('d-none', pane.dataset.sizePane !== target);
                });
            });
        });
        modalBody.querySelectorAll('[data-size-field]').forEach((pill) => {
            pill.addEventListener('click', () => {
                const field = pill.dataset.sizeField;
                const val = pill.dataset.sizeVal;
                const group = pill.closest('[data-size-group]');
                if (!group) return;
                group.querySelectorAll('[data-size-field]').forEach((p) => {
                    const active = p === pill;
                    p.classList.toggle('is-active', active);
                    p.setAttribute('aria-pressed', active ? 'true' : 'false');
                });
                const input = group.querySelector(`input[name="${field}"]`);
                if (input) input.value = val;
            });
        });
    }

    function buildSettingsForm(widget) {
        const type = widget.type;
        let html = `<p class="text-muted small">${escapeHtml((editItems[type] && editItems[type].description) || '')}</p>`;
        html += buildSizeSection(widget);

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
        } else if (type === 'kanban_aenderungen' || type === 'kanban_meine_karten') {
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
        const knownNames = options.contact_names || {};
        const names = {};
        (initialIds || []).forEach((id) => {
            names[id] = knownNames[String(id)] || `#${id}`;
        });
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
        if (modalDialog) modalDialog.classList.remove('modal-lg');
        if (modalBody) modalBody.innerHTML = buildSettingsForm(widget);
        bindSizeSettings();
        const modal = openModal(t('live.settings', 'Widget-Einstellungen'));
        if (modal) modal.show();
        if (widget.type === 'kontakte') {
            bindContactSearch(widget.contact_ids || []);
        }
        if (modalSave) {
            modalSave.classList.remove('d-none');
            modalSave.disabled = false;
            modalSave.textContent = t('live.save', 'Speichern');
        }
    }

    let selectedAddType = null;
    let catalogCategory = 'all';
    let catalogQuery = '';

    async function addWidgetByType(type) {
        if (!type) return;
        const entry = { id: newId(), type, w: 1, h: 2, mobile_w: 2, mobile_h: 2, grid_v: 2 };
        if (type === 'termine') entry.calendar_ids = [];
        if (type === 'kontakte') entry.contact_ids = [];
        if (type === 'emails') entry.mailbox_id = null;
        if (type === 'passwoerter') entry.credential_ids = [];
        if (type === 'kanban_aenderungen' || type === 'kanban_meine_karten') entry.board_ids = [];
        widgets = [...collectWidgetsFromDom(), entry];
        await saveConfig({ widgets });
        window.location.reload();
    }

    function renderCatalogCards(usedOnce) {
        if (!modalBody) return;
        const gridEl = modalBody.querySelector('#dashWidgetCatalogGrid');
        if (!gridEl) return;
        const q = catalogQuery.trim().toLowerCase();
        const allTypes = options.widget_types || [];
        const filtered = allTypes.filter((wt) => {
            if (catalogCategory !== 'all' && wt.category !== catalogCategory) return false;
            if (!q) return true;
            const hay = `${wt.label || ''} ${wt.description || ''} ${wt.category_label || ''} ${wt.type || ''}`.toLowerCase();
            return hay.includes(q);
        });
        if (!filtered.length) {
            gridEl.innerHTML = `<div class="dashboard-catalog-empty text-muted small">${escapeHtml(t('live.catalog_empty', 'Keine passenden Widgets gefunden.'))}</div>`;
            return;
        }
        gridEl.innerHTML = filtered.map((wt) => {
            const isAdded = !!(wt.once && usedOnce.has(wt.type));
            const isSelected = !isAdded && selectedAddType === wt.type;
            const icon = wt.icon || 'bi-grid';
            return `<div class="dashboard-catalog-card${isSelected ? ' is-selected' : ''}${isAdded ? ' is-added' : ''}"
                         role="button"
                         tabindex="${isAdded ? '-1' : '0'}"
                         aria-pressed="${isSelected ? 'true' : 'false'}"
                         aria-disabled="${isAdded ? 'true' : 'false'}"
                         data-widget-type="${escapeHtml(wt.type)}">
                <div class="dashboard-catalog-card__icon" aria-hidden="true">
                    <i class="bi ${escapeHtml(icon)}"></i>
                </div>
                <div class="dashboard-catalog-card__body">
                    <div class="dashboard-catalog-card__top">
                        <strong class="dashboard-catalog-card__title">${escapeHtml(wt.label || wt.type)}</strong>
                        ${isAdded
                            ? `<span class="dashboard-catalog-badge dashboard-catalog-badge--added"><i class="bi bi-check2" aria-hidden="true"></i> ${escapeHtml(t('live.already_added', 'Aktiv'))}</span>`
                            : (wt.configurable
                                ? `<span class="dashboard-catalog-badge dashboard-catalog-badge--cfg" title="${escapeHtml(t('live.configurable_hint', 'Konfigurierbar'))}"><i class="bi bi-sliders" aria-hidden="true"></i></span>`
                                : '')}
                    </div>
                    <p class="dashboard-catalog-card__desc">${escapeHtml(wt.description || '')}</p>
                    <div class="dashboard-catalog-card__meta">
                        <span class="dashboard-catalog-cat">${escapeHtml(wt.category_label || '')}</span>
                        ${!isAdded ? `<button type="button" class="dashboard-catalog-quick-add" data-quick-add="${escapeHtml(wt.type)}" title="${escapeHtml(t('live.quick_add', 'Direkt hinzufügen'))}" aria-label="${escapeHtml(t('live.quick_add', 'Direkt hinzufügen'))}"><i class="bi bi-plus-lg" aria-hidden="true"></i></button>` : ''}
                    </div>
                </div>
            </div>`;
        }).join('');
    }

    function openAddWidget() {
        modalMode = 'add';
        activeWidgetId = null;
        selectedAddType = null;
        catalogCategory = 'all';
        catalogQuery = '';
        if (modalDialog) modalDialog.classList.add('modal-lg');

        const usedOnce = new Set(
            widgets.filter((w) => (options.widget_types || []).find((wt) => wt.type === w.type && wt.once))
                .map((w) => w.type)
        );
        const allTypes = options.widget_types || [];
        const availableCount = allTypes.filter((wt) => !(wt.once && usedOnce.has(wt.type))).length;
        const categories = options.categories || [];

        if (modalBody) {
            if (!allTypes.length || availableCount === 0) {
                modalBody.innerHTML = `<p class="mb-0">${escapeHtml(t('live.all_added', 'Alle verfügbaren Widgets sind bereits hinzugefügt.'))}</p>`;
                if (modalSave) modalSave.classList.add('d-none');
            } else {
                const catPills = [
                    `<button type="button" class="mod-pill-btn mod-pill-btn--sm mod-pill-btn--accent is-active" data-catalog-cat="all">${escapeHtml(t('live.catalog_all', 'Alle'))}</button>`,
                    ...categories.map((c) =>
                        `<button type="button" class="mod-pill-btn mod-pill-btn--sm mod-pill-btn--outline" data-catalog-cat="${escapeHtml(c.key)}">${escapeHtml(c.label)}</button>`
                    ),
                ].join('');

                modalBody.innerHTML = `
                    <div class="dashboard-catalog-toolbar">
                        <label class="mod-search-field dashboard-catalog-search" for="dashWidgetCatalogSearch">
                            <i class="bi bi-search" aria-hidden="true"></i>
                            <input type="search"
                                   id="dashWidgetCatalogSearch"
                                   class="mod-search-input"
                                   placeholder="${escapeHtml(t('live.catalog_search', 'Widgets durchsuchen…'))}"
                                   autocomplete="off"
                                   spellcheck="false">
                        </label>
                        <div class="dashboard-catalog-filters" role="tablist" aria-label="${escapeHtml(t('live.catalog_categories', 'Kategorien'))}">
                            ${catPills}
                        </div>
                    </div>
                    <div class="dashboard-catalog-grid" id="dashWidgetCatalogGrid"></div>
                `;
                renderCatalogCards(usedOnce);

                const searchInput = modalBody.querySelector('#dashWidgetCatalogSearch');
                if (searchInput) {
                    searchInput.addEventListener('input', () => {
                        catalogQuery = searchInput.value || '';
                        renderCatalogCards(usedOnce);
                    });
                }

                modalBody.querySelectorAll('[data-catalog-cat]').forEach((btn) => {
                    btn.addEventListener('click', () => {
                        catalogCategory = btn.dataset.catalogCat || 'all';
                        modalBody.querySelectorAll('[data-catalog-cat]').forEach((b) => {
                            const active = b === btn;
                            b.classList.toggle('is-active', active);
                            b.classList.toggle('mod-pill-btn--accent', active);
                            b.classList.toggle('mod-pill-btn--outline', !active);
                        });
                        renderCatalogCards(usedOnce);
                    });
                });

                const gridEl = modalBody.querySelector('#dashWidgetCatalogGrid');
                if (gridEl) {
                    gridEl.addEventListener('click', async (e) => {
                        const quickBtn = e.target.closest('[data-quick-add]');
                        if (quickBtn) {
                            e.stopPropagation();
                            const wtype = quickBtn.dataset.quickAdd;
                            quickBtn.disabled = true;
                            try {
                                await addWidgetByType(wtype);
                            } catch (err) {
                                console.error(err);
                                quickBtn.disabled = false;
                            }
                            return;
                        }
                        const card = e.target.closest('.dashboard-catalog-card');
                        if (!card || card.classList.contains('is-added')) return;
                        selectedAddType = card.dataset.widgetType || null;
                        gridEl.querySelectorAll('.dashboard-catalog-card').forEach((c) => {
                            const sel = c === card;
                            c.classList.toggle('is-selected', sel);
                            c.setAttribute('aria-pressed', sel ? 'true' : 'false');
                        });
                        if (modalSave) modalSave.disabled = !selectedAddType;
                    });

                    gridEl.addEventListener('dblclick', async (e) => {
                        const card = e.target.closest('.dashboard-catalog-card');
                        if (!card || card.classList.contains('is-added')) return;
                        const wtype = card.dataset.widgetType;
                        if (!wtype) return;
                        try {
                            await addWidgetByType(wtype);
                        } catch (err) {
                            console.error(err);
                        }
                    });
                }

                if (modalSave) {
                    modalSave.classList.remove('d-none');
                    modalSave.disabled = true;
                    modalSave.textContent = t('live.add_selected', 'Hinzufügen');
                }
            }
        }
        const modal = openModal(t('live.add_widget', 'Widget hinzufügen'));
        if (modal) modal.show();
    }

    function readSettingsFromForm(type, base) {
        const next = { ...base };
        const readInt = (name, fallback, min, max) => {
            const inp = modalBody && modalBody.querySelector(`input[name="${name}"]`);
            const parsed = inp ? parseInt(inp.value, 10) : NaN;
            return Number.isNaN(parsed) ? fallback : clamp(parsed, min, max);
        };
        next.w = readInt('w', next.w || 1, 1, 4);
        next.h = readInt('h', next.h || 2, 1, 6);
        next.x = clamp(parseInt(next.x, 10) || 1, 1, 5 - next.w);
        next.mobile_w = readInt('mobile_w', next.mobile_w || 2, 1, 2);
        next.mobile_h = readInt('mobile_h', next.mobile_h || 2, 1, 6);
        next.mobile_x = clamp(parseInt(next.mobile_x, 10) || 1, 1, 3 - next.mobile_w);
        next.grid_v = 2;

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
        } else if (type === 'kanban_aenderungen' || type === 'kanban_meine_karten') {
            next.board_ids = [...modalBody.querySelectorAll('input[name="board_ids"]:checked')]
                .map((el) => parseInt(el.value, 10))
                .filter((n) => !Number.isNaN(n));
        }
        return next;
    }

    async function onModalSave() {
        try {
            if (modalMode === 'add') {
                if (!selectedAddType) return;
                await addWidgetByType(selectedAddType);
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

        grid.addEventListener('click', async (e) => {
            const actionBtn = e.target.closest('[data-mobile-action]');
            if (!actionBtn || !arrangeMode) return;
            e.preventDefault();
            e.stopPropagation();
            const widget = actionBtn.closest('.dash-widget[data-widget-id]');
            if (!widget) return;
            const action = actionBtn.dataset.mobileAction;
            let mw = clamp(parseInt(widget.dataset.mobileColSpan, 10) || 2, 1, 2);
            let mh = clamp(parseInt(widget.dataset.mobileRowSpan, 10) || 2, 1, 6);
            if (action === 'width') {
                mw = mw === 1 ? 2 : 1;
            } else if (action === 'h-dec') {
                mh = clamp(mh - 1, 1, 6);
            } else if (action === 'h-inc') {
                mh = clamp(mh + 1, 1, 6);
            } else {
                return;
            }
            reflowMobileWidgets(widget, mw, mh);
            scheduleFitWidgetLists();
            try {
                const next = collectWidgetsFromDom();
                await saveConfig({ widgets: next });
            } catch (err) {
                console.error(err);
            }
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

        scheduleFitWidgetLists();
        if (typeof ResizeObserver !== 'undefined') {
            const listObserver = new ResizeObserver((entries) => {
                entries.forEach((entry) => {
                    const widget = entry.target.closest('.dash-widget') || entry.target;
                    if (widget && widget.classList.contains('dash-widget')) {
                        scheduleFitWidgetLists(widget);
                    } else {
                        scheduleFitWidgetLists();
                    }
                });
            });
            listObserver.observe(grid);
            grid.querySelectorAll('.dash-widget').forEach((widget) => listObserver.observe(widget));
        }
        window.addEventListener('resize', onWindowResize);
    }

    window.dashboardFitWidgetLists = scheduleFitWidgetLists;

    if (grid) {
        grid.addEventListener('change', async (e) => {
            const cb = e.target.closest('.dash-todo-check');
            if (!cb) return;
            const row = cb.closest('[data-todo-source][data-todo-id]');
            if (!row) return;
            const source = row.dataset.todoSource;
            const itemId = row.dataset.todoId;
            const widget = row.closest('.dash-widget[data-widget-type="todos"]');
            const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
            try {
                const res = await fetch(`/todos/api/items/${source}/${itemId}`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrf,
                    },
                    credentials: 'same-origin',
                    body: JSON.stringify({ is_completed: cb.checked }),
                });
                if (res.ok && cb.checked) {
                    row.remove();
                    if (widget) {
                        const list = widget.querySelector('.dash-widget-list');
                        const badge = widget.querySelector('.dash-widget-badge');
                        const remaining = list ? list.querySelectorAll('[data-todo-id]').length : 0;
                        if (badge) badge.textContent = String(remaining);
                        if (remaining === 0 && list) {
                            const emptyText = widget.dataset.emptyText || '';
                            list.outerHTML = `<div class="dash-widget-empty">${emptyText}</div>`;
                        }
                    }
                }
            } catch (err) {
                cb.checked = !cb.checked;
            }
        });
    }
})();
