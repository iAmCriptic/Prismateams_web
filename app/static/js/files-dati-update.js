/**
 * Dati update: upload toast, unified share management, OnlyOffice presence.
 */
(function (window) {
    'use strict';

    const FILES_I18N = window.FILES_I18N || {};
    const CURRENT_FOLDER_ID = window.CURRENT_FOLDER_ID ?? null;

    function shareLabels() {
        return (FILES_I18N.modals && FILES_I18N.modals.share) || {};
    }

    function modeLabel(mode) {
        const L = shareLabels();
        if (mode === 'view') return L.mode_view || 'Betrachten';
        if (mode === 'edit') return L.mode_edit || 'Bearbeiten';
        if (mode === 'dropbox') return L.mode_dropbox || 'Briefkasten';
        return mode;
    }

    function modeChipHtml(mode) {
        const label = modeLabel(mode);
        let cls = 'files-share-chip--view';
        let icon = 'bi-eye';
        if (mode === 'edit') {
            cls = 'files-share-chip--edit';
            icon = 'bi-pencil';
        } else if (mode === 'dropbox') {
            cls = 'files-share-chip--dropbox';
            icon = 'bi-mailbox';
        }
        return `<span class="files-share-chip ${cls}"><i class="bi ${icon}" aria-hidden="true"></i>${escapeHtml(label)}</span>`;
    }

    function shareStatusChipHtml(link) {
        if (!link.enabled) {
            return '<span class="files-share-status files-share-status--off">aus</span>';
        }
        if (link.is_expired) {
            return '<span class="files-share-status files-share-status--expired">abgelaufen</span>';
        }
        return '<span class="files-share-status files-share-status--active">aktiv</span>';
    }

    const MAX_UPLOAD_BYTES = Number(window.FILES_MAX_UPLOAD_BYTES) || (100 * 1024 * 1024);
    const UPLOAD_HISTORY_KEY = 'filesUploadHistoryV1';

    function ensureToastStack() {
        let stack = document.getElementById('filesUploadToastStack');
        if (!stack) {
            stack = document.createElement('div');
            stack.id = 'filesUploadToastStack';
            stack.className = 'files-upload-toast-stack';
            document.body.appendChild(stack);
        }
        return stack;
    }

    function loadUploadHistory() {
        try {
            const raw = sessionStorage.getItem(UPLOAD_HISTORY_KEY);
            const data = raw ? JSON.parse(raw) : null;
            if (!data || !Array.isArray(data.items)) return { items: [], collapsed: true };
            return {
                items: data.items.slice(-40),
                collapsed: data.collapsed !== false,
            };
        } catch (e) {
            return { items: [], collapsed: true };
        }
    }

    function saveUploadHistory(state) {
        try {
            sessionStorage.setItem(UPLOAD_HISTORY_KEY, JSON.stringify({
                items: (state.items || []).slice(-40),
                collapsed: !!state.collapsed,
            }));
        } catch (e) { /* ignore */ }
    }

    function clearUploadHistory() {
        try { sessionStorage.removeItem(UPLOAD_HISTORY_KEY); } catch (e) { /* ignore */ }
    }

    function pluralUploads(n) {
        return n === 1 ? 'Upload' : 'Uploads';
    }

    function normalizeUploadEntries(fileEntries) {
        if (!fileEntries || !fileEntries.length) return [];
        return fileEntries.map((entry) => {
            if (typeof entry === 'string') {
                return { name: entry, size: 0 };
            }
            return {
                name: (entry && entry.name) || 'Datei',
                size: Math.max(0, Number(entry && entry.size) || 0),
            };
        }).filter((e) => e.name);
    }

    function extractUploadFiles(formData) {
        const files = [];
        for (const [key, value] of formData.entries()) {
            if ((key === 'file' || key === 'folder_upload') && value && typeof value === 'object' && typeof value.size === 'number') {
                files.push({
                    name: value.name || 'Datei',
                    size: value.size,
                });
            }
        }
        return files;
    }

    /** Persistentes Upload-Panel unten rechts (Verlauf, Collapse, Schließen). */
    function getUploadPanel() {
        const stack = ensureToastStack();
        let el = document.getElementById('filesUploadPanel');
        if (el && el._uploadApi) return el._uploadApi;

        // Altes Markup ohne Progress außerhalb entfernen
        if (el) el.remove();

        el = document.createElement('div');
        el.id = 'filesUploadPanel';
        el.className = 'files-upload-toast files-upload-panel is-collapsed';
        el.setAttribute('role', 'status');
        el.hidden = true;
        el.innerHTML = `
            <div class="files-upload-panel-header">
                <button type="button" class="files-upload-panel-toggle" data-upload-toggle aria-expanded="false" title="Details">
                    <i class="bi bi-chevron-up" aria-hidden="true"></i>
                </button>
                <div class="files-upload-panel-summary" data-upload-summary></div>
                <button type="button" class="files-upload-panel-close" data-upload-close aria-label="Schließen">
                    <i class="bi bi-x-lg" aria-hidden="true"></i>
                </button>
            </div>
            <div class="files-upload-panel-progress" data-upload-progress hidden>
                <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
                    <div class="progress-bar progress-bar-striped progress-bar-animated" style="width:0%"></div>
                </div>
                <div class="files-upload-toast-pct" data-upload-pct>0%</div>
            </div>
            <div class="files-upload-panel-body" data-upload-body hidden>
                <div class="files-upload-panel-list" data-upload-list></div>
            </div>
        `;
        stack.appendChild(el);

        const state = {
            items: [],
            collapsed: true,
            uploading: false,
            batchIds: [],
        };

        const summaryEl = () => el.querySelector('[data-upload-summary]');
        const listEl = () => el.querySelector('[data-upload-list]');
        const bodyEl = () => el.querySelector('[data-upload-body]');
        const progressWrap = () => el.querySelector('[data-upload-progress]');
        const toggleBtn = () => el.querySelector('[data-upload-toggle]');

        function isDoneStatus(status) {
            return status === 'success';
        }

        function canDismissStatus(status) {
            return status === 'success' || status === 'error';
        }

        function removeItem(id) {
            const item = state.items.find((i) => i.id === id);
            if (!item || !canDismissStatus(item.status)) return;
            state.items = state.items.filter((i) => i.id !== id);
            state.batchIds = state.batchIds.filter((bid) => bid !== id);
            if (!state.items.length) {
                hideAndClear();
                return;
            }
            renderList();
            renderSummary();
            persist();
        }

        function paintItemProgress(itemId) {
            const item = state.items.find((i) => i.id === itemId);
            if (!item) return;
            const list = listEl();
            if (!list) return;
            const row = list.querySelector(`[data-item-id="${itemId}"]`);
            if (!row) return;
            const pct = Math.max(0, Math.min(100, Math.round(Number(item.progress) || 0)));
            const bar = row.querySelector('.files-upload-panel-item-bar');
            const pctEl = row.querySelector('.files-upload-panel-item-pct');
            const msgEl = row.querySelector('.files-upload-panel-item-msg');
            if (bar) bar.style.width = pct + '%';
            if (pctEl) pctEl.textContent = pct + '%';
            if (msgEl && item.status === 'uploading') {
                msgEl.hidden = false;
                msgEl.textContent = pct > 0 ? `Wird hochgeladen… ${pct}%` : 'Wird hochgeladen…';
            }
        }

        /** Verteilt Gesamt-Bytes auf die aktuelle Batch (geschätzt nach Dateigröße). */
        function distributeBatchProgress(loaded, total) {
            const batch = state.batchIds
                .map((id) => state.items.find((i) => i.id === id))
                .filter(Boolean);
            if (!batch.length) return;
            const sizes = batch.map((i) => Math.max(0, Number(i.size) || 0));
            const sum = sizes.reduce((a, b) => a + b, 0);
            const overallFrac = (total > 0) ? Math.max(0, Math.min(1, loaded / total)) : 0;

            if (!sum) {
                const pct = Math.round(overallFrac * 100);
                batch.forEach((item) => {
                    item.progress = pct;
                    paintItemProgress(item.id);
                });
                return;
            }

            let cursor = overallFrac * sum;
            batch.forEach((item, idx) => {
                const size = sizes[idx] || 1;
                let pct = 0;
                if (cursor >= size) {
                    pct = 100;
                    cursor -= size;
                } else if (cursor > 0) {
                    pct = Math.min(100, Math.round((cursor / size) * 100));
                    cursor = 0;
                }
                item.progress = pct;
                paintItemProgress(item.id);
            });
        }

        function renderList() {
            const list = listEl();
            if (!list) return;
            list.innerHTML = '';
            state.items.forEach((item) => {
                const row = document.createElement('div');
                const status = item.status || 'pending';
                const pct = Math.max(0, Math.min(100, Math.round(Number(item.progress) || 0)));
                row.className = 'files-upload-panel-item is-' + status;
                row.dataset.itemId = item.id;
                const icon = status === 'success' ? 'bi-check-circle-fill'
                    : status === 'error' ? 'bi-x-circle-fill'
                    : status === 'uploading' ? 'bi-arrow-up-circle-fill'
                    : 'bi-file-earmark';
                const dismissBtn = canDismissStatus(status)
                    ? `<button type="button" class="files-upload-panel-item-dismiss" data-upload-dismiss="${item.id}" aria-label="Entfernen" title="Entfernen"><i class="bi bi-x" aria-hidden="true"></i></button>`
                    : '';
                const itemBar = status === 'uploading'
                    ? `<div class="files-upload-panel-item-progress">
                            <div class="files-upload-panel-item-bar-track">
                                <div class="files-upload-panel-item-bar" style="width:${pct}%"></div>
                            </div>
                            <span class="files-upload-panel-item-pct">${pct}%</span>
                       </div>`
                    : '';
                row.innerHTML = `
                    <i class="bi ${icon}" aria-hidden="true"></i>
                    <div class="files-upload-panel-item-main">
                        <span class="files-upload-panel-item-name"></span>
                        <span class="files-upload-panel-item-msg" hidden></span>
                        ${itemBar}
                    </div>
                    ${dismissBtn}
                `;
                row.querySelector('.files-upload-panel-item-name').textContent = item.name || 'Datei';
                const msgEl = row.querySelector('.files-upload-panel-item-msg');
                if (status === 'error' && item.message) {
                    msgEl.hidden = false;
                    msgEl.textContent = item.message;
                } else if (status === 'success') {
                    msgEl.hidden = false;
                    msgEl.textContent = 'Hochgeladen';
                } else if (status === 'uploading') {
                    msgEl.hidden = false;
                    msgEl.textContent = pct > 0 ? `Wird hochgeladen… ${pct}%` : 'Wird hochgeladen…';
                }
                if (item.message) row.title = item.message;
                list.appendChild(row);
            });
            list.scrollTop = list.scrollHeight;
        }

        function syncProgressVisibility() {
            const prog = progressWrap();
            if (!prog) return;
            // Gesamtbalken nur bei mehreren Dateien / Ordner-Upload
            const multi = state.uploading && state.batchIds.length > 1;
            prog.hidden = !multi;
        }

        function renderSummary() {
            const sum = summaryEl();
            if (!sum) return;
            const total = state.items.length;
            const done = state.items.filter((i) => isDoneStatus(i.status)).length;
            const err = state.items.filter((i) => i.status === 'error').length;
            const uploading = state.uploading || state.items.some((i) => i.status === 'uploading');

            el.classList.remove('is-success', 'is-error', 'is-warning', 'is-uploading');
            if (uploading) {
                el.classList.add('is-uploading');
                if (!sum.dataset.live) {
                    sum.textContent = 'Wird hochgeladen…';
                }
            } else if (total === 0) {
                sum.textContent = '';
                delete sum.dataset.live;
            } else if (done === 0 && err > 0) {
                delete sum.dataset.live;
                sum.textContent = `${err}/${total} ${pluralUploads(total)} fehlgeschlagen`;
                el.classList.add('is-error');
            } else {
                delete sum.dataset.live;
                sum.textContent = `${done}/${total} ${pluralUploads(total)} abgeschlossen`;
                if (err > 0) el.classList.add('is-error');
                else el.classList.add('is-success');
            }
            syncProgressVisibility();
        }

        function applyCollapsed() {
            const body = bodyEl();
            const btn = toggleBtn();
            el.classList.toggle('is-collapsed', state.collapsed);
            // Nur Dateiliste einklappbar — Fortschrittsbalken bleibt unabhängig sichtbar
            if (body) body.hidden = state.collapsed;
            if (btn) {
                btn.setAttribute('aria-expanded', state.collapsed ? 'false' : 'true');
                const icon = btn.querySelector('i');
                if (icon) {
                    icon.className = state.collapsed ? 'bi bi-chevron-up' : 'bi bi-chevron-down';
                }
            }
        }

        function persist() {
            saveUploadHistory({ items: state.items, collapsed: state.collapsed });
        }

        function show() {
            el.hidden = false;
        }

        function hideAndClear() {
            state.items = [];
            state.batchIds = [];
            state.uploading = false;
            clearUploadHistory();
            el.hidden = true;
            const sum = summaryEl();
            if (sum) delete sum.dataset.live;
            renderList();
            renderSummary();
            syncProgressVisibility();
        }

        function setCollapsed(collapsed) {
            state.collapsed = !!collapsed;
            applyCollapsed();
            persist();
        }

        const api = {
            el,
            restore() {
                const saved = loadUploadHistory();
                state.items = saved.items || [];
                state.collapsed = saved.collapsed !== false;
                if (!state.items.length) {
                    el.hidden = true;
                    return;
                }
                state.items.forEach((item) => {
                    if (item.status === 'uploading') {
                        item.status = 'error';
                        item.message = item.message || 'Upload unterbrochen';
                    }
                });
                state.uploading = false;
                // Fehler nach Reload sichtbar lassen
                if (state.items.some((i) => i.status === 'error')) {
                    state.collapsed = false;
                }
                // Alte "warning"-Einträge als Erfolg behandeln
                state.items.forEach((item) => {
                    if (item.status === 'warning') item.status = 'success';
                });
                show();
                renderList();
                renderSummary();
                applyCollapsed();
                syncProgressVisibility();
                persist();
            },
            beginBatch(fileEntries) {
                const entries = normalizeUploadEntries(fileEntries);
                const ids = [];
                const stamp = Date.now();
                if (!entries.length) {
                    const id = 'u-' + stamp + '-0';
                    state.items.push({ id, name: 'Upload', status: 'uploading', progress: 0, size: 0 });
                    ids.push(id);
                } else {
                    entries.forEach((entry, idx) => {
                        const id = 'u-' + stamp + '-' + idx + '-' + Math.random().toString(36).slice(2, 6);
                        state.items.push({
                            id,
                            name: entry.name,
                            status: 'uploading',
                            progress: 0,
                            size: entry.size || 0,
                        });
                        ids.push(id);
                    });
                }
                state.batchIds = ids;
                state.uploading = true;
                // Während Upload aufklappen — Einzelbalken sichtbar
                state.collapsed = false;
                show();
                renderList();
                renderSummary();
                applyCollapsed();
                syncProgressVisibility();
                this.setProgress(0);
                const bar = el.querySelector('.progress-bar');
                if (bar) bar.classList.add('progress-bar-animated', 'progress-bar-striped');
                persist();
                return ids;
            },
            setProgress(pct, loaded, total) {
                const n = Math.max(0, Math.min(100, Number(pct) || 0));
                const bar = el.querySelector('.progress-bar');
                const wrap = el.querySelector('[data-upload-progress] .progress');
                const pctEl = el.querySelector('[data-upload-pct]');
                const multi = state.batchIds.length > 1;
                const prog = progressWrap();
                if (prog) prog.hidden = !(state.uploading && multi);
                if (multi) {
                    if (bar) {
                        bar.style.width = n + '%';
                        bar.classList.add('progress-bar-animated', 'progress-bar-striped');
                    }
                    if (wrap) wrap.setAttribute('aria-valuenow', String(Math.round(n)));
                    if (pctEl) pctEl.textContent = Math.round(n) + '%';
                }
                const sum = summaryEl();
                if (sum && state.uploading) {
                    sum.dataset.live = '1';
                    sum.textContent = 'Wird hochgeladen… ' + Math.round(n) + '%';
                }
                if (typeof loaded === 'number' && typeof total === 'number' && total > 0) {
                    distributeBatchProgress(loaded, total);
                } else if (state.batchIds.length) {
                    state.batchIds.forEach((id) => {
                        const item = state.items.find((i) => i.id === id);
                        if (item && item.status === 'uploading') {
                            item.progress = n;
                            paintItemProgress(id);
                        }
                    });
                }
            },
            setIndeterminate(on) {
                const bar = el.querySelector('.progress-bar');
                const multi = state.batchIds.length > 1;
                const prog = progressWrap();
                if (prog) prog.hidden = !(state.uploading && multi);
                if (!bar || !multi) return;
                if (on) {
                    bar.classList.add('progress-bar-animated', 'progress-bar-striped');
                    bar.style.width = '100%';
                }
            },
            setStatus(text) {
                const sum = summaryEl();
                if (sum && text) {
                    sum.dataset.live = '1';
                    sum.textContent = text;
                }
            },
            finishBatch(ok, message, kind) {
                // ok → immer grün (auch bei Info-/Warn-Flash); Fehler → rot
                const status = ok ? 'success' : 'error';
                const ids = state.batchIds.length
                    ? state.batchIds.slice()
                    : state.items.filter((i) => i.status === 'uploading').map((i) => i.id);
                ids.forEach((id) => {
                    const item = state.items.find((i) => i.id === id);
                    if (item) {
                        item.status = status;
                        item.progress = ok ? 100 : (item.progress || 0);
                        if (!ok && message) item.message = message;
                        else if (ok) item.message = 'Hochgeladen';
                    }
                });
                state.batchIds = [];
                state.uploading = false;
                const wasMulti = ids.length > 1;
                const bar = el.querySelector('.progress-bar');
                if (bar) {
                    bar.classList.remove('progress-bar-animated', 'progress-bar-striped');
                    bar.style.width = '100%';
                }
                const pctEl = el.querySelector('[data-upload-pct]');
                if (pctEl) pctEl.textContent = '100%';
                const sum = summaryEl();
                if (sum) delete sum.dataset.live;
                const prog = progressWrap();
                if (prog) {
                    if (wasMulti) {
                        prog.hidden = false;
                        setTimeout(() => { prog.hidden = true; }, 450);
                    } else {
                        prog.hidden = true;
                    }
                }
                // Bei Fehler oder mehreren Dateien aufklappen
                if (status === 'error' || ids.length > 1) state.collapsed = false;
                else state.collapsed = true;
                show();
                renderList();
                renderSummary();
                applyCollapsed();
                persist();
            },
            close: hideAndClear,
        };

        const tBtn = toggleBtn();
        if (tBtn) {
            tBtn.addEventListener('click', () => setCollapsed(!state.collapsed));
        }
        const cBtn = el.querySelector('[data-upload-close]');
        if (cBtn) {
            cBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                hideAndClear();
            });
        }
        const list = listEl();
        if (list) {
            list.addEventListener('click', (e) => {
                const btn = e.target.closest('[data-upload-dismiss]');
                if (!btn) return;
                e.preventDefault();
                e.stopPropagation();
                removeItem(btn.getAttribute('data-upload-dismiss'));
            });
        }

        el._uploadApi = api;
        applyCollapsed();
        syncProgressVisibility();
        return api;
    }

    /** Kompatibilität: liefert API ähnlich dem alten Toast. */
    function createUploadToast(fileEntries) {
        const panel = getUploadPanel();
        panel.beginBatch(fileEntries);
        return {
            id: 'filesUploadPanel',
            el: panel.el,
            setProgress(pct, loaded, total) { panel.setProgress(pct, loaded, total); },
            setIndeterminate(on) { panel.setIndeterminate(on); },
            setStatus(text) { panel.setStatus(text); },
            done(ok, message, kind) { panel.finishBatch(ok, message, kind); },
        };
    }

    // Nach Reload Verlauf wiederherstellen (einmalig)
    let uploadPanelRestored = false;
    function restoreUploadPanelOnce() {
        if (uploadPanelRestored) return;
        uploadPanelRestored = true;
        getUploadPanel().restore();
    }
    document.addEventListener('DOMContentLoaded', restoreUploadPanelOnce);
    if (document.readyState !== 'loading') {
        restoreUploadPanelOnce();
    }

    function formatBytes(n) {
        if (n >= 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + ' MB';
        if (n >= 1024) return (n / 1024).toFixed(0) + ' KB';
        return n + ' B';
    }

    function validateFormDataSizes(formData) {
        const tooBig = [];
        for (const [key, value] of formData.entries()) {
            if ((key === 'file' || key === 'folder_upload') && value && typeof value === 'object' && typeof value.size === 'number') {
                if (value.size > MAX_UPLOAD_BYTES) {
                    tooBig.push({
                        name: value.name || 'Datei',
                        size: value.size
                    });
                }
            }
        }
        return tooBig;
    }

    function xhrUpload(url, formData, { onProgress } = {}) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', url);
            xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
            xhr.setRequestHeader('Accept', 'application/json');
            xhr.responseType = 'text';
            let sawProgress = false;
            xhr.upload.onprogress = (evt) => {
                if (!onProgress) return;
                if (evt.lengthComputable && evt.total > 0) {
                    sawProgress = true;
                    const pct = Math.round((evt.loaded / evt.total) * 100);
                    onProgress(pct, false, evt.loaded, evt.total);
                } else {
                    onProgress(null, true);
                }
            };
            xhr.upload.onloadstart = () => {
                if (onProgress) onProgress(1, false, 0, 1);
            };
            xhr.onload = () => {
                let data = null;
                try {
                    data = JSON.parse(xhr.responseText);
                } catch (e) {
                    data = null;
                }
                resolve({
                    ok: xhr.status >= 200 && xhr.status < 300,
                    status: xhr.status,
                    data,
                    text: xhr.responseText,
                    sawProgress
                });
            };
            xhr.onerror = () => reject(new Error('network'));
            xhr.send(formData);
        });
    }

    function pickMessage(messages, categories) {
        const list = Array.isArray(messages) ? messages : [];
        for (const cat of categories) {
            const hit = list.find(m => m && m.category === cat && m.text);
            if (hit) return hit.text;
        }
        return list.map(m => m && m.text).filter(Boolean).join(' · ') || null;
    }

    async function submitUploadFormDataWithToast(formData, fileNames) {
        const i18n = window.FILES_I18N || FILES_I18N || {};
        const msgs = i18n.messages || {};
        const uploadUrl = window.FILES_UPLOAD_URL || '/files/upload';

        const tooBig = validateFormDataSizes(formData);
        if (tooBig.length) {
            const maxLabel = formatBytes(MAX_UPLOAD_BYTES);
            const detail = tooBig.slice(0, 3).map(f => `${f.name} (${formatBytes(f.size)})`).join(', ');
            const msg = `Datei zu groß (max. ${maxLabel}): ${detail}${tooBig.length > 3 ? ' …' : ''}`;
            const panel = getUploadPanel();
            panel.beginBatch(tooBig);
            panel.finishBatch(false, msg, 'error');
            if (typeof window.showAppBanner === 'function') {
                window.showAppBanner(msg, 'danger', { timeout: 8000 });
            }
            return;
        }

        try {
            const resolveConflictStrategy = window.resolveConflictStrategy;
            if (typeof resolveConflictStrategy === 'function') {
                const strategy = await resolveConflictStrategy(fileNames);
                if (strategy === 'cancel') return;
                if (strategy) formData.append('conflict_strategy', strategy);
            }
        } catch (conflictErr) {
            console.error(conflictErr);
            if (typeof window.showAppBanner === 'function') {
                window.showAppBanner(msgs.upload_error || 'Konfliktprüfung fehlgeschlagen.', 'danger');
            }
            return;
        }

        const uploadEntries = extractUploadFiles(formData);
        const toastEntries = uploadEntries.length
            ? uploadEntries
            : normalizeUploadEntries(fileNames);
        const toast = createUploadToast(toastEntries);
        toast.setStatus('Wird hochgeladen…', null);
        try {
            const result = await xhrUpload(uploadUrl, formData, {
                onProgress: (pct, indeterminate, loaded, total) => {
                    if (indeterminate) {
                        toast.setIndeterminate(true);
                        toast.setStatus('Upload läuft…', null);
                    } else if (pct != null) {
                        toast.setProgress(pct, loaded, total);
                        toast.setStatus(`Wird hochgeladen… ${pct}%`, null);
                    }
                }
            });

            if (result.status === 413) {
                const msg = (result.data && (result.data.message || pickMessage(result.data.messages || [], ['danger'])))
                    || 'Datei zu groß für den Server.';
                toast.done(false, msg, 'error');
                if (typeof window.showAppBanner === 'function') {
                    window.showAppBanner(msg, 'danger', { timeout: 8000 });
                }
                return;
            }

            if (result.status === 0) {
                toast.done(false, 'Server nicht erreichbar. Bitte Seite neu laden und erneut versuchen.', 'error');
                return;
            }

            if (result.data && typeof result.data === 'object') {
                const messages = result.data.messages || [];
                if (!result.data.success || !result.ok) {
                    const errText = pickMessage(messages, ['danger', 'warning', 'info'])
                        || result.data.message
                        || msgs.upload_error
                        || 'Upload fehlgeschlagen';
                    toast.done(false, errText, 'error');
                    // Kein Reload bei Fehler — Meldung bleibt im Panel
                    return;
                }
                const dangerText = pickMessage(messages, ['danger']);
                const okText = pickMessage(messages, ['success']) || 'Upload fertig';
                if (dangerText && !result.data.success) {
                    toast.done(false, dangerText, 'error');
                    return;
                }
                // Erfolg immer grün — Warn-/Info-Flash nicht als gelb anzeigen
                toast.done(true, okText, 'success');
                setTimeout(() => {
                    const url = result.data.redirect_url;
                    if (url) window.location.href = url;
                    else window.location.reload();
                }, 500);
                return;
            }

            if (!result.ok) {
                toast.done(false, msgs.upload_error || 'Upload fehlgeschlagen', 'error');
                return;
            }
            toast.done(true, 'Upload fertig', 'success');
            setTimeout(() => window.location.reload(), 500);
        } catch (err) {
            console.error(err);
            toast.done(false, 'Netzwerkfehler beim Upload. Ist der Server gestartet?', 'error');
        }
    }

    function showSimpleModal(title, bodyHtml, { large } = {}) {
        let modal = document.getElementById('simpleModal');
        if (!modal) {
            const tpl = document.createElement('div');
            tpl.innerHTML = `
            <div class="modal fade" id="simpleModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title"></h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body"></div>
                    </div>
                </div>
            </div>`;
            document.body.appendChild(tpl.firstElementChild);
            modal = document.getElementById('simpleModal');
        }
        const dialog = modal.querySelector('.modal-dialog');
        dialog.classList.toggle('modal-lg', !!large);
        dialog.classList.toggle('modal-xl', !!large);
        modal.querySelector('.modal-content')?.classList.add('files-share-modal-content');
        modal.querySelector('.modal-title').innerText = title;
        modal.querySelector('.modal-body').innerHTML = bodyHtml;
        bootstrap.Modal.getOrCreateInstance(modal).show();
        return modal;
    }

    function closeActiveMenus() {
        document.querySelectorAll('.dropdown-menu.show').forEach(menu => menu.classList.remove('show'));
        document.querySelectorAll('.dropdown.show').forEach(dropdown => dropdown.classList.remove('show'));
        if (window.PrismateamsContextMenu && typeof window.PrismateamsContextMenu.close === 'function') {
            window.PrismateamsContextMenu.close();
        }
    }

    function escapeHtml(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function formatExpires(iso) {
        if (!iso) return '–';
        return String(iso).replace('T', ' ').substring(0, 16);
    }

    function shareIconActionsHtml(formAction, link) {
        const url = link.share_url || '';
        const enabled = !!link.enabled;
        const toggleAction = enabled ? 'disable' : 'enable';
        const toggleTitle = enabled ? 'Deaktivieren' : 'Aktivieren';
        const toggleIcon = enabled ? 'bi-pause-circle' : 'bi-play-circle';
        const toggleCls = enabled ? 'btn-outline-warning' : 'btn-outline-success';
        return `
            <div class="files-share-icon-actions">
                <button type="button" class="btn btn-sm files-share-icon-btn" data-copy-url="${escapeHtml(url)}" title="Link kopieren" aria-label="Link kopieren">
                    <i class="bi bi-clipboard"></i>
                </button>
                <button type="button" class="btn btn-sm files-share-icon-btn" data-edit-share='${escapeHtml(JSON.stringify(link))}' title="Bearbeiten" aria-label="Bearbeiten">
                    <i class="bi bi-pencil"></i>
                </button>
                <form method="POST" action="${formAction}" class="d-inline">
                    <input type="hidden" name="share_id" value="${link.id}">
                    <input type="hidden" name="action" value="regenerate">
                    <button type="submit" class="btn btn-sm files-share-icon-btn" title="Token neu" aria-label="Token neu">
                        <i class="bi bi-arrow-clockwise"></i>
                    </button>
                </form>
                <form method="POST" action="${formAction}" class="d-inline">
                    <input type="hidden" name="share_id" value="${link.id}">
                    <input type="hidden" name="action" value="${toggleAction}">
                    <button type="submit" class="btn btn-sm files-share-icon-btn ${toggleCls}" title="${toggleTitle}" aria-label="${toggleTitle}">
                        <i class="bi ${toggleIcon}"></i>
                    </button>
                </form>
                <form method="POST" action="${formAction}" class="d-inline">
                    <input type="hidden" name="share_id" value="${link.id}">
                    <input type="hidden" name="action" value="delete">
                    <button type="submit" class="btn btn-sm files-share-icon-btn btn-outline-danger" title="Löschen" aria-label="Löschen">
                        <i class="bi bi-x-lg"></i>
                    </button>
                </form>
            </div>`;
    }

    function renderModePicker(modeOptions) {
        if (!modeOptions.length) return '';
        // modeOptions are <option value="x">Label</option>
        const parsed = modeOptions.map(html => {
            const m = String(html).match(/value="([^"]+)".*?>([^<]+)</);
            return m ? { value: m[1], label: m[2] } : null;
        }).filter(Boolean);
        if (!parsed.length) return '';
        const first = parsed[0];
        const items = parsed.map((opt, i) => `
            <li>
                <button type="button" class="dropdown-item ${i === 0 ? 'active' : ''}" data-share-mode-value="${escapeHtml(opt.value)}">
                    ${opt.value === 'dropbox' ? '<i class="bi bi-mailbox me-2"></i>' : (opt.value === 'edit' ? '<i class="bi bi-pencil me-2"></i>' : '<i class="bi bi-eye me-2"></i>')}
                    ${escapeHtml(opt.label)}
                </button>
            </li>`).join('');
        return `
            <div class="dropdown files-share-mode-picker">
                <button type="button" class="btn files-share-mode-btn" data-bs-toggle="dropdown" data-bs-display="static" data-bs-auto-close="true" aria-expanded="false">
                    <span class="files-share-mode-label">${escapeHtml(first.label)}</span>
                    <i class="bi bi-chevron-down"></i>
                </button>
                <ul class="dropdown-menu files-dropdown-menu files-share-mode-menu">${items}</ul>
                <input type="hidden" name="mode" value="${escapeHtml(first.value)}" required>
            </div>`;
    }

    function renderShareMgmt(type, id, item, flags) {
        const L = shareLabels();
        const links = item.links || [];
        const formAction = type === 'file' ? `/files/file/${id}/share-settings` : `/files/folder/${id}/share-settings`;

        const modeOptions = [];
        if (flags.sharing) {
            modeOptions.push(`<option value="view">${escapeHtml(modeLabel('view'))}</option>`);
            modeOptions.push(`<option value="edit">${escapeHtml(modeLabel('edit'))}</option>`);
        }
        if (type === 'folder' && flags.dropbox && item.can_add_dropbox) {
            modeOptions.push(`<option value="dropbox">${escapeHtml(modeLabel('dropbox'))}</option>`);
        }

        const rows = links.map(link => {
            const url = link.share_url || '';
            return `
                <tr data-share-id="${link.id}">
                    <td>${modeChipHtml(link.mode)}</td>
                    <td>${escapeHtml(link.label || '–')}</td>
                    <td>
                        <input type="text" class="form-control form-control-sm files-share-link-input" value="${escapeHtml(url)}" readonly title="${escapeHtml(url)}">
                    </td>
                    <td>${link.has_password ? 'Ja' : 'Nein'}</td>
                    <td>${escapeHtml(formatExpires(link.expires_at))}</td>
                    <td>${shareStatusChipHtml(link)}</td>
                    <td>${shareIconActionsHtml(formAction, link)}</td>
                </tr>`;
        }).join('');

        const cards = links.map(link => {
            const url = link.share_url || '';
            return `
                <div class="files-share-card">
                    <div class="d-flex justify-content-between align-items-start gap-2">
                        <div>
                            ${modeChipHtml(link.mode)}
                            <strong class="ms-1">${escapeHtml(link.label || modeLabel(link.mode))}</strong>
                        </div>
                        ${shareStatusChipHtml(link)}
                    </div>
                    <input type="text" class="form-control form-control-sm files-share-link-input mt-2" value="${escapeHtml(url)}" readonly title="${escapeHtml(url)}">
                    <div class="small text-muted mt-2">Passwort: ${link.has_password ? 'Ja' : 'Nein'} · Ablauf: ${escapeHtml(formatExpires(link.expires_at))}</div>
                    <div class="share-actions">${shareIconActionsHtml(formAction, link)}</div>
                </div>`;
        }).join('');

        const addForm = modeOptions.length ? `
            <div class="files-share-add-section">
            <h6 class="mb-2">${L.add_link || 'Neuen Link anlegen'}</h6>
            <form method="POST" action="${formAction}" class="row g-2 align-items-end files-share-add-form" id="shareAddLinkForm">
                <div class="col-md-3">
                    <label class="form-label">Art</label>
                    ${renderModePicker(modeOptions)}
                </div>
                <div class="col-md-3">
                    <label class="form-label">Label</label>
                    <input type="text" name="label" class="form-control files-pill-input" placeholder="optional">
                </div>
                <div class="col-md-3">
                    <label class="form-label">Passwort</label>
                    <input type="password" name="password" class="form-control files-pill-input" autocomplete="new-password">
                </div>
                <div class="col-md-3">
                    <label class="form-label">Ablauf</label>
                    <input type="datetime-local" name="expires_at" class="form-control files-pill-input">
                </div>
                <div class="col-12 d-flex flex-wrap gap-2">
                    <button type="submit" name="action" value="add_link" class="btn btn-accent files-pill-btn"><i class="bi bi-plus-lg"></i> Link erstellen</button>
                    <button type="submit" name="action" value="disable_all" class="btn btn-outline-danger files-pill-btn" formnovalidate>Alle deaktivieren</button>
                </div>
            </form>
            </div>` : `<p class="text-muted">Keine Link-Typen aktiviert.</p>`;

        return `
            <div class="files-share-mgmt">
                <p class="fw-semibold mb-3">${escapeHtml(item.name || '')}</p>
                <div class="files-share-table-wrap table-responsive">
                    <table class="table table-sm align-middle mb-0">
                        <thead><tr>
                            <th>Art</th><th>Label</th><th>Link</th><th>PW</th><th>Ablauf</th><th>Status</th><th class="text-end">Aktionen</th>
                        </tr></thead>
                        <tbody>${rows || '<tr><td colspan="7" class="text-muted">Noch keine Links.</td></tr>'}</tbody>
                    </table>
                </div>
                <div class="files-share-cards">${cards || '<p class="text-muted">Noch keine Links.</p>'}</div>
                ${addForm}
                <div id="shareEditPanel" class="mt-3" style="display:none;"></div>
            </div>`;
    }

    function bindShareMgmtEvents(modal, formAction) {
        modal.querySelectorAll('[data-copy-url]').forEach(btn => {
            btn.addEventListener('click', () => {
                const url = btn.getAttribute('data-copy-url') || '';
                if (url) {
                    navigator.clipboard.writeText(url).then(() => {
                        const icon = btn.querySelector('i');
                        if (icon) {
                            const prev = icon.className;
                            icon.className = 'bi bi-check-lg';
                            setTimeout(() => { icon.className = prev; }, 1200);
                        }
                    }).catch(() => {});
                }
            });
        });

        modal.querySelectorAll('[data-share-mode-value]').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const picker = item.closest('.files-share-mode-picker');
                if (!picker) return;
                const value = item.getAttribute('data-share-mode-value');
                const label = item.textContent.trim();
                const hidden = picker.querySelector('input[name="mode"]');
                const labelEl = picker.querySelector('.files-share-mode-label');
                if (hidden) hidden.value = value;
                if (labelEl) labelEl.textContent = label;
                picker.querySelectorAll('[data-share-mode-value]').forEach(el => el.classList.remove('active'));
                item.classList.add('active');
            });
        });

        modal.querySelectorAll('[data-edit-share]').forEach(btn => {
            btn.addEventListener('click', () => {
                let link;
                try { link = JSON.parse(btn.getAttribute('data-edit-share')); } catch (e) { return; }
                const panel = modal.querySelector('#shareEditPanel');
                if (!panel) return;
                const exp = link.expires_at ? String(link.expires_at).substring(0, 16) : '';
                panel.style.display = 'block';
                panel.innerHTML = `
                    <div class="files-share-card">
                        <h6>Link bearbeiten (#${link.id})</h6>
                        <form method="POST" action="${formAction}">
                            <input type="hidden" name="action" value="update">
                            <input type="hidden" name="share_id" value="${link.id}">
                            <div class="mb-2">
                                <label class="form-label">Label</label>
                                <input type="text" class="form-control files-pill-input" name="label" value="${escapeHtml(link.label || '')}">
                            </div>
                            <div class="mb-2">
                                <label class="form-label">Neues Passwort (leer = behalten)</label>
                                <input type="password" class="form-control files-pill-input" name="password" autocomplete="new-password">
                            </div>
                            <div class="form-check mb-2">
                                <input class="form-check-input" type="checkbox" name="clear_password" value="1" id="clearPw${link.id}">
                                <label class="form-check-label" for="clearPw${link.id}">Passwort entfernen</label>
                            </div>
                            <div class="mb-2">
                                <label class="form-label">Ablauf</label>
                                <input type="datetime-local" class="form-control files-pill-input" name="expires_at" value="${escapeHtml(exp)}">
                            </div>
                            <div class="form-check mb-3">
                                <input class="form-check-input" type="checkbox" name="enabled" value="1" id="en${link.id}" ${link.enabled ? 'checked' : ''}>
                                <label class="form-check-label" for="en${link.id}">Aktiv</label>
                            </div>
                            <button type="submit" class="btn btn-accent files-pill-btn">Speichern</button>
                        </form>
                    </div>`;
            });
        });
    }

    function openShareManagement(type, id) {
        closeActiveMenus();
        const L = shareLabels();
        const endpoint = type === 'file' ? `/files/file/${id}/share-settings` : `/files/folder/${id}/share-settings`;
        const formAction = type === 'file' ? `/files/file/${id}/share-settings` : `/files/folder/${id}/share-settings`;
        const flags = {
            sharing: !!window.FILES_SHARING_ENABLED,
            dropbox: !!window.FILES_DROPBOX_ENABLED
        };
        fetch(endpoint, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
            .then(async (r) => {
                const ct = (r.headers.get('content-type') || '').toLowerCase();
                if (!r.ok || !ct.includes('application/json')) {
                    throw new Error(r.status === 401 || r.status === 403 ? 'Keine Berechtigung' : 'Serverfehler');
                }
                return r.json();
            })
            .then(data => {
                if (!data || !data.success) {
                    if (typeof window.showAppBanner === 'function') {
                        window.showAppBanner((data && data.error) || 'Freigaben konnten nicht geladen werden.', 'danger');
                    }
                    return;
                }
                const html = renderShareMgmt(type, id, data.item || {}, flags);
                const modal = showSimpleModal(L.manage_title || 'Freigaben', html, { large: true });
                bindShareMgmtEvents(modal, formAction);
            })
            .catch(err => {
                console.error(err);
                if (typeof window.showAppBanner === 'function') {
                    window.showAppBanner(err.message || 'Freigaben konnten nicht geladen werden.', 'danger');
                }
            });
    }

    function renderPresence(presenceMap) {
        document.querySelectorAll('.files-presence-anchor').forEach(el => {
            el.innerHTML = '';
            el.hidden = true;
        });
        Object.keys(presenceMap || {}).forEach(fileId => {
            const users = presenceMap[fileId] || [];
            if (!users.length) return;
            const anchors = document.querySelectorAll(`.files-presence-anchor[data-presence-file="${fileId}"]`);
            anchors.forEach(anchor => {
                const stack = document.createElement('span');
                stack.className = 'files-presence-stack';
                const names = users.map(u => u.display_name).filter(Boolean);
                stack.title = names.join(', ');
                stack.setAttribute('aria-label', names.length
                    ? ('Aktuell im Dokument: ' + names.join(', '))
                    : 'Aktuell im Dokument');
                users.slice(0, 4).forEach(u => {
                    const av = document.createElement('span');
                    av.className = 'files-presence-avatar';
                    av.title = u.display_name || '';
                    if (u.avatar_url) {
                        av.innerHTML = `<img src="${escapeHtml(u.avatar_url)}" alt="">`;
                    } else {
                        av.textContent = u.initials || '?';
                    }
                    stack.appendChild(av);
                });
                if (users.length > 4) {
                    const more = document.createElement('span');
                    more.className = 'files-presence-avatar files-presence-avatar--more';
                    more.textContent = '+' + (users.length - 4);
                    more.title = names.slice(4).join(', ');
                    stack.appendChild(more);
                }
                anchor.appendChild(stack);
                anchor.hidden = false;
            });
        });
    }

    function pollPresence() {
        const folderParam = CURRENT_FOLDER_ID == null ? '' : String(CURRENT_FOLDER_ID);
        fetch(`/files/api/presence?folder_id=${encodeURIComponent(folderParam)}`)
            .then(r => r.json())
            .then(data => {
                if (data && data.success) renderPresence(data.presence || {});
            })
            .catch(() => {});
    }

    // Override legacy share dialogs
    window.openShareDialog = function (type, id) { openShareManagement(type, id); };
    window.openShareSettings = function (type, id) { openShareManagement(type, id); };
    window.openShareManagement = openShareManagement;
    window.submitUploadFormDataWithToast = submitUploadFormDataWithToast;
    window.createUploadToast = createUploadToast;

    let aclState = { type: null, id: null };

    function renderAclEntries(entries) {
        const list = document.getElementById('aclEntriesList');
        if (!list) return;
        const i18n = (window.FILES_I18N && window.FILES_I18N.acl) || {};
        if (!entries || !entries.length) {
            list.innerHTML = `<div class="text-muted small">${i18n.empty || 'Keine internen Freigaben.'}</div>`;
            return;
        }
        list.innerHTML = entries.map(e => {
            const isTeam = !!e.grantee_team_id;
            const label = e.share_all
                ? (i18n.share_all || 'Mit allen')
                : (isTeam
                    ? ((i18n.team_prefix || 'Team') + ': ' + (e.grantee_team_name || e.grantee_name || ('#' + e.grantee_team_id)))
                    : (e.grantee_name || ('#' + e.grantee_user_id)));
            const perm = e.permission === 'edit' ? (i18n.permission_edit || 'edit') : (i18n.permission_view || 'view');
            const gid = e.share_all ? 'all' : (isTeam ? ('team:' + e.grantee_team_id) : String(e.grantee_user_id));
            return `<div class="list-group-item d-flex justify-content-between align-items-center px-0">
                <span>${label} <span class="badge bg-secondary">${perm}</span></span>
                <button type="button" class="btn btn-sm btn-outline-danger" data-acl-remove="${gid}">${i18n.remove || 'Entfernen'}</button>
            </div>`;
        }).join('');
        list.querySelectorAll('[data-acl-remove]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const raw = btn.getAttribute('data-acl-remove');
                let body;
                if (raw === 'all') {
                    body = { grantee_user_id: null };
                } else if (raw && raw.startsWith('team:')) {
                    body = { grantee_team_id: Number(raw.slice(5)) };
                } else {
                    body = { grantee_user_id: Number(raw) };
                }
                await fetch(`/files/api/resource-acl/${aclState.type}/${aclState.id}`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                    body: JSON.stringify(body)
                });
                openInternalShare(aclState.type, aclState.id);
            });
        });
    }

    async function openInternalShare(type, id) {
        if (window.FILES_VIEW === 'public') {
            if (typeof window.showAppBanner === 'function') {
                window.showAppBanner('Public-Dateien können nicht intern freigegeben werden.', 'warning');
            }
            return;
        }
        aclState = { type, id };
        const modalEl = document.getElementById('internalShareModal');
        if (!modalEl) return;
        try {
            const res = await fetch(`/files/api/resource-acl/${type}/${id}`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin',
            });
            const ct = (res.headers.get('content-type') || '').toLowerCase();
            if (!res.ok || !ct.includes('application/json')) {
                throw new Error(res.status === 401 || res.status === 403 ? 'Keine Berechtigung' : 'Serverfehler');
            }
            const data = await res.json();
            if (!data.success) {
                if (typeof window.showAppBanner === 'function') {
                    window.showAppBanner(data.error || 'Fehler', 'danger');
                }
                return;
            }
            const select = document.getElementById('aclUserSelect');
            if (select) {
                select.innerHTML = (data.users || []).map(u =>
                    `<option value="${u.id}">${u.full_name || u.username || ('#' + u.id)}</option>`
                ).join('') || '<option value="">—</option>';
            }
            const teamSelect = document.getElementById('aclTeamSelect');
            const teamWrap = document.getElementById('aclTeamShareWrap');
            const teams = data.teams || [];
            if (teamWrap) {
                teamWrap.hidden = teams.length === 0;
            }
            if (teamSelect) {
                teamSelect.innerHTML = teams.map(t =>
                    `<option value="${t.id}">${t.name || ('#' + t.id)}</option>`
                ).join('') || '<option value="">—</option>';
            }
            renderAclEntries(data.entries || []);
            if (window.bootstrap && bootstrap.Modal) {
                bootstrap.Modal.getOrCreateInstance(modalEl).show();
            } else {
                modalEl.classList.add('show');
                modalEl.style.display = 'block';
            }
        } catch (err) {
            console.error(err);
            if (typeof window.showAppBanner === 'function') {
                window.showAppBanner(err.message || 'Freigabe konnte nicht geladen werden.', 'danger');
            }
        }
    }
    window.openInternalShare = openInternalShare;

    document.addEventListener('DOMContentLoaded', function () {
        // Hook direct uploads if original submitUploadFormData exists — patch via monkeypatch after page script
        setTimeout(() => {
            if (typeof window.submitUploadFormData === 'function') {
                window.submitUploadFormData = function (formData, fileNames) {
                    if (window.FILES_VIEW && !formData.has('view')) {
                        formData.append('view', window.FILES_VIEW);
                    }
                    if (window.FILES_TEAM_ID && !formData.has('team_id')) {
                        formData.append('team_id', window.FILES_TEAM_ID);
                    }
                    return submitUploadFormDataWithToast(formData, fileNames);
                };
            }
        }, 0);

        const shareAllBtn = document.getElementById('aclShareAllBtn');
        const shareUserBtn = document.getElementById('aclShareUserBtn');
        const shareTeamBtn = document.getElementById('aclShareTeamBtn');
        if (shareAllBtn) {
            shareAllBtn.addEventListener('click', async () => {
                const perm = document.getElementById('aclPermSelect')?.value || 'view';
                await fetch(`/files/api/resource-acl/${aclState.type}/${aclState.id}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                    body: JSON.stringify({ share_all: true, permission: perm })
                });
                openInternalShare(aclState.type, aclState.id);
            });
        }
        if (shareUserBtn) {
            shareUserBtn.addEventListener('click', async () => {
                const uid = document.getElementById('aclUserSelect')?.value;
                const perm = document.getElementById('aclPermSelect')?.value || 'view';
                if (!uid) return;
                const res = await fetch(`/files/api/resource-acl/${aclState.type}/${aclState.id}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                    body: JSON.stringify({ grantee_user_id: Number(uid), permission: perm })
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok || data.success === false) {
                    if (typeof window.showAppBanner === 'function') {
                        window.showAppBanner(data.error || 'Freigabe fehlgeschlagen.', 'danger');
                    }
                    return;
                }
                openInternalShare(aclState.type, aclState.id);
            });
        }
        if (shareTeamBtn) {
            shareTeamBtn.addEventListener('click', async () => {
                const tid = document.getElementById('aclTeamSelect')?.value;
                const perm = document.getElementById('aclPermSelect')?.value || 'view';
                if (!tid) return;
                const res = await fetch(`/files/api/resource-acl/${aclState.type}/${aclState.id}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                    body: JSON.stringify({ grantee_team_id: Number(tid), permission: perm })
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok || data.success === false) {
                    if (typeof window.showAppBanner === 'function') {
                        window.showAppBanner(data.error || 'Freigabe fehlgeschlagen.', 'danger');
                    }
                    return;
                }
                openInternalShare(aclState.type, aclState.id);
            });
        }

        // Sidebar Neu dropdown (mirrors main Neu button behaviour)
        const sideBtn = document.getElementById('newButtonSidebar');
        const sideMenu = document.getElementById('newDropdownMenuSidebar');
        const sideWrap = document.getElementById('newButtonDropdownSidebar');
        if (sideBtn && sideMenu) {
            const placeSideMenu = () => {
                const rect = sideBtn.getBoundingClientRect();
                sideMenu.style.position = 'fixed';
                sideMenu.style.inset = 'auto';
                sideMenu.style.top = `${Math.round(rect.bottom + 6)}px`;
                sideMenu.style.left = `${Math.round(rect.left)}px`;
                sideMenu.style.right = 'auto';
                sideMenu.style.bottom = 'auto';
                sideMenu.style.minWidth = `${Math.max(rect.width, 264)}px`;
                sideMenu.style.zIndex = '2000';
            };
            const closeSideMenu = () => {
                sideMenu.style.display = 'none';
            };
            const openSideMenu = () => {
                sideMenu.style.display = 'block';
                placeSideMenu();
            };
            sideBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const open = sideMenu.style.display === 'block';
                if (open) closeSideMenu();
                else openSideMenu();
            });
            sideMenu.querySelectorAll('[data-pt-trigger-click]').forEach((item) => {
                item.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const sel = item.getAttribute('data-pt-trigger-click');
                    const trigger = sel ? document.querySelector(sel) : null;
                    closeSideMenu();
                    if (trigger) trigger.click();
                });
            });
            document.addEventListener('click', (e) => {
                if (sideWrap && sideWrap.contains(e.target)) return;
                if (sideMenu.contains(e.target)) return;
                closeSideMenu();
            });
            window.addEventListener('resize', () => {
                if (sideMenu.style.display === 'block') placeSideMenu();
            });
            window.addEventListener('scroll', () => {
                if (sideMenu.style.display === 'block') placeSideMenu();
            }, true);
        }

        document.querySelectorAll(
            'form[action*="create-folder"], form[action*="create-office-file"], form[action*="create-file"], #inlineFileForm, #inlineFileFormList, #uploadForm, #newFolderModal form'
        ).forEach(form => {
            if (window.FILES_VIEW && !form.querySelector('input[name="view"]')) {
                const inp = document.createElement('input');
                inp.type = 'hidden';
                inp.name = 'view';
                inp.value = window.FILES_VIEW;
                form.appendChild(inp);
            }
            if (window.FILES_TEAM_ID && !form.querySelector('input[name="team_id"]')) {
                const tinp = document.createElement('input');
                tinp.type = 'hidden';
                tinp.name = 'team_id';
                tinp.value = window.FILES_TEAM_ID;
                form.appendChild(tinp);
            }
        });

        const mobileBtn = document.getElementById('newButtonMobile');
        const mobileMenu = document.getElementById('newDropdownMenuMobile');
        const mobileWrap = document.getElementById('newButtonDropdownMobile');
        if (mobileBtn && mobileMenu) {
            mobileBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const cm = window.PrismateamsContextMenu;
                if (
                    cm &&
                    typeof cm.isMobileSheetEnabled === 'function' &&
                    cm.isMobileSheetEnabled() &&
                    typeof cm.showMobileActionSheet === 'function'
                ) {
                    mobileMenu.style.display = 'none';
                    cm.showMobileActionSheet(mobileMenu);
                    return;
                }
                const open = mobileMenu.style.display === 'block';
                mobileMenu.style.display = open ? 'none' : 'block';
            });
            mobileMenu.querySelectorAll('[data-pt-trigger-click]').forEach((item) => {
                item.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const sel = item.getAttribute('data-pt-trigger-click');
                    const trigger = sel ? document.querySelector(sel) : null;
                    mobileMenu.style.display = 'none';
                    if (trigger) trigger.click();
                });
            });
            document.addEventListener('click', (e) => {
                if (mobileWrap && mobileWrap.contains(e.target)) return;
                mobileMenu.style.display = 'none';
            });
        }

        document.querySelectorAll('#filesMobileNav a[data-files-dismiss-offcanvas]').forEach((link) => {
            link.addEventListener('click', () => {
                // Do not preventDefault — Bootstrap data-bs-dismiss blocks <a> navigation.
                setTimeout(() => {
                    const el = document.getElementById('filesMobileNav');
                    if (!el || !window.bootstrap || !bootstrap.Offcanvas) return;
                    const oc = bootstrap.Offcanvas.getInstance(el);
                    if (oc) oc.hide();
                }, 50);
            });
        });

        pollPresence();
        setInterval(pollPresence, 25000);
    });

    function favoritesI18n() {
        return (window.FILES_I18N && window.FILES_I18N.favorites) || {};
    }

    function renderFavoritesLists(favorites) {
        const emptyText = favoritesI18n().empty || 'Keine Favoriten';
        const items = Array.isArray(favorites) ? favorites : [];
        ['filesFavoritesNavDesktop', 'filesFavoritesNavMobile'].forEach((id) => {
            const root = document.getElementById(id);
            if (!root) return;
            const list = root.querySelector('.files-favorites-list');
            if (!list) return;
            const dismiss = id === 'filesFavoritesNavMobile';
            if (!items.length) {
                list.innerHTML = `<div class="files-favorites-empty text-muted small px-3">${emptyText}</div>`;
                return;
            }
            list.innerHTML = items.map((fav) => {
                const colorClass = fav.color ? '' : ' text-warning';
                const colorStyle = fav.color ? ` style="color: ${fav.color};"` : '';
                const dismissAttr = dismiss ? ' data-files-dismiss-offcanvas="1"' : '';
                const name = (fav.name || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                const url = fav.url || '#';
                return `<a class="nav-link mod-nav-link files-favorite-link" href="${url}" data-folder-id="${fav.id}"${dismissAttr}>` +
                    `<i class="bi bi-folder-fill me-2 folder-color-icon${colorClass}"${colorStyle}></i>` +
                    `<span class="files-favorite-name text-truncate">${name}</span></a>`;
            }).join('');
            if (dismiss) {
                list.querySelectorAll('a[data-files-dismiss-offcanvas]').forEach((link) => {
                    link.addEventListener('click', () => {
                        setTimeout(() => {
                            const el = document.getElementById('filesMobileNav');
                            if (!el || !window.bootstrap || !bootstrap.Offcanvas) return;
                            const oc = bootstrap.Offcanvas.getInstance(el);
                            if (oc) oc.hide();
                        }, 50);
                    });
                });
            }
        });
    }

    function updateFavoriteMenuLabels(folderId, favorited) {
        const addLabel = favoritesI18n().add || 'Zu Favoriten';
        const removeLabel = favoritesI18n().remove || 'Aus Favoriten entfernen';
        document.querySelectorAll(`.files-favorite-toggle[data-folder-id="${folderId}"]`).forEach((el) => {
            const icon = el.querySelector('i.bi');
            const span = el.querySelector('span');
            if (icon) {
                icon.classList.toggle('bi-star-fill', favorited);
                icon.classList.toggle('bi-star', !favorited);
            }
            if (span) span.textContent = favorited ? removeLabel : addLabel;
        });
    }

    window.toggleFolderFavorite = async function toggleFolderFavorite(folderId) {
        try {
            const res = await fetch(`/files/api/folder-favorite/${folderId}`, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin',
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.success) {
                const msg = data.error || favoritesI18n().limit || 'Favorit konnte nicht geändert werden.';
                if (window.showAppBanner) window.showAppBanner(msg, 'warning');
                return;
            }
            updateFavoriteMenuLabels(folderId, !!data.favorited);
            renderFavoritesLists(data.favorites || []);
        } catch (err) {
            if (window.showAppBanner) {
                window.showAppBanner(favoritesI18n().limit || 'Favorit konnte nicht geändert werden.', 'danger');
            }
        }
    };
})(window);
