/**
 * Booking Module - Interactive Table, Inline Editing & Custom Fields Manager
 */

(function () {
    'use strict';

    const tableEl = document.getElementById('bpTable');
    if (!tableEl && !document.getElementById('bpPublicForm') && !document.getElementById('bpPublicOverview') && !document.getElementById('bpActDetailContainer') && !document.getElementById('bpSettingsContainer') && !document.getElementById('bpTemplatesContainer')) {
        return;
    }

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

    function getHeaders() {
        return {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        };
    }

    // -------------------------------------------------------------
    // Portal Dialog Helpers (Keine nativen Alerts/Confirms/Prompts)
    // -------------------------------------------------------------
    window.showToast = function (message, type = 'info') {
        let toast = document.getElementById('bpToast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'bpToast';
            toast.style.cssText = 'position: fixed; bottom: 24px; right: 24px; color: #fff; padding: 12px 20px; border-radius: 8px; z-index: 1090; font-size: 0.9rem; font-weight: 500; box-shadow: 0 4px 12px rgba(0,0,0,0.18); transition: opacity 0.25s ease; pointer-events: none;';
            document.body.appendChild(toast);
        }
        if (type === 'error' || type === 'danger') {
            toast.style.background = '#dc2626';
        } else if (type === 'success') {
            toast.style.background = '#16a34a';
        } else {
            toast.style.background = '#1e293b';
        }
        toast.textContent = message;
        toast.style.opacity = '1';
        setTimeout(() => {
            toast.style.opacity = '0';
        }, 2800);
    };

    window.showConfirmModal = function ({ title = 'Bestätigung', message = 'Bist du sicher?', confirmText = 'Bestätigen', confirmClass = 'btn-danger', onConfirm }) {
        const modalEl = document.getElementById('bpConfirmModal');
        if (!modalEl) {
            if (onConfirm) onConfirm();
            return;
        }
        const titleEl = document.getElementById('bpConfirmModalTitle');
        const msgEl = document.getElementById('bpConfirmModalMessage');
        const btnEl = document.getElementById('bpConfirmModalBtn');

        if (titleEl) titleEl.textContent = title;
        if (msgEl) msgEl.innerHTML = message;
        if (btnEl) {
            btnEl.textContent = confirmText;
            btnEl.className = `btn mod-pill-btn ${confirmClass} rounded-pill px-4`;
            btnEl.onclick = function () {
                const modal = bootstrap.Modal.getInstance(modalEl);
                if (modal) modal.hide();
                if (onConfirm) onConfirm();
            };
        }
        const bsModal = new bootstrap.Modal(modalEl);
        bsModal.show();
    };

    window.showPromptModal = function ({ title = 'Eingabe', label = 'Bezeichnung', defaultValue = '', onConfirm }) {
        const modalEl = document.getElementById('bpPromptModal');
        if (!modalEl) return;
        const titleEl = document.getElementById('bpPromptModalTitle');
        const labelEl = document.getElementById('bpPromptModalLabel');
        const inputEl = document.getElementById('bpPromptModalInput');
        const submitBtn = document.getElementById('bpPromptModalSubmitBtn');

        if (titleEl) titleEl.textContent = title;
        if (labelEl) labelEl.textContent = label;
        if (inputEl) inputEl.value = defaultValue;

        const bsModal = new bootstrap.Modal(modalEl);
        if (submitBtn) {
            submitBtn.onclick = function () {
                const val = inputEl ? inputEl.value.trim() : '';
                if (!val) return;
                bsModal.hide();
                if (onConfirm) onConfirm(val);
            };
        }
        bsModal.show();
        setTimeout(() => inputEl && inputEl.focus(), 300);
    };

    window.copyToClipboard = function (text) {
        if (!text) return;
        navigator.clipboard.writeText(text).then(() => {
            showToast('Link in Zwischenablage kopiert!', 'success');
        }).catch(() => {
            showToast('Link konnte nicht kopiert werden.', 'error');
        });
    };

    window.copyApplyUrlDirect = function (url) {
        if (!url) {
            const input = document.getElementById('bpApplyUrlInput');
            url = input ? input.value : '';
        }
        if (!url) return;
        navigator.clipboard.writeText(url).then(() => {
            showToast('Bewerbungslink in Zwischenablage kopiert!', 'success');
        }).catch(() => {
            showToast('Link konnte nicht kopiert werden.', 'error');
        });
    };

    window.copyApplyUrl = function (btn) {
        const input = document.getElementById('bpApplyUrlInput');
        if (!input || !input.value) return;
        navigator.clipboard.writeText(input.value).then(() => {
            showToast('Bewerbungslink in Zwischenablage kopiert!', 'success');
            if (btn) {
                const oldHtml = btn.innerHTML;
                btn.innerHTML = '<i class="bi bi-check-lg text-white"></i>';
                setTimeout(() => { btn.innerHTML = oldHtml; }, 2000);
            }
        }).catch(() => {
            showToast('Link konnte nicht kopiert werden.', 'error');
        });
    };

    // -------------------------------------------------------------
    // Inline-Cell-Editing
    // -------------------------------------------------------------
    if (tableEl) {
        tableEl.addEventListener('click', function (e) {
            const cell = e.target.closest('.bp-cell-editable');
            if (!cell || cell.classList.contains('is-editing')) return;

            const entryId = cell.dataset.entryId;
            const fieldKey = cell.dataset.fieldKey;
            const fieldType = cell.dataset.fieldType;
            const rawValue = cell.dataset.rawValue || '';

            if (fieldType === 'badge_select') {
                openBadgePicker(cell, entryId, fieldKey);
            } else if (fieldType === 'multi_select') {
                openMultiSelectPicker(cell, entryId, fieldKey);
            } else if (fieldType === 'action_accept') {
                openMailPreview(entryId, 'accept');
            } else if (fieldType !== 'image_upload' && fieldType !== 'file_upload' && fieldType !== 'formula' && fieldType !== 'form_link') {
                startTextEdit(cell, entryId, fieldKey, rawValue, fieldType);
            }
        });
    }

    function formatCurrencyValue(val) {
        if (val === null || val === undefined) return '';
        const s = String(val).trim();
        if (!s || s === '-') return '';
        let cleaned = s.replace(/€/g, '').replace(/\s+/g, '');
        if (cleaned.includes('.') && cleaned.includes(',')) {
            if (cleaned.lastIndexOf(',') > cleaned.lastIndexOf('.')) {
                cleaned = cleaned.replace(/\./g, '').replace(',', '.');
            } else {
                cleaned = cleaned.replace(/,/g, '');
            }
        } else if (cleaned.includes(',')) {
            cleaned = cleaned.replace(',', '.');
        }
        const num = parseFloat(cleaned);
        return isNaN(num) ? s : `€${num.toFixed(2)}`;
    }

    function startTextEdit(cell, entryId, fieldKey, currentValue, fieldType) {
        cell.classList.add('is-editing');
        const input = document.createElement('input');
        input.type = (fieldType === 'counter' || fieldType === 'number') ? 'number' : 'text';
        input.className = 'bp-cell-input';
        input.value = fieldType === 'currency'
            ? String(currentValue || '').replace(/€/g, '').trim()
            : currentValue;

        cell.innerHTML = '';
        cell.appendChild(input);
        input.focus();
        if (input.type === 'text') {
            input.select();
        }

        let isSaving = false;
        function save() {
            if (isSaving) return;
            isSaving = true;
            let newVal = input.value.trim();
            if (fieldType === 'currency') {
                newVal = formatCurrencyValue(newVal);
            }
            saveCell(entryId, fieldKey, newVal, cell, fieldType);
        }

        input.addEventListener('blur', save);
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                input.blur();
            } else if (e.key === 'Escape') {
                isSaving = true;
                cell.classList.remove('is-editing');
                renderCellDisplay(cell, currentValue, fieldType);
            }
        });
    }

    function openBadgePicker(cell, entryId, fieldKey) {
        document.querySelectorAll('.bp-popover').forEach(p => p.remove());

        let options = [];
        try {
            options = JSON.parse(cell.dataset.options || '[]');
        } catch (e) {
            options = [];
        }

        if (!options || options.length === 0) return;

        const popover = document.createElement('div');
        popover.className = 'bp-popover shadow-sm';

        options.forEach(opt => {
            const val = typeof opt === 'object' ? opt.value : opt;
            const color = typeof opt === 'object' ? (opt.color || 'secondary') : 'secondary';
            const item = document.createElement('div');
            item.className = 'bp-popover-item';
            item.innerHTML = `<span class="bp-badge bp-badge-${color}">${escapeHtml(val)}</span>`;
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                popover.remove();
                saveCell(entryId, fieldKey, val, cell, 'badge_select', color);
            });
            popover.appendChild(item);
        });

        document.body.appendChild(popover);
        const rect = cell.getBoundingClientRect();
        popover.style.top = (rect.bottom + window.scrollY + 2) + 'px';
        popover.style.left = (rect.left + window.scrollX) + 'px';

        setTimeout(() => {
            function closeOutside(e) {
                if (!popover.contains(e.target)) {
                    popover.remove();
                    document.removeEventListener('click', closeOutside);
                }
            }
            document.addEventListener('click', closeOutside);
        }, 10);
    }

    function openMultiSelectPicker(cell, entryId, fieldKey) {
        document.querySelectorAll('.bp-popover').forEach(p => p.remove());

        let options = [];
        try {
            options = JSON.parse(cell.dataset.options || '[]');
        } catch (e) {
            options = [];
        }

        if (!options || options.length === 0) return;

        let selected = [];
        const raw = cell.dataset.rawValue || '';
        if (raw) {
            try {
                const parsed = JSON.parse(raw);
                selected = Array.isArray(parsed) ? parsed.map(String) : [String(raw)];
            } catch (e) {
                selected = raw.split(',').map(s => s.trim()).filter(Boolean);
            }
        }

        const popover = document.createElement('div');
        popover.className = 'bp-popover bp-multiselect-popover shadow-lg';

        const titleDiv = document.createElement('div');
        titleDiv.className = 'd-flex align-items-center justify-content-between pb-1 mb-2 border-bottom';
        titleDiv.innerHTML = '<span class="small fw-bold text-muted">Auswahl:</span><button type="button" class="btn btn-xs btn-primary rounded-pill px-2.5 py-0.5" id="bpMultiSelectDone">Fertig</button>';
        popover.appendChild(titleDiv);

        const listDiv = document.createElement('div');
        listDiv.className = 'd-flex flex-column gap-1.5';

        options.forEach(opt => {
            const val = typeof opt === 'object' ? opt.value : opt;
            const color = typeof opt === 'object' ? (opt.color || 'primary') : 'primary';
            const isChecked = selected.includes(String(val));

            const item = document.createElement('label');
            item.className = 'd-flex align-items-center gap-2 p-1 rounded-2 cursor-pointer';
            item.style.cursor = 'pointer';
            item.innerHTML = `
                <input type="checkbox" class="form-check-input mt-0 bp-multi-opt" value="${escapeHtml(val)}" ${isChecked ? 'checked' : ''}>
                <span class="bp-badge bp-badge-${color}">${escapeHtml(val)}</span>
            `;
            listDiv.appendChild(item);
        });
        popover.appendChild(listDiv);

        document.body.appendChild(popover);
        const rect = cell.getBoundingClientRect();
        popover.style.top = (rect.bottom + window.scrollY + 2) + 'px';
        popover.style.left = (rect.left + window.scrollX) + 'px';

        let closed = false;
        function saveMulti() {
            if (closed) return;
            closed = true;
            const checkedVals = Array.from(popover.querySelectorAll('.bp-multi-opt:checked')).map(cb => cb.value);
            popover.remove();
            document.removeEventListener('click', closeOutside);
            saveCell(entryId, fieldKey, JSON.stringify(checkedVals), cell, 'multi_select');
        }

        popover.querySelector('#bpMultiSelectDone')?.addEventListener('click', (e) => {
            e.stopPropagation();
            saveMulti();
        });

        function closeOutside(e) {
            if (!popover.contains(e.target) && e.target !== cell && !cell.contains(e.target)) {
                saveMulti();
            }
        }
        setTimeout(() => {
            document.addEventListener('click', closeOutside);
        }, 10);
    }

    async function saveCell(entryId, fieldKey, value, cell, fieldType, badgeColor) {
        try {
            const resp = await fetch(`/booking-personal/api/entry/${entryId}/cell`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ field_key: fieldKey, value: value })
            });
            const data = await resp.json();
            if (data.success) {
                const savedValue = (data.updated_custom_data && Object.prototype.hasOwnProperty.call(data.updated_custom_data, fieldKey))
                    ? data.updated_custom_data[fieldKey]
                    : value;
                cell.dataset.rawValue = savedValue ?? '';
                cell.classList.remove('is-editing');
                renderCellDisplay(cell, savedValue, fieldType, badgeColor);

                if (data.updated_custom_data) {
                    const row = cell.closest('tr');
                    if (row) {
                        const statusFieldKey = tableEl?.dataset.statusFieldKey || 'status_booking';
                        const areaFieldKey = tableEl?.dataset.areaFieldKey || 'bereich';
                        if (fieldKey === statusFieldKey || fieldKey === 'status_booking' || fieldKey === 'status') {
                            row.dataset.status = value || '';
                        }
                        if (fieldKey === areaFieldKey || fieldKey === 'bereich' || fieldKey === 'stage' || fieldKey === 'area' || fieldKey === 'buehne') {
                            const areas = parseAreaValues(value);
                            row.dataset.areas = JSON.stringify(areas);
                            row.dataset.area = areas.join(', ');
                        }
                        if (['project_name', 'auftrittsname_projektname', 'artist_name', 'name'].includes(fieldKey)) {
                            row.dataset.name = value || '';
                        }
                        for (const [k, v] of Object.entries(data.updated_custom_data)) {
                            const formulaCell = row.querySelector(`.bp-cell-formula[data-field-key="${k}"]`);
                            if (formulaCell) {
                                formulaCell.textContent = v || '€0.00';
                            }
                        }
                    }
                }
                applyFiltersAndSort();
            } else {
                showToast(data.error || 'Fehler beim Speichern', 'error');
            }
        } catch (err) {
            console.error(err);
            showToast('Netzwerkfehler beim Speichern.', 'error');
        }
    }

    function renderCellDisplay(cell, value, fieldType, badgeColor) {
        if (!value || value === '-') {
            cell.innerHTML = '<span class="bp-cell-empty">-</span>';
            return;
        }

        if (fieldType === 'currency') {
            const formatted = formatCurrencyValue(value);
            cell.innerHTML = formatted ? escapeHtml(formatted) : '<span class="bp-cell-empty">-</span>';
        } else if (fieldType === 'badge_select') {
            const color = badgeColor || cell.dataset.badgeColor || 'secondary';
            cell.innerHTML = `<span class="bp-badge bp-badge-${color}">${escapeHtml(value)}</span>`;
        } else if (fieldType === 'multi_select') {
            let arr = [];
            if (Array.isArray(value)) {
                arr = value;
            } else {
                try {
                    const parsed = JSON.parse(value);
                    arr = Array.isArray(parsed) ? parsed : [value];
                } catch (e) {
                    arr = String(value).split(',').map(s => s.trim()).filter(Boolean);
                }
            }
            if (!arr || arr.length === 0) {
                cell.innerHTML = '<span class="bp-cell-empty">-</span>';
                return;
            }
            let options = [];
            try { options = JSON.parse(cell.dataset.options || '[]'); } catch (e) {}
            const optMap = {};
            options.forEach(o => {
                if (typeof o === 'object') optMap[o.value] = o.color || 'primary';
                else optMap[o] = 'primary';
            });
            const badgesHtml = arr.map(item => {
                const c = optMap[item] || 'primary';
                return `<span class="bp-badge bp-badge-${c}">${escapeHtml(item)}</span>`;
            }).join(' ');
            cell.innerHTML = `<div class="bp-badge-group">${badgesHtml}</div>`;
        } else {
            cell.textContent = value;
        }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    // -------------------------------------------------------------
    // Filter, Sortierung & Suche
    // -------------------------------------------------------------
    const navSearchInput = document.getElementById('bpSearchInput');
    const navSearchClear = document.getElementById('bpSearchClear');
    const tableSearchInput = document.getElementById('bpTableSearchInput');
    const tableSearchClear = document.getElementById('bpTableSearchClear');
    const dynamicFilters = Array.from(document.querySelectorAll('.bp-dynamic-filter'));
    const sortSelect = document.getElementById('bpSortSelect');

    function getCellRawOrText(row, fieldKey) {
        const td = row.querySelector(`td[data-field-key="${fieldKey}"]`);
        if (!td) return '';
        const editable = td.querySelector('[data-raw-value]');
        if (editable && editable.dataset.rawValue !== undefined) {
            return String(editable.dataset.rawValue).trim();
        }
        const formula = td.querySelector('.bp-cell-formula');
        if (formula) {
            return formula.textContent.trim();
        }
        const boolToggle = td.querySelector('.bp-cell-boolean-toggle');
        if (boolToggle) {
            return boolToggle.checked ? 'Ja' : 'Nein';
        }
        const txt = td.textContent.trim();
        return txt === '-' ? '' : txt;
    }

    function parseAreaValues(raw) {
        if (!raw) return [];
        if (Array.isArray(raw)) {
            return raw.map(v => String(v).trim()).filter(v => v && v !== '-');
        }
        const str = String(raw).trim();
        if (!str || str === '-') return [];
        if (str.startsWith('[') && str.endsWith(']')) {
            try {
                const parsed = JSON.parse(str);
                if (Array.isArray(parsed)) {
                    return parsed.map(v => String(v).trim()).filter(v => v && v !== '-');
                }
            } catch (e) {
                // Fallback zu normalem String
            }
        }
        return str.split(',').map(v => v.trim()).filter(v => v && v !== '-');
    }

    function getRowAreas(row) {
        if (row.dataset.areas) {
            return parseAreaValues(row.dataset.areas);
        }
        return parseAreaValues(row.dataset.area || '');
    }

    function getRowTotal(row) {
        const gesamtCell = row.querySelector('.bp-cell-formula[data-field-key="gesamt"]');
        return gesamtCell ? parseCurrencyVal(gesamtCell.textContent) : 0;
    }

    function getSearchQuery() {
        return ((tableSearchInput?.value ?? navSearchInput?.value) || '').toLowerCase().trim();
    }

    function syncSearchInputs(value, sourceEl) {
        if (navSearchInput && sourceEl !== navSearchInput) {
            navSearchInput.value = value;
        }
        if (tableSearchInput && sourceEl !== tableSearchInput) {
            tableSearchInput.value = value;
        }
        const hasText = value.trim().length > 0;
        if (navSearchClear) navSearchClear.classList.toggle('d-none', !hasText);
        if (tableSearchClear) tableSearchClear.classList.toggle('d-none', !hasText);
    }

    function compareText(a, b) {
        return a.localeCompare(b, 'de', { sensitivity: 'base', numeric: true });
    }

    function applyFiltersAndSort() {
        if (!tableEl) return;
        const tbody = tableEl.querySelector('tbody');
        if (!tbody) return;

        const q = getSearchQuery();
        const activeFilters = dynamicFilters
            .map(sel => ({ key: sel.dataset.fieldKey, val: (sel.value || '').trim().toLowerCase() }))
            .filter(f => f.key && f.val);
        const sortVal = (sortSelect?.value || '').trim();

        const filterIndicator = document.getElementById('bpFilterIndicator');
        const filterBtn = document.getElementById('bpFilterDropdownBtn');
        const hasActiveFilterOrSort = Boolean(activeFilters.length > 0 || sortVal);
        if (filterIndicator) {
            filterIndicator.classList.toggle('d-none', !hasActiveFilterOrSort);
        }
        if (filterBtn) {
            filterBtn.classList.toggle('mod-pill-btn--accent', hasActiveFilterOrSort);
            filterBtn.classList.toggle('mod-pill-btn--outline', !hasActiveFilterOrSort);
        }

        const rows = Array.from(tbody.querySelectorAll('tr[data-entry-id]'));

        rows.sort((a, b) => {
            if (!sortVal) {
                return Number(a.dataset.orderIndex || 0) - Number(b.dataset.orderIndex || 0);
            }
            if (sortVal.startsWith('col:')) {
                const parts = sortVal.split(':');
                const fieldKey = parts[1];
                const dir = parts[2];
                const valA = getCellRawOrText(a, fieldKey);
                const valB = getCellRawOrText(b, fieldKey);
                if (dir === 'num_asc' || dir === 'num_desc') {
                    const diff = parseCurrencyVal(valA) - parseCurrencyVal(valB);
                    return dir === 'num_asc' ? diff : -diff;
                }
                const cmp = compareText(valA, valB);
                return dir === 'text_asc' ? cmp : -cmp;
            }
            if (sortVal === 'name_asc' || sortVal === 'name_desc') {
                const cmp = compareText((a.dataset.name || '').trim(), (b.dataset.name || '').trim());
                return sortVal === 'name_asc' ? cmp : -cmp;
            }
            if (sortVal === 'status_asc' || sortVal === 'status_desc') {
                const cmp = compareText((a.dataset.status || '').trim(), (b.dataset.status || '').trim());
                return sortVal === 'status_asc' ? cmp : -cmp;
            }
            if (sortVal === 'area_asc' || sortVal === 'area_desc') {
                const areaA = getRowAreas(a)[0] || '';
                const areaB = getRowAreas(b)[0] || '';
                const cmp = compareText(areaA, areaB);
                return sortVal === 'area_asc' ? cmp : -cmp;
            }
            if (sortVal === 'total_desc' || sortVal === 'total_asc') {
                const diff = getRowTotal(a) - getRowTotal(b);
                return sortVal === 'total_asc' ? diff : -diff;
            }
            return Number(a.dataset.orderIndex || 0) - Number(b.dataset.orderIndex || 0);
        });

        const noResultsRow = document.getElementById('bpNoFilterResultsRow');
        let visibleCount = 0;

        rows.forEach(row => {
            tbody.appendChild(row);
            const rowText = row.textContent.toLowerCase();
            const matchesSearch = !q || rowText.includes(q);
            const matchesAllDynamic = activeFilters.every(f => {
                const raw = getCellRawOrText(row, f.key);
                const vals = parseAreaValues(raw).map(v => v.toLowerCase());
                return vals.includes(f.val);
            });

            const isVisible = matchesSearch && matchesAllDynamic;
            row.style.display = isVisible ? '' : 'none';

            if (isVisible) {
                visibleCount += 1;
                const indexCell = row.querySelector('td:first-child');
                if (indexCell) indexCell.textContent = String(visibleCount);
            }
        });

        if (noResultsRow) {
            tbody.appendChild(noResultsRow);
            noResultsRow.classList.toggle('d-none', !(rows.length > 0 && visibleCount === 0));
        }

        updateFinanceFooter();
    }

    if (navSearchInput) {
        navSearchInput.addEventListener('input', function () {
            syncSearchInputs(this.value, this);
            applyFiltersAndSort();
        });
    }
    if (tableSearchInput) {
        tableSearchInput.addEventListener('input', function () {
            syncSearchInputs(this.value, this);
            applyFiltersAndSort();
        });
    }
    if (navSearchClear) {
        navSearchClear.addEventListener('click', function () {
            syncSearchInputs('', null);
            applyFiltersAndSort();
            if (navSearchInput) navSearchInput.focus();
        });
    }
    if (tableSearchClear) {
        tableSearchClear.addEventListener('click', function () {
            syncSearchInputs('', null);
            applyFiltersAndSort();
            if (tableSearchInput) tableSearchInput.focus();
        });
    }

    dynamicFilters.forEach(sel => sel.addEventListener('change', applyFiltersAndSort));
    if (sortSelect) sortSelect.addEventListener('change', applyFiltersAndSort);

    const resetFiltersBtn = document.getElementById('bpResetFiltersBtn');
    if (resetFiltersBtn) {
        resetFiltersBtn.addEventListener('click', function () {
            dynamicFilters.forEach(sel => {
                sel.value = '';
                if (window.InventoryPillSelect) window.InventoryPillSelect.sync(sel);
            });
            if (sortSelect) {
                sortSelect.value = '';
                if (window.InventoryPillSelect) window.InventoryPillSelect.sync(sortSelect);
            }
            applyFiltersAndSort();
        });
    }

    // -------------------------------------------------------------
    // Neuen Act hinzufügen (Über Bootstrap-Modal)
    // -------------------------------------------------------------
    const addActBtn = document.getElementById('bpAddActBtn');
    const confirmAddActBtn = document.getElementById('bpConfirmAddActBtn');
    const addActModalEl = document.getElementById('bpAddActModal');

    if (addActBtn && addActModalEl) {
        addActBtn.addEventListener('click', function () {
            const input = document.getElementById('bpAddActNameInput');
            if (input) input.value = '';
            const modal = new bootstrap.Modal(addActModalEl);
            modal.show();
            setTimeout(() => input && input.focus(), 300);
        });
    }

    if (confirmAddActBtn && addActBtn) {
        confirmAddActBtn.addEventListener('click', async function () {
            const input = document.getElementById('bpAddActNameInput');
            const name = (input ? input.value : '').trim();
            if (!name) return;

            const eventId = addActBtn.dataset.eventId;
            try {
                const resp = await fetch(`/booking-personal/api/event/${eventId}/entry`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({ name: name })
                });
                const data = await resp.json();
                if (data.success) {
                    window.location.reload();
                } else {
                    showToast(data.error || 'Fehler beim Erstellen', 'error');
                }
            } catch (err) {
                console.error(err);
                showToast('Netzwerkfehler.', 'error');
            }
        });
    }

    // -------------------------------------------------------------
    // Zeile / Act löschen (Über Confirm-Modal)
    // -------------------------------------------------------------
    window.deleteEntry = function (entryId) {
        showConfirmModal({
            title: 'Act löschen',
            message: 'Möchtest du diesen Act wirklich aus der Veranstaltung entfernen?',
            confirmText: 'Löschen',
            confirmClass: 'btn-danger',
            onConfirm: async function () {
                try {
                    const resp = await fetch(`/booking-personal/api/entry/${entryId}/delete`, {
                        method: 'POST',
                        headers: getHeaders()
                    });
                    const data = await resp.json();
                    if (data.success) {
                        const row = document.querySelector(`tr[data-entry-id="${entryId}"]`);
                        if (row) row.remove();
                        updateFinanceFooter();
                        showToast('Act erfolgreich gelöscht.', 'info');
                    } else {
                        showToast(data.error || 'Fehler beim Löschen.', 'error');
                    }
                } catch (err) {
                    console.error(err);
                    showToast('Netzwerkfehler beim Löschen.', 'error');
                }
            }
        });
    };

    // -------------------------------------------------------------
    // Veranstaltung löschen
    // -------------------------------------------------------------
    window.confirmDeleteCurrentEvent = function (eventName) {
        showConfirmModal({
            title: 'Veranstaltung unwiderruflich löschen',
            message: `Möchtest du die Veranstaltung <strong>„${escapeHtml(eventName)}“</strong> samt aller Acts und Tabellendaten wirklich löschen?`,
            confirmText: 'Veranstaltung löschen',
            confirmClass: 'btn-danger',
            onConfirm: function () {
                const form = document.querySelector('form[action*="/delete"]');
                if (form) form.submit();
            }
        });
    };

    // -------------------------------------------------------------
    // Detail-Modal ("Öffnen")
    // -------------------------------------------------------------
    window.openEntryDetail = async function (entryId) {
        const modalEl = document.getElementById('bpEntryModal');
        if (!modalEl) return;
        const bsModal = new bootstrap.Modal(modalEl);

        try {
            const resp = await fetch(`/booking-personal/api/entry/${entryId}`);
            const data = await resp.json();
            if (data.success) {
                renderDetailModal(data.entry, data.fields);
                bsModal.show();
            }
        } catch (err) {
            console.error(err);
            showToast('Fehler beim Laden der Details.', 'error');
        }
    };

    function renderDetailModal(entry, fields) {
        const titleEl = document.getElementById('bpDetailModalTitle');
        const bodyEl = document.getElementById('bpDetailModalBody');
        const saveBtn = document.getElementById('bpDetailModalSaveBtn');

        if (titleEl) titleEl.textContent = entry.name || 'Act-Details';

        const custom = entry.custom_data || {};
        let html = `<form id="bpDetailForm" data-entry-id="${entry.id}"><div class="row g-3">`;

        fields.forEach(f => {
            if (f.field_type === 'formula' || f.field_type === 'form_link' || f.field_type === 'action_accept') {
                return;
            }
            const val = custom[f.field_key] || '';
            html += `<div class="col-md-6">
                <label class="form-label small fw-semibold">${escapeHtml(f.label)}</label>`;

            if (f.field_type === 'textarea') {
                html += `<textarea class="form-control form-control-sm" name="${f.field_key}" rows="2">${escapeHtml(val)}</textarea>`;
            } else if (f.field_type === 'badge_select' && f.options && f.options.length > 0) {
                html += `<select class="form-select form-select-sm" name="${f.field_key}">
                    <option value="">-- Keine Angabe --</option>`;
                f.options.forEach(opt => {
                    const optVal = typeof opt === 'object' ? opt.value : opt;
                    const selected = optVal === val ? 'selected' : '';
                    html += `<option value="${escapeHtml(optVal)}" ${selected}>${escapeHtml(optVal)}</option>`;
                });
                html += `</select>`;
            } else if (f.field_type === 'counter' || f.field_type === 'number') {
                html += `<input type="number" class="form-control form-control-sm" name="${f.field_key}" value="${escapeHtml(val)}">`;
            } else if (f.field_type === 'boolean') {
                const isChecked = val === true || ['true', '1', 'ja', 'yes', 'on'].includes(String(val).toLowerCase());
                html += `<div class="form-check form-switch pt-1">
                    <input class="form-check-input" type="checkbox" role="switch" name="${f.field_key}" id="bpDetailField_${f.field_key}" ${isChecked ? 'checked' : ''}>
                    <label class="form-check-label small text-muted" for="bpDetailField_${f.field_key}">Aktiv</label>
                </div>`;
            } else {
                html += `<input type="text" class="form-control form-control-sm" name="${f.field_key}" value="${escapeHtml(val)}">`;
            }
            html += `</div>`;
        });

        html += `</div></form>`;
        if (bodyEl) bodyEl.innerHTML = html;

        if (saveBtn) {
            saveBtn.onclick = async function () {
                const form = document.getElementById('bpDetailForm');
                const formData = new FormData(form);
                const payload = {};
                formData.forEach((v, k) => payload[k] = v);
                form.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    payload[cb.name] = cb.checked;
                });

                try {
                    const resp = await fetch(`/booking-personal/api/entry/${entry.id}/update-all`, {
                        method: 'POST',
                        headers: getHeaders(),
                        body: JSON.stringify(payload)
                    });
                    const d = await resp.json();
                    if (d.success) {
                        window.location.reload();
                    } else {
                        showToast(d.error || 'Fehler beim Speichern', 'error');
                    }
                } catch (err) {
                    console.error(err);
                    showToast('Netzwerkfehler.', 'error');
                }
            };
        }
    }

    // -------------------------------------------------------------
    // Spalten-Manager (Custom Fields)
    // -------------------------------------------------------------
    window.insertFormulaToken = function (inputId, token, isOperator = false) {
        const input = document.getElementById(inputId);
        if (!input) return;
        const val = input.value;
        const start = typeof input.selectionStart === 'number' ? input.selectionStart : val.length;
        const end = typeof input.selectionEnd === 'number' ? input.selectionEnd : val.length;
        const before = val.slice(0, start);
        const after = val.slice(end);
        const trimmedBefore = before.trimEnd();

        let insertText = token;
        if (isOperator) {
            if (['+', '-', '*', '/'].includes(token)) {
                const needLeadSpace = trimmedBefore.length > 0 && !before.endsWith(' ');
                const needTrailSpace = after.length > 0 && !after.startsWith(' ');
                insertText = `${needLeadSpace ? ' ' : ''}${token}${needTrailSpace ? ' ' : ' '}`;
            } else {
                insertText = token;
            }
        } else {
            const lastChar = trimmedBefore.slice(-1);
            const afterBinaryOrOpen = !trimmedBefore || ['+', '-', '*', '/', '('].includes(lastChar);
            if (afterBinaryOrOpen) {
                const needSpace = trimmedBefore.length > 0 && lastChar !== '(' && !before.endsWith(' ');
                insertText = `${needSpace ? ' ' : ''}${token}`;
            } else {
                insertText = ` + ${token}`;
            }
        }

        input.value = before + insertText + after;
        const newPos = before.length + insertText.length;
        input.focus();
        if (typeof input.setSelectionRange === 'function') {
            input.setSelectionRange(newPos, newPos);
        }
    };

    const bpColType = document.getElementById('bpColType');
    if (bpColType) {
        bpColType.addEventListener('change', function () {
            const type = this.value;
            const optGroup = document.getElementById('bpColOptionsGroup');
            const formGroup = document.getElementById('bpColFormulaGroup');
            if (optGroup) optGroup.style.display = (type === 'badge_select' || type === 'multi_select') ? 'block' : 'none';
            if (formGroup) formGroup.style.display = (type === 'formula') ? 'block' : 'none';
        });
    }

    const COLUMN_PRESETS = {
        'status': {
            label: 'Booking Status',
            label_en: 'Booking Status',
            type: 'badge_select',
            category: 'Stammdaten & Status',
            options: [
                { value: 'Angefragt', color: 'secondary' },
                { value: 'Bewerbung eingegangen', color: 'info' },
                { value: 'Formular gesendet', color: 'primary' },
                { value: 'Formular ausgefüllt', color: 'purple' },
                { value: 'Zusage gesendet', color: 'success' },
                { value: 'Abgeschlossen', color: 'success' },
                { value: 'Rechnung weitergeleitet', color: 'warning' },
                { value: 'Absage', color: 'danger' }
            ],
            is_external: false,
            overview: false
        },
        'bereich': {
            label: 'Bereich',
            label_en: 'Area / Stage',
            type: 'badge_select',
            category: 'Stammdaten & Status',
            options: [
                { value: 'Main Stage', color: 'primary' },
                { value: 'Ambient', color: 'info' },
                { value: 'Mühle', color: 'warning' },
                { value: 'Workshop', color: 'success' }
            ],
            is_external: false,
            overview: true
        },
        'multi_select': {
            label: 'Aufgaben / Tags',
            label_en: 'Tasks / Tags',
            type: 'multi_select',
            category: 'Allgemein',
            options: [
                { value: 'Soundcheck', color: 'primary' },
                { value: 'Catering', color: 'success' },
                { value: 'Hotel gebucht', color: 'info' },
                { value: 'Fahrservice', color: 'warning' }
            ],
            is_external: false,
            overview: true
        },
        'form_link': {
            label: 'Formular-Link',
            label_en: 'Form Link',
            type: 'form_link',
            category: 'Aktionen & Links',
            options: [],
            is_external: false,
            overview: false
        },
        'action_accept': {
            label: 'Zusage senden',
            label_en: 'Send Confirmation',
            type: 'action_accept',
            category: 'Aktionen & Links',
            options: [],
            is_external: false,
            overview: false
        },
        'gage': {
            label: 'Gage (€)',
            label_en: 'Fee (€)',
            type: 'currency',
            category: 'Finanzen',
            options: [],
            is_external: false,
            overview: true
        },
        'steuersatz': {
            label: 'Steuersatz',
            label_en: 'Tax Rate',
            type: 'badge_select',
            category: 'Finanzen',
            options: [
                { value: '0%', color: 'warning' },
                { value: '7%', color: 'info' },
                { value: '19%', color: 'primary' },
                { value: 'Reverse Charge', color: 'secondary' }
            ],
            is_external: false,
            overview: true
        },
        'techrider': {
            label: 'Techrider (PDF)',
            label_en: 'Techrider (PDF)',
            type: 'file_upload',
            category: 'Presse & Technik',
            options: [],
            is_external: true,
            overview: false
        },
        'promo_images': {
            label: 'Promo-Bilder',
            label_en: 'Press Photos',
            type: 'image_upload',
            category: 'Presse & Technik',
            options: [],
            is_external: true,
            overview: false
        },
        'pronoun': {
            label: 'Pronomen',
            label_en: 'Pronouns',
            type: 'text',
            category: 'Stammdaten & Status',
            options: [],
            is_external: true,
            overview: true
        },
        'drinks': {
            label: 'Getränkeguthaben',
            label_en: 'Drink Tokens',
            type: 'counter',
            category: 'Hospitality & Logistik',
            options: [],
            is_external: false,
            overview: true
        },
        'guestlist': {
            label: 'Gästeliste Plätze',
            label_en: 'Guest List Spots',
            type: 'counter',
            category: 'Hospitality & Logistik',
            options: [],
            is_external: true,
            overview: true
        }
    };

    window.applyColPreset = function (key) {
        const p = COLUMN_PRESETS[key];
        if (!p) return;

        const labelEl = document.getElementById('bpColLabel');
        const labelEnEl = document.getElementById('bpColLabelEn');
        const typeEl = document.getElementById('bpColType');
        const catEl = document.getElementById('bpColCategory');
        const widthEl = document.getElementById('bpColWidth');
        const extEl = document.getElementById('bpColIsExternal');
        const overEl = document.getElementById('bpColVisibleOverview');
        const optList = document.getElementById('bpColOptionsList');

        if (labelEl) labelEl.value = p.label;
        if (labelEnEl) labelEnEl.value = p.label_en;
        if (typeEl) typeEl.value = p.type;
        if (catEl) catEl.value = p.category;
        if (widthEl) widthEl.value = ''; // Auto width!
        if (extEl) extEl.checked = p.is_external;
        if (overEl) overEl.checked = p.overview;

        if (optList) {
            optList.innerHTML = '';
            if (p.options && p.options.length > 0) {
                p.options.forEach(opt => addBadgeOptionRow(opt.value, opt.color));
            }
        }

        const isChoice = (p.type === 'badge_select' || p.type === 'multi_select');
        const optGroup = document.getElementById('bpColOptionsGroup');
        const formGroup = document.getElementById('bpColFormulaGroup');
        if (optGroup) optGroup.style.display = isChoice ? 'block' : 'none';
        if (formGroup) formGroup.style.display = (p.type === 'formula') ? 'block' : 'none';
    };

    window.openColumnModal = function (mode, fieldData = null) {
        const modalEl = document.getElementById('bpColumnModal');
        if (!modalEl) return;
        const titleEl = document.getElementById('bpColumnModalTitle');
        const modeEl = document.getElementById('bpColMode');
        const fieldIdEl = document.getElementById('bpColFieldId');

        modeEl.value = mode;
        if (mode === 'add') {
            titleEl.textContent = 'Neue Spalte hinzufügen';
            fieldIdEl.value = '';
            document.getElementById('bpColLabel').value = '';
            document.getElementById('bpColLabelEn').value = '';
            const catEl = document.getElementById('bpColCategory');
            if (catEl) catEl.value = 'Allgemein';
            document.getElementById('bpColType').value = 'text';
            const wEl = document.getElementById('bpColWidth'); if (wEl) wEl.value = '';
            document.getElementById('bpColIsExternal').checked = false;
            document.getElementById('bpColVisibleOverview').checked = true;
            document.getElementById('bpColFormula').value = '';
            document.getElementById('bpColOptionsList').innerHTML = '';
            document.getElementById('bpColOptionsGroup').style.display = 'none';
            document.getElementById('bpColFormulaGroup').style.display = 'none';
        } else if (mode === 'edit' && fieldData) {
            titleEl.textContent = 'Spalte bearbeiten: ' + fieldData.label;
            fieldIdEl.value = fieldData.id;
            document.getElementById('bpColLabel').value = fieldData.label || '';
            document.getElementById('bpColLabelEn').value = fieldData.label_en || '';
            const catEl = document.getElementById('bpColCategory');
            if (catEl) catEl.value = fieldData.category || 'Allgemein';
            document.getElementById('bpColType').value = fieldData.field_type || 'text';
            const wEl = document.getElementById('bpColWidth'); if (wEl) wEl.value = fieldData.width || '';
            document.getElementById('bpColIsExternal').checked = !!fieldData.is_external;
            document.getElementById('bpColVisibleOverview').checked = !!fieldData.visible_in_overview;
            document.getElementById('bpColFormula').value = fieldData.formula_definition || '';

            const optList = document.getElementById('bpColOptionsList');
            optList.innerHTML = '';
            if (fieldData.options && fieldData.options.length > 0) {
                fieldData.options.forEach(opt => {
                    const v = typeof opt === 'object' ? opt.value : opt;
                    const c = typeof opt === 'object' ? opt.color : 'secondary';
                    addBadgeOptionRow(v, c);
                });
            }

            const isChoice = (fieldData.field_type === 'badge_select' || fieldData.field_type === 'multi_select');
            document.getElementById('bpColOptionsGroup').style.display = isChoice ? 'block' : 'none';
            document.getElementById('bpColFormulaGroup').style.display = (fieldData.field_type === 'formula') ? 'block' : 'none';
        }

        const bsModal = new bootstrap.Modal(modalEl);
        bsModal.show();
    };

    window.addBadgeOptionRow = function (val = '', color = 'secondary') {
        const list = document.getElementById('bpColOptionsList');
        if (!list) return;
        const row = document.createElement('div');
        row.className = 'd-flex gap-2 align-items-center';
        row.innerHTML = `
            <input type="text" class="form-control form-control-sm bp-badge-val" placeholder="Wert (z. B. Angenommen)" value="${escapeHtml(val)}" required>
            <select class="form-select form-select-sm w-auto bp-badge-color">
                <option value="primary" ${color === 'primary' ? 'selected' : ''}>Blau</option>
                <option value="info" ${color === 'info' ? 'selected' : ''}>Hellblau</option>
                <option value="success" ${color === 'success' ? 'selected' : ''}>Grün</option>
                <option value="warning" ${color === 'warning' ? 'selected' : ''}>Gelb</option>
                <option value="danger" ${color === 'danger' ? 'selected' : ''}>Rot</option>
                <option value="purple" ${color === 'purple' ? 'selected' : ''}>Lila</option>
                <option value="pink" ${color === 'pink' ? 'selected' : ''}>Pink</option>
                <option value="dark" ${color === 'dark' ? 'selected' : ''}>Dunkel</option>
                <option value="secondary" ${color === 'secondary' ? 'selected' : ''}>Grau</option>
            </select>
            <button type="button" class="btn btn-xs btn-link text-danger p-0" onclick="this.closest('div').remove()"><i class="bi bi-x-circle-fill"></i></button>
        `;
        list.appendChild(row);
    };

    const saveColBtn = document.getElementById('bpSaveColumnBtn');
    if (saveColBtn) {
        saveColBtn.addEventListener('click', async function () {
            const mode = document.getElementById('bpColMode').value;
            const fieldId = document.getElementById('bpColFieldId').value;
            const label = document.getElementById('bpColLabel').value.trim();
            const labelEn = document.getElementById('bpColLabelEn').value.trim();
            const category = document.getElementById('bpColCategory')?.value.trim() || 'Allgemein';
            const fieldType = document.getElementById('bpColType').value;
            const wEl = document.getElementById('bpColWidth'); const rawW = wEl ? wEl.value.trim() : '';
            const width = parseInt(rawW, 10) > 0 ? parseInt(rawW, 10) : 0; // 0 = Backend Berechnet automatisch
            const isExternal = document.getElementById('bpColIsExternal').checked;
            const visibleInOverview = document.getElementById('bpColVisibleOverview').checked;
            const formula = document.getElementById('bpColFormula').value.trim();

            if (!label) {
                showToast('Bitte einen Spaltennamen angeben.', 'error');
                return;
            }

            let options = [];
            if (fieldType === 'badge_select' || fieldType === 'multi_select') {
                const optRows = document.querySelectorAll('#bpColOptionsList > div');
                optRows.forEach(r => {
                    const v = r.querySelector('.bp-badge-val').value.trim();
                    const c = r.querySelector('.bp-badge-color').value;
                    if (v) options.push({ value: v, color: c });
                });
            }

            const payload = {
                label: label,
                label_en: labelEn,
                category: category,
                field_type: fieldType,
                width: width,
                is_external: isExternal,
                visible_in_overview: visibleInOverview,
                formula_definition: formula,
                options: options
            };

            const currentEventId = document.getElementById('bpAddActBtn')?.dataset.eventId;
            const url = (mode === 'add')
                ? `/booking-personal/api/event/${currentEventId}/field/add`
                : `/booking-personal/api/field/${fieldId}/update`;

            try {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (data.success) {
                    showToast('Spalte erfolgreich gespeichert!', 'success');
                    setTimeout(() => window.location.reload(), 600);
                } else {
                    showToast(data.error || 'Fehler beim Speichern', 'error');
                }
            } catch (e) {
                console.error(e);
                showToast('Netzwerkfehler.', 'error');
            }
        });
    }

    window.deleteColumnField = function (fieldId, label) {
        showConfirmModal({
            title: 'Spalte löschen',
            message: `Möchtest du die Spalte <strong>„${escapeHtml(label)}“</strong> wirklich aus dieser Veranstaltung löschen?`,
            confirmText: 'Spalte löschen',
            confirmClass: 'btn-danger',
            onConfirm: async function () {
                try {
                    const resp = await fetch(`/booking-personal/api/field/${fieldId}/delete`, {
                        method: 'POST',
                        headers: getHeaders()
                    });
                    const d = await resp.json();
                    if (d.success) {
                        showToast('Spalte gelöscht!', 'info');
                        setTimeout(() => window.location.reload(), 600);
                    } else {
                        showToast(d.error || 'Fehler beim Löschen.', 'error');
                    }
                } catch (e) {
                    console.error(e);
                    showToast('Netzwerkfehler.', 'error');
                }
            }
        });
    };

    window.toggleFieldProperty = async function (fieldId, propName, checked) {
        try {
            const resp = await fetch(`/booking-personal/api/field/${fieldId}/update`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ [propName]: checked })
            });
            const d = await resp.json();
            if (d.success) {
                showToast('Einstellung aktualisiert.', 'success');
            } else {
                showToast(d.error || 'Fehler beim Aktualisieren', 'error');
            }
        } catch (e) {
            console.error(e);
            showToast('Netzwerkfehler.', 'error');
        }
    };

    window.moveColumnOrder = async function (fieldId, delta) {
        const rows = Array.from(document.querySelectorAll('#bpColumnsListBody tr'));
        const currentIndex = rows.findIndex(r => parseInt(r.dataset.fieldId, 10) === fieldId);
        if (currentIndex === -1) return;

        const targetIndex = currentIndex + delta;
        if (targetIndex < 0 || targetIndex >= rows.length) return;

        // Vertausche im DOM
        const currentElem = rows[currentIndex];
        const targetElem = rows[targetIndex];
        if (delta > 0) {
            targetElem.after(currentElem);
        } else {
            targetElem.before(currentElem);
        }

        // Sammle neue Reihenfolge
        const newOrder = Array.from(document.querySelectorAll('#bpColumnsListBody tr')).map(r => parseInt(r.dataset.fieldId, 10));
        const currentEventId = document.getElementById('bpAddActBtn')?.dataset.eventId;

        try {
            const resp = await fetch(`/booking-personal/api/event/${currentEventId}/fields/reorder`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ order: newOrder })
            });
            const d = await resp.json();
            if (d.success) {
                showToast('Reihenfolge gespeichert.', 'info');
            }
        } catch (e) {
            console.error(e);
        }
    };

    // -------------------------------------------------------------
    // Vorlagen-Management (Templates)
    // -------------------------------------------------------------
    const saveAsTmplBtn = document.getElementById('bpSaveAsTemplateBtn');
    if (saveAsTmplBtn) {
        saveAsTmplBtn.addEventListener('click', function () {
            const eventId = this.dataset.eventId;
            showPromptModal({
                title: 'Als Vorlage speichern',
                label: 'Name der neuen Vorlage (z. B. „Clubnacht Minimal“, „Band-Setup“)',
                defaultValue: '',
                onConfirm: async function (tmplName) {
                    try {
                        const resp = await fetch(`/booking-personal/api/event/${eventId}/save-template`, {
                            method: 'POST',
                            headers: getHeaders(),
                            body: JSON.stringify({ name: tmplName })
                        });
                        const data = await resp.json();
                        if (data.success) {
                            showToast('Vorlage erfolgreich gespeichert!', 'success');
                            setTimeout(() => window.location.reload(), 800);
                        } else {
                            showToast(data.error || 'Fehler beim Speichern der Vorlage.', 'error');
                        }
                    } catch (err) {
                        console.error(err);
                        showToast('Netzwerkfehler.', 'error');
                    }
                }
            });
        });
    }

    window.confirmLoadTemplate = function (templateId, templateName) {
        const currentEventId = document.getElementById('bpAddActBtn')?.dataset.eventId;
        showConfirmModal({
            title: 'Vorlage anwenden',
            message: `Möchtest du die Vorlage <strong>„${escapeHtml(templateName)}“</strong> auf diese Veranstaltung anwenden?<br><br><span class="text-danger small">Achtung: Alle Spalten werden gemäß dieser Vorlage neu strukturiert.</span>`,
            confirmText: 'Vorlage jetzt anwenden',
            confirmClass: 'btn-primary',
            onConfirm: async function () {
                try {
                    const resp = await fetch(`/booking-personal/api/event/${currentEventId}/load-template`, {
                        method: 'POST',
                        headers: getHeaders(),
                        body: JSON.stringify({ template_id: templateId })
                    });
                    const d = await resp.json();
                    if (d.success) {
                        showToast('Vorlage erfolgreich geladen!', 'success');
                        setTimeout(() => window.location.reload(), 800);
                    } else {
                        showToast(d.error || 'Fehler beim Laden der Vorlage.', 'error');
                    }
                } catch (e) {
                    console.error(e);
                    showToast('Netzwerkfehler.', 'error');
                }
            }
        });
    };

    window.confirmDeleteTemplate = function (templateId, templateName) {
        showConfirmModal({
            title: 'Vorlage löschen',
            message: `Möchtest du die benutzerdefinierte Vorlage <strong>„${escapeHtml(templateName)}“</strong> wirklich löschen?`,
            confirmText: 'Vorlage löschen',
            confirmClass: 'btn-danger',
            onConfirm: async function () {
                try {
                    const resp = await fetch(`/booking-personal/api/template/${templateId}/delete`, {
                        method: 'POST',
                        headers: getHeaders()
                    });
                    const d = await resp.json();
                    if (d.success) {
                        const item = document.querySelector(`[data-template-id="${templateId}"]`);
                        if (item) item.remove();
                        showToast('Vorlage gelöscht.', 'info');
                    } else {
                        showToast(d.error || 'Fehler beim Löschen.', 'error');
                    }
                } catch (e) {
                    console.error(e);
                    showToast('Netzwerkfehler.', 'error');
                }
            }
        });
    };

    // -------------------------------------------------------------
    // E-Mail Vorschau & Senden Modal (Zusage, Absage, Einladung)
    // -------------------------------------------------------------
    window.openMailPreview = async function (entryId, mailType, lang = 'de') {
        const modalEl = document.getElementById('bpMailModal');
        if (!modalEl) return;
        const bsModal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);

        const currentLangEl = document.getElementById('bpMailCurrentLang');
        if (currentLangEl) currentLangEl.value = lang;

        const btnDe = document.getElementById('bpMailLangBtnDe');
        const btnEn = document.getElementById('bpMailLangBtnEn');
        if (btnDe && btnEn) {
            if (lang === 'en') {
                btnEn.className = 'btn btn-xs rounded-pill px-3 py-1 btn-primary';
                btnDe.className = 'btn btn-xs rounded-pill px-3 py-1 btn-light text-muted';
            } else {
                btnDe.className = 'btn btn-xs rounded-pill px-3 py-1 btn-primary';
                btnEn.className = 'btn btn-xs rounded-pill px-3 py-1 btn-light text-muted';
            }
        }

        try {
            const resp = await fetch(`/booking-personal/api/entry/${entryId}/mail-preview`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ type: mailType, lang: lang })
            });
            const data = await resp.json();
            if (data.success) {
                document.getElementById('bpMailRecipient').value = data.recipient || '';
                document.getElementById('bpMailSubject').value = data.subject || '';
                document.getElementById('bpMailBody').value = data.body || '';
                document.getElementById('bpMailType').value = data.type || mailType;
                document.getElementById('bpMailEntryId').value = entryId;

                const mailboxLabel = document.getElementById('bpMailboxName');
                if (mailboxLabel) mailboxLabel.textContent = data.mailbox_name || 'Standard-Portalabsender';

                const titleEl = document.getElementById('bpMailModalTitle');
                if (titleEl) {
                    if (mailType === 'accept') titleEl.innerHTML = '<i class="bi bi-check2-circle text-success me-2"></i>Zusage per E-Mail versenden';
                    else if (mailType === 'reject') titleEl.innerHTML = '<i class="bi bi-x-circle text-danger me-2"></i>Absage per E-Mail versenden';
                    else titleEl.innerHTML = '<i class="bi bi-send text-info me-2"></i>Fragebogen-Einladung versenden';
                }

                bsModal.show();
            } else {
                showToast(data.error || 'Fehler beim Laden der E-Mail-Vorschau', 'error');
            }
        } catch (err) {
            console.error(err);
            showToast('Netzwerkfehler.', 'error');
        }
    };

    window.switchMailPreviewLang = function (lang) {
        const entryId = document.getElementById('bpMailEntryId')?.value;
        const mailType = document.getElementById('bpMailType')?.value || 'accept';
        if (entryId) {
            openMailPreview(entryId, mailType, lang);
        }
    };

    const sendMailBtn = document.getElementById('bpSendMailBtn');
    if (sendMailBtn) {
        sendMailBtn.addEventListener('click', async function () {
            const entryId = document.getElementById('bpMailEntryId').value;
            const recipient = document.getElementById('bpMailRecipient').value.trim();
            const subject = document.getElementById('bpMailSubject').value.trim();
            const body = document.getElementById('bpMailBody').value;
            const mailType = document.getElementById('bpMailType').value;

            if (!recipient) {
                showToast('Bitte eine Empfängeradresse eingeben.', 'error');
                return;
            }

            this.disabled = true;
            this.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Wird gesendet...';

            try {
                const resp = await fetch(`/booking-personal/api/entry/${entryId}/mail-send`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({
                        recipient: recipient,
                        subject: subject,
                        body: body,
                        type: mailType
                    })
                });
                const data = await resp.json();
                if (data.success) {
                    showToast(data.message || 'E-Mail erfolgreich versendet!', 'success');
                    setTimeout(() => window.location.reload(), 1000);
                } else {
                    showToast(data.error || 'Fehler beim Senden.', 'error');
                    this.disabled = false;
                    this.innerHTML = '<i class="bi bi-send me-1"></i> E-Mail jetzt senden';
                }
            } catch (err) {
                console.error(err);
                showToast('Netzwerkfehler beim Senden der E-Mail.', 'error');
                this.disabled = false;
                this.innerHTML = '<i class="bi bi-send me-1"></i> E-Mail jetzt senden';
            }
        });
    }


    // -------------------------------------------------------------
    // Inline-Editing for Act Detail Overview (Direct click-to-edit)
    // -------------------------------------------------------------
    const actDetailEl = document.getElementById('bpActDetailContainer');
    if (actDetailEl) {
        actDetailEl.addEventListener('click', function (e) {
            // Ignore if clicked on buttons, links, or inputs
            if (e.target.closest('a, button, input, select, textarea, .dropdown-menu, .dropdown-toggle')) {
                return;
            }

            const row = e.target.closest('.bp-detail-field-row');
            if (!row) return;

            const entryId = row.dataset.entryId;
            const fieldKey = row.dataset.fieldKey;
            const fieldType = row.dataset.fieldType;
            const rawVal = row.dataset.rawValue || '';

            // Ignore non-editable types or formula fields
            if (['formula', 'file_upload', 'image_upload', 'form_link', 'action_accept'].includes(fieldType) || fieldKey === 'gesamt') {
                return;
            }

            if (row.classList.contains('is-editing')) return;
            row.classList.add('is-editing');

            const valContainer = row.querySelector('.bp-field-val-container');
            const displayEl = row.querySelector('.bp-field-display');
            const penEl = row.querySelector('.bp-field-edit-pen');

            if (!valContainer || !displayEl) return;

            displayEl.classList.add('d-none');
            if (penEl) penEl.classList.add('d-none');

            if (fieldType === 'badge_select') {
                let opts = [];
                try {
                    opts = JSON.parse(row.dataset.options || '[]');
                } catch (err) {}
                const select = document.createElement('select');
                select.className = 'form-select form-select-sm mod-pill-input py-0 px-2';
                select.style.fontSize = '0.82rem';
                select.style.width = 'auto';
                select.style.minWidth = '110px';

                const emptyOpt = document.createElement('option');
                emptyOpt.value = '';
                emptyOpt.textContent = '–';
                select.appendChild(emptyOpt);

                opts.forEach(opt => {
                    const optVal = typeof opt === 'object' ? opt.value : opt;
                    const o = document.createElement('option');
                    o.value = optVal;
                    o.textContent = optVal;
                    if (optVal === rawVal) o.selected = true;
                    select.appendChild(o);
                });

                valContainer.appendChild(select);
                select.focus();

                let finished = false;
                async function finishSelect() {
                    if (finished) return;
                    finished = true;
                    const newVal = select.value;
                    select.remove();
                    displayEl.classList.remove('d-none');
                    if (penEl) penEl.classList.remove('d-none');
                    row.classList.remove('is-editing');

                    if (newVal !== rawVal) {
                        await saveDetailInline(entryId, fieldKey, newVal, row, displayEl, fieldType);
                    }
                }

                select.addEventListener('change', finishSelect);
                select.addEventListener('blur', finishSelect);
            } else {
                const wrap = document.createElement('div');
                wrap.className = 'd-inline-flex align-items-center gap-1';

                const input = document.createElement('input');
                input.type = (fieldType === 'number' || fieldType === 'counter') ? 'number' : 'text';
                input.className = 'form-control form-control-sm mod-pill-input py-0 px-2';
                input.style.fontSize = '0.82rem';
                input.style.width = '120px';

                let initialText = rawVal;
                if (fieldType === 'currency') {
                    initialText = String(rawVal).replace('€', '').trim();
                }
                input.value = initialText;

                wrap.appendChild(input);
                valContainer.appendChild(wrap);
                input.focus();
                input.select();

                let finished = false;
                async function finishInput() {
                    if (finished) return;
                    finished = true;
                    let newVal = input.value.trim();
                    if (fieldType === 'currency') {
                        newVal = formatCurrencyValue(newVal);
                    }
                    wrap.remove();
                    displayEl.classList.remove('d-none');
                    if (penEl) penEl.classList.remove('d-none');
                    row.classList.remove('is-editing');

                    if (newVal !== rawVal) {
                        await saveDetailInline(entryId, fieldKey, newVal, row, displayEl, fieldType);
                    }
                }

                input.addEventListener('keydown', function (evt) {
                    if (evt.key === 'Enter') {
                        evt.preventDefault();
                        finishInput();
                    } else if (evt.key === 'Escape') {
                        finished = true;
                        wrap.remove();
                        displayEl.classList.remove('d-none');
                        if (penEl) penEl.classList.remove('d-none');
                        row.classList.remove('is-editing');
                    }
                });

                input.addEventListener('blur', finishInput);
            }
        });
    }

    async function saveDetailInline(entryId, fieldKey, value, row, displayEl, fieldType) {
        try {
            const resp = await fetch(`/booking-personal/api/entry/${entryId}/cell`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ field_key: fieldKey, value: value })
            });
            const data = await resp.json();
            if (data.success) {
                row.dataset.rawValue = value;

                // Update visual display
                if (fieldType === 'currency') {
                    const formatted = formatCurrencyValue(value) || '€0.00';
                    row.dataset.rawValue = formatCurrencyValue(value);
                    displayEl.innerHTML = `<span class="fw-semibold text-body small">${escapeHtml(formatted)}</span>`;
                } else if (fieldType === 'badge_select') {
                    if (value) {
                        displayEl.innerHTML = `<span class="badge rounded-pill bg-body-secondary text-body border px-2.5 py-1">${escapeHtml(value)}</span>`;
                    } else {
                        displayEl.innerHTML = '<span class="text-muted small">-</span>';
                    }
                } else if (fieldType === 'counter') {
                    displayEl.innerHTML = `<span class="badge rounded-pill bg-body-secondary text-body border px-2.5 py-0.5 fw-bold small">${escapeHtml(value || '0')}</span>`;
                } else {
                    displayEl.innerHTML = `<span class="text-body small">${escapeHtml(value || '-')}</span>`;
                }

                // If calculated/formula values changed (e.g. gesamt in Finanzen)
                if (data.updated_custom_data) {
                    for (const [k, v] of Object.entries(data.updated_custom_data)) {
                        const targetRow = document.querySelector(`.bp-detail-field-row[data-field-key="${k}"]`);
                        if (targetRow) {
                            targetRow.dataset.rawValue = v;
                            const targetDisp = targetRow.querySelector('.bp-field-display');
                            if (targetDisp) {
                                targetDisp.innerHTML = `<span class="fw-bold text-primary small">${escapeHtml(v || '€0.00')}</span>`;
                            }
                        }
                        if (k === 'gesamt') {
                            const bannerVal = document.getElementById('bpDetailTotalCostVal');
                            if (bannerVal) bannerVal.textContent = v || '€0.00';
                        }
                    }
                }
                showToast('Gespeichert', 'success');
            } else {
                showToast(data.error || 'Fehler beim Speichern', 'error');
            }
        } catch (err) {
            console.error(err);
            showToast('Netzwerkfehler.', 'error');
        }
    }

    // -------------------------------------------------------------
    // Boolean-Toggle-Zellen (z. B. Booking Fee netto)
    // -------------------------------------------------------------
    if (tableEl) {
        tableEl.addEventListener('change', async function (e) {
            const toggle = e.target.closest('.bp-cell-boolean-toggle');
            if (!toggle) return;

            const entryId = toggle.dataset.entryId;
            const fieldKey = toggle.dataset.fieldKey;
            const checked = toggle.checked;
            const label = toggle.parentElement?.querySelector('.bp-boolean-label');
            if (label) label.textContent = checked ? 'Ja' : 'Nein';

            try {
                const resp = await fetch(`/booking-personal/api/entry/${entryId}/cell`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({ field_key: fieldKey, value: checked })
                });
                const data = await resp.json();
                if (data.success && data.updated_custom_data) {
                    const row = toggle.closest('tr');
                    if (row) {
                        for (const [k, v] of Object.entries(data.updated_custom_data)) {
                            const formulaCell = row.querySelector(`.bp-cell-formula[data-field-key="${k}"]`);
                            if (formulaCell) {
                                formulaCell.textContent = v || '€0.00';
                            }
                        }
                    }
                    updateFinanceFooter();
                } else if (!data.success) {
                    toggle.checked = !checked;
                    if (label) label.textContent = !checked ? 'Ja' : 'Nein';
                    showToast(data.error || 'Fehler beim Speichern', 'error');
                }
            } catch (err) {
                console.error(err);
                toggle.checked = !checked;
                if (label) label.textContent = !checked ? 'Ja' : 'Nein';
                showToast('Netzwerkfehler beim Speichern.', 'error');
            }
        });
    }

    // -------------------------------------------------------------
    // Finanz-Fußzeile & Gesamtbudget
    // -------------------------------------------------------------
    function parseCurrencyVal(str) {
        if (!str) return 0;
        const num = parseFloat(String(str).replace('€', '').replace(',', '.').trim());
        return Number.isFinite(num) ? num : 0;
    }

    function parseTaxRatePct(raw) {
        if (!raw) return 0;
        const m = String(raw).match(/(\d+(?:[.,]\d+)?)\s*%/);
        if (!m) return 0;
        const pct = parseFloat(m[1].replace(',', '.'));
        return Number.isFinite(pct) ? pct / 100.0 : 0;
    }

    function updateFinanceFooter() {
        const footer = document.getElementById('bpFinanceFooter');
        if (!footer || !tableEl) return;

        const targetKey = footer.dataset.financeColKey || 'gesamt';
        const rows = tableEl.querySelectorAll('tbody tr[data-entry-id]');
        let artistCount = 0;
        let totalSpent = 0;

        rows.forEach(row => {
            if (row.style.display === 'none') return;
            const status = (row.dataset.status || '').trim().toLowerCase();
            if (status === 'absage') return;

            artistCount += 1;
            if (targetKey === 'gesamt') {
                const gesamtCell = row.querySelector('.bp-cell-formula[data-field-key="gesamt"]');
                if (gesamtCell) {
                    totalSpent += parseCurrencyVal(gesamtCell.textContent);
                }
            } else if (targetKey) {
                const valCell = row.querySelector(`[data-field-key="${targetKey}"]`);
                if (valCell) {
                    let amt = parseCurrencyVal(valCell.dataset.rawValue || valCell.textContent);
                    if (targetKey === 'gage') {
                        const taxCell = row.querySelector('[data-field-key="steuersatz"]');
                        if (taxCell) {
                            const rate = parseTaxRatePct(taxCell.dataset.rawValue || taxCell.textContent);
                            if (rate > 0) amt = amt * (1 + rate);
                        }
                    }
                    totalSpent += amt;
                }
            }
        });

        const countEl = document.getElementById('bpFooterArtistCount');
        const spentEl = document.getElementById('bpFooterTotalSpent');
        const remEl = document.getElementById('bpFooterRemaining');
        const remIcon = document.getElementById('bpFooterRemainingIcon');

        if (countEl) countEl.textContent = String(artistCount);
        if (spentEl) spentEl.textContent = `€${totalSpent.toFixed(2)}`;

        const rawBudget = footer.dataset.totalBudget;
        const hasBudget = rawBudget !== undefined && rawBudget !== '' && !Number.isNaN(parseFloat(rawBudget));
        if (remEl && remIcon) {
            if (!hasBudget) {
                remEl.textContent = 'Kein Budget';
                remEl.className = 'text-muted';
                remIcon.className = 'bi bi-wallet2 text-secondary';
            } else {
                const budgetVal = parseFloat(rawBudget);
                const remaining = budgetVal - totalSpent;
                if (remaining >= 0) {
                    remEl.textContent = `Rest €${remaining.toFixed(2)} (Im Budget)`;
                    remEl.className = 'text-success';
                    remIcon.className = 'bi bi-check-circle-fill text-success';
                } else {
                    remEl.textContent = `Rest €${remaining.toFixed(2)} (Überschritten)`;
                    remEl.className = 'text-danger';
                    remIcon.className = 'bi bi-exclamation-triangle-fill text-danger';
                }
            }
        }

        // Zähler pro Status & Stage/Bereich in der Fußzeile aktualisieren (3 übereinander, dann daneben)
        footer.querySelectorAll('.bp-footer-counts-grid[data-footer-counts-for]').forEach(grid => {
            const key = grid.dataset.footerCountsFor;
            const counts = new Map();
            rows.forEach(row => {
                if (row.style.display === 'none') return;
                const raw = getCellRawOrText(row, key);
                const vals = parseAreaValues(raw);
                vals.forEach(v => {
                    counts.set(v, (counts.get(v) || 0) + 1);
                });
            });
            if (counts.size === 0) {
                grid.innerHTML = '<span class="text-muted">-</span>';
            } else {
                const items = Array.from(counts.entries())
                    .sort((a, b) => b[1] - a[1] || compareText(a[0], b[0]))
                    .map(([label, cnt]) => `<span class="text-nowrap"><span class="text-muted">${escapeHtml(label)}:</span> <strong class="text-body">${cnt}</strong></span>`);
                grid.innerHTML = items.join('');
            }
        });
    }

    const budgetInput = document.getElementById('bpFooterBudgetInput');
    const budgetSaveBtn = document.getElementById('bpFooterBudgetSaveBtn');
    const budgetDisplayBtn = document.getElementById('bpFooterBudgetDisplayBtn');
    const budgetDisplayText = document.getElementById('bpFooterBudgetDisplayText');
    const budgetEditWrap = document.getElementById('bpFooterBudgetEditWrap');
    const financeFooterEl = document.getElementById('bpFinanceFooter');

    function closeBudgetEditMode() {
        if (budgetEditWrap) budgetEditWrap.classList.add('d-none');
        if (budgetDisplayBtn) budgetDisplayBtn.classList.remove('d-none');
    }

    function openBudgetEditMode() {
        if (budgetDisplayBtn) budgetDisplayBtn.classList.add('d-none');
        if (budgetEditWrap) budgetEditWrap.classList.remove('d-none');
        if (budgetInput) {
            budgetInput.focus();
            budgetInput.select();
        }
    }

    async function saveEventBudget() {
        if (!financeFooterEl || !budgetInput) return;
        const eventId = financeFooterEl.dataset.eventId;
        const val = budgetInput.value.trim();
        try {
            const resp = await fetch(`/booking-personal/api/event/${eventId}/budget`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ total_budget: val === '' ? null : val })
            });
            const data = await resp.json();
            if (data.success) {
                const hasBudget = data.total_budget !== null && data.total_budget !== undefined;
                financeFooterEl.dataset.totalBudget = hasBudget ? String(data.total_budget) : '';
                if (hasBudget) {
                    const formatted = Number(data.total_budget).toFixed(2);
                    budgetInput.value = formatted;
                    if (budgetDisplayText) budgetDisplayText.textContent = `€${formatted}`;
                } else {
                    budgetInput.value = '';
                    if (budgetDisplayText) budgetDisplayText.textContent = 'Budget festlegen';
                }
                closeBudgetEditMode();
                updateFinanceFooter();
                showToast('Gesamtbudget gespeichert.', 'success');
            } else {
                showToast(data.error || 'Fehler beim Speichern des Budgets.', 'error');
            }
        } catch (err) {
            console.error(err);
            showToast('Netzwerkfehler beim Speichern des Budgets.', 'error');
        }
    }

    if (budgetDisplayBtn) {
        budgetDisplayBtn.addEventListener('click', openBudgetEditMode);
    }
    if (budgetSaveBtn) {
        budgetSaveBtn.addEventListener('click', saveEventBudget);
    }
    if (budgetInput) {
        budgetInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                saveEventBudget();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                const rawBudget = financeFooterEl?.dataset.totalBudget || '';
                budgetInput.value = rawBudget !== '' ? Number(rawBudget).toFixed(2) : '';
                closeBudgetEditMode();
            }
        });
        budgetInput.addEventListener('blur', function () {
            setTimeout(() => {
                if (document.activeElement !== budgetSaveBtn && budgetEditWrap && !budgetEditWrap.classList.contains('d-none')) {
                    saveEventBudget();
                }
            }, 150);
        });
    }

    updateFinanceFooter();

    // Global Pill-Select Enhancer fuer alle Selects im Modul
    function initPillSelects(root) {
        if (window.InventoryPillSelect) {
            window.InventoryPillSelect.enhanceAll(root || document);
        }
    }
    initPillSelects();

    // Mobile Offcanvas: Links schliessen das Menue sauber
    document.querySelectorAll('#bpMobileNav a[data-bp-dismiss-offcanvas]').forEach(function (link) {
        link.addEventListener('click', function () {
            setTimeout(function () {
                var el = document.getElementById('bpMobileNav');
                if (!el || !window.bootstrap || !bootstrap.Offcanvas) return;
                var oc = bootstrap.Offcanvas.getInstance(el);
                if (oc) oc.hide();
            }, 50);
        });
    });
    document.addEventListener('shown.bs.modal', function (e) {
        initPillSelects(e.target);
    });
    document.addEventListener('shown.bs.dropdown', function (e) {
        initPillSelects(e.target);
    });

})();
