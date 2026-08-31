const InventoryFormManager = (() => {
    const INVENTORY_API_BASES = ['/inventory/vnext/api', '/vnext/api'];
    let activeInventoryApiBase = INVENTORY_API_BASES[0];

    const normalizeApiPath = (path) => {
        if (!path) return '';
        return path.startsWith('/') ? path : `/${path}`;
    };

    const resolveApiUrl = (path, base = activeInventoryApiBase) => {
        return `${base}${normalizeApiPath(path)}`;
    };

    const inventoryApiFetch = async (path, options = {}) => {
        const normalizedPath = normalizeApiPath(path);
        const candidateBases = [
            activeInventoryApiBase,
            ...INVENTORY_API_BASES.filter(base => base !== activeInventoryApiBase)
        ];

        let lastResponse = null;
        let lastError = null;

        for (const base of candidateBases) {
            try {
                const response = await fetch(resolveApiUrl(normalizedPath, base), options);
                lastResponse = response;
                if (response.status !== 404) {
                    activeInventoryApiBase = base;
                    return response;
                }
            } catch (error) {
                lastError = error;
            }
        }

        if (lastResponse) {
            return lastResponse;
        }
        throw lastError || new Error('API-Anfrage fehlgeschlagen.');
    };

    const state = {
        folders: [],
        categories: [],
        selectedFolderId: null,
        selectedCategory: null,
    };

    const labels = {
        noFolder: 'Kein Ordner',
        noCategory: 'Keine Kategorie',
        edit: 'Bearbeiten',
        delete: 'Löschen',
        folderDeleteConfirm: 'Ordner wirklich löschen?',
        categoryDeleteConfirm: 'Kategorie wirklich löschen?',
    };

    let folderSelect;
    let categorySelect;

    const formNotify = (message, category = 'danger') => {
        if (typeof window.ptAlert === 'function') {
            window.ptAlert(message, category);
            return;
        }
        window.alert(String(message || ''));
    };

    const routes = {
        folders: '/folders',
        categories: '/categories',
    };

    const sortByName = (items) => {
        return items.slice().sort((a, b) => {
            const nameA = (typeof a === 'string' ? a : a.name) || '';
            const nameB = (typeof b === 'string' ? b : b.name) || '';
            return nameA.localeCompare(nameB, 'de', { sensitivity: 'base' });
        });
    };

    const showPanel = (id) => {
        const el = document.getElementById(id);
        if (el) el.hidden = false;
    };

    const hidePanel = (id) => {
        const el = document.getElementById(id);
        if (el) el.hidden = true;
    };

    const refreshFolderSelect = () => {
        if (!folderSelect) return;
        folderSelect.innerHTML = '';
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = labels.noFolder;
        folderSelect.appendChild(defaultOption);

        sortByName(state.folders).forEach(folder => {
            const option = document.createElement('option');
            option.value = String(folder.id);
            option.textContent = folder.name;
            folderSelect.appendChild(option);
        });

        const targetValue = state.selectedFolderId ? String(state.selectedFolderId) : '';
        folderSelect.value = targetValue;
        if (folderSelect.value !== targetValue) {
            folderSelect.value = '';
        }
    };

    const refreshCategorySelect = () => {
        if (!categorySelect) return;
        categorySelect.innerHTML = '';
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = labels.noCategory;
        categorySelect.appendChild(defaultOption);

        sortByName(state.categories).forEach(category => {
            const option = document.createElement('option');
            option.value = category;
            option.textContent = category;
            categorySelect.appendChild(option);
        });

        const targetValue = state.selectedCategory || '';
        categorySelect.value = targetValue;
        if (categorySelect.value !== targetValue) {
            categorySelect.value = '';
        }
    };

    const renderManageList = (type) => {
        const isFolder = type === 'folder';
        const listEl = document.getElementById(isFolder ? 'folderList' : 'categoryList');
        const emptyHint = document.getElementById(isFolder ? 'foldersEmptyHint' : 'categoriesEmptyHint');
        if (!listEl) return;
        const items = isFolder ? state.folders : state.categories;

        listEl.innerHTML = '';
        if (!items || items.length === 0) {
            if (emptyHint) emptyHint.style.display = 'block';
            return;
        }
        if (emptyHint) emptyHint.style.display = 'none';

        sortByName(items).forEach(item => {
            const li = document.createElement('li');
            li.className = 'inventory-manage-item';
            const name = typeof item === 'string' ? item : item.name;
            const id = typeof item === 'string' ? item : item.id;

            const nameSpan = document.createElement('span');
            nameSpan.className = 'inventory-manage-item-name';
            nameSpan.textContent = name;
            li.appendChild(nameSpan);

            const btnGroup = document.createElement('div');
            btnGroup.className = 'inventory-manage-item-actions';

            const editBtn = document.createElement('button');
            editBtn.type = 'button';
            editBtn.className = 'btn btn-sm inventory-pill-btn inventory-pill-btn--muted';
            editBtn.innerHTML = '<i class="bi bi-pencil"></i>';
            editBtn.title = labels.edit;
            editBtn.addEventListener('click', () => openEditPanel(type, id, name));

            const deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.className = 'btn btn-sm inventory-pill-btn inventory-pill-btn--danger';
            deleteBtn.innerHTML = '<i class="bi bi-trash"></i>';
            deleteBtn.title = labels.delete;
            deleteBtn.addEventListener('click', () => {
                handleDelete(type, type === 'folder' ? Number(id) : id, name);
            });

            btnGroup.appendChild(editBtn);
            btnGroup.appendChild(deleteBtn);
            li.appendChild(btnGroup);
            listEl.appendChild(li);
        });
    };

    const openEditPanel = (type, id, name) => {
        if (type === 'folder') {
            document.getElementById('folderEditId').value = id;
            document.getElementById('folderEditName').value = name;
            showPanel('folderEditPanel');
            document.getElementById('folderEditName').focus();
        } else {
            document.getElementById('categoryEditId').value = id;
            document.getElementById('categoryEditName').value = name;
            showPanel('categoryEditPanel');
            document.getElementById('categoryEditName').focus();
        }
    };

    const requestCreateFolder = async (name) => {
        const response = await inventoryApiFetch(routes.folders, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error || 'Ordner konnte nicht erstellt werden.');
        }
        return response.json();
    };

    const requestUpdateFolder = async (id, name) => {
        const response = await inventoryApiFetch(`${routes.folders}/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error || 'Ordner konnte nicht aktualisiert werden.');
        }
        return response.json();
    };

    const requestDeleteFolder = async (id) => {
        const response = await inventoryApiFetch(`${routes.folders}/${id}`, {
            method: 'DELETE',
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error || 'Ordner konnte nicht gelöscht werden.');
        }
        return response.json();
    };

    const requestCreateCategory = async (name) => {
        const response = await inventoryApiFetch(routes.categories, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error || 'Kategorie konnte nicht erstellt werden.');
        }
        return response.json();
    };

    const requestUpdateCategory = async (originalName, newName) => {
        const response = await inventoryApiFetch(`${routes.categories}/${encodeURIComponent(originalName)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName }),
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error || 'Kategorie konnte nicht aktualisiert werden.');
        }
        return response.json();
    };

    const requestDeleteCategory = async (name) => {
        const response = await inventoryApiFetch(`${routes.categories}/${encodeURIComponent(name)}`, {
            method: 'DELETE',
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error || 'Kategorie konnte nicht gelöscht werden.');
        }
        return response.json();
    };

    const handleDelete = async (type, id, name) => {
        const confirmText = type === 'folder'
            ? labels.folderDeleteConfirm.replace('{name}', name)
            : labels.categoryDeleteConfirm.replace('{name}', name);
        const ok = typeof window.ptConfirm === 'function'
            ? await window.ptConfirm(confirmText, { danger: true, confirmLabel: labels.delete })
            : confirm(confirmText);
        if (!ok) return;

        try {
            if (type === 'folder') {
                await requestDeleteFolder(id);
                state.folders = state.folders.filter(folder => folder.id !== id);
                if (state.selectedFolderId && String(state.selectedFolderId) === String(id)) {
                    state.selectedFolderId = null;
                }
                refreshFolderSelect();
                renderManageList('folder');
                hidePanel('folderEditPanel');
            } else {
                await requestDeleteCategory(id);
                state.categories = state.categories.filter(cat => cat !== id);
                if (state.selectedCategory === id) {
                    state.selectedCategory = null;
                }
                refreshCategorySelect();
                renderManageList('category');
                hidePanel('categoryEditPanel');
            }
        } catch (error) {
            console.error(error);
            formNotify(error.message || 'Löschen fehlgeschlagen.');
        }
    };

    const bindEvents = () => {
        document.getElementById('addFolderBtn')?.addEventListener('click', () => {
            hidePanel('folderManagePanel');
            hidePanel('folderEditPanel');
            document.getElementById('folderCreateName').value = '';
            showPanel('folderCreatePanel');
            document.getElementById('folderCreateName').focus();
        });

        document.getElementById('folderCreateCancel')?.addEventListener('click', () => {
            hidePanel('folderCreatePanel');
        });

        document.getElementById('folderCreateSubmit')?.addEventListener('click', async () => {
            const name = (document.getElementById('folderCreateName')?.value || '').trim();
            if (!name) {
                document.getElementById('folderCreateName')?.focus();
                return;
            }
            try {
                const created = await requestCreateFolder(name);
                state.folders.push({ id: created.id, name: created.name });
                state.selectedFolderId = created.id;
                refreshFolderSelect();
                hidePanel('folderCreatePanel');
            } catch (error) {
                console.error(error);
                formNotify(error.message || 'Aktion fehlgeschlagen.');
            }
        });

        document.getElementById('manageFoldersBtn')?.addEventListener('click', () => {
            hidePanel('folderCreatePanel');
            hidePanel('folderEditPanel');
            renderManageList('folder');
            showPanel('folderManagePanel');
        });

        document.getElementById('folderManageClose')?.addEventListener('click', () => {
            hidePanel('folderManagePanel');
            hidePanel('folderEditPanel');
        });

        document.getElementById('folderEditCancel')?.addEventListener('click', () => {
            hidePanel('folderEditPanel');
        });

        document.getElementById('folderEditSubmit')?.addEventListener('click', async () => {
            const id = document.getElementById('folderEditId')?.value;
            const name = (document.getElementById('folderEditName')?.value || '').trim();
            if (!id || !name) return;
            try {
                const updated = await requestUpdateFolder(Number(id), name);
                state.folders = state.folders.map(folder =>
                    folder.id === updated.id ? { id: updated.id, name: updated.name } : folder
                );
                if (state.selectedFolderId && String(state.selectedFolderId) === String(updated.id)) {
                    state.selectedFolderId = updated.id;
                }
                refreshFolderSelect();
                renderManageList('folder');
                hidePanel('folderEditPanel');
            } catch (error) {
                console.error(error);
                formNotify(error.message || 'Aktion fehlgeschlagen.');
            }
        });

        document.getElementById('folderEditDelete')?.addEventListener('click', () => {
            const id = document.getElementById('folderEditId')?.value;
            const name = document.getElementById('folderEditName')?.value || '';
            if (!id) return;
            handleDelete('folder', Number(id), name);
        });

        document.getElementById('addCategoryBtn')?.addEventListener('click', () => {
            hidePanel('categoryManagePanel');
            hidePanel('categoryEditPanel');
            document.getElementById('categoryCreateName').value = '';
            showPanel('categoryCreatePanel');
            document.getElementById('categoryCreateName').focus();
        });

        document.getElementById('categoryCreateCancel')?.addEventListener('click', () => {
            hidePanel('categoryCreatePanel');
        });

        document.getElementById('categoryCreateSubmit')?.addEventListener('click', async () => {
            const name = (document.getElementById('categoryCreateName')?.value || '').trim();
            if (!name) {
                document.getElementById('categoryCreateName')?.focus();
                return;
            }
            try {
                await requestCreateCategory(name);
                state.categories.push(name);
                state.selectedCategory = name;
                refreshCategorySelect();
                hidePanel('categoryCreatePanel');
            } catch (error) {
                console.error(error);
                formNotify(error.message || 'Aktion fehlgeschlagen.');
            }
        });

        document.getElementById('manageCategoriesBtn')?.addEventListener('click', () => {
            hidePanel('categoryCreatePanel');
            hidePanel('categoryEditPanel');
            renderManageList('category');
            showPanel('categoryManagePanel');
        });

        document.getElementById('categoryManageClose')?.addEventListener('click', () => {
            hidePanel('categoryManagePanel');
            hidePanel('categoryEditPanel');
        });

        document.getElementById('categoryEditCancel')?.addEventListener('click', () => {
            hidePanel('categoryEditPanel');
        });

        document.getElementById('categoryEditSubmit')?.addEventListener('click', async () => {
            const originalName = document.getElementById('categoryEditId')?.value;
            const name = (document.getElementById('categoryEditName')?.value || '').trim();
            if (!originalName || !name) return;
            try {
                await requestUpdateCategory(originalName, name);
                state.categories = state.categories.map(cat => (cat === originalName ? name : cat));
                if (state.selectedCategory === originalName) {
                    state.selectedCategory = name;
                }
                refreshCategorySelect();
                renderManageList('category');
                hidePanel('categoryEditPanel');
            } catch (error) {
                console.error(error);
                formNotify(error.message || 'Aktion fehlgeschlagen.');
            }
        });

        document.getElementById('categoryEditDelete')?.addEventListener('click', () => {
            const id = document.getElementById('categoryEditId')?.value;
            const name = document.getElementById('categoryEditName')?.value || id;
            if (!id) return;
            handleDelete('category', id, name);
        });

        folderSelect?.addEventListener('change', () => {
            state.selectedFolderId = folderSelect.value ? Number(folderSelect.value) : null;
        });

        categorySelect?.addEventListener('change', () => {
            state.selectedCategory = categorySelect.value || null;
        });
    };

    const initState = () => {
        if (!window.inventoryFormData) return;
        Object.assign(labels, window.inventoryFormData.labels || {});
        state.folders = Array.isArray(window.inventoryFormData.folders)
            ? window.inventoryFormData.folders.map(folder => ({ id: Number(folder.id), name: folder.name }))
            : [];
        state.categories = Array.isArray(window.inventoryFormData.categories)
            ? window.inventoryFormData.categories.slice()
            : [];
        const selectedFolderRaw = window.inventoryFormData.selectedFolderId;
        state.selectedFolderId = selectedFolderRaw !== null && selectedFolderRaw !== undefined
            ? Number(selectedFolderRaw)
            : null;
        const selectedCategoryRaw = window.inventoryFormData.selectedCategory;
        state.selectedCategory = selectedCategoryRaw !== null && selectedCategoryRaw !== undefined
            ? String(selectedCategoryRaw)
            : null;
    };

    const init = () => {
        folderSelect = document.getElementById('folder_id');
        categorySelect = document.getElementById('category');
        initState();
        refreshFolderSelect();
        refreshCategorySelect();
        bindEvents();
    };

    return { init };
})();

document.addEventListener('DOMContentLoaded', () => {
    InventoryFormManager.init();
    setupProductFormTooltips();
    setupDguvRequiredToggle();
    setupDguvAutoNext();
});

function setupProductFormTooltips() {
    const root = document.querySelector('.inventory-form');
    if (!root || typeof bootstrap === 'undefined' || !bootstrap.Tooltip) return;
    root.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
        bootstrap.Tooltip.getOrCreateInstance(el);
    });
}

function addMonthsToDate(isoDate, months) {
    if (!isoDate || !months) return null;
    const parts = String(isoDate).slice(0, 10).split('-').map(Number);
    if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return null;
    const [y, m, d] = parts;
    const totalMonths = (y * 12 + (m - 1)) + Number(months);
    const year = Math.floor(totalMonths / 12);
    const month = (totalMonths % 12) + 1;
    const daysInMonth = new Date(year, month, 0).getDate();
    const day = Math.min(d, daysInMonth);
    const mm = String(month).padStart(2, '0');
    const dd = String(day).padStart(2, '0');
    return `${year}-${mm}-${dd}`;
}

function formatDeDate(isoDate) {
    if (!isoDate) return '';
    const [y, m, d] = String(isoDate).slice(0, 10).split('-');
    if (!y || !m || !d) return '';
    return `${d}.${m}.${y}`;
}

function isDguvRequired() {
    const toggle = document.getElementById('dguv_required');
    return !toggle || toggle.checked;
}

function setupDguvRequiredToggle() {
    const toggle = document.getElementById('dguv_required');
    const wrap = document.getElementById('dguvFieldsWrap');
    if (!toggle || !wrap) return;

    const sync = () => {
        wrap.classList.toggle('d-none', !toggle.checked);
        if (toggle.checked && typeof window.__inventoryRefreshDguvNext === 'function') {
            window.__inventoryRefreshDguvNext();
        } else if (!toggle.checked) {
            const nextDisplay = document.getElementById('dguv_next_check_display');
            const nextHidden = document.getElementById('dguv_next_check');
            if (nextDisplay) nextDisplay.value = '';
            if (nextHidden) nextHidden.value = '';
        }
    };

    toggle.addEventListener('change', sync);
    sync();
}

function setupDguvAutoNext() {
    const lastInput = document.getElementById('dguv_last_check');
    const intervalInput = document.getElementById('dguv_interval_months');
    const nextDisplay = document.getElementById('dguv_next_check_display');
    const nextHidden = document.getElementById('dguv_next_check');
    if (!lastInput || !intervalInput) return;

    const isCreate = !document.querySelector('#status');

    const refresh = () => {
        if (!isDguvRequired()) {
            if (nextDisplay) nextDisplay.value = '';
            if (nextHidden) nextHidden.value = '';
            return;
        }
        let nextIso = null;
        if (lastInput.value) {
            nextIso = addMonthsToDate(lastInput.value, intervalInput.value || 12);
        } else if (isCreate) {
            nextIso = new Date().toISOString().slice(0, 10);
        } else {
            // Bearbeiten ohne letzte Prüfung: Anlagedatum nicht im Formular — leer lassen,
            // Backend setzt next auf created_at.
            nextIso = null;
        }
        if (nextDisplay) nextDisplay.value = nextIso ? formatDeDate(nextIso) : '';
        if (nextHidden) nextHidden.value = nextIso || '';
    };

    window.__inventoryRefreshDguvNext = refresh;

    lastInput.addEventListener('change', refresh);
    lastInput.addEventListener('input', refresh);
    intervalInput.addEventListener('change', refresh);
    intervalInput.addEventListener('input', refresh);
    refresh();
}
