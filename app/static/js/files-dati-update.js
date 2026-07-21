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

    const MAX_UPLOAD_BYTES = 100 * 1024 * 1024; // 100MB — matches files.upload_file

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

    function createUploadToast(fileNames) {
        const stack = ensureToastStack();
        const id = 'upload-toast-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7);
        const names = (fileNames || []).filter(Boolean);
        const label = names.length === 0
            ? 'Upload'
            : (names.length === 1 ? names[0] : names.length + ' Dateien');
        const el = document.createElement('div');
        el.id = id;
        el.className = 'files-upload-toast';
        el.setAttribute('role', 'status');
        el.innerHTML = `
            <div class="files-upload-toast-title">Wird hochgeladen…</div>
            <div class="files-upload-toast-meta"></div>
            <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
                <div class="progress-bar progress-bar-striped progress-bar-animated bg-primary" style="width:0%"></div>
            </div>
            <div class="files-upload-toast-pct">0%</div>
        `;
        el.querySelector('.files-upload-toast-meta').textContent = label;
        stack.appendChild(el);
        return {
            id,
            el,
            setProgress(pct) {
                const n = Math.max(0, Math.min(100, Number(pct) || 0));
                const bar = el.querySelector('.progress-bar');
                const wrap = el.querySelector('.progress');
                const pctEl = el.querySelector('.files-upload-toast-pct');
                if (bar) bar.style.width = n + '%';
                if (wrap) wrap.setAttribute('aria-valuenow', String(Math.round(n)));
                if (pctEl) pctEl.textContent = Math.round(n) + '%';
            },
            setIndeterminate(on) {
                const bar = el.querySelector('.progress-bar');
                if (!bar) return;
                if (on) {
                    bar.classList.add('progress-bar-animated', 'progress-bar-striped');
                    bar.style.width = '100%';
                }
            },
            setStatus(text, kind) {
                const title = el.querySelector('.files-upload-toast-title');
                if (title) title.textContent = text;
                el.classList.remove('is-success', 'is-error', 'is-warning');
                if (kind === 'success') el.classList.add('is-success');
                if (kind === 'error') el.classList.add('is-error');
                if (kind === 'warning') el.classList.add('is-warning');
            },
            done(ok, message, kind) {
                const bar = el.querySelector('.progress-bar');
                if (bar) bar.classList.remove('progress-bar-animated');
                this.setProgress(100);
                const k = kind || (ok ? 'success' : 'error');
                this.setStatus(message || (ok ? 'Upload fertig' : 'Upload fehlgeschlagen'), k);
                setTimeout(() => el.remove(), ok && k !== 'warning' ? 2800 : 7000);
            }
        };
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
                    onProgress(Math.round((evt.loaded / evt.total) * 100), false);
                } else {
                    onProgress(null, true);
                }
            };
            xhr.upload.onloadstart = () => {
                if (onProgress) onProgress(1, false);
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
            const detail = tooBig.slice(0, 3).map(f => `${f.name} (${formatBytes(f.size)})`).join(', ');
            const msg = `Datei zu groß (max. 100MB): ${detail}${tooBig.length > 3 ? ' …' : ''}`;
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

        const toast = createUploadToast(fileNames);
        toast.setStatus('Wird hochgeladen…', null);
        try {
            const result = await xhrUpload(uploadUrl, formData, {
                onProgress: (pct, indeterminate) => {
                    if (indeterminate) {
                        toast.setIndeterminate(true);
                        toast.setStatus('Upload läuft…', null);
                    } else if (pct != null) {
                        toast.setProgress(pct);
                        toast.setStatus(`Wird hochgeladen… ${pct}%`, null);
                    }
                }
            });

            if (result.status === 413) {
                const msg = (result.data && (result.data.message || pickMessage(result.data.messages || [], ['danger'])))
                    || 'Datei zu groß für den Server (max. 100MB pro Datei).';
                toast.el.remove();
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
                    return;
                }
                const warnText = pickMessage(messages, ['warning', 'info']);
                const okText = pickMessage(messages, ['success']) || 'Upload fertig';
                if (warnText) {
                    toast.done(true, `${okText} — ${warnText}`, 'warning');
                } else {
                    toast.done(true, okText, 'success');
                }
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

    function renderShareMgmt(type, id, item, flags) {
        const L = shareLabels();
        const links = item.links || [];
        const formAction = type === 'file' ? `/files/file/${id}/share-settings` : `/files/folder/${id}/share-settings`;
        const createAction = type === 'file' ? `/files/file/${id}/share` : `/files/folder/${id}/share`;

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
            const status = !link.enabled ? 'aus' : (link.is_expired ? 'abgelaufen' : 'aktiv');
            const toggleAction = link.enabled
                ? `<form method="POST" action="${formAction}" class="d-inline">
                        <input type="hidden" name="share_id" value="${link.id}">
                        <input type="hidden" name="action" value="disable">
                        <button type="submit" class="btn btn-sm btn-outline-warning" title="Deaktivieren">Deaktivieren</button>
                   </form>`
                : `<form method="POST" action="${formAction}" class="d-inline">
                        <input type="hidden" name="share_id" value="${link.id}">
                        <input type="hidden" name="action" value="enable">
                        <button type="submit" class="btn btn-sm btn-outline-success" title="Aktivieren">Aktivieren</button>
                   </form>`;
            return `
                <tr data-share-id="${link.id}">
                    <td><span class="badge text-bg-secondary">${escapeHtml(modeLabel(link.mode))}</span></td>
                    <td>${escapeHtml(link.label || '–')}</td>
                    <td>
                        <div class="input-group input-group-sm">
                            <input type="text" class="form-control" value="${escapeHtml(url)}" readonly>
                            <button type="button" class="btn btn-outline-secondary" data-copy-url="${escapeHtml(url)}"><i class="bi bi-clipboard"></i></button>
                        </div>
                    </td>
                    <td>${link.has_password ? 'Ja' : 'Nein'}</td>
                    <td>${escapeHtml(formatExpires(link.expires_at))}</td>
                    <td>${status}</td>
                    <td class="text-nowrap">
                        <button type="button" class="btn btn-sm btn-outline-primary" data-edit-share='${escapeHtml(JSON.stringify(link))}'>Bearbeiten</button>
                        <form method="POST" action="${formAction}" class="d-inline">
                            <input type="hidden" name="share_id" value="${link.id}">
                            <input type="hidden" name="action" value="regenerate">
                            <button type="submit" class="btn btn-sm btn-outline-secondary" title="Token neu">↺</button>
                        </form>
                        ${toggleAction}
                        <form method="POST" action="${formAction}" class="d-inline">
                            <input type="hidden" name="share_id" value="${link.id}">
                            <input type="hidden" name="action" value="delete">
                            <button type="submit" class="btn btn-sm btn-outline-danger" title="Löschen">×</button>
                        </form>
                    </td>
                </tr>`;
        }).join('');

        const cards = links.map(link => {
            const url = link.share_url || '';
            const toggleAction = link.enabled
                ? `<form method="POST" action="${formAction}" class="d-inline">
                        <input type="hidden" name="share_id" value="${link.id}">
                        <input type="hidden" name="action" value="disable">
                        <button type="submit" class="btn btn-sm btn-outline-warning">Deaktivieren</button>
                   </form>`
                : `<form method="POST" action="${formAction}" class="d-inline">
                        <input type="hidden" name="share_id" value="${link.id}">
                        <input type="hidden" name="action" value="enable">
                        <button type="submit" class="btn btn-sm btn-outline-success">Aktivieren</button>
                   </form>`;
            return `
                <div class="files-share-card">
                    <div class="d-flex justify-content-between align-items-start gap-2">
                        <div>
                            <span class="badge text-bg-secondary">${escapeHtml(modeLabel(link.mode))}</span>
                            <strong class="ms-1">${escapeHtml(link.label || modeLabel(link.mode))}</strong>
                        </div>
                        <small class="text-muted">${!link.enabled ? 'aus' : (link.is_expired ? 'abgelaufen' : 'aktiv')}</small>
                    </div>
                    <div class="input-group input-group-sm mt-2">
                        <input type="text" class="form-control" value="${escapeHtml(url)}" readonly>
                        <button type="button" class="btn btn-outline-secondary" data-copy-url="${escapeHtml(url)}"><i class="bi bi-clipboard"></i></button>
                    </div>
                    <div class="small text-muted mt-2">Passwort: ${link.has_password ? 'Ja' : 'Nein'} · Ablauf: ${escapeHtml(formatExpires(link.expires_at))}</div>
                    <div class="share-actions">
                        <button type="button" class="btn btn-sm btn-outline-primary" data-edit-share='${escapeHtml(JSON.stringify(link))}'>Bearbeiten</button>
                        <form method="POST" action="${formAction}" class="d-inline">
                            <input type="hidden" name="share_id" value="${link.id}">
                            <input type="hidden" name="action" value="regenerate">
                            <button type="submit" class="btn btn-sm btn-outline-secondary">Token neu</button>
                        </form>
                        ${toggleAction}
                        <form method="POST" action="${formAction}" class="d-inline">
                            <input type="hidden" name="share_id" value="${link.id}">
                            <input type="hidden" name="action" value="delete">
                            <button type="submit" class="btn btn-sm btn-outline-danger">Löschen</button>
                        </form>
                    </div>
                </div>`;
        }).join('');

        const addForm = modeOptions.length ? `
            <hr>
            <h6 class="mb-2">${L.add_link || 'Neuen Link anlegen'}</h6>
            <form method="POST" action="${formAction}" class="row g-2 align-items-end" id="shareAddLinkForm">
                <div class="col-md-3">
                    <label class="form-label">Art</label>
                    <select name="mode" class="form-select" required>${modeOptions.join('')}</select>
                </div>
                <div class="col-md-3">
                    <label class="form-label">Label</label>
                    <input type="text" name="label" class="form-control" placeholder="optional">
                </div>
                <div class="col-md-3">
                    <label class="form-label">Passwort</label>
                    <input type="password" name="password" class="form-control" autocomplete="new-password">
                </div>
                <div class="col-md-3">
                    <label class="form-label">Ablauf</label>
                    <input type="datetime-local" name="expires_at" class="form-control">
                </div>
                <div class="col-12">
                    <button type="submit" name="action" value="add_link" class="btn btn-primary"><i class="bi bi-plus-lg"></i> Link erstellen</button>
                    <button type="submit" name="action" value="disable_all" class="btn btn-outline-danger ms-1" formnovalidate>Alle deaktivieren</button>
                </div>
            </form>` : `<p class="text-muted">Keine Link-Typen aktiviert.</p>`;

        return `
            <div class="files-share-mgmt">
                <p class="text-muted small mb-3">${escapeHtml(item.name || '')}</p>
                <div class="files-share-table-wrap table-responsive">
                    <table class="table table-sm align-middle">
                        <thead><tr>
                            <th>Art</th><th>Label</th><th>Link</th><th>PW</th><th>Ablauf</th><th>Status</th><th></th>
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
                if (url) navigator.clipboard.writeText(url);
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
                    <div class="border rounded p-3">
                        <h6>Link bearbeiten (#${link.id})</h6>
                        <form method="POST" action="${formAction}">
                            <input type="hidden" name="action" value="update">
                            <input type="hidden" name="share_id" value="${link.id}">
                            <div class="mb-2">
                                <label class="form-label">Label</label>
                                <input type="text" class="form-control" name="label" value="${escapeHtml(link.label || '')}">
                            </div>
                            <div class="mb-2">
                                <label class="form-label">Neues Passwort (leer = behalten)</label>
                                <input type="password" class="form-control" name="password" autocomplete="new-password">
                            </div>
                            <div class="form-check mb-2">
                                <input class="form-check-input" type="checkbox" name="clear_password" value="1" id="clearPw${link.id}">
                                <label class="form-check-label" for="clearPw${link.id}">Passwort entfernen</label>
                            </div>
                            <div class="mb-2">
                                <label class="form-label">Ablauf</label>
                                <input type="datetime-local" class="form-control" name="expires_at" value="${escapeHtml(exp)}">
                            </div>
                            <div class="form-check mb-3">
                                <input class="form-check-input" type="checkbox" name="enabled" value="1" id="en${link.id}" ${link.enabled ? 'checked' : ''}>
                                <label class="form-check-label" for="en${link.id}">Aktiv</label>
                            </div>
                            <button type="submit" class="btn btn-primary">Speichern</button>
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
        fetch(endpoint)
            .then(r => r.json())
            .then(data => {
                if (!data.success) return;
                const html = renderShareMgmt(type, id, data.item || {}, flags);
                const modal = showSimpleModal(L.manage_title || 'Freigaben', html, { large: true });
                bindShareMgmtEvents(modal, formAction);
            })
            .catch(err => console.error(err));
    }

    function renderPresence(presenceMap) {
        document.querySelectorAll('.files-presence-stack').forEach(el => el.remove());
        Object.keys(presenceMap || {}).forEach(fileId => {
            const users = presenceMap[fileId] || [];
            if (!users.length) return;
            const targets = document.querySelectorAll(`[data-item-type="file"][data-item-id="${fileId}"]`);
            targets.forEach(target => {
                let anchor = target.querySelector('.files-presence-anchor') || target.querySelector('.card-title, .fw-semibold, h6, .file-name');
                if (!anchor) anchor = target;
                const stack = document.createElement('span');
                stack.className = 'files-presence-stack';
                stack.title = users.map(u => u.display_name).join(', ');
                users.slice(0, 4).forEach(u => {
                    const av = document.createElement('span');
                    av.className = 'files-presence-avatar';
                    if (u.avatar_url) {
                        av.innerHTML = `<img src="${escapeHtml(u.avatar_url)}" alt="">`;
                    } else {
                        av.textContent = u.initials || '?';
                    }
                    stack.appendChild(av);
                });
                if (users.length > 4) {
                    const more = document.createElement('span');
                    more.className = 'files-presence-avatar';
                    more.textContent = '+' + (users.length - 4);
                    stack.appendChild(more);
                }
                anchor.appendChild(stack);
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
            const label = e.share_all ? (i18n.share_all || 'Mit allen') : (e.grantee_name || ('#' + e.grantee_user_id));
            const perm = e.permission === 'edit' ? (i18n.permission_edit || 'edit') : (i18n.permission_view || 'view');
            const gid = e.share_all ? 'all' : e.grantee_user_id;
            return `<div class="list-group-item d-flex justify-content-between align-items-center px-0">
                <span>${label} <span class="badge bg-secondary">${perm}</span></span>
                <button type="button" class="btn btn-sm btn-outline-danger" data-acl-remove="${gid}">${i18n.remove || 'Entfernen'}</button>
            </div>`;
        }).join('');
        list.querySelectorAll('[data-acl-remove]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const raw = btn.getAttribute('data-acl-remove');
                const body = { grantee_user_id: raw === 'all' ? null : Number(raw) };
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
        const res = await fetch(`/files/api/resource-acl/${type}/${id}`, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
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
        renderAclEntries(data.entries || []);
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
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
                    return submitUploadFormDataWithToast(formData, fileNames);
                };
            }
        }, 0);

        const shareAllBtn = document.getElementById('aclShareAllBtn');
        const shareUserBtn = document.getElementById('aclShareUserBtn');
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

        // Sidebar Neu dropdown (mirrors main Neu button behaviour)
        const sideBtn = document.getElementById('newButtonSidebar');
        const sideMenu = document.getElementById('newDropdownMenuSidebar');
        const sideWrap = document.getElementById('newButtonDropdownSidebar');
        if (sideBtn && sideMenu) {
            sideBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const open = sideMenu.style.display === 'block';
                sideMenu.style.display = open ? 'none' : 'block';
            });
            sideMenu.querySelectorAll('[data-pt-trigger-click]').forEach((item) => {
                item.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const sel = item.getAttribute('data-pt-trigger-click');
                    const trigger = sel ? document.querySelector(sel) : null;
                    sideMenu.style.display = 'none';
                    if (trigger) trigger.click();
                });
            });
            document.addEventListener('click', (e) => {
                if (sideWrap && sideWrap.contains(e.target)) return;
                sideMenu.style.display = 'none';
            });
        }

        document.querySelectorAll('form[action*="create-folder"]').forEach(form => {
            if (window.FILES_VIEW && !form.querySelector('input[name="view"]')) {
                const inp = document.createElement('input');
                inp.type = 'hidden';
                inp.name = 'view';
                inp.value = window.FILES_VIEW;
                form.appendChild(inp);
            }
        });

        const mobileBtn = document.getElementById('newButtonMobile');
        const mobileMenu = document.getElementById('newDropdownMenuMobile');
        const mobileWrap = document.getElementById('newButtonDropdownMobile');
        if (mobileBtn && mobileMenu) {
            mobileBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
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

        document.querySelectorAll('#filesMobileNav a.files-nav-link, #filesMobileNav a.files-favorite-link').forEach((link) => {
            link.addEventListener('click', () => {
                const el = document.getElementById('filesMobileNav');
                if (!el || !window.bootstrap || !bootstrap.Offcanvas) return;
                const oc = bootstrap.Offcanvas.getInstance(el);
                if (oc) oc.hide();
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
                const dismissAttr = dismiss ? ' data-bs-dismiss="offcanvas"' : '';
                const name = (fav.name || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                const url = fav.url || '#';
                return `<a class="nav-link files-nav-link files-favorite-link" href="${url}" data-folder-id="${fav.id}"${dismissAttr}>` +
                    `<i class="bi bi-folder-fill me-2 folder-color-icon${colorClass}"${colorStyle}></i>` +
                    `<span class="files-favorite-name text-truncate">${name}</span></a>`;
            }).join('');
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
