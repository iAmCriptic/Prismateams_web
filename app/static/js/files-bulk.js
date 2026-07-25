/**
 * Multi-select + bulk actions for files browser (ZIP, delete, share, restore).
 */
(function (window, document) {
    'use strict';

    const selected = new Set(); // keys: "file:12" / "folder:34"

    function keyOf(type, id) {
        return String(type) + ':' + String(id);
    }

    function parseKey(key) {
        const i = key.indexOf(':');
        if (i < 0) return null;
        const id = parseInt(key.slice(i + 1), 10);
        if (!id) return null;
        return { type: key.slice(0, i), id };
    }

    function selectedItems() {
        return Array.from(selected).map(parseKey).filter(Boolean);
    }

    function isTrash() {
        return !!window.FILES_IS_TRASH;
    }

    function canShare() {
        return !!(window.FILES_SHARING_ENABLED || window.FILES_DROPBOX_ENABLED);
    }

    function toolbar() {
        return document.getElementById('filesBulkToolbar');
    }

    function countEl() {
        return document.getElementById('filesBulkCount');
    }

    function banner(msg, kind) {
        if (typeof window.showAppBanner === 'function') {
            window.showAppBanner(msg, kind || 'info', { timeout: 6000 });
        } else {
            window.alert(msg);
        }
    }

    function updateSelectionUI() {
        const n = selected.size;
        const bar = toolbar();
        if (bar) bar.style.display = n > 0 ? 'block' : 'none';
        const count = countEl();
        if (count) count.textContent = String(n);

        const shareBtn = document.getElementById('filesBulkShareBtn');
        if (shareBtn) {
            const ok = !isTrash() && canShare() && n === 1;
            shareBtn.disabled = !ok;
            shareBtn.title = ok
                ? 'Freigaben'
                : (n === 1 ? 'Freigaben nicht verfügbar' : 'Freigeben: genau ein Element wählen');
        }

        const zipBtn = document.getElementById('filesBulkZipBtn');
        if (zipBtn) zipBtn.hidden = isTrash();

        const deleteBtn = document.getElementById('filesBulkDeleteBtn');
        const restoreBtn = document.getElementById('filesBulkRestoreBtn');
        const purgeBtn = document.getElementById('filesBulkPurgeBtn');
        if (deleteBtn) deleteBtn.hidden = isTrash();
        if (restoreBtn) restoreBtn.hidden = !isTrash();
        if (purgeBtn) purgeBtn.hidden = !isTrash();

        document.querySelectorAll('.files-item-checkbox').forEach((cb) => {
            const type = cb.getAttribute('data-item-type');
            const id = cb.getAttribute('data-item-id');
            if (!type || !id) return;
            const on = selected.has(keyOf(type, id));
            cb.checked = on;
            const host = cb.closest('[data-item-wrapper], tr.mod-list-row, .files-draggable-item');
            const card = cb.closest('.card.file-item, .card.folder-item') || host;
            if (card) card.classList.toggle('is-selected', on);
            if (host) host.classList.toggle('is-selected', on);
        });

        const selectAll = document.getElementById('filesSelectAllCheckbox');
        if (selectAll) {
            const boxes = visibleCheckboxes();
            const checked = boxes.filter((b) => b.checked).length;
            selectAll.checked = boxes.length > 0 && checked === boxes.length;
            selectAll.indeterminate = checked > 0 && checked < boxes.length;
        }

        document.body.classList.toggle('files-has-selection', n > 0);
    }

    function visibleCheckboxes() {
        return Array.from(document.querySelectorAll('.files-item-checkbox')).filter((cb) => {
            const wrap = cb.closest('[data-item-wrapper], tr.mod-list-row');
            if (!wrap) return true;
            return wrap.offsetParent !== null || wrap.style.display !== 'none';
        });
    }

    function toggleItem(type, id, force) {
        const key = keyOf(type, id);
        const on = force != null ? !!force : !selected.has(key);
        if (on) selected.add(key);
        else selected.delete(key);
        updateSelectionUI();
    }

    function selectAllVisible() {
        visibleCheckboxes().forEach((cb) => {
            const type = cb.getAttribute('data-item-type');
            const id = cb.getAttribute('data-item-id');
            if (type && id) selected.add(keyOf(type, id));
        });
        updateSelectionUI();
    }

    function deselectAll() {
        selected.clear();
        updateSelectionUI();
    }

    async function postJson(url, body) {
        const res = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            credentials: 'same-origin',
            body: JSON.stringify(body),
        });
        const ct = res.headers.get('content-type') || '';
        if (ct.includes('application/json')) {
            const data = await res.json();
            return { ok: res.ok, status: res.status, data };
        }
        return { ok: res.ok, status: res.status, data: null, blob: await res.blob() };
    }

    async function downloadZip() {
        const items = selectedItems();
        if (!items.length) return;
        banner('ZIP wird erstellt…', 'info');
        try {
            const res = await fetch(window.FILES_BULK_ZIP_URL || '/files/api/download-zip', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/zip, application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'same-origin',
                body: JSON.stringify({ items }),
            });
            const ct = res.headers.get('content-type') || '';
            if (!res.ok || ct.includes('application/json')) {
                let msg = 'ZIP-Download fehlgeschlagen.';
                try {
                    const data = await res.json();
                    if (data && data.error) msg = data.error;
                } catch (e) { /* ignore */ }
                banner(msg, 'danger');
                return;
            }
            const blob = await res.blob();
            let filename = 'Dateien.zip';
            const cd = res.headers.get('content-disposition') || '';
            const m = /filename\*?=(?:UTF-8''|")?([^\";]+)/i.exec(cd);
            if (m) {
                try { filename = decodeURIComponent(m[1].replace(/"/g, '')); } catch (e) { filename = m[1]; }
            }
            const a = document.createElement('a');
            const url = URL.createObjectURL(blob);
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 2000);
            banner('ZIP-Download gestartet.', 'success');
        } catch (err) {
            console.error(err);
            banner('ZIP-Download fehlgeschlagen.', 'danger');
        }
    }

    async function bulkDelete(purge) {
        const items = selectedItems();
        if (!items.length) return;
        const label = purge
            ? `Wirklich ${items.length} Element(e) endgültig löschen?`
            : `Wirklich ${items.length} Element(e) in den Papierkorb legen?`;
        if (!window.confirm(label)) return;

        const url = window.FILES_BULK_DELETE_URL || '/files/api/bulk-delete';
        try {
            const result = await postJson(url, { items, purge: !!purge });
            if (!result.ok || !result.data || !result.data.success) {
                banner((result.data && (result.data.error || result.data.message)) || 'Löschen fehlgeschlagen.', 'danger');
                return;
            }
            banner(result.data.message || 'Gelöscht.', 'success');
            deselectAll();
            setTimeout(() => window.location.reload(), 400);
        } catch (err) {
            console.error(err);
            banner('Löschen fehlgeschlagen.', 'danger');
        }
    }

    async function bulkRestore() {
        const items = selectedItems();
        if (!items.length) return;
        const url = window.FILES_BULK_RESTORE_URL || '/files/api/bulk-restore';
        try {
            const result = await postJson(url, { items });
            if (!result.ok || !result.data || !result.data.success) {
                banner((result.data && (result.data.error || result.data.message)) || 'Wiederherstellen fehlgeschlagen.', 'danger');
                return;
            }
            banner(result.data.message || 'Wiederhergestellt.', 'success');
            deselectAll();
            setTimeout(() => window.location.reload(), 400);
        } catch (err) {
            console.error(err);
            banner('Wiederherstellen fehlgeschlagen.', 'danger');
        }
    }

    function shareSelected() {
        const items = selectedItems();
        if (items.length !== 1) {
            banner('Zum Freigeben genau ein Element wählen.', 'warning');
            return;
        }
        const item = items[0];
        if (typeof window.openShareManagement === 'function') {
            window.openShareManagement(item.type, item.id);
        } else {
            banner('Freigabe-Dialog nicht verfügbar.', 'danger');
        }
    }

    function onCheckboxChange(e) {
        const cb = e.target.closest('.files-item-checkbox');
        if (!cb) return;
        e.stopPropagation();
        const type = cb.getAttribute('data-item-type');
        const id = cb.getAttribute('data-item-id');
        if (!type || !id) return;
        toggleItem(type, id, cb.checked);
    }

    function onCardClickCapture(e) {
        if (!selected.size) return;
        if (e.target.closest('.files-item-checkbox, .files-select-check, .dropdown, button, .files-dnd-handle, input, textarea, form')) {
            return;
        }
        const card = e.target.closest('.card.file-item[data-item-type], .card.folder-item[data-item-type], tr.mod-list-row[data-item-type]');
        if (!card || card.classList.contains('files-inline-create-card')) return;
        const type = card.getAttribute('data-item-type');
        const id = card.getAttribute('data-item-id');
        if (!type || !id) return;
        e.preventDefault();
        e.stopPropagation();
        toggleItem(type, id);
    }

    function bind() {
        document.addEventListener('change', (e) => {
            if (e.target && e.target.classList && e.target.classList.contains('files-item-checkbox')) {
                onCheckboxChange(e);
            }
            if (e.target && e.target.id === 'filesSelectAllCheckbox') {
                if (e.target.checked) selectAllVisible();
                else deselectAll();
            }
        });

        document.addEventListener('click', onCardClickCapture, true);

        const map = [
            ['filesBulkSelectAllBtn', selectAllVisible],
            ['filesBulkDeselectBtn', deselectAll],
            ['filesBulkZipBtn', downloadZip],
            ['filesBulkShareBtn', shareSelected],
            ['filesBulkDeleteBtn', () => bulkDelete(false)],
            ['filesBulkPurgeBtn', () => bulkDelete(true)],
            ['filesBulkRestoreBtn', bulkRestore],
        ];
        map.forEach(([id, fn]) => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('click', (ev) => {
                ev.preventDefault();
                fn();
            });
        });

        updateSelectionUI();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
    } else {
        bind();
    }

    window.FilesBulkSelection = {
        clear: deselectAll,
        selectAll: selectAllVisible,
        getSelected: selectedItems,
    };
})(window, document);
