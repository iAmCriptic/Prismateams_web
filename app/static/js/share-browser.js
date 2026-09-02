document.addEventListener('DOMContentLoaded', () => {
    if (typeof window.initFilesViewToggle === 'function') {
        window.initFilesViewToggle({
            toggleEl: document.querySelector('.files-ext-toolbar .files-view-toggle'),
            listBtn: document.getElementById('listViewBtn'),
            gridBtn: document.getElementById('gridViewBtn'),
            listPane: document.getElementById('listViewContainer'),
            gridPane: document.getElementById('gridViewContainer'),
            stageEl: document.getElementById('shareViewStage'),
            storageKey: 'shareViewMode',
            defaultMode: 'grid',
        });
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
        createFolderMenuItem.addEventListener('click', async (event) => {
            event.preventDefault();
            closeNewMenu();
            const folderName = typeof window.ptPrompt === 'function'
                ? await window.ptPrompt('Ordnername eingeben', { title: 'Neuer Ordner', confirmLabel: 'Erstellen' })
                : window.prompt('Ordnername eingeben');
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
