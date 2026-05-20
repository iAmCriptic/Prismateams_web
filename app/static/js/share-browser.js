document.addEventListener('DOMContentLoaded', () => {
    const listViewBtn = document.getElementById('listViewBtn');
    const gridViewBtn = document.getElementById('gridViewBtn');
    const gridViewContainer = document.getElementById('gridViewContainer');
    const listViewContainer = document.getElementById('listViewContainer');
    const viewStorageKey = 'shareViewMode';

    function setView(mode) {
        if (!listViewBtn || !gridViewBtn || !gridViewContainer || !listViewContainer) {
            return;
        }
        if (mode === 'list') {
            listViewBtn.classList.add('active');
            gridViewBtn.classList.remove('active');
            listViewContainer.classList.remove('d-none');
            gridViewContainer.classList.add('d-none');
        } else {
            gridViewBtn.classList.add('active');
            listViewBtn.classList.remove('active');
            gridViewContainer.classList.remove('d-none');
            listViewContainer.classList.add('d-none');
        }
        window.localStorage.setItem(viewStorageKey, mode);
    }

    if (listViewBtn && gridViewBtn) {
        listViewBtn.addEventListener('click', () => setView('list'));
        gridViewBtn.addEventListener('click', () => setView('grid'));
        const savedMode = window.localStorage.getItem(viewStorageKey) || 'grid';
        setView(savedMode === 'list' ? 'list' : 'grid');
    }

    const newButtonDropdown = document.getElementById('newButtonDropdown');
    const newButton = document.getElementById('newButton');
    const newDropdownMenu = document.getElementById('newDropdownMenu');
    const uploadFileMenuItem = document.getElementById('uploadFileMenuItem');
    const uploadFolderMenuItem = document.getElementById('uploadFolderMenuItem');
    const createFolderMenuItem = document.getElementById('createFolderMenuItem');
    const directFileUpload = document.getElementById('directFileUpload');
    const directFolderUpload = document.getElementById('directFolderUpload');
    const shareUploadForm = document.getElementById('shareUploadForm');
    const shareCreateFolderForm = document.getElementById('shareCreateFolderForm');
    const shareCreateFolderName = document.getElementById('shareCreateFolderName');

    function closeNewMenu() {
        if (newDropdownMenu) {
            newDropdownMenu.classList.remove('show');
        }
    }

    if (newButton && newDropdownMenu) {
        newButton.addEventListener('click', (event) => {
            event.preventDefault();
            newDropdownMenu.classList.toggle('show');
        });

        document.addEventListener('click', (event) => {
            if (!newButtonDropdown || !newButtonDropdown.contains(event.target)) {
                closeNewMenu();
            }
        });
    }

    if (uploadFileMenuItem && directFileUpload) {
        uploadFileMenuItem.addEventListener('click', (event) => {
            event.preventDefault();
            closeNewMenu();
            directFileUpload.click();
        });
    }

    if (uploadFolderMenuItem && directFolderUpload) {
        uploadFolderMenuItem.addEventListener('click', (event) => {
            event.preventDefault();
            closeNewMenu();
            directFolderUpload.click();
        });
    }

    if (directFileUpload && shareUploadForm) {
        directFileUpload.addEventListener('change', () => {
            if (directFileUpload.files && directFileUpload.files.length > 0) {
                shareUploadForm.submit();
            }
        });
    }

    if (directFolderUpload && shareUploadForm) {
        directFolderUpload.addEventListener('change', () => {
            if (directFolderUpload.files && directFolderUpload.files.length > 0) {
                shareUploadForm.submit();
            }
        });
    }

    if (createFolderMenuItem && shareCreateFolderForm && shareCreateFolderName) {
        createFolderMenuItem.addEventListener('click', (event) => {
            event.preventDefault();
            closeNewMenu();
            const folderName = window.prompt('Ordnername eingeben');
            if (!folderName) {
                return;
            }
            shareCreateFolderName.value = folderName.trim();
            if (!shareCreateFolderName.value) {
                return;
            }
            shareCreateFolderForm.submit();
        });
    }
});
