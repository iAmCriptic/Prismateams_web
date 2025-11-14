const InventoryFormManager = (() => {
    const state = {
        folders: [],
        categories: [],
        selectedFolderId: null,
        selectedCategory: null,
    };

    let folderSelect;
    let categorySelect;
    let entryModal;
    let entryModalInstance;
    let manageFoldersModalInstance;
    let manageCategoriesModalInstance;
    let entryForm;
    let entryTypeInput;
    let entryIdInput;
    let entryNameInput;
    let entryNameLabel;
    let entrySubmitBtn;
    let entryDeleteBtn;

    const routes = {
        folders: '/inventory/api/folders',
        categories: '/inventory/api/categories',
    };

    const sortByName = (items) => {
        return items.slice().sort((a, b) => {
            const nameA = (typeof a === 'string' ? a : a.name) || '';
            const nameB = (typeof b === 'string' ? b : b.name) || '';
            return nameA.localeCompare(nameB, 'de', { sensitivity: 'base' });
        });
    };

    const refreshFolderSelect = () => {
        if (!folderSelect) return;
        const currentValue = folderSelect.value;
        folderSelect.innerHTML = '';
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = 'Kein Ordner';
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
        const currentValue = categorySelect.value;
        categorySelect.innerHTML = '';
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = 'Keine Kategorie';
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
            li.className = 'list-group-item d-flex justify-content-between align-items-center';
            const name = typeof item === 'string' ? item : item.name;
            const id = typeof item === 'string' ? item : item.id;

            const nameSpan = document.createElement('span');
            nameSpan.textContent = name;
            li.appendChild(nameSpan);

            const btnGroup = document.createElement('div');
            btnGroup.className = 'btn-group btn-group-sm';

            const editBtn = document.createElement('button');
            editBtn.type = 'button';
            editBtn.className = 'btn btn-outline-secondary';
            editBtn.innerHTML = '<i class="bi bi-pencil"></i>';
            editBtn.title = 'Bearbeiten';
            editBtn.addEventListener('click', () => {
                openEntryModal({
                    type,
                    mode: 'edit',
                    id,
                    name,
                });
            });

            const deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.className = 'btn btn-outline-danger';
            deleteBtn.innerHTML = '<i class="bi bi-trash"></i>';
            deleteBtn.title = 'Löschen';
            deleteBtn.addEventListener('click', () => {
                handleDelete(type, type === 'folder' ? Number(id) : id, name);
            });

            btnGroup.appendChild(editBtn);
            btnGroup.appendChild(deleteBtn);
            li.appendChild(btnGroup);
            listEl.appendChild(li);
        });
    };

    const openEntryModal = ({ type, mode, id = null, name = '' }) => {
        if (!entryModalInstance) return;
        entryForm.dataset.mode = mode;
        entryTypeInput.value = type;
        entryIdInput.value = id !== null ? id : '';
        entryNameInput.value = name;
        entryNameLabel.textContent = type === 'folder' ? 'Ordnername' : 'Kategoriename';
        entryModalTitle.textContent = mode === 'create'
            ? (type === 'folder' ? 'Neuen Ordner anlegen' : 'Neue Kategorie anlegen')
            : (type === 'folder' ? 'Ordner bearbeiten' : 'Kategorie bearbeiten');
        entrySubmitBtn.textContent = mode === 'create' ? 'Anlegen' : 'Speichern';
        entryDeleteBtn.style.display = mode === 'edit' ? 'inline-flex' : 'none';
        entryDeleteBtn.dataset.entryId = id !== null ? id : '';
        entryDeleteBtn.dataset.entryType = type;
        entryDeleteBtn.dataset.entryName = name;
        entryModalInstance.show();
        setTimeout(() => entryNameInput.focus(), 200);
    };

    const requestCreateFolder = async (name) => {
        const response = await fetch(routes.folders, {
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
        const response = await fetch(`${routes.folders}/${id}`, {
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
        const response = await fetch(`${routes.folders}/${id}`, {
            method: 'DELETE',
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error || 'Ordner konnte nicht gelöscht werden.');
        }
        return response.json();
    };

    const requestCreateCategory = async (name) => {
        const response = await fetch(routes.categories, {
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
        const response = await fetch(`${routes.categories}/${encodeURIComponent(originalName)}`, {
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
        const response = await fetch(`${routes.categories}/${encodeURIComponent(name)}`, {
            method: 'DELETE',
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error || 'Kategorie konnte nicht gelöscht werden.');
        }
        return response.json();
    };

    const handleEntrySubmit = async (event) => {
        event.preventDefault();
        const mode = entryForm.dataset.mode;
        const type = entryTypeInput.value;
        const id = entryIdInput.value;
        const name = entryNameInput.value.trim();
        if (!name) {
            entryNameInput.focus();
            return;
        }

        try {
            if (type === 'folder') {
                if (mode === 'create') {
                    const created = await requestCreateFolder(name);
                    state.folders.push({ id: created.id, name: created.name });
                    state.selectedFolderId = created.id;
                } else {
                    const updated = await requestUpdateFolder(Number(id), name);
                    state.folders = state.folders.map(folder =>
                        folder.id === updated.id ? { id: updated.id, name: updated.name } : folder
                    );
                    if (state.selectedFolderId && String(state.selectedFolderId) === String(updated.id)) {
                        state.selectedFolderId = updated.id;
                    }
                }
                refreshFolderSelect();
                renderManageList('folder');
            } else {
                if (mode === 'create') {
                    await requestCreateCategory(name);
                    state.categories.push(name);
                    state.selectedCategory = name;
                } else {
                    const originalName = id;
                    await requestUpdateCategory(originalName, name);
                    state.categories = state.categories.map(cat => (cat === originalName ? name : cat));
                    if (state.selectedCategory === originalName) {
                        state.selectedCategory = name;
                    }
                }
                refreshCategorySelect();
                renderManageList('category');
            }
            entryModalInstance.hide();
        } catch (error) {
            console.error(error);
            alert(error.message || 'Aktion fehlgeschlagen.');
        }
    };

    const handleDelete = async (type, id, name) => {
        const confirmText = type === 'folder'
            ? `Sollen der Ordner "${name}" wirklich gelöscht werden?\nBereits zugewiesene Produkte verlieren dann ihren Ordner.`
            : `Soll die Kategorie "${name}" wirklich gelöscht werden?\nBereits zugewiesene Produkte verlieren dann ihre Kategorie.`;
        if (!confirm(confirmText)) {
            return;
        }
        try {
            if (type === 'folder') {
                await requestDeleteFolder(id);
                state.folders = state.folders.filter(folder => folder.id !== id);
                if (state.selectedFolderId && String(state.selectedFolderId) === String(id)) {
                    state.selectedFolderId = null;
                }
                refreshFolderSelect();
                renderManageList('folder');
            } else {
                await requestDeleteCategory(id);
                state.categories = state.categories.filter(cat => cat !== id);
                if (state.selectedCategory === id) {
                    state.selectedCategory = null;
                }
                refreshCategorySelect();
                renderManageList('category');
            }
        } catch (error) {
            console.error(error);
            alert(error.message || 'Löschen fehlgeschlagen.');
        }
    };

    const bindEvents = () => {
        const addFolderBtn = document.getElementById('addFolderBtn');
        if (addFolderBtn) {
            addFolderBtn.addEventListener('click', () => openEntryModal({ type: 'folder', mode: 'create' }));
        }

        const manageFoldersBtn = document.getElementById('manageFoldersBtn');
        if (manageFoldersBtn) {
            manageFoldersBtn.addEventListener('click', () => {
                renderManageList('folder');
                manageFoldersModalInstance.show();
            });
        }

        const modalCreateFolderBtn = document.getElementById('modalCreateFolderBtn');
        if (modalCreateFolderBtn) {
            modalCreateFolderBtn.addEventListener('click', () => {
                if (manageFoldersModalInstance) {
                    manageFoldersModalInstance.hide();
                }
                setTimeout(() => openEntryModal({ type: 'folder', mode: 'create' }), 150);
            });
        }

        const addCategoryBtn = document.getElementById('addCategoryBtn');
        if (addCategoryBtn) {
            addCategoryBtn.addEventListener('click', () => openEntryModal({ type: 'category', mode: 'create' }));
        }

        const manageCategoriesBtn = document.getElementById('manageCategoriesBtn');
        if (manageCategoriesBtn) {
            manageCategoriesBtn.addEventListener('click', () => {
                renderManageList('category');
                manageCategoriesModalInstance.show();
            });
        }

        const modalCreateCategoryBtn = document.getElementById('modalCreateCategoryBtn');
        if (modalCreateCategoryBtn) {
            modalCreateCategoryBtn.addEventListener('click', () => {
                if (manageCategoriesModalInstance) {
                    manageCategoriesModalInstance.hide();
                }
                setTimeout(() => openEntryModal({ type: 'category', mode: 'create' }), 150);
            });
        }

        if (entryForm) {
            entryForm.addEventListener('submit', handleEntrySubmit);
        }

        if (entryDeleteBtn) {
            entryDeleteBtn.addEventListener('click', () => {
                const type = entryTypeInput.value;
                const id = entryDeleteBtn.dataset.entryId;
                const name = entryDeleteBtn.dataset.entryName;
                entryModalInstance.hide();
                handleDelete(type, type === 'folder' ? Number(id) : id, name);
            });
        }

        if (folderSelect) {
            folderSelect.addEventListener('change', () => {
                state.selectedFolderId = folderSelect.value ? Number(folderSelect.value) : null;
            });
        }

        if (categorySelect) {
            categorySelect.addEventListener('change', () => {
                state.selectedCategory = categorySelect.value || null;
            });
        }
    };

    const initState = () => {
        if (!window.inventoryFormData) return;
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
        entryModal = document.getElementById('entryModal');
        entryForm = document.getElementById('entryForm');
        entryTypeInput = document.getElementById('entryType');
        entryIdInput = document.getElementById('entryId');
        entryNameInput = document.getElementById('entryName');
        entryNameLabel = document.getElementById('entryNameLabel');
        entrySubmitBtn = document.getElementById('entrySubmitBtn');
        entryDeleteBtn = document.getElementById('entryDeleteBtn');

        entryModalInstance = entryModal ? new bootstrap.Modal(entryModal) : null;
        const foldersModalEl = document.getElementById('manageFoldersModal');
        manageFoldersModalInstance = foldersModalEl ? new bootstrap.Modal(foldersModalEl) : null;
        const categoriesModalEl = document.getElementById('manageCategoriesModal');
        manageCategoriesModalInstance = categoriesModalEl ? new bootstrap.Modal(categoriesModalEl) : null;

        initState();
        refreshFolderSelect();
        refreshCategorySelect();
        bindEvents();
    };

    return { init };
})();

document.addEventListener('DOMContentLoaded', () => {
    if (typeof bootstrap === 'undefined') {
        console.error('Bootstrap ist nicht verfügbar.');
        return;
    }
    InventoryFormManager.init();
});
