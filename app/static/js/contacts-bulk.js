/**
 * Multi-select + bulk actions for contacts (vCard, email-all, share, delete).
 */
(function (window, document) {
    'use strict';

    const selected = new Set(); // contact ids as strings
    let bulkBusy = false;

    function i18n(key, fallback) {
        const bag = window.CONTACTS_BULK_I18N || {};
        return bag[key] || fallback;
    }

    function banner(msg, kind) {
        if (typeof window.showAppBanner === 'function') {
            window.showAppBanner(msg, kind || 'info', { timeout: 6000 });
        } else {
            window.alert(msg);
        }
    }

    function toolbar() {
        return document.getElementById('contactsBulkToolbar');
    }

    function countEl() {
        return document.getElementById('contactsBulkCount');
    }

    function selectedIds() {
        return Array.from(selected).map((id) => parseInt(id, 10)).filter((n) => n > 0);
    }

    function checkboxNodes() {
        return document.querySelectorAll('.files-item-checkbox[data-item-type="contact"]');
    }

    function itemRoot(id) {
        return document.querySelector(
            `.mod-list-row[data-item-type="contact"][data-item-id="${id}"], ` +
            `.contacts-card[data-item-type="contact"][data-item-id="${id}"], ` +
            `[data-item-type="contact"][data-item-id="${id}"]`
        );
    }

    function toggleItem(id, force) {
        const key = String(id);
        const on = force === undefined ? !selected.has(key) : !!force;
        if (on) selected.add(key);
        else selected.delete(key);
        updateSelectionUI();
    }

    function selectAllVisible() {
        checkboxNodes().forEach((cb) => {
            const id = cb.getAttribute('data-item-id');
            if (id) selected.add(String(id));
        });
        updateSelectionUI();
    }

    function deselectAll() {
        selected.clear();
        updateSelectionUI();
    }

    function emailsFromSelection() {
        const emails = [];
        const seen = new Set();
        selectedIds().forEach((id) => {
            const el = document.querySelector(`[data-item-type="contact"][data-item-id="${id}"]`);
            if (!el) return;
            const email = (el.getAttribute('data-contact-email') || '').trim();
            if (!email) return;
            const key = email.toLowerCase();
            if (seen.has(key)) return;
            seen.add(key);
            emails.push(email);
        });
        return emails;
    }

    function contactCardText(id) {
        const el = document.querySelector(`[data-item-type="contact"][data-item-id="${id}"]`);
        if (!el) return '';
        const name = el.getAttribute('data-contact-name') || '';
        const email = el.getAttribute('data-contact-email') || '';
        const phone = el.getAttribute('data-contact-phone') || '';
        const notes = el.getAttribute('data-contact-notes') || '';
        const lines = [name];
        if (email) lines.push(email);
        if (phone) lines.push(phone);
        if (notes) lines.push(notes);
        return lines.filter(Boolean).join('\n');
    }

    function updateSelectionUI() {
        const n = selected.size;
        const bar = toolbar();
        if (bar) bar.style.display = n > 0 ? 'block' : 'none';
        const count = countEl();
        if (count) count.textContent = String(n);

        document.body.classList.toggle('files-has-selection', n > 0);

        checkboxNodes().forEach((cb) => {
            const id = cb.getAttribute('data-item-id');
            if (!id) return;
            const on = selected.has(String(id));
            cb.checked = on;
            const root = cb.closest('.mod-list-row, .contacts-card, [data-item-type="contact"]');
            if (root) root.classList.toggle('is-selected', on);
        });

        const selectAll = document.getElementById('contactsSelectAllCheckbox');
        if (selectAll) {
            const total = checkboxNodes().length;
            selectAll.checked = total > 0 && n >= total;
            selectAll.indeterminate = n > 0 && n < total;
        }

        const mailBtn = document.getElementById('contactsBulkEmailBtn');
        if (mailBtn) {
            const emails = emailsFromSelection();
            mailBtn.disabled = emails.length === 0;
            mailBtn.title = emails.length
                ? i18n('email_all', 'E-Mail an alle')
                : i18n('email_none', 'Keine E-Mail-Adresse in der Auswahl');
        }

        const shareBtn = document.getElementById('contactsBulkShareBtn');
        if (shareBtn) {
            shareBtn.disabled = n !== 1;
            shareBtn.title = n === 1
                ? i18n('share', 'Teilen')
                : i18n('share_one', 'Zum Teilen genau einen Kontakt wählen');
        }
    }

    function setBulkBusy(on) {
        bulkBusy = !!on;
        const bar = toolbar();
        if (!bar) return;
        bar.querySelectorAll('button').forEach((btn) => {
            if (btn.id === 'contactsBulkDeselectBtn') return;
            btn.disabled = on || (btn.id === 'contactsBulkEmailBtn' && emailsFromSelection().length === 0)
                || (btn.id === 'contactsBulkShareBtn' && selected.size !== 1);
        });
    }

    async function postJson(url, body) {
        const res = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            body: JSON.stringify(body || {}),
            credentials: 'same-origin',
        });
        let data = null;
        const ct = res.headers.get('content-type') || '';
        if (ct.includes('application/json')) {
            data = await res.json();
        }
        return { ok: res.ok, status: res.status, data, res };
    }

    async function downloadVcf() {
        const ids = selectedIds();
        if (!ids.length || bulkBusy) return;
        setBulkBusy(true);
        const url = window.CONTACTS_BULK_DOWNLOAD_URL || '/contacts/api/download-vcf';
        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Accept': 'text/vcard, application/json' },
                body: JSON.stringify({ ids }),
                credentials: 'same-origin',
            });
            const ct = res.headers.get('content-type') || '';
            if (!res.ok) {
                let msg = i18n('download_error', 'Download fehlgeschlagen.');
                if (ct.includes('application/json')) {
                    const data = await res.json();
                    if (data && data.error) msg = data.error;
                }
                banner(msg, 'danger');
                return;
            }
            const blob = await res.blob();
            let filename = 'Kontakte.vcf';
            const cd = res.headers.get('Content-Disposition') || '';
            const match = /filename="?([^"]+)"?/i.exec(cd);
            if (match) filename = match[1];
            const a = document.createElement('a');
            const objUrl = URL.createObjectURL(blob);
            a.href = objUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(objUrl), 2000);
            banner(i18n('download_ok', 'Download gestartet.'), 'success');
        } catch (err) {
            console.error(err);
            banner(i18n('download_error', 'Download fehlgeschlagen.'), 'danger');
        } finally {
            setBulkBusy(false);
            updateSelectionUI();
        }
    }

    async function bulkDelete() {
        const ids = selectedIds();
        if (!ids.length || bulkBusy) return;
        const label = (i18n('delete_confirm', 'Wirklich {count} Kontakt(e) löschen?') || '')
            .replace('{count}', String(ids.length));
        const ok = typeof window.ptConfirm === 'function'
            ? await window.ptConfirm(label, { danger: true })
            : window.confirm(label);
        if (!ok) return;

        setBulkBusy(true);
        const url = window.CONTACTS_BULK_DELETE_URL || '/contacts/api/bulk-delete';
        try {
            const result = await postJson(url, { ids });
            if (!result.ok || !result.data || !result.data.success) {
                banner((result.data && (result.data.error || result.data.message))
                    || i18n('delete_error', 'Löschen fehlgeschlagen.'), 'danger');
                return;
            }
            banner(result.data.message || i18n('delete_ok', 'Gelöscht.'), 'success');
            deselectAll();
            setTimeout(() => window.location.reload(), 400);
        } catch (err) {
            console.error(err);
            banner(i18n('delete_error', 'Löschen fehlgeschlagen.'), 'danger');
        } finally {
            setBulkBusy(false);
        }
    }

    function emailAll() {
        const total = selected.size;
        const emails = emailsFromSelection();
        if (!emails.length) {
            banner(i18n('email_none', 'Keine E-Mail-Adresse in der Auswahl'), 'warning');
            return;
        }
        if (emails.length < total) {
            const msg = (i18n('email_partial', '{have} von {total} Empfänger haben eine Adresse') || '')
                .replace('{have}', String(emails.length))
                .replace('{total}', String(total));
            banner(msg, 'info');
        }
        const base = window.CONTACTS_COMPOSE_URL || '/email/compose';
        const url = base + (base.includes('?') ? '&' : '?') + 'to=' + encodeURIComponent(emails.join(', '));
        window.location.href = url;
    }

    function shareSelected() {
        const ids = selectedIds();
        if (ids.length !== 1) {
            banner(i18n('share_one', 'Zum Teilen genau einen Kontakt wählen'), 'warning');
            return;
        }
        const text = contactCardText(ids[0]);
        const modalEl = document.getElementById('contactsShareModal');
        const pre = document.getElementById('contactsSharePreview');
        if (pre) pre.textContent = text;
        if (modalEl && window.bootstrap && bootstrap.Modal) {
            bootstrap.Modal.getOrCreateInstance(modalEl).show();
        } else if (navigator.clipboard && text) {
            navigator.clipboard.writeText(text).then(() => {
                banner(i18n('share_copied', 'Kontaktkarte kopiert'), 'success');
            }).catch(() => banner(i18n('share_copy_error', 'Kopieren fehlgeschlagen.'), 'danger'));
        }
    }

    function copySharePreview() {
        const pre = document.getElementById('contactsSharePreview');
        const text = pre ? pre.textContent : '';
        if (!text) return;
        navigator.clipboard.writeText(text).then(() => {
            banner(i18n('share_copied', 'Kontaktkarte kopiert'), 'success');
        }).catch(() => banner(i18n('share_copy_error', 'Kopieren fehlgeschlagen.'), 'danger'));
    }

    function onCheckboxChange(e) {
        const cb = e.target.closest('.files-item-checkbox[data-item-type="contact"]');
        if (!cb) return;
        e.stopPropagation();
        const id = cb.getAttribute('data-item-id');
        if (!id) return;
        toggleItem(id, cb.checked);
    }

    function onRowClickCapture(e) {
        if (!selected.size) return;
        if (e.target.closest('.files-item-checkbox, .files-select-check, .dropdown, button, a, input, textarea, form')) {
            return;
        }
        const row = e.target.closest(
            'tr.mod-list-row[data-item-type="contact"], .contacts-card[data-item-type="contact"]'
        );
        if (!row) return;
        const id = row.getAttribute('data-item-id');
        if (!id) return;
        e.preventDefault();
        e.stopPropagation();
        toggleItem(id);
    }

    function bind() {
        document.addEventListener('change', (e) => {
            if (e.target && e.target.classList && e.target.classList.contains('files-item-checkbox')) {
                onCheckboxChange(e);
            }
            if (e.target && e.target.id === 'contactsSelectAllCheckbox') {
                if (e.target.checked) selectAllVisible();
                else deselectAll();
            }
        });

        document.addEventListener('click', onRowClickCapture, true);

        const zipBtn = document.getElementById('contactsBulkDownloadBtn');
        if (zipBtn) zipBtn.addEventListener('click', downloadVcf);
        const mailBtn = document.getElementById('contactsBulkEmailBtn');
        if (mailBtn) mailBtn.addEventListener('click', emailAll);
        const shareBtn = document.getElementById('contactsBulkShareBtn');
        if (shareBtn) shareBtn.addEventListener('click', shareSelected);
        const deleteBtn = document.getElementById('contactsBulkDeleteBtn');
        if (deleteBtn) deleteBtn.addEventListener('click', bulkDelete);
        const selectAllBtn = document.getElementById('contactsBulkSelectAllBtn');
        if (selectAllBtn) selectAllBtn.addEventListener('click', selectAllVisible);
        const deselectBtn = document.getElementById('contactsBulkDeselectBtn');
        if (deselectBtn) deselectBtn.addEventListener('click', deselectAll);
        const copyBtn = document.getElementById('contactsShareCopyBtn');
        if (copyBtn) copyBtn.addEventListener('click', copySharePreview);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
    } else {
        bind();
    }

    window.ContactsBulkSelection = {
        clear: deselectAll,
        selectAll: selectAllVisible,
        getSelected: selectedIds,
    };
})(window, document);
