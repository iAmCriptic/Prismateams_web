/** Dateien-Browser: Upload, DnD, Suche, Inline-Create, Side-Menu (P09). */
'use strict';

const FILES_I18N = window.FILES_I18N || {};
const CURRENT_FOLDER_ID = window.CURRENT_FOLDER_ID ?? null;
const FILES_SHARING_ENABLED = !!window.FILES_SHARING_ENABLED;
const FILES_DROPBOX_ENABLED = !!window.FILES_DROPBOX_ENABLED;

(function () {
    const modalEl = document.getElementById('webdavConnectModal');
    if (modalEl && modalEl.parentElement !== document.body) {
        document.body.appendChild(modalEl);
    }
    if (modalEl) {
        modalEl.addEventListener('shown.bs.modal', () => {
            const backdrops = document.querySelectorAll('.modal-backdrop');
            const last = backdrops[backdrops.length - 1];
            if (last) {
                last.style.zIndex = '11040';
            }
            modalEl.style.zIndex = '11050';
        });
    }

    const copyBtn = document.getElementById('webdavCopyUrlBtn');
    const urlInput = document.getElementById('webdavConnectUrl');
    if (!copyBtn || !urlInput) {
        return;
    }
    copyBtn.addEventListener('click', async () => {
        const value = urlInput.value || '';
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(value);
            } else {
                urlInput.select();
                document.execCommand('copy');
            }
            const icon = copyBtn.querySelector('i');
            if (icon) {
                icon.className = 'bi bi-check2';
                setTimeout(() => { icon.className = 'bi bi-clipboard'; }, 1500);
            }
        } catch (err) {
            urlInput.select();
        }
    });
})();

(function () {
    function applyPayload(root, data) {
        if (!root || !data) {
            return;
        }
        const footer = root.closest('.files-storage-footer') || root;
        const quotaOn = !!data.quota_enabled;
        const hasLimit = !!(data.max_file_label || data.max_file_size);
        if (!quotaOn && !hasLimit) {
            footer.hidden = true;
            return;
        }
        footer.hidden = false;
        root.classList.toggle('files-storage-widget--quota', quotaOn);
        root.classList.toggle('is-warning', quotaOn && !!data.warning);

        const head = root.querySelector('.files-storage-widget__head');
        if (head) head.hidden = !quotaOn;

        const pct = Math.max(0, Math.min(100, Number(data.percent) || 0));
        const fill = root.querySelector('[data-storage-fill]');
        const bar = root.querySelector('[data-storage-bar]');
        const usage = root.querySelector('[data-storage-usage]');
        const limit = root.querySelector('[data-storage-limit]');
        const warn = root.querySelector('[data-storage-warn]');
        const i18n = (window.FILES_I18N && window.FILES_I18N.storage) || {};

        if (fill) {
            fill.style.width = quotaOn ? (pct + '%') : '0%';
        }
        if (bar) {
            bar.hidden = !quotaOn;
            bar.setAttribute('aria-valuenow', String(Math.round(pct)));
        }
        if (usage) {
            usage.hidden = !quotaOn;
            if (quotaOn) {
                const tpl = i18n.usage || '{used} / {quota} ({percent}%)';
                usage.textContent = tpl
                    .replace('{used}', data.used_label || '')
                    .replace('{quota}', data.quota_label || '')
                    .replace('{percent}', String(data.percent != null ? data.percent : Math.round(pct)).replace('.', ','));
            }
        }
        if (limit) {
            const tpl = i18n.file_limit || 'Dateigrößenlimit: {limit}';
            limit.textContent = tpl.replace('{limit}', data.max_file_label || '');
            limit.hidden = !hasLimit;
        }
        if (warn) {
            warn.hidden = !(quotaOn && data.warning);
        }
    }

    async function refreshFilesStorageWidgets() {
        const url = window.FILES_STORAGE_USAGE_URL;
        if (!url) return;
        try {
            const res = await fetch(url, {
                headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin',
            });
            if (!res.ok) return;
            const data = await res.json();
            document.querySelectorAll('[data-files-storage-widget]').forEach((el) => applyPayload(el, data));
            if (data && data.max_file_size) {
                window.FILES_MAX_UPLOAD_BYTES = data.max_file_size;
            }
        } catch (e) {
            /* ignore */
        }
    }

    window.refreshFilesStorageWidgets = refreshFilesStorageWidgets;
    document.addEventListener('DOMContentLoaded', refreshFilesStorageWidgets);
})();
document.addEventListener('DOMContentLoaded', function() {
    function isExternalFileDrag(event) {
        const types = Array.from(event?.dataTransfer?.types || []);
        return types.includes('Files');
    }

    // NEU Button Dropdown mit Hover-Funktionalität
    const newButton = document.getElementById('newButton');
    const newButtonDropdown = document.getElementById('newButtonDropdown');
    const newDropdownMenu = document.getElementById('newDropdownMenu');
    const uploadFileMenuItem = document.getElementById('uploadFileMenuItem');
    const uploadFolderMenuItem = document.getElementById('uploadFolderMenuItem');
    const directFileUpload = document.getElementById('directFileUpload');
    const directFolderUpload = document.getElementById('directFolderUpload');
    const uploadConflictModalEl = document.getElementById('uploadConflictModal');
    const uploadConflictNamesEl = document.getElementById('uploadConflictNames');
    const uploadConflictVersionBtn = document.getElementById('uploadConflictVersionBtn');
    const uploadConflictSeparateBtn = document.getElementById('uploadConflictSeparateBtn');
    const uploadConflictCancelBtn = document.getElementById('uploadConflictCancelBtn');
    const uploadConflictModal = uploadConflictModalEl ? new bootstrap.Modal(uploadConflictModalEl) : null;
    
    let hoverTimeout = null;
    let isMenuOpen = false;
    
    // Funktion zur Anpassung der Menü-Positionierung
    function adjustMenuPosition() {
        if (!newDropdownMenu || !newButton) return;
        
        // Positioniere Hauptmenü horizontal
        const buttonRect = newButton.getBoundingClientRect();
        const menuWidth = newDropdownMenu.offsetWidth || 200;
        const menuHeight = newDropdownMenu.offsetHeight || 300;
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        
        // Horizontal: Wenn nicht genug Platz rechts ist, positioniere nach rechts
        if (buttonRect.left + menuWidth > viewportWidth - 20) {
            newDropdownMenu.classList.add('position-right');
        } else {
            newDropdownMenu.classList.remove('position-right');
        }
        
        // Vertikal: Wenn nicht genug Platz unten ist, positioniere nach oben
        if (buttonRect.bottom + menuHeight > viewportHeight - 20) {
            newDropdownMenu.style.top = 'auto';
            newDropdownMenu.style.bottom = '100%';
            newDropdownMenu.style.marginTop = '0';
            newDropdownMenu.style.marginBottom = '0.5rem';
        } else {
            newDropdownMenu.style.top = '100%';
            newDropdownMenu.style.bottom = 'auto';
            newDropdownMenu.style.marginTop = '0.5rem';
            newDropdownMenu.style.marginBottom = '0';
        }
    }
    
    // Hover-Timeout für 2 Sekunden
    if (newButton && newDropdownMenu) {
        newButton.addEventListener('mouseenter', function() {
            clearTimeout(hoverTimeout);
            hoverTimeout = setTimeout(function() {
                if (!isMenuOpen) {
                    newDropdownMenu.style.display = 'block';
                    isMenuOpen = true;
                    // Position anpassen nach dem Anzeigen
                    setTimeout(adjustMenuPosition, 10);
                }
            }, 2000); // 2 Sekunden
        });
        
        newButton.addEventListener('mouseleave', function() {
            clearTimeout(hoverTimeout);
        });
        
        // Menü offen halten beim Hovern über das Menü
        newDropdownMenu.addEventListener('mouseenter', function() {
            clearTimeout(hoverTimeout);
        });
        
        newDropdownMenu.addEventListener('mouseleave', function() {
            hoverTimeout = setTimeout(function() {
                newDropdownMenu.style.display = 'none';
                isMenuOpen = false;
            }, 300);
        });
        
        // Klick auf Button öffnet/schließt auch das Menü
        newButton.addEventListener('click', function(e) {
            e.stopPropagation();
            if (isMenuOpen) {
                newDropdownMenu.style.display = 'none';
                isMenuOpen = false;
            } else {
                newDropdownMenu.style.display = 'block';
                isMenuOpen = true;
                // Position anpassen nach dem Anzeigen
                setTimeout(adjustMenuPosition, 10);
            }
        });
        
        // Schließe Menü beim Klicken außerhalb
        document.addEventListener('click', function(e) {
            if (!newButtonDropdown.contains(e.target)) {
                newDropdownMenu.style.display = 'none';
                isMenuOpen = false;
            }
        });

        // Wenn das globale Module-Menü geöffnet wird, NEU-Button vollständig ausblenden
        // damit er nicht in das Offcanvas hineinragt.
        const globalMoreMenu = document.getElementById('moreMenu');
        if (globalMoreMenu && newButtonDropdown) {
            globalMoreMenu.addEventListener('show.bs.offcanvas', function() {
                newDropdownMenu.style.display = 'none';
                isMenuOpen = false;
                newButtonDropdown.style.visibility = 'hidden';
            });

            globalMoreMenu.addEventListener('hidden.bs.offcanvas', function() {
                newButtonDropdown.style.visibility = '';
            });
        }
    }
    
    // Position beim Resize / Scroll anpassen (nur bei offenem Menü)
    window.addEventListener('resize', function() {
        if (isMenuOpen) {
            adjustMenuPosition();
        }
    });
    
    window.addEventListener('scroll', function() {
        if (isMenuOpen) {
            adjustMenuPosition();
        }
    }, true);
    
    // Direkter Upload-Dialog beim Klick auf "Dateien hochladen"
    if (uploadFileMenuItem) {
        uploadFileMenuItem.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            // Schließe das Dropdown-Menü
            newDropdownMenu.style.display = 'none';
            isMenuOpen = false;
            
            // Öffne direkt den File-Dialog für Dateien
            directFileUpload.click();
        });
    }
    
    // Direkter Upload-Dialog beim Klick auf "Ordner hochladen"
    if (uploadFolderMenuItem) {
        uploadFolderMenuItem.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            // Schließe das Dropdown-Menü
            newDropdownMenu.style.display = 'none';
            isMenuOpen = false;
            
            // Öffne direkt den File-Dialog für Ordner
            directFolderUpload.click();
        });
    }
    
    function openUploadConflictDialog(conflicts) {
        if (!uploadConflictModal || !uploadConflictNamesEl) {
            return Promise.resolve('cancel');
        }

        const conflictPreview = conflicts.slice(0, 8).join(', ');
        uploadConflictNamesEl.textContent = `${conflictPreview}${conflicts.length > 8 ? ', ...' : ''}`;

        return new Promise(resolve => {
            let resolved = false;

            const cleanup = () => {
                uploadConflictVersionBtn?.removeEventListener('click', onVersion);
                uploadConflictSeparateBtn?.removeEventListener('click', onSeparate);
                uploadConflictCancelBtn?.removeEventListener('click', onCancel);
                uploadConflictModalEl?.removeEventListener('hidden.bs.modal', onHidden);
            };

            const settle = (value) => {
                if (resolved) return;
                resolved = true;
                cleanup();
                resolve(value);
            };

            const onVersion = () => {
                uploadConflictModal.hide();
                settle('version');
            };
            const onSeparate = () => {
                uploadConflictModal.hide();
                settle('separate');
            };
            const onCancel = () => {
                uploadConflictModal.hide();
                settle('cancel');
            };
            const onHidden = () => settle('cancel');

            uploadConflictVersionBtn?.addEventListener('click', onVersion);
            uploadConflictSeparateBtn?.addEventListener('click', onSeparate);
            uploadConflictCancelBtn?.addEventListener('click', onCancel);
            uploadConflictModalEl?.addEventListener('hidden.bs.modal', onHidden, { once: true });
            uploadConflictModal.show();
        });
    }

    async function resolveConflictStrategy(fileNames) {
        if (!Array.isArray(fileNames) || fileNames.length === 0) {
            return '';
        }

        try {
            const response = await fetch(window.FILES_UPLOAD_CONFLICTS_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    folder_id: CURRENT_FOLDER_ID,
                    filenames: fileNames
                })
            });

            const result = await response.json().catch(() => ({}));
            if (!response.ok || !result.success) {
                return '';
            }

            const conflicts = Array.isArray(result.conflicts) ? result.conflicts : [];
            if (conflicts.length === 0) {
                return '';
            }

            return await openUploadConflictDialog(conflicts);
        } catch (error) {
            console.error('Conflict check error:', error);
            return '';
        }
    }

    async function submitUploadFormData(formData, fileNames) {
        if (typeof window.submitUploadFormDataWithToast === 'function') {
            return window.submitUploadFormDataWithToast(formData, fileNames);
        }
        const strategy = await resolveConflictStrategy(fileNames);
        if (strategy === 'cancel') {
            return;
        }
        if (strategy) {
            formData.append('conflict_strategy', strategy);
        }

        const response = await fetch(window.FILES_UPLOAD_URL, {
            method: 'POST',
            body: formData
        });

        if (response.redirected) {
            window.location.href = response.url;
            return;
        }

        const html = await response.text();
        if (html) {
            window.location.reload();
        }
    }
    window.submitUploadFormData = submitUploadFormData;
    window.resolveConflictStrategy = resolveConflictStrategy;

    // Handle file upload - verwende FormData für direkten Upload
    if (directFileUpload) {
        directFileUpload.addEventListener('change', async function() {
            if (this.files.length > 0) {
                const formData = new FormData();
                formData.append('folder_id', CURRENT_FOLDER_ID != null ? String(CURRENT_FOLDER_ID) : '');
                if (window.FILES_VIEW) formData.append('view', window.FILES_VIEW);
                if (window.FILES_TEAM_ID) formData.append('team_id', window.FILES_TEAM_ID);
                const fileNames = [];

                for (let i = 0; i < this.files.length; i++) {
                    const nextFile = this.files[i];
                    formData.append('file', nextFile);
                    fileNames.push(nextFile.name);
                }

                submitUploadFormData(formData, fileNames).catch(error => {
                    console.error('Upload error:', error);
                    if (typeof window.showAppBanner === 'function') {
                        window.showAppBanner(FILES_I18N.messages.upload_error, 'danger');
                    }
                });

                this.value = '';
            }
        });
    }
    
    // Handle folder upload - verwende FormData für direkten Upload
    if (directFolderUpload) {
        directFolderUpload.addEventListener('change', async function() {
            if (this.files.length > 0) {
                const formData = new FormData();
                formData.append('folder_id', CURRENT_FOLDER_ID != null ? String(CURRENT_FOLDER_ID) : '');
                if (window.FILES_VIEW) formData.append('view', window.FILES_VIEW);
                if (window.FILES_TEAM_ID) formData.append('team_id', window.FILES_TEAM_ID);
                const fileNames = [];

                for (let i = 0; i < this.files.length; i++) {
                    const nextFile = this.files[i];
                    formData.append('folder_upload', nextFile);
                    fileNames.push(nextFile.name);
                }

                submitUploadFormData(formData, fileNames).catch(error => {
                    console.error('Upload error:', error);
                    if (typeof window.showAppBanner === 'function') {
                        window.showAppBanner(FILES_I18N.messages.upload_folder_error, 'danger');
                    }
                });

                this.value = '';
            }
        });
    }

    function showDnDMessage(message, type = 'warning') {
        if (typeof window.showAppBanner === 'function') {
            window.showAppBanner(message, type);
            return;
        }
        const alert = document.createElement('div');
        alert.className = `alert alert-${type} files-toast-message`;
        alert.innerText = message;
        document.body.appendChild(alert);
        setTimeout(() => alert.classList.add('show'), 10);
        setTimeout(() => {
            alert.classList.remove('show');
            setTimeout(() => alert.remove(), 250);
        }, 2600);
    }

    function clearDropHighlights() {
        document.querySelectorAll('.files-drop-active').forEach(el => el.classList.remove('files-drop-active'));
    }

    function getDropTargetInfo(dropTarget) {
        if (!dropTarget) {
            return {
                target_folder_id: CURRENT_FOLDER_ID,
                view: window.FILES_VIEW || undefined,
                team_id: window.FILES_TEAM_ID || undefined
            };
        }
        const spaceTarget = dropTarget.closest('[data-drop-target="space"]');
        if (spaceTarget) {
            const view = spaceTarget.dataset.dropView || 'public';
            const teamRaw = spaceTarget.dataset.dropTeamId;
            return {
                target_folder_id: null,
                view,
                team_id: teamRaw ? parseInt(teamRaw, 10) : undefined
            };
        }
        const folderTarget = dropTarget.closest('[data-drop-target="folder"][data-item-id]');
        if (folderTarget) {
            const rawId = folderTarget.dataset.itemId;
            let targetFolderId = CURRENT_FOLDER_ID;
            if (rawId === '' || rawId === 'null' || rawId === undefined) {
                targetFolderId = null;
            } else {
                targetFolderId = parseInt(rawId, 10);
            }
            return {
                target_folder_id: targetFolderId,
                view: window.FILES_VIEW || undefined,
                team_id: window.FILES_TEAM_ID || undefined
            };
        }
        return {
            target_folder_id: CURRENT_FOLDER_ID,
            view: window.FILES_VIEW || undefined,
            team_id: window.FILES_TEAM_ID || undefined
        };
    }

    function getDropTargetFolderId(dropTarget) {
        return getDropTargetInfo(dropTarget).target_folder_id;
    }

    function createRollbackState(itemType, itemId) {
        const selector = `[data-item-wrapper="${itemType}"][data-item-id="${itemId}"]`;
        const nodes = Array.from(document.querySelectorAll(selector));
        return nodes.map(node => ({
            node,
            parent: node.parentNode,
            nextSibling: node.nextSibling
        }));
    }

    function applyOptimisticHide(rollbackState) {
        rollbackState.forEach(entry => {
            if (entry.node && entry.node.parentNode) {
                entry.node.parentNode.removeChild(entry.node);
            }
        });
    }

    function rollbackNodes(rollbackState) {
        rollbackState.forEach(entry => {
            if (!entry.parent || !entry.node) return;
            if (entry.nextSibling && entry.nextSibling.parentNode === entry.parent) {
                entry.parent.insertBefore(entry.node, entry.nextSibling);
            } else {
                entry.parent.appendChild(entry.node);
            }
        });
    }

    async function moveItemViaApi(payload, rollbackState) {
        applyOptimisticHide(rollbackState);
        try {
            const response = await fetch(window.FILES_MOVE_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok || !result.success) {
                rollbackNodes(rollbackState);
                showDnDMessage(result.error || FILES_I18N.messages.move_error || 'Verschieben fehlgeschlagen.', 'danger');
                return;
            }
            showDnDMessage(FILES_I18N.messages.move_success || 'Element verschoben.', 'success');
            window.location.reload();
        } catch (error) {
            rollbackNodes(rollbackState);
            showDnDMessage(FILES_I18N.messages.move_error || 'Verschieben fehlgeschlagen.', 'danger');
        }
    }

    async function appendEntryFiles(entry, formData, currentPath = '') {
        if (!entry) return;
        if (entry.isFile) {
            await new Promise(resolve => {
                entry.file(file => {
                    const safePath = currentPath ? `${currentPath}/${file.name}` : file.name;
                    formData.append('folder_upload', file, safePath);
                    resolve();
                }, () => resolve());
            });
            return;
        }
        if (entry.isDirectory) {
            const reader = entry.createReader();
            const entries = await new Promise(resolve => reader.readEntries(resolve, () => resolve([])));
            for (const child of entries) {
                const nextPath = currentPath ? `${currentPath}/${entry.name}` : entry.name;
                await appendEntryFiles(child, formData, nextPath);
            }
        }
    }

    async function uploadDroppedContent(event) {
        const dataTransfer = event.dataTransfer;
        if (!dataTransfer) return;
        const formData = new FormData();
        formData.append('folder_id', CURRENT_FOLDER_ID ?? '');
        if (window.FILES_VIEW) formData.append('view', window.FILES_VIEW);
        if (window.FILES_TEAM_ID) formData.append('team_id', window.FILES_TEAM_ID);
        const fileNames = Array.from(dataTransfer.files || []).map(file => file.name);

        const items = Array.from(dataTransfer.items || []);
        let hasDirectoryEntries = false;
        for (const item of items) {
            if (item.kind === 'file' && typeof item.webkitGetAsEntry === 'function') {
                const entry = item.webkitGetAsEntry();
                if (entry && entry.isDirectory) {
                    hasDirectoryEntries = true;
                    await appendEntryFiles(entry, formData, '');
                }
            }
        }

        if (!hasDirectoryEntries) {
            const files = Array.from(dataTransfer.files || []);
            files.forEach(file => formData.append('file', file));
        }

        try {
            await submitUploadFormData(formData, fileNames);
        } catch (error) {
            showDnDMessage(FILES_I18N.messages.upload_drag_error || FILES_I18N.messages.upload_error, 'danger');
        }
    }

    const dndMimeType = 'application/x-prismateams-item';
    const draggableItems = document.querySelectorAll('.files-draggable-item[data-item-type][data-item-id]');
    const dropZones = [
        ...Array.from(document.querySelectorAll('.files-drop-target')),
        document.getElementById('foldersListView'),
        document.getElementById('gridView'),
        document.getElementById('filesListTableBody'),
        document.getElementById('listViewContainer')
    ].filter(Boolean);

    draggableItems.forEach(item => {
        item.addEventListener('dragstart', event => {
            if (event.target.closest('.dropdown, a, form, input, textarea, [data-bs-toggle="dropdown"]')) {
                event.preventDefault();
                return;
            }
            const blockedBtn = event.target.closest('.btn');
            if (blockedBtn && !blockedBtn.classList.contains('files-dnd-handle')) {
                event.preventDefault();
                return;
            }
            const itemType = item.dataset.itemType;
            const itemId = item.dataset.itemId;
            if (!itemType || !itemId) {
                event.preventDefault();
                return;
            }
            const payload = JSON.stringify({ item_type: itemType, item_id: parseInt(itemId, 10) });
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData(dndMimeType, payload);
            document.body.classList.add('files-dnd-dragging');
        });
        item.addEventListener('dragend', () => {
            clearDropHighlights();
            document.body.classList.remove('files-dnd-dragging');
        });
    });

    dropZones.forEach(zone => {
        zone.addEventListener('dragover', event => {
            event.preventDefault();
            const isInternal = Array.from(event.dataTransfer.types || []).includes(dndMimeType);
            if (isInternal || (event.dataTransfer.files && event.dataTransfer.files.length > 0)) {
                clearDropHighlights();
                const activeTarget = event.target.closest('.files-drop-target') || (zone.classList.contains('files-drop-target') ? zone : null);
                if (activeTarget) {
                    activeTarget.classList.add('files-drop-active');
                }
            }
        });

        zone.addEventListener('dragleave', event => {
            if (!zone.contains(event.relatedTarget)) {
                zone.classList.remove('files-drop-active');
            }
        });

        zone.addEventListener('drop', async event => {
            event.preventDefault();
            event.stopPropagation();
            clearDropHighlights();
            document.body.classList.remove('files-dnd-dragging');

            const internalPayloadRaw = event.dataTransfer.getData(dndMimeType);
            if (internalPayloadRaw) {
                let parsed;
                try {
                    parsed = JSON.parse(internalPayloadRaw);
                } catch (e) {
                    showDnDMessage(FILES_I18N.errors.move_invalid_request || 'Ungültige Verschiebe-Anfrage.', 'danger');
                    return;
                }

                const dropInfo = getDropTargetInfo(event.target);
                const rollbackState = createRollbackState(parsed.item_type, String(parsed.item_id));
                await moveItemViaApi({
                    item_type: parsed.item_type,
                    item_id: parsed.item_id,
                    target_folder_id: dropInfo.target_folder_id,
                    view: dropInfo.view,
                    team_id: dropInfo.team_id
                }, rollbackState);
                return;
            }

            if (event.dataTransfer.files && event.dataTransfer.files.length > 0) {
                await uploadDroppedContent(event);
            }
        });
    });

    document.addEventListener('dragover', event => {
        if (isExternalFileDrag(event)) {
            event.preventDefault();
            event.dataTransfer.dropEffect = 'copy';
        }
    });

    document.addEventListener('drop', async event => {
        if (event.defaultPrevented) {
            return;
        }
        if (!isExternalFileDrag(event)) {
            return;
        }

        const droppedInInternalZone = event.target.closest('.files-drop-target, #foldersListView, #gridView, #filesListTableBody, #listViewContainer');
        if (droppedInInternalZone) {
            return;
        }

        event.preventDefault();
        await uploadDroppedContent(event);
    });

    // Sicherheitsnetz: verhindert Browser-"Datei öffnen" überall im sichtbaren Bereich.
    window.addEventListener('dragover', event => {
        if (isExternalFileDrag(event)) {
            event.preventDefault();
            event.dataTransfer.dropEffect = 'copy';
        }
    });

    window.addEventListener('drop', async event => {
        if (!isExternalFileDrag(event)) {
            return;
        }

        const alreadyHandled = event.defaultPrevented;
        event.preventDefault();

        // Interne Drop-Zonen wurden bereits behandelt.
        if (alreadyHandled) {
            return;
        }

        await uploadDroppedContent(event);
    });
    
    // Leerer Ordner: Überschriften / Empty-State steuern
    function getFilesContentMeta() {
        const meta = document.getElementById('filesContentMeta');
        return {
            hasFolders: meta && meta.dataset.hasFolders === '1',
            hasFiles: meta && meta.dataset.hasFiles === '1'
        };
    }

    function setFilesEmptyStateVisible(visible) {
        document.querySelectorAll('.mod-empty-state').forEach(function(el) {
            el.style.display = visible ? '' : 'none';
        });
    }

    function restoreFilesSectionHeadings() {
        const meta = getFilesContentMeta();
        setFilesEmptyStateVisible(!meta.hasFolders && !meta.hasFiles);
    }

    function hideInlineCreatePanels() {
        const folderGrid = document.getElementById('inlineFolderCreateGrid');
        const folderList = document.getElementById('inlineFolderCreateList');
        const fileGrid = document.getElementById('inlineFileCreateGrid');
        const fileList = document.getElementById('inlineFileCreateList');
        if (folderGrid) folderGrid.style.display = 'none';
        if (folderList) folderList.style.display = 'none';
        if (fileGrid) fileGrid.style.display = 'none';
        if (fileList) fileList.style.display = 'none';
        restoreFilesSectionHeadings();
    }

    // Inline-Erstellung Funktionen
    function showInlineCreate(type, fileType) {
        // Schließe Dropdown-Menü
        newDropdownMenu.style.display = 'none';
        isMenuOpen = false;
        
        // Bestimme aktuelle Ansicht
        const isGridView = gridViewBtn.classList.contains('active');
        setFilesEmptyStateVisible(false);
        
        if (type === 'folder') {
            // Zeige Inline-Ordner-Erstellung
            if (isGridView) {
                document.getElementById('inlineFolderCreateGrid').style.display = '';
            } else {
                document.getElementById('inlineFolderCreateList').style.display = 'block';
            }
            // Fokus auf Eingabefeld
            setTimeout(function() {
                const input = document.querySelector('#inlineFolderCreateGrid input[name="folder_name"], #inlineFolderCreateList input[name="folder_name"]');
                if (input) input.focus();
            }, 100);
        } else if (type === 'file') {
            // Zeige Inline-Datei-Erstellung
            const formGrid = document.getElementById('inlineFileForm');
            const formList = document.getElementById('inlineFileFormList');
            const iconGrid = document.getElementById('inlineFileIcon');
            const iconList = document.getElementById('inlineFileIconList');
            
            // Setze Formular-Action und Icon basierend auf Dateityp
            let actionUrl = '';
            let iconClass = '';
            let placeholder = FILES_I18N.inline.file_name_placeholder;
            
            if (fileType === 'docx' || fileType === 'odt') {
                actionUrl = window.FILES_CREATE_OFFICE_URL;
                iconClass = 'bi-file-earmark-word text-primary';
                placeholder = FILES_I18N.inline.document_name_placeholder;
            } else if (fileType === 'xlsx' || fileType === 'ods') {
                actionUrl = window.FILES_CREATE_OFFICE_URL;
                iconClass = 'bi-file-earmark-spreadsheet text-success';
                placeholder = FILES_I18N.inline.spreadsheet_name_placeholder;
            } else if (fileType === 'pptx' || fileType === 'odp') {
                actionUrl = window.FILES_CREATE_OFFICE_URL;
                iconClass = 'bi-file-earmark-slides text-warning';
                placeholder = FILES_I18N.inline.presentation_name_placeholder;
            } else if (fileType === 'md') {
                actionUrl = window.FILES_CREATE_FILE_URL;
                iconClass = 'bi-file-earmark-text text-info';
                placeholder = FILES_I18N.inline.markdown_name_placeholder;
            }
            
            if (formGrid && formList) {
                formGrid.action = actionUrl;
                formList.action = actionUrl;
                
                // Füge file_type hinzu wenn Office-/OpenDocument-Datei
                if (['docx', 'xlsx', 'pptx', 'odt', 'ods', 'odp'].includes(fileType)) {
                    let typeInputGrid = formGrid.querySelector('input[name="file_type"]');
                    let typeInputList = formList.querySelector('input[name="file_type"]');
                    if (!typeInputGrid) {
                        typeInputGrid = document.createElement('input');
                        typeInputGrid.type = 'hidden';
                        typeInputGrid.name = 'file_type';
                        formGrid.appendChild(typeInputGrid);
                    }
                    if (!typeInputList) {
                        typeInputList = document.createElement('input');
                        typeInputList.type = 'hidden';
                        typeInputList.name = 'file_type';
                        formList.appendChild(typeInputList);
                    }
                    typeInputGrid.value = fileType;
                    typeInputList.value = fileType;
                } else if (fileType === 'md') {
                    let typeInputGrid = formGrid.querySelector('input[name="file_type"]');
                    let typeInputList = formList.querySelector('input[name="file_type"]');
                    if (!typeInputGrid) {
                        typeInputGrid = document.createElement('input');
                        typeInputGrid.type = 'hidden';
                        typeInputGrid.name = 'file_type';
                        formGrid.appendChild(typeInputGrid);
                    }
                    if (!typeInputList) {
                        typeInputList = document.createElement('input');
                        typeInputList.type = 'hidden';
                        typeInputList.name = 'file_type';
                        formList.appendChild(typeInputList);
                    }
                    typeInputGrid.value = 'md';
                    typeInputList.value = 'md';
                }
                
                // Setze Placeholder
                formGrid.querySelector('input[name="filename"]').placeholder = placeholder;
                formList.querySelector('input[name="filename"]').placeholder = placeholder;
                
                // Setze Icon
                if (iconGrid) iconGrid.className = 'bi ' + iconClass + ' fs-1';
                if (iconList) iconList.className = 'bi ' + iconClass + ' fs-4';
            }
            
            if (isGridView) {
                document.getElementById('inlineFileCreateGrid').style.display = '';
            } else {
                document.getElementById('inlineFileCreateList').style.display = 'block';
            }
            
            // Fokus auf Eingabefeld
            setTimeout(function() {
                const input = document.querySelector('#inlineFileCreateGrid input[name="filename"], #inlineFileCreateList input[name="filename"]');
                if (input) input.focus();
            }, 100);
        }
    }
    
    // Event Listener für Erstellungs-Optionen
    document.getElementById('createFolderMenuItem')?.addEventListener('click', function(e) {
        e.preventDefault();
        showInlineCreate('folder');
    });
    
    document.getElementById('createMdMenuItem')?.addEventListener('click', function(e) {
        e.preventDefault();
        showInlineCreate('file', 'md');
    });
    
    // Office-Dateien
    document.querySelectorAll('[data-create-type]').forEach(function(item) {
        item.addEventListener('click', function(e) {
            e.preventDefault();
            const fileType = this.getAttribute('data-create-type');
            showInlineCreate('file', fileType);
        });
    });
    
    // Abbrechen-Buttons
    document.querySelectorAll('.cancel-inline-create').forEach(function(btn) {
        btn.addEventListener('click', function() {
            hideInlineCreatePanels();
        });
    });
    
    // ESC-Taste zum Abbrechen
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            const isVisible = (el) => el && el.style.display !== 'none' && getComputedStyle(el).display !== 'none';
            if (isVisible(document.getElementById('inlineFolderCreateGrid')) ||
                isVisible(document.getElementById('inlineFolderCreateList')) ||
                isVisible(document.getElementById('inlineFileCreateGrid')) ||
                isVisible(document.getElementById('inlineFileCreateList'))) {
                hideInlineCreatePanels();
            }
        }
    });
    
    // View mode toggle
    function isInlinePanelOpen(el) {
        return el && el.style.display !== 'none' && window.getComputedStyle(el).display !== 'none';
    }

    function switchInlineCreatePanels(mode) {
        const inlineFolderGrid = document.getElementById('inlineFolderCreateGrid');
        const inlineFolderList = document.getElementById('inlineFolderCreateList');
        const inlineFileGrid = document.getElementById('inlineFileCreateGrid');
        const inlineFileList = document.getElementById('inlineFileCreateList');

        if (mode === 'list') {
            if (isInlinePanelOpen(inlineFolderGrid)) {
                inlineFolderGrid.style.display = 'none';
                if (inlineFolderList) inlineFolderList.style.display = 'block';
            }
            if (isInlinePanelOpen(inlineFileGrid)) {
                inlineFileGrid.style.display = 'none';
                if (inlineFileList) inlineFileList.style.display = 'block';
            }
        } else {
            if (inlineFolderList && inlineFolderList.style.display === 'block') {
                inlineFolderList.style.display = 'none';
                if (inlineFolderGrid) inlineFolderGrid.style.display = '';
            }
            if (inlineFileList && inlineFileList.style.display === 'block') {
                inlineFileList.style.display = 'none';
                if (inlineFileGrid) inlineFileGrid.style.display = '';
            }
        }
    }

    if (typeof window.initFilesViewToggle === 'function') {
        window.initFilesViewToggle({
            toggleEl: document.querySelector('.mod-toolbar .mod-view-toggle'),
            listBtn: document.getElementById('listViewBtn'),
            gridBtn: document.getElementById('gridViewBtn'),
            listPane: document.getElementById('listViewWrapper'),
            gridPane: document.getElementById('gridViewContainer'),
            stageEl: document.getElementById('filesViewStage'),
            storageKey: 'filesViewMode',
            defaultMode: 'grid',
            onSwitch: switchInlineCreatePanels,
        });
    }

    // Lokale Suche im aktuellen Ordner (Grid + Liste)
    (function initFilesSearch() {
        const inputs = [
            document.getElementById('filesSearchInput'),
            document.getElementById('filesSearchInputMobile'),
        ].filter(Boolean);
        const clearBtns = [
            document.getElementById('filesSearchClear'),
            document.getElementById('filesSearchClearMobile'),
        ].filter(Boolean);
        const emptyHint = document.getElementById('filesSearchEmpty');
        if (!inputs.length) return;

        function applyFilesSearch(rawQuery) {
            const query = (rawQuery || '').trim().toLowerCase();
            clearBtns.forEach(function(clearBtn) {
                clearBtn.classList.toggle('d-none', !query);
            });

            const items = document.querySelectorAll('[data-search-name]');
            let visibleCount = 0;
            items.forEach(function(el) {
                const name = (el.getAttribute('data-search-name') || '').toLowerCase();
                const match = !query || name.includes(query);
                el.classList.toggle('d-none', !match);
                if (match) visibleCount += 1;
            });

            const hasItems = items.length > 0;
            if (emptyHint) {
                emptyHint.classList.toggle('d-none', !(query && hasItems && visibleCount === 0));
            }
        }

        inputs.forEach(function(input) {
            input.addEventListener('input', function() {
                const value = input.value;
                inputs.forEach(function(other) {
                    if (other !== input) other.value = value;
                });
                applyFilesSearch(value);
            });
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Escape' && input.value) {
                    e.preventDefault();
                    inputs.forEach(function(el) { el.value = ''; });
                    applyFilesSearch('');
                }
            });
        });

        clearBtns.forEach(function(clearBtn) {
            clearBtn.addEventListener('click', function() {
                inputs.forEach(function(el) { el.value = ''; });
                applyFilesSearch('');
                const visible = inputs.find(function(el) { return el.offsetParent !== null; }) || inputs[0];
                if (visible) visible.focus();
            });
        });

        document.addEventListener('lazy-more:loaded', function() {
            const hasItems = document.querySelector('#gridView [data-lazy-item], #filesListTableBody [data-lazy-item]');
            if (hasItems) {
                ['filesEmptyStateGrid', 'filesEmptyStateList'].forEach(function(id) {
                    const el = document.getElementById(id);
                    if (el) el.hidden = true;
                });
                const listWrap = document.querySelector('#listViewContainer .mod-list-table-wrap');
                if (listWrap) listWrap.hidden = false;
            }
            const active = inputs.find(function(el) { return el.value; }) || inputs[0];
            applyFilesSearch(active ? active.value : '');
        });
    })();
    
    // File size validation
    const fileInput = document.getElementById('file');
    const folderInput = document.getElementById('folder_upload');
    const uploadForm = document.getElementById('uploadForm');
    const uploadBtn = document.getElementById('uploadBtn');
    const uploadProgress = document.getElementById('uploadProgress');
    const maxSize = Number(window.FILES_MAX_UPLOAD_BYTES) || (100 * 1024 * 1024);
    
    function validateUpload() {
        let hasValidInput = false;
        
        // Check single file input
        if (fileInput && fileInput.files.length > 0) {
            const file = fileInput.files[0];
            if (file.size > maxSize) {
                if (typeof window.showAppBanner === 'function') {
                    window.showAppBanner(FILES_I18N.messages.file_too_large, 'danger');
                }
                fileInput.value = '';
                uploadBtn.disabled = true;
                return;
            }
            hasValidInput = true;
        }
        
        // Check folder input
        if (folderInput && folderInput.files.length > 0) {
            hasValidInput = true;
        }
        
        uploadBtn.disabled = !hasValidInput;
    }
    
    if (fileInput) {
        fileInput.addEventListener('change', function() {
            if (folderInput && folderInput.files.length > 0) {
                folderInput.value = '';
            }
            validateUpload();
        });
    }
    
    if (folderInput) {
        folderInput.addEventListener('change', function() {
            if (fileInput && fileInput.files.length > 0) {
                fileInput.value = '';
            }
            validateUpload();
        });
    }
    
    // Upload with real progress toast
    if (uploadForm) {
        uploadForm.addEventListener('submit', function(e) {
            e.preventDefault();
            if ((!fileInput || fileInput.files.length === 0) &&
                (!folderInput || folderInput.files.length === 0)) {
                if (typeof window.showAppBanner === 'function') {
                    window.showAppBanner(FILES_I18N.messages.select_prompt, 'warning');
                }
                return;
            }

            const formData = new FormData(uploadForm);
            const names = [];
            if (fileInput && fileInput.files.length) {
                Array.from(fileInput.files).forEach(f => names.push(f.name));
            }
            if (folderInput && folderInput.files.length) {
                Array.from(folderInput.files).forEach(f => names.push(f.name));
            }
            uploadBtn.disabled = true;
            uploadBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Hochladen...';
            const modalEl = document.getElementById('uploadModal');
            if (modalEl) {
                const inst = bootstrap.Modal.getInstance(modalEl);
                if (inst) inst.hide();
            }
            const runner = window.submitUploadFormDataWithToast || window.submitUploadFormData;
            if (typeof runner === 'function') {
                runner(formData, names).finally(() => {
                    uploadBtn.disabled = false;
                    uploadBtn.innerHTML = '<i class="bi bi-upload"></i> ' + (FILES_I18N.modals?.upload?.submit || 'Hochladen');
                });
            } else {
                uploadForm.submit();
            }
        });
    }
    
    // Mobile: Scroll-Inertia; ⋮-Menüs laufen global über context-menu.js (Action Sheet)
    if (window.innerWidth <= 768) {
        document.body.style.webkitOverflowScrolling = 'touch';
    }
});

// Side Menu Funktionen
function openFileDetails(fileId) {
    const sideMenu = document.getElementById('sideMenu');
    const backdrop = document.getElementById('sideMenuBackdrop');
    const content = document.getElementById('sideMenuContent');
    const title = document.getElementById('sideMenuTitle');
    
    // Zeige Loading-Status
    content.innerHTML = `
        <div class="text-center py-4">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">${(FILES_I18N.messages && FILES_I18N.messages.progress) || ''}</span>
            </div>
            <p class="mt-2 text-muted">Lade Datei-Details...</p>
        </div>
    `;
    
    // Zeige das Side-Menü
    sideMenu.classList.add('show');
    backdrop.classList.add('show');
    document.body.style.overflow = 'hidden';
    
    // Lade echte Datei-Details
    fetch(`/files/api/file-details/${fileId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const file = data.file;
                const versions = data.versions;
                const actions = data.actions;
                
                const sideMenuLabels = FILES_I18N.modals.side_menu;
                content.innerHTML = `
                    <div class="mb-4">
                        <h6>${sideMenuLabels.info_title}</h6>
                        <div class="mod-details-card">
                            <p><strong>${sideMenuLabels.info_labels.name}:</strong> ${file.name}</p>
                            <p><strong>${sideMenuLabels.info_labels.size}:</strong> ${file.size}</p>
                            <p><strong>${sideMenuLabels.info_labels.type}:</strong> ${file.type}</p>
                            <p><strong>${sideMenuLabels.info_labels.uploader}:</strong> ${file.uploader}</p>
                            <p><strong>${sideMenuLabels.info_labels.created}:</strong> ${file.created_at}</p>
                            <p><strong>${sideMenuLabels.info_labels.version}:</strong> ${file.version}</p>
                        </div>
                    </div>
                    
                    <div class="mb-4">
                        <h6>${sideMenuLabels.versions_title}</h6>
                        <div id="versionsList">
                            ${versions.length > 0 ? `
                                <div class="list-group list-group-flush">
                                    ${versions.map(version => `
                                        <div class="list-group-item d-flex justify-content-between align-items-center">
                                            <div>
                                                <i class="bi bi-clock-history me-2"></i>
                                                ${sideMenuLabels.version_label.replace('{number}', version.version_number)}${version.is_current ? sideMenuLabels.current_suffix : ''}
                                            </div>
                                            <a href="${version.download_url}" class="btn btn-sm btn-outline-primary mod-pill-btn">
                                                <i class="bi bi-download"></i> ${sideMenuLabels.download_button}
                                            </a>
                                        </div>
                                    `).join('')}
                                </div>
                            ` : `
                                <div class="files-hint files-hint--info" role="status">
                                    <span class="files-hint__icon"><i class="bi bi-info-circle"></i></span>
                                    <span class="files-hint__text">${sideMenuLabels.no_versions}</span>
                                </div>
                            `}
                        </div>
                    </div>
                    
                    <div class="mb-4">
                        <h6>${sideMenuLabels.actions_title}</h6>
                        <div class="d-grid gap-2">
                            <a href="${actions.download_url}" class="btn btn-outline-primary mod-pill-btn">
                                <i class="bi bi-download"></i> ${sideMenuLabels.download}
                            </a>
                            ${actions.view_url ? `
                                <a href="${actions.view_url}" class="btn btn-outline-secondary mod-pill-btn">
                                    <i class="bi bi-eye"></i> ${sideMenuLabels.view}
                                </a>
                            ` : ''}
                            ${actions.edit_url ? `
                                <a href="${actions.edit_url}" class="btn btn-outline-secondary mod-pill-btn">
                                    <i class="bi bi-pencil"></i> ${sideMenuLabels.edit}
                                </a>
                            ` : ''}
                        </div>
                    </div>
                `;
            } else {
                content.innerHTML = `
                    <div class="files-hint files-hint--danger" role="alert">
                        <span class="files-hint__icon"><i class="bi bi-exclamation-triangle"></i></span>
                        <span class="files-hint__text">${FILES_I18N.messages.file_details_error}</span>
                    </div>
                `;
            }
        })
        .catch(error => {
            console.error('Error loading file details:', error);
            content.innerHTML = `
                <div class="files-hint files-hint--danger" role="alert">
                    <span class="files-hint__icon"><i class="bi bi-exclamation-triangle"></i></span>
                    <span class="files-hint__text">${FILES_I18N.messages.file_details_error}: ${error.message}</span>
                </div>
            `;
        });
}

function closeFileDetails() {
    const sideMenu = document.getElementById('sideMenu');
    const backdrop = document.getElementById('sideMenuBackdrop');
    
    sideMenu.classList.remove('show');
    backdrop.classList.remove('show');
    document.body.style.overflow = '';
}

// Briefkasten Einstellungen
function openDropboxSettings(folderId) {
    closeActiveMenus();
    const modal = new bootstrap.Modal(document.getElementById('dropboxSettingsModal'));
    const content = document.getElementById('dropboxSettingsContent');
    const dropboxLabels = FILES_I18N.modals.dropbox;
    
    // Show loading
    content.innerHTML = `
        <div class="text-center py-4">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">${FILES_I18N.messages.progress}</span>
            </div>
        </div>
    `;
    
    modal.show();
    
    // Load settings
    fetch(`/files/folder/${folderId}/dropbox-settings`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const folder = data.folder;
                content.innerHTML = `
                    <div class="files-settings-section">
                        <h6>${dropboxLabels.link_label}</h6>
                        <div class="input-group">
                            <input type="text" class="form-control" id="dropboxUrl" value="${folder.dropbox_url}" readonly>
                            <button class="btn btn-outline-secondary" type="button" onclick="copyDropboxUrl()">
                                <i class="bi bi-clipboard"></i> ${dropboxLabels.copy_button}
                            </button>
                        </div>
                        <div class="form-text">${dropboxLabels.info_text}</div>
                    </div>
                    
                    <div class="files-settings-section">
                        <h6>${dropboxLabels.password_section}</h6>
                        ${folder.has_password ? `
                            <div class="files-hint files-hint--info" role="status">
                                <span class="files-hint__icon"><i class="bi bi-info-circle"></i></span>
                                <span class="files-hint__text">${dropboxLabels.password_enabled}</span>
                            </div>
                            <form method="POST" action="/files/folder/${folderId}/dropbox-settings" class="mb-2">
                                <input type="hidden" name="action" value="remove_password">
                                <button type="submit" class="btn btn-outline-danger mod-pill-btn">
                                    <i class="bi bi-x-circle"></i> ${dropboxLabels.password_remove}
                                </button>
                            </form>
                        ` : ''}
                        <form method="POST" action="/files/folder/${folderId}/dropbox-settings">
                            <input type="hidden" name="action" value="set_password">
                            <div class="mb-3">
                                <label for="dropboxPassword" class="form-label">${folder.has_password ? dropboxLabels.password_label_change : dropboxLabels.password_label_set}</label>
                                <input type="password" class="form-control" id="dropboxPassword" name="password" placeholder="${dropboxLabels.password_keep_hint}">
                            </div>
                            <button type="submit" class="btn btn-primary">
                                <i class="bi bi-key"></i> ${folder.has_password ? dropboxLabels.password_change : dropboxLabels.password_set}
                            </button>
                        </form>
                    </div>
                    
                    <div class="files-settings-section">
                        <h6>${dropboxLabels.regenerate_title}</h6>
                        <form method="POST" action="/files/folder/${folderId}/dropbox-settings">
                            <input type="hidden" name="action" value="regenerate_token">
                            <button type="submit" class="btn btn-outline-warning">
                                <i class="bi bi-arrow-clockwise"></i> ${dropboxLabels.regenerate}
                            </button>
                        </form>
                        <div class="form-text text-warning">${dropboxLabels.regenerate_hint}</div>
                    </div>
                    
                    <div class="files-settings-section">
                        <h6>${dropboxLabels.disable_title}</h6>
                        <form method="POST" action="/files/folder/${folderId}/disable-dropbox">
                            <button type="submit" class="btn btn-outline-danger" data-confirm-delete="${FILES_I18N.alerts.dropbox_disable}">
                                <i class="bi bi-x-circle"></i> ${dropboxLabels.disable}
                            </button>
                        </form>
                    </div>
                `;
            } else {
                content.innerHTML = `
                    <div class="files-hint files-hint--danger" role="alert">
                        <span class="files-hint__icon"><i class="bi bi-exclamation-triangle"></i></span>
                        <span class="files-hint__text">${FILES_I18N.messages.settings_error}</span>
                    </div>
                `;
            }
        })
        .catch(error => {
            console.error('Error loading dropbox settings:', error);
            content.innerHTML = `
                <div class="files-hint files-hint--danger" role="alert">
                    <span class="files-hint__icon"><i class="bi bi-exclamation-triangle"></i></span>
                    <span class="files-hint__text">${FILES_I18N.messages.settings_error}: ${error.message}</span>
                </div>
            `;
        });
}

function copyDropboxUrl() {
    const urlInput = document.getElementById('dropboxUrl');
    urlInput.select();
    document.execCommand('copy');
    
    // Show feedback
    const btn = event.target.closest('button');
    const originalHTML = btn.innerHTML;
    btn.innerHTML = `<i class="bi bi-check"></i> ${FILES_I18N.modals.dropbox.copy_success}`;
    btn.classList.add('btn-success');
    btn.classList.remove('btn-outline-secondary');
    
    setTimeout(() => {
        btn.innerHTML = originalHTML;
        btn.classList.remove('btn-success');
        btn.classList.add('btn-outline-secondary');
    }, 2000);
}

// ===== Inline umbenennen (kein Modal/Backdrop) =====
let _inlineRenameActive = null;

function cancelInlineRename() {
    if (!_inlineRenameActive) return;
    const { el, restoreHtml } = _inlineRenameActive;
    if (el) el.outerHTML = restoreHtml;
    _inlineRenameActive = null;
}

function startInlineRename(type, id, currentName) {
    try {
        document.querySelectorAll('.dropdown-menu.show').forEach(function (m) { m.classList.remove('show'); });
        document.querySelectorAll('.dropdown.show').forEach(function (d) { d.classList.remove('show'); });
    } catch (e) { /* ignore */ }

    cancelInlineRename();
    const sel = '[data-rename-target="' + type + '-' + id + '"]';
    const candidates = Array.from(document.querySelectorAll(sel));
    // List+Grid existieren parallel — sichtbares Target nehmen (sonst trifft querySelector immer Grid zuerst)
    let target = candidates.find(function (el) {
        if (!el || !el.getClientRects || !el.getClientRects().length) return false;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none') return false;
        let node = el;
        while (node && node !== document.body) {
            const cs = window.getComputedStyle(node);
            if (cs.display === 'none' || cs.visibility === 'hidden') return false;
            node = node.parentElement;
        }
        return true;
    }) || null;
    if (!target) {
        console.warn('Inline rename: target not found', type, id);
        return;
    }

    const restoreHtml = target.outerHTML;
    const lastDot = type === 'file' ? String(currentName).lastIndexOf('.') : -1;
    const ext = (type === 'file' && lastDot > 0) ? String(currentName).substring(lastDot) : '';
    const baseName = (type === 'file' && lastDot > 0) ? String(currentName).substring(0, lastDot) : String(currentName);

    const wrap = document.createElement('div');
    wrap.className = 'files-inline-rename';
    wrap.setAttribute('data-rename-target', type + '-' + id);
    wrap.addEventListener('click', function (e) { e.stopPropagation(); e.preventDefault(); });

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'form-control form-control-sm mod-pill-input';
    input.value = baseName;
    input.setAttribute('aria-label', 'Umbenennen');

    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'btn btn-sm btn-accent mod-pill-btn';
    saveBtn.innerHTML = '<i class="bi bi-check"></i>';
    saveBtn.title = 'Speichern';

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn btn-sm btn-secondary mod-pill-btn';
    cancelBtn.innerHTML = '<i class="bi bi-x"></i>';
    cancelBtn.title = 'Abbrechen';

    wrap.appendChild(input);
    if (ext) {
        const extSpan = document.createElement('span');
        extSpan.className = 'text-muted small flex-shrink-0';
        extSpan.textContent = ext;
        wrap.appendChild(extSpan);
    }
    wrap.appendChild(saveBtn);
    wrap.appendChild(cancelBtn);

    target.replaceWith(wrap);
    _inlineRenameActive = { el: wrap, restoreHtml };
    setTimeout(function () {
        input.focus();
        input.select();
    }, 0);

    function submitRename() {
        const name = (input.value || '').trim();
        if (!name) {
            input.focus();
            return;
        }
        const newName = type === 'file' ? (name + ext) : name;
        const url = type === 'file' ? ('/files/file/' + id + '/rename') : ('/files/folder/' + id + '/rename');
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = url;
        const field = document.createElement('input');
        field.type = 'hidden';
        field.name = 'new_name';
        field.value = newName;
        form.appendChild(field);
        if (window.FILES_VIEW) {
            const viewField = document.createElement('input');
            viewField.type = 'hidden';
            viewField.name = 'view';
            viewField.value = window.FILES_VIEW;
            form.appendChild(viewField);
        }
        if (window.FILES_TEAM_ID) {
            const teamField = document.createElement('input');
            teamField.type = 'hidden';
            teamField.name = 'team_id';
            teamField.value = String(window.FILES_TEAM_ID);
            form.appendChild(teamField);
        }
        if (window.CURRENT_FOLDER_ID != null && window.CURRENT_FOLDER_ID !== '') {
            const folderField = document.createElement('input');
            folderField.type = 'hidden';
            folderField.name = 'return_folder_id';
            folderField.value = String(window.CURRENT_FOLDER_ID);
            form.appendChild(folderField);
        }
        document.body.appendChild(form);
        form.submit();
    }

    saveBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        submitRename();
    });
    cancelBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        cancelInlineRename();
    });
    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            submitRename();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancelInlineRename();
        }
    });
}

window.startInlineRename = startInlineRename;
window.openRenameFileModal = function (fileId, currentName) { startInlineRename('file', fileId, currentName); };
window.openRenameFolderModal = function (folderId, currentName) { startInlineRename('folder', folderId, currentName); };

// ===== Ordnerfarbe =====
function openFolderColorModal(folderId, folderName, currentColor) {
    const modal = new bootstrap.Modal(document.getElementById('folderColorModal'));
    const form = document.getElementById('folderColorForm');
    const nameEl = document.getElementById('folderColorName');
    const colorInput = document.getElementById('folderColorInput');
    const clearInput = document.getElementById('folderColorClear');
    const resetBtn = document.getElementById('folderColorResetBtn');

    form.action = `/files/folder/${folderId}/color`;
    nameEl.textContent = folderName || '';
    clearInput.value = '0';
    colorInput.value = (currentColor && /^#[0-9a-fA-F]{6}$/.test(currentColor)) ? currentColor : '#f6c344';

    colorInput.oninput = function() {
        clearInput.value = '0';
    };

    resetBtn.onclick = function() {
        clearInput.value = '1';
        colorInput.value = '#f6c344';
    };

    modal.show();
}

// ===== Verschieben (Modal + Ordnerbaum) =====
(function () {
    let moveState = {
        itemType: null,
        itemId: null,
        selected: null,
        modal: null
    };

    function moveLabels() {
        const modals = (window.FILES_I18N && window.FILES_I18N.modals && window.FILES_I18N.modals.move) || {};
        const actions = (window.FILES_I18N && window.FILES_I18N.actions) || {};
        const nav = (window.FILES_I18N && window.FILES_I18N.nav) || {};
        return {
            title: modals.title || actions.move || 'Verschieben',
            loading: modals.loading || 'Lade Ziele…',
            confirm: modals.confirm || 'Hierher verschieben',
            empty: modals.empty || 'Keine Ordner verfügbar.',
            root_hint: modals.root_hint || 'In diesen Bereich (Root)',
            item_file: modals.item_file || 'Datei verschieben',
            item_folder: modals.item_folder || 'Ordner verschieben',
            nav
        };
    }

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function setMoveError(message) {
        const el = document.getElementById('filesMoveError');
        if (!el) return;
        if (!message) {
            el.hidden = true;
            el.textContent = '';
            return;
        }
        el.hidden = false;
        el.textContent = message;
    }

    function setMoveSelection(payload, button) {
        moveState.selected = payload;
        document.querySelectorAll('.files-move-node.is-selected').forEach(el => el.classList.remove('is-selected'));
        if (button) button.classList.add('is-selected');
        const confirmBtn = document.getElementById('filesMoveConfirmBtn');
        if (confirmBtn) confirmBtn.disabled = !payload;
    }

    function renderFolderNodes(nodes, depth) {
        if (!nodes || !nodes.length) return '';
        return nodes.map(node => {
            const hasChildren = node.children && node.children.length;
            const kids = hasChildren
                ? `<div class="files-move-children">${renderFolderNodes(node.children, depth + 1)}</div>`
                : '';
            const toggle = hasChildren
                ? `<button type="button" class="files-move-toggle" aria-expanded="true" title="Unterordner"><i class="bi bi-caret-down-fill"></i></button>`
                : `<span class="files-move-toggle-spacer"></span>`;
            const colorStyle = node.color ? ` style="color:${escapeHtml(node.color)}"` : '';
            return `
                <div class="files-move-branch" data-depth="${depth}">
                    <div class="files-move-row">
                        ${toggle}
                        <button type="button" class="files-move-node"
                            data-folder-id="${node.id}"
                            data-view=""
                            data-team-id="">
                            <i class="bi bi-folder-fill folder-color-icon"${colorStyle}></i>
                            <span class="text-truncate">${escapeHtml(node.name)}</span>
                        </button>
                    </div>
                    ${kids}
                </div>`;
        }).join('');
    }

    function renderSpaces(spaces) {
        const labels = moveLabels();
        return (spaces || []).map(space => {
            const icon = space.view === 'ablage'
                ? 'bi-hdd'
                : (space.view === 'team' ? 'bi-people-fill' : 'bi-globe2');
            const colorDot = space.color
                ? `<span class="files-move-team-dot" style="background:${escapeHtml(space.color)}"></span>`
                : `<i class="bi ${icon}"></i>`;
            const teamAttr = space.team_id != null ? ` data-team-id="${space.team_id}"` : ' data-team-id=""';
            const children = renderFolderNodes(space.folders || [], 1);
            return `
                <div class="files-move-space" data-space-key="${escapeHtml(space.key)}">
                    <button type="button" class="files-move-node files-move-space-root"
                        data-folder-id=""
                        data-view="${escapeHtml(space.view)}"
                        ${teamAttr}>
                        ${colorDot}
                        <span class="text-truncate">${escapeHtml(space.label)}</span>
                        <span class="files-move-root-hint">${escapeHtml(labels.root_hint)}</span>
                    </button>
                    ${children ? `<div class="files-move-children">${children}</div>` : ''}
                </div>`;
        }).join('');
    }

    function bindTreeEvents(treeEl) {
        treeEl.querySelectorAll('.files-move-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const branch = btn.closest('.files-move-branch');
                if (!branch) return;
                const kids = branch.querySelector(':scope > .files-move-children');
                if (!kids) return;
                const open = kids.hidden;
                kids.hidden = !open;
                btn.setAttribute('aria-expanded', open ? 'true' : 'false');
                const icon = btn.querySelector('i');
                if (icon) {
                    icon.className = open ? 'bi bi-caret-down-fill' : 'bi bi-caret-right-fill';
                }
            });
        });

        treeEl.querySelectorAll('.files-move-node').forEach(btn => {
            btn.addEventListener('click', () => {
                const rawFolder = btn.getAttribute('data-folder-id');
                const view = btn.getAttribute('data-view') || '';
                const teamRaw = btn.getAttribute('data-team-id');
                let targetFolderId = null;
                if (rawFolder !== '' && rawFolder != null) {
                    targetFolderId = parseInt(rawFolder, 10);
                }
                // Folder nodes inherit view/team from enclosing space
                const space = btn.closest('.files-move-space');
                const spaceRoot = space && space.querySelector('.files-move-space-root');
                const resolvedView = view || (spaceRoot && spaceRoot.getAttribute('data-view')) || window.FILES_VIEW || 'public';
                const resolvedTeam = teamRaw || (spaceRoot && spaceRoot.getAttribute('data-team-id')) || '';
                setMoveSelection({
                    target_folder_id: Number.isFinite(targetFolderId) ? targetFolderId : null,
                    view: resolvedView,
                    team_id: resolvedTeam ? parseInt(resolvedTeam, 10) : undefined
                }, btn);
            });
        });
    }

    async function loadDestinations() {
        const loading = document.getElementById('filesMoveLoading');
        const tree = document.getElementById('filesMoveTree');
        const confirmBtn = document.getElementById('filesMoveConfirmBtn');
        if (loading) loading.hidden = false;
        if (tree) {
            tree.hidden = true;
            tree.innerHTML = '';
        }
        if (confirmBtn) confirmBtn.disabled = true;
        setMoveError('');
        moveState.selected = null;

        const params = new URLSearchParams();
        if (moveState.itemType === 'folder' && moveState.itemId) {
            params.set('exclude_folder_id', String(moveState.itemId));
        }
        const url = (window.FILES_MOVE_DESTINATIONS_URL || '/files/api/move-destinations')
            + (params.toString() ? ('?' + params.toString()) : '');

        try {
            const response = await fetch(url, { headers: { 'Accept': 'application/json' } });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.success) {
                throw new Error(data.error || (FILES_I18N.messages && FILES_I18N.messages.move_error) || 'Laden fehlgeschlagen');
            }
            if (loading) loading.hidden = true;
            if (!tree) return;
            if (!data.spaces || !data.spaces.length) {
                tree.innerHTML = `<div class="text-muted small">${escapeHtml(moveLabels().empty)}</div>`;
            } else {
                tree.innerHTML = renderSpaces(data.spaces);
                bindTreeEvents(tree);
            }
            tree.hidden = false;
        } catch (err) {
            if (loading) loading.hidden = true;
            setMoveError(err.message || (FILES_I18N.messages && FILES_I18N.messages.move_error));
        }
    }

    window.openMoveModal = function openMoveModal(itemType, itemId) {
        if (window.FILES_IS_TRASH) return;
        moveState.itemType = itemType;
        moveState.itemId = itemId;
        const labels = moveLabels();
        const labelEl = document.getElementById('filesMoveItemLabel');
        if (labelEl) {
            labelEl.textContent = itemType === 'folder' ? labels.item_folder : labels.item_file;
        }
        const modalEl = document.getElementById('filesMoveModal');
        if (!modalEl) return;
        moveState.modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        moveState.modal.show();
        loadDestinations();
    };

    document.addEventListener('DOMContentLoaded', () => {
        const confirmBtn = document.getElementById('filesMoveConfirmBtn');
        if (!confirmBtn) return;
        confirmBtn.addEventListener('click', async () => {
            if (!moveState.selected || !moveState.itemType || !moveState.itemId) return;
            confirmBtn.disabled = true;
            setMoveError('');
            try {
                const response = await fetch(window.FILES_MOVE_URL || '/files/move', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        item_type: moveState.itemType,
                        item_id: moveState.itemId,
                        target_folder_id: moveState.selected.target_folder_id,
                        view: moveState.selected.view,
                        team_id: moveState.selected.team_id
                    })
                });
                const result = await response.json().catch(() => ({}));
                if (!response.ok || !result.success) {
                    setMoveError(result.error || (FILES_I18N.messages && FILES_I18N.messages.move_error) || 'Verschieben fehlgeschlagen.');
                    confirmBtn.disabled = false;
                    return;
                }
                if (moveState.modal) moveState.modal.hide();
                if (typeof showDnDMessage === 'function') {
                    showDnDMessage((FILES_I18N.messages && FILES_I18N.messages.move_success) || 'Element wurde verschoben.', 'success');
                }
                window.location.reload();
            } catch (err) {
                setMoveError((FILES_I18N.messages && FILES_I18N.messages.move_error) || 'Verschieben fehlgeschlagen.');
                confirmBtn.disabled = false;
            }
        });
    });
})();

// ===== Umbenennen & Freigaben =====
function shareModeFieldsHtml(shareLabels, mode) {
    const modeLabel = mode === 'view' ? (shareLabels.mode_view || 'Betrachten') : (shareLabels.mode_edit || 'Bearbeiten');
    return `
        <div class="border rounded p-3 mb-3 share-mode-fields" data-mode="${mode}" style="display:none;">
            <h6 class="mb-2">${modeLabel}</h6>
            <div class="mb-2">
                <label class="form-label">${shareLabels.password_label}</label>
                <input type="password" name="password_${mode}" class="form-control">
            </div>
            <div class="mb-0">
                <label class="form-label">${shareLabels.expires_label}</label>
                <input type="datetime-local" name="expires_at_${mode}" class="form-control">
            </div>
        </div>`;
}

function bindShareModeToggles(form) {
    const toggles = form.querySelectorAll('.share-mode-toggle');
    const update = () => {
        toggles.forEach(cb => {
            const block = form.querySelector(`.share-mode-fields[data-mode="${cb.value}"]`);
            if (block) block.style.display = cb.checked ? 'block' : 'none';
        });
    };
    toggles.forEach(cb => cb.addEventListener('change', update));
    update();
}

function openShareDialog(type, id) {
    closeActiveMenus();
    const shareLabels = FILES_I18N.modals.share;
    const title = type === 'file' ? shareLabels.title_file : shareLabels.title_folder;
    const formAction = type === 'file' ? `/files/file/${id}/share` : `/files/folder/${id}/share`;
    const html = `
        <form method="POST" action="${formAction}" id="shareCreateForm">
            <p class="text-muted small">${shareLabels.choose_modes || 'Wählen Sie mindestens einen Link-Typ.'}</p>
            <div class="form-check mb-2">
                <input class="form-check-input share-mode-toggle" type="checkbox" name="share_modes" value="view" id="share_mode_view">
                <label class="form-check-label" for="share_mode_view">${shareLabels.mode_view || 'Betrachten-Link'}</label>
            </div>
            <div class="form-check mb-3">
                <input class="form-check-input share-mode-toggle" type="checkbox" name="share_modes" value="edit" id="share_mode_edit" checked>
                <label class="form-check-label" for="share_mode_edit">${shareLabels.mode_edit || 'Bearbeiten-Link'}</label>
            </div>
            ${shareModeFieldsHtml(shareLabels, 'view')}
            ${shareModeFieldsHtml(shareLabels, 'edit')}
            <div class="files-hint files-hint--info" role="status">
                <span class="files-hint__icon"><i class="bi bi-info-circle"></i></span>
                <span class="files-hint__text">${shareLabels.info_text}</span>
            </div>
            <div class="d-flex gap-2">
                <button type="submit" class="btn btn-primary"><i class="bi bi-share"></i> ${shareLabels.create_button}</button>
                <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">${shareLabels.close_button}</button>
            </div>
        </form>`;
    showSimpleModal(title, html);
    const form = document.getElementById('simpleModal')?.querySelector('#shareCreateForm');
    if (form) bindShareModeToggles(form);
}

function renderShareLinkSection(shareLabels, formAction, link) {
    if (!link.enabled) {
        return `
            <div class="border rounded p-3 mb-3">
                <h6>${link.mode === 'view' ? (shareLabels.mode_view || 'Betrachten') : (shareLabels.mode_edit || 'Bearbeiten')} – ${shareLabels.link_inactive || 'inaktiv'}</h6>
                <button type="submit" name="action" value="create_${link.mode}" class="btn btn-sm btn-outline-primary">${shareLabels.create_link_button || 'Link anlegen'}</button>
            </div>`;
    }
    const exp = link.expires_at ? link.expires_at.substring(0, 16) : '';
    return `
        <div class="border rounded p-3 mb-3">
            <h6>${link.mode === 'view' ? (shareLabels.mode_view || 'Betrachten') : (shareLabels.mode_edit || 'Bearbeiten')}</h6>
            <div class="mb-2">
                <label class="form-label">${shareLabels.link_label}</label>
                <div class="input-group">
                    <input type="text" class="form-control" value="${link.share_url}" readonly>
                    <button class="btn btn-outline-secondary" type="button" onclick="navigator.clipboard.writeText('${link.share_url}')"><i class="bi bi-clipboard"></i></button>
                </div>
            </div>
            <div class="mb-2">
                <label class="form-label">${shareLabels.password_keep_label}</label>
                <input type="password" class="form-control" name="password_${link.mode}">
            </div>
            <div class="mb-2">
                <label class="form-label">${shareLabels.expires_label_compact}</label>
                <input type="datetime-local" class="form-control" name="expires_at_${link.mode}" value="${exp}">
            </div>
            <button type="submit" name="action" value="disable_${link.mode}" class="btn btn-sm btn-outline-danger">${shareLabels.disable_link_button || 'Link deaktivieren'}</button>
        </div>`;
}

function formatAccessLogAction(action) {
    const labels = FILES_I18N.modals.share.access_actions || {};
    return labels[action] || action;
}

function closeActiveMenus() {
    document.querySelectorAll('.dropdown-menu.show').forEach(menu => menu.classList.remove('show'));
    document.querySelectorAll('.dropdown.show').forEach(dropdown => dropdown.classList.remove('show'));
    if (window.PrismateamsContextMenu && typeof window.PrismateamsContextMenu.close === 'function') {
        window.PrismateamsContextMenu.close();
    }
}

function renderShareAccessLogsTable(logs, shareLabels) {
    if (!logs.length) {
        return `<p class="text-muted small">${shareLabels.access_log_empty || 'Noch keine Zugriffe protokolliert.'}</p>`;
    }
    return `
        <div class="table-responsive" style="max-height:320px;overflow:auto;">
            <table class="table table-sm table-striped mb-0">
                <thead><tr><th>${shareLabels.access_log_time || 'Zeit'}</th><th>${shareLabels.access_log_action || 'Aktion'}</th><th>IP</th><th>${shareLabels.access_log_guest || 'Gast'}</th></tr></thead>
                <tbody>
                    ${logs.map(log => `<tr><td>${(log.accessed_at || '').replace('T', ' ').substring(0, 16)}</td><td>${formatAccessLogAction(log.action)}</td><td>${log.ip_address || '–'}</td><td>${log.guest_name || '–'}</td></tr>`).join('')}
                </tbody>
            </table>
        </div>`;
}

function openShareSettings(type, id) {
    closeActiveMenus();
    const shareLabels = FILES_I18N.modals.share;
    const endpoint = type === 'file' ? `/files/file/${id}/share-settings` : `/files/folder/${id}/share-settings`;
    fetch(endpoint)
        .then(r => r.json())
        .then(data => {
            if (!data.success) { return; }
            const item = data.item;
            const formAction = type === 'file' ? `/files/file/${id}/share-settings` : `/files/folder/${id}/share-settings`;
            const linksHtml = (item.links || []).map(link => renderShareLinkSection(shareLabels, formAction, link)).join('');
            const html = `
                <form method="POST" action="${formAction}">
                    ${linksHtml}
                    <div class="d-flex gap-2 mt-3">
                        <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> ${shareLabels.save_button}</button>
                        <button type="submit" name="action" value="disable_all" class="btn btn-outline-danger"><i class="bi bi-slash-circle"></i> ${shareLabels.disable_button}</button>
                        <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">${shareLabels.close_button}</button>
                    </div>
                </form>`;
            showSimpleModal(shareLabels.edit_title, html);
        });
}

function openShareActivity(type, id) {
    closeActiveMenus();
    const shareLabels = FILES_I18N.modals.share;
    const endpoint = type === 'file' ? `/files/file/${id}/share-settings` : `/files/folder/${id}/share-settings`;
    fetch(endpoint)
        .then(r => r.json())
        .then(data => {
            if (!data.success) { return; }
            const logs = data.item?.access_logs || [];
            const title = `${shareLabels.access_log_title || 'Aktivitätsverlauf'}${data.item?.name ? ` – ${data.item.name}` : ''}`;
            const html = renderShareAccessLogsTable(logs, shareLabels);
            showSimpleModal(title, html);
        });
}

function showSimpleModal(title, bodyHtml) {
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
    modal.querySelector('.modal-title').innerText = title;
    modal.querySelector('.modal-body').innerHTML = bodyHtml;
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
}
