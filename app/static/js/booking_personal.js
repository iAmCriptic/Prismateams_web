/**
 * Booking / Personal Module - Interactive Table, Inline Editing & Workflows
 */

(function () {
    'use strict';

    // Globale Referenzen
    const tableEl = document.getElementById('bpTable');
    if (!tableEl && !document.getElementById('bpPublicForm') && !document.getElementById('bpPublicOverview')) {
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
            } else if (fieldType === 'action_accept') {
                openMailPreview(entryId, 'accept');
            } else if (fieldType === 'form_link') {
                copyToClipboard(cell.dataset.url);
            } else if (fieldType !== 'image_upload' && fieldType !== 'file_upload' && fieldType !== 'formula') {
                startTextEdit(cell, entryId, fieldKey, rawValue, fieldType);
            }
        });
    }

    function startTextEdit(cell, entryId, fieldKey, currentValue, fieldType) {
        cell.classList.add('is-editing');
        const input = document.createElement('input');
        input.type = (fieldType === 'counter' || fieldType === 'number') ? 'number' : 'text';
        input.className = 'bp-cell-input';
        input.value = currentValue;

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
            const newVal = input.value.trim();
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
        // Schließe vorherige Popover
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

    async function saveCell(entryId, fieldKey, value, cell, fieldType, badgeColor) {
        try {
            const resp = await fetch(`/booking-personal/api/entry/${entryId}/cell`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ field_key: fieldKey, value: value })
            });
            const data = await resp.json();
            if (data.success) {
                cell.dataset.rawValue = value;
                cell.classList.remove('is-editing');
                renderCellDisplay(cell, value, fieldType, badgeColor);

                // Aktualisiere abhängige Formelfelder (z. B. GESAMT) in derselben Zeile
                if (data.updated_custom_data) {
                    const row = cell.closest('tr');
                    if (row) {
                        for (const [k, v] of Object.entries(data.updated_custom_data)) {
                            const formulaCell = row.querySelector(`.bp-cell-formula[data-field-key="${k}"]`);
                            if (formulaCell) {
                                formulaCell.textContent = v || '€0.00';
                            }
                        }
                    }
                }
            } else {
                alert(data.error || 'Fehler beim Speichern');
            }
        } catch (err) {
            console.error(err);
            alert('Netzwerkfehler beim Speichern.');
        }
    }

    function renderCellDisplay(cell, value, fieldType, badgeColor) {
        if (!value || value === '-') {
            cell.innerHTML = '<span class="bp-cell-empty">-</span>';
            return;
        }

        if (fieldType === 'currency') {
            let num = parseFloat(String(value).replace('€', '').replace(',', '.').trim() || 0);
            cell.innerHTML = `€${num.toFixed(2)}`;
        } else if (fieldType === 'badge_select') {
            const color = badgeColor || cell.dataset.badgeColor || 'secondary';
            cell.innerHTML = `<span class="bp-badge bp-badge-${color}">${escapeHtml(value)}</span>`;
        } else {
            cell.textContent = value;
        }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    function copyToClipboard(text) {
        if (!text) return;
        navigator.clipboard.writeText(text).then(() => {
            showToast('Link in Zwischenablage kopiert!');
        }).catch(() => {
            prompt('Link kopieren:', text);
        });
    }

    function showToast(message) {
        let toast = document.getElementById('bpToast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'bpToast';
            toast.style.cssText = 'position: fixed; bottom: 20px; right: 20px; background: #1e293b; color: #fff; padding: 10px 18px; border-radius: 8px; z-index: 9999; font-size: 0.88rem; box-shadow: 0 4px 6px rgba(0,0,0,0.15); transition: opacity 0.3s ease;';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.style.opacity = '1';
        setTimeout(() => {
            toast.style.opacity = '0';
        }, 2500);
    }

    // -------------------------------------------------------------
    // Global Filter & Suche
    // -------------------------------------------------------------
    const searchInput = document.getElementById('bpSearchInput');
    const statusFilter = document.getElementById('bpStatusFilter');
    const areaFilter = document.getElementById('bpAreaFilter');

    function applyFilters() {
        if (!tableEl) return;
        const q = (searchInput?.value || '').toLowerCase().trim();
        const statusVal = (statusFilter?.value || '').toLowerCase();
        const areaVal = (areaFilter?.value || '').toLowerCase();

        const rows = tableEl.querySelectorAll('tbody tr');
        rows.forEach(row => {
            const rowText = row.textContent.toLowerCase();
            const rowStatus = (row.dataset.status || '').toLowerCase();
            const rowArea = (row.dataset.area || '').toLowerCase();

            const matchesSearch = !q || rowText.includes(q);
            const matchesStatus = !statusVal || rowStatus === statusVal;
            const matchesArea = !areaVal || rowArea === areaVal;

            if (matchesSearch && matchesStatus && matchesArea) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    }

    if (searchInput) searchInput.addEventListener('input', applyFilters);
    if (statusFilter) statusFilter.addEventListener('change', applyFilters);
    if (areaFilter) areaFilter.addEventListener('change', applyFilters);

    // -------------------------------------------------------------
    // Neuen Act hinzufügen
    // -------------------------------------------------------------
    const addActBtn = document.getElementById('bpAddActBtn');
    if (addActBtn) {
        addActBtn.addEventListener('click', async function () {
            const eventId = this.dataset.eventId;
            const name = prompt('Name des Acts / Projekts:', 'Neuer Act');
            if (!name) return;

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
                    alert(data.error || 'Fehler beim Erstellen');
                }
            } catch (err) {
                console.error(err);
                alert('Netzwerkfehler.');
            }
        });
    }

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
            alert('Fehler beim Laden der Details.');
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
                        alert(d.error || 'Fehler beim Speichern');
                    }
                } catch (err) {
                    console.error(err);
                    alert('Netzwerkfehler.');
                }
            };
        }
    }

    // -------------------------------------------------------------
    // E-Mail Vorschau & Senden Modal (Zusage, Absage, Einladung)
    // -------------------------------------------------------------
    window.openMailPreview = async function (entryId, mailType) {
        const modalEl = document.getElementById('bpMailModal');
        if (!modalEl) return;
        const bsModal = new bootstrap.Modal(modalEl);

        try {
            const resp = await fetch(`/booking-personal/api/entry/${entryId}/mail-preview`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ type: mailType })
            });
            const data = await resp.json();
            if (data.success) {
                document.getElementById('bpMailRecipient').value = data.recipient || '';
                document.getElementById('bpMailSubject').value = data.subject || '';
                document.getElementById('bpMailBody').value = data.body || '';
                document.getElementById('bpMailType').value = data.type || mailType;
                document.getElementById('bpMailEntryId').value = entryId;

                const mailboxLabel = document.getElementById('bpMailboxName');
                if (mailboxLabel) mailboxLabel.textContent = data.mailbox_name || '';

                const titleEl = document.getElementById('bpMailModalTitle');
                if (titleEl) {
                    if (mailType === 'accept') titleEl.textContent = 'Zusage per E-Mail versenden';
                    else if (mailType === 'reject') titleEl.textContent = 'Absage per E-Mail versenden';
                    else titleEl.textContent = 'Fragebogen-Einladung versenden';
                }

                bsModal.show();
            } else {
                alert(data.error || 'Fehler beim Laden der E-Mail-Vorschau');
            }
        } catch (err) {
            console.error(err);
            alert('Netzwerkfehler.');
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
                alert('Bitte eine Empfängeradresse eingeben.');
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
                    showToast(data.message || 'E-Mail erfolgreich versendet!');
                    setTimeout(() => window.location.reload(), 1000);
                } else {
                    alert(data.error || 'Fehler beim Senden.');
                    this.disabled = false;
                    this.innerHTML = '<i class="bi bi-send me-1"></i> E-Mail jetzt senden';
                }
            } catch (err) {
                console.error(err);
                alert('Netzwerkfehler beim Senden der E-Mail.');
                this.disabled = false;
                this.innerHTML = '<i class="bi bi-send me-1"></i> E-Mail jetzt senden';
            }
        });
    }

    // -------------------------------------------------------------
    // Zeile löschen
    // -------------------------------------------------------------
    window.deleteEntry = async function (entryId) {
        if (!confirm('Diesen Eintrag wirklich löschen?')) return;
        try {
            const resp = await fetch(`/booking-personal/api/entry/${entryId}/delete`, {
                method: 'POST',
                headers: getHeaders()
            });
            const data = await resp.json();
            if (data.success) {
                const row = document.querySelector(`tr[data-entry-id="${entryId}"]`);
                if (row) row.remove();
                showToast('Eintrag gelöscht.');
            }
        } catch (err) {
            console.error(err);
            alert('Fehler beim Löschen.');
        }
    };

    // -------------------------------------------------------------
    // Vorlagen-Management (Save & Load Templates)
    // -------------------------------------------------------------
    const saveTemplateBtn = document.getElementById('bpSaveTemplateBtn');
    if (saveTemplateBtn) {
        saveTemplateBtn.addEventListener('click', async function () {
            const eventId = this.dataset.eventId;
            const name = prompt('Name für die neue Vorlage eingeben (z. B. "Festival Standard", "Clubnacht"):');
            if (!name) return;

            try {
                const resp = await fetch(`/booking-personal/api/event/${eventId}/save-template`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({ name: name })
                });
                const data = await resp.json();
                if (data.success) {
                    showToast('Vorlage erfolgreich gespeichert!');
                    setTimeout(() => window.location.reload(), 800);
                } else {
                    alert(data.error || 'Fehler beim Speichern der Vorlage.');
                }
            } catch (err) {
                console.error(err);
                alert('Netzwerkfehler.');
            }
        });
    }

    const loadTemplateSelect = document.getElementById('bpLoadTemplateSelect');
    if (loadTemplateSelect) {
        loadTemplateSelect.addEventListener('change', async function () {
            const tmplId = this.value;
            if (!tmplId) return;
            const eventId = this.dataset.eventId;

            if (!confirm('Vorlage laden? Alle Spalten werden gemäß Vorlage überschrieben.')) {
                this.value = '';
                return;
            }

            try {
                const resp = await fetch(`/booking-personal/api/event/${eventId}/load-template`, {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({ template_id: tmplId })
                });
                const data = await resp.json();
                if (data.success) {
                    showToast('Vorlage erfolgreich angewendet!');
                    setTimeout(() => window.location.reload(), 800);
                } else {
                    alert(data.error || 'Fehler beim Laden.');
                }
            } catch (err) {
                console.error(err);
                alert('Netzwerkfehler.');
            }
        });
    }

})();

